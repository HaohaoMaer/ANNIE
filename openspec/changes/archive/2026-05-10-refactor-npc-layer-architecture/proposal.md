## Why

The NPC Agent layer already has a clear architectural contract, but the code shape makes the execution model hard to read: graph selection, run setup, tool dispatch, skill activation, prompt assembly, and output projection are spread across `agent.py`, `executor.py`, runtime helpers, and node wrappers. This makes it difficult to see the intended flow and increases the risk that future changes accidentally move world-engine business logic back into the NPC layer.

This change reorganizes the NPC layer around its core idea: a stateless, business-agnostic cognitive runtime that receives all per-run data through `AgentContext`, executes one registered generic graph, and returns an `AgentResponse` without owning world state or persistence.

## What Changes

- Refactor NPC layer internals so the public execution flow is readable from graph selection through response projection.
- Separate run orchestration from graph compilation, graph policy/runtime setup, node implementations, and output projection.
- Make the action route implementation easier to follow by isolating planner selection, executor setup, retry routing, and response construction.
- Preserve existing public contracts: `NPCAgent(llm, skills_dir=None)`, `NPCAgent.run(context)`, `AgentContext`, `AgentResponse`, `ToolDef`, `SkillDef`, `MemoryInterface`, registered graph IDs, route behavior, and debug metadata.
- Preserve the architecture invariant that the NPC layer must not own world state, parse NPC YAML, import `chromadb`, or contain world-engine business vocabulary.
- Keep behavior-compatible tests as the migration guardrail before any deeper behavioral changes.
- No breaking API change is intended.

## Capabilities

### New Capabilities

- `npc-layer-architecture`: Internal organization requirements for keeping the NPC Agent layer readable as a stateless, business-agnostic graph runtime.

### Modified Capabilities

- None. This is an implementation refactor of existing NPC Agent capabilities; it should not change spec-level behavior.

## Impact

- Affected code:
  - `src/annie/npc/agent.py`
  - `src/annie/npc/nodes.py`
  - `src/annie/npc/executor.py`
  - `src/annie/npc/runtime/`
  - `src/annie/npc/graph_registry.py`
  - `src/annie/npc/prompts.py`
  - focused NPC tests under `tests/test_npc/`
- Public API impact:
  - No intended public API change.
  - Existing graph IDs, route mappings, tool policy behavior, and response fields remain stable.
- Dependencies:
  - No new runtime dependency is expected.
- Verification:
  - `pytest tests/test_npc`
  - `pytest tests/test_integration/test_decoupled_flow.py`
  - `pytest tests/test_integration/test_cross_run_todo.py`
  - `ruff check src/annie/npc`
