# Tasks: 分层上下文管理、多类别记忆与 Agentic RAG

施工路线图。按阶段顺序推进，同阶段内可并行。

**原则**：先动存储（底层）、再动接口（签名）、最后动循环（Executor + Compressor）。不保留新旧并存。

---

## 阶段 0：准备

- [x] 0.1 本地清空 `./data/vector_store/` 和 `./data/history/`（如存在）
- [x] 0.2 从 `refactor/decouple-npc-world-engine` 切新分支 `refactor/context-mgmt-and-agentic-rag`
- [x] 0.3 确认 `langchain-core` / `langgraph` 版本支持 `bind_tools` 与 `ToolMessage`

## 阶段 1：长期记忆坍缩（单 collection + category metadata）

- [x] 1.1 合并 `src/annie/world_engine/episodic.py` + `semantic.py` 为 `src/annie/world_engine/store.py`
  - 单 ChromaDB collection: `npc_memory_{npc_id}`
  - metadata.category 区分类别
  - 保留 `chroma_lock.py` 复用
- [x] 1.2 删除 `episodic.py` / `semantic.py`
- [x] 1.3 更新 `src/annie/npc/memory/interface.py`
  - `MemoryRecord.type` → `MemoryRecord.category`
  - `recall(query, type=)` → `recall(query, categories: list[str] | None)`
  - `remember(content, type=)` → `remember(content, category=)`
- [x] 1.4 更新 `src/annie/world_engine/memory.py` (`DefaultMemoryInterface`)
  - 使用新 `store.py` 后端
  - impression 加权（`IMPRESSION_WEIGHT=1.2`）
  - `build_context` 按 category 分段格式化
- [x] 1.5 同步调用方：`sub_agents/memory_agent.py`、`tools/builtin.py` 的 `memory_recall` / `memory_store`、`reflector.py`
- [x] 1.6 `immediate_memory.py` 与新接口对齐（categories 参数）

## 阶段 2：HistoryStore

- [x] 2.1 新建 `src/annie/world_engine/history.py`
  - `HistoryEntry` Pydantic 模型
  - `HistoryStore(npc_id, path)`: `append` / `read_last(n)` / `estimate_tokens` / `replace(turn_ids, new_entry)`
  - JSONL append-only 存储 + 全量重写（replace 用）
- [x] 2.2 单元测试：append / read / replace / 文件损坏兜底

## 阶段 3：Compressor

- [x] 3.1 新建 `src/annie/world_engine/compressor.py`
  - `Compressor(history_store, memory, llm)`
  - `maybe_fold(npc_id)`: 判阈值 → 选段 → LLM 摘要 → HistoryStore.replace + memory.remember(impression)
  - FOLD_TOKEN_THRESHOLD=3000，单次 fold 目标 ~1500 tokens
  - is_folded=True 的 entry 不进入候选集
- [x] 3.2 摘要 prompt 模板：明确要求"谁对谁做了什么 + 情绪基调"
- [x] 3.3 单元测试：阈值触发、双写落地、递归折叠被拒绝

## 阶段 4：WorldEngine 接入

- [x] 4.1 更新 `src/annie/world_engine/base.py`
  - WorldEngine ABC 添加 `history_for(npc_id)` / `compressor_for(npc_id)` 可选方法
- [x] 4.2 更新 `src/annie/world_engine/default_engine.py`
  - 构造时实例化 per-NPC HistoryStore + Compressor
  - `build_context`: 渲染 history（Trim 生效）→ 不做预召回
  - `handle_response`: dialogue→HistoryStore + memory(episodic) → reflection→memory(reflection) → Compressor.maybe_fold

## 阶段 5：Executor 切原生 tool-use loop

- [x] 5.1 更新 `src/annie/npc/state.py`
  - `AgentState.messages: list[BaseMessage]`
  - `AgentState.context_budget: ContextBudget | None`
- [x] 5.2 新建 `src/annie/npc/context_budget.py`
  - `ContextBudget(model_ctx_limit, reserve_output)`
  - `check(messages, llm) -> messages`（触发 Emergency fold）
  - `estimate_tokens(messages)`
