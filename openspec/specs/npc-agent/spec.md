# NPC Agent 层 Capability Spec

本 spec 定义 NPC Agent 层的职责、边界与契约。描述停留在语义层，不钉具体类型签名。

## ADDED Requirements

### Requirement: NPC Agent 层必须是通用 AI 能力框架，不承载任何业务假设

NPC Agent 层提供通用的角色驱动 AI 能力（规划、执行、反思），不得内置任何特定世界观、玩法或业务领域的知识。

#### Scenario: 剧本杀与沙盒共用同一 Agent 实现

- **WHEN** 一个世界引擎是剧本杀引擎，另一个是沙盒引擎
- **THEN** 两者必须能够复用完全相同的 NPC Agent 代码
- **AND** NPC Agent 代码中不得出现 "剧本"、"线索"、"阶段"、"沙盒"、"物理" 等业务词汇

#### Scenario: Agent 层代码变更的影响面

- **WHEN** 一个业务需求仅涉及某一种世界引擎（如给剧本杀加一个新的线索检查流程）
- **THEN** NPC Agent 层代码不应因此被修改

---

### Requirement: NPC Agent 不得持有任何业务持久状态

NPC Agent 实例在 `run()` 调用之间不得持有 NPC 身份、记忆、世界状态等持久数据。所有此类数据必须通过 `AgentContext` 在每次运行时注入。

#### Scenario: 多 NPC 共享单个 Agent 实例

- **WHEN** 世界引擎需要驱动 N 个不同的 NPC
- **THEN** 应允许使用一个 NPCAgent 实例，分别传入 N 个不同的 AgentContext
- **AND** 不得要求为每个 NPC 创建独立的 NPCAgent 对象

#### Scenario: Agent 可被安全丢弃与重建

- **WHEN** 世界引擎在两次运行之间销毁 NPCAgent 并重新创建
- **THEN** 业务行为必须与复用同一 Agent 实例完全等价

---

### Requirement: NPC Agent 保留 Planner → Executor → Reflector 的 LangGraph 流程

Agent 内部必须以 LangGraph 实现 Planner → Executor → Reflector 三节点循环，并保留 Executor 结果为空时重新规划的重试边。Planner 在 LLM 判断事件简单时可自行选择跳过（skip），不强制产生任务列表。

#### Scenario: 简单事件跳过规划

- **WHEN** 触发事件被 Planner LLM 判断为"无需多步分解"
- **THEN** Planner 返回 skip 信号
- **AND** Executor 直接处理原始事件而非任务列表

#### Scenario: Executor 无产出时的重试

- **WHEN** Executor 完成后所有任务状态均为 FAILED 或产出为空
- **AND** 重试次数未达上限
- **THEN** 流程必须回到 Planner 重新规划

---

### Requirement: NPC Agent 通过 AgentContext 接收输入，通过 AgentResponse 返回结果

`run()` 方法的输入契约是 `AgentContext`（由世界引擎构造），输出契约是 `AgentResponse`。不得通过其他旁路（全局状态、构造函数残留等）传递业务数据。

#### Scenario: Context 是唯一输入通道

- **WHEN** 代码审查发现 NPCAgent.run() 从 AgentContext 以外的来源读取 NPC 身份、工具、记忆、角色设定
- **THEN** 该代码违反本要求

#### Scenario: Response 是唯一输出通道

- **WHEN** NPC 的思考、对话、行动意图、记忆更新请求产生
- **THEN** 必须封装在 AgentResponse 中返回
- **AND** 不得通过回调、全局事件、直接修改传入对象等方式隐式输出

---

### Requirement: NPC Agent 层内置一组基础 Tools

NPC Agent 层必须在内部维护一组通用 built-in tools，至少包括：
- 记忆检索（对 MemoryInterface.recall 的 LLM 可见包装）
- 记忆写入（对 MemoryInterface.remember 的 LLM 可见包装）
- 内心独白 / 自言自语（用于 LLM 表达非对话性思考）

这些 built-in tools 在装配 ToolRegistry 时与 `AgentContext.tools`（世界引擎注入的业务工具）合并，对 LLM 呈现为统一工具集。

#### Scenario: LLM 可同时调用 built-in 与注入工具

