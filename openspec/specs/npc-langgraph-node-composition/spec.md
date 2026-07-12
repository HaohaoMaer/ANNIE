# npc-langgraph-node-composition Specification

## Purpose
TBD - created by archiving change modularize-npc-langgraph-tools. Update Purpose after archive.
## Requirements
### Requirement: NPC graphs are composed from business-agnostic nodes

The NPC Agent layer SHALL compose registered LangGraph graphs from NPC-owned nodes whose names and behavior describe generic cognitive functions, not concrete world-engine domains.

#### Scenario: Initial node categories are generic

- **WHEN** the NPC layer defines nodes for registered routes
- **THEN** each node belongs to a generic category such as `planning`, `memory`, `action`, `output`, or `reflection`
- **AND** node names do not mention schedules, clues, suspects, factions, towns, war games, interrogation phases, or other concrete game concepts

#### Scenario: World engine does not provide nodes

- **WHEN** a world engine constructs `AgentContext`
- **THEN** it may select a registered `route_id`
- **AND** it MUST NOT provide LangGraph nodes, node names to execute, edges, compiled graphs, builder functions, or dynamic graph specs

### Requirement: NPC nodes use a shared per-run route state

NPC graph nodes SHALL exchange per-run information through an NPC-owned route state object derived from the current `AgentContext`.

#### Scenario: Per-run data enters through route state

- **WHEN** a registered route runs for an NPC
- **THEN** the initial route state is built from the current `AgentContext`
- **AND** NPC identity, memory interface, tools, prompt text, evidence, output requirements, and input event are not read from registry-level mutable state

#### Scenario: Node state is run-local

- **WHEN** the same node is used by multiple graphs or multiple NPC runs
- **THEN** the node does not retain world state, memory recall results, tool runtime state, or previous responses across runs

### Requirement: Output nodes project route state into AgentResponse

NPC output nodes SHALL convert route state into stable `AgentResponse` fields without performing world-engine business validation or persistence.

#### Scenario: Structured output projection

- **WHEN** a structured-output graph completes
- **THEN** an output node writes the generated structured-output text into the dedicated `AgentResponse` field
- **AND** the world engine remains responsible for parsing, schema validation, repair, retry, fallback, and persistence

#### Scenario: Reflection projection

- **WHEN** a reflection graph completes
- **THEN** an output node writes the reflection candidate into `AgentResponse`
- **AND** the NPC Agent does not persist that reflection unless the world engine later writes it through `MemoryInterface`

#### Scenario: Action status projection

- **WHEN** an action graph calls one or more world-engine tools
- **THEN** an output node includes the resulting tool execution statuses in `AgentResponse`
- **AND** it does not convert those statuses into declarative world-action intents

### Requirement: Node execution is observably bounded

NPC route execution SHALL expose bounded node-level observability for tests and debugging without making full LangGraph traces part of the stable API.

#### Scenario: Node path is reported

- **WHEN** a registered route completes
- **THEN** `AgentResponse` debug metadata includes the selected route identifier and bounded node path labels
- **AND** tests can assert that an expected node category was or was not executed

#### Scenario: Debug metadata omits unbounded internals

- **WHEN** route debug metadata is produced
- **THEN** it may include graph ID, route/policy kind, node labels, bound tool names, and tool execution status summaries
- **AND** it MUST NOT expose unbounded model messages, private memory contents, full prompt text, or full LangGraph trace state as stable public API

