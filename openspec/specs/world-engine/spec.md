# 世界引擎层 Capability Spec

## Purpose

本 spec 定义世界引擎层的职责、边界与契约，确保业务状态、行动裁决、记忆后端、历史压缩和多 NPC 推进逻辑都由世界引擎层拥有，而 NPC Agent 层保持 stateless、业务无关。
## Requirements
### Requirement: 世界引擎层必须承载所有业务状态与业务逻辑

世界引擎层 MUST 是所有业务复杂度的唯一承载者，包括：世界状态、NPC 身份与设定、所有 NPC 的记忆存储、业务工具实现、技能定义、场景推进逻辑、行动裁决逻辑。

#### Scenario: 新玩法的实现位置

- **WHEN** 需要实现一种新玩法（如剧本杀、AI 主持人、沙盒）
- **THEN** 新增代码必须全部位于世界引擎层
- **AND** 不得要求修改 NPC Agent 层

#### Scenario: 业务状态的唯一真相源

- **WHEN** 查询某个 NPC 的当前状态、位置、已知线索等业务数据
- **THEN** 世界引擎是唯一真相源
- **AND** NPC Agent 层不得缓存或复制此类数据

---

### Requirement: 世界引擎必须实现 WorldEngine 抽象基类

所有具体的世界引擎实现（剧本杀、AI 主持人、沙盒等）MUST 继承同一 `WorldEngine` 抽象基类，实现其规定的最小接口方法。具体方法集合由 plan 阶段定案，至少包括：构造 AgentContext、处理 AgentResponse、提供 MemoryInterface 实例。

#### Scenario: 接口一致性

- **WHEN** 上层代码持有一个 WorldEngine 引用
- **THEN** 不应依赖其具体实现类型即可驱动 NPC 运行完整一轮

#### Scenario: 扩展新引擎

- **WHEN** 新增一种世界引擎实现
- **THEN** 只需继承 WorldEngine 基类并实现其抽象方法
- **AND** 不得要求修改 NPC Agent 层或基类本身

---

### Requirement: 世界引擎必须为每次 Agent 运行构造完整的 AgentContext

在调用 NPCAgent.run() 之前，世界引擎 MUST 构造包含所有必要字段的 AgentContext：NPC 身份、触发事件、可用工具、MemoryInterface 实例、character_prompt、世界规则、当前场景描述。世界引擎 MAY additionally request an NPC execution route for the run, and when it does, it MUST provide route-appropriate context, tools, and validation responsibilities without moving business logic into the NPC Agent layer.

#### Scenario: Context 的完整性

- **WHEN** 世界引擎构造 AgentContext 时遗漏必填字段
- **THEN** NPCAgent 运行应立即失败并给出明确错误，而非静默使用默认值

#### Scenario: character_prompt 的构造责任

- **WHEN** 世界引擎想让 NPC 表现出特定性格、情绪、动机
- **THEN** 世界引擎负责将这些信息拼接为自然语言字符串放入 `character_prompt`
- **AND** NPC Agent 层不做任何结构化拼装

#### Scenario: Route selection remains world-owned

- **WHEN** 世界引擎需要 NPC 生成世界行动、托管会话台词、结构化 JSON、或 distilled reflection
- **THEN** 世界引擎通过 `AgentContext.route` 选择对应 NPC execution route
- **AND** 世界引擎仍然负责业务状态、工具实现、行动裁决、结构化输出校验和长期记忆持久化

#### Scenario: Macro planning remains world-owned

- **WHEN** 世界引擎需要生成或修订长期计划、每日日程、未来行动序列、或跨 tick 的策略
- **THEN** it may request candidate plan text through the structured JSON route
- **AND** it remains responsible for parsing, validating, accepting, persisting, revising, cancelling, and advancing that plan
- **AND** it does not rely on the NPC action-route planner as persistent plan state

#### Scenario: Dialogue route context does not grant world actions

- **WHEN** 世界引擎请求 managed dialogue route
- **THEN** it provides dialogue/session context and memory access as appropriate
- **AND** it does not expose movement, interaction, wait, schedule completion, or conversation-start tools for that route

#### Scenario: Structured JSON route validation remains world-owned

