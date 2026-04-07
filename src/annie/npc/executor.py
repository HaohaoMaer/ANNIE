"""Executor - Carries out planned tasks via memory lookup, skills, tools, and LLM.

LangGraph node function that processes each task from the Planner,
gathering context and generating actions.
"""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from annie.npc.state import AgentState, TaskStatus
from annie.npc.sub_agents.memory_agent import MemoryAgent
from annie.npc.tracing import EventType

if TYPE_CHECKING:
    from annie.npc.cognitive.belief_system import BeliefSystem
    from annie.npc.cognitive.emotional_state import EmotionalStateManager
    from annie.npc.cognitive.motivation import MotivationEngine
    from annie.npc.cognitive.decision_maker import DecisionMaker
    from annie.npc.sub_agents.skill_agent import SkillAgent
    from annie.npc.sub_agents.tool_agent import ToolAgent
    from annie.social_graph.event_log import SocialEventLog

logger = logging.getLogger(__name__)

EXECUTOR_SYSTEM_PROMPT = """\
你是NPC"{name}"的行动执行模块。

性格特点：{traits}
价值观：{values}

你的角色剧本梗概：
{script_summary}

当前动机：
{motivations}

当前情绪状态：{emotional_state}

你接到了一个需要执行的任务。请结合提供的记忆上下文和你的角色剧本来决定你的行动。

重要要求：你必须以如下两个部分回答：
1. 【内心活动】：你内心真正的想法（基于你的真实剧本、秘密和动机），这是你的私密思考过程。
2. 【说的话】：你对其他人说的话。这应该隐藏你的秘密并保护你的利益，同时保持可信。

请严格按照以下格式回复：
【内心活动】
(你的真实想法、推理和基于剧本的分析)

【说的话】
(你实际对其他人说的话，精心措辞以隐藏秘密)

保持角色扮演。你的内心活动应该反映你的真实意图和剧本中的知识。你说的话应该具有策略性，可以与你的想法不同。
"""

VOTING_SYSTEM_PROMPT = """\
你是NPC"{name}"在投票阶段的行动执行模块。

性格特点：{traits}
价值观：{values}

你的角色剧本梗概：
{script_summary}

当前动机：
{motivations}

当前情绪状态：{emotional_state}

这是投票阶段。你必须投票指认你认为的凶手。

可投票的对象（请从以下名单中选择一个人名）：
{voteable_names}

重要要求：你必须以如下三个部分回答：
1. 【内心活动】：你对凶手身份的真实分析（基于你实际的知识和剧本）。
2. 【说的话】：你对其他人说的关于你投票的话（如果你是凶手，你可以说谎来误导他人）。
3. 【投票】：你投票给的人名（只写一个人名，必须从上面的名单中选择）。

请严格按照以下格式回复：
【内心活动】
(你对凶手是谁的真实分析和推理)

【说的话】
(你对其他人说的关于你投票的话)

【投票】
(单个人名，不要写其他内容)

如果你是凶手，你应该在说的话中尝试误导他人，而你的内心活动则揭示你的真实想法。
"""


