"""Multi-NPC tick runners for TownWorldEngine validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol, cast

from annie.npc.context import AgentContext
from annie.npc.response import AgentResponse
from annie.town.engine import TownWorldEngine


class TownAgent(Protocol):
    def run(self, context: AgentContext) -> AgentResponse:
        ...


@dataclass
class TownTickTrace:
    tick: int
    minute: int
    ran_npc_ids: list[str] = field(default_factory=list)
    skipped_npc_ids: list[str] = field(default_factory=list)
    action_count: int = 0
    reflection_count: int = 0


@dataclass
class TownMultiNpcRunResult:
    npc_ids: list[str]
    ticks: list[TownTickTrace]
    replay_paths: dict[str, Path] = field(default_factory=dict)
    note: str = ""

    @property
    def ok(self) -> bool:
        return not self.note


def run_multi_npc_day(
    engine: TownWorldEngine,
    agent: TownAgent,
    npc_ids: list[str] | None = None,
    *,
    start_minute: int | None = None,
    end_minute: int | None = None,
    max_ticks: int = 48,
    replay_dir: str | Path | None = None,
    reflection_agent: TownAgent | None = None,
) -> TownMultiNpcRunResult:
    """Run active town NPCs through a bounded tick window."""
    active_npcs = list(npc_ids) if npc_ids is not None else engine.state.resident_ids()
    if start_minute is not None:
        engine.state.clock.minute = start_minute

    traces: list[TownTickTrace] = []
    note = ""
    for _ in range(max_ticks):
        if end_minute is not None and engine.state.clock.minute >= end_minute:
            break
        before_actions = len(engine.action_log)
        before_reflections = len(engine.reflection_log)
        records = engine.step(agent, active_npcs)
        checkpoint = cast(dict[str, Any], engine.replay_log[-1])
        if reflection_agent is not None:
            tick = int(checkpoint["tick"])
            for npc_id in active_npcs:
                if engine.reflection_due_for(npc_id):
                    engine.reflect_for_resident(npc_id, reflection_agent)
                    if len(engine.reflection_log) > before_reflections:
                        engine.reflection_log[-1]["tick"] = tick
            reflection_events = engine.reflection_log[before_reflections:]
            if reflection_events:
                checkpoint["snapshot"] = engine.build_replay_snapshot(
                    active_npcs,
                    minute=int(checkpoint["minute"]),
                    reflection_events=reflection_events,
                )
        reflection_count = len(engine.reflection_log) - before_reflections
        traces.append(
            TownTickTrace(
                tick=int(checkpoint["tick"]),
                minute=int(checkpoint["minute"]),
                ran_npc_ids=[str(item) for item in checkpoint["ran_npc_ids"]],
                skipped_npc_ids=[str(item) for item in checkpoint["skipped_npc_ids"]],
                action_count=len(engine.action_log) - before_actions,
                reflection_count=reflection_count,
            )
        )
        if (
            end_minute is None
            and not records
            and _all_current_schedules_complete(engine, active_npcs)
        ):
            break
        if end_minute is not None and engine.state.clock.minute >= end_minute:
            break
    else:
        if end_minute is None or engine.state.clock.minute < end_minute:
            note = f"达到 max_ticks={max_ticks}，多 NPC 小镇运行仍未结束。"

    replay_paths: dict[str, Path] = {}
    if replay_dir is not None:
        replay_paths = engine.write_replay_artifacts(replay_dir)
    return TownMultiNpcRunResult(
        npc_ids=active_npcs,
        ticks=traces,
        replay_paths=replay_paths,
        note=note,
    )


def _all_current_schedules_complete(engine: TownWorldEngine, npc_ids: list[str]) -> bool:
    for npc_id in npc_ids:
        segment = engine.state.current_schedule_segment(npc_id)
        if segment is not None and not engine.state.is_schedule_segment_complete(npc_id, segment):
            return False
    return True
