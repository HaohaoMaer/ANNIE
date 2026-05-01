"""Deterministic semantic town fixtures for early TownWorldEngine validation."""

from __future__ import annotations

from annie.town.domain import (
    Location,
    ResidentSpatialMemory,
    ScheduleSegment,
    SemanticAffordance,
    TownClock,
    TownObject,
    TownResidentState,
    TownState,
)


def create_small_town_state() -> TownState:
    """Create a 3-NPC semantic town fixture with bounded affordances."""
    locations = {
        "home_alice": Location(
            id="home_alice",
            name="Alice 的家",
            description="小镇边缘的一间小屋。",
            exits=["town_square"],
            exit_travel_minutes={"town_square": 5},
            object_ids=["breakfast_table"],
            affordances=[
                _aff("rest", "休息", "在家中短暂休息，恢复一天开始时的状态。", aliases=["休息", "整理家务"]),
            ],
        ),
        "town_square": Location(
            id="town_square",
            name="小镇广场",
            description="小镇中央的广场，通向各个公共地点。",
            exits=["home_alice", "cafe", "library", "clinic", "market", "workshop", "park"],
            exit_travel_minutes={
                "home_alice": 5,
                "cafe": 3,
                "library": 4,
                "clinic": 4,
                "market": 4,
                "workshop": 6,
                "park": 5,
            },
            object_ids=["notice_board"],
            affordances=[
                _aff("meet", "碰面", "在广场等待或和同地点镇民碰面。", aliases=["碰面", "会合"]),
            ],
        ),
        "cafe": Location(
            id="cafe",
            name="咖啡馆",
            description="一间安静的咖啡馆，镇民常在这里交换晨间消息。",
            exits=["town_square"],
            exit_travel_minutes={"town_square": 3},
            object_ids=["cafe_counter", "pastry_case"],
            affordances=[
                _aff("sit", "入座", "在咖啡馆找座位进行短暂停留。", aliases=["坐下", "休息"]),
            ],
        ),
        "library": Location(
            id="library",
            name="图书馆",
            description="一座公共图书馆，里面有长阅读桌。",
            exits=["town_square"],
            exit_travel_minutes={"town_square": 4},
            object_ids=["bookshelf", "returns_cart"],
            affordances=[
                _aff("study", "阅读学习", "在公共阅读桌查阅资料或安静学习。", aliases=["阅读", "学习"]),
            ],
        ),
        "clinic": Location(
            id="clinic",
            name="诊所",
            description="一间整洁的诊所，备有基础医疗用品。",
            exits=["town_square"],
            exit_travel_minutes={"town_square": 4},
            object_ids=["medicine_cabinet"],
            affordances=[
                _aff("consult", "问诊", "向诊所请求基础健康建议或简单服务。", aliases=["问诊", "咨询"]),
            ],
        ),
        "market": Location(
            id="market",
            name="集市",
            description="小镇早市，有摊位、公共秤和采购清单。",
            exits=["town_square"],
            exit_travel_minutes={"town_square": 4},
            object_ids=["produce_stall", "community_scale", "errand_box"],
            affordances=[
                _aff("shop", "采购", "购买或询问日常用品。", aliases=["采购", "买菜", "买东西"]),
            ],
        ),
        "workshop": Location(
            id="workshop",
            name="修理工坊",
            description="一间堆着工具和木料的修理工坊。",
            exits=["town_square"],
            exit_travel_minutes={"town_square": 6},
            object_ids=["tool_rack", "repair_bench", "parts_bin"],
            affordances=[
                _aff("repair_service", "请求修理", "请求简单修理或借用工具。", aliases=["修理", "借工具"]),
            ],
        ),
        "park": Location(
            id="park",
            name="河边公园",
            description="沿河的小公园，长椅旁能看到慢跑路线。",
            exits=["town_square"],
            exit_travel_minutes={"town_square": 5},
            object_ids=["park_bench", "garden_plot"],
            affordances=[
                _aff("walk", "散步", "沿河散步、整理思绪或等待别人。", aliases=["散步", "等人"]),
            ],
        ),
    }
    objects = {
        "breakfast_table": TownObject(
            id="breakfast_table",
            name="早餐桌",
            location_id="home_alice",
            description="桌上放着简单早餐，可用于完成吃早餐日程。",
            affordances=[
                _aff("eat_breakfast", "吃早餐", "吃完桌上的简单早餐。", aliases=["吃早餐", "用餐"]),
                _aff("clear_table", "收拾餐桌", "收拾餐具并整理桌面。", aliases=["收拾", "整理餐桌"]),
            ],
        ),
        "notice_board": TownObject(
            id="notice_board",
            name="公告栏",
            location_id="town_square",
            description="一块贴满本地公告的木板。",
            affordances=[
                _aff("read_notices", "阅读公告", "查看公告栏上近期的镇内消息。", aliases=["读公告", "查看公告"], event_type="notice"),
                _aff("post_notice", "张贴公告", "张贴一条给镇民看的简短公告。", aliases=["贴公告", "发布通知"], event_type="notice"),
            ],
        ),
        "cafe_counter": TownObject(
            id="cafe_counter",
            name="咖啡馆柜台",
            location_id="cafe",
            description="摆着杯子和收银机的木质柜台，可用于点单、结账和准备营业。",
            affordances=[
                _aff(
                    "order_coffee",
                    "点咖啡",
                    "点一杯咖啡或完成咖啡购买。",
                    aliases=["点咖啡", "买咖啡", "取咖啡", "点咖啡并取咖啡", "结账"],
                ),
                _aff(
                    "prepare_counter",
                    "整理柜台",
                    "整理杯子、菜单和收银台。",
                    aliases=["准备营业", "整理柜台", "检查柜台", "煮咖啡"],
                ),
            ],
        ),
        "pastry_case": TownObject(
            id="pastry_case",
            name="点心陈列柜",
            location_id="cafe",
            description="玻璃柜里陈列着可颂和松饼，可用于购买早餐或搭配咖啡。",
            affordances=[
                _aff("buy_pastry", "购买点心", "购买可颂或松饼。", aliases=["买点心", "买早餐"]),
                _aff(
                    "stock_pastries",
                    "整理点心",
                    "补齐或整理陈列柜里的点心。",
                    aliases=["整理点心", "整理点心柜", "补货"],
                ),
            ],
        ),
        "bookshelf": TownObject(
            id="bookshelf",
            name="书架",
            location_id="library",
            description="放着地方史书和借阅小说的书架，可用于整理馆藏。",
            affordances=[
                _aff("browse_books", "查阅书籍", "查阅书架上的地方史或小说。", aliases=["查书", "阅读"]),
                _aff(
                    "shelve_books",
                    "上架书籍",
                    "把书放回正确的书架位置。",
                    aliases=["上架", "整理馆藏", "放回书架"],
                ),
            ],
        ),
        "returns_cart": TownObject(
            id="returns_cart",
            name="归还书车",
            location_id="library",
            description="推车上放着刚归还的书，可用于完成整理归还书籍日程。",
            affordances=[
                _aff(
                    "sort_returns",
                    "整理归还书",
                    "按类别整理刚归还的书。",
                    aliases=["整理归还", "整理归还书籍", "分拣书"],
                ),
            ],
        ),
        "medicine_cabinet": TownObject(
            id="medicine_cabinet",
            name="药品柜",
            location_id="clinic",
            description="存放常用医疗用品的上锁柜子。",
            affordances=[
                _aff("request_medicine", "领取药品", "领取基础医疗用品。", aliases=["拿药", "领药"]),
                _aff("check_supplies", "检查药品", "检查药品柜库存。", aliases=["检查库存", "整理药品"]),
            ],
        ),
        "produce_stall": TownObject(
            id="produce_stall",
            name="蔬果摊",
            location_id="market",
            description="摆着新鲜蔬菜和水果的摊位。",
            affordances=[
                _aff("buy_produce", "购买蔬果", "购买当天需要的蔬菜或水果。", aliases=["买菜", "采购"]),
                _aff("ask_price", "询价", "向摊主询问价格和货源。", aliases=["询价", "问价格"]),
            ],
        ),
        "community_scale": TownObject(
            id="community_scale",
            name="公共秤",
            location_id="market",
            description="供摊主和居民称量物品的公共台秤。",
            affordances=[
                _aff("weigh_goods", "称量物品", "称量采购物或寄放物。", aliases=["称重", "称量"]),
            ],
        ),
        "errand_box": TownObject(
            id="errand_box",
            name="代办箱",
            location_id="market",
            description="居民可以留下采购或取送请求的木箱。",
            affordances=[
                _aff("leave_request", "留下代办请求", "写下采购、取送或帮忙请求。", aliases=["留下请求", "委托"]),
                _aff("read_requests", "阅读代办请求", "查看当前无人处理的代办请求。", aliases=["查看请求", "读请求"]),
            ],
        ),
        "tool_rack": TownObject(
            id="tool_rack",
            name="工具架",
            location_id="workshop",
            description="挂着锤子、钳子和卷尺的工具架。",
            affordances=[
                _aff("borrow_tool", "借用工具", "借用一件小工具。", aliases=["借工具", "拿工具"]),
                _aff("return_tool", "归还工具", "把借出的工具归还到工具架。", aliases=["还工具", "归还"]),
            ],
        ),
        "repair_bench": TownObject(
            id="repair_bench",
            name="修理台",
            location_id="workshop",
            description="可以处理简单维修的长工作台。",
            affordances=[
                _aff("repair_item", "修理物品", "处理一件简单损坏物品。", aliases=["修理", "维修"]),
                _aff("request_repair", "请求维修服务", "请求工坊安排维修。", aliases=["请求维修", "报修"]),
            ],
        ),
        "parts_bin": TownObject(
            id="parts_bin",
            name="零件箱",
            location_id="workshop",
            description="分类放着螺丝、铰链和小零件。",
            affordances=[
                _aff("find_part", "寻找零件", "查找维修所需的小零件。", aliases=["找零件", "取零件"]),
            ],
        ),
        "park_bench": TownObject(
            id="park_bench",
            name="公园长椅",
            location_id="park",
            description="面向河边的小长椅，适合休息或谈话。",
            affordances=[
                _aff("sit_rest", "坐下休息", "短暂坐下休息或等待别人。", aliases=["休息", "等人"]),
            ],
        ),
        "garden_plot": TownObject(
            id="garden_plot",
            name="社区花圃",
            location_id="park",
            description="居民共同照料的小花圃。",
            affordances=[
                _aff("water_plants", "浇花", "给社区花圃浇水。", aliases=["浇水", "照料花圃"]),
                _aff("inspect_garden", "查看花圃", "检查花圃的状态。", aliases=["查看花圃", "检查植物"]),
            ],
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
    common_known_locations = [
        "town_square",
        "cafe",
        "library",
        "clinic",
        "market",
        "workshop",
        "park",
    ]
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


def _aff(
    affordance_id: str,
    label: str,
    description: str,
    *,
    duration_minutes: int = 5,
    aliases: list[str] | None = None,
    event_type: str = "interaction",
) -> SemanticAffordance:
    return SemanticAffordance(
        id=affordance_id,
        label=label,
        description=description,
        duration_minutes=duration_minutes,
        aliases=aliases or [],
        event_type=event_type,
    )
