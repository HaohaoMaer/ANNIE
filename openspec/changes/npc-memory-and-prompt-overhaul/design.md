# Design: NPC 记忆双索引与 Prompt 体检

## memory_grep 的实现边界

`grep` 不做向量运算。在 ChromaDB `collection.get(where=...)` 上拉出候选集后，在 Python 端做 `pattern in entry.content` 子串匹配。

- `pattern` 大小写不敏感（`str.casefold()`）。
- `metadata_filters` 直接映射到 ChromaDB `where` 子句；`category` 作为 `where={"category": ...}` 的语法糖。
- 命中按 `created_at` 新 → 旧排序；同时间戳按 insert 顺序。
- 返回的 `MemoryRecord.relevance_score` 统一写 `1.0`（字面命中无相似度意义，避免和 RAG 混排时误导）。
- `k` 默认 20，比 `recall` 默认 5 高：grep 场景多为"列出所有跟某人相关的记忆"，k 太小容易漏。

**不做**：正则 / 近似匹配 / 多 pattern AND/OR。后续可通过加参数扩展，本次只接受单个 pattern。

**IMPRESSION_WEIGHT 不适用**：grep 不走相似度排序，加权无意义。

## Prompt 结构定稿

Executor system template（XML-sectioned，字段顺序固定）：

```
<character>{character_prompt}</character>
<world_rules>{world_rules}</world_rules>
<situation>{situation}</situation>
<memory_categories>
- episodic: 原始经历（对话落盘、事件观察）
- semantic: 客观事实
- reflection: 自我反思与人物印象
- impression: 折叠产生的模糊印象
- todo: 跨回合未完成目标（可能为空）
</memory_categories>
<working_memory>{working_memory}</working_memory>
<available_skills>{skills}</available_skills>

You are acting as this NPC. Respond in-character. You may call the tools
listed in this turn's tool schema to ground your answer; when you have
everything you need, produce a final in-character reply with no further
tool calls.
```

- `working_memory` 空时渲染为 `(none)`；非空直接塞 Planner 阶段预检索得到的多行字符串。
- `available_skills` 本 change 仍渲染 `(none this run)` — 交给 change 2 接 SkillRegistry 后切换。
- `<todo>` 段**本 change 不渲染**；等 change 2 引入 plan_todo 再接入。`<memory_categories>` 中提到 `todo` 是为了让模型认识它一旦被引入就知道含义。

## Planner prompt 结构定稿

Static 部分（精简后）：

```
You are an NPC planning module. Your job is to decide whether the incoming
event needs multi-step decomposition.

DEFAULT: respond with {"skip": true, "reason": "<brief>"}.

Only return a task list when the event truly requires sequential stages
that cannot fit in a single in-character reply. Examples that warrant a
list: "先去厨房取证据再回来质询"; "连问三个人比对口供". Examples that
DO NOT: 单轮对话回应, 情绪反应, 表态, 内心活动.

Task list format (only when needed):
[{"description": "...", "priority": 0-10}]  // 最多 3 条
```

Dynamic 部分不再包含 history。只含：

```
## Character
{character_prompt}

## World Rules
{world_rules}

## Current Situation
{situation}
```

User content：

```
Event: {input_event}

Working memory (pre-retrieved):
{working_memory}

{retry_context_if_present}
```

Retry context 示例：

```
<retry_context>
Previous attempt produced no usable results.
Reason: executor produced no results
Previous tasks: ["去厨房找匕首", "比对指纹"]
Revise the plan or skip.
</retry_context>
```

## skip 路径的重复消除

现状代码路径：

```python
# agent.py _executor_with_skip
if not tasks:
    tasks = [Task(description=evt or "Respond...", priority=5)]
# executor.py _initial_messages
trigger = HumanMessage(content=(
    f"<input_event>{input_event}</input_event>\n"
    f"<task>{task.description}</task>"
))
```

