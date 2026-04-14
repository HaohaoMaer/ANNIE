# Tool / Skill System Capability Spec — Delta

本次 change 对 tool-skill-system capability 的修订。

## ADDED Requirements

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
