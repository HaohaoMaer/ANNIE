# Tool / Skill System Capability Spec

本 spec 定义 Tool 与 Skill 的分层、定义规范、激活机制。

## ADDED Requirements

### Requirement: Tool 与 Skill 是两种语义不同的能力单元

- **Tool**：一个机械可执行的能力单元，有结构化输入输出 schema，LLM 通过 tool_call 直接调用，结果喂回 LLM
- **Skill**：一个"带流程指导的 prompt 模板 + 允许调用的 Tool 子集"，**不被 LLM 直接调用**，而是在 Executor 匹配到相关任务时注入到 LLM 的指令中

二者不得混淆或合并。Skill 不是"复杂 Tool"，Tool 也不是"简单 Skill"。

#### Scenario: Tool 的调用

- **WHEN** LLM 生成 tool_call
- **THEN** 目标必须是一个 Tool 的名字（built-in 或世界引擎注入）
- **AND** 该 tool_call 进入 Executor 的执行循环，调用结果作为 observation 喂回 LLM

#### Scenario: Skill 的激活

- **WHEN** LLM 调用 `use_skill(skill_name, args)` built-in 工具
- **THEN** 该 Skill 的 `prompt` 被追加为 SystemMessage 到当前 messages 列表
- **AND** 本次 Executor loop 的后续轮次可见 skill.extra_tools 中声明的工具
- **AND** Executor loop 结束时 extra_tools 从 ToolRegistry 帧栈弹出，不再可见

#### Scenario: Skill 不是 Tool

- **WHEN** 枚举 AgentContext.tools
- **THEN** Skill 不出现其中
- **WHEN** LLM 查看可调用工具
- **THEN** 只看到 Tool 名字，看不到 Skill 名字

---

### Requirement: Tool 必须遵循统一的 ToolDef 规范

每个 Tool 必须具备：

- 唯一的 `name`
- 给 LLM 看的 `description`
- 结构化的 `input_schema`（Pydantic model 或等价）
- 可选的 `output_schema`
- `call(input, ctx)` 实际执行方法
- 元数据：`is_read_only`、`is_concurrency_safe` 等

具体类形态（Protocol / ABC / buildTool factory）由 plan 阶段决定，但必须在同一规范下。

#### Scenario: Tool 的统一注册

- **WHEN** 装配 ToolRegistry
- **THEN** built-in tools 与世界引擎注入的 tools 必须使用同一个 ToolDef 规范
- **AND** 不得存在两套不同的 Tool 基类

#### Scenario: Tool 的 schema 驱动

- **WHEN** LLM 请求工具列表
- **THEN** 每个 Tool 应能产出标准 JSON Schema 供 LLM 理解参数结构
- **AND** 调用时 Executor 对参数做 schema 校验

---

### Requirement: Skill 必须遵循统一的 SkillDef 规范

每个 Skill 必须具备：

- `name`：唯一 id
- `one_line`：一句话描述，作为 `<available_skills>` 的渐进披露第一层
- `prompt`：激活时追加到 messages 的 SystemMessage 内容
- `extra_tools`：激活时临时可见的 tool id 列表；所引用 tool 必须在 ToolRegistry 或 AgentContext.tools 中已注册
- `triggers`（可选）：人类/UI 索引用关键词，不参与自动激活

Skill 可通过 YAML manifest（`skill.yaml`）+ 同目录 `prompt.md` 的文件形式组织，由 `SkillRegistry.load_dir(path)` 统一加载。

#### Scenario: Skill 解锁额外工具

- **WHEN** `use_skill(skill_name="deduction")` 被调用
- **AND** deduction 的 `extra_tools` 中含 `evidence_cross_check`
- **THEN** 本 Executor loop 的下一轮 bind_tools 中必须包含 `evidence_cross_check`
- **AND** 该工具在 Executor loop 结束后不再可见

#### Scenario: Skill 激活不 fork 子 Agent

- **WHEN** `use_skill` 被调用
- **THEN** 当前 AgentContext / messages / tool_registry 保持同一实例
- **AND** 不得创建新的 NPCAgent / 新 LangGraph 执行

#### Scenario: extra_tools 引用必须存在

- **WHEN** 激活 `SkillDef(extra_tools=["evidence_cross_check"])`
- **AND** `evidence_cross_check` 未在 ToolRegistry 注册
- **THEN** 激活期必须立即报错（ValueError）
- **AND** 不得静默跳过

