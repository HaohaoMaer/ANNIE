"""Tests for NPCAgent - LangGraph graph wiring and end-to-end flow."""

import json
import uuid
from unittest.mock import MagicMock, patch

import chromadb
import pytest

from annie.npc.agent import AgentRunResult, NPCAgent
from annie.npc.tracing import EventType


@pytest.fixture
def chroma_client():
    return chromadb.EphemeralClient()


def _make_mock_llm():
    """Create a mock LLM that returns appropriate responses for each node."""
    llm = MagicMock()
    call_count = 0

    def mock_invoke(messages):
        nonlocal call_count
        call_count += 1
        response = MagicMock()

        # Planner calls first
        if call_count == 1:
            response.content = json.dumps([
                {"description": "Observe the stranger", "priority": 8},
                {"description": "Prepare a greeting", "priority": 5},
            ])
        # Executor calls for each task (2 tasks)
        elif call_count <= 3:
            response.content = f"The elder performs action for task {call_count - 1}."
        # Reflector call
        else:
            response.content = (
                "REFLECTION: The elder met a stranger and handled it wisely.\n"
                'FACTS: ["A stranger arrived at the village"]'
            )
        return response

    llm.invoke = mock_invoke
    return llm


class TestNPCAgent:
    def test_init_loads_profile(self, chroma_client, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        with patch("annie.npc.agent.create_chat_model", return_value=_make_mock_llm()):
            agent = NPCAgent(
                "data/npcs/example_npc.yaml",
                chroma_client=chroma_client,
            )
        assert agent.npc_profile.name == "Example NPC"

    def test_run_returns_result(self, chroma_client, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        with patch("annie.npc.agent.create_chat_model", return_value=_make_mock_llm()):
            agent = NPCAgent(
                "data/npcs/example_npc.yaml",
                chroma_client=chroma_client,
            )
        result = agent.run("A stranger approaches the village.")
        assert isinstance(result, AgentRunResult)

    def test_run_produces_tasks(self, chroma_client, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        with patch("annie.npc.agent.create_chat_model", return_value=_make_mock_llm()):
            agent = NPCAgent(
                "data/npcs/example_npc.yaml",
                chroma_client=chroma_client,
            )
        result = agent.run("A stranger approaches the village.")
        assert len(result.tasks) == 2
        assert result.tasks[0].description == "Observe the stranger"

    def test_run_produces_execution_results(self, chroma_client, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        with patch("annie.npc.agent.create_chat_model", return_value=_make_mock_llm()):
            agent = NPCAgent(
                "data/npcs/example_npc.yaml",
                chroma_client=chroma_client,
            )
        result = agent.run("A stranger approaches the village.")
        assert len(result.execution_results) == 2
        assert "action" in result.execution_results[0]

    def test_run_produces_reflection(self, chroma_client, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        with patch("annie.npc.agent.create_chat_model", return_value=_make_mock_llm()):
            agent = NPCAgent(
                "data/npcs/example_npc.yaml",
                chroma_client=chroma_client,
            )
        result = agent.run("A stranger approaches the village.")
        assert len(result.reflection) > 0

    def test_run_produces_trace_summary(self, chroma_client, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        with patch("annie.npc.agent.create_chat_model", return_value=_make_mock_llm()):
            agent = NPCAgent(
                "data/npcs/example_npc.yaml",
                chroma_client=chroma_client,
            )
        result = agent.run("A stranger approaches the village.")
        assert "Planner" in result.trace_summary
        assert "Executor" in result.trace_summary
        assert "Reflector" in result.trace_summary
        assert "ms]" in result.trace_summary

    def test_get_last_trace(self, chroma_client, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        with patch("annie.npc.agent.create_chat_model", return_value=_make_mock_llm()):
            agent = NPCAgent(
                "data/npcs/example_npc.yaml",
                chroma_client=chroma_client,
            )
        assert agent.get_last_trace() is None
        agent.run("A stranger approaches.")
        tracer = agent.get_last_trace()
        assert tracer is not None
        assert len(tracer.events) > 0

    def test_trace_has_correct_node_sequence(self, chroma_client, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        with patch("annie.npc.agent.create_chat_model", return_value=_make_mock_llm()):
            agent = NPCAgent(
                "data/npcs/example_npc.yaml",
                chroma_client=chroma_client,
            )
        agent.run("A stranger approaches.")
        tracer = agent.get_last_trace()
        # Extract node_enter events to verify execution order
        enters = [
            e.node_name for e in tracer.events if e.event_type == EventType.NODE_ENTER
        ]
        assert enters == ["planner", "executor", "reflector"]

    def test_trace_has_all_event_types(self, chroma_client, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        with patch("annie.npc.agent.create_chat_model", return_value=_make_mock_llm()):
            agent = NPCAgent(
                "data/npcs/example_npc.yaml",
                chroma_client=chroma_client,
            )
        agent.run("A stranger approaches.")
        tracer = agent.get_last_trace()
        event_types = {e.event_type for e in tracer.events}
        assert EventType.NODE_ENTER in event_types
        assert EventType.NODE_EXIT in event_types
        assert EventType.LLM_CALL in event_types
        assert EventType.LLM_RESPONSE in event_types
        assert EventType.TASK_CREATED in event_types
        assert EventType.MEMORY_WRITE in event_types

    def test_seeds_initial_memories(self, chroma_client, monkeypatch):
        monkeypatch.setenv("DEEPSEEK_API_KEY", "test-key")
        with patch("annie.npc.agent.create_chat_model", return_value=_make_mock_llm()):
            agent = NPCAgent(
                "data/npcs/example_npc.yaml",
                chroma_client=chroma_client,
            )
        # The example NPC has "Initial important memory" as a seed
        facts = agent._semantic.retrieve("important memory", k=1)
        assert len(facts) == 1
        assert "Initial important memory" in facts[0].content


@pytest.mark.integration
class TestNPCAgentIntegration:
    def test_end_to_end_with_real_llm(self, chroma_client):
        agent = NPCAgent(
            "data/npcs/example_npc.yaml",
            chroma_client=chroma_client,
        )
        result = agent.run("You see a stranger approaching the village from the east road.")
        assert len(result.tasks) > 0
        assert len(result.execution_results) > 0
        assert len(result.reflection) > 0
        # Print trace for manual inspection
        tracer = agent.get_last_trace()
        print("\n--- Trace Log ---")
        for line in tracer.to_log_lines():
            print(line)
        print(f"\nSummary: {tracer.summary()}")