- **WHEN** 世界引擎请求 structured JSON route
- **THEN** it provides the output requirements in route context
- **AND** it parses and validates the returned structured-output text according to its own business schema
- **AND** it decides whether malformed or schema-invalid output should be repaired, retried, rejected, or handled by fallback logic

#### Scenario: Reflection route evidence remains world-owned

- **WHEN** 世界引擎请求 reflection route
- **THEN** it provides the evidence, memory summary, and persistence context needed for distilled reflection
- **AND** it does not rely on the NPC Agent layer to perform implicit memory recall for reflection
- **AND** it remains responsible for deciding whether the returned reflection should be persisted

#### Scenario: Legacy direct-mode flags are migrated

- **WHEN** an existing world engine integration still uses temporary `extra["npc_direct_mode"]` flags
- **THEN** it should migrate to `AgentContext.route`
- **AND** compatibility mappings may be used only during the migration period

### Requirement: 世界引擎必须裁决 NPC 返回的行动意图

NPC Agent 的 AgentResponse 中包含行动意图（ActionRequest）。世界引擎收到后 MUST 进行裁决：允许执行、修改后执行、或拒绝。世界引擎据此更新世界状态并决定下一步。

#### Scenario: 合法行动被执行

- **WHEN** NPC 表达意图"打开门"且世界状态允许
- **THEN** 世界引擎执行该动作并更新世界状态

#### Scenario: 非法行动被拒绝或修改

- **WHEN** NPC 表达意图"打开保险柜"但没有钥匙
- **THEN** 世界引擎可拒绝该动作或修改为"尝试打开保险柜（失败）"
- **AND** 裁决结果应反馈给 NPC（通常作为下一轮的 input_event）

---

### Requirement: 世界引擎必须实现 MemoryInterface

每个世界引擎实例 MUST 能提供一个 `MemoryInterface` 实现，供 NPC 通过 built-in tools 读写记忆。MemoryInterface 的具体后端（向量库、内存、文件）由世界引擎自行决定。

#### Scenario: 默认实现

- **WHEN** 未指定自定义记忆后端
- **THEN** 提供一个包装 ChromaDB 的默认 MemoryInterface 实现
- **AND** 该实现支持 semantic / reflection / relationship 等常见 type

#### Scenario: 多 NPC 的记忆隔离

- **WHEN** 一个世界引擎管理多个 NPC
- **THEN** 每个 NPC 的记忆必须在逻辑上隔离
- **AND** NPC A 的 recall 不得返回 NPC B 的私有记忆（除非明确共享）

---

### Requirement: 世界引擎负责 NPC YAML / 配置的解析

现有 NPC YAML 中的 personality、background、goals、relationships 等字段 MUST 由世界引擎自行解析并转换为 AgentContext 的 character_prompt 或其他字段。NPC Agent 层不得直接加载 NPC YAML。

#### Scenario: YAML 解析位置

- **WHEN** 新建一个 NPC
- **THEN** YAML 加载与解析必须发生在世界引擎层
- **AND** NPC Agent 层的代码中不得出现 `load_npc_profile` 或直接读取 NPC YAML 文件的调用

#### Scenario: relationships 字段的转换

- **WHEN** NPC YAML 中声明了 `relationships: [{target: X, type: friend, intensity: 0.8}]`
- **THEN** 世界引擎负责将其转为自然语言（如 "你与 X 是朋友，关系紧密"），嵌入 character_prompt
- **AND** 静态数值不得直接传入 NPC Agent 层

---

### Requirement: 世界引擎决定"接下来发生什么"

场景推进（时间流逝、事件触发、NPC 调度、剧情进展）MUST 完全由世界引擎控制。NPC Agent 层不得内置任何场景推进逻辑。

#### Scenario: 时间推进

- **WHEN** 需要时间流逝或场景切换
- **THEN** 由世界引擎决定并主动触发下一轮 NPC 运行
- **AND** NPC Agent 不得自行决定"等待 X 分钟"这类世界级副作用

#### Scenario: 多种引擎的推进模式

- **WHEN** 世界引擎是剧本杀引擎
- **THEN** 推进基于剧本阶段控制与规则触发
- **WHEN** 世界引擎是 AI 主持人引擎
- **THEN** 推进由主持人 Agent（另一个 LLM）动态决策
- **WHEN** 世界引擎是沙盒引擎
- **THEN** 推进基于物理/规则模拟，最小干预

