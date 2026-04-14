# Tool / Skill System Capability Spec

本 spec 定义 Tool 与 Skill 的分层、定义规范、激活机制。

## ADDED Requirements

### Requirement: Tool 与 Skill 是两种语义不同的能力单元

- **Tool**：一个机械可执行的能力单元，有结构化输入输出 schema，LLM 通过 tool_call 直接调用，结果喂回 LLM
- **Skill**：一个"带流程指导的 prompt 模板 + 允许调用的 Tool 子集"，**不被 LLM 直接调用**，而是在 Executor 匹配到相关任务时注入到 LLM 的指令中

二者不得混淆或合并。Skill 不是"复杂 Tool"，Tool 也不是"简单 Skill"。

#### Scenario: Tool 的调用

- **WHEN** LLM 生成 tool_call
- **THEN** 目标必须是一个 Tool 的名字（built-in 或世界引擎注入）
- **AND** 该 tool_call 进入 Executor 的执行循环，调用结果作为 observation 喂回 LLM

#### Scenario: Skill 的激活

- **WHEN** Executor 处理任务时发现任务与某个 Skill 匹配
- **THEN** 该 Skill 的 prompt_template 被拼接到当前 LLM 调用的 system prompt 中
- **AND** 本次调用可用的 tool 列表被限制为该 Skill 的 allowed_tools

#### Scenario: Skill 不是 Tool

- **WHEN** 枚举 AgentContext.tools
- **THEN** Skill 不出现其中
- **WHEN** LLM 查看可调用工具
- **THEN** 只看到 Tool 名字，看不到 Skill 名字

---

### Requirement: Tool 必须遵循统一的 ToolDef 规范

每个 Tool 必须具备：

- 唯一的 `name`
- 给 LLM 看的 `description`
- 结构化的 `input_schema`（Pydantic model 或等价）
- 可选的 `output_schema`
- `call(input, ctx)` 实际执行方法
- 元数据：`is_read_only`、`is_concurrency_safe` 等

具体类形态（Protocol / ABC / buildTool factory）由 plan 阶段决定，但必须在同一规范下。

#### Scenario: Tool 的统一注册

- **WHEN** 装配 ToolRegistry
- **THEN** built-in tools 与世界引擎注入的 tools 必须使用同一个 ToolDef 规范
- **AND** 不得存在两套不同的 Tool 基类

#### Scenario: Tool 的 schema 驱动

- **WHEN** LLM 请求工具列表
- **THEN** 每个 Tool 应能产出标准 JSON Schema 供 LLM 理解参数结构
- **AND** 调用时 Executor 对参数做 schema 校验

---

### Requirement: Skill 必须遵循统一的 SkillDef 规范

每个 Skill 必须具备：

- 唯一的 `name`
- `description`：技能的用途与何时使用
- `allowed_tools`：该技能激活时 LLM 可调用的 Tool 名字子集
- `prompt_template`：技能的流程指导（可含占位符）

具体字段类型与匹配算法由 plan 阶段决定。首版匹配算法可为关键字 / name 匹配，后续可优化为语义匹配。

#### Scenario: Skill 限制可用工具

- **WHEN** 名为 "interrogation" 的 Skill 被激活
- **THEN** 本次 LLM 调用仅能看到 allowed_tools 中声明的工具
- **AND** 即使 AgentContext 提供了更多工具，也被临时隔离

#### Scenario: Skill 无 schema

- **WHEN** 定义一个 Skill
- **THEN** 不需要 input_schema / output_schema（它不被直接调用）
- **AND** 其"输入"来自任务上下文与 NPC 当前状态

---

### Requirement: 基础 Tools 位于 NPC Agent 层，业务 Tools 位于世界引擎层

- **基础 Tools**（memory_recall / memory_store / inner_monologue 等通用能力）：必须在 NPC Agent 层内置
- **业务 Tools**（inspect_item / move_to_location / perceive_scene 等与具体世界相关）：必须在世界引擎层定义

#### Scenario: 基础工具不应要求世界引擎重复注册

- **WHEN** 不同的世界引擎接入 NPC Agent
- **THEN** 每个世界引擎无需重新定义 memory_recall 等基础工具
- **AND** 这些工具由 NPC Agent 在装配 ToolRegistry 时自动包含

#### Scenario: 业务工具不应出现在 NPC Agent 层

- **WHEN** 代码审查 `src/annie/npc/tools/` 目录
- **THEN** 不应出现 inspect_item 等业务相关工具
- **AND** 这些工具的定义与实现均位于 world_engine 层

---

### Requirement: Skill 仅位于世界引擎层

Skill 是业务特化的流程指导（审讯、推理、谈判等均与具体世界设定强绑定），必须由世界引擎层定义。NPC Agent 层不得内置任何 Skill。

#### Scenario: NPC Agent 层无 Skill

- **WHEN** 代码审查 `src/annie/npc/skills/` 目录
- **THEN** 只应存在 SkillDef 规范（base）和 Skill 注册 / 匹配机制
- **AND** 不应存在任何具体 Skill 实例

---

### Requirement: Tool 与 Skill 的合并在 Agent 内部对 LLM 统一呈现

NPC Agent 的 ToolRegistry 合并 built-in tools 与 `AgentContext.tools`；SkillRegistry 接收 `AgentContext.skills`。对 LLM 而言，可用工具就是合并后的统一集合，不感知来源。

#### Scenario: 工具来源透明化

- **WHEN** LLM 看到可调用工具列表
- **THEN** 不知道某个工具是 built-in 还是世界引擎注入
- **AND** 调用方式完全相同

#### Scenario: 命名冲突

- **WHEN** built-in tool 与注入 tool 同名
- **THEN** 行为必须是明确定义的（由 plan 阶段决定优先规则）
- **AND** 不得静默覆盖造成行为不可预测

---

### Requirement: Tool 执行上下文可访问 AgentContext 的扩展字段

Tool.call 方法接收的 ctx 参数中，必须能访问当前运行的 AgentContext（或其相关部分），以便工具实现可以读取世界引擎注入的扩展数据。

#### Scenario: Tool 访问扩展字段

- **WHEN** 一个业务 Tool 需要知道 "当前场景 ID"
- **THEN** 通过 ctx 访问 AgentContext.extra["scene_id"]
- **AND** 不需要通过参数传入（避免 LLM 需要知道这些内部细节）

#### Scenario: Tool 访问 MemoryInterface

- **WHEN** 一个 built-in tool（如 memory_recall）执行
- **THEN** 通过 ctx 访问 AgentContext.memory
- **AND** 不通过构造函数依赖注入（因为每次 run 的 memory 实例可能不同）
