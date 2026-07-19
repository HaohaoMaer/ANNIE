# ANNIE 项目面试深聊稿

> 简历 bullet 的详细实现 + 面试可扩展方向。每一条按「简历原文 / 实现细节 / 设计取舍 / 可扩展话题」组织。

项目技术栈：Python 3.11+ · LangGraph · LangChain · ChromaDB · Pydantic · pytest

代码位置：
- NPC Agent 层：`src/annie/npc/`
- World Engine 层：`src/annie/world_engine/`
- 端到端集成测试：`tests/test_integration/test_decoupled_flow.py`

---

## Bullet 1 — 三大协议解耦 World Engine 与 NPC Agent

> 设计 `AgentContext / AgentResponse / MemoryInterface` 三大协议，将 World
> Engine（世界状态 / 记忆 / 业务工具）与 NPC Agent（无状态通用认知框架）完全解耦，
> 保证框架在不同游戏类型间零改动复用。

### 实现细节

**1. 分层的硬边界**

- `src/annie/npc/` 下禁止出现任何业务词汇（剧本杀、线索、沙盒……）或 `chromadb`
  导入，由代码审查强制执行。
- 所有 per-NPC 数据通过一次 `run(AgentContext)` 调用注入，`NPCAgent.__init__`
  不保留任何 NPC 状态。同一个 `NPCAgent` 实例可在同一进程里并行驱动任意多个 NPC。

**2. AgentContext 三层结构**（`src/annie/npc/context.py`）

- **强类型核心层**：`npc_id`、`input_event`、`tools: list[ToolDef]`、
  `skills: list[SkillDef]`、`memory: MemoryInterface`、`graph_id`、`route`
  — 代码直接引用的机械依赖，Pydantic 强制非空。
- **提示词文本层**：`character_prompt / world_rules / situation / history / todo`
  — 完全自由的字符串，框架只搬运不解析。
- **开放扩展层**：`extra: dict[str, Any]` — 传递临时元数据（场景、房间、
  同场 NPC 列表），工具子系统借道传递运行期状态（`_tool_registry`、
  `_recall_seen_ids` 等）。

设计动机：强类型核心让编译器帮你抓 refactor 错误；提示词层放进类型反而诱导
代码尝试解析 LLM 文本；`extra` 兜底避免每加一个小字段就改协议。

**3. AgentResponse**（`src/annie/npc/response.py`）

单向返回通道：`dialogue / inner_thought / actions / memory_updates / reflection`。
Agent 声明意图（`ActionRequest`, `MemoryUpdate`），世界引擎裁决是否执行。
Agent 永远不直接修改世界状态。

**4. MemoryInterface 协议**（`src/annie/npc/memory/interface.py`）

```python
@runtime_checkable
class MemoryInterface(Protocol):
    def recall(query, categories=None, k=5) -> list[MemoryRecord]
    def grep(pattern, category=None, metadata_filters=None, k=20) -> list[MemoryRecord]
    def remember(content, category="semantic", metadata=None) -> None
    def build_context(query) -> str
```

- 使用 `typing.Protocol` 而非 ABC——实现方只需"形似"，无需继承。
- `category` 是开放字符串非 enum——业务方可自由扩展类别。
- 约定类别：`semantic / reflection / impression / episodic / todo`。

**5. 默认世界引擎实现**（`src/annie/world_engine/default_engine.py`）

`DefaultWorldEngine` 组合了 `DefaultMemoryInterface` + `HistoryStore` + 可选
`Compressor`。`build_context` 渲染最近 20 轮历史、调用 `memory.build_context`
得到记忆摘要、组装 `AgentContext`；`handle_response` 追加对话到 JSONL、
写入记忆更新、触发 `compressor.maybe_fold`。

**6. WorldEngine.drive_npc() 行动循环**（`src/annie/world_engine/base.py`）

