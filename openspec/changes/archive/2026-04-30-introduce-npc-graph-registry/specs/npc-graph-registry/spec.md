## ADDED Requirements

### Requirement: NPC Agent exposes graph-id dispatch

The NPC Agent layer SHALL expose a first-class `graph_id` dispatch contract on `AgentContext` for selecting a pre-registered cognitive graph.

#### Scenario: Explicit graph selection

- **WHEN** a world engine constructs an `AgentContext` with a registered `graph_id`
- **THEN** `NPCAgent.run()` executes the graph registered for that identifier
- **AND** graph selection does not depend on parsing `input_event`, tool names, or business metadata

#### Scenario: Unknown graph is rejected

- **WHEN** a world engine requests a `graph_id` that is not registered by the NPC layer
- **THEN** `NPCAgent.run()` fails with a clear graph selection error
- **AND** it does not fall back to a different graph silently

#### Scenario: Default graph selection

- **WHEN** a world engine omits `graph_id`, `route`, and legacy direct-mode flags
- **THEN** `NPCAgent.run()` uses the default action graph
- **AND** the default preserves existing world-action behavior

### Requirement: NPC Agent owns the graph registry

The NPC Agent layer SHALL own the registry of legal cognitive graphs and their construction.

#### Scenario: Registered graphs are built inside NPC layer

- **WHEN** `NPCAgent.run()` resolves a `graph_id`
- **THEN** it looks up a graph entry registered inside `src/annie/npc/`
- **AND** it builds or fetches the corresponding LangGraph graph without consulting world-engine graph definitions

#### Scenario: World engine cannot provide graph structure

- **WHEN** a world engine constructs an `AgentContext`
- **THEN** it may provide a `graph_id`
- **AND** it must not provide LangGraph nodes, edges, builder functions, compiled graphs, or dynamic graph specs

#### Scenario: Registry entries remain lightweight

- **WHEN** the NPC layer registers an initial cognitive graph
- **THEN** the registry entry contains a stable identifier, graph builder, and minimal policy metadata
- **AND** it does not require a new declarative graph DSL for nodes and edges

### Requirement: Graph identifiers are business-agnostic

Registered graph identifiers SHALL describe generic cognitive or output flow and SHALL NOT encode concrete world-engine business domains.

#### Scenario: Generic graph names

- **WHEN** the NPC layer defines graph identifiers for action, dialogue, structured output, or reflection
- **THEN** the identifiers describe generic cognitive flow such as action execution, memory-augmented dialogue, structured output, or evidence-based reflection
- **AND** they do not mention schedules, clues, suspects, factions, towns, war games, interrogation phases, or other concrete game concepts

#### Scenario: Business purpose stays in context

- **WHEN** a world engine needs a business-specific result such as a schedule draft, clue analysis, or faction order
- **THEN** it selects a generic graph identifier
- **AND** it provides the business-specific prompt text, evidence, tools, or output requirements through `AgentContext`

### Requirement: Route compatibility maps to graph identifiers

The NPC Agent layer SHALL provide temporary compatibility mappings from existing route-based dispatch inputs to default graph identifiers.

#### Scenario: Route maps to graph

- **WHEN** a world engine provides `AgentContext.route` but omits `graph_id`
- **THEN** `NPCAgent.run()` maps that route to the corresponding default graph identifier
- **AND** it executes the mapped graph through the graph registry

#### Scenario: Graph id takes precedence

- **WHEN** a world engine provides both `graph_id` and `route`
- **THEN** `NPCAgent.run()` selects the explicit `graph_id`
- **AND** debug metadata records the selected graph identifier and route-kind classification

#### Scenario: Legacy direct mode maps to graph

- **WHEN** an existing integration still provides legacy `extra["npc_direct_mode"]`
- **THEN** `NPCAgent.run()` maps the direct-mode value to a default graph identifier during the migration period
- **AND** the mapped execution follows the same tool and output policy as explicit graph selection

### Requirement: Graph policy controls tool availability

Each registered graph SHALL carry or derive policy metadata sufficient to enforce tool availability before LLM invocation and tool dispatch.

#### Scenario: Graph policy filters tools

- **WHEN** a graph is selected
- **THEN** the NPC Agent applies that graph's tool policy before binding tools to the LLM
- **AND** forbidden tools are not dispatchable even if the model or a test attempts to call them by name

#### Scenario: Disabled tools only narrow graph policy

- **WHEN** `disabled_tools` is present in `AgentContext`
- **THEN** the NPC Agent removes matching tools after applying graph policy
- **AND** `disabled_tools` never grants a tool forbidden by the selected graph

#### Scenario: World-injected tools remain policy-bound

- **WHEN** a world engine injects tools into `AgentContext.tools`
- **THEN** those tools are exposed only if their metadata permits the selected graph's policy classification
- **AND** graph filtering does not rely on matching business-specific tool names

### Requirement: Graph execution is observable

The NPC Agent layer SHALL expose bounded observability for graph execution without making full internal traces part of the stable public API.

#### Scenario: Response reports selected graph

- **WHEN** any graph completes
- **THEN** `AgentResponse` or its debug metadata reports the selected graph identifier
- **AND** tests can assert which graph was selected

#### Scenario: Debug metadata includes path and tools

- **WHEN** graph debug metadata is enabled or produced for tests
- **THEN** it includes bounded information such as graph identifier, route-kind classification, node path, and bound tool names
- **AND** it does not expose unbounded model messages, private memory contents, or full internal traces as stable public API

### Requirement: Graph execution remains stateless across runs

The NPC Agent layer SHALL keep per-run and per-NPC data out of the graph registry and compiled graph cache.

#### Scenario: Per-run data enters through context

- **WHEN** the same registered graph is used for multiple NPCs or multiple runs
- **THEN** NPC identity, memory interface, tools, prompt text, evidence, and input event come from the current `AgentContext`
- **AND** no previous run's business state is read from the graph registry

#### Scenario: Compiled graph cache is run-neutral

- **WHEN** the NPC layer caches compiled graphs
- **THEN** cached graph objects contain only run-neutral graph wiring
- **AND** they do not cache world state, memory recall results, profile data, tool runtime state, or previous responses
