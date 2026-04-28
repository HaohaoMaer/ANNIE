## ADDED Requirements

### Requirement: Concrete world engines may provide replayable multi-NPC simulation

A concrete world engine MAY implement replayable multi-NPC simulation, but any such implementation MUST keep simulation state and business rules in the world-engine layer and expose NPC-visible state only through `AgentContext`, memory interfaces, and injected tools.

#### Scenario: Simulation state remains world-owned
- **WHEN** a concrete engine tracks time, locations, schedules, occupants, local events, or replay snapshots
- **THEN** those structures are owned by the world-engine layer
- **AND** the NPC Agent layer remains stateless across runs

#### Scenario: Concrete engine injects action tools
- **WHEN** a concrete engine supports business actions such as moving, observing, speaking, interacting, or waiting
- **THEN** the actions are exposed through `AgentContext.tools` or the agreed `tools_for(npc_id)` path
- **AND** the engine arbitrates every resulting world mutation

#### Scenario: Replay output is engine-owned
- **WHEN** a concrete engine emits replay/checkpoint artifacts
- **THEN** replay serialization is implemented in the concrete engine or world-engine support modules
- **AND** NPC Agent code does not depend on replay schemas
