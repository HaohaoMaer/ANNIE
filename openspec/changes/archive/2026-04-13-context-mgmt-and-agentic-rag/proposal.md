# Proposal: 分层上下文管理、多类别长期记忆与 Agentic RAG

## Why

Phase 0-2 重构完成后，NPC ↔ WorldEngine 的两层解耦虽然接口已立，但以下几条核心问题尚未解决，直接阻塞"剧本杀世界引擎 + 单 NPC 审问闭环"这个下一里程碑：

1. **上下文管理缺位**。`AgentContext` 被当成一次性静态 envelope 使用，`Executor` 对每个 task 只做一次 `llm.invoke`，不维护 messages 列表、没有 tool-use 多轮循环。`AgentContext.history` / `situation` / `world_rules` 字段在 Executor 中**根本没被读取**。结果是 NPC 的"动态上下文"实际上只有 `character_prompt` 这一项。
2. **工具实际上不是工具**。`ToolAgent.try_tool` 通过关键词匹配**预先跑一个工具**、把结果字符串拼进 user message，模型从未获得 tool-use 决策能力。长期看这会把业务工具的调用逻辑推到关键词匹配里，无法扩展。
3. **长期记忆召回是 Naive RAG 且结构僵化**。`DefaultMemoryInterface` 把两个 ChromaDB collection 硬编码为"episodic = reflection only"与"semantic = 其他一切"，`recall` 的 `type` 语义模糊（既是过滤器又是路由器）。无法表达"多类别混合召回"、"impression 加权"这类查询，也阻碍后续引入"对话折叠摘要"等记忆类别。
4. **没有压缩策略**。NPC 的跨 run 对话历史、单 run 内工具调用累积，目前都没有任何"瘦身"机制。任何中等长度的 scene 都会直接碰到 context window 上限。
5. **Skill 的 keyword 自动激活不可用**。当前实现把 skill 的 `prompt_template` 永久注入 system prompt、且通过关键词匹配自动选取，既缺生命周期也缺显式触发。在 tool-use loop 建立之前，这条路径应当冻结而不是继续添砖。

上述问题环环相扣：不解决记忆分类，压缩折叠的产物无处安放；不落地 tool-use loop，Agentic RAG（模型自主多轮召回）就无从谈起；不引入上下文压缩，世界引擎没法真正跑起完整的一幕剧本。

## What Changes

本次变更一次性建立**上下文管理 + 多类别记忆 + 原生工具循环**三项能力，为后续"剧本杀世界引擎 MVP"铺平道路。

### 1. 上下文管理分层（context-compression 新增 capability）

按生命周期把上下文切成清晰的四档：

- **Stable**（`character_prompt` / `world_rules`）：WorldEngine 组装，Agent 只读。
- **Rolling**（`DialogueHistory` / `SceneState`）：WorldEngine 持有跨 run 累积，**压缩主战场**。
- **Long-term**（多类别 ChromaDB 记忆）：WorldEngine 持有，Agent 通过 `memory_recall` 工具按需查询。
- **Working**（单 run 内的 `messages` / 工具结果 / 召回回流）：Agent 持有在 `AgentState` 中，run 结束即亡。

在此之上定义五种压缩策略，按归属落位：

| 策略     | 作用对象           | 归属        | 触发                       |
|----------|--------------------|-------------|----------------------------|
| Trim     | DialogueHistory    | WorldEngine | 每次 `build_context` 前    |
| Fold     | 连续 N 条 history   | WorldEngine | token 阈值 / scene 切换    |
| Auto     | history 整体        | WorldEngine | 后台/定时                  |
| Micro    | 单条工具输出 / 记忆 | Agent       | 插入 messages 时           |
| Emergency| Agent.messages     | Agent       | LLM 调用前预算超限         |

本次 change 实装 **Trim + Fold + Micro + Emergency**；Auto 作为 Fold 的调度器留待后续。

### 2. 长期记忆多类别统一（memory-interface 修订）

坍缩当前的 episodic/semantic 双 collection 为**单 ChromaDB collection + `category` metadata**，初始约定四类（均为开放字符串，不做枚举）：

- `episodic` — 原始经历（来自 handle_response 的对话落盘）
- `semantic` — 客观事实
- `reflection` — 自我分析（来自 Reflector）
- `impression` — ★ 新增：Fold 产物"遗忘细节、留下印象"

接口签名调整：

```python
# Before
recall(query, type: str | None, k: int) -> list[MemoryRecord]

# After
recall(query, categories: list[str] | None = None, k: int = 5) -> list[MemoryRecord]
```

`categories=None` 代表跨全类别召回；`impression` 类别在召回阶段加权（配置项，默认加权 1.2×）。

### 3. Fold 语义与落盘（"遗忘细节，留下印象"）

Fold 触发时，WorldEngine 拿原始 N 条 history turn 交给**主 LLM**（同一个，不引入新模型依赖）做摘要，产物同时：

- **替换**掉 HistoryStore 中这 N 条原始 turn，new entry 标 `is_folded=True` 不再参与二次折叠
- **回写**到 MemoryBackend 的 `impression` 类别，保留 `scene` / `time_range` / `source="fold"` metadata
- 原始 turn **不**从 `episodic` 类别删除——深层记忆仍可被 `memory_recall(categories=["episodic"])` 唤出

结果是三层记忆深度：**History（清晰当下）→ Impression（模糊印象）→ Episodic（深层追忆）**。

