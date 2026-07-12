# town-world-simulation Specification

## Purpose

Defines the semantic town simulation capability used to validate autonomous NPC action loops, world-owned schedules, local perception, town actions, and replay artifacts before scaling to a tile-backed town.
## Requirements
### Requirement: Town engine owns semantic world state

The system SHALL provide a town simulation engine that owns semantic world state, including simulated time, locations, exits, objects, occupants, local events, NPC schedules, and NPC current action state.

#### Scenario: Query current town state
- **WHEN** the town engine builds context for an NPC
- **THEN** the context is derived from the engine-owned town state
- **AND** the NPC layer does not read or store town state directly

#### Scenario: Location occupancy updates
- **WHEN** an NPC moves from one location to another
- **THEN** the source location no longer lists that NPC as an occupant
- **AND** the destination location lists that NPC as an occupant

### Requirement: Town engine advances by simulation ticks

The town engine SHALL advance simulated time in discrete ticks and evaluate active NPCs according to world-owned schedules, pending events, and action state.

#### Scenario: Tick advances time
- **WHEN** the engine advances one tick with a configured stride of 10 minutes
- **THEN** simulated time advances by 10 minutes
- **AND** the engine records the tick in its replay/checkpoint output

#### Scenario: Idle NPC is not forced into dialogue
- **WHEN** an NPC has no visible event, no pending inbox event, and no schedule transition
- **THEN** the engine may skip running that NPC for the tick

### Requirement: Town engine renders local perception

The town engine SHALL render NPC context from local perception rather than from global omniscient state. Local perception MUST include current time, current location, visible occupants, visible objects, local events, current schedule segment, recent history, todo items, and relevant memory context when available.

#### Scenario: NPC sees same-location event
- **WHEN** an event occurs in the same visible location as the NPC
- **THEN** the next context for that NPC includes a rendered description of that event

#### Scenario: NPC does not see hidden remote event
- **WHEN** an event occurs outside the NPC's visible locations
- **THEN** the NPC context does not include that event unless another world rule transmits it

### Requirement: Town engine exposes town action tools

The town engine SHALL expose town-specific action tools through world-engine tool injection. At minimum, the first implementation MUST support moving, observing, speaking to another NPC, interacting with an object, and waiting.

#### Scenario: Move action succeeds
- **WHEN** an NPC calls the move tool with a reachable destination
- **THEN** the engine updates location state
- **AND** returns a structured observation describing the move result

#### Scenario: Move action fails
- **WHEN** an NPC calls the move tool with an unreachable destination
- **THEN** the engine does not change the NPC location
- **AND** returns a structured failed observation with reachable alternatives when available

### Requirement: Town engine records replay artifacts

The town engine SHALL write replay-friendly artifacts that allow a simulation run to be inspected after execution. The initial replay output MUST support at least a structured JSON event stream and a human-readable timeline.

#### Scenario: Action appears in replay
- **WHEN** an NPC performs a successful action during a tick
- **THEN** the replay output includes the tick time, NPC id, action type, location, and rendered summary

#### Scenario: Conversation appears in replay
- **WHEN** NPCs speak during the simulation
- **THEN** the human-readable timeline includes the speaker, listener, location, and utterance summary or text

### Requirement: First town milestone is intentionally small

The first town implementation SHALL validate a small simulation before scaling. It MUST support a scenario with 3-5 NPCs, at least 5 semantic locations, one simulated day, deterministic tests, and replay artifact generation.

#### Scenario: Small town smoke run
- **WHEN** the small-town smoke scenario runs with stubbed or deterministic model responses
- **THEN** it completes one simulated day
- **AND** produces replay artifacts
- **AND** demonstrates movement, observation, and at least one NPC-to-NPC interaction

### Requirement: Town engine owns persistent resident state
The town engine SHALL maintain persistent per-NPC resident state for
Stanford-style town simulation. Resident state MUST be owned by the town/world
engine layer and MUST NOT be retained by `NPCAgent` between calls.

#### Scenario: Resident state persists across ticks
- **WHEN** a resident accumulates a daily schedule, current action, spatial
  memory, or reflection trigger state during one tick
- **THEN** a later tick can render that state into AgentContext for the same
  resident
- **AND** `NPCAgent` does not need an in-memory object from the prior tick

#### Scenario: Resident state is distinct from generic NPC capability state
- **WHEN** the town engine stores schedule, spatial, action, or reflection
  counters for a resident
- **THEN** those values are stored under town/world-engine ownership
- **AND** `src/annie/npc/` remains business-agnostic and stateless across runs

### Requirement: Residents generate daily planning through NPCAgent
The town engine SHALL support NPC-generated daily planning by invoking
`NPCAgent` as a stateless cognitive backend for a resident. The resulting plans
MUST be persisted in town-owned resident state, not inside `NPCAgent`.

#### Scenario: Daily plan becomes schedule state
- **WHEN** a resident is asked to plan a day from persona, memory, current
  situation, and known town places
- **THEN** `NPCAgent` may produce a daily schedule proposal for that resident
- **AND** the accepted plan is stored in that resident's town-owned state
- **AND** subsequent NPC contexts render the current schedule segment from that state

#### Scenario: Schedule revision remains resident-owned
- **WHEN** an event causes an NPC schedule to be revised
- **THEN** the revised schedule is persisted in the resident's town-owned state
- **AND** the NPC layer receives the revision only through a later AgentContext

