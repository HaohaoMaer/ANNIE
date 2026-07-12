## ADDED Requirements

### Requirement: Graph registry entries declare node composition

The NPC Agent graph registry SHALL register each graph with enough metadata to describe its generic node composition and policy classification.

#### Scenario: Registry entry includes composition metadata

- **WHEN** the NPC layer registers a graph
- **THEN** the registry entry includes a stable graph identifier, route or policy kind, graph builder, response kind, and bounded node composition labels
- **AND** the node composition labels are generic NPC cognitive categories rather than business-domain names

#### Scenario: Builder remains NPC-owned

- **WHEN** `NPCAgent.run()` resolves a registered graph
- **THEN** the graph builder and node wiring come from the NPC layer registry
- **AND** the world engine cannot override the node composition through `AgentContext`

### Requirement: Registry validates node-composed graph policy

The NPC Agent layer SHALL validate that registered node-composed graphs have policy metadata sufficient to enforce tool availability before model invocation and tool dispatch.

#### Scenario: Action-capable graph declares action policy

- **WHEN** a graph includes an action tool-use node
- **THEN** its registry entry declares an action-capable route or tool policy kind
- **AND** injected world tools are filtered by that policy before being bound or dispatched

#### Scenario: Output-only graph forbids action tools

- **WHEN** a graph is registered for structured output or reflection without an action node
- **THEN** action/world-mutation tools are not bound to that graph
- **AND** prompt text cannot make those tools dispatchable

