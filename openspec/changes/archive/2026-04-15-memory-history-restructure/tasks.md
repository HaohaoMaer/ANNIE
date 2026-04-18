# Tasks: 记忆 / 历史层重构

依赖：change `npc-skills-and-todo` 已 apply。

---

## 阶段 0：准备

- [x] 0.1 从主干新建分支 `refactor/memory-history-restructure`
- [x] 0.2 通读 `openspec/specs/npc-agent/spec.md`、`memory-interface/spec.md`、`world-engine/spec.md`，定位将被修订的小节

## 阶段 1：死代码清理

- [x] 1.1 删除 `src/annie/npc/context_manager.py`（无 import 验证：`Grep "ContextCompressor"` 仅剩文件自身）
- [x] 1.2 删除 `src/annie/npc/memory/immediate_memory.py`（同上）
- [x] 1.3 CLAUDE.md 的"Architecture"段移除对这两者的描述（若有），并新增一小节总结四个压缩器的边界
- [x] 1.4 ruff / pyright 干净

## 阶段 2：MemoryInterface 去重

- [x] 2.1 `src/annie/world_engine/memory.py`：新增 `_dedup_id(category, content, metadata)` 辅助；`remember()` 分流：
  - `category ∈ {semantic, reflection}` → `upsert` + stable id
  - 其他 → 现有 `add` + uuid
- [x] 2.2 单元测试 `tests/test_world_engine/test_memory_dedup.py`：
  - 相同 (category, content) 写两次 → 只命中一条 recall
  - 不同 person metadata 的相同 reflection 内容保留两条
  - impression / todo 不被去重
- [x] 2.3 Reflector 相关老测试（若有断言"两条"的）同步调整

## 阶段 3：取消 episodic 写入路径

- [x] 3.1 `src/annie/world_engine/default_engine.py::handle_response`：删除 `memory.remember(..., category=EPISODIC)` 调用
- [x] 3.2 更新 `tests/test_integration/test_decoupled_flow.py`：断言 response 后向量库里不再新增 episodic
- [x] 3.3 检查其他调用 `MEMORY_CATEGORY_EPISODIC.remember` 的位置——确认只保留 memory_store 工具的显式调用路径

## 阶段 4：Compressor 游标化

- [x] 4.1 `src/annie/world_engine/history.py`：新增 metadata sidecar 读写（`{path}.meta.json`，字段 `last_folded_turn_id: int`）
- [x] 4.2 `HistoryStore.prune(keep_last=None, before_turn_id=None)`：两者互斥；返回删除数；prune 后 `_read_all` 自然过滤
- [x] 4.3 `src/annie/world_engine/compressor.py`：
  - `_select_slice` 改为读 `entry.turn_id > last_folded_turn_id` 的条目
  - `force_fold`：不再调 `history.replace(...)`；完成后更新 cursor
  - 保留向 MemoryInterface 写 impression 的步骤
- [x] 4.4 `maybe_fold` 的触发估算改为"游标之后部分的 token"
- [x] 4.5 `HistoryStore._read_all` 跳过 `is_folded=True` 条目的解析（兼容老数据）

## 阶段 5：检索去重

- [x] 5.1 `src/annie/npc/agent.py::run`：开头 `context.extra.setdefault("_recall_seen_ids", set())`
- [x] 5.2 `src/annie/npc/sub_agents/memory_agent.py::build_context`：recall 到的记录 id 灌入该集合
- [x] 5.3 `src/annie/npc/tools/builtin.py::MemoryRecallTool.call` / `MemoryGrepTool.call`：返回前过滤已见 id，新 id 写入集合
- [x] 5.4 单元测试 `tests/test_npc/test_recall_dedup.py`：
  - stub memory 返回固定记录集
  - build_context 后调用 memory_recall，相同 query 不再返回已展示 id

## 阶段 6：plan_todo 健壮性

- [x] 6.1 `PlanTodoTool.call(op="complete")`：先 grep 验证 `{todo_id, status=open}`；不存在返回错误
- [x] 6.2 `PlanTodoTool.call(op="list")`：返回体含 `todo_id / content / timestamp`，按 timestamp 倒序
- [x] 6.3 `add` 时 metadata 写入 `created_at`（ISO8601）
- [x] 6.4 扩展 `tests/test_npc/test_plan_todo.py`：
  - complete 不存在 id → 失败 + 语义明确
  - 双 complete → 第二次失败
  - list 按倒序返回 + 字段完整

## 阶段 7：四个压缩器的回归/边界测试

- [x] 7.1 `tests/test_world_engine/test_compressor.py`：
  - 游标推进：两次 maybe_fold，不重复折叠同一段
  - prune 后 cursor 仍指向已被删位置也能正常工作
  - 折叠结果写入 impression，JSONL 不变
- [x] 7.2 `tests/test_npc/test_context_budget.py`（若缺则新建）：已存在且覆盖核心语义
  - 超限时 emergency fold 保留最近 2 轮 Human
  - 未超限不改动 messages
- [x] 7.3 `tests/test_npc/test_tool_agent_micro.py`（若缺则新建）：
  - 长 ToolMessage 被头尾截断
  - 短内容不变

## 阶段 8：Specs 同步

- [x] 8.1 更新 `openspec/changes/memory-history-restructure/specs/*/spec.md`（已由本 change 初稿提供）
- [x] 8.2 运行 `npx openspec status --change memory-history-restructure --json` 验证

## 阶段 9：文档与收尾

- [x] 9.1 CLAUDE.md 更新：
  - "四个压缩器" 分层表
  - 向量库只存提炼物 (episodic 已取消)
  - HistoryStore prune 原语与 cursor
  - Memory dedup 规则
- [x] 9.2 `ruff check src/annie/npc src/annie/world_engine` / `pyright` 干净
- [x] 9.3 `pytest tests/test_integration/test_decoupled_flow.py tests/test_npc tests/test_world_engine` 通过
- [ ] 9.4 归档：`/opsx:archive memory-history-restructure`

---

## 验收标准

1. `ContextCompressor` / `ImmediateMemory` 文件不存在，全仓零 import 残留
2. `handle_response` 不再写 episodic；相关集成测试断言通过
3. 相同 (semantic, content, person) 写两次 → 向量库只有一条
4. `Compressor` 不再修改 JSONL；折叠状态靠游标持久化；prune 原语生效
5. run 内 `<working_memory>` 展示过的记录不再在后续 tool response 中重复
6. `plan_todo(complete)` 对未知/已关闭 id 失败；`list()` 返回包含 timestamp
7. 四个压缩器各有独立的单元/集成测试覆盖其核心语义
8. CLAUDE.md 更新、ruff / pyright / 目标测试集干净

## 不在验收

- 历史向量库中现存 episodic 记录的清洗
- `history_grep` 工具
- 游戏时间感知的 prune 策略
- todo 的优先级 / 截止时间 / reopen
