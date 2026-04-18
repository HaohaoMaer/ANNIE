# Proposal: 记忆 / 历史层重构 + 压缩职责明晰

## Why

上两个 change 把 NPC 侧的骨架立起来后，压缩与记忆这一块暴露出四个积累问题：

1. **压缩器重叠**：`ContextCompressor`（5 档）、`ContextBudget`、`Compressor`、`ToolAgent.micro` 四者名字与边界混乱；其中 `ContextCompressor` 从未被 import，属死代码。`ImmediateMemory` 同样是无引用残留。
2. **短/长期记忆混居**：`HistoryStore`（JSONL）和 `MemoryInterface`（向量库）同时保存原始对话——每条台词 `handle_response` 都写一遍到 `episodic`。Reflector 再把对话总结成 reflection/semantic，折叠再产出 impression。同一事实在向量库中以三种粒度重复出现，recall 噪声大。
3. **JSONL 无上限增长**：折叠只压缩最老一段，JSONL 本身无淘汰机制。真实时间 TTL 不适配游戏时间；淘汰策略应由 WorldEngine 决定，而非 HistoryStore 自作主张。
4. **Reflector 无幂等**：相同 fact 每轮都会被 append 一次。`memory.remember` 用 uuid 当 id，同文本多写即多条向量。
5. **检索重复**：run 入口 `MemoryAgent.build_context` 做一次 recall 写入 `<working_memory>`；Executor loop 里 LLM 还会主动调 `memory_recall`；两路径可能返回同一条记录，同一条被重复渲染进上下文。
6. **TODO 健壮性不足**：`complete` 不校验 id 存在、不校验是否已关闭；`list` 返回体只有 content，LLM 看不到创建时间或 todo_id。

## What Changes

### 1. 删除死代码

- 删除 `src/annie/npc/context_manager.py`（`ContextCompressor`）
- 删除 `src/annie/npc/memory/immediate_memory.py`（`ImmediateMemory`）

两者均无 import，删除零风险。CLAUDE.md 同步更新。

### 2. 向量库不再存 episodic（职责重分）

`DefaultWorldEngine.handle_response` 取消 `memory.remember(..., category=EPISODIC)` 这一步。向量库从此只存**提炼物**：

| category   | 作用                                         | 写入者       |
|------------|----------------------------------------------|--------------|
| reflection | 反思 / 关系观察                              | Reflector    |
| semantic   | 抽出的事实                                   | Reflector    |
| impression | 折叠摘要（语义召回对话的入口）               | Compressor   |
| todo       | 跨 run 目标                                  | plan_todo    |

原始对话的 source of truth 交给 JSONL 独占。需要"原话"时，WorldEngine/其他工具可直接 grep HistoryStore（后续 change 可加 `history_grep` 工具，本 change 不做）。

### 3. 折叠不改写 JSONL，用游标驱动

- `Compressor` 不再调用 `HistoryStore.replace(...)`；取消 `HistoryEntry.is_folded` / `folded_from` 字段的使用（字段保留一个 release 做兼容，标记 deprecated）。
- `Compressor` 维护 `last_folded_turn_id` 游标（持久化在 JSONL 相邻的 `.fold_cursor` 文件，或 HistoryStore 的 metadata 区）。
- 触发条件：`sum(len(entry.content) for entry in history if entry.turn_id > cursor)` 对应 token 数超 `FOLD_TOKEN_THRESHOLD` 时折叠 cursor 之后的最老 `FOLD_TARGET_TOKENS`，写 impression + 更新 cursor。

### 4. HistoryStore.prune() 原语

提供两个入口，策略留给 WorldEngine：

```python
HistoryStore.prune(keep_last: int | None = None,
                   before_turn_id: int | None = None) -> int  # returns deleted count
```

恰好提供其中一个参数（mutually exclusive）。prune 后 `last_folded_turn_id` 不动——若游标指向已被 prune 的 id，下一次折叠自然基于剩余最老条目重新起算。

### 5. 记忆去重（写入侧，content hash）

`DefaultMemoryInterface.remember` 对 `category ∈ {semantic, reflection}` 改用稳定 id：

- `id = sha1(f"{category}|{content}|{person}")[:16]` 其中 `person = metadata.get("person", "")`
- chroma 用 `upsert`（替代 `add`）落库
- 其他 category（`impression` / `todo` / 以及残留逻辑中残存 `episodic` 调用）保留 uuid 与 `add`

为什么不给 impression 去重：折叠本身是"不同时间段的摘要"，相同文本概率极低，且一旦碰撞会丢失时间段信息。

### 6. 检索去重（读取侧，run-scoped）

`AgentContext.extra["_recall_seen_ids"]: set[str]` 在 run 开始时初始化。

- `MemoryAgent.build_context(event)` 把 recall 到的记录 id 写入该集合，并按原样渲染 `<working_memory>`。
- `MemoryRecallTool` / `MemoryGrepTool` 在 `call()` 返回前过滤掉已在集合中的 id，同时把新返回的 id 加入集合。

这样 LLM 在 `<working_memory>` 里已经看过的记录不会在工具响应里再次出现。过滤在 Tool 内部做，不影响 MemoryInterface 接口。

### 7. Reflector 直接用幂等写入

Reflector 代码无需自检；写入层已处理。移除当前"每 fact append 一次"里潜在的重复担忧。

### 8. plan_todo 健壮性补强

- `complete(todo_id)`：先 `grep(category=todo, metadata_filters={"todo_id": todo_id, "status": "open"})`，若不存在返回 `{"success": False, "error": "unknown or already closed"}`；存在才写 closed 记录。
- `list()`：返回体每项包含 `{"todo_id", "content", "timestamp"}`（timestamp 读自记忆 metadata，若缺失用 "?")。排序：最新创建在前。

## Impact

### 受影响模块

- `src/annie/npc/context_manager.py` — **删除**
- `src/annie/npc/memory/immediate_memory.py` — **删除**
- `src/annie/world_engine/default_engine.py` — `handle_response` 取消 episodic 写入
- `src/annie/world_engine/compressor.py` — 重构为游标模式；不再调 `HistoryStore.replace`
- `src/annie/world_engine/history.py` — 新增 `prune()` 方法；`last_folded_turn_id` 持久化辅助
- `src/annie/world_engine/memory.py` — `remember()` 路径按 category 分流 add/upsert + 稳定 id
- `src/annie/npc/sub_agents/memory_agent.py` — `build_context` 把 ids 注入 `_recall_seen_ids`
- `src/annie/npc/tools/builtin.py` — `MemoryRecallTool` / `MemoryGrepTool` 内置去重；`PlanTodoTool` 校验 + 元数据
- `src/annie/npc/agent.py` — run 开始时初始化 `_recall_seen_ids`

### 破坏性变更

- 向量库里现存的 episodic 记录**仍可 recall**，只是新写入停止；使用者若依赖 episodic 检索需要迁移到 impression。本项目目前无外部消费者。
- `HistoryEntry.is_folded` / `folded_from` 进入 deprecated 状态；读取兼容旧数据（跳过解析 folded 条目）；新写入不再产生。

### 不受影响

- AgentContext / AgentResponse 公共字段
- Executor tool-use 主循环
- Planner / Skill 注册 / 帧栈

## Non-Goals

- 不做向量库清洗脚本（旧 episodic 记录留着不碍事）
- 不引入 `history_grep` 工具（后续 change）
- 不改 `ContextBudget` / `ToolAgent.micro` 的行为，仅补测试与文档
- 不引入"按场景切换 prune"的高层策略（本 change 只提供原语）
- 不做优先级 / 截止时间 / 重新开启等 todo 扩展