### Requirement: Town engine supports bounded spatial perception
The town engine SHALL render local perception with a bounded attention policy.
Perception MUST be derived from world-owned spatial state and MUST support
visible locations, visible actors, visible objects, local events, and attention
limits.

#### Scenario: Perception applies an attention limit
- **WHEN** more local events or objects are visible than the configured attention limit
- **THEN** the context includes only the selected bounded set
- **AND** the selection is deterministic in deterministic test mode

#### Scenario: Spatial memory is rendered from resident state
- **WHEN** an NPC has learned or previously visited town places
- **THEN** relevant spatial knowledge is rendered through AgentContext
- **AND** the NPC layer does not own a separate persistent spatial memory store

### Requirement: Town engine supports relationship-aware conversations
The town engine SHALL support NPC-to-NPC conversation decisions using local
visibility, recent chat history, cooldowns, relationship memory, and topic
context. Conversation orchestration MUST remain world-owned.

#### Scenario: Relationship context affects conversation
- **WHEN** an NPC considers starting a conversation with a visible NPC
- **THEN** the context includes relevant relationship or recent-interaction cues
- **AND** the engine still arbitrates whether the conversation can start

#### Scenario: Conversation avoids repeated immediate chatter
- **WHEN** two NPCs recently completed a conversation
- **THEN** a new conversation between the same pair is rejected or discouraged
- **AND** the replay records the cooldown outcome when an action is attempted

### Requirement: Town engine supports reflection triggers
The town engine SHALL support reflection triggers based on resident-local
accumulated important events, conversations, or schedule outcomes. Reflections
MUST be generated through resident cognition and stored as distilled memory
records using existing memory categories and metadata.

#### Scenario: Important events trigger reflection
- **WHEN** an NPC accumulates enough important events since its last reflection
- **THEN** the town runtime invokes or renders a reflection opportunity for that
  resident
- **AND** resulting reflections are stored as `reflection` or `impression`
  memory, not raw episodic dialogue

#### Scenario: Reflection evidence is traceable
- **WHEN** a reflection memory record is written
- **THEN** its metadata references the triggering event, conversation, schedule,
  or replay identifiers when available

### Requirement: Town engine records long-run replay snapshots
The town engine SHALL record structured replay snapshots for long-running town
simulations. Snapshots MUST support inspection of time, resident location,
current action, schedule state, conversation sessions, and reflection or memory
summary events.

#### Scenario: Snapshot records town state
- **WHEN** the runtime reaches a configured replay checkpoint interval
- **THEN** the replay output includes a structured snapshot of active NPC town state
- **AND** existing action stream and human-readable timeline outputs remain available

#### Scenario: Replay supports deterministic comparison
- **WHEN** a deterministic town run is executed twice with the same fixture and fake agent
- **THEN** the structured replay output is stable enough for tests to compare key fields

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
into NPC context and used by town tools. Scaled town content MUST include
executable affordances for common resident schedule intents including delivery,
stall preparation, inventory checks, price-board updates, home note review,
home note filing, day planning, rest, lesson review, equipment inspection,
art review, seed ledger work, event preparation, parcel processing, and
editorial review.

#### Scenario: Resident acts through object affordance
- **WHEN** a resident is at a location with an object that exposes a relevant affordance
- **THEN** the context includes the bounded affordance information
- **AND** a town tool can execute a valid interaction against that affordance

#### Scenario: Unknown affordance is rejected
- **WHEN** a resident requests an object interaction that is not supported by the object's affordances
- **THEN** the engine rejects the action without changing unrelated state
- **AND** the result explains available alternatives when available

#### Scenario: Scaled schedules have executable affordances
- **WHEN** the scaled town scenario is loaded
- **THEN** high-frequency objects used by seeded schedules expose aliases for their common schedule intents
- **AND** home locations accept both lowercase and uppercase rest affordance requests through matching semantics

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

### Requirement: Town engine persists versioned runtime snapshots

The town engine SHALL persist a versioned JSON-compatible runtime snapshot for
authoritative TownWorld state. The snapshot MUST include engine-owned state
needed to resume a run, including simulated time, semantic world state,
resident state, schedules, current actions, conversation sessions, event
delivery state, loop-guard state, and replay cursor metadata. The first
snapshot schema version MUST be loaded through an explicit version dispatch path.

#### Scenario: Snapshot captures resumable town state
- **WHEN** a TownWorld run writes a runtime snapshot
- **THEN** the snapshot includes a schema version and all required engine-owned state sections
- **AND** the snapshot does not require a retained `NPCAgent` instance to be usable

#### Scenario: Unsupported snapshot version fails clearly
- **WHEN** a runtime snapshot has an unsupported schema version
- **THEN** loading fails with a clear validation error
- **AND** no memory, history, replay, or snapshot files are modified

#### Scenario: Snapshot excludes derived replay as source of truth
- **WHEN** replay artifacts exist for the same run
- **THEN** the runtime snapshot remains the authoritative resume source
- **AND** compressed or presentation-oriented replay artifacts are treated as derived outputs

#### Scenario: Snapshot excludes transient execution state
- **WHEN** a runtime snapshot is written
- **THEN** it does not serialize live `NPCAgent` instances, LLM clients, raw Chroma collections, raw history JSONL content, temporary prompts, route execution frames, or tool-call stacks

### Requirement: Town engine resumes from runtime snapshots

The town engine SHALL reconstruct a runnable `TownWorldEngine` from a runtime
snapshot and configured memory/history backends. Resuming MUST restore
world-owned state without storing durable TownWorld state in `NPCAgent`.

