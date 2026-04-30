"""Deterministic semantic town fixtures for early TownWorldEngine validation."""

from __future__ import annotations

from annie.town.domain import (
    Location,
    ResidentSpatialMemory,
    ScheduleSegment,
    TownClock,
    TownObject,
    TownResidentState,
    TownState,
)


def create_small_town_state() -> TownState:
    """Create a 3-NPC, 5-location semantic town fixture."""
    locations = {
        "home_alice": Location(
            id="home_alice",
            name="Alice 的家",
            description="小镇边缘的一间小屋。",
            exits=["town_square"],
            exit_travel_minutes={"town_square": 5},
            object_ids=["breakfast_table"],
        ),
        "town_square": Location(
            id="town_square",
            name="小镇广场",
            description="小镇中央的广场，通向各个公共地点。",
            exits=["home_alice", "cafe", "library", "clinic"],
            exit_travel_minutes={
                "home_alice": 5,
                "cafe": 3,
                "library": 4,
                "clinic": 4,
            },
            object_ids=["notice_board"],
        ),
        "cafe": Location(
            id="cafe",
            name="咖啡馆",
            description="一间安静的咖啡馆，镇民常在这里交换晨间消息。",
            exits=["town_square"],
            exit_travel_minutes={"town_square": 3},
            object_ids=["cafe_counter", "pastry_case"],
        ),
        "library": Location(
            id="library",
            name="图书馆",
            description="一座公共图书馆，里面有长阅读桌。",
            exits=["town_square"],
            exit_travel_minutes={"town_square": 4},
            object_ids=["bookshelf", "returns_cart"],
        ),
        "clinic": Location(
            id="clinic",
            name="诊所",
            description="一间整洁的诊所，备有基础医疗用品。",
            exits=["town_square"],
            exit_travel_minutes={"town_square": 4},
            object_ids=["medicine_cabinet"],
        ),
    }
    objects = {
        "breakfast_table": TownObject(
            id="breakfast_table",
            name="早餐桌",
            location_id="home_alice",
            description="桌上放着简单早餐，可用于完成吃早餐日程。",
        ),
        "notice_board": TownObject(
            id="notice_board",
            name="公告栏",
            location_id="town_square",
            description="一块贴满本地公告的木板。",
        ),
        "cafe_counter": TownObject(
            id="cafe_counter",
            name="咖啡馆柜台",
            location_id="cafe",
            description="摆着杯子和收银机的木质柜台，可用于点单、结账和准备营业。",
        ),
        "pastry_case": TownObject(
            id="pastry_case",
            name="点心陈列柜",
            location_id="cafe",
            description="玻璃柜里陈列着可颂和松饼，可用于购买早餐或搭配咖啡。",
        ),
        "bookshelf": TownObject(
            id="bookshelf",
            name="书架",
            location_id="library",
            description="放着地方史书和借阅小说的书架，可用于整理馆藏。",
        ),
        "returns_cart": TownObject(
            id="returns_cart",
            name="归还书车",
            location_id="library",
            description="推车上放着刚归还的书，可用于完成整理归还书籍日程。",
        ),
        "medicine_cabinet": TownObject(
            id="medicine_cabinet",
            name="药品柜",
            location_id="clinic",
            description="存放常用医疗用品的上锁柜子。",
        ),
    }
    npc_locations = {
        "alice": "home_alice",
        "bob": "cafe",
        "clara": "library",
    }
    schedules = {
        "alice": [
            ScheduleSegment(
                npc_id="alice",
                start_minute=8 * 60,
                duration_minutes=60,
                location_id="home_alice",
                intent="吃早餐",
            ),
            ScheduleSegment(
                npc_id="alice",
                start_minute=9 * 60,
                duration_minutes=60,
                location_id="cafe",
                intent="买咖啡",
            ),
        ],
        "bob": [
            ScheduleSegment(
                npc_id="bob",
                start_minute=8 * 60,
                duration_minutes=120,
                location_id="cafe",
                intent="准备咖啡馆营业",
            ),
        ],
        "clara": [
            ScheduleSegment(
                npc_id="clara",
                start_minute=8 * 60,
                duration_minutes=120,
                location_id="library",
                intent="整理归还的书籍",
            ),
        ],
    }
    common_known_locations = ["town_square", "cafe", "library", "clinic"]
    residents = {
        npc_id: TownResidentState(
            npc_id=npc_id,
            location_id=location_id,
            schedule=schedules[npc_id],
            spatial_memory=ResidentSpatialMemory(
                known_location_ids=_unique(
                    [
                        location_id,
                        *common_known_locations,
                        *(segment.location_id for segment in schedules[npc_id]),
                    ]
                ),
                known_object_ids=_known_objects_for_locations(
                    locations,
                    _unique(
                        [
                            location_id,
                            *common_known_locations,
                            *(segment.location_id for segment in schedules[npc_id]),
                        ]
                    ),
                ),
            ),
        )
        for npc_id, location_id in npc_locations.items()
    }
    return TownState(
        clock=TownClock(day=1, minute=8 * 60, stride_minutes=10),
        locations=locations,
        objects=objects,
        npc_locations=npc_locations,
        schedules=schedules,
        residents=residents,
    )


def _unique(items) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            result.append(item)
    return result


def _known_objects_for_locations(
    locations: dict[str, Location],
    location_ids: list[str],
) -> list[str]:
    object_ids: list[str] = []
    for location_id in location_ids:
        location = locations.get(location_id)
        if location is not None:
            object_ids.extend(location.object_ids)
    return _unique(object_ids)
