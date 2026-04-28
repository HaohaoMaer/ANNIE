## 1. Spec and Boundary

- [x] Create OpenSpec change for strict NPC/World Engine boundary.
- [x] Document profile ownership, todo ownership, memory-update declarations, and action declarations.

## 2. NPC Layer

- [x] Remove NPC profile/YAML types and loader from `src/annie/npc/state.py`.
- [x] Add `AgentContext.todo`.
- [x] Change Reflector to return `MemoryUpdate` declarations instead of writing memory.
- [x] Change `memory_store` to declare memory updates.
- [x] Add `declare_action` built-in and aggregate actions into `AgentResponse.actions`.
- [x] Move run-local tool state out of `AgentContext.extra` and into `ToolContext.runtime`.
- [x] Ensure `src/annie/npc` has no AST-level imports of `yaml`, `chromadb`, or `annie.world_engine`.

## 3. World Engine Layer

- [x] Add `annie.world_engine.profile` with profile models, YAML loader, and prompt rendering.
- [x] Add `annie.world_engine.tools.PlanTodoTool`.
- [x] Inject todo text and todo tool from `DefaultWorldEngine.build_context()`.
- [x] Persist `AgentResponse.memory_updates` in `DefaultWorldEngine.handle_response()`.
- [x] Update WarGame profile loading and memory-update handling.

## 4. Tests

- [x] Update integration tests for declarative memory persistence.
- [x] Move profile tests to World Engine coverage.
- [x] Update todo tests to import `PlanTodoTool` from World Engine.
- [x] Verify focused NPC/default-engine tests.
- [x] Verify war game tests.
- [x] Run lint on refactored packages.
