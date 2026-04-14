# Design: 分层上下文管理、多类别记忆与 Agentic RAG

本文档记录本次 change 的所有架构决策（D-number）。实现阶段以此文档为准；冲突时以本文档为先。

---

## D1. 上下文的四档归属

上下文按**生命周期 × 归属者**切成四档，严格区分：

```
┌─────────────────────────────────────────────────────────────────┐
│  档位         │  归属          │  内容                           │
├─────────────────────────────────────────────────────────────────┤
│  Stable       │  WorldEngine  │  character_prompt, world_rules  │
│  Rolling      │  WorldEngine  │  DialogueHistory (per-NPC)      │
│  Long-term    │  WorldEngine  │  ChromaDB 多类别记忆             │
│  Working      │  Agent        │  AgentState.messages (单 run 内) │
└─────────────────────────────────────────────────────────────────┘
```

**不变量**：
- Agent 不持有跨 run 状态。`AgentState` 随 `run()` 返回即死。
- WorldEngine 不感知 Agent 单 run 内的 tool-use 中间过程。
- `AgentContext` 是 WorldEngine → Agent 的**单向输入快照**，Agent 不回写 context。
- `AgentResponse` 是 Agent → WorldEngine 的**单向输出**，WorldEngine 据此写 HistoryStore / Memory。

## D2. 压缩策略的五档落位

```
策略        作用对象                    归属         触发
─────────────────────────────────────────────────────────────────────
Trim        HistoryStore 老条目         WorldEngine  每次 build_context
Fold        连续 N 条 raw turn          WorldEngine  token > threshold /
                                                     scene 切换
Auto        (Fold 的定时调度)            WorldEngine  [本次 change 不做]
Micro       单条工具输出/记忆条目        Agent        插入 messages 前
Emergency   Agent.messages 整体         Agent        LLM 调用前预算超限
```

实现优先级：Trim → Micro → Fold → Emergency。Auto 不在本次范围。

### Trim 规则
- `build_context` 时取 HistoryStore 最后 `MAX_HISTORY_TURNS`（默认 20）条；超出的不进入渲染。
- 不删除底层存储——只是视图截断。

### Fold 触发
- 判据：`HistoryStore.estimate_tokens(npc_id) > FOLD_TOKEN_THRESHOLD`（默认 3000）。
- 策略：取**最旧的**连续 N 条**未折叠** turn（N 动态决定，凑到 ~1500 tokens 一段），送主 LLM 做摘要。
- 产物：
  - 替换 HistoryStore 这 N 条为一条 `FoldedEntry(is_folded=True, summary=...)`
  - 同时 `memory.remember(summary, category="impression", metadata={scene, time_range, source="fold"})`
  - 原始 `episodic` 记忆已在 `handle_response` 阶段落盘过，Fold 不重复写。

### Micro 规则
- 工具输出 > `MICRO_MAX_CHARS`（默认 2000）时，Agent 侧前置截断：保留头/尾各 40%，中间用 `[... truncated ...]`。
- 不调用 LLM。

### Emergency 规则
- LLM 调用前估算 `messages` token；如果预测输入 + 预留输出 > model context limit × 0.9，触发。
- 策略：把最早的若干 `ToolMessage` + 其前置 `AIMessage(tool_call)` 折叠成一条 `SystemMessage("[earlier tool work summary] ...")`，用主 LLM 摘要。
- 保留最新 2 轮完整。

## D3. Fold 产物 = 替换 history + impression 落盘

**"遗忘细节，留下印象"** 的三层落地：

```
原始 N 条 raw turn
  │
  ├─ HistoryStore.replace(N 条) → 1 条 FoldedEntry(is_folded=True)
  │                                 （细节从当下记忆中消失）
  │
  └─ memory.remember(
       content=summary,
       category="impression",
       metadata={"scene": ..., "time_range": [t0, t1], "source": "fold"}
     )
     （印象留下，可被语义召回）

不删除：原始 turn 在 handle_response 时已以 category=episodic 入 ChromaDB。
        深层追忆通过 memory_recall(categories=["episodic"]) 可唤回。
```

**递归折叠禁止**：`is_folded=True` 的 entry 不参与下次 Fold 的候选集。避免信息链被反复压扁到无法解读。

## D4. 长期记忆坍缩为单 collection + category metadata

### 为什么统一

- 类别数量开放（episodic / semantic / reflection / impression / 未来更多）。N 个 collection 伸缩差。
- ChromaDB `where={"category": {"$in": [...]}}` 过滤便宜。
- 跨类别 top-k 混合召回更自然（不必手写多路合并 + 重排）。

### 存储结构

单 collection 名：`npc_memory_{npc_id}`。每条 entry 必带 metadata：

```python
{
  "category": "episodic" | "semantic" | "reflection" | "impression" | <open>,
  "created_at": ISO8601,
  "scene": Optional[str],
  # category-specific:
  "person": Optional[str],     # reflection / impression 常用
  "time_range": Optional[[t0, t1]],  # impression (fold 产物)
  "source": Optional[str],     # "fold" / "reflector" / etc.
  "is_folded": bool,           # 仅 impression 使用
}
```

### 类别语义约定（非枚举，仅约定）

| category     | 来源                    | 典型内容                            |
|--------------|-------------------------|-------------------------------------|
| `episodic`   | handle_response 自动落盘 | "今晚和张三在酒吧聊了毒药"           |
| `semantic`   | memory_store 工具        | "张三是医生"                        |
| `reflection` | Reflector 产出           | "张三回答含糊，可能在隐瞒"           |
| `impression` | Fold 产出                | "关于张三——紧张、回避毒药话题"       |

### 召回加权

