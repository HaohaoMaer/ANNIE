"""Tests for Executor node."""

from unittest.mock import MagicMock

import pytest

from annie.npc.executor import Executor
from annie.npc.state import AgentState, NPCProfile, Personality, Task, TaskStatus
from annie.npc.tracing import EventType, Tracer


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
    return NPCProfile(
        name="Elder",
        personality=Personality(traits=["wise", "cautious"], values=["safety"]),
    )


@pytest.fixture
def executor(mock_llm, mock_memory_agent):
    return Executor(mock_llm, mock_memory_agent)


class TestExecutor:
    def test_processes_tasks(self, executor, npc_profile):
        tracer = Tracer("Elder")
        tasks = [
            Task(description="Observe the stranger"),
            Task(description="Recall past encounters"),
        ]
        state: AgentState = {
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

    def test_memory_agent_queried(self, executor, npc_profile, mock_memory_agent):
        tracer = Tracer("Elder")
        tasks = [Task(description="Observe the stranger")]
        state: AgentState = {
            "npc_profile": npc_profile,
            "input_event": "Event",
            "tasks": tasks,
            "tracer": tracer,
        }
        executor(state)
        mock_memory_agent.build_context.assert_called_once()

    def test_tracing_events(self, executor, npc_profile):
        tracer = Tracer("Elder")
        tasks = [Task(description="Observe the stranger")]
        state: AgentState = {
            "npc_profile": npc_profile,
            "input_event": "Event",
            "tasks": tasks,
            "tracer": tracer,
        }
        executor(state)
        event_types = [e.event_type for e in tracer.events]
        assert EventType.NODE_ENTER in event_types
        assert EventType.NODE_EXIT in event_types
        assert EventType.MEMORY_READ in event_types
        assert EventType.LLM_CALL in event_types
        assert EventType.LLM_RESPONSE in event_types

    def test_works_without_tracer(self, executor, npc_profile):
        tasks = [Task(description="Observe the stranger")]
        state: AgentState = {
            "npc_profile": npc_profile,
            "input_event": "Event",
            "tasks": tasks,
        }
        result = executor(state)
        assert len(result["execution_results"]) == 1

    def test_empty_tasks(self, executor, npc_profile):
        tracer = Tracer("Elder")
        state: AgentState = {
            "npc_profile": npc_profile,
            "input_event": "Event",
            "tasks": [],
            "tracer": tracer,
        }
        result = executor(state)
        assert result["execution_results"] == []
        assert result["tasks"] == []
