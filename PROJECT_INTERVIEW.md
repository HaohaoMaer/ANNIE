# ANNIE 项目面试深聊稿

> 简历中四条 bullet 的详细实现 + 面试可扩展方向。每一条都按照「简历原文 / 实现细节 / 设计取舍 / 可扩展话题」组织，便于逐点展开。

项目技术栈：Python · LangGraph · LangChain · ChromaDB · Pydantic · pytest

代码位置：
- NPC Agent 层：`src/annie/npc/`
- World Engine 层：`src/annie/world_engine/`
- 端到端集成测试：`tests/test_integration/test_decoupled_flow.py`

---

## Bullet 1 — 三大协议解耦 World Engine 与 NPC Agent

> 设计 `AgentContext / AgentResponse / MemoryInterface` 三大协议，将 World Engine（世界状态 / 记忆 / 业务工具）与 NPC Agent（无状态通用认知框架）完全解耦，保证框架在不同游戏类型间零改动复用。

### 实现细节

**1. 分层的硬边界**

- `src/annie/npc/` 下**禁止**出现任何业务词汇（剧本杀、线索、沙盒……）或 `chromadb` 导入，这是在 CLAUDE.md 里写死的不变量。
- 所有 per-NPC 的数据（身份、记忆、工具、规则）都**只通过一次 `run(AgentContext)` 调用**从世界引擎注入，不允许在 `NPCAgent.__init__` 留任何状态。这保证了一个 `NPCAgent` 实例可以在同一进程里并行驱动任意多个 NPC（见 `src/annie/npc/agent.py:40-110`）。

**2. `AgentContext` 三层结构**（`src/annie/npc/context.py`）

- **强类型核心层**：`npc_id`、`input_event`、`tools: list[ToolDef]`、`skills: list[SkillDef]`、`memory: MemoryInterface`——这些是代码会直接引用的机械依赖，Pydantic 强制非空。
- **提示词文本层**：`character_prompt / world_rules / situation / history`——完全自由的字符串，框架只负责搬运，不负责解析。
- **开放扩展层**：`extra: dict[str, Any]`——用于世界引擎传递任何临时元数据（比如场景、房间、同场 NPC 列表），也被工具子系统借道传递运行期状态（`_tool_registry`、`_skill_agent`、`_recall_seen_ids` 等，见 `agent.py:74-79`）。

为什么是三层而不是一个大 dict：强类型核心保证代码 refactor 时编译器能帮你抓错；提示词层不放进强类型是因为它对 LLM 才有意义，放入类型反而会诱导代码尝试解析；`extra` 兜底，避免每加一个世界侧小字段就要改协议。

**3. `AgentResponse`**（`src/annie/npc/response.py`）

单向返回通道：`dialogue / inner_thought / actions / memory_updates / reflection`。世界引擎不直接读 Agent 的内部状态，只消费这个纯数据对象。

**4. `MemoryInterface` 协议**（`src/annie/npc/memory/interface.py`）

```python
class MemoryInterface(Protocol):
    def recall(query, categories, k) -> list[MemoryRecord]        # 向量相似度
    def grep(pattern, category, metadata_filters, k)              # 字面子串 + 元数据
    def remember(content, category, metadata)                     # 写入
    def build_context(query) -> str                                # 返回提示词就绪的摘要
```

- 用 `typing.Protocol` 而不是 ABC，让实现方只需"形似"即可——单元测试里的 FakeMemory、ChromaDB 实现、未来可能的 Redis/Postgres 实现都能直接插入，无需继承。
- `category` 是**开放字符串**不是 enum：业务方可以自由扩展（比如"线索"类记忆）而不必改 NPC 层协议。常用 5 个类别（`semantic / reflection / impression / episodic / todo`）以模块常量形式导出，仅作约定。

**5. 默认世界引擎实现**（`src/annie/world_engine/default_engine.py`）