`recall` 对 `impression` 类别的 `relevance_score` 乘以 `IMPRESSION_WEIGHT`（默认 1.2）。理由：Fold 产物是语义浓缩，信息密度高于同长度的原始片段。其他类别等权。

### 接口签名变更

```python
class MemoryRecord(BaseModel):
    content: str
    category: str              # 原 type 字段改名
    metadata: dict[str, Any]
    relevance_score: float

class MemoryInterface(Protocol):
    def recall(
        self,
        query: str,
        categories: list[str] | None = None,  # None = 全类别
        k: int = 5,
    ) -> list[MemoryRecord]: ...

    def remember(
        self,
        content: str,
        category: str = "semantic",
        metadata: dict[str, Any] | None = None,
    ) -> None: ...

    def build_context(self, query: str) -> str: ...
```

`build_context` 保留，作为"跨类别摘要字符串"的便捷方法（内部调 `recall(categories=None)` 然后按类别分段格式化）。

## D5. Agentic RAG via tool-use loop

### 为什么是 Agentic RAG

当前 Executor 是"预先 build_context 一次、结果拼进 prompt"，属于 Naive RAG。切到 tool-use loop 后，召回自然变成 agent-driven：

- 模型根据当前对话决定 query（不固定为 task.description）
- 可多轮召回（拉一次不够再拉）
- 可跨类别比较（先拉 impression 看大局，再拉 episodic 看细节）

**不需要额外动记忆层**——`recall(query, categories, k)` 签名已经够。升级是 Executor 重构的免费副产品。

### Executor 新流程

```
Executor(state):
  messages = initial_messages_from(state.agent_context)
  while True:
    ContextBudget.check(messages)    # 可能触发 Micro / Emergency
    response = llm.bind_tools(tools).invoke(messages)
    messages.append(response)
    if not response.tool_calls:
      break                          # final answer
    for call in response.tool_calls:
      result = ToolAgent.dispatch(call, ctx)
      messages.append(ToolMessage(result, tool_call_id=call.id))
  state.messages = messages
  state.execution_results = [...]
```

### initial_messages 构成

```
SystemMessage:
  <character>{ctx.character_prompt}</character>
  <world_rules>{ctx.world_rules}</world_rules>
  <situation>{ctx.situation}</situation>
  <available_skills>   ← 本次仅占位，value 为空 list
    (skill 冻结状态，未来填 name+desc)
  </available_skills>

[HumanMessage / AIMessage 对，来自 ctx.history]
  （WorldEngine 渲染 HistoryStore 时已区分 speaker，转成 message turn）

HumanMessage:
  <input_event>{ctx.input_event}</input_event>
  <task>{task.description}</task>
```

XML 分节用于明确语义角色，消息层次用于模型对"历史 vs 当下"的天然感知。

## D6. Tool 暴露：全量原生 schema

**决策**：`llm.bind_tools(all_tools)`，不做渐进披露。

理由：
- ANNIE 当前工具数量预计 <20（3 built-in + 5-10 世界引擎注入）
- 原生 tool-use 通道在 SDK 层有结构化解析、参数校验、parallel tool call 等能力
- 渐进披露的收益在 50+ tool 时才显著；成本（多 round-trip、模型要学两步式调用）即时

Skill 的能力未来通过**独立的 `use_skill(name)` tool + prompt 注入**实现渐进披露（不在本次）。

## D7. Skill 冻结的边界

- `SkillDef` / `SkillRegistry` 接口**不删**——future change 会重用。
- `SkillAgent.try_activate` 改为立即返回 `None` 并打一次 `DeprecationWarning`。
- Executor 完全跳过 skill 相关代码路径。
- 测试中对 skill 的断言全部失效（交由新 change 恢复）。

## D8. HistoryStore 的存储形式

**决策**：独立 JSONL 文件 per-NPC，路径 `./data/history/{npc_id}.jsonl`。

候选对比：

| 方案              | 优点                    | 缺点                           |
|-------------------|-------------------------|--------------------------------|
| JSONL 独立文件 ✓   | 简单、易调试、append 友好 | 没有事务                       |
| SQLite            | 事务、查询灵活           | 多一个依赖 & schema 维护       |
| ChromaDB 特殊类别 | 复用现有组件             | 语义混淆（history ≠ memory）   |

MVP 阶段 JSONL 足够。每行一个 `HistoryEntry`：

```python
class HistoryEntry(BaseModel):
    turn_id: int
    timestamp: str
    speaker: str        # npc_id 或 "system" / "player"
    content: str
    is_folded: bool = False
    folded_from: list[int] | None = None  # 原始 turn_id 列表
    metadata: dict[str, Any] = {}
```

## D9. ContextBudget 的实现

单一组件，Agent 内部使用，不暴露给 WorldEngine：

```python
class ContextBudget:
    def __init__(self, model_ctx_limit: int, reserve_output: int = 4096):
        self.limit = int(model_ctx_limit * 0.9)
        self.reserve = reserve_output

    def check(self, messages: list[BaseMessage], llm) -> list[BaseMessage]:
        tokens = estimate_tokens(messages)
        if tokens + self.reserve <= self.limit:
            return messages
        # Emergency: fold earliest tool turns via llm
        return self._emergency_fold(messages, llm)
```

Micro 压缩在 ToolAgent.dispatch 的返回路径上执行，不走 ContextBudget。

## D10. 失败与回滚

- 本次 change 涉及破坏性 schema 变更。**要求开发者清空 `./data/vector_store/` 与 `./data/history/`** 后重跑。
- 测试 `tests/test_integration/test_decoupled_flow.py` 需要同步更新——使用 tmpdir 隔离 chromadb，不受本机状态污染。
- Reflector 的产出从"三段 REFLECTION/FACTS/RELATIONSHIP_NOTES"继续保留，仅 `memory.remember` 调用改为 `category=` 参数。
