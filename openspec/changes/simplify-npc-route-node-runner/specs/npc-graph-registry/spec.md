## MODIFIED Requirements

### Requirement: NPC Agent owns the route registry

The NPC Agent layer SHALL own the registry of legal cognitive route identifiers and the route specifications they resolve to.

#### Scenario: Registered route ids resolve inside NPC layer

- **WHEN** `NPCAgent.run()` resolves a `route_id`
- **THEN** it looks up a registry entry inside `src/annie/npc/`
- **AND** the entry resolves to an NPC-owned route specification and route policy
- **AND** route execution does not require the world engine to provide graph structure

#### Scenario: World engine cannot provide graph structure

- **WHEN** a world engine constructs `AgentContext`
- **THEN** it may provide a `route_id`
- **AND** it must not provide nodes, node names to execute, edges, route specs, LangGraph nodes, builder functions, compiled graphs, or dynamic graph specs

#### Scenario: Registry entries remain lightweight

- **WHEN** the NPC layer registers an initial cognitive route identifier
- **THEN** the registry entry contains a stable identifier, route kind, response kind, default route policy, and route spec reference
- **AND** it does not require LangGraph builders as the core execution mechanism

### Requirement: Graph execution remains stateless across runs

The NPC Agent layer SHALL keep per-run and per-NPC data out of the route registry, route registry, and any run-neutral caches.

#### Scenario: Per-run data enters through context

- **WHEN** the same registered route id or route spec is used for multiple NPCs or multiple runs
- **THEN** NPC identity, memory interface, tools, prompt text, evidence, and input event come from the current `AgentContext`
- **AND** no previous run's business state is read from the route registry or route specification

#### Scenario: Route specs are run-neutral

- **WHEN** the NPC layer caches or reuses route specifications
- **THEN** cached route objects contain only run-neutral node identifiers, edge declarations, route policy, and response classification
- **AND** they do not cache world state, memory recall results, profile data, tool runtime state, or previous responses

### Requirement: Route registry entries declare node composition

The NPC Agent route registry SHALL register each route identifier with enough metadata to describe its generic route composition and policy classification.

#### Scenario: Registry entry includes route composition metadata

- **WHEN** the NPC layer registers a route identifier
- **THEN** the registry entry includes a stable route identifier, route or policy kind, response kind, and route spec reference
- **AND** the referenced route declares bounded node identifiers and conditional edges using generic NPC cognitive categories rather than business-domain names

#### Scenario: Route specification remains NPC-owned

- **WHEN** `NPCAgent.run()` resolves a registered route identifier
- **THEN** the route specification and node transition rules come from the NPC layer registry
- **AND** the world engine cannot override the node composition or conditional edges through `AgentContext`