#### Scenario: Resume rebuilds engine-owned state
- **WHEN** a TownWorld engine is loaded from a valid runtime snapshot
- **THEN** the loaded engine has the same simulated clock, resident locations,
  schedules, active actions, conversation state, and loop-guard state represented by the snapshot
- **AND** subsequent ticks can continue from that state

#### Scenario: Resume preserves NPC-layer statelessness
- **WHEN** a resumed engine invokes an NPC after loading a snapshot
- **THEN** all resident-specific durable state is supplied through `AgentContext`
- **AND** `NPCAgent` does not need prior in-memory state from before the snapshot

#### Scenario: Resume validates backend layout
- **WHEN** a run is resumed from a manifest or snapshot that references missing or incompatible memory/history paths
- **THEN** resume fails before advancing the simulation
- **AND** the error identifies the missing or incompatible backend reference

### Requirement: Town runs write a manifest linking durable artifacts

The town runtime SHALL write a run manifest that links the authoritative
snapshot, optional step snapshots, replay artifacts, history directory, vector
store path, model configuration summary, and validation output paths for a
simulation run. Manifest file paths MUST be relative to the manifest's run root
unless an explicitly external path is marked as external.

#### Scenario: Manifest describes durable run layout
- **WHEN** a TownWorld run writes persistence artifacts
- **THEN** the manifest records the current snapshot path, replay artifact
  paths, history path, vector-store path, run identifier, and relevant
  validation metadata
- **AND** normal artifact paths are relative to the manifest's directory

#### Scenario: Manifest supports resume discovery
- **WHEN** a user or validation script resumes a named TownWorld run
- **THEN** the manifest provides enough information to locate the latest
  authoritative snapshot and the associated memory/history backends

#### Scenario: Default run layout is movable
- **WHEN** a run directory containing a manifest is moved as a unit
- **THEN** manifest-relative snapshot, replay, history, and vector-store paths can still be resolved from the new location

### Requirement: Town engine validates pause and resume behavior

The town project SHALL provide deterministic validation for pause/resume
behavior. Validation MUST compare key behavioral fields from a continuous run
and a run that is saved, loaded, and continued.

#### Scenario: Resumed deterministic run matches stable behavior
- **WHEN** a deterministic TownWorld scenario is run continuously and also run
  with a save/load boundary at the same simulated time
- **THEN** the resumed run matches the continuous run on stable fields including
  clock, resident locations, schedule state, conversation cooldowns,
  loop-guard state, memory evidence availability, and replay checkpoint shape

#### Scenario: Invalid snapshot fails clearly
- **WHEN** a snapshot is missing a required schema version or required runtime section
- **THEN** loading fails with a clear validation error
- **AND** unrelated memory, history, and replay artifacts are not modified

### Requirement: Town runtime provides a consolidated run entry point
The town project SHALL provide a consolidated runtime entry point for named
TownWorld runs. The runtime MUST support creating a new run, resuming an
existing run, advancing a bounded tick or day window, and writing manifest-linked
snapshot, replay, history, vector-store, and diagnostics artifacts. The runtime
MUST orchestrate setup and artifact writing without becoming a second owner of
durable simulation state.

#### Scenario: New named run writes standard artifacts
- **WHEN** a TownWorld run is started with a run id, scenario content, agent mode, and bounded tick or day window
- **THEN** the runtime creates a manifest-backed run directory for that run id
- **AND** it writes the latest runtime snapshot, replay artifacts, diagnostics summary, and backend paths under the run directory

#### Scenario: Existing run resumes from manifest
- **WHEN** the runtime is asked to resume an existing TownWorld run
- **THEN** it loads the manifest, restores the authoritative latest snapshot, resolves associated memory and history backends, and continues from the restored simulated time
- **AND** it does not require a retained `NPCAgent` instance from before the resume

#### Scenario: Runtime uses project model configuration
- **WHEN** the runtime is configured to use a real `NPCAgent`
- **THEN** it uses the project-owned model configuration and environment variables
- **AND** it does not create an ad-hoc LLM configuration path

#### Scenario: Runtime allows agent factory injection
- **WHEN** tests or scripts provide a runtime agent factory
- **THEN** the runtime uses the provided factory to construct the `TownAgent`
- **AND** setup, execution, artifact writing, and diagnostics still flow through the same consolidated runtime path

#### Scenario: Runtime preserves current engine-step semantics
- **WHEN** a bounded TownWorld run is configured with days, start minute, end minute, and max ticks per day
- **THEN** days and minute bounds define the run goal while max ticks per day acts as a safety guard
- **AND** the runtime does not require a fixed-duration clock tick redesign for this change

### Requirement: Town scenarios load from project-owned content files
The town runtime SHALL load semantic scenario content from a project-owned
single-file YAML schema and compile it into world-engine-owned `TownState` and
memory seed data. Content loading MUST validate required fields and fail clearly
before the simulation advances when content is invalid.

#### Scenario: Scenario content constructs semantic town state
- **WHEN** a versioned scenario YAML file defines id, name, locations, exits, location-local objects, affordances, residents, personas, relationships, starting locations, and optional schedules
- **THEN** the loader constructs a `TownState` with equivalent semantic locations, objects, resident state, schedules, and starting locations
- **AND** durable resident data remains owned by the town/world-engine layer

#### Scenario: Scenario persona fields are ANNIE semantic fields
- **WHEN** scenario content defines a resident persona
- **THEN** the persona uses ANNIE-oriented fields such as currently, lifestyle, background, and traits
- **AND** the loader does not require GenerativeAgentsCN `Agent` state, tile coordinates, sprites, portraits, or per-resident LLM config