```python
def drive_npc(self, agent, npc_id, event, max_action_steps=8):
    # 1. build_context → AgentContext
    # 2. agent.run(ctx) → AgentResponse
    # 3. 如果 response 有 actions → execute_action → 结果作为新 event → 回到 2
    # 4. 无 actions 或预算耗尽 → handle_response → 返回
```

### 设计取舍

- **Protocol vs ABC**：Protocol 是结构化子类型，避免 Agent 代码反向依赖世界引擎。
- **单次注入 vs 逐次调用**：AgentContext 单次注入让 Agent 彻底无状态，便于并行和测试。
- **意图声明 vs 直接执行**：Agent 只声明 `ActionRequest`，世界引擎做权限/状态校验
  后给出 `ActionResult`。这在 War Game 里用于校验部署合法性，在 Town 里用于校验
  移动可达性。

### 面试可扩展话题

- **并发模型**：Agent 无状态，多 NPC 共用一个 `NPCAgent` + LLM client。
- **测试策略**：`_StubLLM` 用预设 `AIMessage` 列表替代真实 LLM——解耦红利。
- **扩展到新游戏类型**：只写 `WorldEngine` 子类 + 业务 `ToolDef`/`SkillDef`，
  NPC 层零改动。当前已有三条游戏线验证：Town / War Game / Interrogation。
- **对照反例**：早期原型把记忆类、社交图谱类全塞进 `NPCAgent.__init__`，每加
  一个游戏类型就要改 Agent 构造器。重构的直接动机就是这个。

---

## Bullet 2 — 五图认知路由系统

> 将 NPC 认知能力封装为五种独立的认知图（action / dialogue / structured_json /
> reflection），由世界引擎通过 `AgentContext` 按场景路由分发。其中 action 类图
> 组合 Planner + Executor + Reflector 三节点：Planner 采用 skip-first 策略仅对
> 复杂事件拆解任务，Executor 以原生 tool-use 循环执行 ReAct，Reflector 结构化
> 输出写回分类记忆。

### 实现细节

**1. 核心思想：认知能力 = 可路由的图**

NPC Agent 层不是一条固定流水线，而是一个认知图工具箱。Planner、Executor、
Reflector 是**节点**（可复用的积木），五张图是**不同的节点组合**，
每张图封装一种完整的认知能力：

| 图 | 节点组成 | 本质 |
|---|---|---|
| `action.executor_default` | Executor → (失败时 Planner → Executor) → Reflector | 自主行动：先做，不行再想 |
| `action.plan_execute` | Planner → Executor → Reflector | 先规划后执行 |
| `dialogue.memory_then_output` | MemoryContext → 轻量 tool-loop(2 轮) | 查记忆 → 对话 |
| `output.structured_json` | 单次 LLM 调用 | 生成结构化数据 |
| `reflection.evidence_to_memory_candidate` | 单次 LLM 调用 | 反思写记忆 |

世界引擎是调度者——不同场景、不同 NPC、同一 NPC 的不同时刻，都可能调用
完全不同的认知图：

```python
# Town 示例：同一个 NPC、同一个游戏 loop 内的不同调用
engine.build_context(npc_id, event)           # → action.executor_default
engine.build_reflection_context(npc_id)        # → reflection.evidence_to_memory_candidate
engine.build_daily_planning_context(npc_id, ...)  # → action.plan_execute (工具受限)

# War Game 示例：同一轮、不同阶段
# Declaration 阶段 → structured_json 图
# Deployment 阶段 → action.executor_default 图（带部署工具）
```

**2. 路由机制**（`src/annie/npc/graph_registry.py`）

`NPCAgent.run()` 通过 `_resolve_graph_id()` 决定使用哪个图：

| 优先级 | 来源 | 示例 |
|---|---|---|
| 1 | `ctx.graph_id` 显式指定 | `ACTION_PLAN_EXECUTE` |
| 2 | `ctx.route` 意图路由 | `DIALOGUE` → `dialogue.memory_then_output` |
| 3 | `ctx.extra["npc_direct_mode"]` | `"reflection"` → `reflection.evidence_to_memory_candidate` |

