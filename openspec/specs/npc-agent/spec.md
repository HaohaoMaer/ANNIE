# NPC Agent 层 Capability Spec

本 spec 定义 NPC Agent 层的职责、边界与契约。描述停留在语义层，不钉具体类型签名。

## ADDED Requirements

### Requirement: NPC Agent 层必须是通用 AI 能力框架，不承载任何业务假设

NPC Agent 层提供通用的角色驱动 AI 能力（规划、执行、反思），不得内置任何特定世界观、玩法或业务领域的知识。

#### Scenario: 剧本杀与沙盒共用同一 Agent 实现

- **WHEN** 一个世界引擎是剧本杀引擎，另一个是沙盒引擎
- **THEN** 两者必须能够复用完全相同的 NPC Agent 代码
- **AND** NPC Agent 代码中不得出现 "剧本"、"线索"、"阶段"、"沙盒"、"物理" 等业务词汇

#### Scenario: Agent 层代码变更的影响面

- **WHEN** 一个业务需求仅涉及某一种世界引擎（如给剧本杀加一个新的线索检查流程）
- **THEN** NPC Agent 层代码不应因此被修改

---

### Requirement: NPC Agent 不得持有任何业务持久状态

NPC Agent 实例在 `run()` 调用之间不得持有 NPC 身份、记忆、世界状态等持久数据。所有此类数据必须通过 `AgentContext` 在每次运行时注入。

#### Scenario: 多 NPC 共享单个 Agent 实例

- **WHEN** 世界引擎需要驱动 N 个不同的 NPC
- **THEN** 应允许使用一个 NPCAgent 实例，分别传入 N 个不同的 AgentContext
- **AND** 不得要求为每个 NPC 创建独立的 NPCAgent 对象

#### Scenario: Agent 可被安全丢弃与重建

- **WHEN** 世界引擎在两次运行之间销毁 NPCAgent 并重新创建
- **THEN** 业务行为必须与复用同一 Agent 实例完全等价

---

### Requirement: NPC Agent 保留 Planner → Executor → Reflector 的 LangGraph 流程

Agent 内部必须以 LangGraph 实现 Planner → Executor → Reflector 三节点循环，并保留 Executor 结果为空时重新规划的重试边。Planner 在 LLM 判断事件简单时可自行选择跳过（skip），不强制产生任务列表。

#### Scenario: 简单事件跳过规划

- **WHEN** 触发事件被 Planner LLM 判断为"无需多步分解"
- **THEN** Planner 返回 skip 信号
- **AND** Executor 直接处理原始事件而非任务列表

#### Scenario: Executor 无产出时的重试

- **WHEN** Executor 完成后所有任务状态均为 FAILED 或产出为空
- **AND** 重试次数未达上限
- **THEN** 流程必须回到 Planner 重新规划

---

### Requirement: NPC Agent 通过 AgentContext 接收输入，通过 AgentResponse 返回结果

`run()` 方法的输入契约是 `AgentContext`（由世界引擎构造），输出契约是 `AgentResponse`。不得通过其他旁路（全局状态、构造函数残留等）传递业务数据。

#### Scenario: Context 是唯一输入通道

- **WHEN** 代码审查发现 NPCAgent.run() 从 AgentContext 以外的来源读取 NPC 身份、工具、记忆、角色设定
- **THEN** 该代码违反本要求

#### Scenario: Response 是唯一输出通道

- **WHEN** NPC 的思考、对话、行动意图、记忆更新请求产生
- **THEN** 必须封装在 AgentResponse 中返回
- **AND** 不得通过回调、全局事件、直接修改传入对象等方式隐式输出

---

### Requirement: NPC Agent 层内置一组基础 Tools

NPC Agent 层必须在内部维护一组通用 built-in tools，至少包括：
- 记忆检索（对 MemoryInterface.recall 的 LLM 可见包装）
- 记忆写入（对 MemoryInterface.remember 的 LLM 可见包装）
- 内心独白 / 自言自语（用于 LLM 表达非对话性思考）

这些 built-in tools 在装配 ToolRegistry 时与 `AgentContext.tools`（世界引擎注入的业务工具）合并，对 LLM 呈现为统一工具集。

#### Scenario: LLM 可同时调用 built-in 与注入工具

- **WHEN** 一次 Executor 迭代中 LLM 输出 tool_call
- **THEN** 调用目标既可以是 built-in tools（如 memory_recall），也可以是 context.tools 注入的业务工具
- **AND** Agent 代码对二者的派发逻辑应一致

#### Scenario: 工具命名冲突

- **WHEN** 世界引擎注入的 tool 与 built-in tool 同名
- **THEN** 行为必须是明确定义的（要么 built-in 优先并警告，要么注入优先并警告——plan 阶段定），不得静默覆盖

---

### Requirement: NPC Agent 不得内置任何认知状态数据结构

NPC Agent 层代码中不得存在情绪状态、信念系统、动机引擎、关系图等认知数据结构。认知维度一律通过 `AgentContext` 的 prompt 文本字段（如 character_prompt）由世界引擎注入，由 LLM 从自然语言中实时推理。

#### Scenario: 认知结构被意外引入

- **WHEN** 有人在 NPC Agent 层添加形如 `class EmotionalState(BaseModel): ...` 或 `trust: float` 的结构
- **THEN** 违反本要求，应被拒绝合入

#### Scenario: 认知信息的正确传递方式

- **WHEN** 世界引擎希望让 NPC 知道自己"当前感到焦虑"
- **THEN** 应通过 `character_prompt` 中嵌入自然语言描述（如 "你此刻感到焦虑，因为..."）
- **AND** 不得通过结构化字段如 `emotion={"anxiety": 0.8}` 传递

---

### Requirement: Skill 以 prompt 模板形式注入，不作为独立执行单元

NPC Agent 层的 Executor 在处理任务时，若发现任务与某个 Skill 匹配，应将该 Skill 的 prompt_template 注入到当前 LLM 调用的指令中，引导 LLM 按 Skill 定义的流程使用其 allowed_tools 完成任务。Skill 本身不是可被 LLM 直接 "调用" 的工具。

#### Scenario: Skill 激活

- **WHEN** 当前任务匹配 NPC 拥有的某个 Skill（匹配逻辑首版可为关键字匹配）
- **THEN** Executor 构造 LLM prompt 时追加 Skill 的 prompt_template 片段
- **AND** 此次 LLM 调用可用的工具受 Skill 的 allowed_tools 约束

#### Scenario: Skill 不出现在 LLM 的 tool_call 列表中

- **WHEN** LLM 生成 tool_call
- **THEN** 目标名称只能是 Tool 的名字，不会是 Skill 的名字
