from __future__ import annotations

import json
from pathlib import Path

import chromadb
import pytest

from annie.npc.context import AgentContext
from annie.npc.graph_registry import AgentGraphID
from annie.npc.response import ActionRequest, AgentResponse, MemoryUpdate
from annie.npc.routes import AgentRoute
from annie.npc.tools.base_tool import ToolContext
from annie.town import (
    Location,
    ScheduleSegment,
    TownClock,
    TownEvent,
    TownResidentState,
    TownState,
    TownWorldEngine,
    create_small_town_state,
    run_single_npc_day,
)
from annie.town.domain import CurrentAction
from annie.town.prompt_policy import render_conversation_close_hint


def _town_engine(tmp_path: Path) -> TownWorldEngine:
    return TownWorldEngine(
        create_small_town_state(),
        chroma_client=chromadb.PersistentClient(path=str(tmp_path / "vs")),
        history_dir=tmp_path / "history",
    )


class _PlanningAgent:
    def __init__(self, text: str) -> None:
        self.text = text
        self.contexts: list[AgentContext] = []

    def run(self, context: AgentContext) -> AgentResponse:
        self.contexts.append(context)
        return AgentResponse(dialogue=self.text)


def test_small_town_fixture_has_expected_shape() -> None:
    state = create_small_town_state()

    assert len(state.locations) >= 5
    assert 3 <= len(state.npc_locations) <= 5
    assert set(state.npc_locations) == {"alice", "bob", "clara"}
    assert set(state.residents) == {"alice", "bob", "clara"}

    for npc_id, location_id in state.npc_locations.items():
        assert npc_id in state.locations[location_id].occupant_ids
        assert state.residents[npc_id].location_id == location_id
        assert state.residents[npc_id].spatial_memory.known_location_ids


def test_town_state_constructs_residents_from_legacy_fields() -> None:
    schedule = [
        ScheduleSegment(
            npc_id="alice",
            start_minute=8 * 60,
            duration_minutes=30,
            location_id="home_alice",
            intent="吃早餐",
        )
    ]
    action = CurrentAction(
        npc_id="alice",
        action_type="wait",
        location_id="home_alice",
        start_minute=8 * 60,
        duration_minutes=5,
        status="waiting",
    )

    state = TownState(
        locations={"home_alice": Location(id="home_alice", name="Alice 的家")},
        npc_locations={"alice": "home_alice"},
        schedules={"alice": schedule},
        current_actions={"alice": action},
    )

    resident = state.resident_for("alice")
    assert resident is not None
    assert resident.location_id == "home_alice"
    assert resident.schedule is schedule
    assert resident.current_action is action
    assert state.npc_locations["alice"] == "home_alice"
    assert state.schedules["alice"] is resident.schedule
    assert state.current_actions["alice"] is action


def test_town_state_syncs_legacy_mirrors_from_residents() -> None:
    schedule = [
        ScheduleSegment(
            npc_id="alice",
            start_minute=8 * 60,
            duration_minutes=30,
            location_id="home_alice",
            intent="吃早餐",
        )
    ]
    action = CurrentAction(
        npc_id="alice",
        action_type="wait",
        location_id="home_alice",
        start_minute=8 * 60,
        duration_minutes=5,
        status="waiting",
    )

    state = TownState(
        locations={"home_alice": Location(id="home_alice", name="Alice 的家")},
        residents={
            "alice": TownResidentState(
                npc_id="alice",
                location_id="home_alice",
                schedule=schedule,
                current_action=action,
            )
        },
    )

    assert state.npc_locations == {"alice": "home_alice"}
    assert state.schedules["alice"] is schedule
    assert state.current_actions["alice"] is action
    assert state.locations["home_alice"].occupant_ids == ["alice"]


def test_objects_are_bound_to_locations() -> None:
    state = create_small_town_state()

    for obj in state.objects.values():
        assert obj.location_id in state.locations
        assert obj.id in state.locations[obj.location_id].object_ids


def test_move_updates_location_occupancy() -> None:
    state = create_small_town_state()

    result = state.move_npc("alice", "town_square")

    assert result.ok is True
    assert result.from_location_id == "home_alice"
    assert result.to_location_id == "town_square"
    assert "alice" not in state.locations["home_alice"].occupant_ids
    assert "alice" in state.locations["town_square"].occupant_ids
    assert state.npc_locations["alice"] == "town_square"
    assert state.residents["alice"].location_id == "town_square"
    assert result.travel_minutes == 5


