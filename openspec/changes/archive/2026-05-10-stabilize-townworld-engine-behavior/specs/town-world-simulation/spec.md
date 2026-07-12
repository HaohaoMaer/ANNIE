## MODIFIED Requirements

### Requirement: Town engine deterministically routes resident movement
The TownWorld engine SHALL treat `move_to(destination_id)` as a request to advance
one step toward the requested destination.

#### Scenario: Indirect destination advances one hop
- **WHEN** a resident requests a reachable but non-direct destination
- **THEN** the engine moves the resident to the shortest-path next hop
- **AND** the action succeeds with requested destination, actual destination, route,
  and auto-routing facts

#### Scenario: Unknown or unreachable destination still fails
- **WHEN** a resident requests an unknown or unreachable destination
- **THEN** the action fails with the existing failure reason
- **AND** the resident location is unchanged

### Requirement: Town engine exposes one NPC dialogue entry point
TownWorld NPC contexts SHALL expose `talk_to` as the dialogue action tool and SHALL
NOT expose `speak_to` or `start_conversation` as NPC-facing tools.

#### Scenario: Empty managed conversation fails
- **WHEN** a managed conversation produces an empty first turn twice
- **THEN** the `talk_to` action fails with reason `empty_conversation`
- **AND** no conversation cooldown or schedule completion evidence is written

### Requirement: Town schedule completion uses one ledger
TownWorld schedule completion SHALL be represented by `completed_schedule_segments`
with completion types `explicit_request`, `inferred_action_match`, `repair`, and
`day_finalize_missed`.

#### Scenario: Explicit completion is validated
- **WHEN** a resident calls `complete_current_schedule`
- **THEN** the engine accepts only when the current or recoverable segment has
  location or recent action evidence
- **AND** accepted or rejected results include a clear reason

#### Scenario: Empty conversation is not completion evidence
- **WHEN** a conversation closes or fails because no one said anything
- **THEN** the engine does not infer schedule completion from that conversation
