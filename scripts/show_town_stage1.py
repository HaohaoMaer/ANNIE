"""Print a terminal snapshot of the first-stage TownWorldEngine implementation."""

from __future__ import annotations

from annie.npc.response import ActionRequest
from annie.town import TownWorldEngine, create_small_town_state
from annie.town.domain import ScheduleSegment


def main() -> None:
    state = create_small_town_state()
    engine = TownWorldEngine(state)

    print("TOWN WORLD ENGINE - STAGE 1")
    print("=" * 34)
    print()
    print_world_snapshot(engine)
    print()
    print_schedules(engine)
    print()
    print_agent_context(engine, "bob")
    print()
    print_move_demo(engine)
    print()
    print_world_snapshot(engine)


def print_world_snapshot(engine: TownWorldEngine) -> None:
    state = engine.state
    print(f"[World State] {state.clock.label()}")
    for location in state.locations.values():
        exits = ", ".join(location.exits) if location.exits else "none"
        occupants = ", ".join(location.occupant_ids) if location.occupant_ids else "none"
        objects = ", ".join(location.object_ids) if location.object_ids else "none"
        print(f"- {location.id}: {location.name}")
        print(f"  exits: {exits}")
        print(f"  occupants: {occupants}")
        print(f"  objects: {objects}")


def print_schedules(engine: TownWorldEngine) -> None:
    print("[Schedules]")
    for npc_id in sorted(engine.state.npc_locations):
        print(f"- {npc_id}")
        for segment in engine.state.schedule_for(npc_id):
            print(f"  {render_schedule(segment)}")


def print_agent_context(engine: TownWorldEngine, npc_id: str) -> None:
    context = engine.build_context(npc_id, "Show me what this NPC can perceive.")
    print(f"[AgentContext for {npc_id}]")
    print(context.situation)


def print_move_demo(engine: TownWorldEngine) -> None:
    print("[Move Arbitration]")
    failed = engine.execute_action("alice", ActionRequest(type="move", payload={"to": "library"}))
    print("- alice tries home_alice -> library")
    print(f"  status: {failed.status}")
    print(f"  reason: {failed.reason}")
    print(f"  reachable: {failed.facts['reachable']}")
    print(f"  alice location after failed move: {engine.state.npc_locations['alice']}")

    succeeded = engine.execute_action(
        "alice",
        ActionRequest(type="move", payload={"to": "town_square"}),
    )
    print("- alice tries home_alice -> town_square")
    print(f"  status: {succeeded.status}")
    print(f"  observation: {succeeded.observation}")
    print(f"  alice location after successful move: {engine.state.npc_locations['alice']}")


def render_schedule(segment: ScheduleSegment) -> str:
    return (
        f"{minute_label(segment.start_minute)}-{minute_label(segment.end_minute)} "
        f"at {segment.location_id}: {segment.intent}"
    )


def minute_label(minute: int) -> str:
    hours, minutes = divmod(minute, 60)
    return f"{hours:02d}:{minutes:02d}"


if __name__ == "__main__":
    main()
