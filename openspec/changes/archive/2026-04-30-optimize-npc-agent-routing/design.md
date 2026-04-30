## Context

`NPCAgent.run()` currently uses one default path for all request types: planner, executor, and reflector. That path is appropriate for open-ended world actions, but it is too expensive and too permissive for structured JSON generation, managed dialogue turns, and distilled reflection.

Recent TownWorld validation exposed the design problem clearly:

- resident schedule generation needs strict structured output, not ReAct-style execution;
- managed NPC-NPC dialogue needs access to memory, but should not execute world actions inside the conversation turn;
- reflection is a cognition-only write candidate and should not pay for planner/executor;
- action turns still need world tools, arbitration, and post-action reflection.

The NPC layer must remain stateless and business-agnostic. The world engine may choose the request route and supply route-appropriate tools/context, but business vocabulary and state remain in the world-engine layer.

## Goals / Non-Goals

**Goals:**

- Replace ad-hoc direct-mode branches with explicit route-aware graph behavior.
- Support exactly four initial route families: world action, managed dialogue, structured JSON, and reflection.
- Keep macro planning, such as daily schedule generation and dynamic schedule revision, world-owned while letting world engines use the structured JSON route to ask the NPC layer for candidate plan text.
- Treat action-route planning as optional, run-local micro planning rather than persistent schedule or strategy ownership.
- Allow managed dialogue to use memory/inner-thought tools while preventing world action side effects.
- Keep route selection observable and testable.
- Preserve world-action tool execution while making planner, executor, and reflector independently routable action-route nodes.
- Document prompt policy expectations for schedule anchoring and tool failure handling.

**Non-Goals:**

- Redesign memory storage, Chroma behavior, or history compression.
- Move TownWorld-specific scheduling or conversation policy into the NPC layer.
- Guarantee model obedience solely through prompts; route tool filtering and output validation must provide structural guardrails.
- Add business-specific route families such as schedule, social, war-game, interrogation, or town-specific planning routes.
- Make the NPC layer own plan persistence, plan progress, rescheduling, cancellation, or decisions about when future world activations should happen.
- Move business JSON schema validation into the NPC layer.

## Decisions

### Route selection is a first-class AgentContext contract

World engines will request a route through a typed `AgentContext.route` field. The field uses a stable public enum, `AgentRoute`, with these initial string values:

- `action`
- `dialogue`
- `structured_json`
- `reflection`

The default route is `action` so existing contexts preserve the current world-action behavior.

Alternative considered: infer route from available tools or `input_event` text. This is brittle and repeats the current prompt-coupling problem.

Alternative considered: keep route in `AgentContext.extra`. This keeps migration small, but it repeats the current `npc_direct_mode` ambiguity and makes route behavior harder to type-check and test.

### Action route is composable, not permanently Planner/Executor/Reflector

The action route remains the only route allowed to execute world tools, but it should not be defined long-term as a mandatory `Planner -> Executor -> Reflector` sequence for every run. The executor is the core action node. Planner and reflector are optional action-route nodes selected by route policy and state:

- simple action turns may go directly to executor;
- complex action turns may invoke planner for run-local task decomposition;
- executor failure, empty output, or stale environment evidence may route to planner before retrying;
- durable reflection should normally be requested through the separate reflection route when the world engine decides reflection is due.

The initial implementation may keep the existing full action path for compatibility while the dispatcher and tests are introduced, but the design target is a composable action graph where planner and reflector are not unavoidable costs.

This also clarifies the meaning of the current planner. It is not a macro planner. It should not generate TownWorld daily schedules, revise persistent plans, choose future activation times, or decide when the world engine should run dialogue or reflection. It only decomposes the current action attempt into a small number of temporary tasks when that helps execution.

Non-action routes do not need to be forced into LangGraph immediately. They may use an explicit route dispatcher with route-specific prompts and output construction while preserving observability through `AgentResponse.route` and debug metadata. A future change may move every route into LangGraph if that provides enough value.

### Macro planning is world-owned and may use structured JSON

