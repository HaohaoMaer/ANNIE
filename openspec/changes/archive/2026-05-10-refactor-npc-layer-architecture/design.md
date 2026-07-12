## Context

The NPC Agent layer is intended to be a generic cognitive runtime, not a gameplay engine. Its essential contract is:

```text
WorldEngine.build_context(...) -> AgentContext
NPCAgent.run(context) -> one registered NPC graph -> AgentResponse
WorldEngine.handle_response(...)
```

All per-NPC and per-run information must enter through `AgentContext`: identity text, current event, prompt text, memory interface, tools, skills, route/graph selection, and open metadata. The NPC layer may reason, call bound tools, activate skills, and produce bounded output, but it must not own world state, parse world data, persist long-term memory directly, or decide business lifecycle.

Current code mostly follows this contract, but the implementation obscures the model:

- `agent.py` mixes public orchestration, graph selection, runner-specific setup, LangGraph compilation, node implementations for direct routes, retry routing, and response construction.
- `executor.py` is responsible for task execution, tool loop control, skill frame lifecycle, prompt assembly, productive-effect detection, and task result projection.
- `runtime` is an open dict whose keys are written and read across multiple modules without one obvious owner.
- The old conceptual language of `Planner -> Executor -> Reflector` is still visible, but current registered action graphs are `Executor -> output` or `Planner -> Executor -> output`; durable reflection is a separate route unless a future graph explicitly selects it.

The refactor should make the existing design legible without changing behavior.

## Goals / Non-Goals

**Goals:**

- Make the NPC layer readable as a stateless, business-agnostic graph runtime.
- Keep `NPCAgent.run(context)` small enough to show the high-level flow: resolve graph, create run runtime, execute graph, project response.
- Move graph compilation and node wiring behind graph-owned modules or builders.
- Move run setup into a typed or named runtime object so tool registry, skill runtime, tool statuses, memory updates, and skill frames have an explicit home.
- Keep route and graph policies structurally enforced before tools are bound or dispatched.
- Preserve behavior and public contracts while improving file organization and naming.
- Make tests assert behavior at the contract level rather than depending on incidental module layout.

**Non-Goals:**

- Do not redesign `AgentContext`, `AgentResponse`, `ToolDef`, `SkillDef`, or `MemoryInterface`.
- Do not add a declarative graph DSL.
- Do not move world-engine tool implementations, memory backends, history, compression, NPC YAML parsing, or business validation into `src/annie/npc/`.
- Do not introduce new LLM configuration paths.
- Do not change prompt semantics beyond mechanical relocation required by the refactor.
- Do not make `Reflector` part of the default action route unless a separate behavioral change explicitly requests that graph.

## Decisions

### Decision 1: Keep the core mental model explicit

The refactored code should make this flow visible:

```text
AgentContext
  -> graph resolution
  -> graph policy/runtime creation
  -> graph execution
  -> AgentResponse projection
```

Rationale: this is the actual architecture boundary between the NPC layer and world engine. It is more important than preserving the current physical file layout.

Alternative considered: keep `agent.py` as the single place where all LangGraph wiring lives. This preserves locality but keeps hiding the architecture in one large coordinator.

### Decision 2: Split orchestration from graph builders

`NPCAgent` should remain the public facade. Graph-specific wiring should live in dedicated builder modules or clearly named functions grouped by runner:

- action graph builder
- dialogue graph builder
- structured JSON graph builder
- reflection graph builder

Rationale: each runner has different setup and tool policy. Grouping them by graph behavior makes route behavior easier to inspect and reduces `agent.py` churn.

Alternative considered: move everything into `graph_registry.py`. That would overload the registry with implementation details; the registry should describe legal graphs and policy metadata, not contain all node code.

### Decision 3: Introduce an explicit run runtime boundary

Replace ad hoc runtime dict construction with a small NPC-owned runtime helper or model that still exposes dict-like data where current tools require it. The runtime should own:

