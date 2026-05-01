## ADDED Requirements

### Requirement: Town engine supports multi-day resident lifecycles
The town engine SHALL support resident lifecycle transitions across simulated
days. Day-start, tick-time, and day-end state updates MUST be owned by the
town/world-engine layer, and generated state MUST be persisted in
`TownResidentState` or world-engine memory rather than inside `NPCAgent`.

#### Scenario: Resident receives a new day lifecycle
- **WHEN** a simulated day begins for a resident
- **THEN** the engine updates or creates that resident's day-specific planning state
- **AND** any generated schedule, scratch/currently text, or planning metadata is stored under town-owned state
- **AND** `NPCAgent` remains stateless between lifecycle calls

#### Scenario: Prior day influences next day
- **WHEN** a resident starts a second simulated day after conversations, reflections, or unfinished plans on the first day
- **THEN** the next-day planning context includes distilled relevant memories or relationship summaries
- **AND** the accepted next-day schedule can differ from the previous day's schedule because of that context

### Requirement: Town engine generates daily schedules through staged resident cognition
The town engine SHALL support GenerativeAgentsCN-inspired staged daily schedule
generation. The stages MUST include memory-backed currently update, wake-up or
start-of-day planning, coarse daily intention generation, validated schedule
segment generation, and active segment decomposition or revision.

#### Scenario: Schedule is generated for the current simulated day
- **WHEN** a resident has no valid schedule for the current simulated day
- **THEN** the engine invokes resident cognition to generate a candidate daily plan
- **AND** the engine validates the candidate before persisting it as that resident's schedule
- **AND** replay records the accepted schedule and the planning evidence used

#### Scenario: Existing schedule is not reused across days without renewal
- **WHEN** the simulated date advances beyond the date for which a resident schedule was generated
- **THEN** the engine treats the old schedule as historical state
- **AND** the resident must receive a new or explicitly renewed schedule for the new simulated day

#### Scenario: Active segment is decomposed on demand
- **WHEN** a resident enters a schedule segment that has not yet been decomposed
- **THEN** the engine may invoke resident cognition to produce bounded subtasks for that segment
- **AND** those subtasks are persisted in town-owned schedule state

### Requirement: Town engine validates and repairs generated schedules
The town engine SHALL validate generated schedules before accepting them. The
engine MUST check resident ownership, time bounds, overlap, known locations,
semantic reachability, and required fields. Invalid schedules MUST be rejected,
repaired, or replaced by a deterministic fallback without corrupting resident
state.

#### Scenario: Invalid generated location is rejected
- **WHEN** a generated schedule segment references an unknown location
- **THEN** the engine does not persist that segment as-is
- **AND** the validation result is recorded for debugging or replay

#### Scenario: Overlapping schedule is repaired or rejected
- **WHEN** a generated schedule contains overlapping segments for one resident
- **THEN** the engine repairs the overlap or rejects the schedule candidate
- **AND** the final persisted schedule has non-overlapping segments

### Requirement: Town engine revises schedules after significant interruptions
The town engine SHALL support bounded schedule revision after significant town
events, conversations, waiting, tool failures, or emergency events. Revisions
MUST be scoped to the active or future schedule window and MUST preserve
completed schedule evidence.

#### Scenario: Conversation revises active schedule segment
- **WHEN** a resident enters a conversation that consumes time during an active schedule segment
- **THEN** the engine may revise the resident's active segment or remaining subtasks
- **AND** replay records the original segment, interruption, and revised schedule state

#### Scenario: Completed schedule evidence is preserved
- **WHEN** a schedule revision occurs after a segment has already been completed
- **THEN** the completed segment evidence remains available for replay and later reflection

### Requirement: Town engine exposes richer semantic locations, affordances, and tools
The town engine SHALL support expanded semantic town content without requiring a
visual map. Locations and objects MUST expose affordances that can be rendered
into NPC context and used by town tools.

#### Scenario: Resident acts through object affordance
- **WHEN** a resident is at a location with an object that exposes a relevant affordance
- **THEN** the context includes the bounded affordance information
- **AND** a town tool can execute a valid interaction against that affordance

#### Scenario: Unknown affordance is rejected
- **WHEN** a resident requests an object interaction that is not supported by the object's affordances
- **THEN** the engine rejects the action without changing unrelated state
- **AND** the result explains available alternatives when available

### Requirement: Conversation and reflection outcomes influence later planning
The town engine SHALL store distilled conversation outcomes, relationship
summaries, unresolved topics, day summaries, and reflections as planning
evidence. Later daily planning contexts MUST be able to retrieve and render
that evidence.

#### Scenario: Conversation creates future planning evidence
- **WHEN** two residents complete a conversation with a meaningful outcome
- **THEN** the engine stores a distilled relationship or conversation memory with traceable metadata
- **AND** a later planning context for either resident can include that memory when relevant

#### Scenario: Reflection changes next-day planning context
- **WHEN** a resident generates a reflection before the next simulated day
- **THEN** the reflection is available as distilled memory for next-day planning
- **AND** replay can trace the reflection to its evidence records

### Requirement: Town engine guards against obvious loops and drift
The town engine SHALL provide long-run behavior guards that detect obvious
repetition, low-value action loops, repeated failed actions, excessive immediate
chatter, and schedule drift. Guards MUST be observable through replay or
validation output.

#### Scenario: Repeated failed move is detected
- **WHEN** a resident repeatedly attempts the same invalid movement or unreachable destination within a bounded window
- **THEN** the engine records a loop-guard event
- **AND** subsequent context discourages or prevents the same failed action

#### Scenario: Schedule drift is reported
- **WHEN** a resident spends a configured amount of simulated time away from all plausible schedule goals without a justified interruption
- **THEN** validation or replay records schedule drift evidence

### Requirement: Long-run replay explains resident behavior
The town engine SHALL write replay artifacts that explain long-running resident
behavior. Structured checkpoints MUST include schedule state, current action,
location, visible perception summary, relevant relationship cues, retrieved
planning evidence, reflection evidence, loop-guard events, and schedule
revision reasons when present.

#### Scenario: Replay explains action choice
- **WHEN** a resident performs an action during a long-run simulation
- **THEN** the replay can associate that action with current schedule state, location context, and available evidence when available

#### Scenario: Replay explains next-day plan change
- **WHEN** a resident's schedule changes between two simulated days because of memory, conversation, or reflection evidence
- **THEN** the replay records the previous plan summary, new plan summary, and evidence references used for the change

### Requirement: Town engine validates multi-day runs
The town project SHALL provide deterministic and opt-in real-LLM validation for
multi-day TownWorld runs. Validation MUST check completion without crashes,
absence of obvious loops, bounded schedule drift, conversation/reflection
influence, replay explainability, and preservation of NPC-layer statelessness.

#### Scenario: Deterministic multi-day validation passes
- **WHEN** the deterministic multi-day town validation runs with fixed fixtures and fake cognitive outputs
- **THEN** it completes the configured day and NPC count
- **AND** it asserts key replay, schedule, memory, and loop-guard fields

#### Scenario: Real LLM multi-day validation is opt-in
- **WHEN** the real-LLM multi-day validation script is run explicitly
- **THEN** it uses project model configuration
- **AND** it reports model call counts, replay paths, schedule quality checks, loop warnings, and memory/reflection outcomes
