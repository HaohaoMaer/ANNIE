# Design: NPC Agent / World Engine Two-Layer Architecture

本文档记录本次重构的架构决策与权衡。具体接口字段、类型签名、实现细节保留给 plan mode 在施工时定案——本文档只钉语义契约与职责边界。

## 总体架构

```
┌─────────────────────────────────────────────────────────────────┐
│                         NPC Agent 层                             │
│                                                                 │
│  • 通用 AI 能力框架，无业务假设，无持久状态                         │
│  • LangGraph 流程：Planner → Executor → Reflector                │
│    (Planner 可由 LLM 判断跳过，直接进入 Executor)                 │
│  • 内置基础 Tools：memory_recall, memory_store, inner_monologue  │
│  • 通过 AgentContext 接收一切外部输入                             │
│  • 通过 AgentResponse 返回思考、对话、行动意图                    │
└─────────────────────────────────────────────────────────────────┘
                 ▲                              │
                 │ AgentContext                 │ AgentResponse
                 │ (in)                         │ (out)
                 │                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                        世界引擎层                                 │
│                                                                 │
│  • 持有世界状态、NPC 记忆存储、工具实现、技能定义                   │
│  • 实现 MemoryInterface（通过 AgentContext 注入）                │
│  • 注册业务 Tool / Skill（通过 AgentContext 注入）               │
│  • 决定"接下来发生什么"（场景推进）                                │
│  • 裁决 NPC 的行动意图（是否允许、如何影响世界）                    │
│  • 可有多种实现：剧本杀 / AI 主持人 / 沙盒 ...                     │
└─────────────────────────────────────────────────────────────────┘
```

## 核心架构决策

### D1: NPC Agent 层无持久状态

**决策**：NPC Agent 不再持有 NPC profile、ChromaDB 客户端、SocialGraph 等长期对象；每次 `run()` 从 AgentContext 获取全部输入，运行结束后对象本身可丢弃。

**理由**：
- 通用性：同一个 NPCAgent 类可服务任意数量的 NPC，无需为每个 NPC 建一个 Agent 实例
- 可测试性：无状态对象易于 mock
- 世界引擎自由度：世界引擎完全掌控状态的生命周期与持久化策略

**权衡**：略微增加世界引擎的样板代码（每次 run 要重建 context）。可接受，因为这正是"世界引擎负责业务复杂度"的体现。

### D2: 认知架构完全外置

**决策**：NPC Agent 层不内置任何认知数据结构（情绪状态、信念集合、动机引擎）。认知维度由世界引擎构造为自然语言 prompt，通过 AgentContext 的 `character_prompt` 字段注入。

**理由**：
- 不同世界引擎对认知的理解不同（剧本杀需要戏剧弧线感，沙盒需要物理合理性），强行统一数据结构会迫使其中一方妥协
- LLM 已经具备从自然语言描述中推理认知状态的能力，额外的结构化层是多余的
- 静态数值（trust=0.5）与真实人类认知不符

**权衡**：失去了对认知状态的程序化查询能力（如"筛选所有对张三信任度 > 0.7 的 NPC"）。接受——这种查询本来就可疑，现实中没有人能被量化成这样。

### D3: AgentContext 采用"核心强类型 + prompt 文本注入 + 开放扩展"的分层

**决策**：AgentContext 包含三类字段——

- **核心机械依赖（强类型）**：NPC Agent 的代码需要直接访问的对象，如身份标识、输入事件、Tool 列表、MemoryInterface 实例
- **prompt 文本层（字符串）**：角色设定、世界规则、当前场景描述等由世界引擎构造好的字符串，NPC Agent 不解析，直接拼入 system prompt
- **开放扩展（dict）**：供世界引擎注入自定义元数据，NPC Agent 不消费但可透传给 Tool 实现

**理由**：
- 核心字段强类型保证 Agent 代码不用写防御性 `.get()` 判断
- Prompt 走文本保留了世界引擎的全部自由度，避免了"所有世界引擎的认知模型被 NPC Agent 层的类型定义绑架"
- 开放扩展兜底，不会因为一个新引擎的特殊需求被迫修改 Agent 层

**否决的方案**：
- 全 dict 的松散协议：失去类型安全，Agent 代码满是防御判断
- 全强类型：无法承载认知自由度，每次世界引擎想加字段都要改 Agent 层

### D4: AgentResponse 采用意图声明式

**决策**：NPC Agent 返回的 `ActionRequest` 是**意图声明**，由世界引擎裁决是否允许以及如何执行。

**理由**：
- 世界引擎是业务权威，只有它能判断一个行动（比如"打开保险柜"）是否合法、是否触发其他效应
- NPC Agent 不应内置"世界状态"的知识，它只能表达"我想做什么"
- 允许世界引擎拦截、修改、拒绝行动，保持对世界的完全控制权

**与 Tool 调用的区别**：
- **Tool 调用**：信息查询、记忆读写——在 Executor 循环内即时执行，结果喂回 LLM
- **Action**：影响世界状态的行为——在 AgentResponse 中作为意图返回，由世界引擎裁决