#### Scenario: Memory seeds are loaded through world memory
- **WHEN** scenario content includes initial memory seed records for a resident
- **THEN** the runtime writes those records through the resident's `MemoryInterface`
- **AND** the records use supported memory categories and traceable metadata

#### Scenario: Invalid scenario content fails before ticking
- **WHEN** scenario content references an unknown location, invalid exit, missing resident id, unsupported affordance shape, or malformed schedule segment
- **THEN** runtime setup fails with a clear validation error
- **AND** no tick is advanced and no partial simulation state is treated as a completed run

### Requirement: Town runtime validates resume continuation behavior
The town project SHALL provide deterministic validation proving that a resumed
TownWorld run can continue after loading from a runtime snapshot. Validation
MUST compare stable behavioral signatures between a continuous run and a run
that saves, loads, and continues across the same simulated window.

#### Scenario: Resumed run continues with stable behavior
- **WHEN** a deterministic TownWorld scenario is executed continuously and also executed with a save/load boundary
- **THEN** the resumed run continues ticking with a fresh stateless agent
- **AND** the resumed and continuous runs match on stable behavioral signatures including clock, resident locations, schedule state, active actions, conversation state, loop guards, memory evidence availability, and replay checkpoint shape

#### Scenario: Resume marker appears in diagnostics
- **WHEN** a runtime run resumes from a previous manifest snapshot
- **THEN** diagnostics record the source manifest, source snapshot, restored simulated time, and first continued tick
- **AND** replay or diagnostics can distinguish pre-resume state from post-resume continuation evidence

### Requirement: Town runtime writes stable diagnostics artifacts
The town runtime SHALL write a stable diagnostics artifact for each run. The
diagnostics MUST summarize run parameters, scenario identity, model summary,
tick outcomes, run/skip reasons, action outcomes, schedule revisions, loop
guards, memory/reflection evidence, replay paths, snapshot paths, and resume
metadata when present.

#### Scenario: Diagnostics explain tick activation
- **WHEN** a runtime run advances ticks for one or more residents
- **THEN** diagnostics include which residents ran or skipped per tick
- **AND** skipped residents include a world-owned reason such as no visible event, no pending inbox event, completed schedule, or inactive schedule window

#### Scenario: Diagnostics summarize action outcomes
- **WHEN** residents attempt town actions during a runtime run
- **THEN** diagnostics include action outcome counts and failure reasons grouped by action type and resident id
- **AND** detailed replay artifacts remain available for inspecting individual action records

#### Scenario: Diagnostics link persistence artifacts
- **WHEN** a runtime run writes persistence and replay artifacts
- **THEN** diagnostics include manifest path, latest snapshot path, replay paths, history path, vector-store path, and validation status
- **AND** paths are resolvable relative to the run directory unless explicitly marked external

### Requirement: Town ticks use fixed stride with action lifecycle gating
The town engine SHALL advance simulation time using fixed-stride global ticks.
At the start of each tick, the engine MUST finalize any due `CurrentAction`
records before deciding which NPCs can run. An NPC with a current action whose
end minute is later than the tick start minute MUST NOT be activated during that
tick.

#### Scenario: Due action finalizes before activation
- **WHEN** an NPC has a `CurrentAction` ending at or before the current tick minute
- **THEN** the engine finalizes the action before building that NPC's next context
- **AND** the NPC may be activated during the same tick if schedule or event rules require it

#### Scenario: In-progress action blocks activation
- **WHEN** an NPC has a `CurrentAction` ending after the current tick minute
- **THEN** the engine skips that NPC for the tick
- **AND** replay or diagnostics records `action_in_progress` with the action type and due minute

#### Scenario: Tick advances after replay checkpoint
- **WHEN** the engine completes activation, action execution, and replay checkpoint recording for a tick
- **THEN** the engine advances `TownState.clock.minute` by the configured stride
- **AND** the checkpoint records the tick start minute rather than the already-advanced minute

### Requirement: Duration-bearing town actions share a CurrentAction lifecycle
The town engine SHALL represent duration-bearing resident actions through a
world-owned `CurrentAction` lifecycle. Movement, waiting, semantic interaction,
speech, and conversation MUST create, finalize, fail, or interrupt a
`CurrentAction` with traceable reasoning. Observation and affordance inspection
MUST remain non-blocking information actions that do not consume simulated time.

#### Scenario: Wait blocks future ticks
- **WHEN** an NPC executes a wait action with a positive duration
- **THEN** the engine writes a `CurrentAction` for that NPC
- **AND** later ticks skip the NPC until the wait action is due to finalize

#### Scenario: Movement records occupancy duration
- **WHEN** an NPC successfully moves to another semantic location
- **THEN** the engine records movement lifecycle evidence with start minute, end minute, destination, and status
- **AND** the NPC cannot take another action until the movement duration has elapsed

#### Scenario: Failed action has bounded duration and replay evidence
- **WHEN** a duration-bearing action fails validation or arbitration
- **THEN** the engine records a failed action result with a bounded duration
- **AND** replay or diagnostics includes the failure reason and the next minute when the NPC may act

#### Scenario: Observation does not block activation
- **WHEN** an NPC executes `observe` or `inspect_affordances`
- **THEN** the engine returns current local information without writing `CurrentAction`
- **AND** the action does not consume simulated time or block the NPC's next eligible tick