---

### Requirement: HistoryStore 必须提供 prune 原语

HistoryStore MUST provide a prune primitive for removing old JSONL entries.

`HistoryStore.prune(keep_last: int | None = None, before_turn_id: int | None = None) -> int`
MUST 负责按条数或按 turn_id 分界删除旧条目，返回删除条数。两参数互斥；同时指定必须抛错。

淘汰策略由 WorldEngine 决定；HistoryStore 自身不感知"游戏时间"或"场景"等上层概念。

#### Scenario: 按条数保留

- **WHEN** 调用 `prune(keep_last=100)` 且当前有 250 条条目
- **THEN** JSONL 只剩最新 100 条
- **AND** 返回值 = 150

#### Scenario: 按 turn_id 分界

- **WHEN** 调用 `prune(before_turn_id=42)`
- **THEN** `turn_id <= 42` 的条目被删除
- **AND** 返回值 = 被删除条数

#### Scenario: 两参数互斥

- **WHEN** 同时指定 `keep_last` 与 `before_turn_id`
- **THEN** HistoryStore 必须抛出参数错误

---

### Requirement: Compressor 必须使用游标模式折叠，不得修改 JSONL

Compressor MUST 维护 `last_folded_turn_id` 持久化游标；折叠范围始终是"游标之后"的未折叠对话段。折叠完成后：

- 向 MemoryInterface 写一条 `impression` 摘要
- 更新游标到本次折叠末尾的 turn_id
- **不修改** HistoryStore 中的任何条目

游标的持久化由 HistoryStore 侧的 metadata sidecar（或等价机制）支撑，跨进程恢复。

#### Scenario: 折叠后 JSONL 不变

- **WHEN** 触发 `Compressor.force_fold`
- **THEN** JSONL 文件的条目数与内容均未改变
- **AND** 向量库新增一条 `impression` 记录
- **AND** `last_folded_turn_id` 推进到最新折叠结束位置

#### Scenario: 折叠不会重折同一段

- **WHEN** 连续两次 `maybe_fold` 且期间无新增对话
- **THEN** 第二次返回 None（无新内容可折叠）

#### Scenario: prune 后的游标仍然有效

- **WHEN** `prune(before_turn_id=X)` 删除的范围已覆盖游标位置
- **THEN** 下一次折叠从当前 JSONL 中最老的未折叠条目起算
- **AND** 不抛错、不重复折叠

---

### Requirement: Compressor 必须屏蔽异常，不传播到 handle_response

`Compressor.maybe_fold` 在任何 LLM 调用失败、存储异常、或 LLM 输出不合格的情况下，MUST 返回 `False` 而不得向上抛出。游标 `last_folded_turn_id` 不推进，下次 tick 自然重试。日志级别至少 `warning`。

LLM 输出"不合格"定义（轻量启发式，不试图检测幻觉）：
- 空串或纯空白
- 命中明显拒绝模式（如 `"I cannot"`, `"I can't"`, `"As an AI"`, `"Sorry"` 开头）
- 压缩比不足：`len(summary) >= len(raw) * 0.7`
- 过短：`len(summary.strip()) < 20`

此约束的目的是保证一个 NPC 的压缩失败不会崩掉整个世界 tick（尤其在并发多 NPC 响应同一事件时）。

#### Scenario: LLM 超时不崩 handle_response

- **WHEN** `_summarize` 内部 `llm.invoke` 抛出任意异常
- **THEN** `maybe_fold` 返回 `False`
- **AND** `last_folded_turn_id` 不变
- **AND** `handle_response` 正常完成

#### Scenario: LLM 返回拒绝文本不写入记忆

- **WHEN** LLM 返回 `"I cannot help with that."` 或空串
- **THEN** 不调用 `memory.remember`
- **AND** `maybe_fold` 返回 `False`

---

### Requirement: Compressor 阈值必须可配置以支持小窗口模型部署

