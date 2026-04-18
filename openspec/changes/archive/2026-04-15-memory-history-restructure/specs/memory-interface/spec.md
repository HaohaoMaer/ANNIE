# Memory Interface Spec Delta — memory-history-restructure

## MODIFIED Requirements

### Requirement: 长期记忆按来源分 category；向量库只存提炼物

向量库承载的 long-term memory 仅保存"值得语义召回的提炼物"，具体 category：

- `reflection` — Reflector 产出的反思与关系观察
- `semantic` — Reflector 抽出的事实
- `impression` — Compressor 折叠对话产生的摘要
- `todo` — plan_todo 的跨 run 目标

原始对话 (`episodic`) **不再**由世界引擎在 `handle_response` 写入向量库——对话的权威来源是 HistoryStore (JSONL)。工具 `memory_store` 允许上层显式写 `episodic`，但默认流程中不会产生。

#### Scenario: 默认流程下向量库中不出现新 episodic

- **WHEN** NPC 在一轮对话后由 `DefaultWorldEngine.handle_response` 处理其响应
- **THEN** 向量库里该 NPC 集合中 `episodic` 类别的条目数量不增加
- **AND** 对话原文在 HistoryStore.jsonl 中完整保留

#### Scenario: 旧 episodic 仍可召回

- **WHEN** 向量库已有来自旧版本写入的 `episodic` 记录
- **THEN** `memory.recall` 仍能返回它们
- **AND** 本 change 不要求清洗或迁移

---

### Requirement: semantic / reflection 写入采用 content-hash 去重

`MemoryInterface.remember` 对 `category ∈ {semantic, reflection}` 的写入必须使用稳定 id（基于 `category + content + metadata.person`）并以 upsert 方式落库，确保重复写入相同语义内容只保留一条。

其他 category（`impression` / `todo` 及显式的 `episodic`）保留 uuid + add 语义，每次写入都产生新条目。

#### Scenario: 相同 fact 重复写只存一条

- **WHEN** Reflector 在相邻两轮均抽出相同 fact 字符串并调用 `remember(content, category="semantic")`
- **THEN** 向量库中该 fact 只占一条记录
- **AND** 其 metadata 的 timestamp 反映最近一次写入时间

#### Scenario: 不同 person 的 relationship note 互不覆盖

- **WHEN** 两条 reflection 记录 content 相同但 `metadata.person` 不同
- **THEN** 向量库保留两条独立记录