#### Scenario: Immediate effect interruption does not roll back world state
- **WHEN** an immediate-effect action has already changed world state and is later interrupted
- **THEN** the engine records the interruption and `effect_applied=true`
- **AND** the engine does not roll back the already-applied world state

#### Scenario: Completion effect is reserved for future long actions
- **WHEN** a future tool declares completion-time effects
- **THEN** the engine records a `CurrentAction` when the tool is accepted
- **AND** the world effect is applied only when that action finalizes

#### Scenario: Resume preserves action lifecycle
- **WHEN** a runtime snapshot is resumed while an NPC has an unfinished `CurrentAction`
- **THEN** the resumed engine preserves the action start minute, duration, end minute, status, and summary
- **AND** subsequent ticks apply the same blocking or finalization behavior as a continuous run

### Requirement: Town residents complete a daily lifecycle
The town engine SHALL support a complete daily lifecycle for active residents,
including wake-up or start-of-day initialization, memory-backed planning,
schedule execution, day-end summary, and next-day planning influence. All
durable lifecycle state MUST remain in the town/world-engine layer.

#### Scenario: Day start creates a current-day plan
- **WHEN** a resident starts a simulated day without a valid schedule for that day
- **THEN** the engine generates or falls back to a validated current-day schedule
- **AND** the accepted schedule, planning evidence, and day metadata are stored in town-owned resident state

#### Scenario: Day execution uses action lifecycle
- **WHEN** residents execute their current-day schedules
- **THEN** every duration-bearing action follows the shared `CurrentAction` lifecycle
- **AND** schedule progress is derived from world-owned action, location, completion, and event evidence

#### Scenario: Day end stores distilled summary
- **WHEN** a simulated day ends for a resident
- **THEN** the engine records completed, overdue, revised, interrupted, and unfinished schedule evidence
- **AND** it stores a distilled day summary as supported memory with traceable metadata

#### Scenario: Prior day influences next-day planning
- **WHEN** a resident starts a later simulated day
- **THEN** the planning context can include relevant reflection, impression, day-summary, conversation, todo, relationship, and unfinished-schedule evidence
- **AND** the evidence references are available in replay or diagnostics

### Requirement: Town schedule execution has explicit completion overdue drift and revision boundaries
The town engine SHALL define explicit schedule execution semantics for segment
completion, overdue detection, drift detection, revision, and fallback behavior.
Schedule segments MUST NOT silently complete because their time window elapsed
or because an ordinary action appears related to the segment.

#### Scenario: Segment completes only through finish tool
- **WHEN** an NPC calls `finish_schedule_segment` for the active segment
- **THEN** the engine records the segment as completed with note, day, start minute, location, and evidence metadata
- **AND** the completed evidence remains available after later schedule revisions

#### Scenario: Ordinary tool action does not complete segment
- **WHEN** an NPC performs a related ordinary action such as moving, eating, drinking, reading, speaking, or interacting with an object
- **THEN** the engine may record supporting schedule evidence or prompt hints
- **AND** the active segment remains incomplete until `finish_schedule_segment` is called

#### Scenario: Segment becomes overdue
- **WHEN** the tick minute reaches or passes an active segment end minute and the segment has not completed
- **THEN** the engine records overdue schedule evidence
- **AND** replay or diagnostics identifies the segment, resident, planned location, and current location

#### Scenario: Overdue segment remains recoverable before day end
- **WHEN** a segment is overdue and the simulated day has not ended
- **THEN** the segment remains eligible for explicit completion or schedule revision
- **AND** the engine does not mark the segment missed solely because it is overdue

#### Scenario: Day end marks expired uncompleted segment missed
- **WHEN** day-end processing finds an expired segment that was not completed
- **THEN** the engine records missed or fallback-missed evidence for that segment
- **AND** the engine does not auto-complete the segment

#### Scenario: Schedule drift is detected
- **WHEN** a resident remains away from plausible schedule goals for a configured threshold without an explanatory current action, interruption, conversation, or significant event
- **THEN** the engine records a schedule drift guard event
- **AND** the guard is rendered into later context or diagnostics

#### Scenario: Drift whitelist excludes justified interruptions
- **WHEN** a resident is away from the schedule goal because of a valid current action toward the segment, active conversation, pending priority inbox event, significant event handling, or recent schedule revision grace window
- **THEN** the engine does not count that interval as schedule drift

#### Scenario: Conversation cooldown is a narrow drift exemption
- **WHEN** conversation cooldown blocks or rejects a social action
- **THEN** the cooldown may explain the social action outcome
- **AND** the cooldown does not by itself exempt physical distance from the schedule goal from drift detection

#### Scenario: Drift blacklist counts low-value away behavior
- **WHEN** a resident has no current action while away from the goal, repeatedly visits non-schedule locations, repeatedly waits away from the goal, repeatedly observes or inspects away from the goal, or repeatedly fails moves that do not approach the goal
- **THEN** the engine counts that evidence toward schedule drift detection

#### Scenario: Revision preserves completed evidence
- **WHEN** the engine revises a resident's active or future schedule after an event, conversation, failed action, overdue segment, or drift
- **THEN** the revision records before and after schedule state
- **AND** completed segment evidence is preserved for replay, reflection, and day-end summary

#### Scenario: Invalid or missing schedule uses deterministic fallback
- **WHEN** generated planning output is invalid, missing, overlapping, out of bounds, or references unknown locations
- **THEN** the engine rejects or repairs the candidate before persistence
- **AND** if no valid candidate remains, the engine persists a deterministic fallback schedule with validation evidence

