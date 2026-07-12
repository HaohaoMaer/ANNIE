"""Tests for Executor node."""

from unittest.mock import MagicMock
from types import SimpleNamespace

import pytest

from langchain_core.messages import AIMessage, BaseMessage
from pydantic import BaseModel

from annie.npc.agent import _after_executor
from annie.npc.cognition.executor import Executor
from annie.npc.core.context import AgentContext
from annie.npc.runtime.tool_dispatcher import ToolDispatcher
from annie.npc.runtime.skill_runtime import SkillRuntime
from annie.npc.skills.base_skill import SkillDef, SkillRegistry
from annie.npc.core.state import AgentState, Task, TaskStatus
from annie.npc.tools.base_tool import ToolContext, ToolDef
from annie.npc.tools.tool_registry import ToolRegistry
from annie.npc.observability.tracing import EventType, Tracer


class _StubLLM:
    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[list[BaseMessage]] = []

    def invoke(self, messages, **_):
        self.calls.append(list(messages))
        if not self._responses:
            return AIMessage(content="")
        nxt = self._responses.pop(0)
        if isinstance(nxt, AIMessage):
            return nxt
        return AIMessage(content=str(nxt))

    def bind_tools(self, tools):  # noqa: ARG002 - signature compatibility
        return self


@pytest.fixture
def mock_llm():
    llm = MagicMock()
    response = MagicMock()
    response.content = "The elder carefully observes the stranger."
    llm.invoke.return_value = response
    return llm


@pytest.fixture
def mock_memory_agent():
    agent = MagicMock()
    agent.build_context.return_value = "No relevant memories."
    return agent


@pytest.fixture
def npc_profile():
    return SimpleNamespace(
        name="Elder",
        personality=SimpleNamespace(traits=["wise", "cautious"], values=["safety"]),
    )


@pytest.fixture
def executor(mock_llm, mock_memory_agent):
    return Executor(mock_llm, ToolDispatcher(ToolRegistry(builtins=[])))


def _ctx(profile) -> AgentContext:
    return AgentContext(
        npc_id=profile.name,
        input_event="A stranger approaches.",
        memory=MagicMock(),
        character_prompt=f"Traits: {', '.join(profile.personality.traits)}",
    )


