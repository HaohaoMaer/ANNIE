# Memory Interface Capability Spec — Delta

本次 change 对 memory-interface capability 的修订。

## ADDED Requirements

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