`DefaultWorldEngine` 组合了 `DefaultMemoryInterface` + `HistoryStore` + 可选 `Compressor`。`build_context` 渲染最近 20 轮历史、调用 `memory.build_context` 得到记忆摘要、组装 `AgentContext` 返回；`handle_response` 把对话追加到 JSONL、调用 `compressor.maybe_fold`。

### 设计取舍

- **Protocol vs ABC**：Protocol 是结构化子类型，对 NPC 层更轻量，避免 Agent 代码反向依赖世界引擎的类。
- **单次注入 vs 逐次调用**：相比 "Agent 持有 memory 字段" 的做法，AgentContext 单次注入让 Agent 本体彻底无状态，便于并行、便于测试。
- **为什么不用 DI 容器**：项目规模决定了手动注入可读性更高；而且 LangGraph 本身的 state 字典已经是一种轻量 DI。

### 面试可扩展话题

- **并发模型**：因为 Agent 无状态，多 NPC 场景下可以共用一个 `NPCAgent` + 一个 LLM client，节省连接数和 token 预算计算的开销。
- **测试策略**：`tests/test_integration/test_decoupled_flow.py` 里的 `_StubLLM` 用预设 `AIMessage` 列表 + 调用计数替代真实 LLM——这是解耦的直接红利。
- **对照反例**：早期原型把记忆类、社交图谱类全塞进 `NPCAgent.__init__`，结果每加一个游戏类型就要改 Agent 构造器。重构的直接动机就是这个。
- **如何扩展到新游戏类型**：新游戏只写一个 `WorldEngine` 子类 + 必要的业务 `ToolDef` / `SkillDef`，NPC 层零改动。业务工具通过 `AgentContext.tools` 注入，业务技能通过 `AgentContext.skills` 注入。

---

## Bullet 2 — Planner-Executor-Reflector 认知架构

> 构建 Planner-Executor-Reflector 认知架构：Planner 采用 skip-first 策略仅对复杂事件拆解任务，Executor 以原生 tool-use 循环执行 ReAct，空结果经 retry 边回流重规划，Reflector 结构化输出 REFLECTION / FACTS / RELATIONSHIP_NOTES 写回分类记忆。

### 实现细节

**1. LangGraph 连线**（`src/annie/npc/agent.py:117-127`）

```
START → planner → executor → (conditional) → reflector → END
                                   │
                                   └── retry edge → planner
```

`_should_retry`（`agent.py:147-158`）：当 `execution_results` 为空或所有任务 `FAILED` 且 `retry_count < max_retries` 时走 retry，把 `loop_reason` 与 `last_tasks` 写回 state。

**2. Planner：skip-first 策略**（`src/annie/npc/planner.py`）

静态提示词第一条就是「DEFAULT: 返回 `{"skip": true, ...}`」，只有真正需要顺序推进的事件（"先去厨房取证据再回来质询"、"连问三个人比对口供"）才拆任务，上限 3 条。

为什么默认 skip：
- 剧本杀类场景 80% 的事件是单轮对话，不需要拆解。Planner 乱拆只会放大 token 成本、拖慢响应，还可能让人格表演变得僵硬（"先思考再回答"会丢掉自然的对话感）。
- Planner 动态提示词**故意不渲染 history**——history 只给 Executor 作为消息序列使用。Planner 看到 history 会过度倾向于"基于历史规划"，反而助长拆分。

`__skip__` 标记（`executor.py:42`）：Planner 返回 skip 时，`_executor_with_skip` 合成一个 marker task，Executor 只渲染 `<input_event>`，避免冗余的 `<task>` 区块。

Retry 时在 user_content 追加 `<retry_context>` 区块，告诉 Planner 上一次的 `loop_reason` 和任务列表，避免重复犯错（`planner.py:77-86`）。

**3. Executor：原生 tool-use 循环**（`src/annie/npc/executor.py:128-213`）

系统提示词按固定顺序拼 XML 区块：

```
<character> <world_rules> <situation> <memory_categories>
<working_memory> <todo> <available_skills>
```

循环结构：