#### Scenario: Skill 无 schema

- **WHEN** 定义一个 Skill
- **THEN** 不需要 input_schema / output_schema（它不被直接调用）
- **AND** 其"输入"来自任务上下文与 NPC 当前状态

---

### Requirement: 基础 Tools 位于 NPC Agent 层，业务 Tools 位于世界引擎层

- **基础 Tools**（memory_recall / memory_store / inner_monologue 等通用能力）：必须在 NPC Agent 层内置
- **业务 Tools**（inspect_item / move_to_location / perceive_scene 等与具体世界相关）：必须在世界引擎层定义

#### Scenario: 基础工具不应要求世界引擎重复注册

- **WHEN** 不同的世界引擎接入 NPC Agent
- **THEN** 每个世界引擎无需重新定义 memory_recall 等基础工具
- **AND** 这些工具由 NPC Agent 在装配 ToolRegistry 时自动包含

#### Scenario: 业务工具不应出现在 NPC Agent 层

- **WHEN** 代码审查 `src/annie/npc/tools/` 目录
- **THEN** 不应出现 inspect_item 等业务相关工具
- **AND** 这些工具的定义与实现均位于 world_engine 层

---

### Requirement: Skill 仅位于世界引擎层

Skill 是业务特化的流程指导（审讯、推理、谈判等均与具体世界设定强绑定），必须由世界引擎层定义。NPC Agent 层不得内置任何 Skill。

#### Scenario: NPC Agent 层无 Skill

- **WHEN** 代码审查 `src/annie/npc/skills/` 目录
- **THEN** 只应存在 SkillDef 规范（base）和 Skill 注册 / 匹配机制
- **AND** 不应存在任何具体 Skill 实例

---

### Requirement: Tool 与 Skill 的合并在 Agent 内部对 LLM 统一呈现

NPC Agent 的 ToolRegistry 合并 built-in tools 与 `AgentContext.tools`；SkillRegistry 接收 `AgentContext.skills`。对 LLM 而言，可用工具就是合并后的统一集合，不感知来源。

#### Scenario: 工具来源透明化

- **WHEN** LLM 看到可调用工具列表
- **THEN** 不知道某个工具是 built-in 还是世界引擎注入
- **AND** 调用方式完全相同

#### Scenario: 命名冲突

- **WHEN** built-in tool 与注入 tool 同名
- **THEN** 行为必须是明确定义的（由 plan 阶段决定优先规则）
- **AND** 不得静默覆盖造成行为不可预测

---

### Requirement: Tool 执行上下文可访问 AgentContext 的扩展字段

Tool.call 方法接收的 ctx 参数中，必须能访问当前运行的 AgentContext（或其相关部分），以便工具实现可以读取世界引擎注入的扩展数据。

#### Scenario: Tool 访问扩展字段

- **WHEN** 一个业务 Tool 需要知道 "当前场景 ID"
- **THEN** 通过 ctx 访问 AgentContext.extra["scene_id"]
- **AND** 不需要通过参数传入（避免 LLM 需要知道这些内部细节）

#### Scenario: Tool 访问 MemoryInterface

- **WHEN** 一个 built-in tool（如 memory_recall）执行
- **THEN** 通过 ctx 访问 AgentContext.memory
- **AND** 不通过构造函数依赖注入（因为每次 run 的 memory 实例可能不同）
## Requirements
### Requirement: built-in 工具必须包含 `memory_grep`

`memory_grep` 与 `memory_recall` 并列为长期记忆的一等检索入口，覆盖字面/元数据命中场景。

- 输入至少接受：`pattern: str`、`category: str | None`、`metadata_filters: dict | None`、`k: int`。
- 实现必须调用 `MemoryInterface.grep`，不得自行实现检索逻辑。
- 声明为 `is_read_only = True`。

#### Scenario: 模型能在同一轮 tool-use loop 内混合使用

- **WHEN** 模型连续调用 `memory_recall` 与 `memory_grep`
- **THEN** Executor tool loop 正常分派两者
- **AND** 返回结构一致（records 列表）

---

### Requirement: inner_monologue 输出必须被 AgentResponse 消费

`inner_monologue` 工具每次调用的 `thought` 必须在本次 `run()` 结束时汇总进入 `AgentResponse.inner_thought`。

