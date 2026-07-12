## Why

The current cognitive graph direction is still too coarse: graph IDs select whole flows, but the NPC layer does not yet have a clear contract for smaller, independently useful cognitive nodes that can be recomposed with LangGraph. At the same time, world-action arbitration is split between direct world-engine tool execution and declarative intent-style tool use, which adds complexity before the engine has enough stable semantics to benefit from intent declarations.

This change makes NPC cognition explicitly node-oriented and keeps all world side effects behind world-engine-owned tool execution with explicit execution status.

## What Changes

- Refactor the NPC graph registry contract so registered LangGraph graphs are composed from business-agnostic, functional node categories such as `action`, `output`, `memory`, `planning`, and `reflection`.
- Define reusable NPC-layer node interfaces for inputs, outputs, graph state mutation, observability, and response projection.
- Keep graph identifiers as the world-facing dispatch API, but make graph entries describe their node composition and policy classification.
- Replace the current mixed action arbitration model with one world-engine tool execution path: NPC graph nodes may request/call exposed tools, but the concrete tool implementation and status result are owned by the world engine.
- Remove or deprecate declarative intent-as-tool-use semantics for this stage. The world engine should return explicit tool execution states such as success, failure, running, rejected, or invalid.
- Ensure `AgentResponse` and debug metadata can report selected graph ID, node path, tool calls, and world-engine tool statuses without exposing unbounded internal traces.

## Capabilities

### New Capabilities

- `npc-langgraph-node-composition`: Defines reusable, business-agnostic NPC graph nodes and how registered LangGraph graphs compose them into action/output/reflection flows.

### Modified Capabilities

- `npc-graph-registry`: Graph registry entries now describe node composition and policy metadata instead of only whole-flow builder functions.
- `npc-agent-routing`: Existing routes and graph IDs map onto node-composed graphs, preserving route compatibility while avoiding hidden monolithic route handlers.
- `world-engine`: World action arbitration changes from mixed direct execution plus declarative intent handling to engine-owned tool execution with explicit status results.

## Impact

- Affected NPC code: `src/annie/npc/` graph registry, graph builders, executor/planner/reflector/output node boundaries, `AgentContext`, `AgentResponse`, and tests that assert route/graph behavior.
- Affected world-engine code: world tool interfaces, tool result/status types, `handle_response` action arbitration paths, concrete engine tool implementations, and integration tests around NPC actions.
- API impact: `graph_id` remains the preferred dispatch field; `route` remains a compatibility classification. Tool execution results become explicit status objects rather than implicit declarative intents.
- Dependency impact: LangGraph remains the graph composition mechanism inside the NPC layer; world engines must not provide LangGraph nodes, edges, compiled graphs, or dynamic graph specs.
