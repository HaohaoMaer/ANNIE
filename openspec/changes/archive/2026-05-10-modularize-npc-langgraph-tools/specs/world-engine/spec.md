## MODIFIED Requirements

### Requirement: 世界引擎必须裁决 NPC 返回的行动意图

NPC Agent 的 action-capable graph MAY call world-engine injected tools, but all concrete world side effects MUST execute through world-engine-owned tool implementations. The world engine MUST arbitrate each tool call by executing, rejecting, validating, or continuing it, and MUST return an explicit tool execution status for the NPC response path.

#### Scenario: 合法行动工具调用被执行

- **WHEN** NPC 通过 action graph 调用世界引擎提供的工具表达 "打开门"
- **THEN** 世界引擎执行对应工具并更新世界状态
- **AND** 工具返回 `success` 状态和有界结果摘要

#### Scenario: 非法行动工具调用返回失败或拒绝

- **WHEN** NPC 调用 "打开保险柜" 工具但世界状态显示没有钥匙
- **THEN** 世界引擎返回 `failure` 或 `rejected` 状态
- **AND** 状态信息说明失败原因或下一步可行提示
- **AND** 世界状态不得被非法修改

#### Scenario: 长耗时工具调用返回执行中

- **WHEN** NPC 调用一个无法在当前 tick 完成的世界工具
- **THEN** 世界引擎返回 `running` 状态
- **AND** 状态信息包含后续 tick 可关联的有界标识或摘要

#### Scenario: 声明式行动意图不再作为执行路径

- **WHEN** NPC response 包含仅声明意图但未通过世界引擎工具执行的行动描述
- **THEN** 世界引擎不得将该声明式意图作为独立副作用执行路径
- **AND** 如需产生世界副作用，必须通过世界引擎拥有的工具调用与状态返回完成

#### Scenario: 工具状态反馈给后续 NPC 上下文

- **WHEN** 世界引擎收到工具执行状态
- **THEN** it may persist the result, update history, or pass a bounded status summary into a later `AgentContext.input_event`
- **AND** NPC Agent 层不得直接拥有该状态的业务生命周期
