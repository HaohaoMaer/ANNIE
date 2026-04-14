# Memory Interface Capability Spec

本 spec 定义 NPC 记忆系统的分层与 MemoryInterface 契约。

## ADDED Requirements

### Requirement: NPC 记忆分为即时记忆与长期记忆两层，走不同通道

- **即时记忆（working memory）**：当前对话上下文、当前场景描述、最近事件摘要。由世界引擎在构造 AgentContext 时通过 prompt 文本字段直接注入，**不走 MemoryInterface**。
- **长期记忆**：语义知识、反思产出、对他人的认知等跨 run 持久化的内容。**统一通过 MemoryInterface** 读写，由世界引擎实现具体后端。

#### Scenario: 即时记忆的正确路径

- **WHEN** 世界引擎需要让 NPC 知道"刚才张三说了什么"
- **THEN** 将对话内容嵌入 AgentContext 的 situation / history 字段
- **AND** 不得要求 NPC 通过 recall 查询

#### Scenario: 长期记忆的正确路径

- **WHEN** NPC 需要回忆几小时前与李四的谈话内容
- **THEN** 通过 memory_recall Tool 经由 MemoryInterface 检索
- **AND** 世界引擎不得将长期记忆预先塞满 AgentContext

---

### Requirement: MemoryInterface 必须提供统一的 recall / remember / build_context 方法

MemoryInterface 是协议（Protocol）式接口，至少暴露：

- **recall**：根据查询字符串检索记忆，可选 `type` 过滤和 `k` 条数
- **remember**：写入一条记忆，必须指定 `type` 和可选的 metadata
- **build_context**：针对某个查询综合检索多类记忆并格式化为可嵌入 prompt 的上下文字符串

具体方法签名（同步 / 异步、返回类型、分页等）由 plan 阶段定案。

#### Scenario: 统一查询

- **WHEN** NPC Agent 内置的 memory_recall Tool 被调用
- **THEN** 内部只调用 MemoryInterface.recall，不依赖具体后端
- **AND** 世界引擎可自由替换底层（ChromaDB / SQLite / 内存 / Redis）

#### Scenario: build_context 作为便捷方法

- **WHEN** Planner 或 Reflector 需要综合所有相关记忆产生背景文本
- **THEN** 可直接调用 `memory.build_context(query)` 获得格式化字符串
- **AND** 不需要自行组合 recall 结果

---

### Requirement: 记忆类型（type）是开放字符串，由世界引擎约定

MemoryInterface 不得在接口层硬编码一组有限的 type 枚举。世界引擎可自行约定支持的类型（至少推荐 `semantic` / `reflection` / `relationship`），通过 metadata 实现过滤。

#### Scenario: 新增记忆类型

- **WHEN** 某个世界引擎需要引入新类型（如 `goal_progress`）
- **THEN** 只需在该世界引擎的 MemoryInterface 实现中支持即可
- **AND** 不得要求修改 NPC Agent 层或 MemoryInterface 协议本身

#### Scenario: type 的默认值

- **WHEN** 调用方未指定 type
- **THEN** 行为由 plan 阶段决定（返回所有类型 / 默认 semantic / 报错），但必须是明确定义的

---

### Requirement: 关系认知从关系类记忆片段由 LLM 实时综合，不作为独立存储

NPC 对他人的关系认知（"我觉得张三不太可信"）不得作为结构化数值或独立数据结构存储。每次互动后由 Reflector 产出带人物 tag 的观察文本，以 `type=relationship` 存入语义记忆；需要查询"我对 X 的看法"时，通过 `recall(query=X, type="relationship")` 检索相关片段，由 LLM 实时综合。

#### Scenario: 关系记忆的写入

- **WHEN** NPC 与张三发生一次互动后，Reflector 产出"张三今天又没赴约"
- **THEN** 该条目以 `type=relationship`、metadata 中标记 `person=张三` 写入 MemoryInterface
- **AND** 不得修改任何名为 trust / familiarity 的数值字段

#### Scenario: 关系认知的读取

- **WHEN** NPC 在新一轮互动中需要评估自己对张三的态度
- **THEN** 通过 `recall(query="张三", type="relationship")` 获取所有相关片段
- **AND** LLM 在 prompt 中综合这些片段形成当前判断
- **AND** 不存在名为 `get_relationship(张三)` 返回结构化对象的接口