class TestExecutor:
    def test_processes_tasks(self, executor, npc_profile):
        tracer = Tracer("Elder")
        tasks = [
            Task(description="Observe the stranger"),
            Task(description="Recall past encounters"),
        ]
        state: AgentState = {
            "agent_context": _ctx(npc_profile),
            "npc_profile": npc_profile,
            "input_event": "A stranger approaches.",
            "tasks": tasks,
            "tracer": tracer,
        }
        result = executor(state)
        assert "execution_results" in result
        assert len(result["execution_results"]) == 2

    def test_tasks_marked_done(self, executor, npc_profile):
        tracer = Tracer("Elder")
        tasks = [Task(description="Observe the stranger")]
        state: AgentState = {
            "agent_context": _ctx(npc_profile),
            "npc_profile": npc_profile,
            "input_event": "Event",
            "tasks": tasks,
            "tracer": tracer,
        }
        result = executor(state)
        assert result["tasks"][0].status == TaskStatus.DONE
        assert result["tasks"][0].result is not None

    def test_result_structure(self, executor, npc_profile):
        tracer = Tracer("Elder")
        tasks = [Task(description="Observe the stranger")]
        state: AgentState = {
            "agent_context": _ctx(npc_profile),
            "npc_profile": npc_profile,
            "input_event": "Event",
            "tasks": tasks,
            "tracer": tracer,
        }
        result = executor(state)
        r = result["execution_results"][0]
        assert "task_id" in r
        assert "task_description" in r
        assert "action" in r

    def test_uses_prerendered_working_memory(self, executor, npc_profile):
        tracer = Tracer("Elder")
        tasks = [Task(description="Observe the stranger")]
        state: AgentState = {
            "agent_context": _ctx(npc_profile),
            "npc_profile": npc_profile,
            "input_event": "Event",
            "tasks": tasks,
            "tracer": tracer,
            "working_memory": "Already retrieved notes.",
        }
        result = executor(state)
        assert result["execution_results"][0]["action"]

    def test_tracing_events(self, executor, npc_profile):
        tracer = Tracer("Elder")
        tasks = [Task(description="Observe the stranger")]
        state: AgentState = {
            "agent_context": _ctx(npc_profile),
            "npc_profile": npc_profile,
            "input_event": "Event",
            "tasks": tasks,
            "tracer": tracer,
        }
        executor(state)
        event_types = [e.event_type for e in tracer.events]
        assert EventType.NODE_ENTER in event_types
        assert EventType.NODE_EXIT in event_types
        assert EventType.LLM_CALL in event_types
        assert EventType.LLM_RESPONSE in event_types

    def test_works_without_tracer(self, executor, npc_profile):
        tasks = [Task(description="Observe the stranger")]
        state: AgentState = {
            "agent_context": _ctx(npc_profile),
            "npc_profile": npc_profile,
            "input_event": "Event",
            "tasks": tasks,
        }
        result = executor(state)
        assert len(result["execution_results"]) == 1

    def test_empty_tasks(self, executor, npc_profile):
        tracer = Tracer("Elder")
        state: AgentState = {
            "agent_context": _ctx(npc_profile),
            "npc_profile": npc_profile,
            "input_event": "Event",
            "tasks": [],
            "tracer": tracer,
        }
        result = executor(state)
        assert result["execution_results"] == []
        assert result["tasks"] == []

    def test_empty_final_answer_marks_task_failed(self, npc_profile):
        llm = MagicMock()
        response = MagicMock()
        response.content = ""
        llm.invoke.return_value = response
        executor = Executor(llm, ToolDispatcher(ToolRegistry(builtins=[])))
        task = Task(description="Observe the stranger")
        result = executor({
            "agent_context": _ctx(npc_profile),
            "input_event": "Event",
            "tasks": [task],
            "runtime": {},
        })
        assert result["tasks"][0].status == TaskStatus.FAILED
        assert result["execution_results"] == []

    def test_max_tool_loops_exhaustion_marks_task_failed(self, npc_profile):
        llm = MagicMock()
        llm.invoke.return_value = AIMessage(
            content="",
            tool_calls=[{"name": "missing_tool", "args": {}, "id": "call_1"}],
        )
        executor = Executor(llm, ToolDispatcher(ToolRegistry(builtins=[])), max_loops=1)
        task = Task(description="Observe the stranger")
        result = executor({
            "agent_context": _ctx(npc_profile),
            "input_event": "Event",
            "tasks": [task],
            "runtime": {},
        })
        assert result["tasks"][0].status == TaskStatus.FAILED
        assert "MAX_TOOL_LOOPS" in result["tasks"][0].result
        assert result["execution_results"] == []

    def test_failed_task_triggers_retry_when_budget_remains(self):
        state: AgentState = {
            "tasks": [Task(description="x", status=TaskStatus.FAILED)],
            "execution_results": [],
            "retry_count": 0,
            "max_retries": 1,
        }
        assert _after_executor(state) == "retry"

    def test_later_task_receives_prior_task_results(self, npc_profile):
        llm = _StubLLM([
            "First task complete.",
            "Second task used the first result.",
        ])
        executor = Executor(llm, ToolDispatcher(ToolRegistry(builtins=[])))
        tasks = [
            Task(description="Observe the stranger"),
            Task(description="Respond to the observation"),
        ]

        result = executor({
            "agent_context": _ctx(npc_profile),
            "input_event": "Event",
            "tasks": tasks,
            "runtime": {},
        })

        assert len(result["execution_results"]) == 2
        second_task_messages = "\n".join(str(m.content) for m in llm.calls[1])
        assert "<prior_task_results>" in second_task_messages
        assert "Observe the stranger" in second_task_messages
        assert "First task complete." in second_task_messages

    def test_default_tool_registry_does_not_expose_declarative_action_tools(self):
        registry = ToolRegistry()

        assert "declare_action" not in registry.list_tools()
        assert "request_action" not in registry.list_tools()

    def test_use_skill_with_empty_final_answer_does_not_complete_task(self, npc_profile):
        llm = _StubLLM([
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "use_skill",
                    "args": {"skill_name": "missing", "args": {}},
                    "id": "call_skill",
                }],
            ),
            AIMessage(content=""),
        ])
        executor = Executor(llm, ToolDispatcher(ToolRegistry()))
        task = Task(description="Use a skill")

        result = executor({
            "agent_context": _ctx(npc_profile),
            "input_event": "Event",
            "tasks": [task],
            "runtime": {},
        })

        assert result["tasks"][0].status == TaskStatus.FAILED
        assert result["execution_results"] == []

    def test_inner_monologue_with_empty_final_answer_does_not_complete_task(self, npc_profile):
        llm = _StubLLM([
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "inner_monologue",
                    "args": {"thought": "I should stay cautious."},
                    "id": "call_thought",
                }],
            ),
            AIMessage(content=""),
        ])
        executor = Executor(llm, ToolDispatcher(ToolRegistry()))
        task = Task(description="Think privately")

        result = executor({
            "agent_context": _ctx(npc_profile),
            "input_event": "Event",
            "tasks": [task],
            "runtime": {"inner_thoughts": []},
        })

        assert result["tasks"][0].status == TaskStatus.FAILED
        assert result["execution_results"] == []

    def test_read_only_tool_can_continue_until_final_answer(self, npc_profile):
        llm = _StubLLM([
            AIMessage(
                content="",
                tool_calls=[{"name": "read_note", "args": {}, "id": "call_read"}],
            ),
            AIMessage(content="Read result handled."),
        ])
        executor = Executor(
            llm,
            ToolDispatcher(ToolRegistry(injected=[_ReadNoteTool()], builtins=[])),
        )
        task = Task(description="Read before answering")

        result = executor({
            "agent_context": _ctx(npc_profile),
            "input_event": "Event",
            "tasks": [task],
            "runtime": {},
        })

        assert len(llm.calls) == 2
        assert result["tasks"][0].status == TaskStatus.DONE
        assert result["execution_results"][0]["action"] == "Read result handled."

    def test_commit_tool_ends_activation_after_tool_message(self, npc_profile):
        llm = _StubLLM([
            AIMessage(
                content="",
                tool_calls=[{"name": "commit_action", "args": {}, "id": "call_commit"}],
            ),
            AIMessage(content="This should not run."),
        ])
        executor = Executor(
            llm,
            ToolDispatcher(ToolRegistry(injected=[_CommitActionTool()], builtins=[])),
            max_loops=1,
        )
        task = Task(description="Commit once")

        result = executor({
            "agent_context": _ctx(npc_profile),
            "input_event": "Event",
            "tasks": [task],
            "runtime": {},
        })

        assert len(llm.calls) == 1
        assert result["tasks"][0].status == TaskStatus.DONE
        assert result["execution_results"][0]["action"] == "已提交动作：commit_action"
        assert "MAX_TOOL_LOOPS" not in result["tasks"][0].result

    def test_skill_frames_do_not_leak_between_tasks(self, npc_profile):
        llm = _StubLLM([
            AIMessage(
                content="",
                tool_calls=[{
                    "name": "use_skill",
                    "args": {"skill_name": "focus", "args": {}},
                    "id": "call_skill",
                }],
            ),
            AIMessage(content="First task complete."),
            AIMessage(content="Second task complete."),
        ])
        registry = ToolRegistry()
        skills = SkillRegistry([
            SkillDef(name="focus", one_line="Focus attention.", prompt="Stay focused."),
        ])
        runtime = {"skill_runtime": SkillRuntime(skills)}
        executor = Executor(llm, ToolDispatcher(registry, runtime=runtime))
        tasks = [
            Task(description="Use focus"),
            Task(description="Continue after focus"),
        ]

        result = executor({
            "agent_context": _ctx(npc_profile),
            "input_event": "Event",
            "tasks": tasks,
            "runtime": runtime,
        })

        assert [r["action"] for r in result["execution_results"]] == [
            "First task complete.",
            "Second task complete.",
        ]
        assert runtime["skill_frames"] == []
        assert registry._frames == []


class _ReadNoteTool(ToolDef):
    name = "read_note"
    description = "Read a note."
    input_schema = None
    is_read_only = True

    def call(self, input: BaseModel | dict, ctx: ToolContext):
        return {"note": "current snapshot"}


class _CommitActionTool(ToolDef):
    name = "commit_action"
    description = "Commit a world action."
    input_schema = None
    is_read_only = False
    ends_activation_on_success = True

    def call(self, input: BaseModel | dict, ctx: ToolContext):
        ctx.runtime.setdefault("action_results", []).append({"status": "failed"})
        return {"status": "failed", "reason": "business failure still committed"}