```python
for step in range(max_loops=8):
    messages[:] = budget.check(messages, llm)          # 应急折叠
    tool_defs = tool_registry.list_tools()             # 每轮重读,支持 use_skill 动态扩能
    response = llm.bind_tools(tool_defs).invoke(msgs)
    messages.append(response)
    if not response.tool_calls: return response        # 最终回答
    for call in response.tool_calls:
        result = tool_agent.dispatch(call, ctx)        # 含 Micro 压缩
        messages.append(ToolMessage(result, call.id))
```

关键设计点：
- **原生 `bind_tools` vs 自己写 ReAct 文本协议**：原生工具调用由 LLM SDK 保证 JSON schema 正确，不用自己写正则解析 `Action: foo\nInput: {...}`，错误率低很多，且能直接利用模型的 function-calling 微调。
- **每轮重读工具列表**：支持 `use_skill` 在本轮之后动态 push frame、下一轮就能 bind 上新工具。这一点让"技能"变成了运行时能力扩展而不是静态清单。
- **try/finally 清理帧栈**：任务结束必须 pop 掉本轮 push 进来的技能帧，不然下一任务会"偷"上一任务激活的工具。有 `_skill_frames` 主线 + 栈深度差值兜底双重保险。

**4. Reflector：结构化输出 + 分类写回**（`src/annie/npc/reflector.py`）

提示词要求返回三段：
```
REFLECTION: <2-4 sentence>
FACTS: ["...", "..."]
RELATIONSHIP_NOTES: [{"person": "...", "observation": "..."}]
```

解析采用**两级容忍**（`_parse_list` / `_parse_rel_notes`）：先尝试 JSON，失败了用 bullet list 兜底，再失败返回空。LLM 结构化输出不稳定是常态，容忍式解析比"严格失败重试"更经济。

三类分别写入不同记忆类别：
- `REFLECTION` → `category=reflection`
- `FACTS` → `category=semantic`
- `RELATIONSHIP_NOTES` → `category=reflection`, 带 `metadata={"person": name}`

这样 Reflector 的输出和 Bullet 3 的分类召回天然对接。

### 设计取舍

- **三节点 vs 一节点**：早期有过"让一个大 prompt 同时做规划+执行+反思"的尝试，结果就是模型在三个角色间漂移、输出质量都打折。拆成三个有界责任的节点后，每个 prompt 职责单一，可独立迭代。
- **retry 上限 1**：再多会放大 Planner 错误——如果 Planner 连续两次拆错任务，多半是输入事件本身模糊，退出 fallback（skip + 单任务）比无限重试更合理。
- **Reflector 为什么不能并入 Executor**：Reflector 必须在所有任务结束后跑，才能看到完整执行链；而且反思写记忆是"跨 run 投资"，和 Executor 的"本 run 产出"是不同时间尺度的工作。

### 面试可扩展话题

- **为什么不是 ReAct / CoT / Plan-Execute 标准三件套**：本项目的 Planner skip-first 更接近"选择性拆解"——因为 NPC 场景 80% 是对话驱动，不是任务驱动。标准 Plan-Execute 假设所有输入都需要计划，这里反过来。
- **LangGraph 选型理由**：相比 AutoGen 多 agent 协商、CrewAI 角色流，LangGraph 的显式状态机更适合"可调试、可回放"的要求。state 字典是 LangGraph 原生支持的，可以原地 checkpoint。
- **Tracer 观察点**（`src/annie/npc/tracing.py`）：每个节点用 `tracer.node_span` 包装、工具调用打 `TOOL_INVOKE`，可导出时间线做性能分析。
- **MAX_TOOL_LOOPS=8 的选择**：经验值，足够完成"查两次记忆 + 用一次技能 + 最终回答"的复杂 case，又不会让模型陷入循环。超上限 warn + 返回最后一次 AIMessage（部分降级）。

---

## Bullet 3 — 双通道记忆检索 + 跨会话 Todo

