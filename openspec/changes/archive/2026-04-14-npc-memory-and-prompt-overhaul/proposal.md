# Proposal: NPC 记忆双索引与 Prompt 体检

## Why

上一个 change 建立了单 collection + category 的长期记忆和原生 tool-use 循环，但在单 NPC 闭环测试中暴露了以下问题：

1. **长期记忆只有 RAG 一条腿**。`episodic / semantic / impression` 三类记忆在"按专名命中"（"张三说了什么"、"那把匕首的描述"）时表现很差——向量相似度对专名不敏感，而这恰是剧本杀/推理类世界里最高频的查询形态。
2. **预检索结果被丢弃**。`agent.py` 在 Planner 前已经调用 `memory_agent.build_context(input_event)` 得到 `memory_context`，但 **Executor 的 system 模板根本不读这个字段**。模型要么调 tool 重取，要么瞎编。
3. **Prompt 层暴露多个结构性缺陷**：
   - Executor `system` 硬编码工具名 `"e.g. memory_recall, memory_store, inner_monologue"`，加新工具后会误导模型。
   - Prompt 从未告诉模型长期记忆有哪几个 category 及含义，导致 `memory_recall(categories=...)` 的过滤参数形同虚设。
   - Planner 把 history 作**文本**塞进 user_content，Executor 又把同一 history 解析成 **message 序列** —— 同一数据两种形态双塞给同一模型，诱导过度规划。
   - 简单对话事件经 Planner 拆出单任务后，Executor 的 trigger 同时含 `<input_event>` + `<task>` + system prompt 里的 "Respond in-character"，三重触发导致**重复行为**。
   - `_executor_with_skip` 在 Planner skip 时把 `input_event` 原文再塞进 `task.description`，进一步加剧重复。
4. **Reflector 存在两处正确性 bug**：
   - FACTS / RELATIONSHIP_NOTES 用严格 `json.loads` 解析，模型输出带 bullet 或裸文本时静默丢弃。
   - `store_semantic(fact, metadata={"category": "learned"})` — category 现已是顶层字段，此 metadata 写入无法被索引。
5. **Retry 边对 Planner 沉默**。`loop_reason="executor produced no results"` 写进 state，但 Planner prompt 不读它，重跑几乎必然产出相同结果。
6. **InnerMonologue 形同鸡肋**：tool 只 `return thought`，`AgentResponse.inner_thought` 在 `_build_response` 里被硬写成空串，结果从未消费。

本 change 一次性修复上述所有 prompt / 流程层缺陷，并通过引入 `memory_grep` 补齐长期记忆的"字面/元数据"检索维度，让双索引成为一等公民。

## What Changes

### 1. MemoryInterface 增加 grep（memory-interface 修订）

在 `recall`（RAG）之外新增 `grep` 方法：按 pattern 做子串匹配，可叠加 category 和 metadata 过滤。

```python
grep(
    pattern: str,
    category: str | None = None,
    metadata_filters: dict[str, Any] | None = None,
    k: int = 20,
) -> list[MemoryRecord]
```

语义：在 NPC 的长期记忆 collection 内按字面子串命中 entry.content，可选限定 category / metadata，不按向量相似度排序，按时间新→旧返回前 k 条。

与 `recall` 互补：RAG 负责语义相似度，grep 负责专名 / id / 精确短语。

### 2. 新增 built-in tool `memory_grep`（tool-skill-system 修订）

built-in 工具表从三件套扩展为四件套：

```
memory_recall   语义检索（既有）
memory_grep     ★ 新增：字面/元数据检索
memory_store    写入（既有）
inner_monologue 私密思考（既有；本次接入 AgentResponse）
```

`memory_grep` 的 `input_schema` 字段与 `MemoryInterface.grep` 签名一致。冲突策略保持不变（built-in 优先，冲突日志警告）。

### 3. Prompt 体检与修复（npc-agent 修订）

- **Executor system 模板重写**：
  - 新增 `<memory_categories>` 段，列出 `episodic / semantic / reflection / impression / todo` 五类及各自一行含义，供模型正确使用 `categories=` 参数。
  - 新增 `<working_memory>` 段，内容来自 Planner 已算好的 `memory_context`（透传，零新查询）。
  - 新增 `<todo>` 段（占位，为 change 2 的 plan_todo 预留，本次可渲染为空或未命中说明）。
  - 去掉硬编码工具名，改为通用表述 "You may call the tools listed in this turn's tool schema to ground your answer."
