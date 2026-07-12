## MODIFIED Requirements

### Requirement: Action route supports composable world tool execution

The action route SHALL support world-action execution through node-composed graphs with an action execution node as the core side-effect request point and planner/reflector/output nodes selected by graph policy, including memory tools and world-engine injected tools.

#### Scenario: World action tools are available

- **WHEN** a world engine provides movement, interaction, wait, or other action tools in an action-route context
- **THEN** the NPC Agent exposes those tools to the action execution node according to graph tool policy
- **AND** concrete tool execution is performed by world-engine-owned tool implementations
- **AND** each tool call returns an explicit world-engine tool execution status

#### Scenario: Simple action can execute without pre-planning

- **WHEN** an action-route context is simple enough for one bounded execution attempt
- **THEN** the NPC Agent may route directly to the action execution node without requiring planner output first
- **AND** the action execution node receives the world context, memory context, todo context, available skills, and action tools needed for that attempt

#### Scenario: Planner is run-local micro planning

- **WHEN** an action-route context is complex, explicitly asks for task decomposition, or retries after empty/failed executor output
- **THEN** the NPC Agent may invoke a planning node before the action execution node
- **AND** planner output is limited to temporary tasks for the current action run
- **AND** planner output is not treated as a persistent world plan, schedule, or future route sequence

#### Scenario: Durable reflection is route-owned

- **WHEN** an action-route execution finishes
- **THEN** the NPC Agent does not need to run durable reflection unless action graph policy explicitly selects a reflection node
- **AND** long-term distilled reflection should be requested through the reflection route when the world engine decides reflection is due

#### Scenario: Action route returns tool statuses not declarative intents

- **WHEN** an action-route graph completes after calling world-engine tools
- **THEN** `AgentResponse` includes the resulting tool execution statuses
- **AND** it MUST NOT require the world engine to interpret declarative action intents as a separate execution mechanism

