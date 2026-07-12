## ADDED Requirements

### Requirement: Generative-scale semantic town scenario
The system SHALL provide a project-owned semantic town scenario that reaches
Generative Agents-style population scale while using ANNIE scenario content
instead of importing external runtime objects.

#### Scenario: Scenario has generative-scale resident count
- **WHEN** the scaled town scenario is loaded
- **THEN** it contains at least 25 residents
- **AND** every resident has an id, display name, starting location, home
  location, sleep location, persona fields, relationship data, and at least one
  memory seed or schedule seed

#### Scenario: Scenario uses ANNIE-owned content
- **WHEN** the scaled town scenario defines residents, places, objects, and
  activities
- **THEN** the definitions use ANNIE scenario YAML fields
- **AND** loading does not require GenerativeAgentsCN classes, tile files,
  sprite metadata, or per-resident LLM configuration

### Requirement: Generative-scale location coverage
The scaled town scenario SHALL include a district-level semantic location graph
that covers the everyday functions needed for believable small-town routines.

#### Scenario: Scenario covers everyday town places
- **WHEN** the scaled town scenario is loaded
- **THEN** it contains at least 20 semantic locations
- **AND** those locations include resident homes, food/social venues, workplaces,
  shops, public-service locations, outdoor gathering places, and event locations

#### Scenario: Scenario routes are semantically reachable
- **WHEN** scenario validation checks the scaled town location graph
- **THEN** every resident home can reach the primary public hub through exits
- **AND** every scheduled location for every resident is known and reachable
  through the semantic graph

### Requirement: Generative-scale social graph
The scaled town scenario SHALL define enough resident relationships and shared
threads to exercise local perception, conversations, planning evidence, and
memory retrieval at scale.

#### Scenario: Residents have relationship coverage
- **WHEN** the scaled town scenario is loaded
- **THEN** each resident has at least two named relationships to other residents
- **AND** relationship targets reference residents that exist in the same scenario

#### Scenario: Scenario seeds shared social threads
- **WHEN** the runtime applies memory seeds for the scaled town scenario
- **THEN** memory seeds include shared event, work, family, friendship, or civic
  threads that can influence later planning or conversations
- **AND** seed metadata is traceable by resident id and scenario thread

### Requirement: Generative-scale schedule seeds
The scaled town scenario SHALL provide initial schedule structure sufficient to
exercise multi-resident movement, work, social encounters, and day lifecycle
behavior before relying on generated future-day plans.

#### Scenario: Resident schedules cover core daily routines
- **WHEN** the scaled town scenario is loaded
- **THEN** residents have initial schedule seeds that include home/lifecycle
  periods, work or study periods, and at least one public or social destination
  for a representative validation cohort

#### Scenario: Schedule seeds remain repairable
- **WHEN** scenario validation encounters a generated or authored schedule in
  the scaled town scenario
- **THEN** invalid locations, overlapping segments, or unreachable first segments
  are reported clearly before the run is treated as valid