### Requirement: Town long-run validation covers semantic runtime closure
The town project SHALL provide deterministic long-run validation for multi-NPC,
multi-day semantic TownWorld behavior. This validation MUST be the primary
acceptance contract for backend simulation semantics, while real-LLM validation
remains opt-in smoke coverage.

#### Scenario: Deterministic long-run validation passes
- **WHEN** deterministic long-run validation runs for multiple residents across multiple simulated days
- **THEN** it verifies fixed tick advancement, action lifecycle blocking, day planning, schedule completion or overdue handling, conversation cooldowns, reflection or day-summary influence, replay artifacts, and absence of unhandled loop failures

#### Scenario: Resume matches stable long-run behavior
- **WHEN** deterministic validation compares a continuous long-run execution with a save/load/continue execution across the same simulated window
- **THEN** the two runs match on stable behavioral signatures for clock, resident locations, schedules, current actions, conversation state, loop guards, memory evidence, replay checkpoint shape, and resume metadata

#### Scenario: Real LLM validation reports smoke evidence
- **WHEN** opt-in real-LLM long-run validation is executed
- **THEN** it uses project-owned model configuration
- **AND** it reports model calls, lifecycle failures, schedule quality, loop warnings, replay paths, resume evidence, and memory or reflection outcomes without requiring byte-for-byte equality

### Requirement: Town replay and diagnostics explain semantic runtime decisions
The town runtime SHALL write replay and diagnostics artifacts that explain the
semantic reason for activation, skipping, action lifecycle changes, schedule
state transitions, planning evidence, reflection evidence, day summaries, and
resume boundaries.

#### Scenario: Replay explains activation and skipping
- **WHEN** a tick runs with multiple active residents
- **THEN** replay or diagnostics records which residents ran, which residents skipped, and the world-owned reason for each decision
- **AND** skipped residents with in-progress actions include action type and due minute

#### Scenario: Replay explains action lifecycle
- **WHEN** a resident action starts, remains in progress, finalizes, fails, or is interrupted
- **THEN** replay or diagnostics records the lifecycle state, start minute, end minute, duration, status, and relevant action facts

#### Scenario: Replay explains schedule transitions
- **WHEN** a schedule segment completes, becomes overdue, drifts, or is revised
- **THEN** replay or diagnostics records the resident, segment identity, before or after state where applicable, and evidence references

#### Scenario: Replay explains next-day planning influence
- **WHEN** next-day planning uses prior memory, reflection, conversation, day-summary, todo, relationship, or unfinished-schedule evidence
- **THEN** replay or diagnostics records the evidence categories and traceable references used by the planning context

#### Scenario: Resume boundary is visible
- **WHEN** a run resumes from a manifest and snapshot
- **THEN** diagnostics records the source manifest, source snapshot, restored simulated time, restored current actions, and first continued tick
- **AND** replay or diagnostics distinguishes pre-resume state from post-resume continuation evidence

### Requirement: Town engine models full-day resident lifecycle
The town engine SHALL model resident day boundaries, home locations, sleep locations, wake-up decisions, and overnight state as world-owned resident lifecycle state.

#### Scenario: Resident starts day from sleep or home state
- **WHEN** a new simulated day begins for a resident with home and sleep metadata
- **THEN** the engine initializes that resident from the persisted sleep or home state unless replay state explicitly says otherwise
- **AND** the planning context does not silently treat the prior day's last public location as a normal next-day starting point

#### Scenario: Resident has home and sleep metadata
- **WHEN** a scenario resident is loaded for full-day validation
- **THEN** the resident has a home location or sleep location known to the town engine
- **AND** the location is reachable from the semantic town graph

#### Scenario: Overnight anomaly is recorded
- **WHEN** a resident reaches the end of a simulated day away from home or sleep state without a valid schedule reason
- **THEN** the engine records a lifecycle anomaly in replay or diagnostics
- **AND** the next day's planning evidence can include that anomaly

### Requirement: Residents generate full-day schedules with wake and sleep structure
The town engine SHALL support NPC-generated 24-hour daily schedules that include wake-up timing, sleep/rest blocks, and return-home behavior when required by the resident's lifecycle metadata.

#### Scenario: Full-day planning includes wake-up
- **WHEN** a resident generates a full-day plan through `NPCAgent`
- **THEN** the accepted planning state includes a wake-up minute
- **AND** wake-up evidence is recorded in planning checkpoints

#### Scenario: Full-day schedule includes sleep
- **WHEN** the engine accepts a generated full-day schedule
- **THEN** the schedule includes sleep or rest time before wake-up or near the end of the day
- **AND** the sleep or rest segment references a valid resident home or sleep location

#### Scenario: Away resident returns before sleep
- **WHEN** a generated schedule places a resident away from home before a sleep segment
- **THEN** the accepted schedule includes a reachable return-home transition before sleep
- **OR** the engine records a validation repair or rejection explaining why the schedule was not accepted as-is

### Requirement: Schedule completion can be inferred from successful actions
The town engine SHALL infer schedule completion from successful world actions when those actions satisfy the schedule segment, even if the resident does not explicitly call `finish_schedule_segment`. Completion evidence MUST include the matched action id, action type, segment, and matching reason when inference occurs.

#### Scenario: Movement completes travel segment
- **WHEN** a resident successfully moves to the target location for a travel-like schedule segment
- **THEN** the segment can be marked completed or completion-inferred
- **AND** the evidence references the successful move action

