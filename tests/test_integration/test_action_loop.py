"""Integration tests for WorldEngine-driven action attempts."""

from __future__ import annotations

import chromadb
import pytest
from langchain_core.messages import AIMessage, BaseMessage

from annie.npc.agent import NPCAgent
from annie.world_engine import DefaultWorldEngine
from annie.world_engine.profile import NPCProfile


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

    def bind_tools(self, tools):  # noqa: ARG002 - signature compat only
        return self


@pytest.fixture
def tmp_chroma(tmp_path):
    return chromadb.PersistentClient(path=str(tmp_path / "vs"))


def test_request_action_returns_before_reflector(tmp_path, tmp_chroma):
    llm = _StubLLM([
        AIMessage(
            content="",
            tool_calls=[{
                "name": "request_action",
                "args": {"type": "move", "payload": {"to": "kitchen"}},
                "id": "call_move",
            }],
        ),
        '{"reflection":"should not be consumed","facts":["bad"],"relationship_notes":[]}',
    ])
    engine = DefaultWorldEngine(chroma_client=tmp_chroma, history_dir=tmp_path / "hist")
    engine.register_profile("alice", NPCProfile(name="Alice"))

    response = NPCAgent(llm=llm).run(engine.build_context("alice", "Go to the kitchen."))

    assert len(response.actions) == 1
    assert response.actions[0].type == "move"
    assert response.memory_updates == []
    assert len(llm.calls) == 1


def test_request_action_stops_remaining_planned_tasks(tmp_path, tmp_chroma):
    llm = _StubLLM([
        (
            '{"decision":"plan","reason":"two stages",'
            '"tasks":['
            '{"description":"move first","priority":5},'
            '{"description":"speak after moving","priority":4}'
            ']}'
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "request_action",
                "args": {"type": "move", "payload": {"to": "kitchen"}},
                "id": "call_move",
            }],
        ),
        "This planned follow-up should not run before the action resolves.",
        '{"reflection":"should not be consumed","facts":["bad"],"relationship_notes":[]}',
    ])
    engine = DefaultWorldEngine(chroma_client=tmp_chroma, history_dir=tmp_path / "hist")
    engine.register_profile("alice", NPCProfile(name="Alice"))

    ctx = engine.build_context("alice", "Move, then report.")
    ctx.extra["action_planning"] = "always"
    response = NPCAgent(llm=llm).run(ctx)

    assert len(response.actions) == 1
    assert response.actions[0].type == "move"
    assert response.dialogue == ""
    assert len(llm.calls) == 2


def test_world_action_result_stays_inside_executor_react_loop(tmp_path, tmp_chroma):
    llm = _StubLLM([
        AIMessage(
            content="",
            tool_calls=[{
                "name": "world_action",
                "args": {"type": "move", "payload": {"to": "kitchen"}},
                "id": "call_kitchen",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "world_action",
                "args": {"type": "move", "payload": {"to": "hallway"}},
                "id": "call_hallway",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "world_action",
                "args": {"type": "move", "payload": {"to": "kitchen"}},
                "id": "call_kitchen_again",
            }],
        ),
        "Alice reaches the kitchen.",
    ])
    engine = DefaultWorldEngine(chroma_client=tmp_chroma, history_dir=tmp_path / "hist")
    engine.register_profile("alice", NPCProfile(name="Alice"))
    engine.set_location("alice", "study")
    engine.set_exits("study", ["hallway"])
    engine.set_exits("hallway", ["study", "kitchen"])

    response = NPCAgent(llm=llm).run(engine.build_context("alice", "Go to the kitchen."))

    assert response.actions == []
    assert "kitchen" in response.dialogue
    assert len(llm.calls) == 4
    second_executor_messages = "\n".join(str(m.content) for m in llm.calls[1])
    assert "unreachable" in second_executor_messages
    assert "hallway" in second_executor_messages
    assert "请根据以下上下文判断是否需要多步骤计划" not in second_executor_messages
    third_executor_messages = "\n".join(str(m.content) for m in llm.calls[2])
    assert '"status": "succeeded"' in third_executor_messages
    assert "kitchen" in third_executor_messages
    assert "请根据以下上下文判断是否需要多步骤计划" not in third_executor_messages


def test_drive_npc_feeds_failed_action_result_back_to_agent(tmp_path, tmp_chroma):
    llm = _StubLLM([
        AIMessage(
            content="",
            tool_calls=[{
                "name": "request_action",
                "args": {"type": "move", "payload": {"to": "kitchen"}},
                "id": "call_kitchen",
            }],
        ),
        AIMessage(
            content="",
            tool_calls=[{
                "name": "request_action",
                "args": {"type": "move", "payload": {"to": "hallway"}},
                "id": "call_hallway",
            }],
        ),
        "Alice waits in the hallway.",
    ])
    engine = DefaultWorldEngine(chroma_client=tmp_chroma, history_dir=tmp_path / "hist")
    engine.register_profile("alice", NPCProfile(name="Alice"))
    engine.set_location("alice", "study")
    engine.set_exits("study", ["hallway"])
    agent = NPCAgent(llm=llm)

    response = engine.drive_npc(agent, "alice", "Go to the kitchen.")

    assert "hallway" in response.dialogue
    second_run_executor_messages = "\n".join(str(m.content) for m in llm.calls[1])
    assert "unreachable" in second_run_executor_messages
    assert "hallway" in second_run_executor_messages
    assert "请根据以下上下文判断是否需要多步骤计划" not in second_run_executor_messages
