# NPC Agent 层 Capability Spec — Delta

本次 change 对 npc-agent capability 的修订。

## MODIFIED Requirements

### Requirement: Executor system 的 `<available_skills>` 与 `<todo>` 段必须动态渲染

change 1 为这两个段落预留了位置，本 change 接入真实数据源：

- `<available_skills>`：从 `SkillRegistry` 与 `AgentContext.skills` 的并集（以 name 去重，AgentContext 覆盖）渲染，每行 `- {name}: {one_line}`。空时渲染 `(none)`。
- `<todo>`：从 `run()` 入口预计算的 `todo_list_text` 读取，内容由 `plan_todo` 工具维护的 `category="todo"` 记忆构建。空时渲染 `(none)`。

两段必须都参与每次 Executor system 构造，不得按条件省略，以保证 prompt 结构稳定。

#### Scenario: 无 skill / 无 todo 时渲染占位

- **WHEN** SkillRegistry 与 AgentContext.skills 均为空
- **THEN** `<available_skills>` 渲染 `(none)`，不得省略该段
- **WHEN** 当前 NPC 没有 open todo
- **THEN** `<todo>` 渲染 `(none)`，不得省略该段

#### Scenario: 渐进披露第一层

- **WHEN** 模型查看 `<available_skills>`
- **THEN** 每个 skill 只暴露 `name` 与 `one_line`
- **AND** 不得暴露 `prompt` 全文、`extra_tools` 列表等细节

---

### Requirement: SkillRegistry 实例必须可被 `use_skill` 工具访问

Agent 的装配过程必须保证 `use_skill` 工具在执行时可以取到 SkillRegistry 实例来查 skill 元数据并完成激活。推荐通过 `AgentContext.extra` 的约定键（例如 `_skill_agent`）传递，避免在 NPCAgent 或 Executor 的 `self` 上藏状态。

#### Scenario: use_skill 取不到 registry 时的兜底

- **WHEN** `use_skill` 被调用
- **AND** 无可用 SkillRegistry
- **THEN** 返回结构化错误字符串，不得抛 uncaught 异常