`FOLD_TOKEN_THRESHOLD` 与 `FOLD_TARGET_TOKENS` MUST 支持通过构造器注入；默认值（3000 / 1500）以 128k 窗口模型为参照。部署到小窗口模型（32k 及以下，如 Haiku / 本地开源模型）时，调用方必须能够在不修改源码的前提下降低阈值。

#### Scenario: 构造器覆盖默认阈值

- **WHEN** 以 `Compressor(history, memory, llm, fold_threshold=800, target_fold_tokens=400)` 构造
- **THEN** 使用注入的阈值，不使用模块级默认

---

### Requirement: handle_response 不再将对话写入向量库 episodic

`DefaultWorldEngine.handle_response` MUST 仍将对话追加到 HistoryStore，但**不再**调用 `memory.remember(..., category=EPISODIC)`。对话的权威来源是 JSONL；向量库只承载提炼物（见 memory-interface spec）。

#### Scenario: handle_response 后向量库 episodic 不增

- **WHEN** 调用 `handle_response(npc_id, response)` 且 response.dialogue 非空
- **THEN** 向量库中该 NPC 的 `episodic` 类别条目数量不变
- **AND** HistoryStore.jsonl 新增一条 speaker=npc_id 的条目

---

### Requirement: Concrete world engines may provide replayable multi-NPC simulation

A concrete world engine MAY implement replayable multi-NPC simulation, but any such implementation MUST keep simulation state and business rules in the world-engine layer and expose NPC-visible state only through `AgentContext`, memory interfaces, and injected tools.

#### Scenario: Simulation state remains world-owned

- **WHEN** a concrete engine tracks time, locations, schedules, occupants, local events, or replay snapshots
- **THEN** those structures are owned by the world-engine layer
- **AND** the NPC Agent layer remains stateless across runs

#### Scenario: Concrete engine injects action tools

- **WHEN** a concrete engine supports business actions such as moving, observing, speaking, interacting, or waiting
- **THEN** the actions are exposed through `AgentContext.tools` or the agreed `tools_for(npc_id)` path
- **AND** the engine arbitrates every resulting world mutation

#### Scenario: Replay output is engine-owned

- **WHEN** a concrete engine emits replay/checkpoint artifacts
- **THEN** replay serialization is implemented in the concrete engine or world-engine support modules
- **AND** NPC Agent code does not depend on replay schemas

### Requirement: 世界引擎提示策略必须把日程作为默认锚点

当具体世界引擎使用日程或类似计划机制时，世界引擎 MUST render prompt policy that treats the current schedule as the default anchor while allowing explicit high-priority exceptions.

日程生成、日程修订、日程持久化、完成度跟踪、动态插入、取消和冲突处理 are macro-planning responsibilities owned by the concrete world engine. The NPC Agent layer MAY draft schedule-like structured text through the structured JSON route, but it MUST NOT own accepted schedule state or decide future route activations.

#### Scenario: Schedule remains default

- **WHEN** an NPC has an active schedule and no urgent event, direct request, or clearly valuable opportunity
- **THEN** the world engine context instructs the NPC to prefer schedule-relevant movement or action

#### Scenario: High-priority detour is allowed with time budget

- **WHEN** an urgent event, direct request, or clearly valuable opportunity appears
- **THEN** the world engine context may allow a brief detour
- **AND** it must also instruct the NPC to consider travel/action time and return to the schedule promptly

#### Scenario: Schedule drafting uses structured JSON

- **WHEN** a world engine asks the NPC layer to draft a daily schedule or schedule revision
- **THEN** it uses the structured JSON route or equivalent structured-output route contract
- **AND** it validates the candidate against world-owned time, location, overlap, and business rules before accepting it

### Requirement: 世界引擎提示策略允许工具失败后确认环境

当具体世界引擎提供 observe or equivalent perception tools, it MUST distinguish optional observation from required action, and MAY instruct the NPC to confirm the environment after a tool failure.

#### Scenario: Observe is not a default pre-action step

- **WHEN** the current context already contains enough location, exit, visible object, visible NPC, and event information
- **THEN** the world engine context instructs the NPC not to call observe merely as a default first step

#### Scenario: Tool failure can justify observation

- **WHEN** a world-action tool fails because the environment may be stale or ambiguous
- **THEN** the world engine context may instruct the NPC to call observe or an equivalent perception tool before retrying or choosing a fallback

