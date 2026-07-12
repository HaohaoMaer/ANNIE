# town-replay-viewer Specification

## Purpose
TBD - created by archiving change make-townworld-watchable-replay. Update Purpose after archive.
## Requirements
### Requirement: Town replay read model
The system SHALL provide a versioned presentation read model for TownWorld runs that can be generated from a run manifest and its referenced replay, diagnostics, validation, and snapshot artifacts.

#### Scenario: Read model is generated from run manifest
- **WHEN** a caller provides a valid TownWorld run manifest
- **THEN** the system generates a JSON-compatible read model with run metadata, artifact provenance, locations, residents, timeline events, world frames, schedules, conversations, planning evidence, reflections, day summaries, lifecycle anomalies, and resume markers when present
- **AND** the read model does not require a live `TownWorldEngine` or retained `NPCAgent` instance

#### Scenario: Read model preserves source references
- **WHEN** the read model includes an action, schedule transition, reflection, anomaly, planning checkpoint, or resume boundary
- **THEN** the entry includes enough source reference information to trace it back to the originating replay, diagnostics, validation, or snapshot artifact when available

#### Scenario: Read model is stable across internal replay detail
- **WHEN** internal TownWorld diagnostics include additional backend-only fields
- **THEN** the read model keeps its documented presentation fields stable
- **AND** backend-only fields are omitted or placed under an explicit debug/source section

### Requirement: Watchable local replay viewer
The system SHALL provide a lightweight local viewer artifact that renders a TownWorld replay read model without requiring live LLM credentials or a running simulation.

#### Scenario: Viewer opens from generated run artifacts
- **WHEN** a TownWorld run has generated viewer artifacts
- **THEN** a user can open the viewer locally and inspect the run timeline, current town state, resident locations, actions, conversations, schedules, planning evidence, reflections, diagnostics, and lifecycle anomalies

#### Scenario: Viewer supports time navigation
- **WHEN** a user selects a timeline event or world frame in the viewer
- **THEN** the viewer displays the corresponding day, minute, residents grouped by location, each resident's current action, and each resident's active schedule segment when available

#### Scenario: Viewer separates story view from debug detail
- **WHEN** a replay event has both human-readable summary and detailed diagnostic metadata
- **THEN** the viewer shows the summary in the main timeline
- **AND** the detailed metadata remains available in an inspectable detail panel without overwhelming the primary view

### Requirement: Replay-oriented town demo scenario
The system SHALL include a project-owned TownWorld demo scenario intended to produce replay-worthy semantic behavior.

#### Scenario: Demo scenario has enough visible town density
- **WHEN** the demo scenario is loaded
- **THEN** it includes multiple residents, multiple semantic locations, home or sleep metadata for active residents, location-local objects, affordances, relationships, and memory seeds sufficient to produce visible action and conversation in replay

#### Scenario: Demo scenario uses ANNIE semantic content schema
- **WHEN** the demo scenario is validated or loaded
- **THEN** it uses the ANNIE TownWorld scenario schema
- **AND** it does not require GenerativeAgentsCN tile coordinates, sprites, portraits, or per-resident LLM configuration

#### Scenario: Demo scenario can run deterministically
- **WHEN** deterministic TownWorld validation runs against the demo scenario
- **THEN** the run can generate replay read-model and viewer artifacts without live LLM credentials

