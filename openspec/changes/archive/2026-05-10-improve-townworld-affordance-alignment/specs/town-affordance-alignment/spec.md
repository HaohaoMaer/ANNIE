## ADDED Requirements

### Requirement: Town affordance matching supports executable semantic variants
The town engine SHALL match affordance ids and aliases case-insensitively and SHALL accept supported natural-language object interaction intents only when they match the object's declared affordances.

#### Scenario: Case-insensitive affordance execution
- **WHEN** a resident uses `use_affordance` with an affordance id or alias whose casing differs from the declared affordance
- **THEN** the engine executes the declared affordance and records the canonical affordance id in action facts

#### Scenario: Supported natural-language intent executes
- **WHEN** a resident uses `interact_with` on an object with affordances and the intent matches an affordance id, label, alias, description, or event type
- **THEN** the engine records a successful interaction instead of returning `unsupported_affordance`

#### Scenario: Unsupported intent gives suggestions
- **WHEN** a resident uses `interact_with` on an object with affordances and the intent does not match
- **THEN** the engine rejects the action without writing a town event
- **AND** the failed action facts include `available_affordances` and up to three `suggested_affordances`

### Requirement: Town affordance targets can be discovered by need
The town engine SHALL expose a read-only `find_affordance_targets(query, location_id?)` town tool that searches semantic locations, objects, and declared affordances.

#### Scenario: Delivery target discovery
- **WHEN** a resident searches for `deliver pastries`
- **THEN** the result includes `riverside_cafe` and `cafe_counter_scale` with the matching delivery affordance
- **AND** the result includes a travel hint from the resident's current location when available

#### Scenario: Location-scoped target discovery
- **WHEN** a resident searches for affordances with `location_id` set
- **THEN** results are limited to that location and its local objects

### Requirement: Schedule completion tags guide inferred completion
Town schedule segments SHALL support optional `completion_tags` that contribute to world-owned inferred completion decisions.

#### Scenario: Completion tags are optional
- **WHEN** scenario YAML or snapshots omit `completion_tags`
- **THEN** the loader and persistence layer preserve backward compatibility by using an empty list

#### Scenario: Action evidence satisfies completion tags
- **WHEN** a successful town action at the segment location contains an affordance id, event type, target id, note, alias, or intent matching a segment completion tag
- **THEN** the engine can mark the segment complete with inferred completion metadata

#### Scenario: Rest completion uses lifecycle evidence
- **WHEN** a resident waits or uses a rest affordance at home or sleep location during a sleep/rest segment
- **THEN** the engine can infer completion without requiring table interaction
