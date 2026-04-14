# Memory Interface Capability Spec — Delta

本次 change 对 memory-interface capability 的修订。

## MODIFIED Requirements

### Requirement: 长期记忆以**单 collection + 开放 category 字符串**组织

原需求"记忆类型（type）是开放字符串，由世界引擎约定"升级为：

- 底层存储**统一为单个 ChromaDB collection**（per-NPC 一个）
- 类别区分由 entry 的 `metadata.category` 承担，不通过多 collection 切分
- category 仍为开放字符串；推荐约定值：`episodic` / `semantic` / `reflection` / `impression`
- `impression` 类别在召回时乘以 `IMPRESSION_WEIGHT`（默认 1.2）加权

#### Scenario: 跨类别 top-k 召回

- **WHEN** 调用 `recall(query="张三", categories=None, k=5)`
- **THEN** 在单一 collection 内做一次向量检索
- **AND** 通过 metadata.category 区分结果来源
- **AND** `impression` 条目 relevance_score 乘以 IMPRESSION_WEIGHT 后与其他类别同榜排序

#### Scenario: 按指定类别子集召回

- **WHEN** 调用 `recall(query="毒药", categories=["episodic", "reflection"], k=5)`
- **THEN** 仅返回 metadata.category 属于指定子集的条目
- **AND** 不返回 semantic / impression 类记忆

---

### Requirement: MemoryInterface 的 recall 必须接受 `categories: list[str] | None`

原 `recall(query, type: str | None, k)` 签名升级为 `recall(query, categories: list[str] | None, k)`：

- `categories=None` 代表全类别召回
- `categories=[]` 视为 None 等价处理
- 单类别查询通过 `categories=["semantic"]` 传达
- `MemoryRecord.type` 字段更名为 `MemoryRecord.category`

#### Scenario: 旧代码调用必须更新

- **WHEN** 任何调用方使用 `recall(query, type="semantic")`
- **THEN** 必须改为 `recall(query, categories=["semantic"])`
- **AND** 编译/类型检查阶段立即失败，以强制迁移

#### Scenario: remember 写入必带 category

- **WHEN** 调用 `remember(content, category="impression", metadata=...)`
- **THEN** 该条目以 `metadata.category="impression"` 存入统一 collection
- **AND** 无须指定 collection / type 参数

---

### Requirement: `impression` 作为一等类别记录 Fold 产物

本次 change 将 Fold 压缩产物定义为独立的 `impression` 类别记忆，区别于 semantic（客观事实）与 reflection（自我分析）：

- `impression` 语义："对某段经历或某个人的模糊印象"
- 产出来源：Compressor 的 Fold 操作
- metadata 必带 `source="fold"`、`scene`、`time_range=[t0, t1]`
- 召回阶段的加权保证 impression 比同长度原始片段更突出

#### Scenario: Fold 产物双写

- **WHEN** Compressor 完成一次 Fold
- **THEN** 产出的 summary 以 `category="impression"` 写入 MemoryBackend
- **AND** 同一 summary 同时替换 HistoryStore 中对应的 raw turn 段

#### Scenario: impression 与 episodic 共存

- **WHEN** 针对同一段对话既写了 episodic（handle_response 阶段）又写了 impression（Fold 阶段）
- **THEN** 二者作为两条独立记忆共存于 collection
- **AND** 模型可通过 categories 参数选择召回粒度
