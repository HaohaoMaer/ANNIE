## MODIFIED Requirements

### Requirement: NPC layer exposes a readable stateless facade

The NPC Agent layer SHALL organize its public execution path so that `NPCAgent.run(context)` remains a stateless facade over route selection, route resolution, run setup, route execution, and response projection.

#### Scenario: Agent run uses only current context for per-run data

- **WHEN** `NPCAgent.run()` is invoked for any registered route identifier
- **THEN** NPC identity, prompt text, memory interface, tools, skills, route or route selection, and input event come from the current `AgentContext`
- **AND** the facade does not read per-NPC world state from module globals, cached route objects, route registry data, or previous runs

#### Scenario: Agent facade reveals high-level flow

- **WHEN** a maintainer inspects the NPC Agent entrypoint
- **THEN** the implementation makes graph resolution, route spec resolution, runtime creation, route node execution, and `AgentResponse` projection identifiable as separate steps
- **AND** runner-specific orchestration is not embedded directly in the public facade in a way that obscures the execution model

#### Scenario: Core execution does not require LangGraph

- **WHEN** a registered core NPC route is executed
- **THEN** the NPC Agent may execute it through the NPC-owned route runner
- **AND** LangGraph remains an optional implementation detail rather than a required public architecture boundary

### Requirement: Graph runner implementation remains business-agnostic

The NPC Agent layer SHALL implement registered route runners using generic cognitive categories and SHALL NOT encode world-engine business domains in runner, node, edge, or runtime organization.

#### Scenario: Runner modules use generic concepts

- **WHEN** route runner code is organized or refactored
- **THEN** module names, node labels, edge condition names, helper names, and comments describe generic NPC functions such as route resolution, preparation, planning, action execution, dialogue, structured output, reflection, tool dispatch, runtime, or response projection
- **AND** they do not encode schedules, clues, suspects, towns, war-game phases, NPC YAML fields, or other concrete world-engine business concepts

#### Scenario: World-engine responsibilities stay outside NPC layer

- **WHEN** the NPC layer executes an action-capable route
- **THEN** concrete side effects still occur only through world-engine-owned tool implementations
- **AND** the NPC layer does not parse NPC YAML, import `chromadb`, persist history, own world state, validate business schemas, or decide scene progression
