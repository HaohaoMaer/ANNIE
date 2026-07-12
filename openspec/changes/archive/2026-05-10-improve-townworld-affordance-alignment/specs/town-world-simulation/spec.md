## MODIFIED Requirements

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
