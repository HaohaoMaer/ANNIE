## ADDED Requirements

### Requirement: NPC layer exposes a readable stateless facade

The NPC Agent layer SHALL organize its public execution path so that `NPCAgent.run(context)` remains a stateless facade over graph selection, run setup, graph execution, and response projection.

#### Scenario: Agent run uses only current context for per-run data

- **WHEN** `NPCAgent.run()` is invoked for any registered graph
- **THEN** NPC identity, prompt text, memory interface, tools, skills, route or graph selection, and input event come from the current `AgentContext`
- **AND** the facade does not read per-NPC world state from module globals, cached graph objects, or previous runs

#### Scenario: Agent facade reveals high-level flow

- **WHEN** a maintainer inspects the NPC Agent entrypoint
- **THEN** the implementation makes graph resolution, runtime creation, graph invocation, and `AgentResponse` projection identifiable as separate steps
- **AND** runner-specific LangGraph wiring is not embedded directly in the public facade in a way that obscures the execution model

### Requirement: Graph runner implementation remains business-agnostic

The NPC Agent layer SHALL implement registered graph runners using generic cognitive categories and SHALL NOT encode world-engine business domains in runner, node, or runtime organization.

#### Scenario: Runner modules use generic concepts

- **WHEN** graph runner code is organized or refactored
- **THEN** module names, node labels, helper names, and comments describe generic NPC functions such as graph resolution, planning, action execution, dialogue, structured output, reflection, tool dispatch, runtime, or response projection
- **AND** they do not encode schedules, clues, suspects, towns, war-game phases, NPC YAML fields, or other concrete world-engine business concepts

#### Scenario: World-engine responsibilities stay outside NPC layer

- **WHEN** the NPC layer executes an action-capable graph
- **THEN** concrete side effects still occur only through world-engine-owned tool implementations
- **AND** the NPC layer does not parse NPC YAML, import `chromadb`, persist history, own world state, validate business schemas, or decide scene progression

### Requirement: Run runtime has explicit ownership

The NPC Agent layer SHALL make run-local mutable execution data explicit enough that tool dispatch, skill activation, memory update declaration, and response projection have a clear owner.

#### Scenario: Runtime fields are centrally initialized

- **WHEN** an action or dialogue graph creates run-local runtime data
- **THEN** fields such as tool registry, skill runtime, recall dedup state, inner thoughts, memory updates, action results, tool statuses, skill frames, and active loop messages are initialized or documented through one NPC-owned runtime boundary
- **AND** tools continue to receive the same mutable runtime data needed by `ToolContext`

#### Scenario: Skill tool frames are task-local

- **WHEN** a skill activation temporarily exposes extra tools during an executor loop
- **THEN** those tool frames are cleaned up before the task loop returns
- **AND** the cleanup path remains visible in the action execution runtime lifecycle

### Requirement: Response projection is separated from world arbitration

The NPC Agent layer SHALL project completed graph state into `AgentResponse` fields without performing world-engine business arbitration or persistence.

#### Scenario: Action response projection uses tool statuses

- **WHEN** an action graph completes after tool execution
- **THEN** response projection includes bounded tool statuses and dialogue text derived from executor results
- **AND** it does not create a separate declarative world-action execution path

#### Scenario: Non-action response projection stays route-specific

- **WHEN** a dialogue, structured JSON, or reflection graph completes
- **THEN** response projection writes the route-specific output field
- **AND** it does not run unrelated action planner, action executor, or durable memory persistence logic
