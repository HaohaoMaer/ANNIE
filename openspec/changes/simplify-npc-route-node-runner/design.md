## Context

The NPC layer currently exposes graph-id dispatch and route behavior, but the implementation model is still centered on multiple LangGraph builders and several route-specific runner methods. Some graph nodes only mark output/debug phases, while response projection happens elsewhere. This creates duplicated entrypoints for similar behavior and makes route boundaries harder to inspect.

The desired direction is a smaller NPC-owned execution model: reusable capability nodes, route-local conditional edges, and a thin Python runner. The world engine still selects a registered `route_id` or compatibility route, but it does not provide nodes, edges, or dynamic graph structure.

## Goals / Non-Goals

**Goals:**

- Make nodes reusable business-agnostic capability units.
- Make each route an explicit small state machine with its own conditional edges.
- Keep route boundaries readable by declaring every allowed edge inside the route spec.
- Remove LangGraph as the default orchestration abstraction for core NPC routes.
- Preserve external compatibility for existing `route_id`, `route`, and legacy direct-mode selection.
- Remove obsolete internal graph, builder, node, and compatibility code once the route runner replaces it.
- Preserve existing layer invariants: NPC stays stateless across runs, and world side effects occur only through injected tools.

**Non-Goals:**

- Do not introduce a general graph DSL, topological scheduler, or global dynamic graph.
- Do not make route edges globally reusable fragments; duplication is acceptable for route readability.
- Do not expose node or edge selection to the world engine.
- Do not expand Executor's internal ReAct/tool loop into graph nodes.
- Do not change world-engine memory storage, action arbitration, or business schemas.
- Do not keep dead internal compatibility wrappers, deprecated builders, or unused marker nodes after the new route runner is in place.

## Decisions

### Decision: Use route-local state machines instead of a global conditional graph

Each route spec declares its entry node, exit nodes, allowed nodes, and ordered conditional edges. Nodes are globally reusable, but edges are owned by the route.

Rationale: a global graph would make it hard to know which capabilities a route may reach when conditional edges fire. Route-local edges make the full boundary visible in one place.

Alternative considered: one global capability graph with route selecting only an entry. Rejected because conditional transitions could blur route boundaries and make forbidden capabilities easier to reach accidentally.

### Decision: Build a thin Python runner instead of using LangGraph by default

The runner executes the current node, records the node path, evaluates the current route's outgoing edges in deterministic order, and stops at an exit node.

Rationale: the current goal is simplification and readability. A small runner directly expresses the NPC layer's model without LangGraph-specific concepts such as `StateGraph`, compile steps, and builder-local conditional wiring.

Alternative considered: continue with LangGraph and refactor builders. Rejected for this change because the orchestration layer remains more opaque than the desired route/state/node model.

### Decision: Keep `route_id` externally, resolve to `RouteSpec` internally

Existing world engines may continue to set `AgentContext.route_id`. The NPC layer maps route identifiers and route compatibility inputs to registered route specs.

Rationale: this avoids breaking callers while allowing the implementation to use clearer route terminology.

Alternative considered: rename the external field immediately. Rejected because the current specs and integrations already use `route_id`.

### Decision: Make an internal clean break instead of preserving obsolete compatibility code

External selection fields may remain stable where current callers need them, but the old LangGraph-centered internal implementation should not remain as wrappers, deprecated paths, fallback runners, or unused builder code once equivalent route-runner behavior exists.

Rationale: the purpose of this change is to improve readability by reducing duplicate implementations. Keeping old internal paths for compatibility would preserve the same confusion this change is meant to remove.

Alternative considered: leave deprecated wrappers around old route builders during migration. Rejected because the migration target should be a single readable implementation, with tests updated to the new model rather than adapter code kept for old internals.

### Decision: Keep Executor's tool loop inside one capability node

The action execution node owns the bounded ReAct/tool-use loop, including tool binding, dispatch, context budget handling, skill activation cleanup, and task outcome classification.

Rationale: these are tightly coupled local execution concerns. Expanding every LLM/tool step into route graph nodes would increase state surface and obscure cleanup guarantees.

### Decision: Do not reuse edge fragments

Common condition functions may be shared, but each route declares its own concrete edges.

Rationale: duplicated edges are easier to audit than route specs assembled from shared edge fragments. The architecture values route readability over eliminating a small amount of repetition.

## Risks / Trade-offs

- Route specs may duplicate common transitions -> Accept duplication and keep condition functions shared where useful.
- A custom runner could grow into a framework -> Keep the runner minimal: no global graph DSL, no dynamic route creation, no world-provided specs.
- Migration may temporarily leave old graph modules in place -> Treat this as short-lived implementation work only; completion requires deleting obsolete internal builders, wrappers, and marker nodes rather than leaving deprecated paths behind.
- Debug metadata may change shape -> Preserve bounded `route_id`, route kind, executed node path, and bound tools so existing tests have equivalent observability.
