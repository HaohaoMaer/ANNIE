# World Engine Spec Delta — memory-history-restructure

## ADDED Requirements

### Requirement: HistoryStore 必须提供 prune 原语

`HistoryStore.prune(keep_last: int | None = None, before_turn_id: int | None = None) -> int`
负责按条数或按 turn_id 分界删除旧条目，返回删除条数。两参数互斥；同时指定必须抛错。

淘汰策略由 WorldEngine 决定；HistoryStore 自身不感知"游戏时间"或"场景"等上层概念。

#### Scenario: 按条数保留

- **WHEN** 调用 `prune(keep_last=100)` 且当前有 250 条条目
- **THEN** JSONL 只剩最新 100 条
- **AND** 返回值 = 150

#### Scenario: 按 turn_id 分界

- **WHEN** 调用 `prune(before_turn_id=42)`
- **THEN** `turn_id <= 42` 的条目被删除
- **AND** 返回值 = 被删除条数

#### Scenario: 两参数互斥

- **WHEN** 同时指定 `keep_last` 与 `before_turn_id`
- **THEN** HistoryStore 必须抛出参数错误

---

### Requirement: Compressor 必须使用游标模式折叠，不得修改 JSONL

Compressor 维护 `last_folded_turn_id` 持久化游标；折叠范围始终是"游标之后"的未折叠对话段。折叠完成后：

- 向 MemoryInterface 写一条 `impression` 摘要
- 更新游标到本次折叠末尾的 turn_id
- **不修改** HistoryStore 中的任何条目

游标的持久化由 HistoryStore 侧的 metadata sidecar（或等价机制）支撑，跨进程恢复。

#### Scenario: 折叠后 JSONL 不变

- **WHEN** 触发 `Compressor.force_fold`
- **THEN** JSONL 文件的条目数与内容均未改变
- **AND** 向量库新增一条 `impression` 记录
- **AND** `last_folded_turn_id` 推进到最新折叠结束位置

#### Scenario: 折叠不会重折同一段

- **WHEN** 连续两次 `maybe_fold` 且期间无新增对话
- **THEN** 第二次返回 None（无新内容可折叠）

#### Scenario: prune 后的游标仍然有效

- **WHEN** `prune(before_turn_id=X)` 删除的范围已覆盖游标位置
- **THEN** 下一次折叠从当前 JSONL 中最老的未折叠条目起算
- **AND** 不抛错、不重复折叠

---

## MODIFIED Requirements

### Requirement: handle_response 不再将对话写入向量库 episodic

`DefaultWorldEngine.handle_response` 仍将对话追加到 HistoryStore，但**不再**调用 `memory.remember(..., category=EPISODIC)`。对话的权威来源是 JSONL；向量库只承载提炼物（见 memory-interface spec delta）。

#### Scenario: handle_response 后向量库 episodic 不增

- **WHEN** 调用 `handle_response(npc_id, response)` 且 response.dialogue 非空
- **THEN** 向量库中该 NPC 的 `episodic` 类别条目数量不变
- **AND** HistoryStore.jsonl 新增一条 speaker=npc_id 的条目