五种注册图：

| Graph ID | Runner | 行为 |
|---|---|---|
| `action.executor_default` | `action` | Executor 先行，失败时 Planner+重试（默认） |
| `action.plan_execute` | `action` | Planner 永远先运行 |
| `dialogue.memory_then_output` | `dialogue` | 记忆召回 + 2 轮 tool-loop 对话输出 |
| `output.structured_json` | `structured_json` | 单次 LLM 调用 → JSON |
| `reflection.evidence_to_memory_candidate` | `reflection` | 单次 LLM 调用 → 反思文本 |

**3. Action 图节点：Planner — skip-first 策略**（`src/annie/npc/planner.py`）

- 静态提示词第一条就是「DEFAULT: 返回 `{"skip": true}`」。
- 只有真正需要顺序执行的事件才拆任务，上限 3 条。
- Planner 动态提示词**故意不渲染 history**——history 只给 Executor 用。
  Planner 看到 history 会过度倾向拆解。
- Retry 时 HumanMessage 追加 `<retry_context>` 区块：上一次 `loop_reason` +
  任务列表，避免重复犯错。
- 解析做严格 JSON 校验：skip 时 tasks 必须为空，plan 时 tasks 必须非空，
  每条 task 有 `description`（非空）和 `priority`（0-10）。

**4. Action 图节点：Executor — 原生 tool-use 循环**（`src/annie/npc/executor.py`）

```
max_loops=8:
    budget.check(messages, llm)          # Emergency 折叠检查
    tool_defs = registry.list_tools()     # 每轮重读（use_skill 可能 push frame）
    response = llm.bind_tools(tool_defs).invoke(messages)
    if 无 tool_calls: return              # 最终回答
    for each tool_call:
        result = dispatcher.dispatch(call, ctx)  # 含 Micro 压缩
        messages.append(ToolMessage(result))
```

关键设计：
- **每轮重读工具列表**：`use_skill` 可以在本轮 push frame、下一轮就能 bind 上新工具。
- **`__skip__` 标记**：Planner skip 时 Executor 合成 marker task，只渲染
  `<input_event>`，避免冗余 `<task>` 区块。
- **`try/finally` 清理帧栈**：任务结束必须 pop 本轮 push 的技能帧。
- **`request_action` 打断**：调用后立即返回，不继续执行剩余任务也不跑 Reflector。

**5. Action 图节点：Reflector — 结构化输出 + 分类写回**（`src/annie/npc/reflector.py`）

输出三段：
```
REFLECTION: <2-4 sentence>
FACTS: ["...", "..."]
RELATIONSHIP_NOTES: [{"person": "...", "observation": "..."}]
```

解析采用两级容忍：先尝试 JSON，失败用 `REFLECTION:` 标签提取，再失败返回空。
三类分别写不同记忆类别：
- `REFLECTION` → `category=reflection`
- `FACTS` → `category=semantic`
- `RELATIONSHIP_NOTES` → `category=reflection`, metadata `{"person": name}`

### 设计取舍

- **五种独立图 vs 一个大 prompt**：把"行动/对话/反思/JSON输出"拆成五张独立
  图，每张图职责单一、提示词单一、工具集单一。避免模型在三四种角色间漂移，
  也让每个图可以独立迭代。
- **世界引擎调度 vs Agent 自主判断**：Agent 不知道自己被调用的场景——是 NPC
  自主行动、还是日常反思、还是生成日程。这个判断权完全在世界引擎手里。
  Agent 的职责是"你给我图和上下文，我执行"，不做元决策。
- **Executor-first vs Planner-first**：在 action 类图内部，默认 Executor 先行
  （大部分事件是单轮），只在 Planner-first 图或 retry 时才调用 Planner——节省 token。
