# Proposal: Decouple NPC Agent from World Engine

## Why

当前 ANNIE 项目的 NPC Agent 层与具体业务高度耦合：
- NPC Agent 内置硬编码的认知模块（BeliefSystem / EmotionalStateManager / MotivationEngine / DecisionMaker）
- NPC Agent 持有对 SocialGraph、SocialEventLog、PropagationEngine 的直接引用
- NPC 之间的关系以集中式图结构 + 静态数值（trust / familiarity / emotional_valence）存储
- 感知系统（Perception Pipeline）通过复杂的过滤器让每个 NPC 获取"自己的视角"

这一设计存在三类问题：

1. **过度工程化**：PropagationEngine 实现了完整的 BFS 信息传播，但核心路径未使用；KnowledgeFilter / BeliefEvaluator / PerceptionBuilder 三层感知在实际调用中被绕过。
2. **认知建模失真**：用 `trust=0.5` 这样的静态数值描述人际关系不符合真实认知——人通过经历与互动形成对他人的判断，而非维护一个被动更新的数值。
3. **复用性为零**：当前的 NPC Agent 无法脱离"剧本杀"业务独立使用。想接入 AI 主持人模式、沙盒模式等其他玩法时，必须从头重写 Agent。

## What Changes

本次重构建立 **NPC Agent 层**与**世界引擎层**的两层解耦架构：

- **NPC Agent 层**：提供通用 AI 能力框架（Planner / Executor / Reflector），完全无持久状态；通过 `AgentContext` 接收世界引擎注入的一切（身份、工具、记忆接口、认知 prompt、世界规则），通过 `AgentResponse` 返回思考、对话、行动意图。
- **世界引擎层**：持有所有业务状态、NPC 记忆、工具实现、技能定义、认知配置、场景推进逻辑。通过实现 `MemoryInterface` 和提供 Tool / Skill 集合服务于 NPC Agent。

同一 NPC Agent 接口下可以承载多种世界引擎实现（剧本杀引擎、AI 主持人引擎、沙盒引擎等）。

### 核心变更

1. 移除 `src/annie/npc/cognitive/` 整个目录——认知维度改由世界引擎通过 prompt 文本注入，LLM 实时推理。
2. 移除 `src/annie/social_graph/` 整个目录——集中式关系图被每个 NPC 独立维护的 outgoing 关系记忆取代。
3. 移除 `src/annie/npc/memory/relationship.py`——关系记忆合并入语义记忆，通过 `type` 区分。
4. 定义新接口 `AgentContext` / `AgentResponse` / `MemoryInterface` 作为两层之间的唯一契约。
5. 重构 `NPCAgent` 构造签名：不再持有 NPC profile / SocialGraph / ChromaDB 客户端，仅接收 AgentContext 执行一次 run。
6. 定义 `WorldEngine` 抽象基类：规定世界引擎应实现的最小接口（构造 AgentContext、处理 AgentResponse、提供 MemoryInterface）。
7. 提供一个默认的 `WorldEngine` 骨架实现供后续具体引擎继承。

### 认知架构去数值化

- 情感：自然语言描述（如"复杂的情感，既感激又失望"），写入语义记忆
- 关系：不再有独立的关系数据结构；每次互动后由 Reflector 产出观察并存为带人物 tag 的语义记忆；需要"我对 X 的看法"时由 LLM 从相关记忆片段实时综合
- 信念 / 动机：由世界引擎构造 character_prompt 提供，NPC Agent 不做结构化建模

### 记忆分层

- 即时记忆（working memory）→ 通过 AgentContext 传入（非 MemoryInterface）
- 语义记忆 + 关系记忆 → 统一通过 MemoryInterface，用 `type` 字段区分
- MemoryInterface 由世界引擎实现，NPC Agent 通过内置的 memory tool 调用

### Tool / Skill 分层

- 基础 Tools（memory_recall / memory_store 等）→ NPC Agent 层内置
- 业务 Tools（inspect_item / move_to / perceive_scene 等）→ 世界引擎层定义
- Skills → 世界引擎层定义，作为 prompt 模板 + 允许调用的 tool 子集，在 Executor 匹配到相关任务时注入

## Impact

### 受影响的模块

- `src/annie/npc/agent.py`（重构构造与 run 签名）
- `src/annie/npc/state.py`（NPCProfile 瘦身，AgentState 保留 LangGraph 部分）
- `src/annie/npc/planner.py`、`executor.py`、`reflector.py`（解耦旧依赖）
- `src/annie/npc/sub_agents/*`（适配新接口）
- `src/annie/npc/tools/*`（按新 ToolDef 规范）
- `src/annie/npc/skills/*`（按新 SkillDef 规范）

### 删除的模块

- `src/annie/npc/cognitive/` 整个目录
- `src/annie/social_graph/` 整个目录
- `src/annie/npc/memory/relationship.py`
- `src/annie/npc/sub_agents/social_agent.py`
- `src/annie/npc/tools/perception.py`
- `src/annie/world_engine/` 原有实现（目录保留，准备重写）

### 新增的模块

- `src/annie/npc/context.py`（AgentContext）
- `src/annie/npc/response.py`（AgentResponse）
- `src/annie/npc/memory/interface.py`（MemoryInterface 协议）
- `src/annie/world_engine/base.py`（WorldEngine 抽象基类）
- `src/annie/world_engine/memory.py`（默认 MemoryInterface 实现，包装 ChromaDB）

### 保留不动的模块

- `src/annie/npc/llm.py`、`config.py`、`tracing.py`
- `src/annie/npc/memory/episodic.py`、`semantic.py`、`chroma_lock.py`、`immediate_memory.py`（存储层复用）
- `src/annie/npc/tools/base_tool.py`、`memory_query.py`、`memory_search.py`（小改适配）
- `src/annie/npc/skills/base_skill.py`（小改适配）

### 破坏性变更

- 现有调用 `NPCAgent(npc_yaml_path=..., social_graph=..., event_log=...)` 的代码必须改为通过 WorldEngine 构造 AgentContext 后调用。
- 现有 NPC YAML 中的 `cognitive_*`、`relationships` 数值字段不再被 NPC Agent 层消费，需由世界引擎自行解析并转为 character_prompt 文本。

## Non-Goals（本次不做）

- **不实现具体的世界引擎**：本次仅建立抽象基类与默认 MemoryInterface。剧本杀引擎、AI 主持人引擎、沙盒引擎的具体实现在后续独立 change 中完成。
- **不迁移剧本解析与业务数据**：`script_parser`、剧本杀相关的线索管理、剧情推进等业务逻辑不在本次范围内，留给后续世界引擎具体实现时处理。
- **不改动 LLM provider 接入层**：LLM 调用、模型配置、向量数据库的选型保持现状。
- **不重做 Planner / Executor / Reflector 的核心流程**：LangGraph 的 Planner → Executor → Reflector 循环（含失败重试）保持原样，仅解耦其输入来源。
- **不保证旧 demo 的运行**：剧本杀演示将在本次重构期间暂时失效，后续由具体世界引擎实现恢复。
