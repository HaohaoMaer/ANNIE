## ADDED Requirements

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
