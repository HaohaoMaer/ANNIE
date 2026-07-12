## Why

The scaled 25-resident real-LLM TownWorld run exposed a mismatch between reasonable NPC intent and executable world affordances. NPCs often tried to deliver pastries, prepare stalls, file notes, inspect equipment, or rest, but the town layer either lacked the target affordance or rejected casing and natural-language variants.

## What Changes

- Expand scaled town semantic affordances for high-frequency work, home, delivery, review, and inspection objects.
- Make town affordance execution case-insensitive for ids and aliases while preserving strict target visibility checks.
- Return actionable `suggested_affordances` on unsupported object interactions.
- Add a read-only town tool for need-driven affordance target lookup.
- Broaden schedule completion inference using completion tags, affordance ids, aliases, target ids, notes, event types, wait/rest evidence, and short inserted conversation segments.
- Extend scaled diagnostics so quality reports expose top failed targets, intents, suggestion misses, and rest/lifecycle failures.

## Capabilities

### New Capabilities
- `town-affordance-alignment`: Need-driven affordance lookup, matching, suggestions, and completion inference for semantic TownWorld actions.

### Modified Capabilities
- `town-world-simulation`: TownWorld locations, objects, tools, and schedule completion must expose executable semantic affordances aligned with resident schedules.
- `town-full-day-validation`: Full-day validation diagnostics must summarize affordance and rest/lifecycle failure patterns for scaled runs.

## Impact

- Affected code: `src/annie/town/`, scaled town scenario YAML, town runtime diagnostics, town tests.
- Public behavior: new town tool `find_affordance_targets(query, location_id?)`; optional `ScheduleSegment.completion_tags`; richer failed-action facts.
- No NPC-layer architecture changes and no new dependencies.
