"""Shared prompt contracts for NPC graph nodes."""

from __future__ import annotations

import json
import re
from typing import TYPE_CHECKING, Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage

if TYPE_CHECKING:
    from annie.npc.state import Task
    from annie.npc.skills.base_skill import SkillDef

MEMORY_CATEGORIES_BLOCK = """\
- episodic: 原始经历（旧类别；新默认流程不应写入）
- semantic: 客观事实
- reflection: 自我反思与人物印象
- impression: 折叠产生的模糊印象
- todo: 跨回合未完成目标（可能为空）"""

PLANNER_SYSTEM_PROMPT = """\
你是 NPC 的计划判断模块。你的职责不是扮演角色，也不是输出台词，而是判断本轮事件是否真的需要拆成多个有先后顺序的执行步骤。

判断规则：
- 默认选择 "skip"。普通对话、情绪反应、表态、观察、单次行动，都应交给执行器直接处理。
- 如果一个目标可以由执行器在同一个 ReAct 工具循环中通过“调用工具 -> 读取 observation -> 再调用工具”逐步完成，也必须选择 "skip"。
- 不要把工具失败后的备选步骤、重试步骤、根据 observation 调整下一步这类内容拆成 planner tasks；这些属于执行器职责。
- 只有当事件明确需要多个顺序阶段，且单轮角色回应无法自然完成时，才选择 "plan"。
- 不要调用工具，不要写角色台词，不要做复盘。
- 只能输出严格 JSON。不要使用 markdown 代码块，不要附加解释文字。

选择 skip 时输出：
{"decision":"skip","reason":"brief reason","tasks":[]}

选择 plan 时输出：
{"decision":"plan","reason":"brief reason","tasks":[{"description":"specific executable task","priority":5}]}

任务约束：
- tasks 最多 3 个。
- 每个 description 必须是具体、可执行的任务。
- 每个 priority 必须是 0 到 10 之间的整数。
"""

EXECUTOR_SYSTEM_PROMPT = """\
{identity}
<world_rules>
{world_rules}
</world_rules>
<situation>
{situation}
</situation>
<memory_categories>
{memory_categories}
</memory_categories>
<working_memory>
{working_memory}
</working_memory>
<todo>
{todo}
</todo>
<available_skills>
{skills}
</available_skills>

你现在扮演 <character> 中的 NPC。

上下文读取顺序：
- <world_rules> 是最高优先级规则，必须遵守。
- <situation> 是当前场景状态，用来判断此刻能自然发生什么。
- 对话历史会以消息序列提供；它只是最近说过的话，不等于长期记忆或客观事实。
- <working_memory> 是本轮提前检索出的长期记忆摘要，可能不完整。
- <todo> 是跨回合目标背景；只有当前事件相关时才处理，不要为了完成 todo 而偏离当前场景。
- <available_skills> 只列出可通过 use_skill 激活的能力；技能名不是独立工具名。

执行要求：
- 始终按 NPC 的身份、认知和语气回应。
- 需要工具时，只能依据本轮绑定的工具 schema 调用工具。
- 没有必要使用工具时，直接给出最终角色回应。
- 不要输出 planner JSON，也不要解释你的内部流程。
"""

REFLECTOR_SYSTEM_PROMPT = """\
你是 NPC 的复盘模块。你的职责是从 NPC 视角总结刚刚发生的执行结果，并声明可能需要写入记忆的内容。

注意：
- 你只声明 memory update 意图，不负责持久化。
- reflection 必须是 NPC 视角的 2 到 4 句话。
- facts 只写客观事实，不写猜测。
- relationship_notes 只写与具体人物相关的观察。
- 只能输出严格 JSON。不要使用 markdown 代码块，不要在 JSON 外附加文字。

输出格式：
{
  "reflection": "2-4 sentence NPC perspective reflection",
  "facts": ["objective fact learned"],
  "relationship_notes": [
    {"person": "Name", "observation": "text"}
  ]
}
"""


def render_identity(ctx: Any) -> str:
    """Return the ``<character>...</character>`` XML block.

    Used by Executor (in the system template) and Reflector (appended to
    its system prompt) so both nodes see an identical character framing.
    """
    npc_id = getattr(ctx, "npc_id", "") or ""
    character_prompt = getattr(ctx, "character_prompt", "") or ""
    if npc_id or character_prompt:
        inner = "\n".join(
            part for part in (
                f"角色ID：{npc_id}" if npc_id else "",
                f"角色设定：\n{character_prompt}" if character_prompt else "",
            )
            if part
        )
    else:
        inner = "(none)"
    return f"<character>\n{inner}\n</character>"


def render_skills_text(skills: list["SkillDef"]) -> str:
    """One-line-per-skill summary for the ``<available_skills>`` XML block."""
    if not skills:
        return "(none)"
    return "\n".join(
        f"- {s.name}: {s.one_line}" if s.one_line else f"- {s.name}"
        for s in skills
    )