#### Scenario: Affordance completes matching segment
- **WHEN** a resident successfully uses an object or location affordance whose label, aliases, target, event type, note, or completion tag matches the active schedule intent
- **THEN** the segment can be marked completed or completion-inferred
- **AND** the day summary does not count that segment as missed solely because `finish_schedule_segment` was not called

#### Scenario: Rest and wait complete lifecycle segment
- **WHEN** a resident waits or uses a home-level rest affordance at the resident's home or sleep location during a sleep/rest segment
- **THEN** the segment can be marked completed or completion-inferred
- **AND** lifecycle settlement does not require unrelated table interaction

#### Scenario: Short event segment can complete from conversation response
- **WHEN** a short inserted event segment targets another NPC and the target NPC has responded or the related conversation has naturally closed
- **THEN** the segment can be marked explicit or inferred complete instead of missed solely because the segment window was brief

#### Scenario: Inferred completion is traceable
- **WHEN** the engine infers completion for a schedule segment
- **THEN** replay or day-summary metadata includes the inferred status, matched action id, segment start minute, location, and matching reason

### Requirement: Town runtime exports presentation replay artifacts
The town runtime SHALL export presentation-facing replay artifacts for completed or bounded TownWorld runs while preserving existing debug replay, diagnostics, validation, and snapshot artifacts.

#### Scenario: Runtime writes presentation event stream
- **WHEN** a TownWorld runtime run writes replay artifacts
- **THEN** it writes or derives a presentation event stream with stable event categories for run boundaries, day boundaries, resident planning, action lifecycle, movement, speech, conversations, schedule transitions, reflections, day summaries, lifecycle anomalies, and resume boundaries when those events occur
- **AND** the event stream is linked from the run manifest or diagnostics artifact

#### Scenario: Presentation artifacts do not replace authoritative state
- **WHEN** presentation replay artifacts are generated
- **THEN** the runtime snapshot remains the authoritative resume source
- **AND** presentation artifacts are treated as derived outputs

#### Scenario: Runtime can build viewer input after resume
- **WHEN** a run resumes from a manifest and continues ticking
- **THEN** the presentation replay artifacts include a visible resume boundary with source manifest, source snapshot, restored simulated time, and first continued tick when available

### Requirement: Town replay events are presentation-safe
The town runtime SHALL normalize presentation replay events so consumers do not need to understand internal engine log shapes.

#### Scenario: Action event has normalized fields
- **WHEN** a resident action appears in the presentation replay stream
- **THEN** the event includes event type, day, minute, resident id, location id, status, summary, and relevant action facts such as action type, start minute, end minute, and source ids when available

#### Scenario: Schedule event has normalized fields
- **WHEN** a schedule segment completes, becomes overdue, is missed, drifts, is inferred complete, or is revised
- **THEN** the event includes resident id, day, segment identity, location id, intent, transition type, summary, and evidence references when available

#### Scenario: Conversation event has normalized fields
- **WHEN** a conversation starts, records a turn, or ends
- **THEN** the event includes participants, location id, topic or utterance summary, minute, status, and source session id when available

### Requirement: Town run manifest links watchable replay artifacts
The town run manifest SHALL link generated presentation read-model and viewer artifacts when they are available.

#### Scenario: Manifest includes viewer paths
- **WHEN** a TownWorld run writes read-model or viewer artifacts
- **THEN** the run manifest records their paths relative to the run directory unless an explicitly external path is marked as external

#### Scenario: Existing artifact consumers remain compatible
- **WHEN** presentation replay artifacts are added to a run manifest
- **THEN** existing replay, diagnostics, validation, and snapshot paths remain present with their existing meanings

### Requirement: Town runtime follows a simplified semantic tick loop

The town engine SHALL run residents through a deterministic semantic tick loop:
finalize due actions, select the current schedule window, build an action
context only for free residents, start one concrete world action, and record
side effects after the action/schedule transition.

#### Scenario: Due action finalizes before resident activation

- **WHEN** a resident has a current action whose end minute is at or before the current clock minute
- **AND** the runtime is about to activate that resident for another decision
- **THEN** the engine first finalizes the due action
- **AND** schedule advancement uses the finalized action evidence before a new action context is built

#### Scenario: Busy resident is not asked for a new action

- **WHEN** a resident has a running action whose end minute is after the current clock minute
- **THEN** the engine does not build a normal action-selection context for that resident
- **AND** it preserves the running action until the action finalization step

#### Scenario: Side effects do not replace the main loop

- **WHEN** reflection evidence, relationship cues, replay rows, diagnostics, or conversation summaries are recorded during a tick
- **THEN** they are recorded after or around the action/schedule transition
- **AND** they do not advance ordinary schedules except through finalized action evidence or an explicit schedule policy

### Requirement: Town action lifecycle is compact and deterministic

The town engine SHALL represent normal action control using action type, start
minute, end minute, status, and structured result evidence. Additional lifecycle
metadata MAY be preserved for replay or debugging, but normal prompt policy and
schedule advancement SHALL NOT depend on the NPC reasoning over that metadata.

#### Scenario: Action duration determines when resident becomes free

- **WHEN** a resident starts a successful duration-bearing action
- **THEN** the engine records the action start minute and end minute
- **AND** the resident remains occupied until the finalization step reaches the end minute

#### Scenario: Instant support actions do not overwrite running work

