## 1. Route Contract

- [x] 1.1 Define `AgentRoute` as a public enum with `action`, `dialogue`, `structured_json`, and `reflection`.
- [x] 1.2 Add first-class `AgentContext.route` with default `action`.
- [x] 1.3 Add route-aware `AgentResponse` fields: `route`, `structured_output`, and optional bounded `debug` metadata.
- [x] 1.4 Document each route's expected input context, allowed tools, and response fields.
- [x] 1.5 Add tests that default contexts still use the action route.
- [x] 1.6 Add temporary compatibility mapping from legacy `extra["npc_direct_mode"]` values to the new route contract.

## 2. Route Dispatch

- [x] 2.1 Add explicit route dispatch in `NPCAgent.run()`.
- [x] 2.2 Preserve action-route world tool execution while introducing an action node policy that can select executor, planner, and reflector independently.
- [x] 2.3 Ensure non-action routes do not run unrelated planner, action executor, or action reflector nodes.
- [x] 2.4 Add a structured JSON path that runs a single structured-output prompt with no tools and fills `structured_output`.
- [x] 2.5 Add a reflection path that uses explicit world-provided evidence, avoids all tools, and fills `reflection`.
- [x] 2.6 Add a dialogue path that can use memory/inner-thought tools but cannot execute world actions.
- [x] 2.7 Give dialogue route its own small tool-loop limit separate from action executor limits.
- [x] 2.8 Add tests for simple action turns that do not require planner output before executor.
- [x] 2.9 Add tests for action retry or complex action hints that can invoke planner as run-local micro planning.
- [x] 2.10 Ensure action route does not run durable reflection by default when the world engine has not requested reflection.

## 3. Tool Policy

- [x] 3.1 Implement allowlist-based route-specific tool filtering before tools are bound to the LLM.
- [x] 3.2 Ensure dialogue route exposes memory recall, literal grep, and inner monologue.
- [x] 3.3 Ensure dialogue route does not expose `use_skill` in the initial version.
- [x] 3.4 Ensure structured JSON route exposes no tools.
- [x] 3.5 Ensure reflection route exposes no tools and does not perform implicit pre-run memory recall.
- [x] 3.6 Preserve `disabled_tools` as a second narrowing step that cannot grant route-forbidden tools.
- [x] 3.7 Add route metadata to world-injected tools, such as `allowed_routes` or `tool_kind`, with action-only as the default for unmarked injected tools.
- [x] 3.8 Add tests that forbidden tools are neither bound nor dispatchable for each route.

## 4. Prompt And Output Contracts

- [x] 4.1 Split route prompts so action, dialogue, structured JSON, and reflection do not share inappropriate instructions.
- [x] 4.2 Add dialogue output parsing that returns only utterance text.
- [x] 4.3 Add structured JSON output handling that returns raw structured-output text and leaves parsing, repair, retry, fallback, and schema validation to the world engine.
- [x] 4.4 Add reflection prompt constraints and post-processing or rejection for internal orchestration terms.
- [x] 4.5 Ensure route output fields follow the decided contract: action uses existing fields, dialogue uses `dialogue`, structured JSON uses `structured_output`, and reflection uses `reflection`.
- [x] 4.6 Add regression tests for system/tool metadata not leaking into persisted impressions or reflections.

## 5. World Engine Integration

- [x] 5.1 Update TownWorld resident planning to request the structured JSON route.
- [x] 5.2 Update TownWorld managed conversation turns to request the dialogue route with memory tools.
- [x] 5.3 Update TownWorld reflection to request the reflection route.
- [x] 5.4 Replace temporary ad-hoc direct-mode flags with the finalized route contract.
- [x] 5.5 Adjust schedule prompt policy to use the default-anchor wording with allowed high-priority detours.
- [x] 5.6 Preserve the rule that tool failure can justify environment confirmation through observe.
- [x] 5.7 Ensure TownWorld parses and validates structured JSON route output through world-owned schema logic.
- [x] 5.8 Ensure TownWorld supplies explicit reflection evidence/context instead of relying on reflection-route memory tools.
- [x] 5.9 Document and test that TownWorld schedule generation and revision are macro planning owned by the world engine, not NPC action planner output.
- [x] 5.10 Ensure accepted schedules, revisions, progress, and completion remain persisted in TownWorld state rather than NPC-layer runtime state.

## 6. Verification

- [x] 6.1 Run NPC prompt, executor, and graph routing tests.
- [x] 6.2 Run TownWorld state and multi-NPC tests.
- [ ] 6.3 Run the real-LLM TownWorld validation script and inspect verbose output for route/tool behavior.
- [x] 6.4 Run lint/type checks for `src/annie/npc` and affected world-engine modules.
- [x] 6.5 Validate the OpenSpec change with `openspec validate optimize-npc-agent-routing --strict`.