### 4. Executor 迁移到原生 tool-use loop（tool-skill-system 修订）

- Executor 使用 `llm.bind_tools(tools)` 的原生 tool-use 通道传递 ToolDef 的 JSON schema；废弃"关键词匹配预跑工具、结果拼 prompt"。
- `ToolAgent` 由"选择器"退化为"dispatcher + error boundary"，不再做 keyword matching。
- `AgentState` 扩充 `messages: list[BaseMessage]` 作为 run 内 working context；Executor 内部跑标准 observe-think-act 循环直至模型输出无 tool_call 的 final answer。
- 每轮 LLM 调用前走一次 `ContextBudget.check()`，按需触发 Micro / Emergency 压缩。

### 5. Skill 能力冻结（tool-skill-system 修订）

- `SkillDef` / `SkillRegistry` 接口保留；`SkillAgent.try_activate` 改为 no-op 并打 `DeprecationWarning`。
- 后续的 `use_skill(name)` 显式触发 + 渐进披露方案**不在本次 change 内**，留给独立 change。
- Executor 不再尝试自动注入 skill prompt；所有 NPC 能力通过 tool-use 暴露。

### 6. WorldEngine 新增组件（world-engine 修订）

- 新增 `HistoryStore`（rolling window，per-NPC）——追加、渲染、按 token 测量。
- 新增 `Compressor`——封装 Trim/Fold/Auto 逻辑，依赖 `HistoryStore` + `MemoryBackend` + LLM。
- `WorldEngine.build_context` 标准化步骤：拼 character → 叠 world_rules → 渲染 history（已被 Compressor 处理过） → 传入 MemoryInterface。
- `WorldEngine.handle_response` 标准化步骤：dialogue 追加到 HistoryStore → 若超阈值触发 Fold → reflection 走 `memory.remember(..., category="reflection")`。

## Impact

### 受影响模块

- `src/annie/npc/context.py` — 无需改动（AgentContext envelope 语义保持）
- `src/annie/npc/state.py` — `AgentState` 新增 `messages` / `context_budget` 字段
- `src/annie/npc/executor.py` — 重写为 tool-use loop；删除"预跑工具"路径
- `src/annie/npc/sub_agents/tool_agent.py` — 退化为 dispatcher
- `src/annie/npc/sub_agents/skill_agent.py` — `try_activate` → no-op
- `src/annie/npc/sub_agents/memory_agent.py` — 接口调整为 `categories: list[str]`
- `src/annie/npc/memory/interface.py` — `recall` 签名变化，`MemoryRecord.type` → `category`
- `src/annie/npc/tools/builtin.py` — `memory_recall` 参数改为 `categories`
- `src/annie/world_engine/memory.py` — 坍缩 episodic+semantic 为单 collection
- `src/annie/world_engine/episodic.py` / `semantic.py` — 合并为 `store.py`（单实现）
- `src/annie/world_engine/base.py` — `WorldEngine` 增加 `HistoryStore` / `Compressor` 协作位
- `src/annie/world_engine/default_engine.py` — 采用新 HistoryStore / Compressor

### 新增模块

- `src/annie/world_engine/history.py` — `HistoryStore`
- `src/annie/world_engine/compressor.py` — `Compressor`
- `src/annie/npc/context_budget.py` — `ContextBudget`（micro / emergency 压缩）

### 删除模块

- `src/annie/world_engine/episodic.py` / `semantic.py` —— 合并为 `store.py`

### 破坏性变更

- `MemoryInterface.recall(type=)` → `recall(categories=)`。任何现有调用方需同步。
- `MemoryRecord.type` → `MemoryRecord.category`。
- `ChromaDB` 集合布局变更。**现有本地 `./data/vector_store/` 需清空重建**——本 change 不写迁移脚本。
- `Executor` 不再支持"预跑工具塞 prompt"语义；所有工具必须通过 `ToolDef.call` + bind_tools 被触发。
- `SkillAgent.try_activate` 进入 deprecated 状态；任何依赖 skill 自动激活的旧测试立即失效。

### 不受影响

- `NPCAgent` 的公开 `run(context)` 签名
- `AgentContext` / `AgentResponse` 字段
- `MemoryInterface` 作为 Protocol 的身份
- LangGraph 节点拓扑（Planner → Executor → Reflector + 重试边）

## Non-Goals（本次不做）

- **Auto 压缩调度**：Fold 只由 handle_response 内阈值触发，不引入后台 / 定时任务。
- **Skill 完整能力**：`use_skill(name)` tool、渐进披露、子 agent fork 不在本次。
- **情景预取**：WorldEngine 不做基于事件元数据的"主动预召回"，完全由模型通过 tool 驱动召回。
- **检索增强**：query rewriting、hybrid BM25、cross-encoder rerank 暂不上；保持 Naive vector 召回。
- **Embedding 模型升级**：ChromaDB 默认 `all-MiniLM-L6-v2` 保持，不引入 bge / OpenAI embedding。
- **剧本杀世界引擎 MVP**：本次只提供 HistoryStore / Compressor / tool-use loop 的基础设施；`ScriptedMurderEngine` 的具体实装在独立 change。
- **递归折叠**：`is_folded=True` 的 entry 即终态，不再参与二次 fold。
- **旧 demo 恢复**：继续与 Phase 0-2 保持一致的暂时失效状态。
