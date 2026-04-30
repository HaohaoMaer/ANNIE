## MODIFIED Requirements

### Requirement: 世界引擎必须为每次 Agent 运行构造完整的 AgentContext

在调用 NPCAgent.run() 之前，世界引擎 MUST 构造包含所有必要字段的 AgentContext：NPC 身份、触发事件、可用工具、MemoryInterface 实例、character_prompt、世界规则、当前场景描述。世界引擎 MAY additionally request a registered NPC cognitive graph by `graph_id`, but it MUST NOT construct or inject NPC graph nodes, edges, builder functions, compiled graphs, or dynamic graph specs.

#### Scenario: Context 的完整性

- **WHEN** 世界引擎构造 AgentContext 时遗漏必填字段
- **THEN** NPCAgent 运行应立即失败并给出明确错误，而非静默使用默认值

#### Scenario: character_prompt 的构造责任

- **WHEN** 世界引擎想让 NPC 表现出特定性格、情绪、动机
- **THEN** 世界引擎负责将这些信息拼接为自然语言字符串放入 `character_prompt`
- **AND** NPC Agent 层不做任何结构化拼装

#### Scenario: Graph selection remains world-owned

- **WHEN** 世界引擎需要 NPC 生成世界行动、托管会话台词、结构化输出、或 distilled reflection
- **THEN** 世界引擎 may select a registered NPC cognitive graph through `AgentContext.graph_id`
- **AND** 世界引擎仍然负责业务状态、工具实现、行动裁决、结构化输出校验和长期记忆持久化

#### Scenario: World engine does not construct NPC graphs

- **WHEN** 世界引擎构造 `AgentContext`
- **THEN** it may provide only a registered graph identifier for NPC cognitive graph selection
- **AND** it must not provide LangGraph nodes, edges, graph builder callables, compiled graphs, or dynamic graph specs

#### Scenario: Business-specific intent stays outside graph identifiers

- **WHEN** 世界引擎 needs a business-specific result such as a schedule draft, clue analysis, interrogation utterance, or faction decision
- **THEN** it selects a generic NPC graph identifier
- **AND** it provides business-specific context, evidence, tools, and output requirements through ordinary `AgentContext` fields
- **AND** it does not require an NPC graph identifier named after the concrete business domain

#### Scenario: Route compatibility is transitional

- **WHEN** an existing world-engine integration still sets `AgentContext.route`
- **THEN** NPCAgent may map the route to a default graph identifier during migration
- **AND** new or migrated integrations should select `AgentContext.graph_id` directly when they know the desired cognitive graph
