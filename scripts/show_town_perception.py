"""Print a deterministic bounded-perception smoke snapshot for TownWorld."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import chromadb

from annie.town import TownEvent, TownObject, TownPerceptionPolicy, TownWorldEngine
from annie.town.content import create_small_town_state


def main() -> int:
    with tempfile.TemporaryDirectory(prefix="annie_town_perception_") as tmp:
        tmp_path = Path(tmp)
        engine = TownWorldEngine(
            create_small_town_state(),
            chroma_client=chromadb.PersistentClient(path=str(tmp_path / "vector_store")),
            history_dir=tmp_path / "history",
            perception_policy=TownPerceptionPolicy(
                max_events=2,
                max_objects=2,
                max_npcs=1,
                max_exits=2,
            ),
        )
        _arrange_scene(engine)

        context = engine.build_context("alice", "观察广场上的重要变化。")
        town = context.extra["town"]
        perception = town["perception"]
        observed = engine.observe("alice")

        print("TOWN PERCEPTION SMOKE")
        print("=" * 25)
        print()
        print("[AgentContext extra.town.perception]")
        print(json.dumps(perception, ensure_ascii=False, indent=2))
        print()
        print("[Legacy town fields]")
        print(
            json.dumps(
                {
                    "visible_event_ids": town["visible_event_ids"],
                    "object_ids": town["object_ids"],
                    "visible_npc_ids": town["visible_npc_ids"],
                    "exits": town["exits"],
                    "schedule_revision": town["schedule_revision"],
                    "current_schedule": town["current_schedule"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print()
        print("[observe('alice')]")
        print(
            json.dumps(
                {
                    "local_events": observed["local_events"],
                    "objects": observed["objects"],
                    "known_locations": observed["known_locations"],
                    "known_objects": observed["known_objects"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
        print()

        checks = _checks(town, observed)
        for label, ok in checks.items():
            print(f"{'PASS' if ok else 'FAIL'} {label}")
        return 0 if all(checks.values()) else 1


def _arrange_scene(engine: TownWorldEngine) -> None:
    state = engine.state
    state.set_location("alice", "town_square")
    state.set_location("bob", "town_square")
    state.set_location("clara", "town_square")

    square = state.locations["town_square"]
    for object_id in ["aaa_marker", "bbb_marker", "ccc_marker"]:
        state.objects[object_id] = TownObject(
            id=object_id,
            name=f"测试物体 {object_id}",
            location_id="town_square",
            description=f"{object_id} 的可见描述。",
        )
        square.object_ids.append(object_id)

    state.events.extend(
        [
            TownEvent(
                id="ordinary_square",
                minute=state.clock.minute + 3,
                location_id="town_square",
                actor_id="gm",
                event_type="notice",
                summary="广场上有人张贴普通通知。",
            ),
            TownEvent(
                id="targeted_square",
                minute=state.clock.minute + 1,
                location_id="town_square",
                actor_id="gm",
                event_type="notice",
                summary="有人专门请 Alice 处理公告栏旁的情况。",
                target_ids=["alice"],
            ),
            TownEvent(
                id="urgent_square",
                minute=state.clock.minute,
                location_id="town_square",
                actor_id="gm",
                event_type="urgent",
                summary="广场中央响起紧急铃声。",
            ),
            TownEvent(
                id="hidden_square",
                minute=state.clock.minute + 4,
                location_id="town_square",
                actor_id="gm",
                event_type="secret",
                summary="隐藏事件不应出现。",
                visible=False,
            ),
            TownEvent(
                id="remote_cafe",
                minute=state.clock.minute + 5,
                location_id="cafe",
                actor_id="gm",
                event_type="urgent",
                summary="咖啡馆远处紧急事件不应从广场看到。",
            ),
        ]
    )


def _checks(town: dict[str, object], observed: dict[str, object]) -> dict[str, bool]:
    context_events = list(town["visible_event_ids"])
    observe_events = [event["id"] for event in observed["local_events"]]
    context_objects = list(town["object_ids"])
    observe_objects = [obj["id"] for obj in observed["objects"]]
    known_locations = {row["id"] for row in observed["known_locations"]}
    known_objects = {row["id"] for row in observed["known_objects"]}

    return {
        "context and observe select the same events": context_events == observe_events,
        "context and observe select the same objects": context_objects == observe_objects,
        "hidden and remote events are excluded": not {
            "hidden_square",
            "remote_cafe",
        }.intersection(context_events),
        "targeted and urgent events survive tight event budget": context_events
        == ["targeted_square", "urgent_square"],
        "spatial memory stays separate from visible content": bool(
            {"cafe", "library", "clinic"}.intersection(known_locations)
        )
        and bool({"cafe_counter", "bookshelf"}.intersection(known_objects))
        and not set(context_objects).intersection(known_objects),
    }


if __name__ == "__main__":
    raise SystemExit(main())