> 设计双通道记忆检索（向量 recall + 字面 grep）与单 run 去重，规避 RAG 对专有名词召回弱的问题；跨会话 Todo 以事件流形式存入统一记忆接口，在提示中动态渲染 todo 区块。

### 实现细节

**1. 为什么需要 grep**

RAG / 向量召回对"语义相似"很强，但有两个盲区：
- **专有名词**：问"李四说过什么"，embedding 可能把"李四"与"张三"嵌得很接近（都是人名），召回结果漂移。
- **结构化查询**：想找 `category=todo && status=open` 这种精确元数据条件，向量检索根本不适用。

所以设计了 `grep(pattern, category, metadata_filters, k)`：
- 字面子串匹配（`casefold()` 大小写不敏感）
- 可按 category 筛
- 可按 metadata 精确相等筛
- 结果按 `created_at` 倒序（最新优先），`relevance_score=1.0`（字面命中无相似度概念）
- `pattern=""` 是"纯按筛选条件返回"的约定

实现位置：`src/annie/world_engine/memory.py:89-116` → 底层 `MemoryStore.grep_entries` 用 Chroma 的 `collection.get(where=...)` + Python 侧 `casefold()`。

**2. 两个通道一起暴露给 LLM**

`memory_recall` 和 `memory_grep` 都是内建工具（`src/annie/npc/tools/builtin.py:59-121`），描述里明确指导 LLM「专有名词 / 精确短语用 grep，模糊语义用 recall」。模型自己决定用哪个——这是 tool-use 范式的好处，不需要应用层做路由。

**3. 单 run 去重**

`agent.py:79` 初始化 `extra["_recall_seen_ids"] = set()`。
- 运行开始时 `MemoryAgent.build_context` 就把 `<working_memory>` 里展示的记录 content 加入 seen。
- 后续 `memory_recall` / `memory_grep` 命中 seen 的记录会被过滤掉（`builtin.py:37-56`）。
- 去重粒度是**单次 run**，下一次 run 的 seen 集合重新开。

为什么要去重：没有它，LLM 看到 `<working_memory>` 里已经有的东西，还会习惯性地再调一次 `memory_recall` 拿同样的结果，浪费 token 也浪费轮次。

**4. 默认 MemoryInterface 的额外设计**（`src/annie/world_engine/memory.py`）

- **向量存储只放蒸馏内容**：只写 `reflection / semantic / impression / todo`，不写 `episodic`。episodic 的原始对话由 `HistoryStore` (JSONL) 承担，职责分离。
- **去重语义**：`semantic / reflection` 两类用 `sha1(category|content|person)[:16]` 作稳定 id，`upsert` 避免重复事实堆积；其他类别用 uuid + add（impression 摘要覆盖不同时间窗，不能去重）。
- **印象加权**：`recall` 里给 `impression` 类命中乘 1.2× relevance（长期记忆蒸馏的价值高于原始事实）。

**5. 跨会话 Todo：事件流模型**（`src/annie/npc/tools/builtin.py:206-300`）

`plan_todo` 工具三种操作：
- `add(content)`：写入一条 `category=todo, metadata={status: open, todo_id: <8hex>, created_at: ISO}`，返回 todo_id。
- `complete(todo_id)`：**追加一条新记录** `{status: closed, closes: <todo_id>}`（绝不修改原记录）。完成前会先 grep 验证 open 记录存在、且没有同 id 的 closed 记录。
- `list`：grep 所有 open 和 closed，用 Python 差集算出 alive。

为什么是事件流而不是 update：
- `MemoryInterface` 协议里没有 update 方法——加了就是破坏最小协议原则（Protocol 越简单实现方越好写）。
- 事件流天然可审计（任何时候都能重放出 todo 历史），写入幂等（重复 complete 会因为 closed 记录已存在而失败）。
- 代价是 list 需要 O(open+closed) 扫描——但 todo 数量级一般很小，实测没问题。

**6. `<todo>` 区块动态渲染**

