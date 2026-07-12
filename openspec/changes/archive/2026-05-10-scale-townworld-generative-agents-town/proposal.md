## Why

TownWorldEngine has reached the point where the core Generative Agents-style
semantic runtime exists, but current validation still uses small scenarios with
2-3 active residents. The next risk is scale: whether schedules, local
perception, conversations, memory, reflection, replay, and resume remain stable
when the town approaches the size and social density of GenerativeAgentsCN.

## What Changes

- Add a larger project-owned semantic town scenario inspired by the
  GenerativeAgentsCN town scale, with a target of at least 25 residents and a
  district-level location graph covering homes, workplaces, public venues, and
  social gathering places.
- Define resident personas, relationships, occupations, home/sleep locations,
  memory seeds, and schedule seeds using ANNIE's scenario schema rather than
  importing GenerativeAgentsCN runtime objects.
- Extend deterministic town validation to run larger resident cohorts without
  live LLM credentials.
- Extend opt-in real-LLM validation to support scalable cohorts with explicit
  cost controls and quality diagnostics.
- Add scale-oriented diagnostics for schedule completion, failed action rates,
  loop guards, conversation density, reflection/day-summary evidence, memory
  seed coverage, and replay explainability.
- Preserve the current semantic TownWorld architecture. This change does not
  introduce tile rendering or make tile coordinates authoritative.

## Capabilities

### New Capabilities
- `town-generative-scale-content`: Defines requirements for a large
  GenerativeAgentsCN-inspired semantic town scenario, including resident count,
  location coverage, social graph coverage, and scenario loading expectations.

### Modified Capabilities
- `town-world-simulation`: Adds requirements for scaled semantic-town runtime
  behavior with larger resident cohorts and district-level locations.
- `town-full-day-validation`: Adds requirements for deterministic and opt-in
  real-LLM scale validation of larger TownWorld runs.

## Impact

- Scenario content under `src/annie/town/content/scenarios/`.
- Scenario loading and validation in `src/annie/town/content/scenario.py`.
- Town runtime and diagnostics in `src/annie/town/runtime/`.
- Town replay/read-model output if additional scale diagnostics are surfaced.
- Deterministic tests under `tests/test_town/`.
- Opt-in real-LLM validation scripts under `scripts/`.
- No intended changes to `src/annie/npc/` architecture or persistent NPC state.
