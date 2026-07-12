## ADDED Requirements

### Requirement: Deterministic generative-scale validation
The town project SHALL provide deterministic validation for the scaled semantic
town scenario without requiring live LLM credentials.

#### Scenario: Deterministic scaled scenario preflight passes
- **WHEN** deterministic town validation loads the scaled scenario
- **THEN** it verifies resident count, location count, relationship references,
  memory seed coverage, schedule seed validity, route reachability, and scenario
  schema validity

#### Scenario: Deterministic scaled runtime window passes
- **WHEN** deterministic town validation runs a representative scaled cohort
  across at least one bounded day window
- **THEN** it produces replay, diagnostics, and snapshot artifacts
- **AND** it asserts no runtime crash, no unreported invalid routes, bounded
  failed action rates, bounded loop guard counts, and inspectable schedule
  progress

### Requirement: Opt-in real-LLM generative-scale validation
The town project SHALL provide opt-in real-LLM validation for scaled semantic
TownWorld runs with explicit cost and runtime controls.

#### Scenario: Real-LLM scaled validation supports cohort controls
- **WHEN** the real-LLM scaled validation script is invoked
- **THEN** the caller can select resident ids or resident count, day count,
  start minute, end minute, max ticks, model config path, temperature, retries,
  output directory, and prompt preview length

#### Scenario: Real-LLM scaled validation writes quality summary
- **WHEN** the real-LLM scaled validation run completes or stops at its bound
- **THEN** it writes terminal output, summary JSON, validation JSON, replay
  artifacts, manifest, latest snapshot, diagnostics, LLM call count, action
  counts, failed action reasons, schedule completion metrics, loop guard
  metrics, conversation metrics, reflection/day-summary metrics, and final
  resident states

### Requirement: Scaled validation distinguishes behavior quality from failure
Scaled validation SHALL distinguish runtime failure from completed runs that
contain behavior-quality warnings.

#### Scenario: Completed scaled run can report warnings
- **WHEN** a scaled run completes but has unfinished schedules, excessive skips,
  repeated failed actions, loop guards, missing memory seed coverage, or weak
  conversation/reflection evidence
- **THEN** validation reports those as inspectable warnings
- **AND** it does not label them as runner crashes unless execution or artifact
  generation failed

#### Scenario: Scaled validation links artifacts for inspection
- **WHEN** scaled validation writes artifacts
- **THEN** the summary and diagnostics include paths to replay, checkpoint,
  reflection, manifest, latest snapshot, history, vector store, and viewer/read
  model artifacts when available
