## Why

The refactor boundary still leaked business ownership into `src/annie/npc/`: NPC profile/YAML loading, direct memory writes, cross-run todo tooling, and run-local tool state were all coupled to the agent layer. This change tightens the two-layer architecture so the NPC layer remains a stateless AI capability framework and World Engine owns persistence, profile parsing, todo policy, and action arbitration.

## What Changes

- **BREAKING**: Remove `NPCProfile` and `load_npc_profile` from `annie.npc.state`; profile schema, YAML loading, and prompt rendering move to `annie.world_engine.profile`.
- **BREAKING**: Move `plan_todo` out of NPC built-ins and into World Engine tooling; `DefaultWorldEngine.build_context()` injects it explicitly.
- Change Reflector to return `reflection` plus `MemoryUpdate` declarations instead of writing through `MemoryInterface`.
- Change `memory_store` into a declarative memory-update built-in and add `declare_action` for `ActionRequest` output.
- Add `AgentContext.todo` so the World Engine pre-renders todo prompt text instead of NPC querying todo memory.
- Keep NPC run-local tool state in internal runtime storage rather than mutating `AgentContext.extra`.
- Update concrete engines and tests to import profiles from World Engine and persist `AgentResponse.memory_updates` in `handle_response()`.

## Capabilities

### New Capabilities
- `strict-npc-world-boundary`: Captures the stricter ownership rules for profile loading, todo tools, memory-update declarations, action declarations, and run-local agent state.

### Modified Capabilities
- `agent-interface`: `AgentContext` gains todo prompt text and `AgentResponse.memory_updates` becomes the default reflection output path.
- `npc-agent`: NPC layer removes profile/YAML ownership and direct Reflector persistence.
- `tool-skill-system`: built-ins no longer include `plan_todo`; `memory_store` and `declare_action` are declarative.
- `world-engine`: World Engine owns profiles, todo tools, and memory persistence from response updates.

## Impact

- Affected code: `src/annie/npc/`, `src/annie/world_engine/`, `src/annie/war_game/`.
- API impact: profile imports move to `annie.world_engine.profile`; callers should use `DefaultWorldEngine.register_profile()` with World Engine profile types.
- Persistence impact: memory updates from Reflector and `memory_store` persist only after a World Engine accepts them in `handle_response()`.
- Test impact: integration tests assert the new declarative memory path and explicit World Engine todo injection.
