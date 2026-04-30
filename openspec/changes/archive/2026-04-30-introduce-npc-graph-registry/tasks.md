## 1. Public Contract

- [x] 1.1 Add `graph_id` to `AgentContext` as the preferred graph-selection field.
- [x] 1.2 Define the initial stable graph ID constants or enum-like values for action, dialogue, structured output, and reflection graphs.
- [x] 1.3 Implement graph selection resolution order: explicit `graph_id`, then `route`, then legacy `extra["npc_direct_mode"]`, then default action graph.
- [x] 1.4 Add clear errors for unknown graph IDs and tests proving no silent fallback occurs.
- [x] 1.5 Add compatibility tests mapping existing `AgentRoute` values and direct-mode flags to default graph IDs.

## 2. Graph Registry

- [x] 2.1 Create a lightweight NPC-owned graph registry module under `src/annie/npc/`.
- [x] 2.2 Define a minimal graph entry type with graph ID, route-kind/tool-policy classification, builder function, and response kind or response projector metadata.
- [x] 2.3 Register the initial graph entries without introducing a declarative graph DSL.
- [x] 2.4 Ensure registry lookup and graph building are owned entirely by the NPC layer.
- [x] 2.5 Add tests proving world-provided graph structure is not accepted through `AgentContext`.

## 3. Graph Execution

- [x] 3.1 Route `NPCAgent.run()` through graph ID resolution and registry lookup.
- [x] 3.2 Move the default action execution path behind its registered action graph ID.
- [x] 3.3 Move dialogue execution behind its registered dialogue graph ID.
- [x] 3.4 Move structured-output execution behind its registered structured-output graph ID.
- [x] 3.5 Move reflection execution behind its registered reflection graph ID.
- [x] 3.6 Ensure output projection still populates the existing `AgentResponse` fields for each graph family.

## 4. Tool Policy and Statelessness

- [x] 4.1 Apply graph entry route-kind/tool-policy metadata before tools are bound to the LLM.
- [x] 4.2 Preserve `disabled_tools` as a narrowing step after graph policy.
- [x] 4.3 Add tests for bound and dispatchable tool names for each initial graph.
- [x] 4.4 Ensure world-injected tools remain governed by route metadata rather than business-name filtering.
- [x] 4.5 Ensure any compiled graph caching stores only run-neutral graph wiring.

## 5. Observability

- [x] 5.1 Add selected `graph_id` to `AgentResponse` or bounded debug metadata.
- [x] 5.2 Add route-kind classification, node path, and bound tool names to debug metadata where tests need them.
- [x] 5.3 Ensure debug metadata does not expose full model messages, private memory contents, or unbounded traces as stable API.
- [x] 5.4 Update tracing tests to assert graph path observability where applicable.

## 6. World Engine Migration

- [x] 6.1 Update relevant world-engine contexts to select `graph_id` directly when the desired cognitive graph is known.
- [x] 6.2 Keep route-based integrations working through compatibility mapping during migration.
- [x] 6.3 Add tests proving world engines select graph IDs but do not construct NPC graphs.
- [x] 6.4 Ensure graph IDs used by world engines are generic and do not encode business domains.

## 7. Validation

- [x] 7.1 Run targeted NPC routing and registry tests.
- [x] 7.2 Run canonical decoupled-flow and cross-run todo integration tests.
- [x] 7.3 Run `ruff check src/annie/npc src/annie/world_engine`.
- [x] 7.4 Run `openspec validate introduce-npc-graph-registry --strict`.
