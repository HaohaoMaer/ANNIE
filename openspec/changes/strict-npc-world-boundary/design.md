## Context

The intended architecture is a strict two-layer split:

- NPC Agent layer: stateless planning, tool-use execution, reflection parsing, and declarative outputs.
- World Engine layer: state, profile/YAML parsing, tools with business persistence, todo policy, memory writes, and action arbitration.

The implementation still had four coupling points: `npc.state` loaded YAML profiles, Reflector wrote memory directly, `plan_todo` was an NPC built-in, and tool runtime state was stored under private keys in `AgentContext.extra`.

## Decisions

### Profile Ownership

Move `NPCProfile`, related nested models, `load_npc_profile()`, and profile-to-prompt rendering into `annie.world_engine.profile`. `npc.state` keeps only runtime state (`Task`, `TaskStatus`, `AgentState`).

### Declarative Memory

Reflector parses its LLM response into:

- `reflection` text
- `MemoryUpdate(type="reflection")` for the event reflection
- `MemoryUpdate(type="semantic")` for parsed facts
- `MemoryUpdate(type="reflection", metadata={"person": ...})` for relationship notes

The World Engine decides whether and how to persist those updates. `DefaultWorldEngine` and `WarGameEngine` accept the default updates and call `memory.remember()`.

### Tool Boundary

NPC built-ins remain generic:

- `memory_recall`
- `memory_grep`
- `memory_store` as declaration only
- `inner_monologue`
- `use_skill`
- `declare_action`

`plan_todo` moves to `annie.world_engine.tools` and is injected by `DefaultWorldEngine`. Other engines can inject their own todo tool or omit todo support.

### Todo Prompt Rendering

`AgentContext.todo` carries pre-rendered todo text. Executor always renders `<todo>`, but it does not query memory to build the section.

### Run-Local Internal State

Introduce `ToolContext.runtime`, owned by `NPCAgent.run()`, for skill activation, message access, frame tracking, recall dedup, inner thoughts, memory-update declarations, and action declarations. `AgentContext.extra` remains available for World Engine metadata and injected tool needs.

## Risks

- Existing callers importing profile models from `annie.npc.state` must migrate.
- Existing tests expecting memory writes during `NPCAgent.run()` must call `WorldEngine.handle_response()`.
- Skill manifest loading still exists for `NPCAgent(skills_dir=...)`; it is generic capability loading, not NPC profile/YAML loading.

## Migration

- Replace `from annie.npc.state import NPCProfile, load_npc_profile` with `from annie.world_engine.profile import NPCProfile, load_npc_profile`.
- Use `AgentResponse.memory_updates` for memory write intents and persist them in engine `handle_response()`.
- Inject `PlanTodoTool()` from the engine when cross-run todo support is desired.
