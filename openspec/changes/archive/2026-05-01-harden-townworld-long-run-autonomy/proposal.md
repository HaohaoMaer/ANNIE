## Why

TownWorld has now validated real-LLM multi-NPC behavior for a richer one-day
Generative Agents style loop. The next problem is durability: the town should
run across multiple simulated days without obvious loops or drift, while each
resident's behavior remains explainable from schedule, place, relationships,
memory, and replay evidence.

## What Changes

- Extend `TownWorldEngine` into a long-running semantic social simulation core
  that supports multi-day resident lifecycles without introducing a visual or
  tile-backed map in this phase.
- Replace fixture-like daily schedule usage with a GenerativeAgentsCN-inspired
  schedule lifecycle: memory-backed `currently` update, wake-up planning,
  coarse daily plan generation, hourly/segment schedule generation, current
  segment decomposition, and event-driven schedule revision.
- Expand semantic town content with more locations, objects, affordances, and
  town tools while keeping all durable town state in `TownWorldEngine` and
  `TownResidentState`.
- Make conversations and reflections affect later planning through distilled
  memory, relationship summaries, unresolved topics, and next-day planning
  context.
- Add long-run observability and quality checks: replay should explain why NPCs
  acted, what schedule/memory/relationship evidence was used, when loops were
  avoided, and how daily plans changed over time.
- Add deterministic and opt-in real-LLM validation for multi-day runs, including
  no-crash, no-obvious-loop, schedule adherence, conversation/reflection
  influence, and replay explainability checks.

## Capabilities

### New Capabilities

### Modified Capabilities

- `town-world-simulation`: expand requirements from a one-day semantic
  Generative Agents milestone to a long-running multi-day social simulation
  kernel with daily planning lifecycle, richer semantic affordances,
  memory-influenced planning, loop guards, and explainable replay.

## Impact

- Affected code: `src/annie/town/`, town runtime scripts, deterministic fixtures,
  town tests, and replay documentation.
- Affected contracts: resident state shape, schedule generation/revision schema,
  semantic location/object affordance metadata, relationship summary metadata,
  replay event/checkpoint schema, and validation output.
- Non-goals: visual map, tile-backed pathfinding, frontend replay UI, copying
  `GenerativeAgentsCN`'s monolithic `Agent`, or moving durable town state into
  `src/annie/npc/`.