- **Planner prompt 重写**：
  - Option B（skip）升格为**默认**；Option A 的适用条件收紧为"明确多阶段且不在单轮对话内可解的任务"。
  - 去掉 "1-5 tasks" 诱导性上限，改为 "最多 3 个，仅在真正需要顺序推进时使用"。
  - 不再在 dynamic_prompt 中渲染 history —— history 只由 Executor 作 message 序列消费。
  - Retry 时 Planner user_content 追加 `<retry_context>` 段，包含 `loop_reason` 与上轮 task 摘要。
- **skip 路径不重复渲染 `input_event`**：`_executor_with_skip` 不再把 `input_event` 塞进 `task.description`；Executor 检测 task=None / 描述与 input_event 同文时只渲染 `<input_event>`，不渲染 `<task>`。
- **`_render_identity()` helper**：Executor 与 Reflector 共用，统一 character 渲染格式。

### 4. Reflector 正确性修补（npc-agent 修订）

- 把 FACTS / RELATIONSHIP_NOTES 解析改为 tolerant parse：先尝试 `json.loads`，失败则按行切分 `- item` / `* item` / `1. item` bullet 回退，仍失败则空列表。
- `store_semantic(fact, metadata={"category": "learned"})` 的 metadata 残留去掉，直接 `store_semantic(fact)`，category 由 MemoryAgent 顶层字段承担。

### 5. InnerMonologue 接入 AgentResponse（agent-interface 修订）

- `InnerMonologueTool.call` 返回 `{"thought": ...}` 之外，写入 `AgentState.inner_thoughts: list[str]`。
- `_build_response` 把 `inner_thoughts` 以换行拼接后填入 `AgentResponse.inner_thought`。

### 6. 命名统一

`state["memory_context"]` / Planner prompt 中的 "Memory context" 字面 / Executor 新增的 XML 段统一为 `working_memory`。Planner node 仍写进 `state["working_memory"]`（原 `memory_context` 字段改名）。

## Impact

### 受影响模块

- `src/annie/npc/memory/interface.py` — `MemoryInterface.grep` 新方法
- `src/annie/world_engine/memory.py` — 实现 `grep`
- `src/annie/world_engine/store.py` — 支持 `where` + substring 扫描
- `src/annie/npc/tools/builtin.py` — 新增 `MemoryGrepTool`；`InnerMonologueTool.call` 改造
- `src/annie/npc/executor.py` — system 模板重写 / skip 路径去重 / `_render_identity` / `<working_memory>` 接入
- `src/annie/npc/planner.py` — prompt 重写 / 移除 history 渲染 / retry_context 渲染 / `state["working_memory"]` 重命名
- `src/annie/npc/reflector.py` — tolerant parser / metadata bug 修复 / 共用 `_render_identity`
- `src/annie/npc/agent.py` — `state["memory_context"]` → `state["working_memory"]`；Retry 路径把 `loop_reason` 和上轮 task 摘要写进 state 供 Planner 读取；`_build_response` 汇总 inner_thoughts
- `src/annie/npc/state.py` — 字段重命名；新增 `inner_thoughts: list[str]`、`last_tasks: list[Task]`

### 破坏性变更

- `MemoryInterface.grep` 为新增必需方法（Protocol 新增方法 → 所有实现需提供）。
- `state["memory_context"]` → `state["working_memory"]`。旧字段即时废弃，无兼容层。
- `Executor.EXECUTOR_SYSTEM_TEMPLATE` 结构变化。任何 snapshot 测试需更新。

### 不受影响

- `AgentContext` / `AgentResponse` 公共字段
- LangGraph 节点拓扑
- ChromaDB 物理布局
- change 2（Skills / todo）与 change 3（multi-NPC）的边界

## Non-Goals

- 预检索精度升级（grep 与 RAG 混合预检索）留给后续观察期
- plan_todo tool / Skill 解冻 / `<available_skills>` 接 SkillRegistry — 属 change 2
- 多 NPC / 事件总线 / 业务 tool hook — 属 change 3
- 两层压缩（Compressor / ContextBudget）的 spec 明文化留作 documentation-only patch，不在本 change 动代码
- InnerMonologue 是否暴露给世界引擎展示 UI — AgentResponse 暴露到此为止
