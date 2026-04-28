## ADDED Requirements

### Requirement: NPC layer must not own profile loading or YAML parsing

`src/annie/npc/` MUST NOT define `NPCProfile`, `load_npc_profile`, or parse NPC YAML definitions. Profile schemas, YAML loading, and conversion to natural-language prompt text MUST live in the World Engine layer.

#### Scenario: Profile loaded for a default engine NPC

- **WHEN** `DefaultWorldEngine` receives an NPC YAML path
- **THEN** it loads the profile through World Engine code
- **AND** passes only prompt text and runtime dependencies to `AgentContext`

### Requirement: Reflector must return declarative memory updates

Reflector MUST NOT call `MemoryInterface.remember()` or any memory wrapper that persists data. It MUST parse the reflection response and return `MemoryUpdate` values for the World Engine to arbitrate.

#### Scenario: Reflection produces facts

- **WHEN** Reflector parses `REFLECTION` and `FACTS`
- **THEN** `AgentResponse.reflection` contains the reflection text
- **AND** `AgentResponse.memory_updates` contains reflection and semantic update declarations
- **AND** no memory is written until a World Engine handles the response

### Requirement: Todo tooling must be owned by World Engine

`plan_todo` MUST NOT be an NPC built-in. Engines that support persistent todos MUST inject a todo tool through `AgentContext.tools` and pre-render todo prompt text into `AgentContext.todo`.

#### Scenario: Default engine supports todos

- **WHEN** `DefaultWorldEngine.build_context()` is called
- **THEN** the returned context includes a `plan_todo` tool
- **AND** the `<todo>` prompt section is populated from pre-rendered context text

### Requirement: NPC built-in writes must be declarative

NPC built-ins MUST NOT directly mutate world state or persistent memory by default. A built-in that records memory or actions MUST write run-local declarations that are included in `AgentResponse`.

#### Scenario: Model calls `declare_action`

- **WHEN** Executor dispatches `declare_action(type="move", payload={...})`
- **THEN** the result is added to `AgentResponse.actions`
- **AND** the World Engine remains responsible for accepting, modifying, or rejecting the action

### Requirement: Internal run state must not pollute AgentContext.extra

NPC internals such as skill agents, tool registries, message lists, skill frames, recall dedup sets, inner thoughts, memory declarations, and action declarations MUST live in run-scoped internal storage rather than private keys in `AgentContext.extra`.

#### Scenario: Reusing an AgentContext

- **WHEN** the same `AgentContext` instance is passed to two separate `NPCAgent.run()` calls
- **THEN** inner thoughts and recall dedup state from the first run do not affect the second run