- `tool_registry`
- `skill_runtime`
- `recall_seen_ids`
- `inner_thoughts`
- `memory_updates`
- `action_results`
- `tool_statuses`
- `skill_frames`
- current loop `messages` when a skill activation needs access

Rationale: the runtime dict is currently the invisible dependency graph between tools, dispatcher, executor, and response projection. Naming this boundary makes ownership and lifecycle clearer without changing tool contracts.

Alternative considered: fully replace runtime dict with a Pydantic model. That is cleaner but higher risk because existing tools and tests expect mutable dict behavior.

### Decision 4: Keep Executor focused on action task execution

`Executor` should remain the action node's LLM tool-use loop, but supporting concerns should be isolated:

- initial message assembly remains prompt-owned
- tool dispatch stays in `ToolDispatcher`
- skill activation stays in `SkillRuntime` and `UseSkillTool`
- task outcome projection is extracted or made locally obvious
- frame cleanup is kept close to the loop because it is a loop lifecycle concern

Rationale: the executor is the hardest code to understand today. It should read as a bounded ReAct loop over tasks, not as the whole runtime.

Alternative considered: split Executor into many tiny classes immediately. That risks fragmentation before the boundaries are proven. Prefer a conservative first refactor with named helpers and moved setup.

### Decision 5: Preserve current reflection semantics

The standalone `Reflector` class may be retained, clarified, or moved, but the default action route must not silently gain durable reflection. Reflection remains route-owned unless a registered action graph explicitly includes a reflection node.

Rationale: existing specs state that durable reflection is optional for action graphs and should usually be requested through the reflection route when the world engine decides reflection is due.

Alternative considered: make all action runs end with Reflector. That would be a behavioral change and would blur world-engine ownership of memory persistence timing.

### Decision 6: Verify by contract tests first

Refactor in small, behavior-preserving slices and keep the following tests green:

- route and graph selection
- route tool policy
- skill registry and skill activation frame behavior
- executor loop and retry behavior
- recall dedup
- integration decoupled flow and cross-run todo

Rationale: this is a readability refactor with architectural risk. The safest success condition is unchanged observable behavior.

Alternative considered: broad rewrite followed by test repair. That makes it harder to tell whether failures are expected refactor fallout or unintended behavior changes.

## Risks / Trade-offs

- Runtime helper could accidentally change tool-visible dict behavior -> keep compatibility by exposing the same keys and passing the same mutable mapping into `ToolContext`.
- Moving graph builder code can break debug node-path metadata -> preserve node labels exactly and add/keep tests for `debug["node_path"]`.
- Extracting response projection can change empty dialogue/tool status behavior -> snapshot current behavior with focused tests before changing projection code.
- Keeping compatibility paths such as `extra["npc_direct_mode"]` preserves some complexity -> leave migration cleanup to a separate behavior change.
- Conservative refactor may not make every file perfect -> prioritize clear flow and stable boundaries over exhaustive cleanup in one pass.

## Migration Plan

1. Add or confirm characterization tests around current NPC route behavior, graph debug metadata, tool policy, executor retry, skill frames, and response projection.
2. Extract graph resolution and runtime construction from `agent.py` without changing behavior.
3. Move graph compilation/wiring into graph runner builders while preserving registered graph IDs and node labels.
4. Extract response projection helpers for action, dialogue, structured JSON, and reflection responses.
5. Simplify `Executor` with named helpers for task execution and loop outcome handling.
6. Run focused NPC tests and integration tests after each slice.
7. Keep rollback simple by making each slice mechanically revertible and behavior-preserving.

## Open Questions

- Should the existing standalone `Reflector` class be kept as a future action-graph node implementation, or renamed/moved to make clear that it is not part of the default action route?
- Should the runtime helper remain an internal dict factory for now, or become a lightweight class with explicit properties and a `mapping` attribute?
- Should compatibility support for `extra["npc_direct_mode"]` be documented as deprecated in code comments during this refactor, or left untouched until a migration change?
