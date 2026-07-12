## Why

The NPC layer currently spreads execution flow across multiple route builders, route compatibility paths, output marker nodes, and LangGraph-specific wiring. This makes the core cognitive model harder to read and causes similar behaviors to have more than one entrypoint or implementation.

This change simplifies the NPC execution model by treating nodes as reusable capability units and routes as explicit, route-local state machines executed by a small NPC-owned runner.

## What Changes

- Replace LangGraph-first graph composition with an NPC-owned route runner for the core NPC routes.
- Define a global library of business-agnostic NPC capability nodes.
- Define route-local conditional edges; edges are not shared globally and do not become active unless a route declares them.
- Keep `route_id` as the external selection compatibility contract while internally resolving it to a route specification.
- Remove output-only graph nodes whose only behavior is debug path marking; response projection remains outside node execution.
- Delete obsolete internal compatibility paths after migration instead of preserving deprecated wrappers around removed graph, builder, or marker-node implementations.
- Preserve bounded debug metadata by recording the actual route node path during runner execution.
- Keep LangGraph as an optional future implementation detail, not the primary abstraction for NPC route design.

## Capabilities

### New Capabilities

- `npc-route-node-runner`: Defines the NPC-owned node library, route-local conditional edges, and thin route runner execution contract.

### Modified Capabilities

- `npc-graph-registry`: Route identifiers resolve to NPC-owned route specifications rather than requiring LangGraph builders as the core execution mechanism.
- `npc-langgraph-node-composition`: Node composition is generalized away from LangGraph-specific composition toward business-agnostic capability nodes and route-local transitions.
- `npc-layer-architecture`: The stateless facade is refined to resolve route specs, build run state, execute route nodes, and project responses.
- `npc-agent-routing`: Route behavior is clarified as explicit route-local state machines with structurally enforced tool and output policies.

## Impact

- Affected code: `src/annie/npc/agent.py`, route/route registry modules, node helpers, action/direct graph runners, response projection, and route/debug tests.
- External behavior: `AgentContext.route_id`, existing route compatibility, tool policies, and `AgentResponse` fields remain stable during migration.
- Dependencies: No new runtime dependency is introduced; the core runner should use plain Python control flow.
- Migration: Existing route identifiers remain valid but are internally mapped to route specs and policies.