- **WHEN** 一次 Executor 迭代中 LLM 输出 tool_call
- **THEN** 调用目标既可以是 built-in tools（如 memory_recall），也可以是 context.tools 注入的业务工具
- **AND** Agent 代码对二者的派发逻辑应一致

#### Scenario: 工具命名冲突

- **WHEN** 世界引擎注入的 tool 与 built-in tool 同名
- **THEN** 行为必须是明确定义的（要么 built-in 优先并警告，要么注入优先并警告——plan 阶段定），不得静默覆盖

---

### Requirement: NPC Agent 不得内置任何认知状态数据结构

NPC Agent 层代码中不得存在情绪状态、信念系统、动机引擎、关系图等认知数据结构。认知维度一律通过 `AgentContext` 的 prompt 文本字段（如 character_prompt）由世界引擎注入，由 LLM 从自然语言中实时推理。

#### Scenario: 认知结构被意外引入

- **WHEN** 有人在 NPC Agent 层添加形如 `class EmotionalState(BaseModel): ...` 或 `trust: float` 的结构
- **THEN** 违反本要求，应被拒绝合入

#### Scenario: 认知信息的正确传递方式

- **WHEN** 世界引擎希望让 NPC 知道自己"当前感到焦虑"
- **THEN** 应通过 `character_prompt` 中嵌入自然语言描述（如 "你此刻感到焦虑，因为..."）
- **AND** 不得通过结构化字段如 `emotion={"anxiety": 0.8}` 传递

---

### Requirement: Skill 通过 `use_skill` 内置工具显式激活，不作为独立执行单元

NPC Agent 层提供 `use_skill(skill_name, args)` built-in 工具，LLM 通过显式调用该工具来激活一个 Skill。激活是同进程 in-loop 的：在当前 Executor tool loop 内追加一个 SystemMessage（skill.prompt）并临时解锁 skill.extra_tools。Skill 名字本身不出现在工具 schema 中，具体可用 skill 通过 `<available_skills>` prompt 段暴露。

#### Scenario: Skill 激活 via use_skill

- **WHEN** LLM 调用 `use_skill(skill_name="deduction", args={...})`
- **THEN** Executor 向 messages 追加 SystemMessage（skill.prompt）
- **AND** skill.extra_tools 被临时推入 ToolRegistry 帧栈，下一轮 bind_tools 中可见
- **AND** Executor loop 结束时帧栈被弹出，extra_tools 不再可见

#### Scenario: Skill 不出现在 LLM 的 tool_call 列表中

- **WHEN** LLM 查看可调用工具列表
- **THEN** 只看到 `use_skill` 工具，不看到具体 skill 名字
- **AND** 具体 skill 名字通过 system prompt 的 `<available_skills>` 段暴露
## Requirements
### Requirement: Executor 构造的 system prompt 必须暴露 memory category 目录、预检索结果、todo 与可用 skill

Executor 的 system message 必须以固定 XML 分段呈现以下内容，顺序稳定：

1. `<character>` — NPC 身份与性格 prompt
2. `<world_rules>` — 世界规则 prompt
3. `<situation>` — 当前场景 prompt
4. `<memory_categories>` — 枚举长期记忆的五类 category 及各自一行含义
5. `<working_memory>` — Planner 阶段预检索得到的 memory context（未命中时渲染 `(none)`）
6. `<todo>` — 当前 NPC 未完成的跨回合目标（由 `plan_todo` 工具维护；空时渲染 `(none)`）
7. `<available_skills>` — 可用 skill 列表，从 `SkillRegistry` 与 `AgentContext.skills` 并集渲染，每行 `- {name}: {one_line}`；空时渲染 `(none)`

七段均须参与每次 Executor system 构造，不得按条件省略，以保证 prompt 结构稳定。
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

---

### Requirement: `<todo>` 与 `<available_skills>` 段必须在空值时渲染占位符

#### Scenario: 无 skill / 无 todo 时渲染占位

- **WHEN** SkillRegistry 与 AgentContext.skills 均为空
- **THEN** `<available_skills>` 渲染 `(none)`，不得省略该段
- **WHEN** 当前 NPC 没有 open todo
- **THEN** `<todo>` 渲染 `(none)`，不得省略该段

