## Context

The active routing work gives `NPCAgent.run()` explicit execution intent through `AgentContext.route` and route-aware tool/output contracts. That solves the immediate problem of forcing every request through one `Planner -> Executor -> Reflector` path, but it still leaves the long-term public abstraction at a coarse route level.

The desired end state is more precise: the NPC layer owns a finite set of legal, business-agnostic cognitive graphs, and the world engine requests one by stable graph identifier. The world engine should never assemble LangGraph nodes or edges. It should only choose a predeclared cognitive flow and provide route-appropriate `AgentContext` data, tools, evidence, and output requirements.

## Goals / Non-Goals

**Goals:**

- Make `graph_id` the long-term public dispatch API for NPC cognition.
- Keep `AgentRoute` as a compatibility alias, fallback, or internal classification during migration.
- Move action, dialogue, structured-output, and reflection execution behind registered graph IDs.
- Keep graph construction, node composition, state transitions, tool policy binding, response projection, and tracing inside `src/annie/npc/`.
- Use a lightweight registry of graph builder entries instead of a heavy graph-spec DSL.
- Ensure graph identifiers describe generic cognitive flow, not business domains.
- Preserve NPC statelessness across runs.
- Preserve existing route allowlist safety by associating each graph entry with a coarse route kind or equivalent policy classification.

**Non-Goals:**

- Let world engines pass arbitrary node lists, edges, graph specs, or graph policies into the NPC layer.
- Add business-specific graph identifiers such as town schedules, war-game deception, interrogation clues, factions, suspects, or scene phases.
- Move macro planning, schedule lifecycle, business JSON validation, memory persistence policy, or action arbitration into the NPC layer.
- Introduce a declarative graph DSL on top of LangGraph in the first implementation.
- Dynamically register graphs from world-engine code at runtime.
- Remove all route compatibility in the same change.

## Decisions

### `graph_id` is the public dispatch contract

`AgentContext` will gain a first-class `graph_id` field. When present, `graph_id` selects the NPC-owned cognitive graph to run. This should become the preferred public API for concrete world engines.

Initial graph IDs should be stable, generic, and cognition-oriented, for example:

```text
action.executor_default
action.plan_execute
dialogue.memory_then_output
output.structured_json
reflection.evidence_to_memory_candidate
```

Exact names may change during implementation, but names must not encode business domains.

Alternative considered: keep `AgentRoute` as the permanent public API and add policy knobs. This keeps the API smaller, but route names are too coarse to represent distinct legal graph paths without either hidden branching or exposing ad-hoc policy fields.

### `AgentRoute` becomes compatibility and classification, not scheduling

`AgentRoute` may remain useful as an internal route kind for tool filtering, output contracts, and compatibility mapping. It should not be the long-term scheduling abstraction for world engines.

Resolution order should be:

1. explicit `graph_id`;
2. explicit `route` mapped to a default graph ID;
3. legacy `extra["npc_direct_mode"]` mapped to a default graph ID;
4. default action graph.

If both `graph_id` and `route` are supplied, the graph ID wins, but the implementation should either validate route-kind consistency or include debug metadata that makes the chosen graph unambiguous.

Alternative considered: remove `AgentRoute` immediately. This would make the API cleaner, but it creates unnecessary churn while the route-aware change and downstream integrations are still settling.

### Use a lightweight graph registry, not a full `GraphSpec` DSL

The first implementation should introduce a registry of graph entries with builder functions and minimal metadata:

```python
@dataclass(frozen=True)
class GraphEntry:
    id: str
    route_kind: AgentRoute
    build: Callable[..., CompiledGraph]
    response_kind: str
```

The exact type can differ, but the shape should stay small. The graph builder may use ordinary Python and LangGraph APIs to wire nodes. The registry is declarative at the dispatch level, not a new language for declaring every node and edge.

Alternative considered: introduce a rich `GraphSpec` with nodes, edges, retry policies, tool allowlists, response schemas, and observability directives. That may become useful later, but it is premature until there are enough graphs and governance needs to justify another abstraction.

### World engines can select graphs but cannot construct them

World engines may set `AgentContext.graph_id` to a registered ID. They must not pass node names, edge definitions, graph objects, builder functions, or custom graph specs into `AgentContext`.

This preserves the NPC/world-engine boundary:

```text
WorldEngine:
  choose graph_id
  provide context, tools, evidence, output requirements
  parse/validate/persist/arbitrate business results

NPC Layer:
  resolve graph_id
  build or fetch compiled graph
  run cognitive nodes
  enforce graph tool/output policy
  return AgentResponse and debug metadata
```

### Graph entries own tool policy classification

Each registered graph must have enough metadata to apply existing route-specific tool policy before tools are bound or dispatchable. A graph entry can carry `route_kind` or an equivalent tool-policy key.

`disabled_tools` remains only a narrowing mechanism after graph policy is applied. It must never grant a tool forbidden by the selected graph.

### Graph execution should converge on one state and response model

Existing node state should evolve toward one graph state model that can support action, dialogue, structured output, and reflection graphs. Output nodes such as `DialogueOutput`, `JSONOutput`, and `ReflectionOutput` should project graph state into `AgentResponse` fields rather than carry business behavior.

This does not require every graph to share every state key. It does require graph output to be observable and testable through consistent response/debug metadata.

### Registry caching must remain stateless with respect to NPC runs

Compiled graph objects may be cached on the `NPCAgent` instance or module-level registry if they are immutable with respect to a run. Per-NPC and per-run data must still enter through `AgentContext` and graph state.

The registry must not cache world state, memory results, profile data, tool runtime state, or previous responses.

## Risks / Trade-offs

- Graph ID proliferation → Keep an intentionally small initial graph set and require generic cognition-oriented names.
- Hidden behavior behind graph IDs → Include selected graph ID, route kind, node path, and bound tool names in bounded debug metadata.
- Premature registry abstraction → Start with builder functions and minimal entries; defer a rich `GraphSpec` until real graph governance pressure appears.
- Compatibility confusion between route and graph ID → Define deterministic resolution order and tests for route/direct-mode mappings.
- Tool exposure regression → Make graph entry route-kind/tool policy mandatory and test every initial graph's bound tools.
- Business leakage through graph names → Reject or avoid graph IDs that encode concrete games, schedules, evidence types, factions, or scene phases.

## Migration Plan

1. Add `AgentContext.graph_id` and graph ID resolution with default mappings from existing routes/direct modes.
2. Introduce the lightweight NPC graph registry and register default graphs for action, dialogue, structured output, and reflection.
3. Route `NPCAgent.run()` through graph resolution and registry lookup.
4. Convert non-action direct handlers into graph-backed execution paths incrementally while preserving response contracts.
5. Add debug metadata for selected graph ID, route kind, node path, and bound tool names.
6. Update world-engine integrations to set `graph_id` directly for flows that already know the desired cognitive graph.
7. Keep `AgentRoute` compatibility until downstream integrations and tests no longer rely on it, then consider deprecating it in a later change.
