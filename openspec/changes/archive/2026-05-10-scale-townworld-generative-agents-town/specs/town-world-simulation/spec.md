## ADDED Requirements

### Requirement: Town engine runs generative-scale semantic cohorts
The town engine SHALL support bounded semantic runs with a larger resident
cohort without moving durable town state into the NPC layer.

#### Scenario: Engine builds contexts for scaled residents
- **WHEN** the runtime advances a scaled scenario with at least 25 residents
- **THEN** `TownWorldEngine` can build bounded `AgentContext` values for active
  residents using local perception, current schedule state, relationship cues,
  recent history, memory evidence, and available town tools
- **AND** `NPCAgent` remains stateless across resident activations

#### Scenario: Engine skips inactive scaled residents
- **WHEN** a scaled scenario contains residents with no visible event, no
  pending inbox event, no active action completion, and no active schedule
  transition for the current tick
- **THEN** the engine records a world-owned skip reason rather than forcing an
  LLM activation for that resident

### Requirement: Town engine reports scale behavior diagnostics
The town engine SHALL expose diagnostics that make scaled semantic-town behavior
inspectable and comparable across runs.

#### Scenario: Diagnostics summarize scaled action quality
- **WHEN** a scaled TownWorld run completes or stops at a configured bound
- **THEN** diagnostics include action counts by resident and type, failed action
  counts by reason, current-action lifecycle counts, schedule completion counts,
  inferred completion counts, unfinished schedule counts, and loop guard counts

#### Scenario: Diagnostics summarize scaled social behavior
- **WHEN** a scaled TownWorld run includes conversations or social attempts
- **THEN** diagnostics include conversation session counts, cooldown or blocked
  conversation evidence, relationship cue availability, and conversation-derived
  planning or memory evidence when present

### Requirement: Scaled replay remains explainable
The town engine SHALL write replay artifacts for scaled runs that can explain
resident behavior without requiring a live debugger.

#### Scenario: Checkpoints include scaled resident summaries
- **WHEN** a scaled run writes replay checkpoints
- **THEN** checkpoints include the simulated time, active and skipped resident
  ids, next available minutes, resident location summaries, current schedule
  state, current action state, conversation sessions, reflection events, and
  loop guard events

#### Scenario: Replay can inspect representative residents
- **WHEN** a scaled run contains more residents than can be displayed compactly
- **THEN** replay or diagnostics preserve enough per-resident detail to inspect
  any selected resident's location, schedule progress, action outcomes, and
  memory/reflection evidence

### Requirement: Scaled runtime preserves resume behavior
The town runtime SHALL continue to persist and resume authoritative state for
scaled semantic-town runs.

#### Scenario: Scaled run snapshot resumes
- **WHEN** a scaled run writes a manifest-backed runtime snapshot and then
  resumes from that manifest
- **THEN** the resumed engine restores clock state, residents, schedules,
  current actions, event delivery state, loop guards, replay cursor metadata,
  memory backend references, and history backend references
- **AND** continuing the run does not require retaining the previous `NPCAgent`
  instance