运行开始时 `render_todo_text(context.memory)` 计算一次 alive todos，写入 `state["todo_list_text"]`（`agent.py:105`）；Executor 把它填进系统提示词的 `<todo>` 区块。这样 NPC 能"记住上次没做完的事"，在新一轮对话里主动推进。

集成测试 `tests/test_integration/test_cross_run_todo.py` 验证：run1 add → run2 可见 → run2 complete → run3 不可见。

### 设计取舍

- **单 run 去重只记 content 字符串**：没用记录 id 是因为 MemoryRecord 的 id 不在协议里；content 字符串作为去重键足够，碰撞率可忽略。
- **event-stream todo**：选这个而不是 soft-delete / mutable record，最大收益是"协议最小"，代价是 list 稍慢。
- **grep 返回 `relevance_score=1.0`**：不装作有排序权重，让 LLM 通过文档看到这是字面匹配。

### 面试可扩展话题

- **为什么不直接让 LLM 路由**：有些架构会让一个"路由 agent"决定走 recall 还是 grep。这里选择把两个都作为工具暴露、让主 LLM 自己决定——少一个 LLM 调用、少一个失败点，也更利用了 function calling 天然的路由能力。
- **Chroma 的 where 子句语法**：`{"$and": [...]}` 是 Chroma 特有的，grep 实现里对单条件和多条件分别处理避免它的 schema 限制（`memory.py:96-106`）。
- **如果换后端（PGVector / LanceDB）**：只需重写一个 `MemoryInterface` 实现，NPC 层零改动——这又回到 Bullet 1 的解耦红利。
- **todo 如果数量爆炸怎么办**：可以给 todo 加 `expires_at` 元数据、定期 grep 清理；或者把"关闭超过 N 天"的 todo prune 掉。
- **recall 里 `_MIN_RELEVANCE=0.35` 的阈值**：来自实测——低于这个相似度的结果混入提示词反而污染模型注意力。

---

## Bullet 4 — 三级上下文压缩

> 设计三级上下文压缩：工具响应微缩(Micro) → Executor 单轮消息应急折叠(Emergency) → 跨运行对话历史沉淀为印象记忆(Fold)，分别覆盖单条工具输出、单轮上下文超限、长期记忆蒸馏三个边界。

### 实现细节

三级压缩器作用域、触发条件、产出都不同，刻意错位以覆盖完整的生命周期：

| 层级 | 位置 | 作用域 | 触发条件 | 产出 |
|---|---|---|---|---|
| **Micro** | `ToolAgent.dispatch` | 单条 ToolMessage | `len(content) > 2000` 字符 | 头 40% + `[...truncated...]` + 尾 | 
| **Emergency** | `ContextBudget.check` | Executor 单轮消息列表 | `tokens + reserve > limit*0.9` | LLM 摘要最早轮次 → SystemMessage，保留最新 2 轮 |
| **Fold** | `Compressor.maybe_fold` | 跨 run 的 JSONL 历史 | 未折叠窗口 tokens > 3000 | LLM 摘要 → 写入 `category=impression` 记忆 + 游标推进 |

**1. Micro — 工具响应微缩**（`src/annie/npc/sub_agents/tool_agent.py`）

```python
MICRO_MAX_CHARS = 2000
_MICRO_HEAD_FRACTION = 0.4

def _micro_compress(text):
    if len(text) <= max_chars: return text
    head_len = max_chars * 0.4
    tail_len = max_chars - head_len - len(markers)
    return f"{text[:head_len]} [... truncated ...] {text[-tail_len:]}"
```

为什么头 40% + 尾 60%：工具响应一般是"元数据 + 结果列表"，头部保 schema/状态，尾部保最新记录（`memory_grep` 返回倒序）。比中间截断保信息更多。

为什么不做 LLM 摘要：
- 成本：每次工具响应都调 LLM 摘要，成本会线性放大。
- 延迟：多一次 round-trip。
- Micro 只处理"单条工具响应异常膨胀"这种边界情况（比如某次 memory_recall 返回了 20 条巨大记录），不是常规优化。