def test_set_location_updates_resident_legacy_and_occupants() -> None:
    state = create_small_town_state()

    state.set_location("alice", "town_square")

    assert state.residents["alice"].location_id == "town_square"
    assert state.npc_locations["alice"] == "town_square"
    assert "alice" not in state.locations["home_alice"].occupant_ids
    assert "alice" in state.locations["town_square"].occupant_ids


def test_move_rejects_unreachable_destination_without_changing_state() -> None:
    state = create_small_town_state()

    result = state.move_npc("alice", "library")

    assert result.ok is False
    assert result.reason == "unreachable_destination"
    assert result.reachable == ["town_square"]
    assert state.npc_locations["alice"] == "home_alice"
    assert "alice" in state.locations["home_alice"].occupant_ids
    assert "alice" not in state.locations["library"].occupant_ids


def test_move_rejects_unknown_npc_and_destination() -> None:
    state = create_small_town_state()

    unknown_npc = state.move_npc("nobody", "town_square")
    unknown_destination = state.move_npc("alice", "moon")

    assert unknown_npc.ok is False
    assert unknown_npc.reason == "unknown_npc"
    assert unknown_destination.ok is False
    assert unknown_destination.reason == "unknown_destination"
    assert state.npc_locations["alice"] == "home_alice"


def test_current_schedule_segment_uses_simulated_minutes() -> None:
    state = create_small_town_state()

    breakfast = state.current_schedule_segment("alice", minute=8 * 60)
    coffee = state.current_schedule_segment("alice", minute=9 * 60)
    none = state.current_schedule_segment("alice", minute=11 * 60)

    assert breakfast is not None
    assert breakfast.location_id == "home_alice"
    assert breakfast.intent == "吃早餐"
    assert coffee is not None
    assert coffee.location_id == "cafe"
    assert coffee.intent == "买咖啡"
    assert none is None


def test_schedule_and_current_action_access_use_resident_state() -> None:
    state = TownState(
        clock=TownClock(day=1, minute=8 * 60, stride_minutes=10),
        locations={"cafe": Location(id="cafe", name="咖啡馆")},
        residents={
            "bob": TownResidentState(
                npc_id="bob",
                location_id="cafe",
                schedule=[
                    ScheduleSegment(
                        npc_id="bob",
                        start_minute=8 * 60,
                        duration_minutes=60,
                        location_id="cafe",
                        intent="准备咖啡",
                    )
                ],
            )
        },
    )
    action = CurrentAction(
        npc_id="bob",
        action_type="wait",
        location_id="cafe",
        start_minute=8 * 60,
        duration_minutes=10,
        status="waiting",
    )

    assert state.current_schedule_segment("bob").intent == "准备咖啡"

    state.set_current_action("bob", action)
    assert state.current_action_for("bob") is action
    assert state.current_actions["bob"] is action

    state.clear_current_action("bob")
    assert state.current_action_for("bob") is None
    assert "bob" not in state.current_actions


def test_current_action_for_syncs_direct_legacy_write_to_resident() -> None:
    state = create_small_town_state()
    action = CurrentAction(
        npc_id="bob",
        action_type="wait",
        location_id="cafe",
        start_minute=8 * 60,
        duration_minutes=5,
        status="waiting",
    )

    state.current_actions["bob"] = action

    assert state.current_action_for("bob") is action
    assert state.residents["bob"].current_action is action


def test_set_schedule_updates_resident_and_legacy_mirror() -> None:
    state = create_small_town_state()
    schedule = [
        ScheduleSegment(
            npc_id="alice",
            start_minute=10 * 60,
            duration_minutes=30,
            location_id="library",
            intent="还书",
        )
    ]

    state.set_schedule("alice", schedule)

    assert state.residents["alice"].schedule is schedule
    assert state.schedules["alice"] is schedule
    assert state.current_schedule_segment("alice", minute=10 * 60).intent == "还书"