- **retry 上限 1**：连续两次拆错多半是输入事件本身模糊，fallback 比无限重试合理。
- **原生 `bind_tools` vs 文本 ReAct**：原生 tool-use 由 SDK 保证 JSON schema 正确，
  不需要正则解析。

### 面试可扩展话题

- **为什么不是标准 ReAct / CoT / Plan-Execute**：标准模板只有 ReAct 一节点；
  本项目五图路由 + skip-first Planner + 显式 retry + per-task 帧栈隔离，
  是针对 NPC 场景的定制。
- **为什么不让 Agent 自己判断用哪个图**：Agent 做元决策（"我该反思吗？我该
  规划吗？"）需要额外的 LLM 调用来判断，增加延迟和成本。世界引擎用确定性的、
  低成本的方式决定（poignancy 超阈值 → 反思图；需要生成日程 → planning 图），
  更快更可靠。
- **LangGraph 选型理由**：显式状态机 > AutoGen 多 agent 协商 / CrewAI 角色流，
  可调试、可回放。LangGraph 的 state 字典原生支持 checkpoint。
- **五图可扩展性**：新场景只需注册新 `GraphEntry`，指定 `runner`（决定 `run()`
  走哪个分发分支）和 `node_path`（决定组合哪些节点），不动现有图。

---

## Bullet 3 — 双通道记忆检索 + 跨会话 Todo

> 设计双通道记忆检索（向量 recall + 字面 grep）与单 run 去重，规避 RAG 对
> 专有名词召回弱的问题；跨会话 Todo 以事件流形式存入统一记忆接口，在提示中
> 动态渲染 todo 区块。

### 实现细节

**1. 为什么需要 grep**

RAG / 向量召回有两个盲区：
- **专有名词**：embedding 可能把"李四"与"张三"嵌得很近（都是人名），召回漂移。
- **结构化查询**：`category=todo && status=open` 这种精确元数据条件，向量检索不适用。

`grep(pattern, category, metadata_filters, k)`：
- 字面子串匹配（`casefold()` 大小写不敏感）
- 可按 category 筛、按 metadata 精确相等筛
- 结果按 `created_at` 倒序，`relevance_score=1.0`
- `pattern=""` 是"纯按筛选条件返回"的约定

底层：`MemoryStore.grep_entries` 用 Chroma 的 `collection.get(where=...)` +
Python 侧 `casefold()`。

**2. 两个通道都暴露为 LLM 工具**

`memory_recall` 和 `memory_grep` 都是内建工具，描述里指导 LLM「专有名词/精确短语
用 grep，模糊语义用 recall」。模型自己决定用哪个——tool-use 范式天然路由。

**3. 单 run 去重**

`runtime["recall_seen_ids"]` 追踪已在 `<working_memory>` 中展示过的记录。
- 运行开始时 `MemoryContextBuilder.build_context` 种子化 seen_ids。
- `memory_recall` / `memory_grep` 命中 seen 的记录被过滤。
- 去重粒度是单次 `run()`，下一次 run 重新开。

**4. DefaultMemoryInterface 写策略**（`src/annie/world_engine/memory.py`）

- `semantic` / `reflection`：**upsert**，用 `sha1(category|content|person)[:16]` 做稳定 id。
  同一事实写两次产生单一记录，只刷新时间戳。
- 其他类别（`impression`、`todo`）：**add**，用随机 UUID。Impression 摘要覆盖不同
  时间窗，不能去重。
- 向量存储只放蒸馏内容，不写 episodic。原始对话由 `HistoryStore` (JSONL) 承担。
- `recall` 里给 `impression` 类命中乘 1.2× relevance。

**5. 跨会话 Todo：事件流模型**

`plan_todo` 工具三种操作（`src/annie/world_engine/tools.py`）：
- `add(content)` → 写入 `{status: open, todo_id: <uuid>}`
- `complete(todo_id)` → **追加新记录** `{status: closed, closes: <todo_id>}`
  （绝不修改原记录）。完成前先 grep 验证 open 记录存在且未被 closed。
