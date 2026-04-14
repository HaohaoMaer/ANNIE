# 世界引擎层 Capability Spec

本 spec 定义世界引擎层的职责、边界与契约。

## ADDED Requirements

### Requirement: 世界引擎层必须承载所有业务状态与业务逻辑

世界引擎层是所有业务复杂度的唯一承载者，包括：世界状态、NPC 身份与设定、所有 NPC 的记忆存储、业务工具实现、技能定义、场景推进逻辑、行动裁决逻辑。

#### Scenario: 新玩法的实现位置

- **WHEN** 需要实现一种新玩法（如剧本杀、AI 主持人、沙盒）
- **THEN** 新增代码必须全部位于世界引擎层
- **AND** 不得要求修改 NPC Agent 层

#### Scenario: 业务状态的唯一真相源

- **WHEN** 查询某个 NPC 的当前状态、位置、已知线索等业务数据
- **THEN** 世界引擎是唯一真相源
- **AND** NPC Agent 层不得缓存或复制此类数据

---

### Requirement: 世界引擎必须实现 WorldEngine 抽象基类

所有具体的世界引擎实现（剧本杀、AI 主持人、沙盒等）必须继承同一 `WorldEngine` 抽象基类，实现其规定的最小接口方法。具体方法集合由 plan 阶段定案，至少包括：构造 AgentContext、处理 AgentResponse、提供 MemoryInterface 实例。

#### Scenario: 接口一致性

- **WHEN** 上层代码持有一个 WorldEngine 引用
- **THEN** 不应依赖其具体实现类型即可驱动 NPC 运行完整一轮

#### Scenario: 扩展新引擎

- **WHEN** 新增一种世界引擎实现
- **THEN** 只需继承 WorldEngine 基类并实现其抽象方法
- **AND** 不得要求修改 NPC Agent 层或基类本身

---

### Requirement: 世界引擎必须为每次 Agent 运行构造完整的 AgentContext

在调用 NPCAgent.run() 之前，世界引擎必须构造包含所有必要字段的 AgentContext：NPC 身份、触发事件、可用工具、MemoryInterface 实例、character_prompt、世界规则、当前场景描述。

#### Scenario: Context 的完整性

- **WHEN** 世界引擎构造 AgentContext 时遗漏必填字段
- **THEN** NPCAgent 运行应立即失败并给出明确错误，而非静默使用默认值

#### Scenario: character_prompt 的构造责任

- **WHEN** 世界引擎想让 NPC 表现出特定性格、情绪、动机
- **THEN** 世界引擎负责将这些信息拼接为自然语言字符串放入 `character_prompt`
- **AND** NPC Agent 层不做任何结构化拼装

---

### Requirement: 世界引擎必须裁决 NPC 返回的行动意图

NPC Agent 的 AgentResponse 中包含行动意图（ActionRequest）。世界引擎收到后必须进行裁决：允许执行、修改后执行、或拒绝。世界引擎据此更新世界状态并决定下一步。

#### Scenario: 合法行动被执行

- **WHEN** NPC 表达意图"打开门"且世界状态允许
- **THEN** 世界引擎执行该动作并更新世界状态

#### Scenario: 非法行动被拒绝或修改

- **WHEN** NPC 表达意图"打开保险柜"但没有钥匙
- **THEN** 世界引擎可拒绝该动作或修改为"尝试打开保险柜（失败）"
- **AND** 裁决结果应反馈给 NPC（通常作为下一轮的 input_event）

---

### Requirement: 世界引擎必须实现 MemoryInterface

每个世界引擎实例必须能提供一个 `MemoryInterface` 实现，供 NPC 通过 built-in tools 读写记忆。MemoryInterface 的具体后端（向量库、内存、文件）由世界引擎自行决定。

#### Scenario: 默认实现

- **WHEN** 未指定自定义记忆后端
- **THEN** 提供一个包装 ChromaDB 的默认 MemoryInterface 实现
- **AND** 该实现支持 semantic / reflection / relationship 等常见 type

#### Scenario: 多 NPC 的记忆隔离

- **WHEN** 一个世界引擎管理多个 NPC
- **THEN** 每个 NPC 的记忆必须在逻辑上隔离
- **AND** NPC A 的 recall 不得返回 NPC B 的私有记忆（除非明确共享）

---

### Requirement: 世界引擎负责 NPC YAML / 配置的解析

现有 NPC YAML 中的 personality、background、goals、relationships 等字段由世界引擎自行解析并转换为 AgentContext 的 character_prompt 或其他字段。NPC Agent 层不得直接加载 NPC YAML。

#### Scenario: YAML 解析位置

- **WHEN** 新建一个 NPC
- **THEN** YAML 加载与解析必须发生在世界引擎层
- **AND** NPC Agent 层的代码中不得出现 `load_npc_profile` 或直接读取 NPC YAML 文件的调用

#### Scenario: relationships 字段的转换

- **WHEN** NPC YAML 中声明了 `relationships: [{target: X, type: friend, intensity: 0.8}]`
- **THEN** 世界引擎负责将其转为自然语言（如 "你与 X 是朋友，关系紧密"），嵌入 character_prompt
- **AND** 静态数值不得直接传入 NPC Agent 层

---

### Requirement: 世界引擎决定"接下来发生什么"

场景推进（时间流逝、事件触发、NPC 调度、剧情进展）完全由世界引擎控制。NPC Agent 层不得内置任何场景推进逻辑。

#### Scenario: 时间推进

- **WHEN** 需要时间流逝或场景切换
- **THEN** 由世界引擎决定并主动触发下一轮 NPC 运行
- **AND** NPC Agent 不得自行决定"等待 X 分钟"这类世界级副作用

#### Scenario: 多种引擎的推进模式

- **WHEN** 世界引擎是剧本杀引擎
- **THEN** 推进基于剧本阶段控制与规则触发
- **WHEN** 世界引擎是 AI 主持人引擎
- **THEN** 推进由主持人 Agent（另一个 LLM）动态决策
- **WHEN** 世界引擎是沙盒引擎
- **THEN** 推进基于物理/规则模拟，最小干预