def test_town_world_engine_builds_minimal_agent_context(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    context = engine.build_context("bob", "开始清晨日程。")

    assert isinstance(context, AgentContext)
    assert context.npc_id == "bob"
    assert context.input_event == "开始清晨日程。"
    assert context.graph_id == AgentGraphID.ACTION_EXECUTOR_DEFAULT
    assert "咖啡馆" in context.situation
    assert "咖啡馆柜台" in context.situation
    assert "全局模拟每 tick 推进 10 分钟" in context.situation
    assert "当前日程剩余时间：120 分钟" in context.situation
    assert "town_square: 3 分钟" in context.situation
    assert "准备咖啡馆营业" in context.situation
    assert context.extra["town"]["location_id"] == "cafe"
    assert context.extra["town"]["exit_travel_minutes"] == {"town_square": 3}
    assert context.extra["town"]["current_schedule_remaining_minutes"] == 120
    assert context.extra["town"]["current_schedule_progress"] == "本日程段尚未记录成功的世界行动"
    assert {tool.name for tool in context.tools} == {
        "plan_todo",
        "move_to",
            "observe",
            "speak_to",
            "start_conversation",
            "interact_with",
        "wait",
        "finish_schedule_segment",
    }
    assert "必须通过小镇工具改变世界状态" in context.world_rules
    assert "不能只用自然语言描述行动" in context.world_rules
    assert "目标达成后不要为了填满剩余时间重复同类交互" in context.world_rules
    assert "日程安排是默认最高优先目标" in context.world_rules
    assert "不要再用 observe 作为行动前的默认步骤" in context.world_rules
    assert "除非紧急事件、直接请求或确认不会影响按时完成" in context.situation


def test_town_world_engine_renders_resident_schedule_and_current_action(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    action = CurrentAction(
        npc_id="bob",
        action_type="wait",
        location_id="cafe",
        start_minute=8 * 60,
        duration_minutes=10,
        status="waiting",
        summary="等待咖啡机预热。",
    )
    engine.state.set_current_action("bob", action)

    context = engine.build_context("bob", "继续清晨日程。")

    assert "准备咖啡馆营业" in context.situation
    assert "wait 从 08:00 到 08:10" in context.situation
    assert context.extra["town"]["current_schedule"]["intent"] == "准备咖啡馆营业"
    assert context.extra["town"]["current_action"]["action_type"] == "wait"


def test_context_hints_finish_after_repeated_schedule_progress(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    engine.interact_with("bob", "cafe_counter", "检查柜台")
    engine.state.clock.minute += 10
    engine.interact_with("bob", "pastry_case", "整理点心")
    engine.state.clock.minute += 10
    engine.interact_with("bob", "cafe_counter", "煮咖啡")
    engine.state.clock.minute += 10

    context = engine.build_context("bob", "继续准备咖啡馆营业。")

    assert "本日程段已有 3 个成功行动" in context.situation
    assert "应优先调用 finish_schedule_segment" in context.situation
    assert "而不是继续重复同类交互" in context.situation
    assert "finish_schedule_segment" in context.extra["town"]["current_schedule_completion_hint"]
    assert "当前活动决策提示" in context.situation
    assert "对象选择" in context.situation
    assert "等待判断" in context.situation
    assert "对话策略" in context.situation
    assert "重复检查" in context.situation
    assert "schedule_decision_hint" in context.extra["town"]["prompt_policy"]


def test_plan_day_for_resident_accepts_deterministic_schedule(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    schedule = [
        ScheduleSegment(
            npc_id="alice",
            start_minute=8 * 60,
            duration_minutes=30,
            location_id="town_square",
            intent="查看公告板",
        ),
        ScheduleSegment(
            npc_id="alice",
            start_minute=9 * 60,
            duration_minutes=30,
            location_id="cafe",
            intent="买咖啡",
        ),
    ]

    accepted = engine.plan_day_for_resident("alice", list(reversed(schedule)))

    assert accepted == schedule
    assert engine.state.residents["alice"].schedule == schedule
    assert engine.state.schedules["alice"] == schedule

    context = engine.build_context("alice", "开始新的一天。")
    assert "查看公告板" in context.situation
    assert context.extra["town"]["current_schedule"]["intent"] == "查看公告板"


def test_build_daily_planning_context_is_tool_free_and_town_owned(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    context = engine.build_daily_planning_context(
        "alice",
        start_minute=8 * 60,
        end_minute=10 * 60,
    )

    town = context.extra["town"]
    assert context.tools == []
    assert context.route == AgentRoute.STRUCTURED_JSON
    assert context.graph_id == AgentGraphID.OUTPUT_STRUCTURED_JSON
    assert town["planning"] is True
    assert town["npc_id"] == "alice"
    assert town["current_location_id"] == "home_alice"
    assert town["planning_window"]["start_minute"] == 8 * 60
    assert {location["id"] for location in town["known_locations"]} >= {
        "town_square",
        "cafe",
    }
    assert "move_to" in context.extra["disabled_tools"]
    assert '"schedule"' in context.situation


def test_generate_day_plan_for_resident_accepts_agent_json(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    agent = _PlanningAgent(
        json.dumps(
            {
                "schedule": [
                    {
                        "npc_id": "alice",
                        "start_minute": 8 * 60,
                        "duration_minutes": 30,
                        "location_id": "town_square",
                        "intent": "查看公告板",
                    },
                    {
                        "npc_id": "alice",
                        "start_minute": 9 * 60,
                        "duration_minutes": 30,
                        "location_id": "cafe",
                        "intent": "买咖啡",
                    },
                ]
            },
            ensure_ascii=False,
        )
    )

    accepted = engine.generate_day_plan_for_resident(
        "alice",
        agent,
        start_minute=8 * 60,
        end_minute=10 * 60,
    )

    assert [segment.intent for segment in accepted] == ["查看公告板", "买咖啡"]
    assert engine.state.residents["alice"].schedule == accepted
    assert engine.state.schedules["alice"] == accepted
    assert agent.contexts[0].tools == []

    context = engine.build_context("alice", "开始 planning 后的新日程。")
    assert context.extra["town"]["current_schedule"]["intent"] == "查看公告板"
    assert "查看公告板" in context.situation


def test_generate_day_plan_for_resident_accepts_json_embedded_in_text(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    agent = _PlanningAgent(
        '好的，结果如下：{"schedule":[{"npc_id":"alice","start_minute":480,'
        '"duration_minutes":30,"location_id":"town_square","intent":"查看公告板"}]}'
    )

    accepted = engine.generate_day_plan_for_resident(
        "alice",
        agent,
        start_minute=8 * 60,
        end_minute=10 * 60,
    )

    assert [segment.intent for segment in accepted] == ["查看公告板"]


def test_generate_day_plan_for_resident_falls_back_when_llm_schedules_after_window(
    tmp_path,
) -> None:
    engine = _town_engine(tmp_path)
    agent = _PlanningAgent(
        json.dumps(
            {
                "schedule": [
                    {
                        "npc_id": "alice",
                        "start_minute": 10 * 60,
                        "duration_minutes": 30,
                        "location_id": "town_square",
                        "intent": "查看公告板",
                    }
                ]
            },
            ensure_ascii=False,
        )
    )

    accepted = engine.generate_day_plan_for_resident(
        "alice",
        agent,
        start_minute=8 * 60,
        end_minute=10 * 60,
    )

    assert [segment.intent for segment in accepted] == ["吃早餐", "买咖啡"]
    assert engine.build_context("alice", "检查日程。").extra["town"]["current_schedule"][
        "intent"
    ] == "吃早餐"


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("not json", "invalid_schedule_plan"),
        (json.dumps({"plan": []}), "missing_schedule"),
        (json.dumps({"schedule": {}}), "invalid_schedule_plan"),
    ],
)
def test_generate_day_plan_for_resident_rejects_invalid_agent_json(
    tmp_path,
    text: str,
    error: str,
) -> None:
    engine = _town_engine(tmp_path)

    with pytest.raises(ValueError, match=error):
        engine.generate_day_plan_for_resident(
            "alice",
            _PlanningAgent(text),
            start_minute=8 * 60,
            end_minute=10 * 60,
        )


@pytest.mark.parametrize(
    ("item", "error"),
    [
        (
            {
                "npc_id": "bob",
                "start_minute": 8 * 60,
                "duration_minutes": 30,
                "location_id": "town_square",
                "intent": "错误归属",
            },
            "schedule_npc_mismatch",
        ),
        (
            {
                "npc_id": "alice",
                "start_minute": 8 * 60,
                "duration_minutes": 30,
                "location_id": "moon",
                "intent": "去不存在的地点",
            },
            "unknown_schedule_location",
        ),
    ],
)
def test_generate_day_plan_for_resident_reuses_schedule_validation(
    tmp_path,
    item: dict[str, object],
    error: str,
) -> None:
    engine = _town_engine(tmp_path)
    text = json.dumps({"schedule": [item]}, ensure_ascii=False)

    with pytest.raises(ValueError, match=error):
        engine.generate_day_plan_for_resident(
            "alice",
            _PlanningAgent(text),
            start_minute=8 * 60,
            end_minute=10 * 60,
        )


def test_generate_day_plan_for_resident_rejects_overlapping_segments(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    text = json.dumps(
        {
            "schedule": [
                {
                    "npc_id": "alice",
                    "start_minute": 8 * 60,
                    "duration_minutes": 45,
                    "location_id": "home_alice",
                    "intent": "吃早餐",
                },
                {
                    "npc_id": "alice",
                    "start_minute": 8 * 60 + 30,
                    "duration_minutes": 30,
                    "location_id": "town_square",
                    "intent": "查看公告板",
                },
            ]
        },
        ensure_ascii=False,
    )

    with pytest.raises(ValueError, match="overlapping_schedule_segments"):
        engine.generate_day_plan_for_resident(
            "alice",
            _PlanningAgent(text),
            start_minute=8 * 60,
            end_minute=10 * 60,
        )


def test_plan_day_for_resident_rejects_invalid_schedule(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    with pytest.raises(ValueError, match="unknown_resident"):
        engine.plan_day_for_resident("nobody", [])

    with pytest.raises(ValueError, match="schedule_npc_mismatch"):
        engine.plan_day_for_resident(
            "alice",
            [
                ScheduleSegment(
                    npc_id="bob",
                    start_minute=8 * 60,
                    duration_minutes=30,
                    location_id="town_square",
                    intent="错误归属",
                )
            ],
        )

    with pytest.raises(ValueError, match="unknown_schedule_location"):
        engine.plan_day_for_resident(
            "alice",
            [
                ScheduleSegment(
                    npc_id="alice",
                    start_minute=8 * 60,
                    duration_minutes=30,
                    location_id="moon",
                    intent="去不存在的地点",
                )
            ],
        )

    with pytest.raises(ValueError, match="overlapping_schedule_segments"):
        engine.plan_day_for_resident(
            "alice",
            [
                ScheduleSegment(
                    npc_id="alice",
                    start_minute=8 * 60,
                    duration_minutes=45,
                    location_id="home_alice",
                    intent="吃早餐",
                ),
                ScheduleSegment(
                    npc_id="alice",
                    start_minute=8 * 60 + 30,
                    duration_minutes=30,
                    location_id="town_square",
                    intent="查看公告板",
                ),
            ],
        )


def test_context_object_selection_lists_only_current_location_objects(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    context = engine.build_context("bob", "继续准备营业。")
    object_hint = context.extra["town"]["prompt_policy"]["object_selection_hint"]

    assert "咖啡馆柜台 (cafe_counter)" in object_hint
    assert "点心陈列柜 (pastry_case)" in object_hint
    assert "早餐桌" not in object_hint
    assert "归还书车" not in object_hint


def test_bob_schedule_policy_suggests_finish_after_distinct_prep_objects(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    engine.interact_with("bob", "cafe_counter", "检查柜台")
    engine.state.clock.minute += 10
    engine.interact_with("bob", "pastry_case", "整理点心柜")

    context = engine.build_context("bob", "继续准备咖啡馆营业。")
    schedule_hint = context.extra["town"]["prompt_policy"]["schedule_decision_hint"]

    assert "准备类目标已有足够证据" in schedule_hint
    assert "finish_schedule_segment" in schedule_hint


def test_clara_schedule_policy_suggests_finish_after_returns_and_shelf(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    engine.interact_with("clara", "returns_cart", "整理归还书籍")
    engine.state.clock.minute += 10
    engine.interact_with("clara", "bookshelf", "放回书架")

    context = engine.build_context("clara", "继续整理归还的书籍。")
    schedule_hint = context.extra["town"]["prompt_policy"]["schedule_decision_hint"]

    assert "整理类目标已有归还/书架处理证据" in schedule_hint
    assert "finish_schedule_segment" in schedule_hint


def test_alice_coffee_policy_suggests_finish_after_order_at_cafe(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.clock.minute = 9 * 60
    engine.state.move_npc("alice", "town_square")
    engine.state.move_npc("alice", "cafe")

    engine.interact_with("alice", "cafe_counter", "点咖啡并取咖啡")

    context = engine.build_context("alice", "继续买咖啡。")
    schedule_hint = context.extra["town"]["prompt_policy"]["schedule_decision_hint"]

    assert "消费/取物类目标已有直接相关行动" in schedule_hint
    assert "finish_schedule_segment" in schedule_hint


def test_wait_policy_prefers_wait_only_when_visible_npc_busy(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.move_npc("alice", "cafe")

    context_without_busy = engine.build_context("alice", "买咖啡。")
    assert "不要用 wait 空转" in context_without_busy.extra["town"]["prompt_policy"][
        "wait_decision_hint"
    ]

    engine.state.current_actions["bob"] = CurrentAction(
        npc_id="bob",
        action_type="interact_with",
        location_id="cafe",
        start_minute=engine.state.clock.minute,
        duration_minutes=10,
        status="succeeded",
        summary="正在准备咖啡。",
    )
    context_with_busy = engine.build_context("alice", "买咖啡。")

    assert "当前忙碌/占用的可见 NPC：bob" in context_with_busy.extra["town"][
        "prompt_policy"
    ]["wait_decision_hint"]


def test_conversation_close_policy_distinguishes_questions_and_goodbyes() -> None:
    assert "应继续回应" in render_conversation_close_hint("今天有什么咖啡推荐吗？")
    assert "可结束会话" in render_conversation_close_hint("谢谢你，我先去坐下了。")


def test_repeat_guard_warns_after_repeated_speak_to_text(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.move_npc("alice", "cafe")

    engine.speak_to("alice", "bob", "早上好。")
    engine.state.clock.minute += engine.speak_cooldown_minutes
    engine.speak_to("alice", "bob", "早上好。")

    context = engine.build_context("alice", "继续互动。")

    assert "重复 speak_to 文本" in context.extra["town"]["prompt_policy"]["repeat_guard_hint"]


def test_small_town_fixture_has_interactable_schedule_objects(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    breakfast = engine.interact_with("alice", "breakfast_table", "吃早餐")
    bob_counter = engine.interact_with("bob", "cafe_counter", "准备营业")
    clara_returns = engine.interact_with("clara", "returns_cart", "整理归还书籍")

    assert breakfast.status == "succeeded"
    assert bob_counter.status == "succeeded"
    assert clara_returns.status == "succeeded"
    assert "简单早餐" in engine.state.objects["breakfast_table"].description
    assert "可颂和松饼" in engine.state.objects["pastry_case"].description
    assert "刚归还的书" in engine.state.objects["returns_cart"].description


def test_town_world_engine_executes_move_action(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    action = ActionRequest(type="move", payload={"to": "town_square"})

    result = engine.execute_action("alice", action)

    assert result.status == "succeeded"
    assert result.action_id == action.action_id
    assert result.facts["from"] == "home_alice"
    assert result.facts["to"] == "town_square"
    assert engine.state.npc_locations["alice"] == "town_square"


def test_town_world_engine_rejects_unreachable_move_action(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    action = ActionRequest(type="move", payload={"to": "library"})

    result = engine.execute_action("alice", action)

    assert result.status == "failed"
    assert result.reason == "unreachable_destination"
    assert result.facts["reachable"] == ["town_square"]
    assert engine.state.npc_locations["alice"] == "home_alice"


def test_injected_move_to_tool_updates_occupancy(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    context = engine.build_context("alice", "移动到广场。")
    tool = next(tool for tool in context.tools if tool.name == "move_to")

    result = tool.safe_call(
        {"destination_id": "town_square"},
        ToolContext(agent_context=context, runtime={}),
    )

    assert result["success"] is True
    assert result["result"]["status"] == "succeeded"
    assert engine.state.npc_locations["alice"] == "town_square"
    assert "alice" in engine.state.locations["town_square"].occupant_ids
    assert engine.action_log[-1]["action_type"] == "move_to"


def test_observe_tool_returns_only_current_location_visibility(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.move_npc("alice", "town_square")
    engine.state.events.append(
        TownEvent(
            id="local",
            minute=engine.state.clock.minute,
            location_id="town_square",
            actor_id="bob",
            event_type="notice",
            summary="Bob 在广场贴了一张便条。",
        )
    )
    engine.state.events.append(
        TownEvent(
            id="remote",
            minute=engine.state.clock.minute,
            location_id="cafe",
            actor_id="bob",
            event_type="hidden",
            summary="Bob 把一个杯子藏在咖啡馆柜台后面。",
        )
    )
    context = engine.build_context("alice", "观察本地环境。")
    tool = next(tool for tool in context.tools if tool.name == "observe")

    result = tool.safe_call({}, ToolContext(agent_context=context, runtime={}))

    assert result["success"] is True
    observed = result["result"]
    assert observed["facts"]["duration_minutes"] == 1
    observed = observed["facts"]
    assert observed["location"]["id"] == "town_square"
    assert observed["exits"] == ["home_alice", "cafe", "library", "clinic"]
    assert observed["objects"][0]["id"] == "notice_board"
    assert [event["id"] for event in observed["local_events"]] == ["local"]
    assert "Bob 在广场贴了一张便条" in context.situation
    assert "藏在咖啡馆柜台" not in context.situation


def test_wait_tool_updates_current_action_without_advancing_clock(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    context = engine.build_context("alice", "稍作等待。")
    tool = next(tool for tool in context.tools if tool.name == "wait")
    before = engine.state.clock.minute

    result = tool.safe_call(
        {"minutes": 15},
        ToolContext(agent_context=context, runtime={}),
    )

    assert result["success"] is True
    assert result["result"]["facts"]["minutes"] == 15
    assert result["result"]["facts"]["duration_minutes"] == 15
    assert result["result"]["facts"]["end_minute"] == before + 15
    assert engine.state.clock.minute == before
    assert engine.state.current_actions["alice"].duration_minutes == 15


def test_finish_schedule_segment_tool_marks_current_segment_done(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    context = engine.build_context("alice", "完成早餐日程。")
    tool = next(tool for tool in context.tools if tool.name == "finish_schedule_segment")

    result = tool.safe_call(
        {"note": "早餐已完成"},
        ToolContext(agent_context=context, runtime={}),
    )

    assert result["success"] is True
    assert result["result"]["status"] == "succeeded"
    assert result["result"]["facts"]["duration_minutes"] == 0
    segment = engine.state.current_schedule_segment("alice")
    assert segment is not None
    assert engine.state.is_schedule_segment_complete("alice", segment)


class _ToolDrivingAgent:
    def run(self, context: AgentContext) -> AgentResponse:
        town = context.extra["town"]
        target = town["current_schedule_target_location_id"]
        location = town["location_id"]
        exits = town["exits"]
        runtime: dict = {}
        tool_context = ToolContext(agent_context=context, runtime=runtime)
        if location == target:
            tool = next(t for t in context.tools if t.name == "finish_schedule_segment")
            tool.safe_call({"note": "已经在目标地点"}, tool_context)
            return AgentResponse(dialogue="已完成")
        destination = target if target in exits else exits[0]
        tool = next(t for t in context.tools if t.name == "move_to")
        tool.safe_call({"destination_id": destination}, tool_context)
        return AgentResponse(dialogue=f"移动到 {destination}")


def test_schedule_runner_sets_clock_and_completes_target_location(tmp_path) -> None:
    engine = _town_engine(tmp_path)

    result = run_single_npc_day(
        engine,
        _ToolDrivingAgent(),
        "alice",
        max_steps_per_segment=4,
    )

    assert result.ok is True
    assert [segment.segment.start_minute for segment in result.segments] == [480, 540]
    assert engine.state.npc_locations["alice"] == "cafe"
    assert engine.state.clock.minute == 540
    assert len(engine.state.completed_schedule_segments["alice"]) == 2
    assert any(item["action_type"] == "move_to" for item in engine.action_log)


def test_schedule_runner_traces_resident_location(tmp_path) -> None:
    engine = _town_engine(tmp_path)
    engine.state.residents["alice"].location_id = "town_square"
    engine.state.npc_locations["alice"] = "home_alice"
    engine.plan_day_for_resident(
        "alice",
        [
            ScheduleSegment(
                npc_id="alice",
                start_minute=8 * 60,
                duration_minutes=30,
                location_id="cafe",
                intent="买咖啡",
            )
        ],
    )

    result = run_single_npc_day(
        engine,
        _ToolDrivingAgent(),
        "alice",
        max_steps_per_segment=2,
    )

    assert result.ok is True
    assert result.segments[0].steps[0].start_location_id == "town_square"
    assert result.segments[0].final_location_id == "cafe"
    assert engine.state.location_id_for("alice") == "cafe"


def test_town_engine_persists_history_jsonl(tmp_path) -> None:
    engine = TownWorldEngine(
        create_small_town_state(),
        chroma_client=chromadb.PersistentClient(path=str(tmp_path / "vs")),
        history_dir=tmp_path / "history",
    )

    engine.ingest_external("alice", "bob", "Bob 说图书馆今天很安静。")
    engine.handle_response("alice", AgentResponse(dialogue="我稍后去图书馆看看。"))

    reopened = TownWorldEngine(
        create_small_town_state(),
        chroma_client=chromadb.PersistentClient(path=str(tmp_path / "vs2")),
        history_dir=tmp_path / "history",
    )
    context = reopened.build_context("alice", "回忆早上的对话。")

    assert "[bob] Bob 说图书馆今天很安静。" in context.history
    assert "[alice] 我稍后去图书馆看看。" in context.history


def test_town_engine_uses_chroma_memory_for_grep_and_context(tmp_path) -> None:
    client = chromadb.PersistentClient(path=str(tmp_path / "vs"))
    engine = TownWorldEngine(
        create_small_town_state(),
        chroma_client=client,
        history_dir=tmp_path / "history",
    )

    memory = engine.memory_for("alice")
    memory.remember(
        "Alice 记得咖啡馆柜台下面有一把备用钥匙。",
        category="semantic",
        metadata={"location_id": "cafe"},
    )
    memory.remember(
        "Alice 认为 Bob 今天比平时更紧张。",
        category="reflection",
        metadata={"person": "bob"},
    )

    grep_hits = memory.grep("备用钥匙", category="semantic")
    context = engine.build_context("alice", "去咖啡馆之前回忆相关信息。")

    assert len(grep_hits) == 1
    assert grep_hits[0].metadata["location_id"] == "cafe"
    assert "相关长期记忆：" in context.situation
    assert "备用钥匙" in context.situation


def test_town_engine_renders_open_todos_from_persistent_memory(tmp_path) -> None:
    client = chromadb.PersistentClient(path=str(tmp_path / "vs"))
    engine = TownWorldEngine(
        create_small_town_state(),
        chroma_client=client,
        history_dir=tmp_path / "history",
    )

    engine.memory_for("alice").remember(
        "确认 Clara 是否还在诊所。",
        category="todo",
        metadata={"status": "open", "todo_id": "todo1234"},
    )

    context = engine.build_context("alice", "继续上午日程。")

    assert "[todo1234] 确认 Clara 是否还在诊所。" in context.todo


def test_town_handle_response_persists_memory_updates(tmp_path) -> None:
    client = chromadb.PersistentClient(path=str(tmp_path / "vs"))
    engine = TownWorldEngine(
        create_small_town_state(),
        chroma_client=client,
        history_dir=tmp_path / "history",
    )

    engine.handle_response(
        "alice",
        AgentResponse(
            memory_updates=[
                MemoryUpdate(
                    content="Alice 知道 Clara 上午会去诊所。",
                    type="semantic",
                    metadata={"person": "clara"},
                )
            ]
        ),
    )

    hits = engine.memory_for("alice").grep("Clara 上午", category="semantic")

    assert len(hits) == 1
    assert hits[0].metadata["source"] == "agent_response"
    assert hits[0].metadata["person"] == "clara"
