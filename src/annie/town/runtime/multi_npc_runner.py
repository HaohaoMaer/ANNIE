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
    reached_end_minute: bool = False
    all_current_schedules_complete: bool = False
    max_ticks_exhausted: bool = False

    @property
    def ok(self) -> bool:
        return not self.note


@dataclass
class TownMultiDayRunResult:
    npc_ids: list[str]
    days: list[TownMultiNpcRunResult]
    replay_paths: dict[str, Path] = field(default_factory=dict)
    note: str = ""

    @property
    def ok(self) -> bool:
        return not self.note and all(day.ok for day in self.days)


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
    reached_end_minute = end_minute is not None and engine.state.clock.minute >= end_minute
    all_current_schedules_complete = (
        end_minute is None and _all_current_schedules_complete(engine, active_npcs)
    )
    max_ticks_exhausted = False
    for _ in range(max_ticks):
        if end_minute is not None and engine.state.clock.minute >= end_minute:
            reached_end_minute = True
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
            all_current_schedules_complete = True
            break
        if end_minute is not None and engine.state.clock.minute >= end_minute:
            reached_end_minute = True
            break
    else:
        reached_end_minute = end_minute is not None and engine.state.clock.minute >= end_minute
        all_current_schedules_complete = _all_current_schedules_complete(engine, active_npcs)
        if not reached_end_minute and not (end_minute is None and all_current_schedules_complete):
            max_ticks_exhausted = True
            note = f"达到 max_ticks={max_ticks}，多 NPC 小镇运行仍未结束。"

    replay_paths: dict[str, Path] = {}
    if replay_dir is not None:
        replay_paths = engine.write_replay_artifacts(replay_dir)
    return TownMultiNpcRunResult(
        npc_ids=active_npcs,
        ticks=traces,
        replay_paths=replay_paths,
        note=note,
        reached_end_minute=reached_end_minute,
        all_current_schedules_complete=all_current_schedules_complete,
        max_ticks_exhausted=max_ticks_exhausted,
    )


def run_multi_npc_days(
    engine: TownWorldEngine,
    agent: TownAgent,
    npc_ids: list[str] | None = None,
    *,
    days: int = 2,
    start_minute: int = 8 * 60,
    end_minute: int = 10 * 60,
    max_ticks_per_day: int = 24,
    replay_dir: str | Path | None = None,
    reflection_agent: TownAgent | None = None,
) -> TownMultiDayRunResult:
    """Run a deterministic lifecycle wrapper around repeated town day ticks."""
    active_npcs = list(npc_ids) if npc_ids is not None else engine.state.resident_ids()
    day_results: list[TownMultiNpcRunResult] = []
    note = ""
    for offset in range(days):
        day = offset + 1
        engine.start_day_for_residents(
            active_npcs,
            day=day,
            start_minute=start_minute,
            end_minute=end_minute,
        )
        result = run_multi_npc_day(
            engine,
            agent,
            active_npcs,
            start_minute=start_minute,
            end_minute=end_minute,
            max_ticks=max_ticks_per_day,
            reflection_agent=reflection_agent,
        )
        day_results.append(result)
        engine.end_day_for_residents(active_npcs, day=day)
        if not result.ok:
            note = result.note
            break

    replay_paths: dict[str, Path] = {}
    if replay_dir is not None:
        replay_paths = engine.write_replay_artifacts(replay_dir)
    return TownMultiDayRunResult(
        npc_ids=active_npcs,
        days=day_results,
        replay_paths=replay_paths,
        note=note,
    )


def _all_current_schedules_complete(engine: TownWorldEngine, npc_ids: list[str]) -> bool:
    for npc_id in npc_ids:
        segment = engine.state.current_schedule_segment(npc_id)
        if segment is not None and not engine.state.is_schedule_segment_complete(npc_id, segment):
            return False
    return True
