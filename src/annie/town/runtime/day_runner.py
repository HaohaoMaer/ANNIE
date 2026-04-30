"""Schedule runners for TownWorldEngine smoke validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from annie.npc.context import AgentContext
from annie.npc.response import AgentResponse
from annie.town.engine import TownWorldEngine
from annie.town.domain import ScheduleSegment


class TownAgent(Protocol):
    def run(self, context: AgentContext) -> AgentResponse:
        ...


@dataclass
class ScheduleStepTrace:
    step: int
    start_location_id: str | None
    end_location_id: str | None
    dialogue: str = ""
    action_count: int = 0


@dataclass
class ScheduleSegmentTrace:
    segment: ScheduleSegment
    status: str
    final_location_id: str | None
    steps: list[ScheduleStepTrace] = field(default_factory=list)
    note: str = ""


@dataclass
class TownDayRunResult:
    npc_id: str
    segments: list[ScheduleSegmentTrace]

    @property
    def ok(self) -> bool:
        return all(segment.status == "completed" for segment in self.segments)


def run_single_npc_day(
    engine: TownWorldEngine,
    agent: TownAgent,
    npc_id: str,
    *,
    max_steps_per_segment: int = 6,
) -> TownDayRunResult:
    """Run one NPC through its world-owned daily schedule.

    Each schedule segment resets the simulated clock to the segment start. The
    global tick loop is intentionally not used here; this runner is a narrow
    smoke harness for validating that a real NPCAgent can drive world-owned town
    tools to satisfy schedule objectives.
    """
    traces: list[ScheduleSegmentTrace] = []
    for segment in sorted(engine.state.schedule_for(npc_id), key=lambda item: item.start_minute):
        engine.state.clock.minute = segment.start_minute
        trace = ScheduleSegmentTrace(
            segment=segment,
            status="running",
            final_location_id=engine.state.location_id_for(npc_id),
        )

        for step in range(1, max_steps_per_segment + 1):
            if engine.state.is_schedule_segment_complete(npc_id, segment):
                break

            start_location = engine.state.location_id_for(npc_id)
            context = engine.build_context(
                npc_id,
                _segment_event(segment, step),
            )
            response = agent.run(context)
            for action in response.actions:
                engine.execute_action(npc_id, action)
            engine.handle_response(npc_id, response)

            end_location = engine.state.location_id_for(npc_id)
            trace.steps.append(
                ScheduleStepTrace(
                    step=step,
                    start_location_id=start_location,
                    end_location_id=end_location,
                    dialogue=response.dialogue,
                    action_count=len(response.actions),
                )
            )

            if engine.state.is_schedule_segment_complete(npc_id, segment):
                break
            if end_location == segment.location_id:
                engine.finish_schedule_segment(npc_id, "已到达日程目标地点")
                break

        trace.final_location_id = engine.state.location_id_for(npc_id)
        if engine.state.is_schedule_segment_complete(npc_id, segment):
            trace.status = "completed"
        elif trace.final_location_id == segment.location_id:
            trace.status = "completed"
        else:
            trace.status = "failed"
            trace.note = "达到步数上限，但尚未满足日程目标"
        traces.append(trace)

    return TownDayRunResult(npc_id=npc_id, segments=traces)


def _segment_event(segment: ScheduleSegment, step: int) -> str:
    return (
        f"日程步骤 {step}：当前日程段为 "
        f"{_minute_label(segment.start_minute)}-{_minute_label(segment.end_minute)}, "
        f"目标='{segment.intent}'，目标地点='{segment.location_id}'。"
        "请使用小镇工具执行：必要时先 observe 查看本地状态；如果需要移动，"
        "只能通过明确出口逐步 move_to；需要消耗时间时使用 wait；"
        "当前日程段完成后调用 finish_schedule_segment。"
    )


def _minute_label(minute: int) -> str:
    hours, minutes = divmod(minute, 60)
    return f"{hours:02d}:{minutes:02d}"
