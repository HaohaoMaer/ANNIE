"""Concrete semantic town world engine."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal, Protocol

import chromadb
from chromadb.api import ClientAPI

from annie.npc.context import AgentContext
from annie.npc.graph_registry import AgentGraphID
from annie.npc.memory.interface import MemoryInterface
from annie.npc.response import ActionRequest, ActionResult, AgentResponse
from annie.npc.routes import AgentRoute
from annie.npc.tools.base_tool import ToolDef
from annie.world_engine.base import WorldEngine
from annie.world_engine.history import HistoryStore
from annie.world_engine.memory import DefaultMemoryInterface
from annie.world_engine.tools import PlanTodoTool, render_todo_text
from annie.town.domain import (
    ConversationSession,
    ConversationTurn,
    CurrentAction,
    Location,
    MoveResult,
    ReflectionEvidence,
    ResidentDayPlan,
    ScheduleRevision,
    ScheduleSegment,
    SemanticAffordance,
    TownEvent,
    TownObject,
    TownPerceptionPolicy,
    TownState,
)
from annie.town.prompt_policy import (
    render_conversation_policy_hint,
    render_object_selection_hint,
    render_repeat_guard_hint,
    render_schedule_decision_hint,
    render_wait_decision_hint,
    schedule_evidence,
    schedule_progress_summary,
    default_subtasks_for,
)
from annie.town.eventing import NPCRegistry, TownEventBus
from annie.town.tools import (
    FinishScheduleSegmentTool,
    InspectAffordancesTool,
    InteractWithTool,
    MoveToTool,
    ObserveTool,
    SpeakToTool,
    StartConversationTool,
    UseAffordanceTool,
    WaitTool,
)

_DEFAULT_TOWN_VECTOR_STORE = Path("./data/town/vector_store")
_DEFAULT_TOWN_HISTORY_DIR = Path("./data/town/history")
MAX_TOWN_HISTORY_TURNS = 20
DEFAULT_MOVE_MINUTES = 5
DEFAULT_FAILED_ACTION_MINUTES = 1
DEFAULT_OBSERVE_MINUTES = 1
DEFAULT_INTERACT_MINUTES = 5
MAX_SPEAK_MINUTES = 5
SPEAK_CHARS_PER_MINUTE = 50
DEFAULT_SPEAK_COOLDOWN_MINUTES = 10
DEFAULT_CHAT_ITER = 4
DEFAULT_CONVERSATION_COOLDOWN_MINUTES = 60
MAX_CONVERSATION_MINUTES = 10
CONVERSATION_CHARS_PER_MINUTE = 240
SIGNIFICANT_EVENT_TYPES = {"urgent", "emergency", "alarm"}
SCHEDULE_REVISION_MINUTES = 15
DEFAULT_REFLECTION_THRESHOLD = 6
DEFAULT_DAY_START_MINUTE = 8 * 60
DEFAULT_DAY_END_MINUTE = 18 * 60
LOOP_GUARD_WINDOW = 6
TOWN_ACTION_TOOL_NAMES = [
    "declare_action",
    "request_action",
    "memory_store",
    "plan_todo",
    "move_to",
    "observe",
    "speak_to",
    "start_conversation",
    "interact_with",
    "inspect_affordances",
    "use_affordance",
    "wait",
    "finish_schedule_segment",
]


class TownAgent(Protocol):
    def run(self, context: AgentContext) -> AgentResponse:
        ...


class TownWorldEngine(WorldEngine):
    """Minimal concrete engine backed by world-owned TownState."""

    def __init__(
        self,
        state: TownState,
        memories: dict[str, MemoryInterface] | None = None,
        *,
        chroma_client: ClientAPI | None = None,
        memory_path: str | Path | None = None,
        history_dir: str | Path | None = None,
        perception_policy: TownPerceptionPolicy | None = None,
    ) -> None:
        self.state = state
        self._client = chroma_client or chromadb.PersistentClient(
            path=str(Path(memory_path) if memory_path else _DEFAULT_TOWN_VECTOR_STORE)
        )
        self._memories = memories or {}
        self._histories: dict[str, HistoryStore] = {}
        self._history_dir = Path(history_dir) if history_dir else _DEFAULT_TOWN_HISTORY_DIR
        self.action_log: list[dict[str, object]] = []
        self.replay_log: list[dict[str, object]] = []
        self.reflection_log: list[dict[str, object]] = []
        self.npc_registry = NPCRegistry.from_state(state)
        self.event_bus = TownEventBus()
        self._inboxes = self.event_bus.inboxes
        self._seen_event_ids = self.event_bus.seen_event_ids
        self._visible_event_count_limit: int | None = None
        self.perception_policy = perception_policy or TownPerceptionPolicy()
        self._active_step_agent: TownAgent | None = None
        self.chat_iter = DEFAULT_CHAT_ITER
        self.conversation_cooldown_minutes = DEFAULT_CONVERSATION_COOLDOWN_MINUTES
        self.speak_cooldown_minutes = DEFAULT_SPEAK_COOLDOWN_MINUTES
        self.reflection_threshold = DEFAULT_REFLECTION_THRESHOLD
        self._speak_cooldowns: dict[tuple[str, str], int] = {}
        self._schedule_revisions: dict[tuple[str, str], ScheduleRevision] = {}
        self._latest_schedule_revision_by_npc: dict[str, ScheduleRevision] = {}
        self.planning_log: list[dict[str, object]] = []
        self.loop_guard_events: list[dict[str, object]] = []
        self._loop_guard_keys: set[tuple[object, ...]] = set()

    def plan_day_for_resident(
        self,
        npc_id: str,
        schedule: list[ScheduleSegment],
        *,
        day: int | None = None,
        planning_evidence: list[dict[str, object]] | None = None,
        validation: dict[str, object] | None = None,
        repair_invalid: bool = False,
    ) -> list[ScheduleSegment]:
        """Accept a deterministic resident-generated daily schedule."""
        if npc_id not in self.state.residents:
            raise ValueError("unknown_resident")
        schedule_day = self.state.clock.day if day is None else day

        if repair_invalid:
            accepted_schedule, validation_result = self._validate_and_repair_schedule(
                npc_id,
                schedule,
                day=schedule_day,
                start_minute=0,
                end_minute=24 * 60,
            )
        else:
            self._assert_schedule_valid(npc_id, schedule)
            accepted_schedule = sorted(schedule, key=lambda segment: segment.start_minute)
            for segment in accepted_schedule:
                segment.day = schedule_day
            validation_result = {
                "ok": True,
                "warnings": [],
                "segment_count": len(accepted_schedule),
            }
        if validation is not None:
            validation_result = {**validation_result, **validation}

        self.state.set_schedule(npc_id, accepted_schedule, day=schedule_day)
        resident = self.state.residents[npc_id]
        day_plan = resident.day_plans.setdefault(schedule_day, ResidentDayPlan(day=schedule_day))
        day_plan.planning_evidence = list(planning_evidence or day_plan.planning_evidence)
        day_plan.validation = validation_result
        day_plan.schedule_summary = _schedule_summary(accepted_schedule)
        self._record_planning_checkpoint(
            npc_id,
            day=schedule_day,
            stage="accepted_schedule",
            payload={
                "schedule": [_full_schedule_dict(segment) for segment in accepted_schedule],
                "evidence": list(planning_evidence or []),
                "validation": validation_result,
            },
        )
        return accepted_schedule

    def start_day_for_resident(
        self,
        npc_id: str,
        *,
        day: int | None = None,
        start_minute: int = DEFAULT_DAY_START_MINUTE,
        end_minute: int = DEFAULT_DAY_END_MINUTE,
    ) -> list[ScheduleSegment]:
        """Run the minimal deterministic day-start lifecycle for one resident."""
        if npc_id not in self.state.residents:
            raise ValueError("unknown_resident")
        schedule_day = self.state.clock.day if day is None else day
        self.state.clock.day = schedule_day
        self.state.clock.minute = start_minute
        self.state.clear_current_action(npc_id)
        resident = self.state.residents[npc_id]
        day_plan = resident.day_plans.setdefault(schedule_day, ResidentDayPlan(day=schedule_day))
        day_plan.started_minute = start_minute

        evidence = self.retrieve_planning_evidence(npc_id)
        day_plan.planning_evidence = evidence
        currently = self.update_currently_for_resident(npc_id, evidence)
        wake_up = self.plan_wake_up_for_resident(npc_id, start_minute=start_minute)
        intentions = self.plan_daily_intentions_for_resident(npc_id, evidence)
        candidate = self.plan_schedule_segments_for_resident(
            npc_id,
            intentions,
            start_minute=max(start_minute, wake_up),
            end_minute=end_minute,
        )
        accepted, validation = self._validate_and_repair_schedule(
            npc_id,
            candidate,
            day=schedule_day,
            start_minute=start_minute,
            end_minute=end_minute,
        )
        day_plan.currently = currently
        day_plan.wake_up_minute = wake_up
        day_plan.daily_intentions = intentions
        return self.plan_day_for_resident(
            npc_id,
            accepted,
            day=schedule_day,
            planning_evidence=evidence,
            validation=validation,
            repair_invalid=True,
        )

    def start_day_for_residents(
        self,
        npc_ids: list[str] | None = None,
        *,
        day: int | None = None,
        start_minute: int = DEFAULT_DAY_START_MINUTE,
        end_minute: int = DEFAULT_DAY_END_MINUTE,
    ) -> dict[str, list[ScheduleSegment]]:
        active_npcs = list(npc_ids) if npc_ids is not None else self.state.resident_ids()
        return {
            npc_id: self.start_day_for_resident(
                npc_id,
                day=day,
                start_minute=start_minute,
                end_minute=end_minute,
            )
            for npc_id in active_npcs
        }

    def end_day_for_resident(
        self,
        npc_id: str,
        *,
        day: int | None = None,
    ) -> str:
        """Summarize the resident's day and persist distilled planning memory."""
        if npc_id not in self.state.residents:
            raise ValueError("unknown_resident")
        schedule_day = self.state.clock.day if day is None else day
        resident = self.state.residents[npc_id]
        day_plan = resident.day_plans.setdefault(schedule_day, ResidentDayPlan(day=schedule_day))
        schedule = [
            segment
            for segment in resident.schedule
            if (schedule_day if segment.day is None else segment.day) == schedule_day
        ]
        completed = [
            item
            for item in self.state.completed_schedule_segments.get(npc_id, [])
            if (schedule_day if item.day is None else item.day) == schedule_day
        ]
        summary = (
            f"第 {schedule_day} 天：{npc_id} 计划 {len(schedule)} 段，"
            f"完成 {len(completed)} 段。{_schedule_summary(schedule)}"
        )
        day_plan.day_summary = summary
        day_plan.ended_minute = self.state.clock.minute
        self.memory_for(npc_id).remember(
            summary,
            category="impression",
            metadata={
                "source": "town_day_summary",
                "day": schedule_day,
                "npc_id": npc_id,
                "completed_count": len(completed),
                "schedule_count": len(schedule),
            },
        )
        self._record_planning_checkpoint(
            npc_id,
            day=schedule_day,
            stage="day_end_summary",
            payload={"summary": summary},
        )
        return summary

    def end_day_for_residents(
        self,
        npc_ids: list[str] | None = None,
        *,
        day: int | None = None,
    ) -> dict[str, str]:
        active_npcs = list(npc_ids) if npc_ids is not None else self.state.resident_ids()
        return {
            npc_id: self.end_day_for_resident(npc_id, day=day)
            for npc_id in active_npcs
        }

    def retrieve_planning_evidence(self, npc_id: str) -> list[dict[str, object]]:
        memory = self.memory_for(npc_id)
        records = []
        records.extend(memory.grep("", category="impression", k=8))
        records.extend(memory.grep("", category="reflection", k=6))
        records.extend(memory.grep("", category="todo", k=6))
        records.extend(
            memory.recall(
                "小镇日程 计划 反思 对话 关系 未完成事项 跟进",
                categories=["impression", "reflection", "todo"],
                k=6,
            )
        )
        seen: set[tuple[str, str]] = set()
        evidence: list[dict[str, object]] = []
        for record in records:
            key = (record.category, record.content)
            if key in seen:
                continue
            seen.add(key)
            evidence.append(
                {
                    "category": record.category,
                    "content": record.content,
                    "metadata": dict(record.metadata),
                }
            )
            if len(evidence) >= 8:
                break
        return evidence

    def relationship_planning_evidence(self, npc_id: str) -> list[dict[str, object]]:
        """Return pairwise conversation evidence that may affect future plans."""
        rows: list[dict[str, object]] = []
        for record in self.memory_for(npc_id).grep(
            "",
            category="impression",
            metadata_filters={"source": "town_conversation"},
            k=6,
        ):
            rows.append(
                {
                    "partner_npc_id": record.metadata.get("partner_npc_id"),
                    "conversation_session_id": record.metadata.get("conversation_session_id"),
                    "topic_or_reason": record.metadata.get("topic_or_reason"),
                    "relationship_pair_key": record.metadata.get("relationship_pair_key"),
                    "relationship_summary": record.metadata.get("relationship_summary"),
                    "unresolved_topics": _split_metadata_list(
                        record.metadata.get("unresolved_topics")
                    ),
                    "follow_up_intentions": _split_metadata_list(
                        record.metadata.get("follow_up_intentions")
                    ),
                    "content": record.content,
                }
            )
        return rows

    def update_currently_for_resident(
        self,
        npc_id: str,
        evidence: list[dict[str, object]] | None = None,
    ) -> str:
        resident = self.state.residents[npc_id]
        location_id = self.state.location_id_for(npc_id) or "unknown"
        evidence_bits = [str(item.get("content", "")) for item in (evidence or [])[:2]]
        suffix = "；参考：" + " / ".join(evidence_bits) if evidence_bits else ""
        resident.scratch.currently = (
            f"{npc_id} 在第 {self.state.clock.day} 天从 {location_id} 开始一天。{suffix}"
        )
        self._record_planning_checkpoint(
            npc_id,
            day=self.state.clock.day,
            stage="currently",
            payload={"currently": resident.scratch.currently, "evidence": evidence or []},
        )
        return resident.scratch.currently

    def plan_wake_up_for_resident(self, npc_id: str, *, start_minute: int) -> int:
        wake_up = start_minute
        self._record_planning_checkpoint(
            npc_id,
            day=self.state.clock.day,
            stage="wake_up",
            payload={"wake_up_minute": wake_up, "wake_up_time": _minute_label(wake_up)},
        )
        return wake_up

    def plan_daily_intentions_for_resident(
        self,
        npc_id: str,
        evidence: list[dict[str, object]] | None = None,
    ) -> list[str]:
        fixture = self.state.schedule_for(npc_id)
        intentions = [segment.intent for segment in fixture[:3]]
        if not intentions:
            intentions = ["查看小镇公告", "整理当天事项"]
        influence = _planning_influence_intentions(evidence or [])
        if influence:
            intentions = influence + intentions
        if evidence:
            intentions.append("回顾昨日事项并调整安排")
        self._record_planning_checkpoint(
            npc_id,
            day=self.state.clock.day,
            stage="daily_intentions",
            payload={"intentions": intentions, "influence": influence},
        )
        return intentions

    def plan_schedule_segments_for_resident(
        self,
        npc_id: str,
        intentions: list[str],
        *,
        start_minute: int,
        end_minute: int,
    ) -> list[ScheduleSegment]:
        fixture = self.state.schedule_for(npc_id)
        known_locations = [
            segment.location_id
            for segment in fixture
            if segment.location_id in self.state.locations
        ]
        if not known_locations:
            known_locations = [self.state.location_id_for(npc_id) or next(iter(self.state.locations))]
        duration = max(15, min(60, (end_minute - start_minute) // max(1, len(intentions))))
        minute = start_minute
        segments: list[ScheduleSegment] = []
        for index, intent in enumerate(intentions):
            if minute >= end_minute:
                break
            location_id = known_locations[min(index, len(known_locations) - 1)]
            segments.append(
                ScheduleSegment(
                    npc_id=npc_id,
                    start_minute=minute,
                    duration_minutes=min(duration, end_minute - minute),
                    location_id=location_id,
                    intent=intent,
                    subtasks=[],
                    day=self.state.clock.day,
                )
            )
            minute += duration
        self._record_planning_checkpoint(
            npc_id,
            day=self.state.clock.day,
            stage="schedule_segments",
            payload={"schedule": [_full_schedule_dict(segment) for segment in segments]},
        )
        return segments

    def build_daily_planning_context(
        self,
        npc_id: str,
        *,
        start_minute: int,
        end_minute: int,
    ) -> AgentContext:
        """Build a tool-free resident planning context for NPCAgent."""
        if npc_id not in self.state.residents:
            raise ValueError("unknown_resident")

        memory = self.memory_for(npc_id)
        planning_evidence = self.retrieve_planning_evidence(npc_id)
        relationship_evidence = self.relationship_planning_evidence(npc_id)
        current_location_id = self.state.location_id_for(npc_id)
        current_location = self.state.locations.get(current_location_id or "")
        fixture_schedule = self.state.schedule_for(npc_id)
        location_rows = []
        for location in self.state.locations.values():
            objects = [
                self.state.objects[obj_id]
                for obj_id in location.object_ids
                if obj_id in self.state.objects
            ]
            location_rows.append(
                {
                    "id": location.id,
                    "name": location.name,
                    "description": location.description,
                    "exits": list(location.exits),
                    "exit_travel_minutes": {
                        exit_id: location.exit_travel_minutes.get(exit_id, DEFAULT_MOVE_MINUTES)
                        for exit_id in location.exits
                    },
                    "objects": [
                        {
                            "id": obj.id,
                            "name": obj.name,
                            "description": obj.description,
                            "interactable": obj.interactable,
                        }
                        for obj in objects
                    ],
                }
            )

        planning_payload = {
            "npc_id": npc_id,
            "current_location_id": current_location_id,
            "current_location_name": current_location.name if current_location else None,
            "planning_window": {
                "start_minute": start_minute,
                "end_minute": end_minute,
                "start_label": _minute_label(start_minute),
                "end_label": _minute_label(end_minute),
            },
            "existing_fixture_schedule": [
                _full_schedule_dict(segment) for segment in fixture_schedule
            ],
            "planning_evidence": planning_evidence,
            "relationship_evidence": relationship_evidence,
            "known_locations": location_rows,
            "output_schema": {
                "schedule": [
                    {
                        "npc_id": npc_id,
                        "start_minute": start_minute,
                        "duration_minutes": 30,
                        "location_id": "town_square",
                        "intent": "查看公告板",
                    }
                ]
            },
        }
        situation = "\n".join(
            [
                "你正在为 TownWorld resident 生成一天中的语义日程。",
                f"居民 id：{npc_id}",
                f"当前位置：{current_location_id or 'unknown'}",
                f"规划窗口：{_minute_label(start_minute)}-{_minute_label(end_minute)}",
                "当前 fixture schedule：",
                json.dumps(
                    planning_payload["existing_fixture_schedule"],
                    ensure_ascii=False,
                    indent=2,
                ),
                "可用于改变今日计划的记忆、反思、todo：",
                _render_planning_evidence(planning_evidence),
                "可用于改变今日计划的关系/对话证据：",
                _render_relationship_planning_evidence(relationship_evidence),
                "可用地点、出口、物体：",
                json.dumps(location_rows, ensure_ascii=False, indent=2),
                "输出必须是一个 JSON object，格式固定为：",
                json.dumps(planning_payload["output_schema"], ensure_ascii=False),
                "硬性约束：所有日程必须位于规划窗口内，start_minute >= "
                f"{start_minute}，end_minute <= {end_minute}。"
                f"至少一个日程段必须从 {start_minute} 开始或覆盖 {_minute_label(start_minute)}。"
                "第一段日程必须从 current_location_id 和可达出口出发安排；"
                "如果第一段不在当前位置，必须预留足够 travel minutes。"
                "fixture 只作为 fallback/reference，不要忽略当前地点和移动约束。"
                "如果 fixture 已填满窗口，也要在窗口内提出替代日程，不要安排到窗口之后。",
                "只输出 JSON，不输出 markdown，不调用工具。",
            ]
        )
        return AgentContext(
            npc_id=npc_id,
            input_event="生成 resident daily schedule JSON。",
            tools=[],
            memory=memory,
            graph_id=AgentGraphID.OUTPUT_STRUCTURED_JSON,
            route=AgentRoute.STRUCTURED_JSON,
            world_rules=(
                "你只负责提出候选日程。TownWorldEngine 会校验地点、归属、"
                "时间重叠并持久化 accepted schedule。"
                "planning 阶段不得移动 NPC，不得写世界动作，不得调用小镇 action tools。"
                "每个日程项必须属于当前 npc_id，location_id 必须来自 known_locations。"
                "日程项必须包含 npc_id、start_minute、duration_minutes、location_id、intent。"
                "所有日程项必须落在规划窗口内，且不要输出规划窗口之后的安排。"
                "如果 planning_evidence 或 relationship_evidence 包含未解决话题、"
                "跟进意图或重要反思，应在时间允许时把它们转化为具体日程意图。"
            ),
            situation=situation,
            extra={
                "disabled_tools": [
                    "declare_action",
                    "request_action",
                    "memory_store",
                    "plan_todo",
                    "move_to",
                    "observe",
                    "speak_to",
                    "start_conversation",
                    "interact_with",
                    "wait",
                    "finish_schedule_segment",
                ],
                "town": {
                    "planning": True,
                    **planning_payload,
                },
            },
        )

    def generate_day_plan_for_resident(
        self,
        npc_id: str,
        agent: TownAgent,
        *,
        start_minute: int,
        end_minute: int,
    ) -> list[ScheduleSegment]:
        """Ask a stateless NPCAgent-compatible backend for a resident daily plan."""
        fallback_schedule = list(self.state.schedule_for(npc_id))
        context = self.build_daily_planning_context(
            npc_id,
            start_minute=start_minute,
            end_minute=end_minute,
        )
        response = agent.run(context)
        schedule = _schedule_from_agent_response(response)
        for segment in schedule:
            if segment.npc_id != npc_id:
                raise ValueError("schedule_npc_mismatch")
            if segment.location_id not in self.state.locations:
                raise ValueError("unknown_schedule_location")
        schedule = _schedule_within_planning_window(
            npc_id=npc_id,
            schedule=schedule,
            fallback_schedule=fallback_schedule,
            start_minute=start_minute,
            end_minute=end_minute,
        )
        self._assert_schedule_valid(npc_id, schedule)
        accepted, validation = self._validate_and_repair_schedule(
            npc_id,
            schedule,
            day=self.state.clock.day,
            start_minute=start_minute,
            end_minute=end_minute,
        )
        planning_evidence = context.extra.get("town", {}).get("planning_evidence", [])
        return self.plan_day_for_resident(
            npc_id,
            accepted,
            planning_evidence=(
                planning_evidence if isinstance(planning_evidence, list) else []
            ),
            validation=validation,
        )

    def reflection_due_for(self, npc_id: str) -> bool:
        resident = self.state.resident_for(npc_id)
        return (
            resident is not None
            and resident.poignancy >= self.reflection_threshold
            and bool(resident.reflection_evidence)
        )

    def build_reflection_context(self, npc_id: str) -> AgentContext:
        resident = self.state.resident_for(npc_id)
        if resident is None:
            raise ValueError("unknown_resident")

        evidence_rows = [_reflection_evidence_dict(item) for item in resident.reflection_evidence]
        evidence_text = _render_reflection_evidence(resident.reflection_evidence)
        situation = "\n".join(
            [
                "你正在为 TownWorld resident 生成 distilled reflection。",
                f"居民 id：{npc_id}",
                f"当前时间：{self.state.clock.label()}",
                f"累计重要性：{resident.poignancy} / {self.reflection_threshold}",
                "证据摘要：",
                evidence_text,
                "请只基于这些小镇证据生成简洁反思，避免复述原始对话逐字内容。",
            ]
        )
        return AgentContext(
            npc_id=npc_id,
            input_event="基于小镇证据生成 distilled reflection。",
            tools=[],
            memory=self.memory_for(npc_id),
            graph_id=AgentGraphID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE,
            route=AgentRoute.REFLECTION,
            world_rules=(
                "反思阶段不得调用小镇 action tools，不得移动 NPC，不得写世界动作。"
                "输出应是可存入长期记忆的概括性 reflection。"
                "必须过滤系统元信息、工具名、函数名、内部流程和 JSON 字段名。"
                "使用中文输出。"
            ),
            situation=situation,
            extra={
                "disabled_tools": list(TOWN_ACTION_TOOL_NAMES),
                "town": {
                    "reflection": {
                        "poignancy": resident.poignancy,
                        "threshold": self.reflection_threshold,
                        "evidence": evidence_rows,
                    }
                },
            },
        )

    def reflect_for_resident(self, npc_id: str, agent: TownAgent) -> bool:
        resident = self.state.resident_for(npc_id)
        if resident is None:
            raise ValueError("unknown_resident")
        if not self.reflection_due_for(npc_id):
            return False

        response = agent.run(self.build_reflection_context(npc_id))
        reflection = (
            response.reflection.strip()
            or response.dialogue.strip()
            or response.inner_thought.strip()
        )
        if not reflection:
            return False

        evidence = list(resident.reflection_evidence)
        self.memory_for(npc_id).remember(
            reflection,
            category="reflection",
            metadata={
                "source": "town_reflection",
                "clock_minute": self.state.clock.minute,
                "trigger_poignancy": resident.poignancy,
                "evidence_ids": [item.id for item in evidence],
                "evidence_types": sorted({item.evidence_type for item in evidence}),
                "evidence_count": len(evidence),
            },
        )
        self.reflection_log.append(
            {
                "tick": None,
                "npc_id": npc_id,
                "minute": self.state.clock.minute,
                "time": self.state.clock.label(),
                "content": reflection,
                "trigger_poignancy": resident.poignancy,
                "evidence_ids": [item.id for item in evidence],
                "evidence_types": sorted({item.evidence_type for item in evidence}),
                "evidence_count": len(evidence),
            }
        )
        resident.reflection_evidence.clear()
        resident.poignancy = 0
        return True

    def build_replay_snapshot(
        self,
        npc_ids: list[str] | None = None,
        *,
        minute: int | None = None,
        reflection_events: list[dict[str, object]] | None = None,
    ) -> dict[str, object]:
        """Build a stable structured checkpoint snapshot for replay inspection."""
        snapshot_minute = self.state.clock.minute if minute is None else minute
        active_npcs = list(npc_ids) if npc_ids is not None else self.state.resident_ids()
        return {
            "day": self.state.clock.day,
            "minute": snapshot_minute,
            "time": _minute_label(snapshot_minute),
            "planning_checkpoints": list(self.planning_log),
            "loop_guard_events": list(self.loop_guard_events),
            "residents": {
                npc_id: self._resident_snapshot(npc_id, minute=snapshot_minute)
                for npc_id in active_npcs
                if self.state.resident_for(npc_id) is not None
            },
            "conversation_sessions": [
                self._conversation_session_snapshot(session)
                for session in sorted(
                    self.state.conversation_sessions.values(),
                    key=lambda item: item.id,
                )
            ],
            "reflection_events": list(reflection_events or []),
        }

    def build_context(self, npc_id: str, event: str) -> AgentContext:
        location = self.state.location_for(npc_id)
        if location is None:
            situation = "当前小镇状态：这个 NPC 尚未被放置到小镇中。"
            extra = {
                "disabled_tools": ["declare_action", "request_action", "memory_store"],
                "town": {"known": False},
            }
        else:
            perception: dict[str, Any] = self.build_perception(npc_id)
            schedule_revision = self._revise_schedule_from_perception(npc_id, perception)
            objects = [
                self.state.objects[obj_id]
                for obj_id in perception["object_ids"]
                if obj_id in self.state.objects
            ]
            occupants = list(perception["visible_npc_ids"])
            schedule = self.state.current_schedule_segment(npc_id)
            if schedule is not None and not schedule.subtasks:
                self.decompose_current_schedule_segment(npc_id)
                schedule = self.state.current_schedule_segment(npc_id)
            selected_event_ids = list(perception["visible_event_ids"])
            events_by_id = {event.id: event for event in self._local_event_candidates(npc_id)}
            local_events = [
                events_by_id[event_id]
                for event_id in selected_event_ids
                if event_id in events_by_id
            ]
            pending_events = list(self._inboxes.get(npc_id, []))
            visible_actions = {
                other: self._current_action_dict(other)
                for other in occupants
                if self.state.current_action_for(other) is not None
            }
            active_session = self.state.active_conversation_for(npc_id)
            recent_chats = self._recent_conversation_summaries(npc_id)
            relationship_cues = self.relationship_cues_for(npc_id, occupants)
            own_action = self.state.current_action_for(npc_id)
            schedule_remaining_minutes = (
                max(0, schedule.end_minute - self.state.clock.minute)
                if schedule is not None
                else None
            )
            schedule_progress = self._schedule_progress_summary(npc_id, schedule)
            schedule_completion_hint = self._schedule_completion_hint(
                npc_id,
                schedule,
                schedule_progress,
            )
            schedule_decision_hint = render_schedule_decision_hint(
                schedule=schedule,
                clock_minute=self.state.clock.minute,
                stride_minutes=self.state.clock.stride_minutes,
                progress_summary=schedule_progress,
                evidence=schedule_evidence(
                    npc_id=npc_id,
                    schedule=schedule,
                    action_log=self.action_log,
                ),
                is_complete=(
                    self.state.is_schedule_segment_complete(npc_id, schedule)
                    if schedule is not None
                    else False
                ),
            )
            object_selection_hint = render_object_selection_hint(
                schedule=schedule,
                location=location,
                objects=objects,
            )
            wait_decision_hint = render_wait_decision_hint(
                visible_actions=visible_actions,
                own_action=own_action,
            )
            conversation_policy_hint = render_conversation_policy_hint(
                active_session_id=active_session.id if active_session is not None else None,
                visible_npc_ids=occupants,
                recent_chats=recent_chats,
                relationship_cues=relationship_cues,
            )
            repeat_guard_hint = render_repeat_guard_hint(
                npc_id=npc_id,
                action_log=self.action_log,
            )
            recent_loop_guards = self._recent_loop_guard_events(npc_id)
            if recent_loop_guards:
                repeat_guard_hint += " 最近 guard：" + "; ".join(
                    str(event.get("message", event.get("guard_type", "")))
                    for event in recent_loop_guards[-3:]
                )
            target_text = (
                f"{schedule.location_id}，目标：{schedule.intent}"
                if schedule is not None
                else "无"
            )
            situation = "\n".join(
                [
                    f"当前时间：{self.state.clock.label()}",
                    f"全局模拟每 tick 推进 {self.state.clock.stride_minutes} 分钟。",
                    f"当前位置：{location.name} ({location.id})",
                    f"地点描述：{location.description}",
                    f"当前日程目标：{target_text}",
                    "当前日程剩余时间："
                    + (
                        f"{schedule_remaining_minutes} 分钟"
                        if schedule_remaining_minutes is not None
                        else "无"
                    ),
                    "可达出口及移动耗时："
                    + (
                        ", ".join(
                            f"{exit_id}: {location.exit_travel_minutes.get(exit_id, DEFAULT_MOVE_MINUTES)} 分钟"
                            for exit_id in perception["exits"]
                        )
                        if perception["exits"]
                        else "无"
                    ),
                    f"可见 NPC：{', '.join(occupants) if occupants else '无'}",
                    "可见物体："
                    + (
                        ", ".join(
                            f"{obj.name} ({obj.id})：{obj.description}"
                            f"；affordances={_render_affordance_refs(obj.affordances)}"
                            for obj in objects
                        )
                        if objects
                        else "无"
                    ),
                    "当前位置 affordances："
                    + _render_affordance_refs(location.affordances),
                    "本地事件："
                    + (
                        "; ".join(event.summary for event in local_events)
                        if local_events
                        else "无"
                    ),
                    "待处理事件："
                    + (
                        "; ".join(event.summary for event in pending_events)
                        if pending_events
                        else "无"
                    ),
                    "可见 NPC 当前行动："
                    + (
                        "; ".join(
                            f"{other}: {action['action_type']} 从 {action['start_time']} "
                            f"到 {action['end_time']}，耗时 {action['duration_minutes']} 分钟"
                            for other, action in visible_actions.items()
                        )
                        if visible_actions
                        else "无"
                    ),
                    "我的当前行动状态："
                    + (
                        f"{own_action.action_type} 从 {_minute_label(own_action.start_minute)} "
                        f"到 {_minute_label(own_action.end_minute)}，"
                        f"耗时 {own_action.duration_minutes} 分钟，状态={own_action.status}"
                        if own_action is not None
                        else "无"
                    ),
                    "当前会话："
                    + (
                        f"{active_session.id}，参与者={', '.join(active_session.participants)}"
                        if active_session is not None
                        else "无"
                    ),
                    "最近对话："
                    + ("; ".join(recent_chats) if recent_chats else "无"),
                    "关系线索：" + _render_relationship_cues(relationship_cues),
                    "已知但当前不可见地点："
                    + _render_known_locations(perception["known_locations"]),
                    "已知但当前不可见物体："
                    + _render_known_objects(perception["known_objects"]),
                    "当前日程：" + _render_schedule(schedule),
                    "当前日程已完成行动：" + schedule_progress,
                    "日程完成判断：" + schedule_completion_hint,
                    "当前活动决策提示：",
                    "- 日程拆解与完成：" + schedule_decision_hint,
                    "- 对象选择：" + object_selection_hint,
                    "- 等待判断：" + wait_decision_hint,
                    "- 对话策略：" + conversation_policy_hint,
                    "- 重复检查：" + repeat_guard_hint,
                ]
            )
            extra = {
                "disabled_tools": ["declare_action", "request_action", "memory_store"],
                "town": {
                    "known": True,
                    "time": self.state.clock.label(),
                    "location_id": location.id,
                    "exits": list(perception["exits"]),
                    "exit_travel_minutes": {
                        exit_id: location.exit_travel_minutes.get(exit_id, DEFAULT_MOVE_MINUTES)
                        for exit_id in perception["exits"]
                    },
                    "object_ids": [obj.id for obj in objects],
                    "location_affordances": [
                        _affordance_dict(affordance)
                        for affordance in location.affordances
                    ],
                    "object_affordances": {
                        obj.id: [_affordance_dict(affordance) for affordance in obj.affordances]
                        for obj in objects
                    },
                    "visible_npc_ids": occupants,
                    "relationship_cues": relationship_cues,
                    "visible_npc_actions": visible_actions,
                    "visible_event_ids": [event.id for event in local_events],
                    "perception": perception,
                    "schedule_revision": _schedule_revision_dict(schedule_revision),
                    "current_schedule": _schedule_dict(schedule),
                    "current_schedule_remaining_minutes": schedule_remaining_minutes,
                    "current_schedule_progress": schedule_progress,
                    "current_schedule_completion_hint": schedule_completion_hint,
                    "prompt_policy": {
                        "schedule_decision_hint": schedule_decision_hint,
                        "object_selection_hint": object_selection_hint,
                        "wait_decision_hint": wait_decision_hint,
                        "conversation_policy_hint": conversation_policy_hint,
                        "repeat_guard_hint": repeat_guard_hint,
                    },
                    "loop_guard_events": recent_loop_guards,
                    "current_schedule_target_location_id": (
                        schedule.location_id if schedule is not None else None
                    ),
                    "current_action": (
                        self._current_action_dict(npc_id)
                        if self.state.current_action_for(npc_id) is not None
                        else None
                    ),
                    "active_conversation_id": (
                        active_session.id if active_session is not None else None
                    ),
                }
            }

        memory = self.memory_for(npc_id)
        memory_context_query = "\n".join(part for part in [event, situation] if part)
        memory_text = memory.build_context(memory_context_query)
        history_text = self._render_history(npc_id)
        todo_text = render_todo_text(memory)

        return AgentContext(
            npc_id=npc_id,
            input_event=event,
            tools=self.tools_for(npc_id),
            memory=memory,
            graph_id=AgentGraphID.ACTION_EXECUTOR_DEFAULT,
            route=AgentRoute.ACTION,
            world_rules=(
                "你只能感知当前语义地点中的信息。"
                "小镇世界引擎负责仲裁所有移动和世界状态变化。"
                "你必须通过小镇工具改变世界状态。"
                "日程安排是默认最高优先目标；除非出现 urgent/emergency/alarm 等紧急事件、"
                "明确的直接请求，或你有足够把握不会影响当前日程按时完成，"
                "不要为了顺路、好奇、闲聊或低优先级兴趣偏离当前日程目标。"
                "如果当前日程目标地点可达，应优先移动到目标地点或执行与目标直接相关的行动。"
                "只有当前场景信息不足、需要刷新本地可见状态、刚收到新事件但细节不清，"
                "或工具失败后需要重新确认环境时才使用 observe；"
                "已在 <situation> 中明确给出的地点、出口、可见物体、NPC 和事件，"
                "不要再用 observe 作为行动前的默认步骤。"
                "使用 move_to 沿明确出口移动，"
                "observe 只是查看状态，不代表世界行动完成，也不会推进全局时钟，"
                "不能用它替代移动、交互、说话、等待或完成日程。"
                "使用 wait 表示主动把接下来一段模拟时间用于原地等待，"
                "它不是等待下一个 tick 的流程控制工具。"
                "move_to、wait、speak_to、start_conversation、interact_with、"
                "finish_schedule_segment 一旦调用，本次行动就结束；"
                "下一次感知必须来自小镇世界引擎的下一次调度。"
                "使用 speak_to 只对同一地点可见 NPC 说话，"
                "NPC-NPC 自发多轮聊天必须使用 start_conversation 发起，"
                "不要用 speak_to 互相维持多轮聊天。"
                "使用 interact_with 只与当前位置物体交互，"
                "除 observe 外，小镇动作工具都会消耗模拟时间，工具返回值会展示动作的开始、"
                "耗时和完成时间。"
                "选择动作前应考虑动作耗时、移动耗时和当前日程剩余时间。"
                "选择动作前先判断当前活动是否已经满足，再选择行动；"
                "满足则优先结束日程。"
                "只有在当前日程段已满足"
                "或无法继续时才调用 finish_schedule_segment。"
                "日程目标已经满足时，应调用 finish_schedule_segment。"
                "日程不是计时打卡；目标达成后不要为了填满剩余时间重复同类交互。"
                "非对话场景中不能只用自然语言描述行动；"
                "如果你正在执行小镇日程，最终必须调用一个小镇 action tool、wait "
                "或 finish_schedule_segment 结束本次激活。"
                "如果日程目标地点不能直接到达，"
                "先移动到一个可达的中转地点。"
                "不是所有可见 NPC 都必须聊天；只有你自己判断值得交流时"
                "才发起 start_conversation。"
                "speak_to 是单次短消息，用于打招呼、通知或回答一句话，成功后本次行动结束。"
                "start_conversation 是多轮聊天入口，由世界引擎控制轮次、结束和 cooldown。"
                "收到对方 speak_to 后，最多直接 speak_to 回复一次；"
                "如果继续深入聊天，应使用 start_conversation。"
            ),
            situation="\n".join(
                [
                    situation,
                    "相关长期记忆：",
                    memory_text,
                ]
            ),
            history=history_text,
            todo=todo_text,
            extra=extra,
        )

    def handle_response(self, npc_id: str, response: AgentResponse) -> None:
        history = self.history_for(npc_id)
        if response.dialogue:
            location = self.state.location_for(npc_id)
            location_id = location.id if location is not None else "unknown"
            self.state.events.append(
                self._event_for_dialogue(npc_id, location_id, response.dialogue)
            )
            history.append(
                speaker=npc_id,
                content=response.dialogue,
                metadata={
                    "source": "town_dialogue",
                    "location_id": location_id,
                    "clock_minute": self.state.clock.minute,
                },
            )

        memory = self.memory_for(npc_id)
        for update in response.memory_updates:
            metadata = {
                "source": "agent_response",
                "clock_minute": self.state.clock.minute,
                **update.metadata,
            }
            memory.remember(update.content, category=update.type, metadata=metadata)

    def execute_action(self, npc_id: str, action: ActionRequest) -> ActionResult:
        if action.type in {"move", "move_to"}:
            destination = action.payload.get("to", action.payload.get("destination_id"))
            if not isinstance(destination, str) or not destination:
                return self._failed_action(
                    action.type,
                    "missing_destination",
                    "移动需要提供目标地点 id。",
                    {"npc_id": npc_id, "payload": action.payload},
                    action_id=action.action_id,
                )

            travel_minutes = self._travel_minutes(npc_id, destination)
            result = self.state.move_npc(npc_id, destination)
            action_result = self._move_result_to_action_result(
                action,
                result,
                travel_minutes=travel_minutes,
            )
            self._record_action_result(npc_id, action_result)
            return action_result

        if action.type == "wait":
            minutes = action.payload.get("minutes")
            if not isinstance(minutes, int):
                return self._failed_action(
                    action.type,
                    "missing_minutes",
                    "等待需要 payload {'minutes': <int>}。",
                    {"npc_id": npc_id, "payload": action.payload},
                    action_id=action.action_id,
                )
            return self.wait(npc_id, minutes, action_id=action.action_id)

        if action.type == "finish_schedule_segment":
            note = action.payload.get("note", "")
            return self.finish_schedule_segment(
                npc_id,
                str(note),
                action_id=action.action_id,
            )

        if action.type == "observe":
            return self.observe_action(npc_id, action_id=action.action_id)

        if action.type in {"speak", "speak_to"}:
            target = action.payload.get("target_npc_id", action.payload.get("target"))
            text = action.payload.get("text", action.payload.get("content", ""))
            if not isinstance(target, str) or not target:
                return self._failed_action(
                    action.type,
                    "missing_target_npc_id",
                    "说话需要提供目标 NPC id。",
                    {"npc_id": npc_id, "payload": action.payload},
                    action_id=action.action_id,
                )
            if not isinstance(text, str) or not text.strip():
                return self._failed_action(
                    action.type,
                    "missing_text",
                    "说话需要提供非空文本。",
                    {"npc_id": npc_id, "target_npc_id": target, "payload": action.payload},
                    action_id=action.action_id,
                )
            return self.speak_to(npc_id, target, text, action_id=action.action_id)

        if action.type in {"start_conversation", "conversation"}:
            target = action.payload.get("target_npc_id", action.payload.get("target"))
            topic = action.payload.get("topic_or_reason", action.payload.get("topic", ""))
            if not isinstance(target, str) or not target:
                return self._failed_action(
                    action.type,
                    "missing_target_npc_id",
                    "发起会话需要提供目标 NPC id。",
                    {"npc_id": npc_id, "payload": action.payload},
                    action_id=action.action_id,
                )
            return self.start_conversation(
                npc_id,
                target,
                str(topic),
                action_id=action.action_id,
            )

        if action.type in {"interact", "interact_with"}:
            object_id = action.payload.get("object_id")
            intent = action.payload.get("intent", action.payload.get("text", ""))
            if not isinstance(object_id, str) or not object_id:
                return self._failed_action(
                    action.type,
                    "missing_object_id",
                    "交互需要提供当前位置物体 id。",
                    {"npc_id": npc_id, "payload": action.payload},
                    action_id=action.action_id,
                )
            if not isinstance(intent, str) or not intent.strip():
                return self._failed_action(
                    action.type,
                    "missing_intent",
                    "交互需要提供非空目的描述。",
                    {"npc_id": npc_id, "object_id": object_id, "payload": action.payload},
                    action_id=action.action_id,
                )
            return self.interact_with(npc_id, object_id, intent, action_id=action.action_id)

        if action.type in {"use_affordance", "affordance"}:
            target_id = action.payload.get("target_id", action.payload.get("object_id"))
            affordance_id = action.payload.get("affordance_id")
            note = action.payload.get("note", action.payload.get("intent", ""))
            if not isinstance(target_id, str) or not target_id:
                return self._failed_action(
                    action.type,
                    "missing_target_id",
                    "执行 affordance 需要提供当前位置或可见物体 id。",
                    {"npc_id": npc_id, "payload": action.payload},
                    action_id=action.action_id,
                )
            if not isinstance(affordance_id, str) or not affordance_id:
                return self._failed_action(
                    action.type,
                    "missing_affordance_id",
                    "执行 affordance 需要提供 affordance_id。",
                    {"npc_id": npc_id, "target_id": target_id, "payload": action.payload},
                    action_id=action.action_id,
                )
            return self.use_affordance(
                npc_id,
                target_id,
                affordance_id,
                str(note),
                action_id=action.action_id,
            )

        return self._failed_action(
            action.type,
            "unsupported_action",
            f"暂不支持小镇动作 '{action.type}'。",
            {"npc_id": npc_id, "payload": action.payload},
            action_id=action.action_id,
        )

    def tools_for(self, npc_id: str) -> list[ToolDef]:
        return [
            PlanTodoTool(),
            MoveToTool(lambda destination_id: self.move_to(npc_id, destination_id)),
            ObserveTool(lambda: self.observe_action(npc_id)),
            SpeakToTool(
                lambda target_npc_id, text: self.speak_to(npc_id, target_npc_id, text)
            ),
            StartConversationTool(
                lambda target_npc_id, topic_or_reason: self.start_conversation(
                    npc_id,
                    target_npc_id,
                    topic_or_reason,
                )
            ),
            InteractWithTool(
                lambda object_id, intent: self.interact_with(npc_id, object_id, intent)
            ),
            InspectAffordancesTool(
                lambda target_id: self.inspect_affordances_action(npc_id, target_id)
            ),
            UseAffordanceTool(
                lambda target_id, affordance_id, note: self.use_affordance(
                    npc_id,
                    target_id,
                    affordance_id,
                    note,
                )
            ),
            WaitTool(lambda minutes: self.wait(npc_id, minutes)),
            FinishScheduleSegmentTool(
                lambda note: self.finish_schedule_segment(npc_id, note)
            ),
        ]

    def move_to(self, npc_id: str, destination_id: str) -> ActionResult:
        return self.execute_action(
            npc_id,
            ActionRequest(type="move_to", payload={"destination_id": destination_id}),
        )

    def observe(self, npc_id: str) -> dict[str, object]:
        location = self.state.location_for(npc_id)
        schedule = self.state.current_schedule_segment(npc_id)
        if location is None:
            return {"known": False, "npc_id": npc_id}
        perception = self.build_perception(npc_id)
        return {
            "known": True,
            "npc_id": npc_id,
            "time": self.state.clock.label(),
            "location": {
                "id": location.id,
                "name": location.name,
                "description": location.description,
                "affordances": [
                    _affordance_dict(affordance)
                    for affordance in location.affordances
                ],
            },
            "exits": list(perception["exits"]),
            "visible_npcs": list(perception["visible_npc_ids"]),
            "objects": [
                {
                    "id": obj.id,
                    "name": obj.name,
                    "description": obj.description,
                    "interactable": obj.interactable,
                    "affordances": [
                        _affordance_dict(affordance)
                        for affordance in obj.affordances
                    ],
                }
                for obj_id in perception["object_ids"]
                if (obj := self.state.objects.get(str(obj_id))) is not None
            ],
            "local_events": [
                {
                    "id": event.id,
                    "minute": event.minute,
                    "actor_id": event.actor_id,
                    "event_type": event.event_type,
                    "summary": event.summary,
                }
                for event in self.visible_events_for(npc_id)
                if event.id in perception["visible_event_ids"]
            ],
            "known_locations": list(perception["known_locations"]),
            "known_objects": list(perception["known_objects"]),
            "perception": perception,
            "current_schedule": _schedule_dict(schedule),
        }

    def observe_action(
        self,
        npc_id: str,
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        minute = self.state.clock.minute
        return ActionResult(
            action_id=action_id or ActionRequest(type="observe").action_id,
            action_type="observe",
            status="succeeded",
            observation="已观察当前本地小镇状态。",
            facts={
                **self.observe(npc_id),
                "start_minute": minute,
                "duration_minutes": DEFAULT_OBSERVE_MINUTES,
                "end_minute": minute + DEFAULT_OBSERVE_MINUTES,
                "start_time": _minute_label(minute),
                "end_time": _minute_label(minute + DEFAULT_OBSERVE_MINUTES),
            },
        )

    def inspect_affordances_action(
        self,
        npc_id: str,
        target_id: str | None = None,
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        location = self.state.location_for(npc_id)
        if location is None:
            return self._failed_action(
                "inspect_affordances",
                "unknown_npc",
                f"{npc_id} 尚未被放置到小镇中。",
                {"npc_id": npc_id, "target_id": target_id},
                action_id=action_id,
            )
        result = self.inspect_affordances(npc_id, target_id)
        status = "succeeded" if result["ok"] else "failed"
        facts = {
            **result,
            "start_minute": self.state.clock.minute,
            "duration_minutes": DEFAULT_OBSERVE_MINUTES,
            "end_minute": self.state.clock.minute + DEFAULT_OBSERVE_MINUTES,
        }
        return ActionResult(
            action_id=action_id or ActionRequest(type="inspect_affordances").action_id,
            action_type="inspect_affordances",
            status=status,
            observation=(
                "已查看可用 affordance。"
                if result["ok"]
                else str(result.get("message", "无法查看 affordance。"))
            ),
            reason=None if result["ok"] else str(result.get("reason", "unavailable")),
            facts=facts,
        )

    def inspect_affordances(
        self,
        npc_id: str,
        target_id: str | None = None,
    ) -> dict[str, object]:
        location = self.state.location_for(npc_id)
        if location is None:
            return {
                "ok": False,
                "reason": "unknown_npc",
                "message": f"{npc_id} 尚未被放置到小镇中。",
                "available_targets": [],
            }
        available = self._available_affordance_targets(location)
        if target_id is None or not target_id:
            return {
                "ok": True,
                "location_id": location.id,
                "targets": [_public_affordance_target(item) for item in available],
            }
        target = self._affordance_target(location, target_id)
        if target is None:
            return {
                "ok": False,
                "reason": "target_not_visible",
                "message": f"{target_id} 不是当前位置或当前位置可见物体。",
                "location_id": location.id,
                "available_targets": [item["id"] for item in available],
            }
        return {
            "ok": True,
            "location_id": location.id,
            "targets": [_public_affordance_target(target)],
        }

    def _available_affordance_targets(
        self,
        location: Location,
    ) -> list[dict[str, object]]:
        targets = [self._location_affordance_target(location)]
        for obj in self.state.objects_at(location.id):
            targets.append(self._object_affordance_target(obj))
        return targets

    def _affordance_target(
        self,
        location: Location,
        target_id: str,
    ) -> dict[str, object] | None:
        if target_id == location.id:
            return self._location_affordance_target(location)
        if target_id not in location.object_ids:
            return None
        obj = self.state.objects.get(target_id)
        if obj is None or obj.location_id != location.id:
            return None
        return self._object_affordance_target(obj)

    def _location_affordance_target(self, location: Location) -> dict[str, object]:
        return {
            "id": location.id,
            "kind": "location",
            "name": location.name,
            "description": location.description,
            "affordances": location.affordances,
            "affordance_ids": [item.id for item in location.affordances],
            "affordance_details": [
                _affordance_dict(affordance)
                for affordance in location.affordances
            ],
        }

    def _object_affordance_target(self, obj: TownObject) -> dict[str, object]:
        return {
            "id": obj.id,
            "kind": "object",
            "name": obj.name,
            "description": obj.description,
            "interactable": obj.interactable,
            "affordances": obj.affordances,
            "affordance_ids": [item.id for item in obj.affordances],
            "affordance_details": [
                _affordance_dict(affordance)
                for affordance in obj.affordances
            ],
        }

    def relationship_cues_for(
        self,
        npc_id: str,
        visible_npc_ids: list[str],
    ) -> list[dict[str, object]]:
        cues: list[dict[str, object]] = []
        for partner_id in visible_npc_ids:
            if partner_id == npc_id:
                continue
            cooldown_until = self.state.conversation_cooldowns.get(
                self._conversation_pair_key(npc_id, partner_id),
            )
            active_cooldown = (
                cooldown_until
                if cooldown_until is not None and cooldown_until > self.state.clock.minute
                else None
            )
            cues.append(
                {
                    "partner_npc_id": partner_id,
                    "recent_conversations": self._recent_conversation_summaries(
                        npc_id,
                        partner_npc_id=partner_id,
                    ),
                    "impressions": self._relationship_impressions(npc_id, partner_id),
                    "cooldown_until_minute": active_cooldown,
                    "cooldown_until_time": (
                        _minute_label(active_cooldown)
                        if active_cooldown is not None
                        else None
                    ),
                    "conversation_block_reason": self._conversation_block_reason(
                        npc_id,
                        partner_id,
                    ),
                }
            )
        return cues

    def speak_to(
        self,
        npc_id: str,
        target_npc_id: str,
        text: str,
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        location = self.state.location_for(npc_id)
        target_location = self.state.location_for(target_npc_id)
        if location is None:
            return self._failed_action(
                "speak_to",
                "unknown_npc",
                f"{npc_id} 尚未被放置到小镇中。",
                {"npc_id": npc_id, "target_npc_id": target_npc_id},
                action_id=action_id,
            )
        if target_location is None:
            return self._failed_action(
                "speak_to",
                "unknown_target_npc",
                f"目标 NPC {target_npc_id} 不存在或不在小镇中。",
                {"npc_id": npc_id, "target_npc_id": target_npc_id},
                action_id=action_id,
            )
        if target_location.id != location.id:
            return self._failed_action(
                "speak_to",
                "target_not_visible",
                f"{target_npc_id} 不在当前位置，无法直接说话。",
                {
                    "npc_id": npc_id,
                    "target_npc_id": target_npc_id,
                    "location_id": location.id,
                    "target_location_id": target_location.id,
                },
                action_id=action_id,
            )
        cooldown_until = self._speak_cooldowns.get((npc_id, target_npc_id), 0)
        if cooldown_until > self.state.clock.minute:
            return self._failed_action(
                "speak_to",
                "recent_speak_to_cooldown",
                f"{npc_id} 刚刚已经对 {target_npc_id} 说过话，短时间内不重复发送单句消息。",
                {
                    "npc_id": npc_id,
                    "target_npc_id": target_npc_id,
                    "cooldown_until_minute": cooldown_until,
                    "cooldown_until_time": _minute_label(cooldown_until),
                },
                action_id=action_id,
            )

        start_minute = max(self.state.clock.minute, self._next_available_minute(npc_id))
        event = TownEvent(
            id=f"event_{len(self.state.events) + 1}",
            minute=start_minute,
            location_id=location.id,
            actor_id=npc_id,
            event_type="speech",
            summary=f"{npc_id} 对 {target_npc_id} 说：{text}",
            target_ids=[target_npc_id],
        )
        self.state.events.append(event)
        self.event_bus.publish(event)
        self._speak_cooldowns[(npc_id, target_npc_id)] = (
            start_minute + self.speak_cooldown_minutes
        )
        metadata = {
            "source": "town_speech",
            "location_id": location.id,
            "clock_minute": self.state.clock.minute,
            "target_npc_id": target_npc_id,
        }
        self.history_for(npc_id).append(speaker=npc_id, content=text, metadata=metadata)
        self.history_for(target_npc_id).append(speaker=npc_id, content=text, metadata=metadata)

        result = self._timed_result(
            npc_id,
            action_id=action_id or ActionRequest(type="speak_to").action_id,
            action_type="speak_to",
            status="succeeded",
            observation=f"{npc_id} 已在 {location.id} 对 {target_npc_id} 说话。",
            facts={
                "npc_id": npc_id,
                "target_npc_id": target_npc_id,
                "location_id": location.id,
                "text": text,
                "event_id": event.id,
            },
            duration_minutes=self._speak_minutes(text),
        )
        self._record_action_result(npc_id, result)
        return result

    def start_conversation(
        self,
        npc_id: str,
        target_npc_id: str,
        topic_or_reason: str = "",
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        agent = self._active_step_agent
        if agent is None:
            return self._failed_action(
                "start_conversation",
                "missing_agent",
                "当前没有可用于生成会话的 NPC agent。",
                {"npc_id": npc_id, "target_npc_id": target_npc_id},
                action_id=action_id,
            )

        blocked = self._conversation_block_reason(npc_id, target_npc_id)
        if blocked is not None:
            failed_facts: dict[str, object] = {
                "npc_id": npc_id,
                "target_npc_id": target_npc_id,
                "topic_or_reason": topic_or_reason,
            }
            cooldown_until = self.state.conversation_cooldowns.get(
                self._conversation_pair_key(npc_id, target_npc_id),
            )
            if blocked == "recent_conversation_cooldown" and cooldown_until is not None:
                failed_facts.update(
                    {
                        "cooldown_until_minute": cooldown_until,
                        "cooldown_until_time": _minute_label(cooldown_until),
                    }
                )
            return self._failed_action(
                "start_conversation",
                blocked,
                f"{npc_id} 暂时不能和 {target_npc_id} 发起会话：{blocked}。",
                failed_facts,
                action_id=action_id,
            )

        location = self.state.location_for(npc_id)
        location_id = location.id if location is not None else "unknown"
        start_minute = max(self.state.clock.minute, self._next_available_minute(npc_id))
        session = ConversationSession(
            id=f"conversation_{len(self.state.conversation_sessions) + 1}",
            participants=(npc_id, target_npc_id),
            initiator_id=npc_id,
            location_id=location_id,
            topic=topic_or_reason,
            started_minute=start_minute,
            max_turns=self.chat_iter * 2,
        )
        self.state.conversation_sessions[session.id] = session

        speakers = (npc_id, target_npc_id)
        close_reason = "max_turns"
        for exchange_index in range(self.chat_iter):
            if not self._append_conversation_turn(
                session,
                agent,
                speakers[0],
                speakers[1],
                closing=False,
            ):
                close_reason = "empty_turn"
                break
            if self._last_turn_repeats(session):
                close_reason = "repeat_detected"
                break
            if exchange_index > 0 and self._conversation_should_close(session):
                self._append_conversation_turn(
                    session,
                    agent,
                    speakers[1],
                    speakers[0],
                    closing=True,
                )
                close_reason = "natural_close"
                break

            if not self._append_conversation_turn(
                session,
                agent,
                speakers[1],
                speakers[0],
                closing=False,
            ):
                close_reason = "empty_turn"
                break
            if self._last_turn_repeats(session):
                close_reason = "repeat_detected"
                break
            if self._conversation_should_close(session):
                close_reason = "natural_close"
                break
        else:
            close_reason = "max_turns"

        return self._close_conversation(
            session,
            close_reason,
            action_id=action_id or ActionRequest(type="start_conversation").action_id,
        )

    def interact_with(
        self,
        npc_id: str,
        object_id: str,
        intent: str,
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        location = self.state.location_for(npc_id)
        if location is None:
            return self._failed_action(
                "interact_with",
                "unknown_npc",
                f"{npc_id} 尚未被放置到小镇中。",
                {"npc_id": npc_id, "object_id": object_id},
                action_id=action_id,
            )
        obj = self.state.objects.get(object_id)
        if obj is None:
            return self._failed_action(
                "interact_with",
                "unknown_object",
                f"物体 {object_id} 不存在。",
                {"npc_id": npc_id, "object_id": object_id},
                action_id=action_id,
            )
        if obj.location_id != location.id or object_id not in location.object_ids:
            return self._failed_action(
                "interact_with",
                "object_not_visible",
                f"{object_id} 不在当前位置，无法交互。",
                {
                    "npc_id": npc_id,
                    "object_id": object_id,
                    "location_id": location.id,
                    "object_location_id": obj.location_id,
                },
                action_id=action_id,
            )
        if not obj.interactable:
            return self._failed_action(
                "interact_with",
                "object_not_interactable",
                f"{object_id} 当前不可交互。",
                {"npc_id": npc_id, "object_id": object_id, "location_id": location.id},
                action_id=action_id,
            )
        if obj.affordances and not _intent_matches_affordance(intent, obj.affordances):
            return self._failed_action(
                "interact_with",
                "unsupported_affordance",
                f"{object_id} 不支持“{intent}”。",
                {
                    "npc_id": npc_id,
                    "object_id": object_id,
                    "location_id": location.id,
                    "intent": intent,
                    "available_affordances": [
                        _affordance_dict(affordance)
                        for affordance in obj.affordances
                    ],
                },
                action_id=action_id,
            )

        start_minute = max(self.state.clock.minute, self._next_available_minute(npc_id))
        event = TownEvent(
            id=f"event_{len(self.state.events) + 1}",
            minute=start_minute,
            location_id=location.id,
            actor_id=npc_id,
            event_type="interaction",
            summary=f"{npc_id} 与 {obj.name} 交互：{intent}",
        )
        self.state.events.append(event)
        result = self._timed_result(
            npc_id,
            action_id=action_id or ActionRequest(type="interact_with").action_id,
            action_type="interact_with",
            status="succeeded",
            observation=f"{npc_id} 已与 {obj.name} 交互。",
            facts={
                "npc_id": npc_id,
                "object_id": object_id,
                "location_id": location.id,
                "intent": intent,
                "event_id": event.id,
            },
            duration_minutes=DEFAULT_INTERACT_MINUTES,
        )
        self._record_action_result(npc_id, result)
        return result

    def use_affordance(
        self,
        npc_id: str,
        target_id: str,
        affordance_id: str,
        note: str = "",
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        location = self.state.location_for(npc_id)
        if location is None:
            return self._failed_action(
                "use_affordance",
                "unknown_npc",
                f"{npc_id} 尚未被放置到小镇中。",
                {"npc_id": npc_id, "target_id": target_id, "affordance_id": affordance_id},
                action_id=action_id,
            )
        target = self._affordance_target(location, target_id)
        if target is None:
            available = self._available_affordance_targets(location)
            return self._failed_action(
                "use_affordance",
                "target_not_visible",
                f"{target_id} 不是当前位置或当前位置可见物体。",
                {
                    "npc_id": npc_id,
                    "target_id": target_id,
                    "affordance_id": affordance_id,
                    "location_id": location.id,
                    "available_targets": [item["id"] for item in available],
                },
                action_id=action_id,
            )
        affordances = target["affordances"]
        affordance = next(
            (
                item
                for item in affordances
                if item.id == affordance_id or affordance_id in item.aliases
            ),
            None,
        )
        if affordance is None:
            return self._failed_action(
                "use_affordance",
                "unsupported_affordance",
                f"{target_id} 不支持 affordance '{affordance_id}'。",
                {
                    "npc_id": npc_id,
                    "target_id": target_id,
                    "affordance_id": affordance_id,
                    "location_id": location.id,
                    "available_affordances": [
                        _affordance_dict(item) for item in affordances
                    ],
                },
                action_id=action_id,
            )

        start_minute = max(self.state.clock.minute, self._next_available_minute(npc_id))
        target_name = str(target["name"])
        target_kind = str(target["kind"])
        summary_note = note.strip() or affordance.description or affordance.label
        event = TownEvent(
            id=f"event_{len(self.state.events) + 1}",
            minute=start_minute,
            location_id=location.id,
            actor_id=npc_id,
            event_type=affordance.event_type,
            summary=(
                f"{npc_id} 在 {target_name} 使用 {affordance.label}："
                f"{summary_note}"
            ),
        )
        self.state.events.append(event)
        result = self._timed_result(
            npc_id,
            action_id=action_id or ActionRequest(type="use_affordance").action_id,
            action_type="use_affordance",
            status="succeeded",
            observation=f"{npc_id} 已使用 {target_name} 的 {affordance.label}。",
            facts={
                "npc_id": npc_id,
                "target_id": target_id,
                "target_kind": target_kind,
                "affordance_id": affordance.id,
                "affordance_label": affordance.label,
                "location_id": location.id,
                "note": summary_note,
                "event_id": event.id,
            },
            duration_minutes=max(1, affordance.duration_minutes),
        )
        self._record_action_result(npc_id, result)
        return result

    def wait(
        self,
        npc_id: str,
        minutes: int,
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        location = self.state.location_for(npc_id)
        location_id = location.id if location is not None else "unknown"
        result = self._timed_result(
            npc_id,
            action_id=action_id or ActionRequest(type="wait").action_id,
            action_type="wait",
            status="succeeded",
            observation=(
                f"{npc_id} 在 {location_id} 等待 {minutes} 分钟。"
                "全局小镇时钟没有推进。"
            ),
            facts={
                "npc_id": npc_id,
                "location_id": location_id,
                "minutes": minutes,
                "clock_minute": self.state.clock.minute,
            },
            duration_minutes=minutes,
            current_action_status="waiting",
        )
        self._record_action_result(npc_id, result)
        return result

    def finish_schedule_segment(
        self,
        npc_id: str,
        note: str = "",
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        segment = self.state.current_schedule_segment(npc_id)
        completion = self.state.complete_schedule_segment(npc_id, segment, note)
        if segment is None or completion is None:
            return self._failed_action(
                "finish_schedule_segment",
                "no_current_schedule_segment",
                f"{npc_id} 当前没有可完成的日程段。",
                {"npc_id": npc_id, "clock_minute": self.state.clock.minute},
                action_id=action_id,
            )
        self._record_reflection_evidence(
            npc_id,
            evidence_type="schedule",
            summary=(
                f"完成日程：{_minute_label(segment.start_minute)} "
                f"在 {segment.location_id} {segment.intent}。"
                + (f"备注：{completion.note}" if completion.note else "")
            ),
            poignancy=2,
            metadata={
                "segment_start_minute": segment.start_minute,
                "location_id": segment.location_id,
                "note": completion.note,
            },
        )
        result = self._timed_result(
            npc_id,
            action_id=action_id or ActionRequest(type="finish_schedule_segment").action_id,
            action_type="finish_schedule_segment",
            status="succeeded",
            observation=(
                f"{npc_id} 已完成 {_minute_label(segment.start_minute)} 开始、"
                f"目标地点为 {segment.location_id} 的日程段。"
            ),
            facts={
                "npc_id": npc_id,
                "segment_start_minute": segment.start_minute,
                "location_id": segment.location_id,
                "note": completion.note,
            },
            duration_minutes=0,
        )
        self._record_action_result(npc_id, result)
        return result

    def decompose_current_schedule_segment(self, npc_id: str) -> list[str]:
        """Persist deterministic subtasks for the active segment under town state."""
        segment = self.state.current_schedule_segment(npc_id)
        if segment is None:
            return []
        if not segment.subtasks:
            segment.subtasks = default_subtasks_for(segment) or [
                "到达目标地点",
                "执行与目标直接相关的行动",
                "目标满足后调用 finish_schedule_segment",
            ]
            self._record_planning_checkpoint(
                npc_id,
                day=self.state.clock.day,
                stage="segment_decomposition",
                payload={
                    "segment": _full_schedule_dict(segment),
                    "subtasks": list(segment.subtasks),
                },
            )
        return list(segment.subtasks)

    def revise_current_schedule_segment(
        self,
        npc_id: str,
        *,
        reason: str,
        subtasks: list[str] | None = None,
    ) -> ScheduleSegment | None:
        """Apply a bounded deterministic revision to the active segment only."""
        segment = self.state.current_schedule_segment(npc_id)
        if segment is None:
            return None
        before = _full_schedule_dict(segment)
        if subtasks is not None:
            segment.subtasks = [str(item) for item in subtasks]
        elif not segment.subtasks:
            segment.subtasks = self.decompose_current_schedule_segment(npc_id)
        if reason and f"revision:{reason}" not in segment.subtasks:
            segment.subtasks.append(f"revision:{reason}")
        self._record_planning_checkpoint(
            npc_id,
            day=self.state.clock.day,
            stage="schedule_revision",
            payload={
                "reason": reason,
                "before": before,
                "after": _full_schedule_dict(segment),
                "completed_evidence": [
                    _schedule_completion_dict(item)
                    for item in self.state.completed_schedule_segments.get(npc_id, [])
                ],
            },
        )
        return segment

    def revise_schedule_for_event(
        self,
        npc_id: str,
        event: TownEvent,
        reason: str = "",
    ) -> list[ScheduleSegment] | None:
        """Insert a deterministic short schedule segment for a significant event."""
        if npc_id not in self.state.residents:
            raise ValueError("unknown_resident")
        if not self._is_significant_event_for(npc_id, event):
            return None
        if event.location_id not in self.state.locations:
            return None

        current = self.state.current_schedule_segment(npc_id)
        if current is not None and current.location_id == event.location_id:
            return None
        revision_key = (npc_id, event.id)
        if revision_key in self._schedule_revisions:
            return None
        if any(
            f"event:{event.id}" in segment.subtasks
            for segment in self.state.schedule_for(npc_id)
        ):
            return None

        insert_start = self.state.clock.minute
        insert_duration = min(
            SCHEDULE_REVISION_MINUTES,
            max(1, self.state.clock.stride_minutes),
        )
        inserted = ScheduleSegment(
            npc_id=npc_id,
            start_minute=insert_start,
            duration_minutes=insert_duration,
            location_id=event.location_id,
            intent=f"处理事件：{event.summary}",
            subtasks=[f"event:{event.id}"],
        )
        revised = self._insert_schedule_segment(npc_id, inserted)
        self.state.set_schedule(npc_id, revised)

        revision = ScheduleRevision(
            npc_id=npc_id,
            event_id=event.id,
            reason=reason or self._significant_event_reason(npc_id, event),
            inserted_segment=inserted,
        )
        self._schedule_revisions[revision_key] = revision
        self._latest_schedule_revision_by_npc[npc_id] = revision
        return revised

    def _insert_schedule_segment(
        self,
        npc_id: str,
        inserted: ScheduleSegment,
    ) -> list[ScheduleSegment]:
        original = sorted(self.state.schedule_for(npc_id), key=lambda segment: segment.start_minute)
        revised: list[ScheduleSegment] = []
        inserted_done = False
        next_free_minute = inserted.start_minute

        for segment in original:
            if not inserted_done and segment.end_minute > inserted.start_minute:
                revised.append(inserted)
                inserted_done = True
                next_free_minute = inserted.end_minute

            if (
                inserted_done
                and segment.end_minute > inserted.start_minute
                and segment.start_minute < next_free_minute
            ):
                shifted_start = max(segment.start_minute, next_free_minute)
                shifted = ScheduleSegment(
                    npc_id=segment.npc_id,
                    start_minute=shifted_start,
                    duration_minutes=segment.duration_minutes,
                    location_id=segment.location_id,
                    intent=segment.intent,
                    subtasks=list(segment.subtasks),
                )
                revised.append(shifted)
                next_free_minute = shifted.end_minute
            else:
                revised.append(segment)

        if not inserted_done:
            revised.append(inserted)

        return sorted(revised, key=lambda segment: segment.start_minute)

    def _revise_schedule_from_perception(
        self,
        npc_id: str,
        perception: dict[str, Any],
    ) -> ScheduleRevision | None:
        visible_event_ids = set(perception.get("visible_event_ids", []))
        for event in self.visible_events_for(npc_id):
            if event.id not in visible_event_ids:
                continue
            if not self._is_significant_event_for(npc_id, event):
                continue
            self._record_event_reflection_evidence(npc_id, event)
            revision_key = (npc_id, event.id)
            existing = self._schedule_revisions.get(revision_key)
            if existing is not None:
                self._latest_schedule_revision_by_npc[npc_id] = existing
                return existing
            self.revise_schedule_for_event(
                npc_id,
                event,
                reason=self._significant_event_reason(npc_id, event),
            )
            return self._schedule_revisions.get(revision_key)
        return None

    def visible_events_for(self, npc_id: str) -> list[TownEvent]:
        perception = self.build_perception(npc_id)
        events_by_id = {event.id: event for event in self._local_event_candidates(npc_id)}
        return [
            events_by_id[event_id]
            for event_id in perception["visible_event_ids"]
            if event_id in events_by_id
        ]

    def build_perception(self, npc_id: str) -> dict[str, Any]:
        location = self.state.location_for(npc_id)
        if location is None:
            return {
                "known": False,
                "npc_id": npc_id,
                "location_id": None,
                "exits": [],
                "visible_npc_ids": [],
                "object_ids": [],
                "visible_event_ids": [],
                "known_locations": [],
                "known_objects": [],
                "limits": self._perception_limits_dict(),
            }

        schedule = self.state.current_schedule_segment(npc_id)
        policy = self.perception_policy
        event_candidates = self._local_event_candidates(npc_id)
        selected_events = self._select_events(
            npc_id,
            event_candidates,
            schedule,
            limit=policy.max_events,
        )
        selected_objects = self._select_objects(
            self.state.objects_at(location.id),
            schedule,
            limit=policy.max_objects,
        )
        selected_npc_ids = self._select_visible_npcs(
            npc_id,
            [other for other in location.occupant_ids if other != npc_id],
            schedule,
            limit=policy.max_npcs,
        )
        selected_exits = self._select_exits(location, schedule, limit=policy.max_exits)
        known_locations = self._known_location_rows(
            npc_id,
            current_location_id=location.id,
            visible_exit_ids=selected_exits,
            limit=policy.max_known_locations,
        )
        known_objects = self._known_object_rows(
            npc_id,
            visible_object_ids=[obj.id for obj in selected_objects],
            limit=policy.max_known_objects,
        )
        return {
            "known": True,
            "npc_id": npc_id,
            "location_id": location.id,
            "limits": self._perception_limits_dict(),
            "exits": selected_exits,
            "visible_npc_ids": selected_npc_ids,
            "object_ids": [obj.id for obj in selected_objects],
            "visible_event_ids": [event.id for event in selected_events],
            "events": [_event_dict(event) for event in selected_events],
            "objects": [_object_dict(obj) for obj in selected_objects],
            "visible_npcs": selected_npc_ids,
            "known_locations": known_locations,
            "known_objects": known_objects,
        }

    def _local_event_candidates(self, npc_id: str) -> list[TownEvent]:
        location = self.state.location_for(npc_id)
        if location is None:
            return []
        events = self.state.events
        if self._visible_event_count_limit is not None:
            events = events[: self._visible_event_count_limit]
        return [
            event
            for event in events
            if event.visible and event.location_id == location.id
        ]

    def _select_events(
        self,
        npc_id: str,
        events: list[TownEvent],
        schedule: ScheduleSegment | None,
        *,
        limit: int,
    ) -> list[TownEvent]:
        return sorted(events, key=lambda event: self._event_attention_key(npc_id, event, schedule))[
            :limit
        ]

    def _event_attention_key(
        self,
        npc_id: str,
        event: TownEvent,
        schedule: ScheduleSegment | None,
    ) -> tuple[int, int, int, str]:
        if npc_id in event.target_ids:
            priority = 0
        elif event.event_type in {"urgent", "emergency", "alarm"}:
            priority = 1
        elif _event_matches_schedule(event, schedule):
            priority = 2
        else:
            priority = 3
        return (priority, -event.minute, self.state.events.index(event), event.id)

    def _select_objects(
        self,
        objects: list[TownObject],
        schedule: ScheduleSegment | None,
        *,
        limit: int,
    ) -> list[TownObject]:
        return sorted(
            objects,
            key=lambda obj: (
                0 if _object_matches_schedule(obj, schedule) else 1,
                obj.id,
            ),
        )[:limit]

    def _select_visible_npcs(
        self,
        npc_id: str,
        visible_npc_ids: list[str],
        schedule: ScheduleSegment | None,
        *,
        limit: int,
    ) -> list[str]:
        return sorted(
            visible_npc_ids,
            key=lambda other: (
                0 if self._has_pending_event_from_or_for(npc_id, other) else 1,
                0 if self.state.current_action_for(other) is not None else 1,
                0 if self._npc_schedule_matches_location(other, schedule) else 1,
                other,
            ),
        )[:limit]

    def _select_exits(
        self,
        location: Location,
        schedule: ScheduleSegment | None,
        *,
        limit: int,
    ) -> list[str]:
        exit_order = {exit_id: index for index, exit_id in enumerate(location.exits)}
        return sorted(
            location.exits,
            key=lambda exit_id: (
                0 if schedule is not None and exit_id == schedule.location_id else 1,
                exit_order[exit_id],
            ),
        )[:limit]

    def _known_location_rows(
        self,
        npc_id: str,
        *,
        current_location_id: str,
        visible_exit_ids: list[str],
        limit: int,
    ) -> list[dict[str, object]]:
        resident = self.state.resident_for(npc_id)
        if resident is None:
            return []
        invisible_ids = [
            location_id
            for location_id in resident.spatial_memory.known_location_ids
            if location_id != current_location_id and location_id not in visible_exit_ids
        ]
        rows: list[dict[str, object]] = []
        for location_id in sorted(dict.fromkeys(invisible_ids)):
            location = self.state.locations.get(location_id)
            if location is None:
                continue
            rows.append(
                {
                    "id": location.id,
                    "name": location.name,
                    "description": location.description,
                    "exits": list(location.exits),
                    "affordances": [
                        _affordance_dict(affordance)
                        for affordance in location.affordances
                    ],
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def _known_object_rows(
        self,
        npc_id: str,
        *,
        visible_object_ids: list[str],
        limit: int,
    ) -> list[dict[str, object]]:
        resident = self.state.resident_for(npc_id)
        if resident is None:
            return []
        visible = set(visible_object_ids)
        rows: list[dict[str, object]] = []
        for object_id in sorted(dict.fromkeys(resident.spatial_memory.known_object_ids)):
            if object_id in visible:
                continue
            obj = self.state.objects.get(object_id)
            if obj is None:
                continue
            rows.append(
                {
                    "id": obj.id,
                    "name": obj.name,
                    "location_id": obj.location_id,
                    "description": obj.description,
                    "interactable": obj.interactable,
                    "affordances": [
                        _affordance_dict(affordance)
                        for affordance in obj.affordances
                    ],
                }
            )
            if len(rows) >= limit:
                break
        return rows

    def _has_pending_event_from_or_for(self, npc_id: str, other_npc_id: str) -> bool:
        return any(
            event.actor_id == other_npc_id or other_npc_id in event.target_ids
            for event in self._inboxes.get(npc_id, [])
        )

    def _npc_schedule_matches_location(
        self,
        npc_id: str,
        schedule: ScheduleSegment | None,
    ) -> bool:
        if schedule is None:
            return False
        other_schedule = self.state.current_schedule_segment(npc_id)
        return (
            other_schedule is not None
            and other_schedule.location_id == schedule.location_id
        )

    def _perception_limits_dict(self) -> dict[str, int]:
        return {
            "events": self.perception_policy.max_events,
            "objects": self.perception_policy.max_objects,
            "npcs": self.perception_policy.max_npcs,
            "exits": self.perception_policy.max_exits,
            "known_locations": self.perception_policy.max_known_locations,
            "known_objects": self.perception_policy.max_known_objects,
        }

    def _record_event_reflection_evidence(self, npc_id: str, event: TownEvent) -> None:
        self._record_reflection_evidence(
            npc_id,
            evidence_type="event",
            summary=f"重要事件：{event.summary}",
            poignancy=_event_poignancy(npc_id, event),
            clock_minute=event.minute,
            metadata={
                "event_id": event.id,
                "event_type": event.event_type,
                "location_id": event.location_id,
            },
        )

    def _record_reflection_evidence(
        self,
        npc_id: str,
        *,
        evidence_type: str,
        summary: str,
        poignancy: int,
        metadata: dict[str, object],
        clock_minute: int | None = None,
    ) -> ReflectionEvidence | None:
        resident = self.state.resident_for(npc_id)
        if resident is None:
            return None
        if _has_duplicate_reflection_evidence(
            resident.reflection_evidence,
            evidence_type=evidence_type,
            metadata=metadata,
        ):
            return None
        evidence = ReflectionEvidence(
            id=f"{npc_id}_{evidence_type}_{len(resident.reflection_evidence) + 1}",
            evidence_type=evidence_type,
            summary=summary,
            poignancy=poignancy,
            clock_minute=self.state.clock.minute if clock_minute is None else clock_minute,
            metadata=metadata,
        )
        resident.reflection_evidence.append(evidence)
        resident.poignancy += poignancy
        return evidence

    def step(  # type: ignore[override]
        self,
        agent: TownAgent,
        npc_ids: list[str] | None = None,
    ) -> list[dict[str, object]]:
        self.npc_registry.sync_from_state(self.state)
        active_npcs = self.npc_registry.active_ids(npc_ids)
        tick = len(self.replay_log) + 1
        tick_start_minute = self.state.clock.minute
        input_order = {npc_id: index for index, npc_id in enumerate(active_npcs)}
        next_available = {
            npc_id: self._next_available_minute(npc_id, at_minute=tick_start_minute)
            for npc_id in active_npcs
        }
        ready_npcs = [
            npc_id
            for npc_id in active_npcs
            if next_available[npc_id] <= tick_start_minute
        ]
        ready_npcs.sort(key=lambda npc_id: (next_available[npc_id], input_order[npc_id]))
        visible_event_limit = len(self.state.events)
        inbox_snapshot = {npc_id: self.event_bus.drain(npc_id) for npc_id in ready_npcs}

        records: list[dict[str, object]] = []
        self._visible_event_count_limit = visible_event_limit
        previous_agent = self._active_step_agent
        self._active_step_agent = agent
        try:
            for npc_id in ready_npcs:
                if self._next_available_minute(npc_id, at_minute=tick_start_minute) > tick_start_minute:
                    continue
                event = self._activation_event(npc_id, inbox_snapshot.get(npc_id, []))
                if event is None:
                    continue
                before_actions = len(self.action_log)
                context = self.build_context(npc_id, event)
                response = agent.run(context)
                action_results = [
                    self.execute_action(npc_id, action).model_dump()
                    for action in response.actions
                ]
                self.handle_response(npc_id, response)
                records.append(
                    {
                        "tick": tick,
                        "time": self.state.clock.label(),
                        "minute": tick_start_minute,
                        "npc_id": npc_id,
                        "input_event": event,
                        "dialogue": response.dialogue,
                        "action_results": action_results,
                        "logged_actions": self.action_log[before_actions:],
                    }
                )
        finally:
            self._visible_event_count_limit = None
            self._active_step_agent = previous_agent

        self.replay_log.append(
            {
                "tick": tick,
                "time": _minute_label(tick_start_minute),
                "minute": tick_start_minute,
                "ran_npc_ids": [str(record["npc_id"]) for record in records],
                "skipped_npc_ids": [
                    npc_id
                    for npc_id in active_npcs
                    if npc_id not in {str(record["npc_id"]) for record in records}
                ],
                "next_available_minutes": next_available,
                "records": records,
                "snapshot": self.build_replay_snapshot(
                    active_npcs,
                    minute=tick_start_minute,
                ),
            }
        )
        self.state.clock.minute += self.state.clock.stride_minutes
        return records

    def write_replay_artifacts(self, output_dir: str | Path) -> dict[str, Path]:
        output = Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        actions_path = output / "town_replay.jsonl"
        timeline_path = output / "town_timeline.txt"
        checkpoints_path = output / "town_checkpoints.jsonl"
        reflections_path = output / "town_reflections.jsonl"

        with actions_path.open("w", encoding="utf-8") as f:
            for item in self.action_log:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

        with checkpoints_path.open("w", encoding="utf-8") as f:
            for item in self.replay_log:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

        with reflections_path.open("w", encoding="utf-8") as f:
            for item in self.reflection_log:
                f.write(json.dumps(item, ensure_ascii=False, default=str) + "\n")

        with timeline_path.open("w", encoding="utf-8") as f:
            for item in self.planning_log:
                f.write(
                    f"[{item.get('time')}] {item.get('npc_id')} planning "
                    f"{item.get('stage')} day={item.get('day')}\n"
                )
            for item in self.loop_guard_events:
                f.write(
                    f"[{item.get('time')}] {item.get('npc_id')} loop_guard "
                    f"{item.get('guard_type')}: {item.get('message')}\n"
                )
            for item in self.action_log:
                f.write(
                    f"[{item.get('time')}] {item.get('npc_id')} "
                    f"{item.get('action_type')} {item.get('status')} "
                    f"@ {item.get('location_id')}: {item.get('summary')}\n"
                )

        return {
            "actions": actions_path,
            "timeline": timeline_path,
            "checkpoints": checkpoints_path,
            "reflections": reflections_path,
        }

    def _append_conversation_turn(
        self,
        session: ConversationSession,
        agent: TownAgent,
        speaker_id: str,
        listener_id: str,
        *,
        closing: bool,
    ) -> bool:
        event = self._conversation_input_event(
            session,
            speaker_id=speaker_id,
            listener_id=listener_id,
            closing=closing,
        )
        context = self.build_context(speaker_id, event)
        context.tools = []
        context.graph_id = AgentGraphID.DIALOGUE_MEMORY_THEN_OUTPUT
        context.route = AgentRoute.DIALOGUE
        context.world_rules = (
            "你正在参与一段由 TownWorldEngine 托管的 NPC-NPC 会话。"
            "本阶段可以用记忆工具确认关系和背景，但不得移动 NPC，不得写世界动作，不得描述工具调用。"
            "只输出对对方说的 1 到 3 句中文台词。"
            "如果对话已经自然结束，只做一句自然收尾，不要继续推进移动、交互或日程动作。"
            "不要提到 start_conversation、conversation_session、tool、input_event 等内部实现词。"
        )
        context.extra.setdefault("town", {})["conversation_session_id"] = session.id
        context.extra["town"]["conversation_partner_id"] = listener_id
        context.extra["town"]["conversation_closing_turn"] = closing
        context.extra["town"]["relationship_cues"] = self.relationship_cues_for(
            speaker_id,
            [listener_id],
        )
        response = agent.run(context)
        text = response.dialogue.strip()
        if not text:
            text = response.inner_thought.strip()
        if not text:
            return False
        text = _clean_conversation_text(_strip_speaker_prefix(text, speaker_id))
        if not text:
            return False
        session.turns.append(
            ConversationTurn(
                speaker_id=speaker_id,
                listener_id=listener_id,
                text=text,
                minute=max(self.state.clock.minute, self._next_available_minute(speaker_id)),
            )
        )
        return True

    def _close_conversation(
        self,
        session: ConversationSession,
        close_reason: str,
        *,
        action_id: str,
    ) -> ActionResult:
        session.status = "closed"
        session.close_reason = close_reason
        duration_minutes = self._conversation_duration_minutes(session)
        session.ended_minute = session.started_minute + duration_minutes
        cooldown_until = session.ended_minute + self.conversation_cooldown_minutes
        self.state.conversation_cooldowns[self._conversation_pair_key(*session.participants)] = (
            cooldown_until
        )

        transcript = self._conversation_transcript(session)
        summary = self._conversation_summary(session)
        event = TownEvent(
            id=f"event_{len(self.state.events) + 1}",
            minute=session.started_minute,
            location_id=session.location_id,
            actor_id=session.initiator_id,
            event_type="conversation",
            summary=summary,
            visible=False,
            target_ids=[p for p in session.participants if p != session.initiator_id],
        )
        self.state.events.append(event)

        for participant in session.participants:
            partner = next(p for p in session.participants if p != participant)
            self._append_conversation_history(participant, session, transcript)
            self.memory_for(participant).remember(
                self._participant_conversation_impression(participant, partner, session),
                category="impression",
                metadata={
                    "source": "town_conversation",
                    "conversation_session_id": session.id,
                    "relationship_pair_key": self._conversation_pair_key(*session.participants),
                    "relationship_participants": ",".join(session.participants),
                    "relationship_summary": self._relationship_summary(
                        participant,
                        partner,
                        session,
                    ),
                    "partner_npc_id": partner,
                    "location_id": session.location_id,
                    "clock_minute": session.started_minute,
                    "close_reason": close_reason,
                    "topic_or_reason": session.topic,
                    "unresolved_topics": ",".join(
                        self._conversation_unresolved_topics(session)
                    ),
                    "follow_up_intentions": ",".join(
                        self._conversation_follow_up_intentions(participant, partner, session)
                    ),
                },
            )
            for index, follow_up in enumerate(
                self._conversation_follow_up_intentions(participant, partner, session),
                start=1,
            ):
                self.memory_for(participant).remember(
                    follow_up,
                    category="todo",
                    metadata={
                        "source": "town_conversation_followup",
                        "status": "open",
                        "todo_id": f"{session.id}_{participant}_followup_{index}",
                        "conversation_session_id": session.id,
                        "partner_npc_id": partner,
                        "relationship_pair_key": self._conversation_pair_key(
                            *session.participants
                        ),
                        "topic_or_reason": session.topic,
                        "created_at": f"day-{self.state.clock.day}:{session.started_minute}",
                    },
                )
            self._record_reflection_evidence(
                participant,
                evidence_type="conversation",
                summary=self._participant_conversation_impression(
                    participant,
                    partner,
                    session,
                ),
                poignancy=3,
                clock_minute=session.started_minute,
                metadata={
                    "conversation_session_id": session.id,
                    "relationship_pair_key": self._conversation_pair_key(*session.participants),
                    "relationship_summary": self._relationship_summary(
                        participant,
                        partner,
                        session,
                    ),
                    "partner_npc_id": partner,
                    "location_id": session.location_id,
                    "close_reason": close_reason,
                    "topic_or_reason": session.topic,
                    "unresolved_topics": ",".join(
                        self._conversation_unresolved_topics(session)
                    ),
                    "follow_up_intentions": ",".join(
                        self._conversation_follow_up_intentions(participant, partner, session)
                    ),
                },
            )
            self.state.set_current_action(
                participant,
                CurrentAction(
                    npc_id=participant,
                    action_type="conversation",
                    location_id=session.location_id,
                    start_minute=session.started_minute,
                    duration_minutes=duration_minutes,
                    status="conversation",
                    summary=summary,
                ),
            )

        result = ActionResult(
            action_id=action_id,
            action_type="start_conversation",
            status="succeeded",
            observation=summary,
            facts={
                "conversation_session_id": session.id,
                "participants": list(session.participants),
                "location_id": session.location_id,
                "topic_or_reason": session.topic,
                "turn_count": len(session.turns),
                "close_reason": close_reason,
                "transcript": [
                    {
                        "speaker_id": turn.speaker_id,
                        "listener_id": turn.listener_id,
                        "text": turn.text,
                        "minute": turn.minute,
                    }
                    for turn in session.turns
                ],
                "start_minute": session.started_minute,
                "duration_minutes": duration_minutes,
                "end_minute": session.ended_minute,
                "start_time": _minute_label(session.started_minute),
                "end_time": _minute_label(session.ended_minute),
                "cooldown_until_minute": cooldown_until,
            },
        )
        self._record_action_result(session.initiator_id, result)
        return result

    def _conversation_block_reason(self, npc_id: str, target_npc_id: str) -> str | None:
        location = self.state.location_for(npc_id)
        target_location = self.state.location_for(target_npc_id)
        if location is None:
            return "unknown_npc"
        if target_location is None:
            return "unknown_target_npc"
        if location.id != target_location.id:
            return "target_not_visible"
        for participant in (npc_id, target_npc_id):
            active = self.state.active_conversation_for(participant)
            if active is not None:
                return "already_in_conversation"
            action = self.state.current_action_for(participant)
            if (
                action is not None
                and action.action_type == "conversation"
                and action.end_minute > self.state.clock.minute
            ):
                return "already_in_conversation"
            if action is not None and action.end_minute > self.state.clock.minute:
                return "participant_busy"
            if action is not None and action.action_type == "sleep":
                return "participant_sleeping"
        cooldown_until = self.state.conversation_cooldowns.get(
            self._conversation_pair_key(npc_id, target_npc_id),
            0,
        )
        if cooldown_until > self.state.clock.minute:
            return "recent_conversation_cooldown"
        return None

    def _conversation_input_event(
        self,
        session: ConversationSession,
        *,
        speaker_id: str,
        listener_id: str,
        closing: bool,
    ) -> str:
        transcript = self._conversation_transcript(session) or "（对话尚未开始）"
        if closing:
            instruction = "请用一句自然的收尾回应结束这段对话，不要提出新的问题。"
        else:
            instruction = "请以角色身份对对方说 1-3 句话。"
        return "\n".join(
            [
                f"你正在与 {listener_id} 进行小镇会话 {session.id}。",
                f"话题/原因：{session.topic or '自然交流'}",
                "当前对话记录：",
                transcript,
                instruction,
            ]
        )

    def _conversation_should_close(self, session: ConversationSession) -> bool:
        if not session.turns:
            return False
        text = session.turns[-1].text.strip()
        if _looks_like_open_question(text):
            return False
        close_markers = (
            "再见",
            "回头见",
            "待会",
            "下次",
            "先这样",
            "先到这里",
            "我先去",
            "我得走",
            "我该去",
            "谢谢你",
            "谢谢你的",
        )
        return any(marker in text for marker in close_markers)

    def _last_turn_repeats(self, session: ConversationSession) -> bool:
        if len(session.turns) < 3:
            return False
        last = session.turns[-1]
        last_text = _normalize_dialogue(last.text)
        if not last_text:
            return False
        for turn in session.turns[:-1]:
            if turn.speaker_id == last.speaker_id and _normalize_dialogue(turn.text) == last_text:
                return True
        return False

    def _append_conversation_history(
        self,
        npc_id: str,
        session: ConversationSession,
        transcript: str,
    ) -> None:
        partner = next(p for p in session.participants if p != npc_id)
        self.history_for(npc_id).append(
            speaker="town_conversation",
            content=transcript,
            metadata={
                "source": "town_conversation",
                "conversation_session_id": session.id,
                "partner_npc_id": partner,
                "location_id": session.location_id,
                "clock_minute": session.started_minute,
                "close_reason": session.close_reason,
            },
        )

    def _conversation_transcript(self, session: ConversationSession) -> str:
        return "\n".join(f"{turn.speaker_id}: {turn.text}" for turn in session.turns)

    def _conversation_summary(self, session: ConversationSession) -> str:
        participants = " 和 ".join(session.participants)
        topic = f"，话题：{session.topic}" if session.topic else ""
        return (
            f"{participants} 在 {session.location_id} 进行了一段对话"
            f"{topic}，共 {len(session.turns)} 句，结束原因：{session.close_reason or 'unknown'}。"
        )

    def _participant_conversation_impression(
        self,
        npc_id: str,
        partner_id: str,
        session: ConversationSession,
    ) -> str:
        own_lines = [
            _clean_conversation_text(turn.text)
            for turn in session.turns
            if turn.speaker_id == npc_id
        ]
        partner_lines = [
            _clean_conversation_text(turn.text)
            for turn in session.turns
            if turn.speaker_id == partner_id
        ]
        own_lines = [line for line in own_lines if line]
        partner_lines = [line for line in partner_lines if line]
        own_text = "；".join(own_lines[-2:]) if own_lines else "没有说太多"
        partner_text = "；".join(partner_lines[-2:]) if partner_lines else "没有回应太多"
        return (
            f"我和 {partner_id} 在 {session.location_id} 聊过"
            f"{('关于' + session.topic) if session.topic else '一会儿'}。"
            f"我提到：{own_text}。{partner_id} 提到：{partner_text}。"
        )

    def _relationship_summary(
        self,
        npc_id: str,
        partner_id: str,
        session: ConversationSession,
    ) -> str:
        unresolved = self._conversation_unresolved_topics(session)
        followups = self._conversation_follow_up_intentions(npc_id, partner_id, session)
        parts = [
            f"{npc_id} 与 {partner_id} 最近在 {session.location_id} 围绕"
            f"“{session.topic or '日常交流'}”有过对话"
        ]
        if unresolved:
            parts.append("未解决：" + "；".join(unresolved))
        if followups:
            parts.append("后续意图：" + "；".join(followups))
        return "。".join(parts) + "。"

    def _conversation_unresolved_topics(self, session: ConversationSession) -> list[str]:
        topics: list[str] = []
        if session.close_reason in {"max_turns", "repeat_detected", "empty_turn"}:
            topics.append(session.topic or "继续完成上次未收束的对话")
        question_lines = [
            turn.text
            for turn in session.turns
            if _looks_like_open_question(turn.text)
        ]
        if question_lines:
            topics.append(_compact_topic(question_lines[-1]))
        return _dedupe_strings(topics)[:3]

    def _conversation_follow_up_intentions(
        self,
        npc_id: str,
        partner_id: str,
        session: ConversationSession,
    ) -> list[str]:
        intentions: list[str] = []
        unresolved = self._conversation_unresolved_topics(session)
        if unresolved:
            intentions.append(f"跟进与 {partner_id} 的话题：{unresolved[0]}")
        if session.topic:
            topic = _compact_topic(session.topic)
            if any(marker in session.topic for marker in ("推荐", "约", "帮", "需要", "确认")):
                intentions.append(f"安排时间处理与 {partner_id} 的{topic}")
        return _dedupe_strings(intentions)[:3]

    def _conversation_duration_minutes(self, session: ConversationSession) -> int:
        total_chars = sum(len(turn.text) for turn in session.turns)
        return max(
            1,
            min(MAX_CONVERSATION_MINUTES, math.ceil(total_chars / CONVERSATION_CHARS_PER_MINUTE)),
        )

    def _conversation_pair_key(self, npc_a: str, npc_b: str) -> str:
        return "|".join(sorted((npc_a, npc_b)))

    def _recent_conversation_summaries(
        self,
        npc_id: str,
        *,
        partner_npc_id: str | None = None,
    ) -> list[str]:
        recent: list[str] = []
        for session in self.state.conversation_sessions.values():
            if npc_id not in session.participants or session.status != "closed":
                continue
            if session.ended_minute is None:
                continue
            partner = next(p for p in session.participants if p != npc_id)
            if partner_npc_id is not None and partner != partner_npc_id:
                continue
            recent.append(
                f"{partner}: {_minute_label(session.started_minute)} "
                f"{session.topic or '日常对话'}，结束={session.close_reason or 'unknown'}"
            )
        return recent[-3:]

    def _relationship_impressions(self, npc_id: str, partner_npc_id: str) -> list[str]:
        return [
            record.content
            for record in self.memory_for(npc_id).grep(
                "",
                category="impression",
                metadata_filters={
                    "source": "town_conversation",
                    "partner_npc_id": partner_npc_id,
                },
                k=3,
            )
        ][-3:]

    def _current_action_dict(self, npc_id: str) -> dict[str, object]:
        action = self.state.current_action_for(npc_id)
        if action is None:
            raise KeyError(npc_id)
        return {
            "action_type": action.action_type,
            "location_id": action.location_id,
            "start_minute": action.start_minute,
            "duration_minutes": action.duration_minutes,
            "end_minute": action.end_minute,
            "start_time": _minute_label(action.start_minute),
            "end_time": _minute_label(action.end_minute),
            "status": action.status,
            "summary": action.summary,
        }

    def _resident_snapshot(self, npc_id: str, *, minute: int) -> dict[str, object]:
        resident = self.state.resident_for(npc_id)
        if resident is None:
            raise KeyError(npc_id)
        current_action = (
            self._current_action_dict(npc_id)
            if self.state.current_action_for(npc_id) is not None
            else None
        )
        current_schedule = self.state.current_schedule_segment(npc_id, minute=minute)
        day_plan = resident.day_plans.get(self.state.clock.day)
        return {
            "location_id": self.state.location_id_for(npc_id),
            "schedule_day": resident.schedule_day,
            "currently": resident.scratch.currently,
            "day_plan": _resident_day_plan_dict(day_plan),
            "current_action": current_action,
            "current_schedule": _schedule_dict(current_schedule),
            "schedule_completed": (
                self.state.is_schedule_segment_complete(npc_id, current_schedule)
                if current_schedule is not None
                else False
            ),
            "poignancy": resident.poignancy,
            "reflection_due": self.reflection_due_for(npc_id),
            "reflection_evidence_count": len(resident.reflection_evidence),
        }

    def _conversation_session_snapshot(
        self,
        session: ConversationSession,
    ) -> dict[str, object]:
        return {
            "id": session.id,
            "participants": list(session.participants),
            "status": session.status,
            "location_id": session.location_id,
            "topic_or_reason": session.topic,
            "turn_count": len(session.turns),
            "started_minute": session.started_minute,
            "ended_minute": session.ended_minute,
            "close_reason": session.close_reason,
        }

    def _schedule_progress_summary(
        self,
        npc_id: str,
        schedule: ScheduleSegment | None,
    ) -> str:
        return schedule_progress_summary(
            npc_id=npc_id,
            schedule=schedule,
            action_log=self.action_log,
        )

    def _schedule_completion_hint(
        self,
        npc_id: str,
        schedule: ScheduleSegment | None,
        progress_summary: str,
    ) -> str:
        if schedule is None:
            return "当前没有日程段，不要调用 finish_schedule_segment。"
        if self.state.is_schedule_segment_complete(npc_id, schedule):
            return "当前日程段已经完成；除非有待处理直接事件，不需要继续行动。"

        successful_actions: list[dict[str, object]] = []
        for item in self.action_log:
            minute = item.get("minute")
            if (
                item.get("npc_id") == npc_id
                and item.get("status") == "succeeded"
                and isinstance(minute, int)
                and schedule.start_minute <= minute < schedule.end_minute
                and item.get("action_type") not in {"observe"}
            ):
                successful_actions.append(item)
        action_count = len(successful_actions)
        remaining = max(0, schedule.end_minute - self.state.clock.minute)
        intent = schedule.intent
        if action_count == 0:
            return (
                "先选择与当前日程最相关的对象或出口行动；"
                "不要只输出叙述或只观察。"
            )
        if any(word in intent for word in ("准备", "整理")) and action_count >= 3:
            return (
                f"你已经为“{intent}”完成多次相关行动。"
                "如果柜台/书车/相关对象已经处理到位，应优先调用 "
                "finish_schedule_segment，而不是继续重复同类交互。"
            )
        if any(word in intent for word in ("吃", "买", "取", "送")) and action_count >= 1:
            return (
                f"你已经执行过与“{intent}”直接相关的行动。"
                "如果物品已取得、交易已完成或需求已满足，应调用 "
                "finish_schedule_segment。"
            )
        if remaining <= self.state.clock.stride_minutes:
            return (
                "当前日程即将结束；如果目标已经基本满足，应立即调用 "
                "finish_schedule_segment。"
            )
        return (
            progress_summary
            + "。继续行动前先判断目标是否已经满足；满足则调用 finish_schedule_segment。"
        )

    def _validate_and_repair_schedule(
        self,
        npc_id: str,
        schedule: list[ScheduleSegment],
        *,
        day: int,
        start_minute: int,
        end_minute: int,
    ) -> tuple[list[ScheduleSegment], dict[str, object]]:
        warnings: list[str] = []
        repaired: list[ScheduleSegment] = []
        fallback_location = self.state.location_id_for(npc_id) or next(iter(self.state.locations))
        next_start = start_minute
        for raw in sorted(schedule, key=lambda segment: segment.start_minute):
            if raw.npc_id != npc_id:
                warnings.append("schedule_npc_mismatch")
                continue
            location_id = raw.location_id
            if location_id not in self.state.locations:
                warnings.append("unknown_schedule_location")
                location_id = fallback_location
            duration = max(1, int(raw.duration_minutes))
            segment_start = max(start_minute, int(raw.start_minute), next_start)
            if segment_start >= end_minute:
                warnings.append("schedule_segment_out_of_bounds")
                continue
            if segment_start != raw.start_minute:
                warnings.append("overlap_or_bounds_repaired")
            duration = min(duration, end_minute - segment_start)
            repaired.append(
                ScheduleSegment(
                    npc_id=npc_id,
                    start_minute=segment_start,
                    duration_minutes=duration,
                    location_id=location_id,
                    intent=raw.intent or "处理当天事项",
                    subtasks=list(raw.subtasks),
                    day=day,
                )
            )
            next_start = segment_start + duration

        if not repaired:
            warnings.append("deterministic_fallback_schedule")
            repaired.append(
                ScheduleSegment(
                    npc_id=npc_id,
                    start_minute=start_minute,
                    duration_minutes=max(1, min(60, end_minute - start_minute)),
                    location_id=fallback_location,
                    intent="整理当天事项",
                    day=day,
                )
            )
        repaired = self._repair_first_segment_reachability(
            npc_id,
            repaired,
            warnings=warnings,
            day=day,
            start_minute=start_minute,
            end_minute=end_minute,
            fallback_location=fallback_location,
        )
        return repaired, {
            "ok": not warnings,
            "warnings": warnings,
            "segment_count": len(repaired),
        }

    def _repair_first_segment_reachability(
        self,
        npc_id: str,
        schedule: list[ScheduleSegment],
        *,
        warnings: list[str],
        day: int,
        start_minute: int,
        end_minute: int,
        fallback_location: str,
    ) -> list[ScheduleSegment]:
        if not schedule:
            return schedule
        current_location_id = self.state.location_id_for(npc_id) or fallback_location
        first = schedule[0]
        if current_location_id == first.location_id:
            return schedule
        travel_minutes = self._shortest_travel_minutes(current_location_id, first.location_id)
        if travel_minutes is None:
            warnings.append("first_segment_unreachable_repaired")
            return [
                ScheduleSegment(
                    npc_id=npc_id,
                    start_minute=start_minute,
                    duration_minutes=max(1, min(first.duration_minutes, end_minute - start_minute)),
                    location_id=current_location_id,
                    intent=f"从当前位置过渡：{first.intent}",
                    subtasks=list(first.subtasks),
                    day=day,
                ),
                *[
                    segment
                    for segment in schedule[1:]
                    if segment.start_minute < end_minute
                ],
            ]
        earliest_arrival = start_minute + travel_minutes
        if first.start_minute >= earliest_arrival:
            return schedule
        warnings.append("first_segment_requires_travel_repair")
        if earliest_arrival >= end_minute:
            warnings.append("deterministic_fallback_schedule")
            return [
                ScheduleSegment(
                    npc_id=npc_id,
                    start_minute=start_minute,
                    duration_minutes=max(1, end_minute - start_minute),
                    location_id=current_location_id,
                    intent="整理当前位置事项",
                    day=day,
                )
            ]

        shifted: list[ScheduleSegment] = []
        next_start = earliest_arrival
        for raw in schedule:
            segment_start = max(raw.start_minute, next_start)
            if segment_start >= end_minute:
                warnings.append("schedule_segment_out_of_bounds")
                continue
            duration = min(raw.duration_minutes, end_minute - segment_start)
            shifted.append(
                ScheduleSegment(
                    npc_id=npc_id,
                    start_minute=segment_start,
                    duration_minutes=max(1, duration),
                    location_id=raw.location_id,
                    intent=raw.intent,
                    subtasks=list(raw.subtasks),
                    day=day,
                )
            )
            next_start = segment_start + duration
        return shifted or [
            ScheduleSegment(
                npc_id=npc_id,
                start_minute=start_minute,
                duration_minutes=max(1, end_minute - start_minute),
                location_id=current_location_id,
                intent="整理当前位置事项",
                day=day,
            )
        ]

    def _shortest_travel_minutes(self, origin_id: str, destination_id: str) -> int | None:
        if origin_id == destination_id:
            return 0
        if origin_id not in self.state.locations or destination_id not in self.state.locations:
            return None
        frontier: list[tuple[int, str]] = [(0, origin_id)]
        best: dict[str, int] = {origin_id: 0}
        while frontier:
            frontier.sort(key=lambda item: item[0])
            travel_so_far, location_id = frontier.pop(0)
            if location_id == destination_id:
                return travel_so_far
            location = self.state.locations.get(location_id)
            if location is None:
                continue
            for exit_id in location.exits:
                if exit_id not in self.state.locations:
                    continue
                next_travel = travel_so_far + location.exit_travel_minutes.get(
                    exit_id,
                    DEFAULT_MOVE_MINUTES,
                )
                if next_travel < best.get(exit_id, 10**9):
                    best[exit_id] = next_travel
                    frontier.append((next_travel, exit_id))
        return None

    def _assert_schedule_valid(
        self,
        npc_id: str,
        schedule: list[ScheduleSegment],
    ) -> None:
        previous: ScheduleSegment | None = None
        for segment in sorted(schedule, key=lambda item: item.start_minute):
            if segment.npc_id != npc_id:
                raise ValueError("schedule_npc_mismatch")
            if segment.location_id not in self.state.locations:
                raise ValueError("unknown_schedule_location")
            if segment.duration_minutes <= 0:
                raise ValueError("invalid_schedule_plan")
            if previous is not None and previous.end_minute > segment.start_minute:
                raise ValueError("overlapping_schedule_segments")
            previous = segment

    def _record_planning_checkpoint(
        self,
        npc_id: str,
        *,
        day: int,
        stage: str,
        payload: dict[str, object],
    ) -> None:
        self.planning_log.append(
            {
                "day": day,
                "minute": self.state.clock.minute,
                "time": self.state.clock.label(),
                "npc_id": npc_id,
                "stage": stage,
                **payload,
            }
        )

    def _detect_loop_guards(self, npc_id: str) -> None:
        recent = [
            item
            for item in self.action_log
            if item.get("npc_id") == npc_id and item.get("day") == self.state.clock.day
        ][-LOOP_GUARD_WINDOW:]
        if len(recent) >= 3:
            last_three = recent[-3:]
            failed = [item for item in last_three if item.get("status") == "failed"]
            if len(failed) == 3:
                action_type = str(failed[-1].get("action_type"))
                reasons: set[str] = set()
                for item in failed:
                    facts = item.get("facts")
                    if isinstance(facts, dict) and facts.get("reason"):
                        reasons.add(str(facts["reason"]))
                    else:
                        reasons.add(str(item.get("status")))
                targets = {_loop_guard_target(item) for item in failed}
                if action_type in {"move_to", "move", "interact_with", "interact"} and len(targets) == 1:
                    self._record_loop_guard_event(
                        npc_id,
                        "repeated_failed_action",
                        f"连续失败的 {action_type}: {next(iter(targets))}",
                        {"action_type": action_type, "reasons": sorted(reasons), "target": next(iter(targets))},
                    )
            action_types = [str(item.get("action_type")) for item in last_three]
            if len(set(action_types)) == 1 and action_types[-1] in {"wait", "speak_to", "start_conversation"}:
                self._record_loop_guard_event(
                    npc_id,
                    "repeated_low_value_action",
                    f"连续执行 {action_types[-1]}，需要检查是否空转。",
                    {"action_type": action_types[-1]},
                )

        schedule = self.state.current_schedule_segment(npc_id)
        location_id = self.state.location_id_for(npc_id)
        if (
            schedule is not None
            and location_id is not None
            and location_id != schedule.location_id
            and self.state.clock.minute - schedule.start_minute >= self.state.clock.stride_minutes * 3
        ):
            self._record_loop_guard_event(
                npc_id,
                "schedule_drift",
                f"{npc_id} 长时间停留在 {location_id}，偏离日程目标 {schedule.location_id}。",
                {
                    "location_id": location_id,
                    "schedule_location_id": schedule.location_id,
                    "segment_start_minute": schedule.start_minute,
                },
            )

    def _record_loop_guard_event(
        self,
        npc_id: str,
        guard_type: str,
        message: str,
        details: dict[str, object],
    ) -> None:
        key = (
            self.state.clock.day,
            npc_id,
            guard_type,
            tuple(sorted((str(k), str(v)) for k, v in details.items())),
        )
        if key in self._loop_guard_keys:
            return
        self._loop_guard_keys.add(key)
        self.loop_guard_events.append(
            {
                "day": self.state.clock.day,
                "minute": self.state.clock.minute,
                "time": self.state.clock.label(),
                "npc_id": npc_id,
                "guard_type": guard_type,
                "message": message,
                "details": details,
            }
        )

    def _recent_loop_guard_events(self, npc_id: str) -> list[dict[str, object]]:
        return [
            event
            for event in self.loop_guard_events
            if event.get("npc_id") == npc_id and event.get("day") == self.state.clock.day
        ][-5:]

    def memory_for(self, npc_id: str) -> MemoryInterface:
        if npc_id not in self._memories:
            self._memories[npc_id] = DefaultMemoryInterface(
                npc_id,
                chroma_client=self._client,
            )
        return self._memories[npc_id]

    def history_for(self, npc_id: str) -> HistoryStore:
        if npc_id not in self._histories:
            self._histories[npc_id] = HistoryStore(
                npc_id,
                self._history_dir / f"{npc_id}.jsonl",
            )
        return self._histories[npc_id]

    def ingest_external(
        self,
        npc_id: str,
        speaker: str,
        content: str,
        metadata: dict[str, object] | None = None,
    ) -> None:
        """Record inbound speech or event text into one NPC's JSONL history."""
        location = self.state.location_for(npc_id)
        base_metadata: dict[str, object] = {
            "source": "town_external",
            "location_id": location.id if location is not None else "unknown",
            "clock_minute": self.state.clock.minute,
        }
        base_metadata.update(metadata or {})
        self.history_for(npc_id).append(
            speaker=speaker,
            content=content,
            metadata=base_metadata,
        )

    def _next_available_minute(self, npc_id: str, *, at_minute: int | None = None) -> int:
        action = self.state.current_action_for(npc_id)
        if action is None:
            return self.state.clock.minute if at_minute is None else at_minute
        return action.end_minute

    def _timed_result(
        self,
        npc_id: str,
        *,
        action_id: str,
        action_type: str,
        status: Literal["succeeded", "failed", "partial", "deferred"],
        observation: str,
        facts: dict[str, object],
        duration_minutes: int,
        reason: str | None = None,
        current_action_status: str | None = None,
    ) -> ActionResult:
        start_minute = max(self.state.clock.minute, self._next_available_minute(npc_id))
        end_minute = start_minute + duration_minutes
        timed_facts = {
            **facts,
            "start_minute": start_minute,
            "duration_minutes": duration_minutes,
            "end_minute": end_minute,
            "start_time": _minute_label(start_minute),
            "end_time": _minute_label(end_minute),
        }
        result = ActionResult(
            action_id=action_id,
            action_type=action_type,
            status=status,
            reason=reason,
            observation=observation,
            facts=timed_facts,
        )
        self._record_current_action(
            npc_id,
            result,
            start_minute=start_minute,
            duration_minutes=duration_minutes,
            current_action_status=current_action_status,
        )
        return result

    def _record_current_action(
        self,
        npc_id: str,
        result: ActionResult,
        *,
        start_minute: int,
        duration_minutes: int,
        current_action_status: str | None = None,
    ) -> None:
        location = self.state.location_for(npc_id)
        self.state.set_current_action(
            npc_id,
            CurrentAction(
                npc_id=npc_id,
                action_type=result.action_type,
                location_id=location.id if location is not None else "unknown",
                start_minute=start_minute,
                duration_minutes=duration_minutes,
                status=current_action_status or result.status,
                summary=result.observation,
            ),
        )

    def _travel_minutes(self, npc_id: str, destination_id: str) -> int:
        location = self.state.location_for(npc_id)
        if location is None:
            return DEFAULT_FAILED_ACTION_MINUTES
        return location.exit_travel_minutes.get(destination_id, DEFAULT_MOVE_MINUTES)

    def _speak_minutes(self, text: str) -> int:
        return max(1, min(MAX_SPEAK_MINUTES, math.ceil(len(text) / SPEAK_CHARS_PER_MINUTE)))

    def _move_result_to_action_result(
        self,
        action: ActionRequest,
        result: MoveResult,
        *,
        travel_minutes: int,
    ) -> ActionResult:
        facts = {
            "npc_id": result.npc_id,
            "from": result.from_location_id,
            "to": result.to_location_id,
            "reachable": result.reachable,
        }
        if result.ok:
            return self._timed_result(
                result.npc_id,
                action_id=action.action_id,
                action_type=action.type,
                status="succeeded",
                observation=(
                    f"{result.npc_id} 已从 {result.from_location_id} "
                    f"移动到 {result.to_location_id}。"
                ),
                facts=facts,
                duration_minutes=result.travel_minutes or travel_minutes,
            )
        return self._timed_result(
            result.npc_id,
            action_id=action.action_id,
            action_type=action.type,
            status="failed",
            reason=result.reason,
            observation=(
                f"{result.npc_id} 无法从 {result.from_location_id} "
                f"移动到 {result.to_location_id}。"
            ),
            facts=facts,
            duration_minutes=DEFAULT_FAILED_ACTION_MINUTES,
        )

    def _activation_event(
        self,
        npc_id: str,
        pending_events: list[TownEvent],
    ) -> str | None:
        if pending_events:
            self.event_bus.mark_seen(npc_id, (event.id for event in pending_events))
            return "待处理小镇事件：" + "; ".join(event.summary for event in pending_events)

        significant_events = self.event_bus.unseen_visible_events(
            npc_id,
            self.visible_events_for(npc_id),
            should_activate=lambda event: self._is_significant_event_for(npc_id, event),
        )
        if significant_events:
            for event in significant_events:
                self.revise_schedule_for_event(
                    npc_id,
                    event,
                    reason=self._significant_event_reason(npc_id, event),
                )
            self.event_bus.mark_seen(npc_id, (event.id for event in significant_events))
            return (
                "你注意到重要本地事件："
                + "; ".join(event.summary for event in significant_events)
            )

        segment = self.state.current_schedule_segment(npc_id)
        if segment is not None and not self.state.is_schedule_segment_complete(npc_id, segment):
            return (
                f"当前日程段：{_minute_label(segment.start_minute)}-"
                f"{_minute_label(segment.end_minute)}，目标地点={segment.location_id}，"
                f"目标={segment.intent}。"
            )
        local_events = self.event_bus.unseen_visible_events(
            npc_id,
            self.visible_events_for(npc_id),
            should_activate=lambda event: self._should_activate_for_local_event(
                npc_id,
                event,
            ),
        )
        if local_events:
            self.event_bus.mark_seen(npc_id, (event.id for event in local_events))
            return (
                "你注意到本地事件："
                + "; ".join(event.summary for event in local_events)
            )
        return None

    def _should_activate_for_local_event(self, npc_id: str, event: TownEvent) -> bool:
        if self._is_significant_event_for(npc_id, event):
            return True
        return self._has_active_or_pending_schedule(npc_id)

    def _is_significant_event_for(self, npc_id: str, event: TownEvent) -> bool:
        return npc_id in event.target_ids or event.event_type in SIGNIFICANT_EVENT_TYPES

    def _significant_event_reason(self, npc_id: str, event: TownEvent) -> str:
        if npc_id in event.target_ids:
            return "targeted_event"
        if event.event_type in SIGNIFICANT_EVENT_TYPES:
            return f"{event.event_type}_event"
        return "significant_event"

    def _has_active_or_pending_schedule(self, npc_id: str) -> bool:
        segment = self.state.current_schedule_segment(npc_id)
        return (
            segment is not None
            and not self.state.is_schedule_segment_complete(npc_id, segment)
        )

    def _failed_action(
        self,
        action_type: str,
        reason: str,
        observation: str,
        facts: dict[str, object],
        *,
        action_id: str | None = None,
    ) -> ActionResult:
        result = self._timed_result(
            str(facts.get("npc_id", "unknown")),
            action_id=action_id or ActionRequest(type=action_type).action_id,
            action_type=action_type,
            status="failed",
            reason=reason,
            observation=observation,
            facts={**facts, "reason": reason},
            duration_minutes=DEFAULT_FAILED_ACTION_MINUTES,
        )
        self._record_action_result(str(facts.get("npc_id", "unknown")), result)
        return result

    def _record_action_result(self, npc_id: str, result: ActionResult) -> None:
        location = self.state.location_for(npc_id)
        minute = result.facts.get("start_minute", self.state.clock.minute)
        self.action_log.append(
            {
                "day": self.state.clock.day,
                "time": _minute_label(minute) if isinstance(minute, int) else self.state.clock.label(),
                "minute": minute,
                "end_minute": result.facts.get("end_minute"),
                "npc_id": npc_id,
                "action_type": result.action_type,
                "status": result.status,
                "location_id": location.id if location is not None else None,
                "summary": result.observation,
                "facts": result.facts,
            }
        )
        self._detect_loop_guards(npc_id)

    def _event_for_dialogue(self, npc_id: str, location_id: str, dialogue: str) -> TownEvent:
        return TownEvent(
            id=f"event_{len(self.state.events) + 1}",
            minute=self.state.clock.minute,
            location_id=location_id,
            actor_id=npc_id,
            event_type="dialogue",
            summary=dialogue,
        )

    def _render_history(self, npc_id: str) -> str:
        history_path = self._history_dir / f"{npc_id}.jsonl"
        if npc_id not in self._histories and not history_path.exists():
            return ""
        entries = self.history_for(npc_id).read_last(MAX_TOWN_HISTORY_TURNS)
        if not entries:
            return ""
        return "\n".join(f"[{entry.speaker}] {entry.content}" for entry in entries)


def _render_schedule(schedule: ScheduleSegment | None) -> str:
    if schedule is None:
        return "无"
    return (
        f"{_minute_label(schedule.start_minute)}-{_minute_label(schedule.end_minute)} "
        f"地点 {schedule.location_id}：{schedule.intent}"
    )


def _render_relationship_cues(cues: list[dict[str, object]]) -> str:
    if not cues:
        return "无"
    rows: list[str] = []
    for cue in cues:
        partner = str(cue.get("partner_npc_id", "unknown"))
        parts: list[str] = []
        recent = cue.get("recent_conversations")
        if isinstance(recent, list) and recent:
            parts.append("近期对话 " + " / ".join(str(item) for item in recent[:2]))
        impressions = cue.get("impressions")
        if isinstance(impressions, list) and impressions:
            parts.append("印象 " + " / ".join(str(item) for item in impressions[:2]))
        cooldown_time = cue.get("cooldown_until_time")
        if isinstance(cooldown_time, str) and cooldown_time:
            parts.append(f"会话冷却至 {cooldown_time}")
        block_reason = cue.get("conversation_block_reason")
        if isinstance(block_reason, str) and block_reason:
            parts.append(f"当前阻止原因 {block_reason}")
        rows.append(f"{partner}：" + ("；".join(parts) if parts else "暂无"))
    return "；".join(rows)


def _render_planning_evidence(evidence: list[dict[str, object]]) -> str:
    if not evidence:
        return "无"
    rows: list[str] = []
    for item in evidence[:8]:
        metadata = item.get("metadata")
        source = ""
        partner = ""
        if isinstance(metadata, dict):
            source = str(metadata.get("source") or "")
            partner_id = metadata.get("partner_npc_id")
            partner = f", partner={partner_id}" if partner_id else ""
        rows.append(
            f"- [{item.get('category', 'memory')}; source={source}{partner}] "
            f"{item.get('content', '')}"
        )
    return "\n".join(rows)


def _render_relationship_planning_evidence(evidence: list[dict[str, object]]) -> str:
    if not evidence:
        return "无"
    rows: list[str] = []
    for item in evidence[:6]:
        parts = [
            f"partner={item.get('partner_npc_id')}",
            f"topic={item.get('topic_or_reason') or '日常交流'}",
        ]
        unresolved = item.get("unresolved_topics")
        if isinstance(unresolved, list) and unresolved:
            parts.append("unresolved=" + " / ".join(str(value) for value in unresolved[:2]))
        followups = item.get("follow_up_intentions")
        if isinstance(followups, list) and followups:
            parts.append("follow_up=" + " / ".join(str(value) for value in followups[:2]))
        summary = item.get("relationship_summary") or item.get("content", "")
        rows.append("- " + "；".join(parts) + f"；summary={summary}")
    return "\n".join(rows)


def _render_reflection_evidence(evidence: list[ReflectionEvidence]) -> str:
    if not evidence:
        return "无"
    return "\n".join(
        (
            f"- {item.id} [{item.evidence_type}, poignancy={item.poignancy}, "
            f"time={_minute_label(item.clock_minute)}] {item.summary}"
        )
        for item in evidence
    )


def _reflection_evidence_dict(evidence: ReflectionEvidence) -> dict[str, object]:
    return {
        "id": evidence.id,
        "evidence_type": evidence.evidence_type,
        "summary": evidence.summary,
        "poignancy": evidence.poignancy,
        "clock_minute": evidence.clock_minute,
        "metadata": dict(evidence.metadata),
    }


def _has_duplicate_reflection_evidence(
    evidence: list[ReflectionEvidence],
    *,
    evidence_type: str,
    metadata: dict[str, object],
) -> bool:
    dedupe_keys = {
        "event": ("event_id",),
        "conversation": ("conversation_session_id", "partner_npc_id"),
        "schedule": ("segment_start_minute", "location_id"),
    }
    keys = dedupe_keys.get(evidence_type, ())
    if not keys:
        return False
    return any(
        item.evidence_type == evidence_type
        and all(item.metadata.get(key) == metadata.get(key) for key in keys)
        for item in evidence
    )


def _event_poignancy(npc_id: str, event: TownEvent) -> int:
    if event.event_type in SIGNIFICANT_EVENT_TYPES:
        return 5
    if npc_id in event.target_ids:
        return 4
    return 2


def _minute_label(minute: int) -> str:
    hours, minutes = divmod(minute, 60)
    return f"{hours:02d}:{minutes:02d}"


def _strip_speaker_prefix(text: str, speaker_id: str) -> str:
    stripped = text.strip()
    for prefix in (f"{speaker_id}:", f"{speaker_id}："):
        if stripped.startswith(prefix):
            return stripped[len(prefix):].strip()
    return stripped


_INTERNAL_CONVERSATION_MARKERS = (
    "conversation is ongoing via",
    "start_conversation",
    "conversation_session",
    "tool_call",
    "tool calls",
    "function call",
    "input_event",
    "available_tools",
    "available_skills",
    "<world_rules>",
    "<situation>",
    "<input_event>",
)


def _clean_conversation_text(text: str) -> str:
    """Drop internal orchestration phrases before persisting dialogue memory."""
    kept: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        lowered = line.lower()
        if any(marker in lowered for marker in _INTERNAL_CONVERSATION_MARKERS):
            continue
        kept.append(line)
    return " ".join(kept).strip()


def _normalize_dialogue(text: str) -> str:
    return "".join(ch for ch in text.lower().strip() if ch.isalnum())


def _looks_like_open_question(text: str) -> bool:
    stripped = text.strip()
    if stripped.endswith(("?", "？")):
        return True
    question_markers = ("吗", "呢", "什么", "怎么", "为什么", "能否", "可以", "要不要")
    return any(marker in stripped[-12:] for marker in question_markers)


def _compact_topic(text: str, *, max_chars: int = 36) -> str:
    compact = " ".join(_clean_conversation_text(text).split())
    if not compact:
        compact = "未命名话题"
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + "..."


def _dedupe_strings(values: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        out.append(normalized)
    return out


def _split_metadata_list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [item.strip() for item in value.split(",") if item.strip()]
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _planning_influence_intentions(evidence: list[dict[str, object]]) -> list[str]:
    prioritized: list[tuple[int, str]] = []
    for item in evidence:
        category = str(item.get("category", ""))
        content = str(item.get("content", ""))
        metadata = item.get("metadata")
        source = ""
        partner = ""
        followups: list[str] = []
        if isinstance(metadata, dict):
            source = str(metadata.get("source") or "")
            partner = str(metadata.get("partner_npc_id") or "")
            followups = _split_metadata_list(metadata.get("follow_up_intentions"))
        if source == "town_conversation_followup":
            prioritized.append((0, content))
        elif followups:
            prioritized.extend((1, followup) for followup in followups)
        elif source == "town_reflection" or category == "reflection":
            prioritized.append((2, "根据近期反思调整今天的优先事项"))
        elif source == "town_conversation" and partner:
            prioritized.append((3, f"考虑是否需要跟进与 {partner} 的交流"))
    intentions = [item for _, item in sorted(prioritized, key=lambda pair: pair[0])]
    return _dedupe_strings(intentions)[:2]


def _schedule_dict(schedule: ScheduleSegment | None) -> dict[str, object] | None:
    if schedule is None:
        return None
    return {
        "npc_id": schedule.npc_id,
        "day": schedule.day,
        "start_minute": schedule.start_minute,
        "end_minute": schedule.end_minute,
        "location_id": schedule.location_id,
        "intent": schedule.intent,
        "subtasks": list(schedule.subtasks),
    }


def _schedule_revision_dict(revision: ScheduleRevision | None) -> dict[str, object]:
    if revision is None:
        return {"revised": False}
    return {
        "revised": True,
        "npc_id": revision.npc_id,
        "event_id": revision.event_id,
        "reason": revision.reason,
        "inserted_segment": _schedule_dict(revision.inserted_segment),
    }


def _event_dict(event: TownEvent) -> dict[str, object]:
    return {
        "id": event.id,
        "minute": event.minute,
        "location_id": event.location_id,
        "actor_id": event.actor_id,
        "event_type": event.event_type,
        "summary": event.summary,
        "target_ids": list(event.target_ids),
    }


def _object_dict(obj: TownObject) -> dict[str, object]:
    return {
        "id": obj.id,
        "name": obj.name,
        "location_id": obj.location_id,
        "description": obj.description,
        "interactable": obj.interactable,
        "affordances": [
            _affordance_dict(affordance)
            for affordance in obj.affordances
        ],
    }


def _affordance_dict(affordance: SemanticAffordance) -> dict[str, object]:
    return {
        "id": affordance.id,
        "label": affordance.label,
        "description": affordance.description,
        "duration_minutes": affordance.duration_minutes,
        "aliases": list(affordance.aliases),
        "event_type": affordance.event_type,
    }


def _public_affordance_target(target: dict[str, object]) -> dict[str, object]:
    affordances = target.get("affordances")
    details: list[dict[str, object]] = []
    if isinstance(affordances, list):
        details = [
            _affordance_dict(item)
            for item in affordances
            if isinstance(item, SemanticAffordance)
        ]
    return {
        key: value
        for key, value in {
            "id": target.get("id"),
            "kind": target.get("kind"),
            "name": target.get("name"),
            "description": target.get("description"),
            "interactable": target.get("interactable"),
            "affordance_ids": target.get("affordance_ids", []),
            "affordances": details,
        }.items()
        if value is not None
    }


def _event_matches_schedule(
    event: TownEvent,
    schedule: ScheduleSegment | None,
) -> bool:
    if schedule is None:
        return False
    haystack = f"{event.event_type} {event.summary} {event.location_id}".lower()
    return (
        schedule.location_id == event.location_id
        or schedule.location_id.lower() in haystack
        or any(token and token in haystack for token in _semantic_tokens(schedule.intent))
    )


def _object_matches_schedule(
    obj: TownObject,
    schedule: ScheduleSegment | None,
) -> bool:
    if schedule is None:
        return False
    affordances = " ".join(
        f"{item.id} {item.label} {item.description} {' '.join(item.aliases)}"
        for item in obj.affordances
    )
    haystack = f"{obj.id} {obj.name} {obj.description} {obj.location_id} {affordances}".lower()
    return any(token and token in haystack for token in _semantic_tokens(schedule.intent))


def _intent_matches_affordance(
    intent: str,
    affordances: list[SemanticAffordance],
) -> bool:
    normalized = intent.lower().strip()
    tokens = _semantic_tokens(intent)
    for affordance in affordances:
        haystack = (
            f"{affordance.id} {affordance.label} {affordance.description} "
            f"{' '.join(affordance.aliases)}"
        ).lower()
        if affordance.id == normalized or normalized in haystack:
            return True
        if any(token and token in haystack for token in tokens):
            return True
    return False


def _render_affordance_refs(affordances: list[SemanticAffordance]) -> str:
    if not affordances:
        return "无"
    return ", ".join(f"{item.label}({item.id})" for item in affordances)


def _semantic_tokens(text: str) -> list[str]:
    separators = " ，,。.;；:/\\()（）[]【】"
    normalized = text.lower()
    for sep in separators:
        normalized = normalized.replace(sep, " ")
    words = [word for word in normalized.split() if len(word) >= 2]
    if not words and text:
        words = [text.lower()]
    return words


def _render_known_locations(rows: object) -> str:
    if not isinstance(rows, list) or not rows:
        return "无"
    rendered: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        rendered.append(
            f"{row.get('name', '未知地点')} ({row.get('id', 'unknown')})："
            f"{row.get('description', '')}；affordances="
            f"{_render_affordance_row_refs(row.get('affordances'))}"
        )
    return "; ".join(rendered) if rendered else "无"


def _render_known_objects(rows: object) -> str:
    if not isinstance(rows, list) or not rows:
        return "无"
    rendered: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        affordance = "可交互" if row.get("interactable") else "不可交互"
        rendered.append(
            f"{row.get('name', '未知物体')} ({row.get('id', 'unknown')})，"
            f"地点={row.get('location_id', 'unknown')}，{affordance}："
            f"{row.get('description', '')}；affordances="
            f"{_render_affordance_row_refs(row.get('affordances'))}"
        )
    return "; ".join(rendered) if rendered else "无"


def _render_affordance_row_refs(value: object) -> str:
    if not isinstance(value, list) or not value:
        return "无"
    rendered: list[str] = []
    for item in value:
        if isinstance(item, dict):
            rendered.append(f"{item.get('label', item.get('id', 'unknown'))}({item.get('id', 'unknown')})")
    return ", ".join(rendered) if rendered else "无"


def _full_schedule_dict(segment: ScheduleSegment) -> dict[str, object]:
    return {
        "npc_id": segment.npc_id,
        "day": segment.day,
        "start_minute": segment.start_minute,
        "duration_minutes": segment.duration_minutes,
        "end_minute": segment.end_minute,
        "location_id": segment.location_id,
        "intent": segment.intent,
        "subtasks": list(segment.subtasks),
    }


def _schedule_completion_dict(completion) -> dict[str, object]:
    return {
        "npc_id": completion.npc_id,
        "day": completion.day,
        "start_minute": completion.start_minute,
        "location_id": completion.location_id,
        "note": completion.note,
    }


def _resident_day_plan_dict(day_plan: ResidentDayPlan | None) -> dict[str, object] | None:
    if day_plan is None:
        return None
    return {
        "day": day_plan.day,
        "currently": day_plan.currently,
        "wake_up_minute": day_plan.wake_up_minute,
        "daily_intentions": list(day_plan.daily_intentions),
        "planning_evidence": list(day_plan.planning_evidence),
        "validation": dict(day_plan.validation),
        "schedule_summary": day_plan.schedule_summary,
        "day_summary": day_plan.day_summary,
        "started_minute": day_plan.started_minute,
        "ended_minute": day_plan.ended_minute,
    }


def _schedule_summary(schedule: list[ScheduleSegment]) -> str:
    if not schedule:
        return "无日程"
    return "；".join(
        f"{_minute_label(segment.start_minute)}-{_minute_label(segment.end_minute)} "
        f"{segment.location_id} {segment.intent}"
        for segment in schedule
    )


def _loop_guard_target(item: dict[str, object]) -> str:
    facts = item.get("facts")
    if not isinstance(facts, dict):
        return ""
    for key in ("to", "object_id", "target_npc_id", "location_id"):
        value = facts.get(key)
        if value:
            return str(value)
    return ""


def _schedule_from_agent_response(response: AgentResponse) -> list[ScheduleSegment]:
    text = (
        response.structured_output.strip()
        or response.dialogue.strip()
        or response.inner_thought.strip()
        or response.reflection.strip()
    )
    payload = _parse_schedule_plan_json(text)
    schedule_items = payload.get("schedule")
    if "schedule" not in payload:
        raise ValueError("missing_schedule")
    if not isinstance(schedule_items, list):
        raise ValueError("invalid_schedule_plan")

    segments: list[ScheduleSegment] = []
    for item in schedule_items:
        if not isinstance(item, dict):
            raise ValueError("invalid_schedule_plan")
        try:
            npc_id = str(item["npc_id"])
            start_minute = int(item["start_minute"])
            duration_minutes = int(item["duration_minutes"])
            location_id = str(item["location_id"])
            intent = str(item["intent"])
            subtasks_raw = item.get("subtasks", [])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("invalid_schedule_plan") from exc
        if not isinstance(subtasks_raw, list):
            raise ValueError("invalid_schedule_plan")
        segments.append(
            ScheduleSegment(
                npc_id=npc_id,
                start_minute=start_minute,
                duration_minutes=duration_minutes,
                location_id=location_id,
                intent=intent,
                subtasks=[str(subtask) for subtask in subtasks_raw],
            )
        )
    return segments


def _schedule_within_planning_window(
    *,
    npc_id: str,
    schedule: list[ScheduleSegment],
    fallback_schedule: list[ScheduleSegment],
    start_minute: int,
    end_minute: int,
) -> list[ScheduleSegment]:
    in_window = [
        segment
        for segment in schedule
        if (
            segment.npc_id == npc_id
            and start_minute <= segment.start_minute
            and segment.end_minute <= end_minute
        )
    ]
    if any(segment.start_minute <= start_minute < segment.end_minute for segment in in_window):
        return in_window

    fallback = [
        segment
        for segment in fallback_schedule
        if (
            segment.npc_id == npc_id
            and start_minute <= segment.start_minute
            and segment.end_minute <= end_minute
        )
    ]
    if fallback:
        return fallback
    return in_window


def _parse_schedule_plan_json(text: str) -> dict[str, Any]:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    if not stripped.startswith("{"):
        start = stripped.find("{")
        end = stripped.rfind("}")
        if start >= 0 and end > start:
            stripped = stripped[start : end + 1]
    try:
        payload = json.loads(stripped)
    except json.JSONDecodeError as exc:
        raise ValueError("invalid_schedule_plan") from exc
    if not isinstance(payload, dict):
        raise ValueError("invalid_schedule_plan")
    return payload