- `list` → grep open + grep closed，差集得 alive。

事件流优势：
- `MemoryInterface` 协议不需要 update 方法（保持最小协议）。
- 天然可审计（任何时候都能重放 todo 历史）。
- 写入幂等（重复 complete 因 closed 记录已存在而失败）。

**6. `<todo>` 区块动态渲染**

运行开始时 `render_todo_text(memory)` 计算 alive todos，写入
`state["todo_list_text"]`；Executor 填进 `<todo>` 区块。NPC 能"记住上次没做完的
事"。

集成测试 `tests/test_integration/test_cross_run_todo.py` 验证：
run1 add → run2 可见 → run2 complete → run3 不可见。

### 设计取舍

- **grep 返回 `relevance_score=1.0`**：不装作有排序权重，让 LLM 通过文档看到这是字面匹配。
- **单 run 去重用 content 字符串而非 record id**：MemoryRecord 的 id 不在协议里。
- **event-stream todo vs mutable record**：选事件流最大收益是协议最小。

### 面试可扩展话题

- **如果换后端（PGVector / LanceDB）**：只需重写一个 `MemoryInterface` 实现，
  NPC 层零改动。
- **todo 数量爆炸**：可加 `expires_at` 元数据定期 prune。
- **recall 里 `_MIN_RELEVANCE=0.35` 阈值**：来自实测——低于此值的结果混入提示词
  反而污染模型注意力。

---

## Bullet 4 — 三级上下文压缩

> 设计三级上下文压缩：工具响应微缩(Micro) → Executor 单轮消息应急折叠
> (Emergency) → 跨运行对话历史沉淀为印象记忆(Fold)，分别覆盖单条工具输出、
> 单轮上下文超限、长期记忆蒸馏三个边界。

### 实现细节

| 层级 | 位置 | 作用域 | 触发条件 | 产出 |
|---|---|---|---|---|
| **Micro** | `ToolDispatcher._micro_compress` | 单条 ToolMessage | `len(content) > 2000` 字符 | 头 40% + `[...truncated...]` + 尾 |
| **Emergency** | `ContextBudget.check` | Executor 单轮消息列表 | `tokens + reserve > limit*0.9` | LLM 摘要最早轮次 → SystemMessage，保留最新 2 轮 |
| **Fold** | `Compressor.maybe_fold` | 跨 run 的 JSONL 历史 | 未折叠窗口 tokens > 3000 | LLM 摘要 → `impression` 记忆 + 游标推进 |

**1. Micro — 工具响应微缩**（`src/annie/npc/runtime/tool_dispatcher.py`）

```python
MICRO_MAX_CHARS = 2000
_MICRO_HEAD_FRACTION = 0.4

def _micro_compress(text):
    if len(text) <= max_chars: return text
    head_len = max_chars * 0.4
    tail_len = max_chars - head_len - len(markers)
    return f"{text[:head_len]} [... truncated ...] {text[-tail_len:]}"
```

头 40% + 尾 60%：工具响应一般是"元数据 + 结果列表"，头部保 schema/状态，
尾部保最新记录。不做 LLM 摘要——每次工具响应都调 LLM 成本会线性放大。

**2. Emergency — 执行器应急折叠**（`src/annie/npc/context_budget.py`）

- 触发阈值：`int(model_ctx_limit * 0.9)`，预留 `reserve_output=4096`。
- Token 估算：`chars / 2.5`（CJK 偏保守，比精确 tokenize 便宜 100 倍）。
- 折叠策略：
  1. 保留所有 SystemMessage
  2. 保留最新 2 轮 Human-initiated 对话（以 HumanMessage 为锚切分保证原子性）
  3. 最早 head 段交给 LLM 摘要成 3-6 bullet points
  4. 摘要作为 `SystemMessage("[earlier tool work summary]\n...")` 插入
