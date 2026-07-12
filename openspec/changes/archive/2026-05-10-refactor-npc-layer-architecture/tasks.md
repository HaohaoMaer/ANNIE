## 1. Characterization

- [x] 1.1 Run the current focused NPC test suite to capture the baseline failure/pass state before refactoring.
- [x] 1.2 Review existing tests for route selection, graph debug metadata, tool policy, executor retry, skill frame cleanup, recall dedup, and response projection.
- [x] 1.3 Add small characterization tests only where an existing behavior required by this change is not already covered.

## 2. Runtime Boundary

- [x] 2.1 Introduce a NPC-owned runtime construction helper that centrally initializes the current runtime keys without changing the mutable mapping passed to tools.
- [x] 2.2 Update action and dialogue runner setup to use the runtime helper while preserving existing runtime key names and values.
- [x] 2.3 Keep skill activation frame ownership and cleanup visible in the executor loop, with tests confirming frames do not leak across tasks.

## 3. Agent Facade And Graph Runners

- [x] 3.1 Extract graph resolution helpers from `agent.py` into a focused NPC-owned module or section with no behavior change.
- [x] 3.2 Move action graph compilation and retry routing into an action graph builder while preserving node labels and graph debug metadata.
- [x] 3.3 Move dialogue, structured JSON, and reflection graph compilation into route-specific graph builders while preserving tool policies and response fields.
- [x] 3.4 Reduce `NPCAgent.run()` and runner dispatch so the high-level flow is graph resolution, runtime/setup, graph invocation, and response projection.

## 4. Response Projection

- [x] 4.1 Extract action `AgentResponse` projection into a focused helper that preserves dialogue, inner thoughts, memory updates, tool statuses, graph ID, route, bound tools, and node path.
- [x] 4.2 Extract dialogue, structured JSON, and reflection response projection into focused helpers with route-specific fields unchanged.
- [x] 4.3 Confirm response projection does not perform world arbitration, persistence, schema validation, or scene progression.

## 5. Executor Readability

- [x] 5.1 Refactor `Executor.__call__` into named internal steps for task execution, loop invocation, task outcome classification, and prior-result rendering.
- [x] 5.2 Preserve the tool-use loop semantics: context budget check, dynamic tool binding each iteration, dispatch through `ToolDispatcher`, micro-compressed tool messages, max-loop failure, and productive-effect handling.
- [x] 5.3 Preserve skip-task behavior so default action graphs can execute directly from `input_event` without redundant task text.

## 6. Architecture Guardrails

- [x] 6.1 Check that `src/annie/npc/` still does not import `chromadb` or world-engine concrete modules.
- [x] 6.2 Check that new NPC-layer module names and helper names remain business-agnostic.
- [x] 6.3 Leave legacy direct-mode compatibility behavior unchanged unless a separate migration change is created.

## 7. Verification

- [x] 7.1 Run `pytest tests/test_npc`.
- [x] 7.2 Run `pytest tests/test_integration/test_decoupled_flow.py`.
- [x] 7.3 Run `pytest tests/test_integration/test_cross_run_todo.py`.
- [x] 7.4 Run `ruff check src/annie/npc`.
- [x] 7.5 Summarize any remaining test gaps or known behavior-preserving limitations.