**2. Emergency — Executor 单轮应急折叠**（`src/annie/npc/context_budget.py`）

触发阈值：`int(model_ctx_limit * 0.9)`，预留 `reserve_output=4096` 给最终回答。token 估算用 `chars / 2.5` 的简单估计（CJK 略偏保守，比精确 tokenize 便宜 100 倍，可接受）。

折叠策略：
1. 保留所有 SystemMessage。
2. 保留最新 2 轮 Human-initiated 对话（Human → AI → ToolMessages 的序列）。
3. 把最早的 head 段（不含 system、不含保留尾部）交给 LLM 摘要成 3-6 个 bullet point。
4. 用一条 `SystemMessage("[earlier tool work summary]\n{summary}")` 替代整个 head。

为什么保留"最近 2 轮 Human"而不是"最近 N 条消息"：ReAct 循环里一条 Human → 多条 AI/Tool 是原子性的，从中间切断会破坏对话完整性。以 Human 为锚点切分能保证每一轮完整。

为什么是应急而不是常规：90% 的上下文不需要 Emergency——只有 tool-use 循环打到 6-7 轮、且每轮 ToolMessage 都很大的罕见场景才会触发。常规优化交给 Fold 在"跨 run"层面处理。

**3. Fold — 跨运行印象沉淀**（`src/annie/world_engine/compressor.py`）

Fold 是唯一会**写入向量存储**的压缩器，其他两个纯内存。

游标驱动：
- `HistoryStore` 的 `.meta.json` sidecar 保存 `last_folded_turn_id`。
- `estimate_tokens_after_cursor` 只计算游标之后的 entries。
- 超阈值 → 选取游标后最老的 `FOLD_TARGET_TOKENS=1500` 的切片 → LLM 摘要 → 写入 `category=impression` → 游标推进到切片尾 turn_id。
- **不改 JSONL**，JSONL 是 append-only。

为什么游标而不是"改标记位"：
- JSONL append-only 对并发友好，游标外挂到 sidecar 避免了"读-改-写"大文件。
- 游标天然防递归折叠：已折叠的内容永远在游标之前，不会再被摘成摘要。
- 可重放：如果将来想改摘要策略，删游标重新跑即可。

摘要提示词（`FOLD_SUMMARY_PROMPT`）强制三要素：WHO 对 WHOM 做了 WHAT、情绪基调、明确事实。第三人称过去时，保留专有名词——这些都是"难以 re-derive"的高价值信息，普通字段不摘。

**4. 三级协同**

一次 Executor 运行中可能全部触发：
- 每个 ToolMessage 过 Micro（即使没超 2000 也走这个函数）。
- 每轮 LLM 调用前过 Emergency（一般不触发）。
- 任务结束、WorldEngine.handle_response 里可能过 Fold（跨 run 沉淀）。

粒度不同也意味着它们作用于不同的生命周期资源：
- Micro 保护单次工具调用的 token 预算。
- Emergency 保护模型的上下文窗口。
- Fold 保护长期记忆的可检索性（不然 20 轮后所有 dialogue 都堆在 history 里）。

### 设计取舍

- **为什么不统一成一个"智能压缩器"**：一个组件同时懂原始对话、懂工具响应、懂模型窗口，会变成上帝对象。错位分层让每一级职责清晰、独立测试、独立调阈值。
- **Prune 没纳入压缩**：`HistoryStore.prune` 是物理删 JSONL 行，不产出摘要、不进 prompt——是存储 GC，不是上下文压缩。这是有意区分的，避免概念混淆。
- **阈值都是经验值**：`MICRO_MAX_CHARS=2000`、`ctx_limit*0.9`、`FOLD_TOKEN_THRESHOLD=3000` 都是实测后拍板。后续可以做自适应（比如按模型窗口动态计算 Fold 阈值）。

### 面试可扩展话题

