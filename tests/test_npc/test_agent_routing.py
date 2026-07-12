from __future__ import annotations

from langchain_core.messages import AIMessage, BaseMessage

from annie.npc.agent import NPCAgent
from annie.npc.core.context import AgentContext
from annie.npc.route.registry import (
    get_route_entry,
    list_route_ids,
)
from annie.npc.memory.interface import MemoryRecord
from annie.npc.core.response import AgentResponse
from annie.npc.core.routes import AgentRoute
from annie.npc.route.route_model import NodeID, RouteID
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
    assert response.route_id == RouteID.ACTION_EXECUTOR_DEFAULT
    assert response.debug["route_id"] == RouteID.ACTION_EXECUTOR_DEFAULT
    assert response.debug["route_kind"] == AgentRoute.ACTION
    assert response.debug["node_path"] == [
        "preparation.action",
        "memory.context",
        "action.tool_execution",
    ]
    assert response.debug["node_composition"] == ["preparation", "memory", "action"]
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

    response = NPCAgent(llm=llm).run(_ctx(extra={"action_planning": "plan"}))

    assert response.route == AgentRoute.ACTION
    assert response.route_id == RouteID.ACTION_PLAN_EXECUTE
    assert response.debug["node_path"] == [
        "memory.context",
        "planning.run_local",
        "action.tool_execution",
    ]
    assert response.debug["node_composition"] == [
        "memory",
        "planning",
        "preparation",
        "action",
    ]
    assert response.dialogue == "NPC completes the planned step."
    assert len(llm.calls) == 2
    assert "请根据以下上下文判断是否需要多步骤计划" in llm.calls[0][-1].content
    assert "<task>" in llm.calls[1][-1].content


def test_action_planning_hint_resolves_to_plan_route():
    llm = _StubLLM([
        (
            '{"decision":"plan","reason":"two steps",'
            '"tasks":[{"description":"check context","priority":5}]}'
        ),
        "NPC completes the planned step.",
    ])

    response = NPCAgent(llm=llm).run(
        _ctx(extra={"action_planning": "plan"})
    )

    assert response.route_id == RouteID.ACTION_PLAN_EXECUTE
    assert response.debug["node_path"] == [
        "memory.context",
        "planning.run_local",
        "action.tool_execution",
    ]


def test_structured_json_route_returns_structured_output():
    llm = _StubLLM(['{"ok": true}'])

    response = NPCAgent(llm=llm).run(_ctx(route=AgentRoute.STRUCTURED_JSON))

    assert response.route == AgentRoute.STRUCTURED_JSON
    assert response.route_id == RouteID.OUTPUT_STRUCTURED_JSON
    assert response.structured_output == '{"ok": true}'
    assert response.dialogue == ""
    assert response.debug["bound_tools"] == []
    assert llm.bound_tool_names == []


def test_reflection_route_has_no_tools_and_no_implicit_memory_context():
    memory = _Memory()
    llm = _StubLLM(["我记住了这件事。"])

    response = NPCAgent(llm=llm).run(_ctx(route=AgentRoute.REFLECTION, memory=memory))

    assert response.route == AgentRoute.REFLECTION
    assert response.route_id == RouteID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE
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
    assert response.route_id == RouteID.DIALOGUE_MEMORY_THEN_OUTPUT
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


def test_route_values_map_to_default_route_ids():
    cases = [
        (AgentRoute.ACTION, RouteID.ACTION_EXECUTOR_DEFAULT),
        (AgentRoute.DIALOGUE, RouteID.DIALOGUE_MEMORY_THEN_OUTPUT),
        (AgentRoute.STRUCTURED_JSON, RouteID.OUTPUT_STRUCTURED_JSON),
        (AgentRoute.REFLECTION, RouteID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE),
    ]

    for route, route_id in cases:
        llm = _StubLLM(["{}" if route == AgentRoute.STRUCTURED_JSON else "ok"])
        response = NPCAgent(llm=llm).run(_ctx(route=route))
        assert response.route_id == route_id


def test_world_provided_route_structure_is_not_context_contract():
    context = AgentContext(
        npc_id="npc1",
        input_event="event",
        memory=_Memory(),
        nodes=["planner", "executor"],
        edges=[("planner", "executor")],
    )

    assert context.route == AgentRoute.ACTION
    assert not hasattr(context, "nodes")
    assert not hasattr(context, "edges")


def test_registered_route_ids_are_generic():
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

    for route_id in list_route_ids():
        assert not any(term in route_id for term in forbidden)


def test_registry_entries_declare_generic_node_composition():
    action_entry = get_route_entry(RouteID.ACTION_EXECUTOR_DEFAULT)
    dialogue_entry = get_route_entry(RouteID.DIALOGUE_MEMORY_THEN_OUTPUT)
    json_entry = get_route_entry(RouteID.OUTPUT_STRUCTURED_JSON)

    assert action_entry.node_composition == ("preparation", "memory", "action")
    assert dialogue_entry.node_composition == ("dialogue",)
    assert json_entry.node_composition == ("structured_output",)


def test_registry_entries_reference_route_specs():
    action_entry = get_route_entry(RouteID.ACTION_PLAN_EXECUTE)
    dialogue_entry = get_route_entry(RouteID.DIALOGUE_MEMORY_THEN_OUTPUT)

    assert action_entry.route_spec.entry_node == NodeID.MEMORY_CONTEXT
    assert NodeID.PLANNING_RUN_LOCAL in action_entry.route_spec.allowed_nodes
    assert NodeID.ACTION_TOOL_EXECUTION in action_entry.route_spec.allowed_nodes
    assert NodeID.PLANNING_RUN_LOCAL not in dialogue_entry.route_spec.allowed_nodes
    assert NodeID.ACTION_TOOL_EXECUTION not in dialogue_entry.route_spec.allowed_nodes
