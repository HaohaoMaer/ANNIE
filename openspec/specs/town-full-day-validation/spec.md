# town-full-day-validation Specification

## Purpose
TBD - created by archiving change enable-townworld-full-day-lifecycle-validation. Update Purpose after archive.
## Requirements
### Requirement: Full-day real-LLM validation script
The system SHALL provide an opt-in real-LLM validation script that runs multiple TownWorld residents across multiple full simulated days and writes inspectable validation artifacts.

#### Scenario: Script runs multi-day full-day validation
- **WHEN** the full-day validation script is executed with configured NPC ids, day count, and model configuration
- **THEN** it runs real `NPCAgent` planning and action ticks for the requested residents
- **AND** it can cover a full-day window from `00:00` through `24:00`

#### Scenario: Script writes replay and summary artifacts
- **WHEN** the full-day validation script completes or fails
- **THEN** it writes terminal output, replay artifacts, manifest or latest state where available, and a machine-readable summary
- **AND** the summary includes run configuration, LLM call count, action counts, schedule completion counts, inferred completion counts, lifecycle anomaly counts, loop guard counts, and final resident states

#### Scenario: Script exposes cost controls
- **WHEN** the full-day validation script is invoked
- **THEN** the caller can configure days, NPC ids, start minute, end minute, max ticks per day, model config, temperature, retries, output directory, and prompt preview length
- **AND** defaults are conservative enough for opt-in local validation

### Requirement: Full-day validation reports lifecycle quality
The full-day validation SHALL report whether the simulated residents behaved consistently with home, wake-up, and sleep lifecycle expectations.

#### Scenario: Lifecycle anomalies are visible
- **WHEN** a resident begins a day away from home or sleep state, omits sleep, fails to return home before sleep, or ends the day in an unexpected public location
- **THEN** the validation summary reports the anomaly with resident id, day, location, and reason

#### Scenario: Validation distinguishes known defects from runner failure
- **WHEN** the script completes but lifecycle anomalies or unfinished schedules remain
- **THEN** the summary distinguishes engine/runtime failure from behavioral diagnostics
- **AND** terminal output gives enough artifact paths to inspect the run

### Requirement: Full-day validation supports deterministic preflight tests
The system SHALL include deterministic tests that validate full-day lifecycle behavior before relying on opt-in real-LLM runs.

#### Scenario: Deterministic tests cover lifecycle contracts
- **WHEN** deterministic town tests are run
- **THEN** they cover resident home/sleep metadata loading, wake-up planning state, overnight settlement, full-day schedule validation, and action-derived schedule completion

#### Scenario: Real-LLM script is not the only correctness gate
- **WHEN** CI or local non-LLM validation runs
- **THEN** the full-day lifecycle contracts can be checked without requiring live LLM credentials

### Requirement: Full-day validation produces watchable replay evidence
Full-day TownWorld validation SHALL prove that lifecycle behavior is visible in replay/viewer artifacts, not only counted in validation summaries.

#### Scenario: Validation checks read model lifecycle visibility
- **WHEN** deterministic full-day validation generates a replay read model
- **THEN** validation confirms that day start, wake or sleep lifecycle state, resident planning, schedule execution, day summary, and lifecycle anomalies when present are represented in viewer-readable events or frames

#### Scenario: Validation checks final resident state visibility
- **WHEN** a full-day validation run completes
- **THEN** the read model or viewer input includes final resident states with location, lifecycle status, active or completed schedule information, and anomaly status when available

#### Scenario: Real LLM validation links viewer artifacts
- **WHEN** an opt-in real-LLM full-day validation run writes summary artifacts
- **THEN** the summary includes paths to generated read-model or viewer artifacts when those artifacts were requested or generated

### Requirement: Full-day validation distinguishes behavior quality in viewer input
Full-day validation SHALL expose behavior-quality diagnostics through viewer-readable artifacts so a user can inspect whether a run looks like coherent town life.

