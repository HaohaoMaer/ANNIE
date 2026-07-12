## MODIFIED Requirements

### Requirement: NPC Agent routes requests by execution intent

The NPC Agent layer SHALL support explicit execution routes so that different request types can use different route-local state machines while preserving the default world-action behavior.

#### Scenario: Route is a typed AgentContext field

- **WHEN** a world engine constructs an `AgentContext`
- **THEN** it may set a first-class route field to one of `action`, `dialogue`, `structured_json`, or `reflection`
- **AND** the route defaults to `action` when omitted
- **AND** route selection does not depend on parsing `input_event`, available tool names, or private business metadata

#### Scenario: Default action route

- **WHEN** a world engine calls `NPCAgent.run()` without specifying a route or route identifier
- **THEN** the NPC Agent uses the existing world-action route
- **AND** the route can execute world tools
- **AND** planner and reflection behavior are optional route capabilities selected by route policy rather than mandatory for every action run

#### Scenario: Explicit non-action route

- **WHEN** a world engine requests a non-action route
- **THEN** the NPC Agent selects the route-local state machine for that route
- **AND** it does not run unrelated planner, executor, or reflection nodes

#### Scenario: Temporary obsolete direct-mode compatibility

- **WHEN** a legacy context includes `extra["npc_direct_mode"]` with value `json`, `dialogue`, or `reflection`
- **THEN** the NPC Agent maps that value to `structured_json`, `dialogue`, or `reflection` respectively
- **AND** the mapped route follows the same tool policy and output contract as an explicitly requested route
- **AND** this compatibility path is treated as temporary migration support

### Requirement: Action route supports composable world tool execution

The action route SHALL support world-action execution through route-local state machines with an action execution node as the core side-effect request point and planning/reflection/projection capabilities selected by route policy, including memory tools and world-engine injected tools.

#### Scenario: World action tools are available

- **WHEN** a world engine provides movement, interaction, wait, or other action tools in an action-route context
- **THEN** the NPC Agent exposes those tools to the action execution node according to route tool policy
- **AND** concrete tool execution is performed by world-engine-owned tool implementations
- **AND** each tool call returns an explicit world-engine tool execution status

#### Scenario: Simple action can execute without pre-planning

- **WHEN** an action-route context is simple enough for one bounded execution attempt
- **THEN** the NPC Agent may route directly to the action execution node without requiring planner output first
- **AND** the action execution node receives the world context, memory context, todo context, available skills, and action tools needed for that attempt

#### Scenario: Planner is run-local micro planning

- **WHEN** an action-route context is complex, explicitly asks for task decomposition, or retries after empty/failed executor output
- **THEN** the NPC Agent may invoke a planning node before the action execution node through a route-local conditional edge
- **AND** planner output is limited to temporary tasks for the current action run
- **AND** planner output is not treated as a persistent world plan, schedule, or future route sequence

#### Scenario: Replanning edge is route-local

- **WHEN** an action execution node marks state as needing replanning and retry policy allows another attempt
- **THEN** only an action route that explicitly declares an execution-to-planning edge may transition back to planning
- **AND** non-action routes or action variants without that edge do not inherit replanning behavior

#### Scenario: Durable reflection is route-owned

- **WHEN** an action-route execution finishes
- **THEN** the NPC Agent does not need to run durable reflection unless action route policy explicitly selects a reflection capability
- **AND** long-term distilled reflection should be requested through the reflection route when the world engine decides reflection is due

#### Scenario: Action route returns tool statuses not declarative intents

- **WHEN** an action-route execution completes after calling world-engine tools
- **THEN** `AgentResponse` includes the resulting tool execution statuses
- **AND** it MUST NOT require the world engine to interpret declarative action intents as a separate execution mechanism
