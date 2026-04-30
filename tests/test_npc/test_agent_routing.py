from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage

from annie.npc.agent import NPCAgent
from annie.npc.context import AgentContext
from annie.npc.graph_registry import AgentGraphID, UnknownAgentGraphError, list_graph_ids
from annie.npc.memory.interface import MemoryRecord
from annie.npc.response import AgentResponse
from annie.npc.routes import AgentRoute
from annie.npc.tools.base_tool import ToolDef
from annie.npc.tools.tool_registry import ToolRegistry


class _StubLLM:
    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[list[BaseMessage]] = []
        self.bound_tool_names: list[list[str]] = []

    def invoke(self, messages, **_):
        self.calls.append(list(messages))
        if not self._responses:
            return AIMessage(content="")
        nxt = self._responses.pop(0)
        if isinstance(nxt, AIMessage):
            return nxt
        return AIMessage(content=str(nxt))

    def bind_tools(self, tools):
        names = []
        for item in tools:
            if isinstance(item, dict):
                names.append(item.get("function", {}).get("name", ""))
        self.bound_tool_names.append(names)
        return self


class _Memory:
    def __init__(self):
        self.build_context_calls = 0

    def recall(self, query, categories=None, k=5):
        return [
            MemoryRecord(
                content=f"remembered {query}",
                category="semantic",
                metadata={},
            )
        ][:k]

    def grep(self, pattern, category=None, metadata_filters=None, k=20):
        return []

    def remember(self, content, category="semantic", metadata=None):
        pass

    def build_context(self, query):
        self.build_context_calls += 1
        return "No relevant memories."


class _WorldTool(ToolDef):
    name = "world_tool"
    description = "fake world mutation"
    is_read_only = False

    def call(self, input, ctx):  # noqa: A002
        return {"mutated": True}


def _ctx(**kwargs) -> AgentContext:
    data = {
        "npc_id": "npc1",
        "input_event": "event",
        "memory": _Memory(),
        "character_prompt": "A cautious resident.",
    }
    data.update(kwargs)
    return AgentContext(**data)


def test_default_context_uses_action_route_without_pre_planner():
    llm = _StubLLM(["NPC acts once."])

    response = NPCAgent(llm=llm).run(_ctx())

    assert isinstance(response, AgentResponse)
    assert response.route == AgentRoute.ACTION
    assert response.graph_id == AgentGraphID.ACTION_EXECUTOR_DEFAULT
    assert response.debug["graph_id"] == AgentGraphID.ACTION_EXECUTOR_DEFAULT
    assert response.debug["route_kind"] == AgentRoute.ACTION
    assert response.debug["node_path"] == ["executor"]
    assert response.dialogue == "NPC acts once."
    assert len(llm.calls) == 1
    assert "请根据以下上下文判断是否需要多步骤计划" not in llm.calls[0][-1].content


def test_action_planning_hint_invokes_run_local_planner():
    llm = _StubLLM([
        (
            '{"decision":"plan","reason":"two steps",'
            '"tasks":[{"description":"check context","priority":5}]}'
        ),
        "NPC completes the planned step.",
    ])

    response = NPCAgent(llm=llm).run(
        _ctx(graph_id=AgentGraphID.ACTION_PLAN_EXECUTE)
    )

    assert response.route == AgentRoute.ACTION
    assert response.graph_id == AgentGraphID.ACTION_PLAN_EXECUTE
    assert response.debug["node_path"] == ["planner", "executor"]
    assert response.dialogue == "NPC completes the planned step."
    assert len(llm.calls) == 2
    assert "请根据以下上下文判断是否需要多步骤计划" in llm.calls[0][-1].content
    assert "<task>" in llm.calls[1][-1].content


def test_legacy_direct_json_maps_to_structured_output_route():
    llm = _StubLLM(['{"ok": true}'])

    response = NPCAgent(llm=llm).run(_ctx(extra={"npc_direct_mode": "json"}))

    assert response.route == AgentRoute.STRUCTURED_JSON
    assert response.graph_id == AgentGraphID.OUTPUT_STRUCTURED_JSON
    assert response.structured_output == '{"ok": true}'
    assert response.dialogue == ""
    assert response.debug["bound_tools"] == []
    assert llm.bound_tool_names == []


def test_reflection_route_has_no_tools_and_no_implicit_memory_context():
    memory = _Memory()
    llm = _StubLLM(["我记住了这件事。"])

    response = NPCAgent(llm=llm).run(_ctx(route=AgentRoute.REFLECTION, memory=memory))

    assert response.route == AgentRoute.REFLECTION
    assert response.graph_id == AgentGraphID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE
    assert response.reflection == "我记住了这件事。"
    assert response.debug["bound_tools"] == []
    assert memory.build_context_calls == 0