### D5: MemoryInterface 统一三类记忆

**决策**：MemoryInterface 只提供一组通用方法（`recall` / `remember` / `build_context`），用 `type` 参数区分语义记忆、反思、关系记忆等。即时记忆不走 MemoryInterface，通过 AgentContext 的 situation / history 字段直接注入。

**理由**：
- 即时记忆本质是"当前上下文"，是世界引擎在每次调用前已知的信息，无须 Agent 主动查询
- 统一 API 降低 NPC Agent 层复杂度；底层存储可用 metadata 过滤，或完全分开实现，Agent 层不关心
- 关系认知从关系记忆片段由 LLM 实时综合，不需要独立的关系存储 schema

**否决的方案**：
- 为关系记忆单独暴露 `recall_person(name)` 方法：表面便利，实际只是 `recall(query=name, type="relationship")` 的糖。增加接口表面积不划算

### D6: Tool / Skill 在 NPC Agent 层和世界引擎层两处定义

**决策**：
- NPC Agent 层内置基础 tools（对 MemoryInterface 的 LLM 可见包装 + 元认知工具）
- 世界引擎层定义业务 tools 与 skills，通过 AgentContext 注入
- Agent 内部的 ToolRegistry 合并两个来源，对 LLM 统一呈现

**理由**：
- Agent 层的基础工具对所有世界引擎都有用，每个引擎重复注册浪费
- 业务工具的实现必须在世界引擎层（它们需要访问世界状态），放在 Agent 层反而需要反向依赖

**Skill 的运作模式**（借鉴 Claude Code）：
- Skill 不是独立执行单元，而是**带流程的 prompt 模板 + 允许调用的 tool 子集**
- Executor 在构建 prompt 时，若发现当前任务匹配某个 skill，则将 skill 的 prompt_template 注入到指令中
- LLM 按 skill 的流程指导调用 tool 完成任务

## 数据流

### 一次 NPC 运行的完整流程

```
世界引擎                          NPC Agent                MemoryInterface
    │                                 │                          │
    │ 1. 构造 AgentContext             │                          │
    │    (identity/tools/memory/       │                          │
    │     character_prompt/...)        │                          │
    │                                 │                          │
    ├──── run(AgentContext) ─────────▶│                          │
    │                                 │                          │
    │                                 │ 2. Planner 判断           │
    │                                 │   (可能 skip)             │
    │                                 │                          │
    │                                 │ 3. Executor 循环          │
    │                                 │   • LLM tool_call        │
    │                                 │   • memory_recall ──────▶│
    │                                 │◀────── 结果 ─────────────│
    │                                 │   • inspect_item ───┐    │
    │                                 │   (业务 tool 回调 WE)│    │
    │◀──────────── 回调 ──────────────┤                     │    │
    │                                 │◀──── 结果 ──────────┘    │
    │                                 │                          │
    │                                 │ 4. Reflector              │
    │                                 │   • memory_store ───────▶│
    │                                 │                          │
    │◀─── AgentResponse ──────────────┤                          │
    │   (dialogue/thoughts/           │                          │
    │    actions/reflection)          │                          │
    │                                 │                          │
    │ 5. 裁决 actions                  │                          │
    │ 6. 更新世界状态                   │                          │
    │ 7. 决定下一步                     │                          │
```

## 重构执行策略

采用"外科手术式重构"——**先删、后建、再修、最后接通**。拒绝新旧并存的中间状态。

详见 tasks.md。关键原则：

1. **删除阶段一次性完成**：不保留任何旧抽象作为兼容层
2. **新接口独立定义**：context / response / memory interface 不依赖任何旧代码
3. **现有文件按编译错误引导修改**：让 linter / mypy 指出耦合点
4. **基础设施保留**：LLM wrapper、ChromaDB 封装、tracing、LangGraph 流程机制完整保留
5. **最后才接通**：最小 end-to-end 跑通留到最后作为验收

## 风险与已知问题

- **风险 R1**：NPC YAML 现有的 cognitive_* 和 relationships 数值字段无人消费。
  **应对**：世界引擎具体实现时，由各自解析并转为 character_prompt 字符串。本次不触及。
- **风险 R2**：Skill 注入 prompt 的匹配逻辑可能复杂。
  **应对**：首版可用简单的 skill.name 与 task.description 关键字匹配，后续优化。
- **风险 R3**：删除 social_graph 后，旧 demo 立刻失效。
  **应对**：接受。本次不保证 demo 运行，在后续 change "implement-script-engine" 中恢复。

## 不在本文档中的内容

以下内容留给 plan mode 在施工时决定：

- 各接口的具体 Pydantic 字段名、类型、默认值
- MemoryInterface 的具体方法签名（同步/异步、返回类型）
- Tool / Skill 的 Python 类形态（Protocol / ABC / dataclass）
- 具体的错误处理策略
- 各模块的日志级别与追踪点

这些细节应由具体实现任务时的 plan 文档覆盖。本文档只保证方向与边界。