- **WHEN** a resident already has a running duration-bearing action
- **AND** a support action such as wait, observe, inspect, or diagnostics would be considered in the same activation window
- **THEN** the engine does not overwrite the running action
- **AND** it waits for normal action finalization before selecting a new concrete action

#### Scenario: Lifecycle debug metadata is not prompt control

- **WHEN** the engine builds a normal action-selection prompt
- **THEN** the prompt does not require the NPC to reason about internal lifecycle fields such as effect model or occupancy model
- **AND** the NPC is asked to choose a concrete world action from the current situation

### Requirement: Town engine automatically completes satisfied schedule segments

The town engine SHALL automatically mark a current schedule segment complete when a finalized successful action satisfies the segment according to world-owned action evidence and the segment completion policy.

#### Scenario: First matching action completes default segment

- **WHEN** a resident performs a successful non-observe action during the current schedule segment
- **AND** the finalized action matches the segment target location and intent evidence
- **AND** the segment uses the default `first_matching_action` policy
- **THEN** the town engine marks the schedule segment complete after simulated time reaches the action end minute
- **AND** later ticks do not ask the resident to continue that same segment

#### Scenario: Movement alone does not complete work segment

- **WHEN** a resident moves to the target location for a work or interaction schedule segment
- **THEN** the town engine records the movement as progress
- **AND** it does not mark the segment complete until a matching non-movement action finalizes

#### Scenario: Travel segment can complete by movement

- **WHEN** a resident's current schedule segment is explicitly a travel or arrival segment
- **AND** a successful move action reaches the target location
- **THEN** the town engine may mark that segment complete after the move action finalizes

### Requirement: Town schedule completion policies are explicit and bounded

The town engine SHALL support a bounded set of schedule completion policies for semantic schedule segments, defaulting to `first_matching_action` when no policy is provided.

#### Scenario: Ordinary segment remains a simple time block

- **WHEN** a schedule segment describes ordinary town life with start minute, duration, target location, and intent
- **THEN** it can run without explicit subtasks, completion tags, or custom policy fields
- **AND** the engine derives ordinary advancement from time and finalized action evidence

#### Scenario: Default policy is assigned

- **WHEN** a schedule segment is loaded or generated without an explicit completion policy
- **THEN** the town engine treats it as `first_matching_action`
- **AND** existing scenario files remain loadable

#### Scenario: Occupy until segment end

- **WHEN** a segment uses `occupy_until_segment_end`
- **AND** a matching action finalizes before the segment end minute
- **THEN** the town engine records the segment as satisfied
- **AND** it does not mark the segment complete until the segment end minute unless an explicit override is allowed by policy

#### Scenario: Minimum matching actions

- **WHEN** a segment uses `min_matching_actions`
- **AND** fewer than the configured number of matching actions have finalized
- **THEN** the town engine keeps the segment active
- **AND** it marks the segment complete only after the configured count is reached and the last matching action has finalized

#### Scenario: Explicit policy preserves completion tool behavior

- **WHEN** a segment uses `explicit`
- **THEN** the town engine does not auto-complete it from matching action evidence alone
- **AND** a valid completion tool call may complete the segment

### Requirement: Schedule completion tools are exceptional compatibility tools

The town engine SHALL keep schedule completion tools available for compatibility and exceptional policies, but normal schedule execution SHALL NOT depend on the NPC calling a completion tool.

#### Scenario: Normal prompt does not require completion tool

- **WHEN** the engine builds an action context for a segment that can auto-complete
- **THEN** the context asks the NPC to choose a concrete world action
- **AND** it does not require the NPC to call `complete_current_schedule` as the normal success path

#### Scenario: Prompt policy presents current situation rather than state mutation

- **WHEN** the engine builds a normal action-selection context
- **THEN** the context includes persona, current time, current location, current schedule intent, visible NPCs, visible objects, exits, affordances, relevant memory, and anti-repeat constraints
- **AND** it does not present schedule completion as the ordinary next action for non-explicit segments

#### Scenario: Completion tool remains valid for explicit policy

- **WHEN** a segment uses `explicit`
- **AND** the NPC calls the completion tool with sufficient location or action evidence
- **THEN** the town engine marks the segment complete

### Requirement: Reflection and conversation remain side effects of town life

The town engine SHALL keep reflection, relationship cues, and conversations as
world-owned side effects that can influence future context, without making them
alternate control paths for ordinary action finalization or schedule advancement.

#### Scenario: Reflection evidence follows completed world events

- **WHEN** a finalized action, completed schedule, urgent event, or conversation produces reflection evidence
- **THEN** the engine records that evidence for future reflection or memory context
- **AND** recording the evidence does not itself complete unrelated schedule segments

#### Scenario: Conversation summary influences future context only

- **WHEN** a conversation closes and the engine stores summaries, impressions, cooldowns, or relationship cues
- **THEN** later prompts may include those cues
- **AND** the closed conversation advances schedule state only if the conversation action itself satisfies the current schedule policy

### Requirement: Replay records automatic schedule completion evidence

The town engine SHALL include replay and diagnostic evidence for automatically completed schedule segments.

#### Scenario: Auto-completion is visible in replay

- **WHEN** the engine automatically completes a segment from finalized action evidence
- **THEN** replay or diagnostics include the resident id, segment start, segment intent, completion policy, matched action id or equivalent source reference, matched action type, action end minute, and completion reason

#### Scenario: Viewer can distinguish explicit and automatic completion

- **WHEN** a replay read model includes schedule completion events
- **THEN** automatic completion and explicit completion are distinguishable by completion type

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