TownWorld daily schedules and dynamic schedule revisions are macro plans. They include business state, time windows, accepted locations, validation rules, persistence, progress tracking, and cancellation/revision policy. Those responsibilities remain in the world engine.

When a world engine wants model help to draft a macro plan, it should call the NPC layer through the structured JSON route with explicit output requirements. The NPC layer returns raw structured text. The world engine parses, validates, repairs or rejects it, persists the accepted plan, and later decides which route to call for each activation.

For example:

```text
day start / major event
  WorldEngine -> NPCAgent(route=structured_json, output=schedule or revision)
  WorldEngine -> parse, validate, persist accepted macro plan

each activation
  WorldEngine -> choose action/dialogue/reflection route from current state
  NPCAgent -> produce one bounded response for that route
```

Future games that need persistent multi-step plans should follow the same division: the NPC layer may generate plan candidates, but the concrete world engine owns plan lifecycle and turns plan steps into later route calls.

### Route-specific tool policy is structural, not prompt-only

Each route will expose tools from an allowlist, then apply `disabled_tools` as a second narrowing step. `disabled_tools` must never grant tools forbidden by the route policy.

- `action`: existing action-route tools, including memory tools, inner monologue, `use_skill`, declarative/deferred action built-ins, and world-engine injected tools allowed for action.
- `dialogue`: `memory_recall`, `memory_grep`, and `inner_monologue`; no `use_skill`, no declarative/deferred action built-ins, and no world-action injected tools.
- `structured_json`: no tools.
- `reflection`: no tools; the world engine must provide the evidence and relevant memory explicitly in route context.

Alternative considered: keep all tools bound and instruct the model not to call some of them. This failed in practice when conversation turns attempted unavailable world actions.

Forbidden tools must be both unbound from the LLM and unavailable to dispatch if a model or test attempts to call them by name.

### World-injected tools need route metadata

NPC built-ins can be classified internally, but world-engine injected tools need a structural way to participate in route filtering. `ToolDef` should gain route metadata such as `allowed_routes` or a `tool_kind` that can be mapped to allowed routes.

Name-based filtering, such as guessing that `move` or `wait` are world actions, is not acceptable as the core policy because it is brittle and leaks business vocabulary into the NPC layer.

### Managed dialogue is not the same as world action

Managed dialogue turns should produce only a turn utterance. They may consult memory to stay in character and use relationship context, but they must not move, interact, wait, finish schedules, or start nested conversations. The world engine owns the conversation session and records its outcome.

Alternative considered: use the full action route with disabled world tools. That still invokes planner/reflector and encourages world-action reasoning in the wrong context.

Dialogue route should use its own small tool-loop limit, such as two tool iterations, so it can perform a memory lookup and then produce an utterance without becoming a general action agent.

### Reflection and structured JSON use specialized routes

Reflection and structured output should not use planner/executor. They should use route-specific prompts, output parsing, and response construction.

Structured JSON returns raw structured-output text to the world engine. The NPC layer does not accept business Pydantic schemas, does not perform business validation, and does not decide malformed-output repair policy.

Reflection is cognition-only. It relies on evidence supplied by the world engine rather than active memory recall. Its prompt and post-processing should filter internal orchestration terms such as tool names, graph node names, route names, JSON field names, and implementation phrases.

Alternative considered: keep using the full graph and improve prompts. This wastes calls and makes validation dependent on model obedience.

### AgentResponse carries route-aware outputs

`AgentResponse` should expose route behavior without forcing every route to overload `dialogue`:

- `route`: the route used for this run.
- `structured_output`: raw text from the `structured_json` route.
- `debug`: optional metadata for tests and verbose diagnostics, including bound tool names.

Existing fields remain meaningful:

- `action`: may populate `dialogue`, `actions`, `memory_updates`, `inner_thought`, and `reflection`.
- `dialogue`: primarily populates `dialogue` and may populate `inner_thought`.
- `structured_json`: populates `structured_output`.
- `reflection`: populates `reflection`.

### Schedule prompt policy remains world-owned