- 为什么是应急：90% 上下文不需要 Emergency，只有 tool-use 打到 6-7 轮的罕见
  场景才触发。

**3. Fold — 跨运行印象沉淀**（`src/annie/world_engine/compressor.py`）

Fold 是唯一会写入向量存储的压缩器。

游标驱动：
- `HistoryStore` 的 `.meta.json` sidecar 保存 `last_folded_turn_id`
- `estimate_tokens_after_cursor()` 只计算游标之后的 entries
- 超阈值 → 取游标后最老 `FOLD_TARGET_TOKENS=1500` 的切片 → LLM 摘要 →
  写入 `category=impression` → 游标推进
- **不改 JSONL**，JSONL 是 append-only

摘要提示词（`FOLD_SUMMARY_PROMPT`）强制三要素：WHO 对 WHOM 做了 WHAT、
情绪基调、明确事实。第三人称过去时，保留专有名词。

**4. 三级协同**

一次 Executor 运行中可能全部触发：
- 每个 ToolMessage 过 Micro
- 每轮 LLM 调用前过 Emergency（一般不触发）
- 任务结束、`handle_response` 里可能过 Fold

粒度错位覆盖完整生命周期：
- Micro 保护单次工具调用的 token 预算
- Emergency 保护模型上下文窗口
- Fold 保护长期记忆的可检索性

### 设计取舍

- **不统一成一个"智能压缩器"**：一个组件同时懂原始对话、工具响应、模型窗口
  会变成上帝对象。错位分层让每一级职责清晰、独立测试、独立调阈值。
- **Prune 不是压缩**：`HistoryStore.prune` 是物理删 JSONL 行，不产出摘要——
  是存储 GC，不是上下文压缩。有意区分避免概念混淆。
- **Emergency 保留 2 轮不是 1 轮**：1 轮不够让模型接住上下文，3 轮以上没必要。
  实测 2 轮是帕累托点。

### 面试可扩展话题

- **Fold 产出的 impression 如何进入新 run**：Reflector 写的 reflection + Fold
  写的 impression 都落在向量库，新 run 的 `build_context` 把它们 recall 出来
  放进 `<working_memory>`。"短期→长期"的完整闭环。
- **LLM 摘要失败降级**：Emergency catch 异常返回原消息；Fold 空摘要放弃本次
  折叠记 warning。原则：宁可多占 token，不可丢信息。
- **对比 LangChain `ConversationSummaryBufferMemory`**：只有一级滚动摘要；
  AutoGPT memory 也类似单级。三级错位是针对长对话 NPC 的专门设计。

---

## 附：三条游戏线

### 1. Town — 语义世界模拟

`src/annie/town/engine.py` 的 `TownWorldEngine` 是 Generative Agents 风格的
完整小镇模拟：

- **空间系统**：8 个位置 + 17 个可交互对象 + 语义 affordance（非 tile 地图）
- **日程系统**：每日 Schedule（位置 + 意图 + 子任务），重大事件触发 schedule revision
- **感知系统**：有界策略（max N events/objects/NPCs/exits），注意力选择
- **对话系统**：`start_conversation` 多轮交替对话 + 自然结束检测 + 冷却
- **反思系统**：Poignancy 触发，事件/日程/对话积累证据
- **循环守卫**：检测重复失败动作、重复低价值对话、日程漂移
- **Replay**：完整 artifact 生成（动作日志、时间线、快照、反思）

### 2. War Game — 三阵营策略游戏

`src/annie/war_game/` 是完整的回合制语言欺骗策略游戏：

- 15 城对称地图，3 阵营（1 玩家 + 2 AI）
- 5 阶段/回合：宣言 → 外交 → 部署 → 结算 → 生产
- AI 阵营使用完整 NPCAgent 栈做战略决策
- 2v1 战斗含谈判子博弈（撤军/决战决策）
- 交互式 CLI 含部署小游戏

