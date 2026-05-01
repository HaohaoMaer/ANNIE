"""Town-specific prompt policy helpers.

These helpers are deterministic. They adapt TownWorld state into prompt-ready
decision hints without calling an LLM or depending on the generic NPC layer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

from annie.town.domain import CurrentAction, Location, ScheduleSegment, TownObject


@dataclass(frozen=True)
class ScheduleEvidence:
    action_count: int
    distinct_object_ids: tuple[str, ...]
    summaries: tuple[str, ...]


def render_schedule_decision_hint(
    *,
    schedule: ScheduleSegment | None,
    clock_minute: int,
    stride_minutes: int,
    progress_summary: str,
    evidence: ScheduleEvidence,
    is_complete: bool,
) -> str:
    if schedule is None:
        return "当前没有日程段；不要调用 finish_schedule_segment，除非世界引擎明确要求。"
    if is_complete:
        return "当前日程段已经完成；除非有待处理直接事件，不需要继续行动。"

    subtasks = schedule.subtasks or default_subtasks_for(schedule)
    remaining = max(0, schedule.end_minute - clock_minute)
    completion = _completion_guidance(schedule, evidence, remaining, stride_minutes)
    subtasks_text = "；".join(subtasks) if subtasks else "无固定子任务，按目标选择最相关行动"
    return (
        f"当前活动“{schedule.intent}”是默认优先目标；"
        "除非紧急事件、直接请求或确认不会影响按时完成，不要偏离日程。"
        "先判断是否已满足，再选择行动。"
        f"建议子任务：{subtasks_text}。"
        f"{completion}"
        f"已完成行动：{progress_summary}。"
    )


def render_object_selection_hint(
    *,
    schedule: ScheduleSegment | None,
    location: Location,
    objects: Sequence[TownObject],
) -> str:
    if not objects:
        return "当前位置没有可见物体；只能考虑可见 NPC、可达出口、wait 或 finish_schedule_segment。"
    visible = ", ".join(
        f"{obj.name} ({obj.id}; affordances={_affordance_ids(obj)})"
        for obj in objects
    )
    if schedule is None:
        return f"对象选择只能从当前位置可见物体中选：{visible}。不要引用其他地点物体。"

    relevant = _relevant_visible_objects(schedule.intent, objects)
    if relevant:
        candidates = ", ".join(f"{obj.name} ({obj.id})" for obj in relevant)
        return (
            f"对象选择只能从当前位置 {location.id} 的可见物体中选：{visible}。"
            f"与“{schedule.intent}”最相关的候选是：{candidates}。"
        )
    return (
        f"对象选择只能从当前位置 {location.id} 的可见物体中选：{visible}。"
        f"若这些物体都不服务于“{schedule.intent}”，优先移动到日程目标地点或结束已满足日程。"
    )


def render_wait_decision_hint(
    *,
    visible_actions: Mapping[str, dict[str, object]],
    own_action: CurrentAction | None,
) -> str:
    busy = [
        npc_id
        for npc_id, action in visible_actions.items()
        if str(action.get("status", "")) not in {"", "succeeded", "failed", "done"}
        or str(action.get("action_type", "")) in {"conversation", "wait", "move_to", "interact_with"}
    ]
    if own_action is not None:
        return "你已经有当前行动；等待只用于让已承诺行动自然结束，不要用新 wait 覆盖行动。"
    if busy:
        return (
            "wait 只适合资源冲突或对方忙碌时使用。"
            f"当前忙碌/占用的可见 NPC：{', '.join(busy)}；若行动依赖他们，可以短暂 wait。"
        )
    return "当前没有明显资源冲突或对方忙碌；优先移动、交互、单句回应或完成日程，不要用 wait 空转。"


def render_conversation_policy_hint(
    *,
    active_session_id: str | None,
    visible_npc_ids: Sequence[str],
    recent_chats: Sequence[str],
    relationship_cues: Sequence[Mapping[str, object]] = (),
    last_text: str | None = None,
) -> str:
    close_hint = render_conversation_close_hint(last_text or "")
    visible = ", ".join(visible_npc_ids) if visible_npc_ids else "无"
    recent = "；".join(recent_chats) if recent_chats else "无"
    relationship = _relationship_cue_summary(relationship_cues)
    if active_session_id:
        return (
            f"当前已在会话 {active_session_id} 中。start_conversation 不应重复发起；"
            f"关系线索：{relationship}。"
            f"对话终止判断：{close_hint}"
        )
    return (
        f"可对话 NPC：{visible}。最近对话：{recent}。"
        f"关系线索：{relationship}。"
        "speak_to 只发一句，收到 speak_to 后最多直接回复一次；"
        "需要多轮交流才用 start_conversation。"
        f"对话终止判断：{close_hint}"
    )


def _relationship_cue_summary(
    relationship_cues: Sequence[Mapping[str, object]],
) -> str:
    if not relationship_cues:
        return "无"
    rendered: list[str] = []
    for cue in relationship_cues[:3]:
        partner = str(cue.get("partner_npc_id", "unknown"))
        bits: list[str] = []
        recent = cue.get("recent_conversations")
        if isinstance(recent, list) and recent:
            bits.append("近期：" + " / ".join(str(item) for item in recent[:2]))
        impressions = cue.get("impressions")
        if isinstance(impressions, list) and impressions:
            bits.append("印象：" + " / ".join(str(item) for item in impressions[:2]))
        cooldown_time = cue.get("cooldown_until_time")
        if isinstance(cooldown_time, str) and cooldown_time:
            bits.append(f"冷却至 {cooldown_time}")
        block_reason = cue.get("conversation_block_reason")
        if isinstance(block_reason, str) and block_reason:
            bits.append(f"当前不可发起：{block_reason}")
        rendered.append(f"{partner}({'; '.join(bits) if bits else '暂无具体线索'})")
    return "；".join(rendered)


def render_conversation_close_hint(last_text: str) -> str:
    text = last_text.strip()
    if not text:
        return "没有最后一句时不要凭空结束；按当前事件决定是否发起或继续。"
    if _looks_like_open_question(text):
        return "最后一句像问题或请求回应，应继续回应，不要立即结束。"
    if _looks_like_close(text):
        return "最后一句像感谢、告别或收尾，可结束会话。"
    return "最后一句没有明确提问；若目标已满足，可自然收尾，否则再补一轮必要信息。"


def render_repeat_guard_hint(
    *,
    npc_id: str,
    action_log: Sequence[dict[str, object]],
) -> str:
    recent = [item for item in action_log if item.get("npc_id") == npc_id][-6:]
    speak_texts: list[str] = []
    for item in recent:
        facts = item.get("facts")
        if item.get("action_type") == "speak_to" and isinstance(facts, dict):
            speak_texts.append(str(facts.get("text", "")).strip())
    normalized = [_normalize(text) for text in speak_texts if text]
    if len(normalized) != len(set(normalized)):
        return "短期内已经出现重复 speak_to 文本；不要再说同一句，改换话题、结束日程或 wait。"
    if len(recent) >= 3:
        action_types = [str(item.get("action_type")) for item in recent[-3:]]
        if len(set(action_types)) == 1:
            return (
                f"短期内连续执行 {action_types[-1]}；继续前检查语义是否重复，"
                "若目标已满足应 finish_schedule_segment。"
            )
    return "短期内不要重复同一句或同语义对话；重复时改换话题、结束会话或转为 wait。"


def schedule_progress_summary(
    *,
    npc_id: str,
    schedule: ScheduleSegment | None,
    action_log: Sequence[dict[str, object]],
) -> str:
    if schedule is None:
        return "无当前日程"
    actions = successful_schedule_actions(npc_id=npc_id, schedule=schedule, action_log=action_log)
    if not actions:
        return "本日程段尚未记录成功的世界行动"
    rendered: list[str] = []
    for item in actions[-6:]:
        action_type = item.get("action_type")
        minute = item.get("minute")
        summary = str(item.get("summary", "")).strip()
        time = _minute_label(minute) if isinstance(minute, int) else str(item.get("time"))
        rendered.append(f"{time} {action_type}: {summary}")
    return f"本日程段已有 {len(actions)} 个成功行动；" + "；".join(rendered)


def schedule_evidence(
    *,
    npc_id: str,
    schedule: ScheduleSegment | None,
    action_log: Sequence[dict[str, object]],
) -> ScheduleEvidence:
    actions = successful_schedule_actions(npc_id=npc_id, schedule=schedule, action_log=action_log)
    object_ids: list[str] = []
    summaries: list[str] = []
    for item in actions:
        facts = item.get("facts")
        if isinstance(facts, dict) and isinstance(facts.get("object_id"), str):
            object_ids.append(str(facts["object_id"]))
        summaries.append(str(item.get("summary", "")))
    return ScheduleEvidence(
        action_count=len(actions),
        distinct_object_ids=tuple(sorted(set(object_ids))),
        summaries=tuple(summaries),
    )


def successful_schedule_actions(
    *,
    npc_id: str,
    schedule: ScheduleSegment | None,
    action_log: Sequence[dict[str, object]],
) -> list[dict[str, object]]:
    if schedule is None:
        return []
    actions: list[dict[str, object]] = []
    for item in action_log:
        minute = item.get("minute")
        if (
            item.get("npc_id") == npc_id
            and item.get("status") == "succeeded"
            and isinstance(minute, int)
            and schedule.start_minute <= minute < schedule.end_minute
            and item.get("action_type") not in {"observe"}
        ):
            actions.append(item)
    return actions


def default_subtasks_for(schedule: ScheduleSegment) -> list[str]:
    intent = schedule.intent
    if schedule.npc_id == "alice" and "吃早餐" in intent:
        return ["与早餐桌交互", "确认已经吃完", "调用 finish_schedule_segment"]
    if schedule.npc_id == "alice" and "咖啡" in intent:
        return ["到达 cafe", "点单或取咖啡", "调用 finish_schedule_segment"]
    if schedule.npc_id == "bob" and "准备" in intent:
        return ["检查柜台", "整理点心柜", "准备咖啡或菜单", "调用 finish_schedule_segment"]
    if schedule.npc_id == "clara" and "整理" in intent:
        return ["处理归还书车", "把书放回书架", "调用 finish_schedule_segment"]
    if "吃" in intent:
        return ["选择可见食物/餐桌", "完成进食", "调用 finish_schedule_segment"]
    if "买" in intent or "取" in intent:
        return ["到达目标地点", "选择交易/取物对象", "完成后调用 finish_schedule_segment"]
    if "准备" in intent:
        return ["选择两个不同相关对象", "完成至少三次准备动作", "调用 finish_schedule_segment"]
    if "整理" in intent:
        return ["选择归还/收纳相关对象", "完成整理动作", "调用 finish_schedule_segment"]
    return []


def _completion_guidance(
    schedule: ScheduleSegment,
    evidence: ScheduleEvidence,
    remaining: int,
    stride_minutes: int,
) -> str:
    intent = schedule.intent
    text = "；".join(evidence.summaries)
    if "准备" in intent and (
        len(evidence.distinct_object_ids) >= 2 or evidence.action_count >= 3
    ):
        return (
            "准备类目标已有足够证据；如果柜台、点心柜、咖啡/菜单等已处理，"
            "应优先调用 finish_schedule_segment，而不是继续重复同类交互。"
        )
    if "整理" in intent and (
        any(word in text for word in ("归还书车", "书架", "整理归还", "馆藏"))
        or len(evidence.distinct_object_ids) >= 2
    ):
        return "整理类目标已有归还/书架处理证据；可调用 finish_schedule_segment。"
    if any(word in intent for word in ("吃", "买", "取", "送")) and evidence.action_count >= 1:
        return "消费/取物类目标已有直接相关行动；若物品已取得或需求已满足，应调用 finish_schedule_segment。"
    if remaining <= stride_minutes:
        return "当前日程即将结束；如果目标已经基本满足，应立即调用 finish_schedule_segment。"
    if evidence.action_count == 0:
        return "先选择与当前日程最相关的可见对象或出口行动；不要只输出叙述或只观察。"
    return "继续行动前先判断目标是否已经满足；满足则调用 finish_schedule_segment。"


def _relevant_visible_objects(intent: str, objects: Sequence[TownObject]) -> list[TownObject]:
    keywords = {
        "吃": ("早餐", "点心", "餐", "桌", "柜"),
        "买": ("柜台", "点心", "咖啡", "收银", "陈列"),
        "咖啡": ("咖啡", "柜台", "点心", "菜单"),
        "准备": ("柜台", "点心", "咖啡", "菜单", "陈列"),
        "整理": ("书", "书架", "归还", "推车", "馆藏"),
    }
    active: list[str] = []
    for marker, words in keywords.items():
        if marker in intent:
            active.extend(words)
    if not active:
        return []
    return [
        obj
        for obj in objects
        if any(word in _object_affordance_text(obj) for word in active)
    ]


def _affordance_ids(obj: TownObject) -> str:
    if not obj.affordances:
        return "none"
    return ",".join(item.id for item in obj.affordances)


def _object_affordance_text(obj: TownObject) -> str:
    affordances = " ".join(
        f"{item.id} {item.label} {item.description} {' '.join(item.aliases)}"
        for item in obj.affordances
    )
    return f"{obj.name} {obj.description} {obj.id} {affordances}"


def _looks_like_open_question(text: str) -> bool:
    stripped = text.strip()
    if stripped.endswith(("?", "？")):
        return True
    question_markers = ("吗", "呢", "什么", "怎么", "为什么", "能否", "可以", "要不要")
    return any(marker in stripped[-12:] for marker in question_markers)


def _looks_like_close(text: str) -> bool:
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


def _normalize(text: str) -> str:
    return "".join(ch for ch in text.lower().strip() if ch.isalnum())


def _minute_label(minute: object) -> str:
    if not isinstance(minute, int):
        return str(minute)
    hours, minutes = divmod(minute, 60)
    return f"{hours:02d}:{minutes:02d}"
