"""Integration test: NPCAgent + DefaultWorldEngine end-to-end.

Uses a stubbed LLM to exercise the full Planner → Executor → Reflector graph
over the new native tool-use loop.
"""

from __future__ import annotations

import chromadb
import pytest
from langchain_core.messages import AIMessage, BaseMessage

from annie.npc.agent import NPCAgent
from annie.npc.response import AgentResponse
from annie.npc.state import NPCProfile
from annie.world_engine import DefaultWorldEngine


class _StubLLM:
    """Round-robin canned AIMessage responses. Supports tool_calls entries.

    Each response may be:
      * str — plain final answer
      * AIMessage — used verbatim (can carry tool_calls)
    """

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

    def bind_tools(self, tools):  # noqa: ARG002 - signature compat only
        return self


@pytest.fixture
def tmp_chroma(tmp_path):
    return chromadb.PersistentClient(path=str(tmp_path / "vs"))


def test_single_npc_single_run(tmp_path, tmp_chroma):
    we = DefaultWorldEngine(chroma_client=tmp_chroma, history_dir=tmp_path / "hist")
    we.register_profile("alice", NPCProfile(name="Alice"))

    llm = _StubLLM([
        '{"skip": true, "reason": "simple event"}',
        "Alice nods and greets the newcomer.",
        "REFLECTION: Met someone new at the tavern.\n"
        'FACTS: ["A newcomer arrived"]\n'
        'RELATIONSHIP_NOTES: []',
    ])

    ctx = we.build_context("alice", event="A stranger walks into the tavern.")
    agent = NPCAgent(llm=llm)
    response = agent.run(ctx)

    assert isinstance(response, AgentResponse)
    assert "Alice" in response.dialogue
    assert "tavern" in response.reflection.lower()

    # Executor system prompt must expose memory category catalog and working_memory.
    executor_first_call = llm.calls[1]
    system_content = executor_first_call[0].content
    assert "<memory_categories>" in system_content
    assert "<working_memory>" in system_content
    # Skip path must not render <task>.
    trigger = executor_first_call[-1].content
    assert "<input_event>" in trigger
    assert "<task>" not in trigger

    records = we.memory_for("alice").recall("newcomer", k=5)
    assert records, "memory should contain reflection records"


def test_inner_monologue_tool_populates_agent_response(tmp_path, tmp_chroma):
    we = DefaultWorldEngine(chroma_client=tmp_chroma, history_dir=tmp_path / "hist")
    we.register_profile("dora", NPCProfile(name="Dora"))

    think_call = AIMessage(
        content="",
        tool_calls=[{
            "name": "inner_monologue",
            "args": {"thought": "I wonder who they are."},
            "id": "call_thought",
        }],
    )
    reply = AIMessage(content="Dora stares silently.")

    llm = _StubLLM([
        '{"skip": true}',
        think_call,
        reply,
        "REFLECTION: pondered.\nFACTS: []\nRELATIONSHIP_NOTES: []",
    ])

    ctx = we.build_context("dora", event="A stranger enters.")
    response = NPCAgent(llm=llm).run(ctx)

    assert "I wonder who they are." in response.inner_thought


def test_tool_use_loop_dispatches_tool(tmp_path, tmp_chroma):
    we = DefaultWorldEngine(chroma_client=tmp_chroma, history_dir=tmp_path / "hist")
    we.register_profile("bob", NPCProfile(name="Bob"))

    # First call from Executor: emit a tool_call to memory_recall.
    first_ai = AIMessage(
        content="",
        tool_calls=[{
            "name": "memory_recall",
            "args": {"query": "who is new", "k": 2},
            "id": "call_1",
        }],
    )
    second_ai = AIMessage(content="Bob greets the newcomer warmly.")

    llm = _StubLLM([
        '{"skip": true, "reason": "single step"}',  # planner
        first_ai,                                    # executor step 1 (tool call)
        second_ai,                                   # executor step 2 (final)
        "REFLECTION: reflected.\nFACTS: []\nRELATIONSHIP_NOTES: []",  # reflector
    ])

    ctx = we.build_context("bob", event="Stranger arrives")
    agent = NPCAgent(llm=llm)
    response = agent.run(ctx)

    assert "Bob greets" in response.dialogue
    # The second executor invocation must have seen a ToolMessage injected.
    executor_second_call = llm.calls[2]
    kinds = [type(m).__name__ for m in executor_second_call]
    assert "ToolMessage" in kinds, f"expected ToolMessage in messages, got {kinds}"


def test_rolling_history_is_injected_on_subsequent_run(tmp_path, tmp_chroma):
    we = DefaultWorldEngine(chroma_client=tmp_chroma, history_dir=tmp_path / "hist")
    we.register_profile("carol", NPCProfile(name="Carol"))

    llm = _StubLLM([
        '{"skip": true}',
        "Carol waves.",
        "REFLECTION: waved.\nFACTS: []\nRELATIONSHIP_NOTES: []",
    ])
    ctx1 = we.build_context("carol", event="A friend appears.")
    agent = NPCAgent(llm=llm)
    resp1 = agent.run(ctx1)
    we.handle_response("carol", resp1)

    # Second run should see Carol's prior utterance in history.
    ctx2 = we.build_context("carol", event="Later that day.")
    assert "Carol waves." in ctx2.history or "waves" in ctx2.history