问题：`task.description == input_event`（skip 合成路径）时，trigger 里 `<task>` 就是对 `<input_event>` 的复读。

**修正**：

1. `_executor_with_skip` 改为生成一个**特殊标记 task**：`Task(description="__skip__", priority=5, metadata={"synthesized": True})`。
2. `Executor._initial_messages` 检测 `task.description == "__skip__"` 或 `task.metadata.get("synthesized")`，trigger 只渲染 `<input_event>`，不渲染 `<task>`。
3. 非 skip 路径保持原样。

**备选**：直接让 `task` 可选为 `None`。但 LangGraph state 的 list 语义更自然，用标记 task 实现成本更低。采纳方案 1。

## `_render_identity` helper

提出到 `src/annie/npc/prompts.py`（新模块）：

```python
def render_identity(ctx) -> str:
    """Return `<character>...</character>` XML block used by Executor/Reflector."""
```

Reflector 改为在 system 末尾追加 `render_identity(ctx)` 的返回而非 `## NPC Identity` 自由格式，保证两个节点看到一致的角色描述结构。

## Reflector tolerant parser

```python
def _parse_list(raw: str) -> list[str]:
    raw = raw.strip()
    if not raw:
        return []
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(x) for x in parsed]
    except json.JSONDecodeError:
        pass
    items = []
    for line in raw.splitlines():
        line = line.strip().lstrip("-*•").lstrip()
        line = re.sub(r"^\d+[.)]\s*", "", line)
        if line:
            items.append(line)
    return items
```

`_parse_response` 对 FACTS / RELATIONSHIP_NOTES 使用此 helper。RELATIONSHIP_NOTES 若解析为纯字符串列表则降级：每条作为 `observation`，`person=""`，最终被 `person and obs` 条件过滤掉（等价于丢弃）——和当前失败时的行为一致，但其他 bullet 结构能正确落地。

## InnerMonologue 接入

`InnerMonologueTool.call`：

```python
def call(self, input, ctx):
    inp = _coerce(input, InnerMonologueInput)
    thoughts = ctx.agent_context.extra.setdefault("_inner_thoughts", [])
    thoughts.append(inp.thought)
    return {"thought": inp.thought}
```

`AgentState` 不直接承载，仍走 `AgentContext.extra`（tool ctx 可达），run 结束时 `_build_response` 从 `context.extra["_inner_thoughts"]` 读取拼接。这样保持"Agent 层不在 self 上藏状态"的大前提。

## Retry 信号的传递

`_should_retry` 产生 retry 时已写 `state["loop_reason"]`。需新增：

- `state["last_tasks"]: list[Task]` — Executor 执行前的 task 列表快照。
- Planner 读取 `state.get("loop_reason")` + `state.get("last_tasks")`，拼 `<retry_context>` 进 user_content。
- `state["retry_count"] > 0` 作为渲染条件。

## Naming: memory_context → working_memory

全链路重命名：

- `AgentState` 字段：`memory_context` → `working_memory`
- `agent.py` 初始化：`memory_agent.build_context(...)` 写入 `working_memory`
- Planner 读取 key 同步
- Executor 新增的 `<working_memory>` 段即读此字段

保留 `MemoryAgent.build_context(query)` 的方法名（它是"构建用于 prompt 的上下文字符串"，与 `AgentContext` 的构造无关，语义上仍合适）。

## 边界拆解

不纳入本 change 的相邻议题：

- **预检索升级为 RAG + grep 混合**：需要从 `input_event` 抽实体做 grep。留待观察期。目前 `build_context` 仍是纯 RAG。
- **`<todo>` 段渲染**：依赖 plan_todo tool，属 change 2。
- **`<available_skills>` 动态化**：依赖 Skill 解冻，属 change 2。
- **Compressor / ContextBudget 边界 spec 明文化**：纯文档工作，可在 change 3 顺带或独立 PR。
