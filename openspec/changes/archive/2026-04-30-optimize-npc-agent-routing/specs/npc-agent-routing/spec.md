## ADDED Requirements

### Requirement: NPC Agent routes requests by execution intent

The NPC Agent layer SHALL support explicit execution routes so that different request types can use different graph paths while preserving the default world-action behavior.

#### Scenario: Route is a typed AgentContext field

- **WHEN** a world engine constructs an `AgentContext`
- **THEN** it may set a first-class route field to one of `action`, `dialogue`, `structured_json`, or `reflection`
- **AND** the route defaults to `action` when omitted
- **AND** route selection does not depend on parsing `input_event`, available tool names, or private business metadata

#### Scenario: Default action route

- **WHEN** a world engine calls `NPCAgent.run()` without specifying a route
- **THEN** the NPC Agent uses the existing world-action route
- **AND** the route can execute world tools
- **AND** planner and reflector behavior are optional action-route nodes selected by route policy rather than mandatory for every action run

#### Scenario: Explicit non-action route

- **WHEN** a world engine requests a non-action route
- **THEN** the NPC Agent selects the graph path for that route
- **AND** it does not run unrelated planner, executor, or reflector nodes

#### Scenario: Temporary direct-mode compatibility

- **WHEN** a legacy context includes `extra["npc_direct_mode"]` with value `json`, `dialogue`, or `reflection`
- **THEN** the NPC Agent maps that value to `structured_json`, `dialogue`, or `reflection` respectively
- **AND** the mapped route follows the same tool policy and output contract as an explicitly requested route
- **AND** this compatibility path is treated as temporary migration support

### Requirement: Action route supports composable world tool execution

The action route SHALL support world-action execution with executor as the core action node and planner/reflector as optional route-policy nodes, including memory tools and world-engine injected tools.

#### Scenario: World action tools are available

- **WHEN** a world engine provides movement, interaction, wait, or other action tools in an action-route context
- **THEN** the NPC Agent exposes those tools to the executor
- **AND** successful action tool calls are returned through `AgentResponse` or the existing tool result path for world-engine arbitration

#### Scenario: Simple action can execute without pre-planning

- **WHEN** an action-route context is simple enough for one bounded execution attempt
- **THEN** the NPC Agent may route directly to executor without requiring planner output first
- **AND** the executor receives the world context, memory context, todo context, available skills, and action tools needed for that attempt

#### Scenario: Planner is run-local micro planning

- **WHEN** an action-route context is complex, explicitly asks for task decomposition, or retries after empty/failed executor output
- **THEN** the NPC Agent may invoke planner before executor
- **AND** planner output is limited to temporary tasks for the current action run
- **AND** planner output is not treated as a persistent world plan, schedule, or future route sequence

#### Scenario: Durable reflection is route-owned

- **WHEN** an action-route execution finishes
- **THEN** the NPC Agent does not need to run durable reflection unless action route policy explicitly selects that node
- **AND** long-term distilled reflection should be requested through the reflection route when the world engine decides reflection is due

### Requirement: Dialogue route permits memory but forbids world side effects

The dialogue route SHALL allow the NPC to use memory-oriented tools for character consistency while preventing world-action side effects.

#### Scenario: Managed dialogue can use memory

- **WHEN** a managed dialogue route is executed
- **THEN** memory recall, literal memory grep, and inner-thought tools are available
- **AND** `use_skill` is not available in the initial dialogue route
- **AND** the route produces dialogue text as its primary output

#### Scenario: Managed dialogue cannot execute world actions

- **WHEN** a managed dialogue route is executed
- **THEN** world mutation tools such as movement, interaction, wait, schedule completion, speaking tools, and conversation-start tools are not exposed
- **AND** the route does not return world action requests

#### Scenario: Managed dialogue uses a small tool loop

- **WHEN** a managed dialogue route uses tools
- **THEN** the NPC Agent limits dialogue tool iterations separately from the action executor
- **AND** the limit is small enough to support memory lookup followed by an utterance without turning dialogue into a general action route

### Requirement: Structured JSON route produces validated structured output

The structured JSON route SHALL generate structured content without planner, world tools, or reflector execution.

#### Scenario: JSON route has no tools

- **WHEN** a structured JSON route is executed
- **THEN** no tools are exposed to the model
- **AND** the output is returned as structured-output text for the world engine to parse and validate

#### Scenario: JSON route does not own business schema validation

- **WHEN** a structured JSON route returns malformed or schema-invalid content
- **THEN** the NPC Agent returns the raw structured-output text
- **AND** the world engine decides whether to parse, repair, retry, fall back, or fail according to business policy

### Requirement: Reflection route is cognition-only

The reflection route SHALL generate distilled reflection content without world-action execution.

#### Scenario: Reflection route avoids action graph

- **WHEN** a reflection route is executed
- **THEN** the NPC Agent does not run the action planner or action executor
- **AND** no tools are exposed

#### Scenario: Reflection evidence is supplied by the world engine

- **WHEN** a reflection route needs facts, memory summaries, or execution evidence
- **THEN** the world engine provides that information explicitly in the route context
- **AND** the NPC Agent does not perform implicit pre-run memory recall for reflection

#### Scenario: Reflection route filters internal orchestration

- **WHEN** a reflection route produces output for long-term memory
- **THEN** the output must not include tool names, graph node names, route names, JSON field names, or other internal orchestration text
- **AND** the NPC Agent uses prompt constraints and post-processing or rejection to reduce orchestration leakage

### Requirement: Route tool policies are enforced structurally

The NPC Agent SHALL enforce route-specific tool availability before invoking the LLM using route allowlists.

#### Scenario: Route allowlist is applied before disabled tools

- **WHEN** a route is executed
- **THEN** the NPC Agent first limits tools to the route allowlist
- **AND** `disabled_tools` may only remove tools from that allowed set
- **AND** `disabled_tools` cannot make a forbidden tool available

#### Scenario: Prompt cannot override route tool policy

- **WHEN** a route forbids a class of tools
- **THEN** those tools are not bound or dispatchable for that route
- **AND** prompt text alone is not the only protection against misuse

#### Scenario: World-injected tools carry route metadata

- **WHEN** a world engine injects a tool into `AgentContext.tools`
- **THEN** the tool declares route metadata such as allowed routes or a kind that maps to allowed routes
- **AND** absent explicit metadata, injected tools default to action-only availability
- **AND** route filtering does not rely on matching business-specific tool names

### Requirement: Route execution is observable in tests

The NPC Agent SHALL expose enough route behavior for tests to verify which path and tool set were used.

#### Scenario: AgentResponse reports route and structured output

- **WHEN** any route completes
- **THEN** `AgentResponse` reports the route used for the run
- **AND** structured JSON route output is available through a dedicated structured-output response field rather than overloading dialogue text

#### Scenario: Test verifies route path

- **WHEN** a test runs a non-action route
- **THEN** it can assert that action planner/executor nodes were not invoked
- **AND** it can assert the bound tool names for that route

#### Scenario: Debug metadata is optional and bounded

- **WHEN** route debug metadata is enabled or produced for tests
- **THEN** it may include bounded diagnostics such as bound tool names
- **AND** it does not expose full internal graph traces as part of the stable public API