def test_reflection_route_rejects_internal_orchestration_terms():
    llm = _StubLLM(["start_conversation tool input_event 都只是内部流程。"])

    response = NPCAgent(llm=llm).run(_ctx(route=AgentRoute.REFLECTION))

    assert response.reflection == ""


def test_dialogue_route_exposes_memory_tools_but_not_world_actions():
    recall = AIMessage(
        content="",
        tool_calls=[{
            "name": "memory_recall",
            "args": {"query": "Alice", "k": 1},
            "id": "call_recall",
        }],
    )
    llm = _StubLLM([recall, "我记得 Alice。"])

    response = NPCAgent(llm=llm).run(
        _ctx(route=AgentRoute.DIALOGUE, tools=[_WorldTool()])
    )

    assert response.route == AgentRoute.DIALOGUE
    assert response.graph_id == AgentGraphID.DIALOGUE_MEMORY_THEN_OUTPUT
    assert response.dialogue == "我记得 Alice。"
    assert llm.bound_tool_names
    assert llm.bound_tool_names[0] == [
        "memory_recall",
        "memory_grep",
        "inner_monologue",
    ]
    assert "world_tool" not in response.debug["bound_tools"]


def test_route_forbidden_tool_is_not_dispatchable():
    registry = ToolRegistry(injected=[_WorldTool()], route=AgentRoute.DIALOGUE.value)

    assert "world_tool" not in registry.list_tools()
    assert registry.get("world_tool") is None


def test_disabled_tools_only_narrows_route_allowlist():
    registry = ToolRegistry(
        injected=[_WorldTool()],
        route=AgentRoute.DIALOGUE.value,
        disabled_tools={"memory_recall"},
    )

    assert "memory_recall" not in registry.list_tools()
    assert "memory_grep" in registry.list_tools()
    assert "world_tool" not in registry.list_tools()


def test_explicit_graph_id_takes_precedence_over_route():
    llm = _StubLLM(['{"ok": true}'])

    response = NPCAgent(llm=llm).run(
        _ctx(
            graph_id=AgentGraphID.OUTPUT_STRUCTURED_JSON,
            route=AgentRoute.DIALOGUE,
        )
    )

    assert response.route == AgentRoute.STRUCTURED_JSON
    assert response.graph_id == AgentGraphID.OUTPUT_STRUCTURED_JSON
    assert response.structured_output == '{"ok": true}'
    assert response.debug["route_kind"] == AgentRoute.STRUCTURED_JSON


def test_unknown_graph_id_fails_without_fallback():
    llm = _StubLLM(["would be fallback"])

    try:
        NPCAgent(llm=llm).run(_ctx(graph_id="town.schedule_generation"))
    except UnknownAgentGraphError as exc:
        assert "town.schedule_generation" in str(exc)
    else:
        raise AssertionError("unknown graph_id did not fail")

    assert llm.calls == []


def test_route_values_map_to_default_graph_ids():
    cases = [
        (AgentRoute.ACTION, AgentGraphID.ACTION_EXECUTOR_DEFAULT),
        (AgentRoute.DIALOGUE, AgentGraphID.DIALOGUE_MEMORY_THEN_OUTPUT),
        (AgentRoute.STRUCTURED_JSON, AgentGraphID.OUTPUT_STRUCTURED_JSON),
        (AgentRoute.REFLECTION, AgentGraphID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE),
    ]

    for route, graph_id in cases:
        llm = _StubLLM(["{}" if route == AgentRoute.STRUCTURED_JSON else "ok"])
        response = NPCAgent(llm=llm).run(_ctx(route=route))
        assert response.graph_id == graph_id


def test_legacy_direct_modes_map_to_default_graph_ids():
    cases = [
        ("dialogue", AgentGraphID.DIALOGUE_MEMORY_THEN_OUTPUT),
        ("json", AgentGraphID.OUTPUT_STRUCTURED_JSON),
        ("reflection", AgentGraphID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE),
    ]

    for direct_mode, graph_id in cases:
        llm = _StubLLM(["ok"])
        response = NPCAgent(llm=llm).run(_ctx(extra={"npc_direct_mode": direct_mode}))
        assert response.graph_id == graph_id


def test_world_provided_graph_structure_is_not_context_contract():
    context = AgentContext(
        npc_id="npc1",
        input_event="event",
        memory=_Memory(),
        graph_id=AgentGraphID.DIALOGUE_MEMORY_THEN_OUTPUT,
        nodes=["planner", "executor"],
        edges=[("planner", "executor")],
    )

    assert context.graph_id == AgentGraphID.DIALOGUE_MEMORY_THEN_OUTPUT
    assert not hasattr(context, "nodes")
    assert not hasattr(context, "edges")


def test_registered_graph_ids_are_generic():
    forbidden = {
        "town",
        "schedule",
        "clue",
        "suspect",
        "faction",
        "war",
        "interrogation",
        "phase",
    }

    for graph_id in list_graph_ids():
        assert not any(term in graph_id for term in forbidden)
