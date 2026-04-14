# Context Compression Capability Spec

新增 capability：分层上下文管理与压缩策略。

## ADDED Requirements

### Requirement: 上下文按生命周期划分四档，归属明确

所有进出 NPC Agent 的上下文必须归类到以下四档之一，每档归属不可越界：

- **Stable**（WorldEngine 拥有）：`character_prompt`、`world_rules` 等角色/世界稳定态
- **Rolling**（WorldEngine 拥有）：`DialogueHistory` 等跨 run 累积、需要压缩的流式数据
- **Long-term**（WorldEngine 拥有）：ChromaDB 多类别记忆；Agent 通过 `MemoryInterface` 按需查询
- **Working**（Agent 拥有）：`AgentState.messages`、工具结果、召回回流等单 run 内数据

#### Scenario: Agent 不持有跨 run 状态

- **WHEN** NPCAgent.run() 返回后
- **THEN** AgentState 随之销毁
- **AND** 下一次 run() 只能通过新的 AgentContext 获取上下文
- **AND** `NPCAgent` 实例 `self` 上不得出现任何 per-NPC / per-run 的字段

#### Scenario: WorldEngine 不感知 Agent 内部 tool-use 过程

- **WHEN** Executor 在 run 内累积 messages / tool 调用
- **THEN** 这些中间状态不通过任何路径回流到 WorldEngine
- **AND** WorldEngine 只通过 `handle_response(AgentResponse)` 感知最终产物

---

### Requirement: 压缩策略五档按归属落位

| 策略     | 作用对象           | 归属        | 触发                     |
|----------|--------------------|-------------|--------------------------|
| Trim     | DialogueHistory    | WorldEngine | 每次 build_context       |
| Fold     | 连续 N 条 history   | WorldEngine | token 阈值 / scene 切换  |
| Auto     | (Fold 调度)        | WorldEngine | 后台/定时（本次不实装）   |
| Micro    | 单条工具输出/记忆  | Agent       | 插入 messages 前         |
| Emergency| Agent.messages    | Agent       | LLM 调用前预算超限       |

本 capability 必须实装 Trim / Fold / Micro / Emergency 四档。

#### Scenario: Trim 在 build_context 时生效

- **WHEN** WorldEngine.build_context 被调用
- **THEN** HistoryStore 的视图截断到最近 MAX_HISTORY_TURNS 条
- **AND** 未被截断的底层数据仍存在于存储中

#### Scenario: Fold 由 token 阈值触发

- **WHEN** handle_response 执行后，HistoryStore 估算 token 数 > FOLD_TOKEN_THRESHOLD
- **THEN** Compressor 取最旧的连续未折叠 turn 段送 LLM 摘要
- **AND** HistoryStore 中这 N 条 turn 被替换为一条 is_folded=True 的 FoldedEntry
- **AND** 同一 summary 以 category="impression" 写入 MemoryBackend

#### Scenario: Micro 压缩工具输出

- **WHEN** ToolAgent 拿到工具执行结果，内容长度 > MICRO_MAX_CHARS
- **THEN** 返回给 Agent messages 前被截断为头/尾保留、中间 [... truncated ...]
- **AND** 此操作不调用任何 LLM

#### Scenario: Emergency 在 LLM 调用前触发

- **WHEN** Executor 准备 llm.invoke，ContextBudget.check 发现输入 token + 预留输出 > 模型限制 × 0.9
- **THEN** 最早的若干 ToolMessage + 其前置 AIMessage(tool_call) 被 LLM 摘要折叠为 SystemMessage
- **AND** 最新 2 轮完整保留

---

### Requirement: Fold 产物同时替换 history 且写入 impression 类别

Fold 必须实现"遗忘细节，留下印象"的双写语义：

- **替换 history**：原始 N 条 raw turn 被单条 FoldedEntry(is_folded=True) 替代
- **写 impression**：同一 summary 以 `category="impression"` 落 MemoryBackend，metadata 含 `scene` / `time_range` / `source="fold"`
- **原始不删**：`handle_response` 阶段已落盘的 `episodic` 类记忆不受影响

#### Scenario: 深层追忆仍可唤回

- **WHEN** NPC 对话中需要回忆某条被 Fold 掉的细节
- **THEN** 通过 memory_recall(categories=["episodic"]) 可检索到原始条目
- **AND** history 字段中这段期间仅呈现 impression summary

#### Scenario: 禁止递归折叠

- **WHEN** Compressor 选取 Fold 候选段
- **THEN** is_folded=True 的 entry 不进入候选集
- **AND** 一次 Fold 产物是后续 Fold 的终态