#### Scenario: 跨 NPC 的关系视角不对称

- **WHEN** NPC A 对 NPC B 的观察被记入 A 的记忆
- **THEN** 只影响 A 的关系认知
- **AND** B 不能直接查看 A 对自己的认知（除非发生了被告知的互动，才会反映在 B 的记忆中）

---

### Requirement: 记忆必须按 NPC scope 隔离

每个 NPC 的记忆在 MemoryInterface 后端必须逻辑隔离。NPC A 调用 recall 时不得返回 NPC B 的私有记忆。

#### Scenario: 记忆 scope

- **WHEN** NPC A 调用 memory_recall
- **THEN** 仅返回 A 的记忆
- **AND** MemoryInterface 实现应基于 NPC 身份标识（来自 AgentContext）内部 scope

#### Scenario: 共享记忆

- **WHEN** 世界引擎希望某条记忆被多个 NPC 共享（如"公告"）
- **THEN** 由世界引擎显式向每个 NPC 的 scope 写入，或提供额外的共享 scope
- **AND** 不得破坏默认的隔离

---

### Requirement: MemoryInterface 由世界引擎实现并通过 AgentContext 注入

MemoryInterface 的具体实现（ChromaDB 封装、SQL 后端等）位于世界引擎层。NPC Agent 层不得直接 import 任何具体实现。

#### Scenario: 实现位置

- **WHEN** 代码审查 `src/annie/npc/` 下的任意文件
- **THEN** 不应出现 `import chromadb` 或对 EpisodicMemory / SemanticMemory 具体类的 import
- **AND** 只能 import `MemoryInterface` 协议

#### Scenario: 默认实现

- **WHEN** 世界引擎未显式选择记忆后端
- **THEN** 使用 `world_engine` 层提供的基于 ChromaDB 的默认实现
## Requirements
### Requirement: MemoryInterface 必须提供字面/元数据检索通道 `grep`

在既有的向量检索 `recall` 之外，MemoryInterface 必须提供 `grep` 方法，用于按字面子串匹配 + metadata 过滤检索长期记忆。

- 签名至少包括：`pattern: str`，`category: str | None`，`metadata_filters: dict | None`，`k: int`。
- 命中语义为大小写不敏感的子串命中 entry.content。
- 不按向量相似度排序；按 entry 的 `created_at` 新→旧排序。
- 返回的 `MemoryRecord.relevance_score` 应为固定值（推荐 1.0），避免与 `recall` 结果混排时误导权重。

#### Scenario: 按专名精确命中

- **WHEN** NPC 想查"所有跟李四相关的记忆"
- **AND** 调用 `grep(pattern="李四")`
- **THEN** 返回所有 content 含"李四"子串的 entry，与向量相似度无关
- **AND** 这种查询在 `recall` 中通常漏掉低相似度但字面命中的记忆

#### Scenario: 叠加 category 和 metadata 过滤

- **WHEN** 调用 `grep(pattern="毒药", category="episodic", metadata_filters={"scene": "S1"})`
- **THEN** 仅返回 `category="episodic"` 且 `metadata.scene="S1"` 且 content 含"毒药"的 entry

#### Scenario: grep 与 recall 互补

- **WHEN** 同一 NPC 的同一查询通过 `recall` 和 `grep` 各取一次
- **THEN** 前者由向量相似度主导、可能包含语义接近但字面无关的结果
- **AND** 后者由字面命中主导、不受语义漂移影响
- **AND** 两者的结果集可以有重叠，但用途不同

---

### Requirement: 长期记忆必须约定五个一等 category

推荐约定值扩展为 `episodic / semantic / reflection / impression / todo` 五类：

- `todo` 作为跨回合未完成目标的持久化载体（由 change 2 的 `plan_todo` tool 写入；本 change 在类别目录上先预留一席）
- 其余四类语义与上一 change 保持一致

category 仍为开放字符串，但 prompt 层必须显式告知模型这五类的存在与含义，以便 `recall(categories=...)` / `grep(category=...)` 的过滤参数可用。

#### Scenario: Prompt 暴露 category 目录

- **WHEN** Executor 构造 system message
- **THEN** system 中必须包含一段枚举上述五类 category 及其一行含义的文本块
- **AND** 该文本块格式稳定、顺序固定