The NPC layer should not know about schedules. World engines may include prompt policy text saying schedules are the default anchor; urgent events, direct requests, or clearly valuable opportunities can briefly override when the time budget allows; after a detour, the NPC should return to the schedule.

Schedule generation and schedule revision are also world-owned macro planning use cases. They may be drafted through structured JSON route calls, but acceptance, conflict handling, progress tracking, completion, and dynamic insertion remain outside the NPC layer.

Tool failure may justify checking the environment before retrying, but this remains world-engine prompt policy and not NPC-layer business logic.

### Direct-mode migration is temporary compatibility

Existing `extra["npc_direct_mode"]` usage should be supported briefly by mapping it internally to the new route contract:

- `json` -> `structured_json`
- `dialogue` -> `dialogue`
- `reflection` -> `reflection`

This compatibility path should be covered by migration tests and removed once TownWorld and other integrations request `AgentContext.route` directly.

### Route context and memory are explicit for non-action routes

The action route continues to build `working_memory` through the existing memory context builder. Non-action routes should not implicitly perform pre-run memory context construction. Their evidence, memory summaries, or output requirements must be supplied explicitly by the world engine, except that the dialogue route may call its allowed memory tools during its small tool loop.

## Risks / Trade-offs

- Route proliferation can make the agent harder to reason about. Mitigation: keep a small route enum and require tests for each route.
- Dialogue routes that can use memory may still spend extra calls. Mitigation: cap dialogue tool loops separately from action tool loops.
- Structured JSON routes may still receive malformed JSON. Mitigation: parse and validate at the world-engine boundary, and decide per use case whether fallback or failure is correct.
- Reflection routes may lose useful execution context if too isolated. Mitigation: require the world engine to pass distilled evidence and relevant memory explicitly.
- Making action graphs composable can complicate observability if node choices become hidden. Mitigation: include bounded debug metadata for route, selected action nodes, and bound tool names in tests.
- Executor-first action turns could miss rare cases where pre-planning would help. Mitigation: planner remains available for complex prompts, explicit world-engine hints, retry, and empty/failed executor output.
- Tool route metadata expands the `ToolDef` contract. Mitigation: default existing injected tools to action-only unless explicitly marked otherwise.
- Existing integrations may depend on current default behavior. Mitigation: default route remains `action` unless a world engine opts into another route.

## Migration Plan

1. Add `AgentRoute`, `AgentContext.route`, and route-aware `AgentResponse` fields while keeping default route as `action`.
2. Add route tool policy, world-injected tool route metadata, and route/debug observability.
3. Map existing `npc_direct_mode` flags to the new route internally for temporary compatibility.
4. Implement the explicit route dispatcher and initially preserve the existing action path where needed for compatibility.
5. Move structured JSON, reflection, and dialogue behavior onto route-specific prompts and outputs.
6. Refactor action route wiring toward executor-first composability: planner for complex/retry cases, reflection through the reflection route when world-owned policy says it is due.
7. Update TownWorld contexts to request the appropriate routes directly.
8. Remove temporary direct-mode flags after tests cover the new route contract.

## Resolved Discussion Decisions

- `route` is a first-class `AgentContext` field.
- The initial route set is `action`, `dialogue`, `structured_json`, and `reflection`.
- Dialogue route does not allow `use_skill` in the first version.
- Reflection route does not use memory tools; the world engine supplies evidence.
- Structured JSON malformed-output handling belongs to the world engine.
- Non-action routes may initially use a route dispatcher instead of full LangGraph branches.
- Action route planner is micro planning only; macro planning remains world-owned and should use structured JSON when model-drafted output is needed.
- Action route should evolve from mandatory `Planner -> Executor -> Reflector` to composable node selection with executor as the core world-action node.
- Durable reflection should be triggered through the reflection route by world-engine policy instead of being an unavoidable action-route tail.
- Route tool policy is allowlist-based.
- `disabled_tools` is retained only as a narrowing mechanism after route policy.
- Route execution is observable through `AgentResponse.route` and optional debug metadata.