### 3. Interrogation — 侦探审讯游戏

`src/annie/interrogation/` 是中文审讯与证据搜索原型（"双重暗影"）：

- 阶段制：初始审讯 → 搜索1 → 二次审讯 → 搜索2 → 最终审讯 → 裁决
- NPC 心率（BPM）系统基于关键词压力检测
- 证据袋跨阶段追踪
- 记忆污染防护（对话 → episodic only，事实 → semantic only）
- 玩家裁决评分基于关键词匹配

## 附：端到端调用链（五种图的调用路径）

```
WorldEngine.build_context(npc_id, event)
    ├─ 读 HistoryStore 最近 20 轮
    ├─ DefaultMemoryInterface.build_context → working_memory
    ├─ render_todo_text(memory) → todo
    ├─ 设 graph_id / route → 决定用哪个图
    └─ 组装 AgentContext (含 tools/skills/memory/prompts)
                │
                ▼
NPCAgent.run(ctx):
    _resolve_graph_id → GraphEntry
    │
    ├─ [action 图: executor_default / plan_execute]
    │   ├─ Executor / Planner → Executor (tool-use 循环)
    │   │   ├─ budget.check → Emergency (如需)
    │   │   ├─ llm.bind_tools(...).invoke
    │   │   ├─ per tool_call: dispatcher.dispatch → Micro (如需)
    │   │   └─ use_skill: SkillRuntime.activate → push frame + SystemMessage
    │   └─ Reflector → memory_updates (REFLECTION + FACTS + RELATIONSHIP_NOTES)
    │
    ├─ [dialogue 图: dialogue.memory_then_output]
    │   └─ MemoryContext → 轻量 tool-loop(2 轮) → 对话文本
    │
    ├─ [structured_json 图: output.structured_json]
    │   └─ 单次 LLM 调用 → JSON 字符串
    │
    └─ [reflection 图: reflection.evidence_to_memory_candidate]
        └─ 单次 LLM 调用 → 反思文本
                │
                ▼
AgentResponse → WorldEngine.handle_response
    ├─ HistoryStore.append(dialogue)
    ├─ memory.remember() per MemoryUpdate
    └─ Compressor.maybe_fold() → impression 记忆 (Fold)
```

## 附：面试追问预案

- **"这个项目有多少行代码"**：核心框架 ~8000 行 Python + 测试 ~5000 行 +
  游戏内容脚本。重点是"架构演进"——从单层端到端 demo 重构成两层解耦，
  删除了 `cognitive/` 等重耦合模块。
- **"LLM 选型"**：框架对 LLM 不耦合，任何 LangChain `BaseChatModel` 兼容的
  provider 都可以。当前默认用 DeepSeek（OpenAI 兼容 API），测试用 `_StubLLM`。
- **"生产环境部署过吗"**：个人项目未生产部署。如果要上线，需要补：
  (a) Tracer → OpenTelemetry、(b) 每 NPC 一个 Chroma collection 的扩展性、
  (c) 限流与 cost guard。
- **"和 LangGraph 官方 ReAct 模板比"**：官方模板只有 ReAct 一节点；本项目
  五图路由 + skip-first Planner + 显式 retry + per-task 帧栈隔离，是针对
  NPC 场景的定制。
- **"为什么选 Pydantic 而不是 dataclass"**：LangChain / LangGraph 生态原生用
  Pydantic；`AgentContext.model_rebuild()` 解 forward ref 也是 Pydantic 的能力。
- **"最复杂的部分是什么"**：Town 的 `build_context` 方法（约 300 行），需要
  把感知、日程进度、对象选择提示、对话策略、循环守卫、历史、记忆、todo 全部
  编织成一个 AgentContext——且不能调用 LLM 做决策辅助（成本考虑）。

---

_文档生成时间：2026-07-18。基于实际代码库当前状态编写。_