#### Scenario: Viewer input includes quality warnings
- **WHEN** validation detects unfinished schedules, lifecycle anomalies, loop guards, excessive skips, or schedule drift
- **THEN** the read model includes viewer-readable warning events or diagnostic summaries linked to the affected resident, day, minute, and source artifact when available

#### Scenario: Viewer input distinguishes failure from inspectable anomaly
- **WHEN** a validation run completes with behavioral anomalies but without runner failure
- **THEN** the read model and validation summary distinguish successful execution with inspectable anomalies from runtime or artifact-generation failure

### Requirement: Validation distinguishes partial-window schedule status

TownWorld validation SHALL distinguish schedule segments that were expected to complete inside the executed simulation window from future segments that were never reached.

#### Scenario: Future segments are not counted as unfinished defects

- **WHEN** a validation run ends before a schedule segment's start minute
- **THEN** the validation summary does not count that segment as an unfinished behavior defect
- **AND** it may report the segment under a future or not-run category

#### Scenario: Elapsed-window unfinished segments remain visible

- **WHEN** a validation run reaches or passes a schedule segment's end minute
- **AND** the segment is not complete or satisfied according to its policy
- **THEN** the validation summary reports it as an elapsed-window unfinished segment

#### Scenario: In-progress sustained segment is not a defect before its end

- **WHEN** a segment uses `occupy_until_segment_end`
- **AND** the run ends before the segment end minute after matching action evidence was recorded
- **THEN** validation reports the segment as satisfied in progress
- **AND** it does not count it as an unfinished defect

### Requirement: Validation distinguishes partial-day lifecycle checks

TownWorld validation SHALL apply home, wake, and sleep lifecycle anomaly checks only when the executed window covers the relevant lifecycle boundary.

#### Scenario: Short window does not trigger end-of-day sleep anomaly

- **WHEN** a validation run finalizes artifacts before the configured full-day sleep or day-end boundary
- **THEN** validation does not report that residents ended away from home as a sleep lifecycle anomaly
- **AND** the summary identifies the run as partial-day coverage

#### Scenario: Full-day run still reports lifecycle anomalies

- **WHEN** a validation run covers the full lifecycle boundary for a day
- **AND** a resident violates home, wake, or sleep expectations
- **THEN** validation reports the lifecycle anomaly with resident id, day, minute, location, and reason

### Requirement: Validation reports action lifecycle using finalized state

TownWorld validation SHALL distinguish submitted action lifecycle state from finalized action lifecycle state when reporting action quality.

#### Scenario: Submitted in-progress actions do not imply stuck actions

- **WHEN** an action log row records an action as `in_progress` at submission time
- **AND** a later tick finalizes that action
- **THEN** validation does not report the action as still in progress
- **AND** diagnostics expose finalized action counts separately from submission-state counts

#### Scenario: Truly unfinalized actions remain visible

- **WHEN** a run ends with a current action whose end minute has passed and no finalization record exists
- **THEN** validation reports the action as an action lifecycle defect

### Requirement: Full-day validation reports affordance alignment quality
Full-day and scaled TownWorld diagnostics SHALL summarize affordance alignment failures separately from runner failures.

#### Scenario: Diagnostics list top failed affordance targets
- **WHEN** a scaled town run records failed `use_affordance` or `interact_with` actions
- **THEN** diagnostics include top failed targets and objects by count
- **AND** diagnostics include top failed intents by count

#### Scenario: Diagnostics expose suggestion misses
- **WHEN** unsupported affordance failures include `suggested_affordances`
- **THEN** diagnostics report how many suggested affordance opportunities were still followed by repeated failure or loop guards

#### Scenario: Diagnostics expose rest lifecycle failures
- **WHEN** rest, sleep, wait, or lifecycle settlement produces failures or anomalies
- **THEN** diagnostics include a rest/lifecycle failure summary with affected residents and reasons

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

