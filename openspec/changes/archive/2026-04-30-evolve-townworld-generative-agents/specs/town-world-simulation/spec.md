## ADDED Requirements

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
