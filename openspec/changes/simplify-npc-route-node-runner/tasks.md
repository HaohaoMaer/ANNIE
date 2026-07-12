## 1. Route Model And Runner

- [x] 1.1 Add route/node model types for route id, node id, route spec, route edge, and route execution errors.
- [x] 1.2 Add a global NPC node registry that maps business-agnostic node ids to callable node implementations.
- [x] 1.3 Add a thin Python route runner that executes the current node, records bounded debug node path, evaluates only route-local outgoing edges, and stops at route exits.
- [x] 1.4 Add generic edge condition helpers such as `always`, `needs_replan`, `action_done`, and `has_tasks` without introducing shared edge fragments.

## 2. Route Specifications

- [x] 2.1 Define action route specs for default execution and planner-enabled execution using route-local edges.
- [x] 2.2 Define dialogue, reflection, and structured JSON route specs using route-local edges and existing route tool policies.
- [x] 2.3 Map existing `RouteID` values and route/obsolete direct-mode compatibility inputs to route specs without changing external selection fields.
- [x] 2.4 Ensure each route spec declares entry node, exit nodes, allowed node set, response kind, route/tool policy, and concrete conditional edges.

## 3. Node Migration

- [x] 3.1 Convert preparation and working-memory setup into reusable route nodes.
- [x] 3.2 Convert planner invocation and default-task creation into route nodes that update run state but do not choose global flow.
- [x] 3.3 Convert action execution to a route node while keeping the Executor tool loop internal.
- [x] 3.4 Convert dialogue, reflection, and structured JSON generation to route nodes or direct node callables.
- [x] 3.5 Remove output-only marker nodes whose only behavior is debug path recording; keep response projection outside route execution.

## 4. Agent Facade And Projection

- [x] 4.1 Refactor `NPCAgent.run()` to resolve route id to route spec, create run state/runtime, execute the route runner, and project `AgentResponse`.
- [x] 4.2 Update response projection to use executed route node path and selected route/route metadata.
- [x] 4.3 Preserve bounded debug fields for selected route id, route kind, executed node path, and bound tools.
- [x] 4.4 Keep only necessary external selection fields stable, and do not add internal compatibility wrappers for removed route/builder/node implementations.

## 5. Cleanup And Tests

- [x] 5.1 Add focused route runner unit tests for successful transitions, route exits, missing transition errors, and disallowed target validation.
- [x] 5.2 Add or update NPC route tests proving action replanning is route-local and non-action routes cannot reach action/planning nodes.
- [x] 5.3 Update route registry/routing tests to assert existing route ids map to the expected route specs and response kinds.
- [x] 5.4 Delete obsolete core route builders, direct graph runners, output-only marker nodes, and old compatibility paths once equivalent route runner tests pass.
- [x] 5.5 Run focused tests for NPC routing, route registry, tool registry frames, plan/todo behavior, and decoupled flow.