class Executor:
    """Processes tasks one by one, querying memory and optionally invoking skills and tools."""

    def __init__(
        self,
        llm: BaseChatModel,
        memory_agent: MemoryAgent,
        skill_agent: SkillAgent | None = None,
        tool_agent: ToolAgent | None = None,
        event_log: SocialEventLog | None = None,
        all_npc_names: list[str] | None = None,
        motivation_engine: MotivationEngine | None = None,
        belief_system: BeliefSystem | None = None,
        emotional_state_manager: EmotionalStateManager | None = None,
        decision_maker: DecisionMaker | None = None,
    ):
        self.llm = llm
        self.memory_agent = memory_agent
        self.skill_agent = skill_agent
        self.tool_agent = tool_agent
        self._event_log = event_log
        self._all_npc_names = all_npc_names or []
        self._is_voting_phase = False
        self._script_summary = ""
        self._motivation_engine = motivation_engine
        self._belief_system = belief_system
        self._emotional_state_manager = emotional_state_manager
        self._decision_maker = decision_maker

    def set_voting_phase(self, is_voting: bool, script_summary: str = "") -> None:
        """Set whether this is a voting phase."""
        self._is_voting_phase = is_voting
        if script_summary:
            self._script_summary = script_summary

    def set_script_summary(self, summary: str) -> None:
        """Set the script summary independently of voting phase."""
        self._script_summary = summary

    def _get_motivation_summary(self) -> str:
        """Get a summary of current motivations."""
        if not self._motivation_engine:
            return "无特定动机"
        motivations = self._motivation_engine.prioritize()
        if not motivations:
            return "无特定动机"
        lines = []
        for m in motivations[:3]:
            lines.append(f"- {m.goal}（强度: {m.intensity:.1f}）")
        return "\n".join(lines)

    def _get_emotional_state_desc(self) -> str:
        """Get a description of current emotional state."""
        if not self._emotional_state_manager:
            return "平静"
        state = self._emotional_state_manager.get_current_state()
        emotion_cn = {
            "joy": "愉快", "sadness": "悲伤", "anger": "愤怒",
            "fear": "恐惧", "surprise": "惊讶", "disgust": "厌恶",
            "trust": "信任", "anticipation": "期待", "neutral": "平静",
        }
        emotion_name = emotion_cn.get(state.primary_emotion.value, state.primary_emotion.value)
        intensity_cn = {
            "mild": "轻微", "moderate": "中等", "strong": "强烈", "intense": "极度",
        }
        intensity_name = intensity_cn.get(state.get_intensity_level().value, "")
        return f"{intensity_name}{emotion_name}"

    def __call__(self, state: AgentState) -> dict:
        """LangGraph node function. Returns partial state with execution results."""
        tracer = state.get("tracer")
        npc = state["npc_profile"]
        tasks = state.get("tasks", [])

        span = tracer.node_span("executor") if tracer else _nullcontext()
        with span:
            motivation_summary = self._get_motivation_summary()
            emotional_state_desc = self._get_emotional_state_desc()

            # Build voteable names (exclude self)
            voteable_names = [n for n in self._all_npc_names if n != npc.name]
            voteable_names_str = "、".join(voteable_names) if voteable_names else "无"

            if self._is_voting_phase:
                system_prompt = VOTING_SYSTEM_PROMPT.format(
                    name=npc.name,
                    traits=", ".join(npc.personality.traits),
                    values=", ".join(npc.personality.values),
                    script_summary=self._script_summary or "暂无剧本信息",
                    motivations=motivation_summary,
                    emotional_state=emotional_state_desc,
                    voteable_names=voteable_names_str,
                )
            else:
                system_prompt = EXECUTOR_SYSTEM_PROMPT.format(
                    name=npc.name,
                    traits=", ".join(npc.personality.traits),
                    values=", ".join(npc.personality.values),
                    script_summary=self._script_summary or "暂无剧本信息",
                    motivations=motivation_summary,
                    emotional_state=emotional_state_desc,
                )

            results = []
            updated_tasks = []

            for task in tasks:
                task.status = TaskStatus.IN_PROGRESS

                if tracer:
                    tracer.trace(
                        "executor",
                        EventType.MEMORY_READ,
                        input_summary=task.description[:80],
                    )
                memory_context = self.memory_agent.build_context(task.description)

                skill_output = None
                if self.skill_agent:
                    skill_output = self.skill_agent.try_skill(task.description, npc, tracer)

                tool_output = None
                if self.tool_agent:
                    tool_output = self.tool_agent.try_tool(task.description, npc.name, tracer)

                user_content = f"任务: {task.description}\n\n记忆上下文:\n{memory_context}"
                if skill_output:
                    user_content += f"\n\n技能输出:\n{skill_output}"
                if tool_output:
                    user_content += f"\n\n工具输出:\n{tool_output}"

                if tracer:
                    tracer.trace(
                        "executor",
                        EventType.LLM_CALL,
                        input_summary=task.description[:80],
                    )

                messages = [
                    SystemMessage(content=system_prompt),
                    HumanMessage(content=user_content),
                ]
                response = self.llm.invoke(messages)

                if tracer:
                    tracer.trace(
                        "executor",
                        EventType.LLM_RESPONSE,
                        output_summary=response.content[:100],
                    )

                task.status = TaskStatus.DONE
                task.result = response.content
                updated_tasks.append(task)

                parsed_result = self._parse_action_response(response.content, npc.name)
                result_entry = {
                    "task_id": task.id,
                    "task_description": task.description,
                    "action": response.content,
                    "inner_thoughts": parsed_result.get("inner_thoughts", ""),
                    "spoken_words": parsed_result.get("spoken_words", ""),
                    "vote": parsed_result.get("vote", ""),
                }
                results.append(result_entry)

                self._maybe_log_social_event(npc, task.description, parsed_result.get("spoken_words", response.content))

        return {"tasks": updated_tasks, "execution_results": results}

    def _parse_action_response(self, response: str, npc_name: str) -> dict:
        """Parse the action response into inner thoughts, spoken words, and vote."""
        result = {
            "inner_thoughts": "",
            "spoken_words": "",
            "vote": "",
        }

        inner_marker = "【内心活动】"
        spoken_marker = "【说的话】"
        vote_marker = "【投票】"

        inner_start = response.find(inner_marker)
        spoken_start = response.find(spoken_marker)
        vote_start = response.find(vote_marker)

        if inner_start != -1:
            inner_start += len(inner_marker)
            inner_end = spoken_start if spoken_start > inner_start else (vote_start if vote_start > inner_start else len(response))
            result["inner_thoughts"] = response[inner_start:inner_end].strip()

        if spoken_start != -1:
            spoken_start += len(spoken_marker)
            spoken_end = vote_start if vote_start > spoken_start else len(response)
            result["spoken_words"] = response[spoken_start:spoken_end].strip()

        if vote_start != -1:
            vote_start += len(vote_marker)
            vote_text = response[vote_start:].strip()
            # Clean up the vote text
            vote_text = re.sub(r'[（()）\s\n]', '', vote_text.split('\n')[0].strip())

            # 1. Exact match
            for name in self._all_npc_names:
                if name != npc_name and vote_text == name:
                    result["vote"] = name
                    break

            # 2. Substring containment
            if not result["vote"]:
                for name in self._all_npc_names:
                    if name != npc_name and name in vote_text:
                        result["vote"] = name
                        break

            # 3. Surname match (first character of Chinese name)
            if not result["vote"]:
                for name in self._all_npc_names:
                    if name != npc_name and len(name) > 0 and name[0] in vote_text:
                        result["vote"] = name
                        break

        # Fallback: if no markers found, treat whole response as spoken words
        if not result["inner_thoughts"] and not result["spoken_words"]:
            result["spoken_words"] = response

        return result

    def _maybe_log_social_event(self, npc, task_desc: str, action: str) -> None:
        """If the action mentions another NPC, log a SocialEvent."""
        if self._event_log is None:
            return

        # Detect mentioned NPCs by name matching.
        mentioned = [
            name for name in self._all_npc_names
            if name != npc.name and name.lower() in action.lower()
        ]
        if not mentioned:
            return

        from annie.social_graph.models import EventVisibility, SocialEvent

        evt = SocialEvent(
            actor=npc.name,
            target=mentioned[0],
            action=task_desc[:80],
            description=action[:300],
            witnesses=mentioned[1:],
            visibility=EventVisibility.WITNESSED,
        )
        self._event_log.append(evt)


class _nullcontext:
    def __enter__(self):
        return self

    def __exit__(self, *args):
        pass