- **token 估算策略**：`chars/2.5` 粗略估计 vs `tiktoken` 精确估算的权衡——粗估够用且无外部依赖、可 CJK 友好，精估延迟不可忽略。
- **为什么 Emergency 保留 2 轮而不是 1 轮**：1 轮不够让模型接住上下文，3 轮以上又没必要。实测 2 轮是帕累托点。
- **Fold 产出的 impression 如何进入新 run**：Reflector 写的 reflection + Fold 写的 impression 都落在向量库，新 run 的 `build_context` 会把它们 recall 出来放进 `<working_memory>`。这是"短期→长期"的完整闭环。
- **如果 LLM 摘要失败**：Emergency 里 catch 异常后返回原消息（降级），Fold 里空摘要会放弃本次折叠并记 warning——两者都是"宁可多占 token，不可丢信息"。
- **对比别人的做法**：LangChain 的 `ConversationSummaryBufferMemory` 只有一级滚动摘要；AutoGPT 的 memory 也类似单级。三级错位是本项目针对"长对话 NPC"的专门设计。

---

## 附：端到端调用链（一次 `run` 做了什么）

```
WorldEngine.build_context(npc_id, event)
    ├─ 读 HistoryStore 最近 20 轮 → ctx.history
    ├─ DefaultMemoryInterface.build_context → ctx.situation 或 working_memory
    └─ 组装 AgentContext
                │
                ▼
NPCAgent.run(ctx):
    MemoryAgent.build_context → state["working_memory"]   # 含单 run 去重 seed
    render_todo_text(memory)  → state["todo_list_text"]
    Planner
        ├─ skip-first 判断
        └─ (retry 时带 <retry_context>)
    Executor (per task):
        initial messages: XML system + history → AIMessage → HumanMessage(task)
        while True:
            ContextBudget.check                       # Emergency
            llm.bind_tools(registry.list_tools()).invoke
            if no tool_calls: break
            for call: ToolAgent.dispatch              # Micro
        (try/finally: pop_frame 所有本任务 push 的技能帧)
    _should_retry: 空结果 → 回 Planner
    Reflector:
        LLM 生成 REFLECTION / FACTS / RELATIONSHIP_NOTES
        MemoryAgent.store_reflection / store_semantic / store_relationship_note
                │
                ▼
AgentResponse → WorldEngine.handle_response
    ├─ HistoryStore.append(dialogue)
    └─ Compressor.maybe_fold → impression 记忆        # Fold
```

## 附：面试追问预案

- **"这个项目有多少行代码 / 写了多久"**：诚实报。重点是"架构演进"——从单层端到端 demo 重构成两层解耦，过程中删除了 `cognitive/` `social_graph/` 等重耦合模块。
- **"LLM 选型"**：框架对 LLM 不耦合，任何 LangChain `BaseChatModel` 兼容的 provider 都可以。测试里用 `_StubLLM`。
- **"没做什么功能"**：多 NPC 之间的对话协调、场景调度这一层在 `WorldEngine` 实现里，当前只有 `DefaultWorldEngine` 的基础实现，剧本杀 Demo 层正在基于新架构重建。诚实说比吹已完成更安全。
- **"和 LangGraph 官方 ReAct 模板比"**：官方模板只有 ReAct 一节点；本项目三节点 + 显式 retry + per-task 隔离的 tool 帧栈，是针对 NPC 场景的定制。
- **"为什么选 Pydantic 而不是 dataclass"**：LangChain / LangGraph 生态原生用 Pydantic；`AgentContext.model_rebuild()` 解 forward ref 也是 Pydantic 的能力。
- **"生产环境部署过吗"**：个人项目未生产部署。如果要上线，需要补的是：(a) Tracer → OpenTelemetry、(b) 每 NPC 一个 Chroma collection 的扩展性（海量 NPC 可能要换 PG/PGVector）、(c) 限流与 cost guard。

---

_文档生成时间：2026-04-15。随代码演进可能产生漂移，优先以 `src/` 和 `CLAUDE.md` 为准。_
