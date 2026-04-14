# Tool & Skill System Capability Spec — Delta

本次 change 对 tool-skill-system capability 的修订。

## MODIFIED Requirements

### Requirement: Executor 必须通过原生 tool-use loop 调用 Tool

原有的"ToolAgent 关键词匹配 → 预跑工具 → 结果拼进 prompt"路径作废。取而代之：

- Executor 使用 `llm.bind_tools(all_tools)` 的原生 tool-use 通道
- 模型输出 `tool_calls` 时由 ToolAgent 作为 dispatcher 执行并返回 `ToolMessage`
- Executor 在一个 observe-think-act 循环中反复 invoke 直到模型输出无 tool_call 的 final answer
- `AgentState.messages: list[BaseMessage]` 承载整个 run 的 working context

#### Scenario: 模型自主决定工具调用

- **WHEN** 模型判断需要查记忆
- **THEN** 产出 tool_call 指向 memory_recall，参数由模型填
- **AND** Executor 不通过任何关键词匹配预先触发工具

#### Scenario: 多轮 tool-use

- **WHEN** 单个 task 需要多次工具调用
- **THEN** Executor 按 tool_call → ToolMessage → 再 invoke 的循环推进
- **AND** 每轮 LLM 调用前执行 ContextBudget.check

#### Scenario: ToolAgent 退化为 dispatcher

- **WHEN** Executor 处理 tool_calls
- **THEN** ToolAgent 只负责按 name 查表、参数校验、调用 ToolDef.call、错误边界
- **AND** 不再做任何 keyword matching 或工具选择

---

### Requirement: Tool 通过**全量 JSON Schema** 暴露给模型

所有可用 Tool 的完整 JSON schema 通过 `llm.bind_tools` 的原生通道传递：

- 不将 tool 名称/描述嵌入 system prompt 做"渐进披露"
- 渐进披露未来仅用于 Skill（本次不做）
- Built-in tools（`memory_recall` / `memory_store` / `inner_monologue`）与 WorldEngine 注入的 tools 合并后统一 bind

#### Scenario: bind_tools 覆盖所有可用工具

- **WHEN** Executor 启动一次 run
- **THEN** ToolRegistry 合并 built-in + context.tools
- **AND** 全量 schema 通过 llm.bind_tools 传入
- **AND** 冲突时 built-in 胜出并打 warning（保持现有策略）

---

### Requirement: Skill 能力在本次 change 中冻结

`SkillDef` / `SkillRegistry` 接口保留，但运行时不再激活：

- `SkillAgent.try_activate` 立即返回 `None` 并打一次 `DeprecationWarning`
- Executor 不再尝试注入 skill prompt 或过滤工具子集
- 现有 skill 定义文件保留，future change 将以 `use_skill(name)` tool + 渐进披露方案恢复

#### Scenario: try_activate 为 no-op

- **WHEN** Executor 调用 SkillAgent.try_activate(task, tracer)
- **THEN** 返回 None
- **AND** 发出一次 DeprecationWarning（整个进程内去重）

#### Scenario: Skill 定义仍可加载

- **WHEN** WorldEngine 从 YAML 加载包含 skills 的 NPC 定义
- **THEN** SkillDef 对象正常构造并放入 AgentContext.skills
- **AND** 不因为运行时冻结而阻止装载