- [x] 5.3 重写 `src/annie/npc/executor.py`
  - 构造 initial_messages（XML 分节的 SystemMessage + 基于 history 的 message turn + 当前 task 的 HumanMessage）
  - `while True`: ContextBudget.check → llm.bind_tools(tools).invoke → 若无 tool_calls 退出 → 否则 dispatch 每个 tool_call 并 append ToolMessage
  - 循环上限 `MAX_TOOL_LOOPS=8`（超出强制退出 + 报错）
- [x] 5.4 更新 `src/annie/npc/sub_agents/tool_agent.py`
  - 退化为 `dispatch(tool_call, ctx) -> str` dispatcher
  - 在返回路径上做 Micro 压缩（MICRO_MAX_CHARS=2000）
  - 删除 keyword matching
- [x] 5.5 更新 `src/annie/npc/tools/builtin.py` 的 `memory_recall` 参数 schema（categories: list[str]）
- [x] 5.6 更新 `src/annie/npc/agent.py`
  - 装配 ContextBudget 传入 AgentState
  - AgentResponse 构造从 final AIMessage.content 取 dialogue

## 阶段 6：Skill 冻结

- [x] 6.1 `src/annie/npc/sub_agents/skill_agent.py`
  - `try_activate` → 返回 None + 一次性 DeprecationWarning（进程内去重）
- [x] 6.2 Executor 删除所有 skill 激活相关代码路径
- [x] 6.3 保留 `SkillDef` / `SkillRegistry` 不改

## 阶段 7：Planner / Reflector 适配

- [x] 7.1 `planner.py`: 产出的 task.description 不再被直接作为 user message 塞入（新 Executor 已接管 message 组装）；保持 task 列表输出
- [x] 7.2 `reflector.py`:
  - 解析 REFLECTION → memory.remember(category="reflection")
  - 解析 FACTS → memory.remember(category="semantic")
  - 解析 RELATIONSHIP_NOTES → memory.remember(category="reflection", metadata={person: ...})（合并到 reflection，不再独立 relationship 类别）

## 阶段 8：集成测试

- [x] 8.1 更新 `tests/test_integration/test_decoupled_flow.py`
  - StubLLM 支持 tool-use（返回带 tool_calls 的 AIMessage，然后第二次 invoke 返回 final answer）
  - 断言：messages 列表累积、tool_call 被 dispatch、impression 记忆在 Fold 后可召回
- [x] 8.2 新增 `tests/test_integration/test_fold_cycle.py`
  - 填满 history 触发 Fold → 验证 HistoryStore 替换 + impression 写入 + 原 episodic 仍可召回
- [x] 8.3 新增 `tests/test_world_engine/test_history_store.py`
- [x] 8.4 新增 `tests/test_world_engine/test_compressor.py`
- [x] 8.5 新增 `tests/test_npc/test_context_budget.py`
- [x] 8.6 tmpdir 隔离：所有 chromadb / history 路径用 tmp_path

## 阶段 9：文档与收尾

- [x] 9.1 更新 CLAUDE.md 的 "Architecture" 章节：加入 HistoryStore / Compressor / tool-use loop 的位置
- [x] 9.2 更新 `src/annie/npc/__init__.py` 和 `src/annie/world_engine/__init__.py` 的导出
- [x] 9.3 pyright: 新/改代码 0 error
- [x] 9.4 ruff check 通过
- [x] 9.5 归档本 change（`npx openspec archive`）— 留待用户确认

---

## 验收标准

1. 任何 `recall(..., type=)` 调用不复存在；统一为 `categories=`
2. `src/annie/world_engine/episodic.py` / `semantic.py` 不复存在
3. Executor 内没有"keyword 选工具"逻辑；`llm.bind_tools` 是唯一工具通道
4. HistoryStore JSONL 存在，Fold 可通过 token 阈值触发，impression 写入成功
5. `SkillAgent.try_activate` 固定返回 None 并触发 DeprecationWarning
6. 所有集成测试通过，至少覆盖：tool-use 多轮、Fold 完整周期、Micro 截断
7. pyright / ruff 干净

## 不在验收中

- Auto（后台定时）压缩
- Skill 的 `use_skill(name)` tool
- 情景预取
- Embedding 模型升级
- 剧本杀世界引擎 MVP（下一个 change）
- Query rewriting / hybrid search / rerank
