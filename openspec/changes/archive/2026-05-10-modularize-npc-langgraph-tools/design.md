## Context

The refactor already separates the stateless NPC Agent layer from the business-owning world-engine layer. Recent routing and graph-registry work introduced `AgentContext.route` compatibility and `AgentContext.graph_id` dispatch, but graph entries are still described mostly as whole cognitive flows.

The requested next step is to make the NPC layer own a set of smaller, functionally independent LangGraph nodes and compose them into registered graphs for different world-engine needs. The same change should simplify action arbitration: world engines should execute tools directly and return explicit execution status, instead of supporting both engine-executed tools and declarative intent-style tool use.

## Goals / Non-Goals

**Goals:**

- Define business-agnostic NPC node categories such as action, output, memory, planning, and reflection.
- Build registered LangGraph graphs by composing NPC-owned nodes.
- Keep graph IDs as the world-facing dispatch API and keep `route` as compatibility/policy classification.
- Keep all graph construction, node wiring, node state, tool binding, and response projection inside `src/annie/npc/`.
- Make world-engine tool execution the only world side-effect path for this stage.
- Return explicit tool execution statuses that can be fed back into NPC context or persisted by the engine.
- Preserve the NPC/world-engine boundary: NPC nodes can reason, call exposed tools, and format outputs; world engines own business state, tool implementations, and arbitration outcomes.

**Non-Goals:**

- Allow world engines to define LangGraph nodes, edges, compiled graphs, builder functions, or dynamic graph specs.
- Add business-specific graph IDs or node types for towns, clues, factions, suspects, phases, schedules, or concrete games.
- Introduce a new declarative graph DSL on top of LangGraph.
- Preserve declarative action intent as a parallel execution path.
- Move macro planning, schema validation, memory persistence policy, or world state mutation into the NPC layer.

## Decisions

### Node composition becomes the internal graph model

Registered graphs should be assembled from NPC-owned node implementations. Initial node categories should stay broad and functional:

```text
planning.*     run-local task decomposition and retry planning
memory.*       recall/grep/context preparation nodes
action.*       LLM tool-use execution nodes
output.*       dialogue, JSON, status, and response projection nodes
reflection.*   evidence-to-reflection generation nodes
```

Node names are implementation and debug concepts, not world-engine business APIs. The stable external selector remains `graph_id`.

Alternative considered: keep each graph builder as a private monolith. That minimizes immediate code movement, but it makes graph behavior harder to test, reuse, and evolve.

### Graph registry entries describe composition and policy

The graph registry should evolve from "ID plus builder" into a lightweight entry that includes stable ID, route/policy classification, node composition metadata, builder, response kind, and observability labels. The builder may still be ordinary Python using LangGraph APIs; composition metadata is for validation, tests, and debug output, not a new graph DSL.

Alternative considered: define every node and edge through a rich `GraphSpec` data model. That is premature until there are many graphs and governance needs.

### World engines select graphs, not nodes

World engines may select a registered `graph_id`, provide context, tools, evidence, and output requirements, then receive an `AgentResponse`. They must not select individual nodes or construct graph structure. This preserves the layer boundary while still letting the NPC layer reuse nodes internally.

Alternative considered: expose node selection knobs to engines. That would blur the boundary and let business code accidentally depend on NPC internals.

### Tool execution has one status-returning path

For action-capable graphs, world-engine injected tools are the single mechanism for world side effects. A tool call returns a structured status such as:

```text
success
failure
running
rejected
invalid
```

The status should include bounded fields such as tool name, call ID, summary message, optional result payload, retry hint, and whether the world state changed. The NPC layer may surface these statuses in `AgentResponse` and debug metadata, but it does not decide the business meaning of those statuses.

Alternative considered: keep declarative intent requests alongside tool execution. That preserves flexibility, but the project does not yet have enough stable action semantics to justify two arbitration systems.

### Output nodes project graph state into `AgentResponse`

Output behavior should be explicit nodes rather than ad-hoc post-processing scattered across routes. Examples include action response projection, dialogue text projection, structured-output projection, and reflection candidate projection. These nodes should not perform business validation or persistence.

Alternative considered: each graph returns arbitrary state and `NPCAgent.run()` normalizes it. That makes tests less precise and hides graph-specific contracts.

## Risks / Trade-offs

- Node abstraction churn -> Keep node interfaces small and only extract nodes that are reused or independently testable.
- Graph ID and node name confusion -> Treat graph IDs as public and node names as bounded debug metadata only.
- Tool status schema over-design -> Start with a minimal enum plus message/payload fields and extend from concrete engine needs.
- Regression in action flows -> Add compatibility tests proving default action graph still exposes action tools and reports world-engine statuses.
- Loss of high-level intent data -> Engines can derive or log intent from tool call arguments, but declarative intent objects should not drive execution in this stage.

## Migration Plan

1. Introduce NPC node interfaces and initial node categories without changing public graph IDs.
2. Convert existing action, dialogue, structured JSON, and reflection graphs to use node-composed LangGraph builders.
3. Extend graph registry entries with composition and policy metadata.
4. Introduce structured tool execution status types in the world-engine layer.
5. Update action graph execution and `AgentResponse` projection to surface tool statuses instead of declarative action intents.
6. Remove or quarantine old intent-declaration arbitration paths behind compatibility tests, then delete once concrete engines no longer call them.
7. Update tests for graph selection, node path observability, route compatibility, and world-engine tool status handling.

## Open Questions

- Whether `running` statuses need a first-class follow-up token/correlation ID in the initial implementation or can reuse existing tool call IDs.
- Whether tool status payloads should be plain dicts initially or a typed generic container with engine-specific payload models.
