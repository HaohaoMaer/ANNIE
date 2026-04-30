## Why

The current `NPCAgent.run()` path treats every request as `Planner -> Executor -> Reflector`, which is too rigid for cognition-only and structured-output tasks. This causes extra LLM calls, tool exposure mismatches, and prompt leakage risks when world engines need specialized behaviors such as resident planning, managed dialogue turns, or distilled reflection.

## What Changes

- Introduce explicit NPC execution routes so different request types can use different graph paths instead of the single fixed pipeline.
- Clarify the distinction between world-owned macro planning and action-route micro planning:
  - macro planning, such as TownWorld daily schedules and dynamic schedule revisions, remains world-engine state and may use the structured JSON route to generate candidate plans;
  - action-route planner behavior is only optional, run-local task decomposition for complex execution attempts.
- Add route-specific tool policies:
  - world action routes may use world action tools plus memory tools;
  - managed dialogue routes may use memory/inner-thought tools but must not execute world actions;
  - structured JSON routes should use no tools;
  - reflection routes should avoid world actions and system metadata leakage.
- Replace ad-hoc direct-mode shortcuts with graph-level route selection and typed/validated route contracts.
- Make the action route composable so executor, planner, and reflector can be invoked independently by route policy instead of treating `Planner -> Executor -> Reflector` as the permanent mandatory action pipeline.
- Adjust prompt policy expectations:
  - schedules remain the default anchor;
  - urgent events, direct requests, or clearly valuable opportunities may briefly override the schedule when time budget allows;
  - tool failure may justify checking the environment before retrying.
- Preserve the NPC/world-engine boundary: the world engine chooses route intent and owns business-specific state, while the NPC layer remains business-agnostic.

## Capabilities

### New Capabilities
- `npc-agent-routing`: Defines route-aware NPC execution, route-specific tool availability, and output contracts for action, dialogue, structured JSON, and reflection requests.

### Modified Capabilities
- `world-engine`: World engines may request an NPC execution route and must provide route-appropriate context without moving business logic into the NPC layer.

## Impact

- Affected code: `src/annie/npc/agent.py`, NPC graph/node wiring, prompt builders, tool registry filtering, and NPC response construction.
- Affected integrations: `src/annie/town/engine.py` and any world engine contexts that currently rely on ad-hoc `extra` flags or the default full agent pipeline.
- Tests: NPC prompt/graph tests, town managed dialogue/planning/reflection tests, and integration tests covering the decoupled NPC/world-engine contract.
