# Tasks: NPC 记忆双索引与 Prompt 体检

原则：先底层（grep 接口）、再工具（memory_grep）、再 prompt / agent 流程、最后测试与文档。不保留新旧并存字段。

---

## 阶段 0：准备

- [ ] 0.1 从当前分支 `refactor/context-mgmt-and-agentic-rag` 新建 `refactor/memory-grep-and-prompt-overhaul`
- [ ] 0.2 确认 `chromadb` 版本支持 `collection.get(where=...)` 的 metadata 过滤

## 阶段 1：MemoryInterface.grep

- [ ] 1.1 `src/annie/npc/memory/interface.py`：Protocol 新增 `grep(pattern, category=None, metadata_filters=None, k=20) -> list[MemoryRecord]`
- [ ] 1.2 `src/annie/world_engine/store.py`：新增 `grep_entries(pattern, where, k)` 方法（ChromaDB `get(where=...)` + Python 端 `casefold()` 子串匹配）
- [ ] 1.3 `src/annie/world_engine/memory.py` (`DefaultMemoryInterface`)：实现 `grep`，`relevance_score` 固定 1.0，按 `created_at` 新→旧排序
- [ ] 1.4 单元测试：
  - 基本子串命中
  - category 过滤
  - metadata_filters 叠加
  - 大小写不敏感
  - k 上限
  - 空 pattern 返回 []

## 阶段 2：memory_grep built-in tool

- [ ] 2.1 `src/annie/npc/tools/builtin.py`：新增 `MemoryGrepInput` + `MemoryGrepTool`
- [ ] 2.2 `default_builtin_tools()` 加入 `MemoryGrepTool()`
- [ ] 2.3 单元测试：tool 的 input/output 往返

## 阶段 3：Prompt 结构改造

- [ ] 3.1 新建 `src/annie/npc/prompts.py`，提供 `render_identity(ctx) -> str` helper
- [ ] 3.2 `src/annie/npc/executor.py`：
  - 重写 `EXECUTOR_SYSTEM_TEMPLATE`，加入 `<memory_categories>` / `<working_memory>` 段，去除硬编码工具名
  - `_initial_messages` 读 `state["working_memory"]`，渲染 `<working_memory>`（空时 `(none)`）
  - skip 路径检测：`task.metadata.get("synthesized")` 或描述为 `"__skip__"` 时不渲染 `<task>`
  - `_render_identity` 替换内联字符串
- [ ] 3.3 `src/annie/npc/planner.py`：
  - 重写 `NPC_PLANNER_STATIC_PROMPT`：Option B 为默认、去掉 1-5 上限、改 "最多 3"
  - `_build_dynamic_prompt` 删除 history 渲染
  - `__call__` 读 `state.get("loop_reason")` 和 `state.get("last_tasks")`，retry_count > 0 时拼 `<retry_context>`
  - 读取 state key：`memory_context` → `working_memory`
- [ ] 3.4 `src/annie/npc/state.py`：
  - 字段 `memory_context` → `working_memory`
  - 新增 `last_tasks: list[Task]`
- [ ] 3.5 `src/annie/npc/agent.py`：
  - 初始化 `working_memory` 代替 `memory_context`
  - Executor 执行前把当前 `tasks` 快照写入 `state["last_tasks"]`（retry 场景用）
  - `_executor_with_skip`：合成 task 用 `Task(description="__skip__", metadata={"synthesized": True})`
  - `_build_response`：从 `context.extra.get("_inner_thoughts", [])` 拼接填入 `inner_thought`

## 阶段 4：Reflector 修补

- [ ] 4.1 `src/annie/npc/reflector.py`：
  - 新增 `_parse_list(raw)` tolerant parser（JSON → bullet → 空）
  - `_parse_response` 对 FACTS 用 `_parse_list`；RELATIONSHIP_NOTES 保留 JSON 优先、解析失败时降级为"字符串列表 → observation"
  - `store_semantic(fact, metadata={"category": "learned"})` 改为 `store_semantic(fact)`
  - system 追加改用 `render_identity(ctx)`

## 阶段 5：InnerMonologue 接入

- [ ] 5.1 `src/annie/npc/tools/builtin.py`：`InnerMonologueTool.call` 写 `ctx.agent_context.extra.setdefault("_inner_thoughts", []).append(...)`
- [ ] 5.2 `_build_response` 从 `extra["_inner_thoughts"]` 读取拼装（阶段 3.5 已列，此处留空确认口径一致）

## 阶段 6：测试

- [ ] 6.1 新增 `tests/test_world_engine/test_memory_grep.py` —— 覆盖 1.4 各场景
- [ ] 6.2 新增 `tests/test_npc/test_prompts.py` —— `render_identity`、`<memory_categories>` / `<working_memory>` 段渲染
- [ ] 6.3 更新 `tests/test_integration/test_decoupled_flow.py`：
  - state 字段改名适配
  - 断言 Executor system 包含 `<memory_categories>` + `<working_memory>`
  - 断言 skip 路径 trigger 不含 `<task>`
  - 断言 StubLLM 触发 inner_monologue 后 `response.inner_thought` 非空
- [ ] 6.4 新增 `tests/test_npc/test_reflector_parser.py`：JSON / bullet / 混合 / 空 四组
- [ ] 6.5 新增 `tests/test_npc/test_retry_context.py`：retry_count=1 时 Planner user_content 含 `<retry_context>` 与上轮 task 描述

## 阶段 7：文档与收尾

- [ ] 7.1 更新 `CLAUDE.md` 的 Architecture / 规约段落：
  - 双索引（recall + grep）
  - `working_memory` 命名
  - Planner skip-first 策略
  - 五个 memory category 的官方含义
- [ ] 7.2 更新 `src/annie/npc/__init__.py` 导出（若 `render_identity` 或新字段需要）
- [ ] 7.3 `pyright src/annie/npc src/annie/world_engine` 0 error
- [ ] 7.4 `ruff check` 通过
- [ ] 7.5 归档：`npx openspec archive` — 留待用户确认

---

## 验收标准

1. `MemoryInterface.grep` 存在且 `DefaultMemoryInterface` 正确实现
2. `memory_grep` tool 出现在 built-in 工具集，模型可通过 bind_tools 调用
3. Executor system prompt 含 `<memory_categories>` 与 `<working_memory>`，不再硬编码工具名
4. Planner skip-first：在简单对话事件下默认返回 skip；Executor skip 路径 trigger 不重复渲染 `<input_event>`
5. Planner retry 分支 user_content 含 `<retry_context>`
6. Reflector 能正确解析 bullet 列表格式的 FACTS
7. `AgentResponse.inner_thought` 反映 `inner_monologue` tool 的累计调用
8. `state["memory_context"]` 完全不存在；全部已改为 `working_memory`
9. pyright / ruff 干净，所有新增测试通过

## 不在验收中

- grep 的正则 / 多 pattern 形态
- 预检索升级为 RAG + grep 混合
- plan_todo / Skill 解冻 / 业务 tool hook（属后续 change）
