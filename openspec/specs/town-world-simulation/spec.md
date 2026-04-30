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

