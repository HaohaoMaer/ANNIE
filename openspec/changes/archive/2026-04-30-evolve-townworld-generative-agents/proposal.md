## Why

TownWorld has validated a small semantic multi-NPC loop, but it still stops short
of the richer Generative Agents pattern: daily planning, bounded perception,
spatial memory, reflection, relationship-aware conversation, and replayable town
life over longer runs. Using `GenerativeAgentsCN` as a reference gives us a
concrete next target: TownWorld should align behaviorally with Stanford-style
Generative Agents while preserving ANNIE's separate stateless NPC capability
layer.

## What Changes

- Evolve `TownWorldEngine` from a small smoke simulation into a Generative
  Agents style town runtime with persistent per-NPC resident state: daily
  schedules, planning scratch, spatial memory, current action, reflection
  counters, relationship cues, conversations, and replay snapshots.
- Keep the Stanford-style resident simulation state in `src/annie/town/` and
  `src/annie/world_engine/`, while using `NPCAgent` only as the stateless
  cognitive backend for planning, action selection, conversation, and reflection.
- Extend town context rendering so NPCs receive bounded local perception,
  current activity goals, relevant relationships, recent interactions, and
  schedule/reflection prompts through `AgentContext`.
- Add deterministic fixtures and tests before scaling to live LLM runs.
- Treat `GenerativeAgentsCN` as the behavioral and lifecycle reference, not as
  code to copy directly into the NPC framework.

## Capabilities

### New Capabilities

### Modified Capabilities

- `town-world-simulation`: expand requirements from the current semantic smoke
  milestone toward a Stanford-style Generative Agents town loop, including
  persistent resident state, NPC-generated daily planning, spatial perception,
  relationship-aware interaction, reflection, and richer replay/checkpoint
  output.

## Impact

- Affected code: `src/annie/town/`, `src/annie/world_engine/`, town scripts,
  town tests, and replay documentation.
- Affected data/contracts: town resident models, town fixtures, schedule models,
  replay event schema, and memory metadata conventions.
- Non-goals: importing legacy `cognitive` modules, moving durable town
  simulation state into `src/annie/npc/`, or adopting
  `GenerativeAgentsCN`'s monolithic agent object.