def build_planner_messages(
    ctx: Any,
    working_memory: str,
    retry_context: dict[str, Any] | None = None,
) -> list[BaseMessage]:
    """Build Planner messages from the shared prompt contract."""
    sections = [
        render_identity(ctx),
        _section("world_rules", getattr(ctx, "world_rules", ""), "最高优先级规则"),
        _section("situation", getattr(ctx, "situation", ""), "当前场景状态"),
        _section("working_memory", working_memory, "本轮预检索的长期记忆摘要，可能不完整"),
        _section("todo", getattr(ctx, "todo", ""), "跨回合目标背景，不代表本轮必须执行"),
        _section("input_event", getattr(ctx, "input_event", ""), "本轮触发事件"),
    ]
    if retry_context:
        sections.append(_section(
            "retry_context",
            json.dumps(retry_context, ensure_ascii=False, indent=2),
            "上一次执行没有产生可用结果，请据此重新判断",
        ))
    return [
        SystemMessage(content=PLANNER_SYSTEM_PROMPT),
        HumanMessage(content="请根据以下上下文判断是否需要多步骤计划。\n\n" + "\n".join(sections)),
    ]


def build_executor_messages(
    ctx: Any,
    task: "Task",
    working_memory: str,
    todo_text: str,
    skills: list["SkillDef"],
) -> list[BaseMessage]:
    """Build Executor messages from the shared prompt contract."""
    system = SystemMessage(content=EXECUTOR_SYSTEM_PROMPT.format(
        identity=render_identity(ctx),
        world_rules=_with_label(getattr(ctx, "world_rules", ""), "最高优先级规则"),
        situation=_with_label(getattr(ctx, "situation", ""), "当前场景状态"),
        memory_categories=MEMORY_CATEGORIES_BLOCK,
        working_memory=_with_label(working_memory, "本轮预检索的长期记忆摘要，可能不完整"),
        todo=_with_label(todo_text, "跨回合目标背景，不代表本轮必须执行"),
        skills=render_skills_text(skills),
    ))
    history_msgs = history_to_messages(getattr(ctx, "history", ""), getattr(ctx, "npc_id", ""))
    trigger_sections = [_section("input_event", getattr(ctx, "input_event", ""), "本轮触发事件")]
    if getattr(task, "description", "") != "__skip__":
        trigger_sections.append(_section("task", getattr(task, "description", ""), "计划器要求本轮执行的具体任务"))
    return [
        system,
        *history_msgs,
        HumanMessage(content="请基于当前事件继续扮演角色。\n\n" + "\n".join(trigger_sections)),
    ]


def build_reflector_messages(
    ctx: Any,
    input_event: str,
    execution_results: list[dict[str, Any]],
) -> list[BaseMessage]:
    """Build Reflector messages from the shared prompt contract."""
    sections = [
        render_identity(ctx),
        _section("world_rules", getattr(ctx, "world_rules", ""), "最高优先级规则"),
        _section("situation", getattr(ctx, "situation", ""), "当前场景状态"),
        _section("input_event", input_event, "本轮触发事件"),
        _section("execution_results", _render_execution_results(execution_results), "执行器刚刚产生的结果"),
    ]
    return [
        SystemMessage(content=REFLECTOR_SYSTEM_PROMPT),
        HumanMessage(content="请只根据以下上下文复盘本轮执行结果。\n\n" + "\n".join(sections)),
    ]


_HISTORY_LINE_RE = re.compile(r"^(\[folded\])?\[(?P<speaker>[^\]]+)\] (?P<content>.*)$")


def history_to_messages(history: str, self_id: str) -> list[BaseMessage]:
    """Parse engine-rendered rolling history into message sequence."""
    if not history.strip():
        return []
    msgs: list[BaseMessage] = []
    for raw in history.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _HISTORY_LINE_RE.match(line)
        if not m:
            msgs.append(HumanMessage(content=line))
            continue
        speaker = m.group("speaker")
        content = m.group("content")
        if speaker == self_id:
            msgs.append(AIMessage(content=content))
        else:
            msgs.append(HumanMessage(content=f"{speaker}：{content}"))
    return msgs


def _section(name: str, value: Any, label: str | None = None) -> str:
    return f"<{name}>\n{_with_label(value, label)}\n</{name}>"


def _with_label(value: Any, label: str | None) -> str:
    text = _none_if_empty(value)
    if text == "(none)" or not label:
        return text
    return f"{label}：\n{text}"


def _none_if_empty(value: Any) -> str:
    text = str(value).strip() if value is not None else ""
    return text or "(none)"


def _render_execution_results(results: list[dict[str, Any]]) -> str:
    if not results:
        return "(none)"
    return json.dumps(results, ensure_ascii=False, indent=2, default=str)
