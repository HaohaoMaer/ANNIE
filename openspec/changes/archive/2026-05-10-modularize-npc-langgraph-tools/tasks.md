## 1. Baseline and Contracts

- [x] 1.1 Inspect current NPC graph registry, route dispatch, graph builders, executor/planner/reflector nodes, and `AgentResponse` fields.
- [x] 1.2 Inspect current world-engine tool interfaces and action arbitration paths to identify direct execution versus declarative intent handling.
- [x] 1.3 Define the minimal tool execution status type with status enum, tool name, call ID, message, optional payload, retry hint, and world-state-change flag.

## 2. NPC Node Composition

- [x] 2.1 Introduce shared per-run graph state helpers derived from `AgentContext`.
- [x] 2.2 Extract or wrap existing planner behavior as a generic `planning` node.
- [x] 2.3 Extract or wrap existing executor/tool-use behavior as a generic `action` node.
- [x] 2.4 Extract dialogue, structured JSON, reflection, and action response projection into generic `output` nodes.
- [x] 2.5 Add bounded node-path/debug metadata collection without exposing prompts, memory contents, or full LangGraph traces.

## 3. Graph Registry and Routing

- [x] 3.1 Extend graph registry entries with route/policy kind, response kind, and node composition labels.
- [x] 3.2 Convert default action graph to compose planning/action/output nodes through LangGraph.
- [x] 3.3 Convert dialogue graph to compose memory/tool-loop and output nodes while forbidding world mutation tools.
- [x] 3.4 Convert structured JSON graph to use output-only node composition with no tools.
- [x] 3.5 Convert reflection graph to use evidence/reflection/output nodes with no world-action execution.
- [x] 3.6 Preserve `graph_id` precedence, route compatibility mappings, and legacy direct-mode compatibility mappings.

## 4. World Tool Execution Status

- [x] 4.1 Update world-engine injected tool wrappers to return the structured execution status.
- [x] 4.2 Update action graph response projection so `AgentResponse` surfaces tool statuses instead of declarative action intents.
- [x] 4.3 Remove or quarantine declarative intent-as-execution arbitration from default world-engine handling.
- [x] 4.4 Ensure `success`, `failure`, `running`, `rejected`, and `invalid` statuses can be passed into later `AgentContext.input_event` or history as bounded summaries.

## 5. Tests and Validation

- [x] 5.1 Add NPC-layer tests for graph registry composition metadata, policy validation, and unknown graph rejection.
- [x] 5.2 Add route compatibility tests proving route/direct-mode inputs resolve to node-composed graph IDs.
- [x] 5.3 Add action graph tests proving world tools are exposed only through action policy and tool statuses appear in `AgentResponse`.
- [x] 5.4 Add non-action graph tests proving dialogue/structured/reflection graphs do not bind world mutation tools.
- [x] 5.5 Add world-engine tests proving legal, illegal, long-running, and invalid tool calls return explicit statuses and do not use declarative intent execution.
- [x] 5.6 Run targeted tests for NPC graph/routing and world-engine action handling.
- [x] 5.7 Run `openspec validate modularize-npc-langgraph-tools --strict`.
