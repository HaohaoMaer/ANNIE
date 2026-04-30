## MODIFIED Requirements

### Requirement: 世界引擎必须为每次 Agent 运行构造完整的 AgentContext

在调用 NPCAgent.run() 之前，世界引擎 MUST 构造包含所有必要字段的 AgentContext：NPC 身份、触发事件、可用工具、MemoryInterface 实例、character_prompt、世界规则、当前场景描述。世界引擎 MAY additionally request an NPC execution route for the run, and when it does, it MUST provide route-appropriate context, tools, and validation responsibilities without moving business logic into the NPC Agent layer.

#### Scenario: Context 的完整性

- **WHEN** 世界引擎构造 AgentContext 时遗漏必填字段
- **THEN** NPCAgent 运行应立即失败并给出明确错误，而非静默使用默认值

#### Scenario: character_prompt 的构造责任

- **WHEN** 世界引擎想让 NPC 表现出特定性格、情绪、动机
- **THEN** 世界引擎负责将这些信息拼接为自然语言字符串放入 `character_prompt`
- **AND** NPC Agent 层不做任何结构化拼装

#### Scenario: Route selection remains world-owned

- **WHEN** 世界引擎需要 NPC 生成世界行动、托管会话台词、结构化 JSON、或 distilled reflection
- **THEN** 世界引擎通过 `AgentContext.route` 选择对应 NPC execution route
- **AND** 世界引擎仍然负责业务状态、工具实现、行动裁决、结构化输出校验和长期记忆持久化

#### Scenario: Macro planning remains world-owned

- **WHEN** 世界引擎需要生成或修订长期计划、每日日程、未来行动序列、或跨 tick 的策略
- **THEN** it may request candidate plan text through the structured JSON route
- **AND** it remains responsible for parsing, validating, accepting, persisting, revising, cancelling, and advancing that plan
- **AND** it does not rely on the NPC action-route planner as persistent plan state

#### Scenario: Dialogue route context does not grant world actions

- **WHEN** 世界引擎请求 managed dialogue route
- **THEN** it provides dialogue/session context and memory access as appropriate
- **AND** it does not expose movement, interaction, wait, schedule completion, or conversation-start tools for that route

#### Scenario: Structured JSON route validation remains world-owned

- **WHEN** 世界引擎请求 structured JSON route
- **THEN** it provides the output requirements in route context
- **AND** it parses and validates the returned structured-output text according to its own business schema
- **AND** it decides whether malformed or schema-invalid output should be repaired, retried, rejected, or handled by fallback logic

#### Scenario: Reflection route evidence remains world-owned

- **WHEN** 世界引擎请求 reflection route
- **THEN** it provides the evidence, memory summary, and persistence context needed for distilled reflection
- **AND** it does not rely on the NPC Agent layer to perform implicit memory recall for reflection
- **AND** it remains responsible for deciding whether the returned reflection should be persisted

#### Scenario: Legacy direct-mode flags are migrated

- **WHEN** an existing world engine integration still uses temporary `extra["npc_direct_mode"]` flags
- **THEN** it should migrate to `AgentContext.route`
- **AND** compatibility mappings may be used only during the migration period

## ADDED Requirements

### Requirement: 世界引擎提示策略必须把日程作为默认锚点

当具体世界引擎使用日程或类似计划机制时，世界引擎 MUST render prompt policy that treats the current schedule as the default anchor while allowing explicit high-priority exceptions.

日程生成、日程修订、日程持久化、完成度跟踪、动态插入、取消和冲突处理 are macro-planning responsibilities owned by the concrete world engine. The NPC Agent layer MAY draft schedule-like structured text through the structured JSON route, but it MUST NOT own accepted schedule state or decide future route activations.

#### Scenario: Schedule remains default

- **WHEN** an NPC has an active schedule and no urgent event, direct request, or clearly valuable opportunity
- **THEN** the world engine context instructs the NPC to prefer schedule-relevant movement or action

#### Scenario: High-priority detour is allowed with time budget

- **WHEN** an urgent event, direct request, or clearly valuable opportunity appears
- **THEN** the world engine context may allow a brief detour
- **AND** it must also instruct the NPC to consider travel/action time and return to the schedule promptly

#### Scenario: Schedule drafting uses structured JSON

- **WHEN** a world engine asks the NPC layer to draft a daily schedule or schedule revision
- **THEN** it uses the structured JSON route or equivalent structured-output route contract
- **AND** it validates the candidate against world-owned time, location, overlap, and business rules before accepting it

### Requirement: 世界引擎提示策略允许工具失败后确认环境

当具体世界引擎提供 observe or equivalent perception tools, it MUST distinguish optional observation from required action, and MAY instruct the NPC to confirm the environment after a tool failure.

#### Scenario: Observe is not a default pre-action step

- **WHEN** the current context already contains enough location, exit, visible object, visible NPC, and event information
- **THEN** the world engine context instructs the NPC not to call observe merely as a default first step

#### Scenario: Tool failure can justify observation

- **WHEN** a world-action tool fails because the environment may be stale or ambiguous
- **THEN** the world engine context may instruct the NPC to call observe or an equivalent perception tool before retrying or choosing a fallback
