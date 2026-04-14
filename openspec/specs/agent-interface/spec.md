# Agent Interface Capability Spec

本 spec 定义 NPC Agent 层与世界引擎层之间的联通接口：`AgentContext`（输入）和 `AgentResponse`（输出）。

## ADDED Requirements

### Requirement: AgentContext 必须采用"核心强类型 + prompt 文本 + 开放扩展"的三段分层

`AgentContext` 是世界引擎传入 NPC Agent 的唯一输入结构，字段分为三类：

1. **核心强类型字段**（NPC Agent 代码直接访问的机械依赖）：
   - NPC 身份标识（用于日志 / 追踪 / 记忆 scope）
   - 触发本次运行的输入事件
   - 可用工具列表（世界引擎注入的业务 Tool）
   - 可用技能列表（世界引擎注入的业务 Skill）
   - MemoryInterface 实例

2. **Prompt 文本字段**（世界引擎构造的自由文本，NPC Agent 不解析）：
   - 角色设定 / 认知状态 / 动机 prompt（承载身份与认知）
   - 世界规则 prompt（承载世界约束）
   - 当前场景描述 prompt（承载即时上下文）
   - 历史对话 / 近期事件摘要（承载短期记忆上下文）

3. **开放扩展字段**：
   - 一个开放的 `extra` / `metadata` dict，供世界引擎注入自定义数据，NPC Agent 不消费但可透传给 Tool

具体字段命名、类型、默认值由 plan 阶段定案。

#### Scenario: 核心字段缺失

- **WHEN** AgentContext 构造时缺少核心强类型字段（如未提供 MemoryInterface）
- **THEN** 必须在构造或 run 入口处立即失败

#### Scenario: Prompt 字段的处理

- **WHEN** NPC Agent 构造 system prompt
- **THEN** 只能将 character_prompt / world_rules / situation 等文本字段按固定顺序拼入
- **AND** 不得解析、分词、结构化提取其中的内容

#### Scenario: extra 字段的透传

- **WHEN** 世界引擎向 extra 注入数据（如 `{"scene_id": "xxx"}`）
- **THEN** NPC Agent 不读取也不校验
- **AND** Tool 实现可通过 Tool 上下文访问这些数据

---

### Requirement: AgentResponse 必须采用意图声明式

NPC Agent 返回的 `AgentResponse` 不得直接修改世界状态，只能声明意图由世界引擎裁决。必须包含：

- 对话内容（NPC 说的话）
- 内心独白 / 思考过程
- 行动意图列表（ActionRequest）——对世界有影响的行为
- 记忆更新请求（可选；若 Executor 期间已通过 Memory Tool 写入则可省略）
- 反思输出（Reflector 产出的总结）

#### Scenario: 行动意图不直接执行

- **WHEN** NPC 决定"去厨房"
- **THEN** AgentResponse.actions 中包含一条 {type: "move", target: "厨房"} 意图
- **AND** 不得在 NPC Agent 内部调用某个改变世界状态的函数

#### Scenario: Tool 调用与 Action 的区别

- **WHEN** NPC 想"回忆起与张三的对话"
- **THEN** 通过 Tool 调用（memory_recall）在 Executor 循环内完成，不出现在 AgentResponse.actions 中
- **WHEN** NPC 想"对张三说话并推开他"
- **THEN** 对话作为 dialogue 返回，推开作为 action 意图返回

#### Scenario: 记忆更新的两种路径

- **WHEN** NPC 在 Executor 过程中通过 memory_store Tool 写入了记忆
- **THEN** 该写入已即时生效，无需在 AgentResponse 中重复声明
- **WHEN** 世界引擎希望对 NPC 返回的 memory_updates 进行过滤或裁决
- **THEN** plan 阶段可决定改为"Executor 不直接写记忆，而是声明写入意图"，此时 AgentResponse 包含 memory_updates

---

### Requirement: Context 是 Agent 的唯一输入，Response 是 Agent 的唯一输出

NPC Agent 与世界引擎之间不得存在 AgentContext / AgentResponse 以外的通信通道。

#### Scenario: 禁止的通信方式

- **WHEN** 代码中出现 NPC Agent 访问世界引擎单例、全局状态、或通过构造函数接收世界引擎的业务对象
- **THEN** 违反本要求

#### Scenario: 允许的通信方式

- **WHEN** NPC Agent 需要访问世界状态
- **THEN** 只能通过 Tool 调用（由世界引擎提供实现），且 Tool 调用本身是 AgentContext.tools 的一部分

---

### Requirement: 接口版本可演进但必须向后兼容

AgentContext 和 AgentResponse 的字段添加不得破坏现有世界引擎实现。新增字段应可选且有合理默认值。字段删除或语义变更必须通过新的 change 正式声明。

#### Scenario: 新增字段

- **WHEN** 下一个 change 需要在 AgentContext 上增加字段（如 `locale: str`）
- **THEN** 该字段在接口层面应有默认值
- **AND** 旧的世界引擎实现无需修改即可继续工作

#### Scenario: 删除字段

- **WHEN** 某个字段不再使用
- **THEN** 必须通过新的 OpenSpec change 正式声明删除
- **AND** 不得静默删除
