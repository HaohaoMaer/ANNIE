# Tool / Skill System Capability Spec — Delta

本次 change 对 tool-skill-system capability 的修订。

## MODIFIED Requirements

### Requirement: Skill 的激活必须通过统一的 `use_skill` 工具显式发起

上一 change 将 Skill 能力冻结，本 change 解冻并将激活口径统一为一个 built-in 工具 `use_skill(skill_name, args)`：

- Skill 不得作为独立 tool 注册进 tool schema，防止 skill 数量膨胀时污染 LLM 工具列表。
- Skill 激活必须**同进程、in-loop**：在当前 Executor tool loop 内追加一个 SystemMessage（skill.prompt）并临时解锁该 skill 的 `extra_tools`，不得 fork 子 Agent。
- Skill 的退出为"自然退出"：当模型下一轮不再 tool_call 时 Executor loop 正常结束，同时卸载临时工具。
- 同一 run 内允许叠加多个 skill 激活，按栈式顺序 pop。

#### Scenario: Skill 解锁额外工具

- **WHEN** 模型调用 `use_skill(skill_name="deduction", args={...})`
- **AND** deduction 的 `extra_tools` 中含 `evidence_cross_check`
- **THEN** 本 Executor loop 的下一轮 bind_tools 中必须包含 `evidence_cross_check`
- **AND** 该工具在 Executor loop 结束后不再可见

#### Scenario: Skill 激活不 fork 子 Agent

- **WHEN** use_skill 被调用
- **THEN** 当前 AgentContext / messages / tool_registry 保持同一实例
- **AND** 不得创建新的 NPCAgent / 新 LangGraph 执行

#### Scenario: Skill 名称在 tool schema 中不出现

- **WHEN** LLM 查看可调用 tool 列表
- **THEN** 看到的是 `use_skill`，而非具体 skill 名
- **AND** 具体 skill 名通过 system prompt 的 `<available_skills>` 段暴露

---

### Requirement: SkillDef 必须包含 `name / one_line / prompt / extra_tools`

Skill 的定义规范扩展为：

- `name`：唯一 id
- `one_line`：一句话描述，作为 prompt 渐进披露第一层
- `prompt`：激活时追加到 messages 的 SystemMessage 内容
- `extra_tools`：激活时临时可见的 tool id 列表；所引用 tool 必须在 ToolRegistry 或 AgentContext.tools 中已注册
- `triggers`（可选）：人类/UI 索引用，不参与自动激活

Skill 可通过 YAML manifest + 同目录 `prompt.md` 的文件形式组织，由 `SkillRegistry` 统一加载。

#### Scenario: extra_tools 引用必须存在

- **WHEN** 加载 `SkillDef(extra_tools=["evidence_cross_check"])`
- **AND** `evidence_cross_check` 未在 ToolRegistry 注册
- **THEN** 加载期或激活期必须立即报错
- **AND** 不得静默跳过

---

## ADDED Requirements

### Requirement: built-in 工具必须包含 `plan_todo`，支持跨回合目标持久化

`plan_todo` 作为 built-in 工具提供 `add / complete / list` 三个动作，持久化使用 `category="todo"` 的长期记忆：

- `add(content)` 写入一条 open 状态的 todo 记忆
- `complete(todo_id)` 以事件追加的方式标记某个 todo 为 closed
- `list()` 返回当前未关闭的 todo 集合

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