- 可通过 `AgentContext.extra` 的约定键承载跨 tool / 跨节点的传递，不得新增 AgentState 上不相关的字段。
- 多次调用的内容按调用顺序拼接。

#### Scenario: 多次 inner_monologue 被完整保留

- **WHEN** 在一次 run 内 `inner_monologue` 被调用三次
- **THEN** `AgentResponse.inner_thought` 按顺序含三段思考文本
- **AND** 不得丢弃、不得去重

#### Scenario: 未调用时保持空

- **WHEN** 模型未调用 `inner_monologue`
- **THEN** `AgentResponse.inner_thought` 为空字符串

---

### Requirement: Skill 激活必须通过 `use_skill` 工具显式发起，不允许自动匹配

`use_skill(skill_name, args)` 是 Skill 激活的唯一入口。Skill 不得作为独立 tool 注册进 tool schema，防止 skill 数量膨胀时污染 LLM 工具列表。

- Skill 激活必须**同进程、in-loop**：在当前 Executor tool loop 内追加一个 SystemMessage（skill.prompt）并临时解锁 extra_tools，不得 fork 子 Agent。
- Skill 的退出为"自然退出"：当模型下一轮不再 tool_call 时 Executor loop 正常结束，同时卸载临时工具（pop_frame）。
- 同一 run 内允许叠加多个 skill 激活，按栈式顺序 pop。

#### Scenario: Skill 名称在 tool schema 中不出现

- **WHEN** LLM 查看可调用 tool 列表
- **THEN** 看到的是 `use_skill`，而非具体 skill 名
- **AND** 具体 skill 名通过 system prompt 的 `<available_skills>` 段暴露

---

### Requirement: built-in 工具必须包含 `plan_todo`，支持跨回合目标持久化

`plan_todo` 作为 built-in 工具提供 `add / complete / list` 三个动作，持久化使用 `category="todo"` 的长期记忆：

- `add(content)` 写入一条 open 状态的 todo 记忆（metadata: `{status: open, todo_id: <8-hex>, created_at: <ISO8601 UTC>}`）
- `complete(todo_id)` 以事件追加的方式标记某个 todo 为 closed（不修改原记录）；调用前必须校验该 id 存在且状态为 open，否则返回 `{"success": False, "error": "unknown or already closed"}` 且不写任何记录
- `list()` 返回当前未关闭的 todo 集合（open 集合减去 closed 集合），每项包含 `{todo_id, content, timestamp}`，按 `timestamp` 倒序（最新在前）

Executor system prompt 必须在 `<todo>` 段渲染当前所有 open 的 todo；渲染过程在 `run()` 入口完成（与 `working_memory` 同阶段）。

#### Scenario: 跨 run 可见

- **WHEN** run1 调用 `plan_todo(add, "去厨房找匕首")`
- **THEN** run2 的 Executor system `<todo>` 段必须列出该项

#### Scenario: complete 后不再出现

- **WHEN** run2 调用 `plan_todo(complete, todo_id)`
- **THEN** run3 的 `<todo>` 段不再显示该项

#### Scenario: todo 作为一等 category

- **WHEN** 模型在 `memory_recall(categories=["todo"])` 中查询
- **THEN** 能检索到 open / closed 所有 todo 条目
- **AND** 不应在 `episodic / semantic / reflection / impression` 中出现 todo 条目

#### Scenario: complete 未知 id 不写记录

- **WHEN** 对一个不存在的 todo_id 调用 `plan_todo(complete)`
- **THEN** 工具返回 `{"success": False, "error": ...}`
- **AND** 向量库 `todo` 类别下没有新增 closed 记录

#### Scenario: complete 已关闭 id 失败

- **WHEN** 同一 todo_id 被 `complete` 两次
- **THEN** 第二次返回失败且不写记录

#### Scenario: add 写入 created_at 元数据

- **WHEN** 调用 `plan_todo(add, content)`
- **THEN** 写入记录的 metadata 中包含 `created_at`（ISO8601 UTC 格式）与 `todo_id`

#### Scenario: list 带元数据且倒序

- **WHEN** 先后 `add("A")` 与 `add("B")` 两个 todo
- **THEN** `list()` 返回顺序为 `[B, A]`
- **AND** 每项含 `todo_id / content / timestamp` 三字段

