# NPC Agent 层 Capability Spec — Delta

本次 change 对 npc-agent capability 的修订。

## MODIFIED Requirements

### Requirement: Executor 构造的 system prompt 必须暴露 memory category 目录与预检索结果

Executor 的 system message 必须以固定 XML 分段呈现以下内容，顺序稳定：

1. `<character>` — NPC 身份与性格 prompt
2. `<world_rules>` — 世界规则 prompt
3. `<situation>` — 当前场景 prompt
4. `<memory_categories>` — 枚举长期记忆的五类 category 及各自一行含义
5. `<working_memory>` — Planner 阶段预检索得到的 memory context（未命中时渲染 `(none)`）
6. `<available_skills>` — 可用 skill 列表（本 change 仍为占位，change 2 接 SkillRegistry）

system 文本尾部的通用指令必须**不得硬编码具体 tool 名**；应以引用"本轮 tool schema"的方式说明可用工具。

#### Scenario: working_memory 透传而非重复查询

- **WHEN** Agent 入口 `run()` 已经调用 `MemoryAgent.build_context(input_event)` 得到 working_memory 字符串
- **THEN** Executor 的 `<working_memory>` 段必须直接读该字符串
- **AND** 不得在 Executor 内再次触发预检索

#### Scenario: 不得硬编码工具名

- **WHEN** 本 change 之后新增 built-in 工具（如 `memory_grep`）
- **THEN** 无须修改 Executor system template 即可被模型看见
- **AND** system 中不得出现形如 `e.g. memory_recall, memory_store, inner_monologue` 的枚举字面

---

### Requirement: Planner 必须以 skip 为默认，仅在真·多阶段场景下产出任务列表

Planner 的 static prompt 必须明确把 skip 作为默认响应，仅当事件需要不可合并的顺序阶段时才产出任务列表；任务数量建议上限压到 3。

Planner 的 dynamic prompt 不得再次渲染 history。history 的唯一消费路径是 Executor 的 message 序列。

#### Scenario: 单轮对话事件默认 skip

- **WHEN** 事件是一句他人台词或简单情绪触发
- **THEN** Planner 应返回 `{"skip": true, "reason": ...}`
- **AND** Executor 在 skip 合成路径下不得把 `input_event` 原文复制到 `task.description`，也不得在 trigger message 中渲染 `<task>` 段

#### Scenario: 真·多阶段事件产出有限任务

- **WHEN** 事件明确需要"先 A 再 B"的顺序推进（如"先去取证据再回来质询"）
- **THEN** Planner 可产出至多 3 个任务
- **AND** 任务 description 必须是可执行动作，不得与 input_event 文本重合

---

### Requirement: 重试路径必须向 Planner 暴露失败原因与上轮任务摘要

当 Executor 无产出、流程重走 Planner 时，Planner 在本轮 user_content 中必须包含：

- 失败原因字符串（`loop_reason`）
- 上一轮的 task 描述列表摘要

这段信息必须以显式分段（如 `<retry_context>`）呈现，Planner 据此修正规划或直接改判 skip。

#### Scenario: 重试时 Planner 能看到上轮失败

- **WHEN** `retry_count > 0`
- **THEN** Planner user_content 必须含 `<retry_context>` 段
- **AND** 段内至少包括 `loop_reason` 与上轮 task 描述摘要

#### Scenario: 首轮不渲染 retry_context

- **WHEN** `retry_count == 0`
- **THEN** Planner user_content 不得渲染 `<retry_context>`

---

### Requirement: Reflector 对 FACTS / RELATIONSHIP_NOTES 必须使用容错解析

Reflector 从 LLM 响应中解析 FACTS / RELATIONSHIP_NOTES 列表时，必须按如下优先级容错：

1. 优先 `json.loads` 严格 JSON
2. 失败回退 bullet list 解析（`-` / `*` / `•` / `1.` / `1)` 开头的行）
3. 仍失败返回空列表

Reflector 写入 semantic 记忆时不得把 category 混入 metadata；category 必须通过顶层字段传递。

#### Scenario: bullet 列表被正确解析

- **WHEN** LLM 返回 `FACTS:\n- 李四昨晚在餐车\n- 匕首上有指纹`
- **THEN** 必须解析为 `["李四昨晚在餐车", "匕首上有指纹"]`
- **AND** 不得静默丢弃

#### Scenario: metadata.category 残留消除

- **WHEN** Reflector 存 semantic 事实
- **THEN** 不得向 metadata 写入 `category` 键
- **AND** category 通过 MemoryInterface 的顶层字段指定
