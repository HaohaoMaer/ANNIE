"""Integration test: NPCAgent + DefaultWorldEngine end-to-end.

Uses a stubbed LLM to exercise the full Planner → Executor → Reflector graph
over the new native tool-use loop.
"""

from __future__ import annotations

import chromadb
import pytest
from langchain_core.messages import AIMessage, BaseMessage, SystemMessage

from annie.npc.agent import NPCAgent
from annie.npc.response import AgentResponse
from annie.world_engine import DefaultWorldEngine
from annie.world_engine.profile import NPCProfile


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
        '{"decision":"skip","reason":"simple event","tasks":[]}',
        "Alice nods and greets the newcomer.",
        '{"reflection":"Met someone new at the tavern.","facts":["A newcomer arrived"],"relationship_notes":[]}',
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

    assert response.memory_updates, "agent should return reflection memory updates"

    # handle_response must NOT write episodic records; the vector store holds
    # only distilled content (reflection, semantic, impression, todo).
    we.handle_response("alice", response)
    records = we.memory_for("alice").recall("newcomer", k=5)
    assert records, "world engine should persist reflection records from response"
    episodic_records = we.memory_for("alice").grep(
        "", category="episodic", k=50,
    )
    assert episodic_records == [], (
        "handle_response must not write episodic entries to the vector store"
    )


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
        '{"decision":"skip","reason":"simple event","tasks":[]}',
        think_call,
        reply,
        '{"reflection":"pondered.","facts":[],"relationship_notes":[]}',
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
        '{"decision":"skip","reason":"single step","tasks":[]}',  # planner
        first_ai,                                    # executor step 1 (tool call)
        second_ai,                                   # executor step 2 (final)
        '{"reflection":"reflected.","facts":[],"relationship_notes":[]}',  # reflector
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
        '{"decision":"skip","reason":"simple event","tasks":[]}',
        "Carol waves.",
        '{"reflection":"waved.","facts":[],"relationship_notes":[]}',
    ])
    ctx1 = we.build_context("carol", event="A friend appears.")
    agent = NPCAgent(llm=llm)
    resp1 = agent.run(ctx1)
    we.handle_response("carol", resp1)

    # Second run should see Carol's prior utterance in history.
    ctx2 = we.build_context("carol", event="Later that day.")
    assert "Carol waves." in ctx2.history or "waves" in ctx2.history


# ---------------------------------------------------------------------------
# New tests: skills rendering, todo section, use_skill path
# ---------------------------------------------------------------------------

def test_available_skills_rendered_in_executor_system(tmp_path, tmp_chroma):
    """<available_skills> in the Executor system prompt lists skills from skills_dir."""
    skill_dir = tmp_path / "skills" / "myfeat"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.yaml").write_text(
        "name: myfeat\none_line: 我的特殊能力\nextra_tools: []\n"
    )
    (skill_dir / "prompt.md").write_text("Feature prompt.")

    we = DefaultWorldEngine(chroma_client=tmp_chroma, history_dir=tmp_path / "hist")
    we.register_profile("alice", NPCProfile(name="Alice"))

    llm = _StubLLM([
        '{"decision":"skip","reason":"simple event","tasks":[]}',
        "Alice replies.",
        '{"reflection":"test.","facts":[],"relationship_notes":[]}',
    ])

    ctx = we.build_context("alice", event="Anything.")
    NPCAgent(llm=llm, skills_dir=str(tmp_path / "skills")).run(ctx)

    # Executor is the second LLM invocation (index 1; index 0 is Planner)
    system_content = llm.calls[1][0].content
    assert "<available_skills>" in system_content
    assert "myfeat" in system_content
    assert "我的特殊能力" in system_content


def test_todo_section_reflects_open_todos(tmp_path, tmp_chroma):
    """<todo> in the Executor system prompt shows pre-stored open todos."""
    we = DefaultWorldEngine(chroma_client=tmp_chroma, history_dir=tmp_path / "hist")
    we.register_profile("eve", NPCProfile(name="Eve"))

    # Pre-store a todo directly via the memory interface
    we.memory_for("eve").remember(
        "Investigate the library",
        category="todo",
        metadata={"status": "open", "todo_id": "abc12345"},
    )

    llm = _StubLLM([
        '{"decision":"skip","reason":"simple event","tasks":[]}',
        "Eve looks around.",
        '{"reflection":"test.","facts":[],"relationship_notes":[]}',
    ])

    ctx = we.build_context("eve", event="Something happens.")
    NPCAgent(llm=llm).run(ctx)

    system_content = llm.calls[1][0].content
    assert "<todo>" in system_content
    assert "abc12345" in system_content
    assert "Investigate the library" in system_content


def test_use_skill_appends_system_message(tmp_path, tmp_chroma):
    """use_skill activation appends a skill-prompt SystemMessage visible to the next loop step."""
    skill_dir = tmp_path / "skills" / "spy"
    skill_dir.mkdir(parents=True)
    (skill_dir / "skill.yaml").write_text(
        "name: spy\none_line: Spy skill\nextra_tools:\n  - memory_recall\n"
    )
    (skill_dir / "prompt.md").write_text("You are in spy mode. Gather intel.")

    we = DefaultWorldEngine(chroma_client=tmp_chroma, history_dir=tmp_path / "hist")
    we.register_profile("spy_npc", NPCProfile(name="Spy"))

    use_skill_ai = AIMessage(
        content="",
        tool_calls=[{
            "name": "use_skill",
            "args": {"skill_name": "spy", "args": {}},
            "id": "call_skill",
        }],
    )
    recall_ai = AIMessage(
        content="",
        tool_calls=[{
            "name": "memory_recall",
            "args": {"query": "intel", "k": 3},
            "id": "call_recall",
        }],
    )
    final_ai = AIMessage(content="Spy has gathered the intel.")

    llm = _StubLLM([
        '{"decision":"skip","reason":"simple event","tasks":[]}',  # planner
        use_skill_ai,       # executor step 1: call use_skill
        recall_ai,          # executor step 2: call memory_recall (after skill activated)
        final_ai,           # executor step 3: final answer
        '{"reflection":"spied.","facts":[],"relationship_notes":[]}',
    ])

    ctx = we.build_context("spy_npc", event="Find out what's happening.")
    response = NPCAgent(llm=llm, skills_dir=str(tmp_path / "skills")).run(ctx)

    assert "intel" in response.dialogue

    # llm.calls[2] = third overall invoke = second executor step (after use_skill processed)
    # The messages list at that point includes the SystemMessage appended by skill activation.
    post_skill_messages = llm.calls[2]
    system_contents = [
        m.content for m in post_skill_messages if isinstance(m, SystemMessage)
    ]
    assert any("spy mode" in c for c in system_contents), (
        f"Expected skill-prompt SystemMessage in messages after use_skill; "
        f"got system messages: {system_contents}"
    )