#### Scenario: `<available_skills>` 渐进披露第一层

- **WHEN** 模型查看 `<available_skills>`
- **THEN** 每个 skill 只暴露 `name` 与 `one_line`
- **AND** 不得暴露 `prompt` 全文、`extra_tools` 列表等细节

---

### Requirement: SkillRegistry 实例必须可被 `use_skill` 工具访问

Agent 的装配过程必须保证 `use_skill` 工具在执行时可以取到 SkillRegistry 实例来查 skill 元数据并完成激活。推荐通过 `AgentContext.extra` 的约定键（如 `_skill_agent`）传递，避免在 NPCAgent 或 Executor 的 `self` 上藏状态。

#### Scenario: use_skill 取不到 registry 时的兜底

- **WHEN** `use_skill` 被调用
- **AND** 无可用 SkillRegistry
- **THEN** 返回结构化错误字符串，不得抛 uncaught 异常

---

### Requirement: 一次 run 内，向 LLM 展示过的记忆记录不重复出现

NPCAgent 在一次 `run()` 内维护一个"已向 LLM 展示的记忆 id 集合"，作用域限定本次 run：

- `MemoryAgent.build_context` 计算 `<working_memory>` 时把返回记录的 id 灌入集合
- `MemoryRecallTool` / `MemoryGrepTool` 的返回值在渲染前过滤掉已在集合中的 id；新 id 加入集合

此去重只在本 run 生效，跨 run 的重复召回不受影响（以保留"多次出现强化记忆"的效果）。

集合通过 `context.extra["_recall_seen_ids"]` 在 run 入口初始化为空 set，并在 run 结束时丢弃。

#### Scenario: working_memory 与工具调用不重复同一记录

- **WHEN** run 开始时 `build_context` 已把记录 A 纳入 `<working_memory>`
- **AND** 本 run 内 LLM 调用 `memory_recall` 返回的结果中包含记录 A
- **THEN** 工具返回给 LLM 的 records 列表中不含 A
- **AND** records 列表中的其他记录正常返回

#### Scenario: 去重不跨 run

- **WHEN** run1 已向 LLM 展示记录 A；run2 启动
- **THEN** run2 的 `<working_memory>` 或工具响应中可以再次出现 A

---

### Requirement: Executor 侧压缩参数必须可配置以支持小窗口模型部署

以下参数必须支持通过构造器（或等价机制）注入，不得以"只能改源码"的形式硬编码。默认值以 128k 窗口为参照；小窗口部署（如 Haiku、本地开源模型）下由调用方覆盖：

- `ContextBudget.model_ctx_limit`（默认 128_000）
- `Executor.MAX_TOOL_LOOPS`（默认 8）
- `ToolAgent.micro` 的截断阈值（默认 2000 字符）
- `DefaultWorldEngine.build_context` 渲染的 history 轮数（默认 20）

此约束的目的是让同一套代码能同时服务研究阶段的大模型调试和未来经济型部署的小模型运行，不通过分叉代码实现。

#### Scenario: ContextBudget 接受注入的窗口上限

- **WHEN** 以 `ContextBudget(model_ctx_limit=8000, reserve_output=512)` 构造
- **THEN** `check` 基于注入的 8k 上限判断是否触发 emergency fold

---

## REMOVED Requirements

### Requirement: ContextCompressor 五档压缩（已移除）

**Reason**: 五档压缩器（snip/microcompact/collapse/autocompact/reactive）从未被 NPCAgent 主流程引用，属实现未接入的遗留。其职责已被 `ContextBudget`（Executor 内部 emergency fold）与 `Compressor`（WorldEngine 侧对话折叠）分别承担。

**Migration**: 无——无外部调用方。删除 `src/annie/npc/context_manager.py` 即可。

### Requirement: ImmediateMemory 即时工作记忆层（已移除）

**Reason**: 设计时预留的"类 Claude Code MEMORY.md 指针层"从未被接入 Executor 或任何 prompt 渲染路径。当前 `<working_memory>` 由 `MemoryAgent.build_context` 直接从 MemoryInterface 拉取，不经过 ImmediateMemory。

**Migration**: 无——无外部调用方。删除 `src/annie/npc/memory/immediate_memory.py` 即可。

