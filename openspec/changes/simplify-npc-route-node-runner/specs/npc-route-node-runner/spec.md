## ADDED Requirements

### Requirement: NPC routes execute as route-local state machines

The NPC Agent layer SHALL execute each registered route through a route-local state machine made of an entry node, allowed nodes, allowed conditional edges, and exit nodes.

#### Scenario: Route declares complete transition boundary

- **WHEN** a maintainer inspects a registered route specification
- **THEN** the specification lists the route entry node, exit nodes, node set, and conditional edges for that route
- **AND** the route does not depend on globally active edges that are invisible from the route specification

#### Scenario: Conditional edge selects next node

- **WHEN** a route node finishes execution
- **THEN** the runner evaluates only the outgoing conditional edges declared by the current route for that source node
- **AND** it transitions to the first matching target node according to deterministic route edge order

#### Scenario: Route cannot leave its declared subgraph

- **WHEN** a conditional edge target is not in the current route's allowed node set
- **THEN** the NPC Agent rejects the route definition or fails before executing the invalid transition
- **AND** it does not silently execute a capability outside the selected route boundary

### Requirement: NPC nodes are reusable capability units

The NPC Agent layer SHALL define nodes as business-agnostic capability units that can be reused by multiple routes without carrying route-specific edge policy.

#### Scenario: Node does not decide global route flow

- **WHEN** a node completes
- **THEN** it may update run-local state with outputs, status, or transition facts
- **AND** it does not directly select a target node outside the route edge resolver

#### Scenario: Shared node implementation can appear in multiple routes

- **WHEN** two routes need the same generic capability such as memory context loading or structured output generation
- **THEN** they may reference the same node implementation
- **AND** each route still declares its own edges to and from that node

#### Scenario: Business domains remain outside node names

- **WHEN** the NPC layer registers node identifiers
- **THEN** node names describe generic capabilities such as preparation, memory context, planning, action execution, dialogue generation, reflection generation, structured output, or projection
- **AND** they do not encode schedules, clues, suspects, towns, war-game phases, NPC YAML fields, or other world-engine business domains

### Requirement: NPC route runner is a thin Python control loop

The NPC Agent layer SHALL provide an NPC-owned route runner that executes route nodes with plain Python control flow and does not require LangGraph for core route orchestration.

#### Scenario: Runner records actual node path

- **WHEN** a route completes
- **THEN** the runner records the bounded list of executed node identifiers in run-local debug state
- **AND** response projection may include that path for tests and diagnostics

#### Scenario: Runner stops at route exit

- **WHEN** the current node is one of the selected route's exit nodes
- **THEN** the runner stops executing nodes and returns the completed run state for response projection

#### Scenario: Runner fails on missing transition

- **WHEN** a non-exit node completes and no declared outgoing edge condition matches
- **THEN** the NPC Agent fails with a clear route execution error
- **AND** it does not guess a fallback node from another route

### Requirement: Edge conditions are route policy, not reusable graph structure

The NPC Agent layer SHALL keep concrete edges route-local, while allowing small condition functions to be shared when they are generic and business-agnostic.

#### Scenario: Edges are not globally active

- **WHEN** one route declares an edge from an execution node back to a planning node for replanning
- **THEN** that edge is active only for that route
- **AND** another route using either node does not inherit the replanning edge unless it explicitly declares it

#### Scenario: Route readability takes precedence over edge de-duplication

- **WHEN** several routes need a common transition pattern
- **THEN** each route still declares its own concrete edges
- **AND** shared edge fragments are not required to understand a route's complete state machine

### Requirement: Obsolete internal compatibility code is removed

The NPC Agent layer SHALL remove old internal graph, builder, runner, and marker-node implementations once their behavior is replaced by route-runner execution.

#### Scenario: External compatibility does not preserve internal duplicate paths

- **WHEN** an external compatibility selector such as an existing `route_id` remains supported
- **THEN** it resolves to the new route specification model
- **AND** the NPC layer does not keep a parallel old route builder, direct runner, or deprecated wrapper solely to preserve the previous internal structure

#### Scenario: Removed concepts do not remain as dead code

- **WHEN** a LangGraph-specific builder, output-only marker node, or legacy direct route-local state machine no longer owns unique behavior
- **THEN** the implementation deletes that code
- **AND** tests are updated to assert the new route-runner behavior rather than depending on obsolete internal paths
