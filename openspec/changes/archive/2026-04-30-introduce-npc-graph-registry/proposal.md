## Why

The route-aware NPC layer is moving in the right direction, but keeping route names as the long-term public dispatch contract is too coarse for the desired architecture. The NPC layer should expose pre-registered, legal cognitive graph identifiers as its scheduling API, while keeping graph construction, node composition, tool policy, state flow, and observability fully inside the business-agnostic NPC layer.

## What Changes

- Add a first-class `AgentContext.graph_id` public API for selecting a prebuilt NPC cognitive graph.
- Treat `AgentRoute` as a compatibility alias or internal coarse classification rather than the long-term world-engine scheduling contract.
- Introduce an NPC-owned graph registry that maps stable graph identifiers to lightweight graph builder entries.
- Keep world engines limited to selecting a registered `graph_id`; they must not provide LangGraph nodes, edges, dynamic graph specs, or business-specific graph definitions.
- Refactor existing action, dialogue, structured output, and reflection flows behind registered graph identifiers.
- Keep the initial registry lightweight: builder functions plus minimal metadata, not a new declarative graph DSL.
- Preserve NPC statelessness and business neutrality: graph identifiers describe generic cognition/output flow, not game-specific concepts such as schedules, interrogation, clues, factions, or town behavior.
- Preserve route/tool safety by deriving or attaching route-kind metadata to registered graphs so existing route allowlists and output contracts continue to apply.
- Support temporary migration from existing `AgentContext.route` values and legacy direct-mode flags to default graph identifiers.

## Capabilities

### New Capabilities

- `npc-graph-registry`: Defines the public graph-id dispatch contract, NPC-owned graph registry, allowed graph selection behavior, graph observability, and migration from route-based dispatch.

### Modified Capabilities

- `world-engine`: World engines may request NPC execution by `graph_id` and must not construct or inject NPC cognitive graphs.

## Impact

- Affected public API: `AgentContext` gains `graph_id`; `AgentRoute` becomes transitional or secondary.
- Affected NPC code: `src/annie/npc/agent.py`, graph/node wiring, route resolution, tracing/debug metadata, response construction, and tests around action/dialogue/structured/reflection execution.
- Affected world-engine integrations: any concrete engine that currently selects `AgentContext.route` should migrate to stable graph identifiers when ready.
- Affected tests: NPC graph registry tests, compatibility mapping tests, tool-policy tests per registered graph, and world-engine contract tests proving engines select graph IDs rather than constructing graphs.
