## MODIFIED Requirements

### Requirement: NPC graphs are composed from business-agnostic nodes

The NPC Agent layer SHALL compose registered route execution from NPC-owned capability nodes whose names and behavior describe generic cognitive functions, not concrete world-engine domains.

#### Scenario: Initial node categories are generic

- **WHEN** the NPC layer defines nodes for registered routes
- **THEN** each node belongs to a generic category such as preparation, memory context, planning, action execution, dialogue generation, structured output, projection, or reflection
- **AND** node names do not mention schedules, clues, suspects, factions, towns, war games, interrogation phases, or other concrete game concepts

#### Scenario: World engine does not provide nodes

- **WHEN** a world engine constructs `AgentContext`
- **THEN** it may select a registered `route_id`
- **AND** it MUST NOT provide nodes, node names to execute, edges, compiled graphs, builder functions, or dynamic graph specs

#### Scenario: LangGraph is not required for core route composition

- **WHEN** a core NPC route is registered
- **THEN** it may execute through the NPC-owned route runner instead of a LangGraph `StateGraph`
- **AND** LangGraph-specific builders are not required to understand the route's node order or conditional transitions

### Requirement: Output nodes project route state into AgentResponse

NPC response projection SHALL convert completed route state into stable `AgentResponse` fields without performing world-engine business validation or persistence.

#### Scenario: Structured output projection

- **WHEN** a structured-output route completes
- **THEN** response projection writes the generated structured-output text into the dedicated `AgentResponse` field
- **AND** the world engine remains responsible for parsing, schema validation, repair, retry, fallback, and persistence

#### Scenario: Reflection projection

- **WHEN** a reflection route completes
- **THEN** response projection writes the reflection candidate into `AgentResponse`
- **AND** the NPC Agent does not persist that reflection unless the world engine later writes it through `MemoryInterface`

#### Scenario: Action status projection

- **WHEN** an action route calls one or more world-engine tools
- **THEN** response projection includes the resulting tool execution statuses in `AgentResponse`
- **AND** it does not convert those statuses into declarative world-action intents

#### Scenario: Output-only marker nodes are unnecessary

- **WHEN** route execution reaches a completed route state
- **THEN** the NPC Agent may project the response outside node execution
- **AND** it does not require output-only route nodes whose sole behavior is recording debug path labels

### Requirement: Node execution is observably bounded

NPC route execution SHALL expose bounded node-level observability for tests and debugging without making full runner internals part of the stable API.

#### Scenario: Node path is reported

- **WHEN** a registered route completes
- **THEN** `AgentResponse` debug metadata includes the selected route identifier and bounded executed node path labels
- **AND** tests can assert that an expected node category was or was not executed

#### Scenario: Debug metadata omits unbounded internals

- **WHEN** route debug metadata is produced
- **THEN** it may include graph ID, route/policy kind, node labels, bound tool names, and tool execution status summaries
- **AND** it MUST NOT expose unbounded model messages, private memory contents, full prompt text, or full runner trace state as stable public API
