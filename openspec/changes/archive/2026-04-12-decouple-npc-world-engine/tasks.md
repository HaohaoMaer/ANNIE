# Tasks: Decouple NPC Agent from World Engine

本文档是重构的施工路线图。按阶段顺序推进，每阶段内部可并行。每个任务完成后勾选。

**原则**：先删、后建、再修、最后接通。不保留任何新旧并存的中间状态。

---

## 阶段 0：准备工作

- [x] 0.1 创建 refactor 分支 `refactor/decouple-npc-world-engine`
- [x] 0.2 备份 / 记录当前 demo 的入口脚本，留作后续恢复参考
- [x] 0.3 在 pyproject.toml 中确认 LangGraph / Pydantic / Chromadb 版本锁定

## 阶段 1：删除旧代码（一次性完成）

### 1.1 删除认知层

- [x] 1.1.1 删除 `src/annie/npc/cognitive/` 整个目录
- [x] 1.1.2 从 `agent.py` 中移除 BeliefSystem / EmotionalStateManager / MotivationEngine / DecisionMaker 的导入与使用

### 1.2 删除社交图层

- [x] 1.2.1 删除 `src/annie/social_graph/` 整个目录
- [x] 1.2.2 从 `agent.py` 中移除 social_graph / event_log 参数及所有相关分支
- [x] 1.2.3 从 `executor.py` 中移除 `_maybe_log_social_event`、`event_log`、`all_npc_names` 依赖
- [x] 1.2.4 从 `reflector.py` 中移除 social_graph 参数与相关逻辑
- [x] 1.2.5 删除 `src/annie/npc/sub_agents/social_agent.py`
- [x] 1.2.6 删除 `src/annie/npc/tools/perception.py`

### 1.3 合并关系记忆

- [x] 1.3.1 删除 `src/annie/npc/memory/relationship.py`
- [x] 1.3.2 从 MemoryAgent 中移除 relationship 专用调用路径
- [x] 1.3.3 从 NPCProfile 中移除 `relationships` 字段（或改为字符串描述字段留给世界引擎解析）

### 1.4 清理世界引擎层

- [x] 1.4.1 删除 `src/annie/world_engine/` 下的所有现有实现文件（保留目录）
- [x] 1.4.2 从各 `__init__.py` 中移除对已删模块的导出

### 1.5 确认断裂状态

- [x] 1.5.1 此时项目应无法 import / 运行——这是预期状态，作为阶段边界

## 阶段 2：定义新接口（新文件，独立于旧代码）

使用 plan mode 细化每个接口的具体字段和方法签名。

- [x] 2.1 创建 `src/annie/npc/context.py`——AgentContext
  - 字段语义见 design.md D3（核心强类型 + prompt 文本 + 开放扩展）
  - plan mode 决定具体 Pydantic 形态
- [x] 2.2 创建 `src/annie/npc/response.py`——AgentResponse
  - 意图声明式（见 design.md D4）
  - 包含 dialogue / inner_thought / actions / memory_updates / reflection
- [x] 2.3 创建 `src/annie/npc/memory/interface.py`——MemoryInterface 协议
  - `recall(query, type, k)` / `remember(content, type, metadata)` / `build_context(query)`
  - type 为开放字符串，由世界引擎注册支持哪些类型
- [x] 2.4 创建 `src/annie/world_engine/base.py`——WorldEngine 抽象基类
  - 规定世界引擎必须实现：提供 MemoryInterface、构造 AgentContext、处理 AgentResponse、推进世界状态
  - 具体方法由 plan 定
- [x] 2.5 更新 `src/annie/npc/tools/base_tool.py`——新 ToolDef 规范
  - 参考 Claude Code 的 buildTool 模式
  - 包含 name / description / input_schema / output_schema / call / is_read_only
- [x] 2.6 更新 `src/annie/npc/skills/base_skill.py`——新 SkillDef 规范
  - 包含 name / description / allowed_tools / prompt_template

## 阶段 3：修残缺（按 import 报错逐个修）

### 3.1 核心 Agent 文件

- [x] 3.1.1 重写 `agent.py` 构造函数：接收 AgentContext 替代 npc_yaml_path / chroma_client
- [x] 3.1.2 重写 `agent.py` 的 `run()` 方法：只接收 event，全部依赖从 context 取
- [x] 3.1.3 `agent.py` 装配 ToolRegistry 时合并 built-in tools 与 context.tools
- [x] 3.1.4 `state.py`：NPCProfile 瘦身，移除 cognitive 字段；AgentState 保留 LangGraph 必需部分
- [x] 3.1.5 `planner.py`：`_build_dynamic_prompt` 改从 context.character_prompt 拼接而非 NPCProfile.personality
- [x] 3.1.6 `executor.py`：ToolRegistry 使用新 ToolDef 接口；SkillRegistry 注入 prompt 模板
- [x] 3.1.7 `reflector.py`：解耦 social_graph，反思结果通过 MemoryInterface 写入

### 3.2 子代理与工具

- [x] 3.2.1 `sub_agents/memory_agent.py`：改为薄包装 MemoryInterface
- [x] 3.2.2 `sub_agents/tool_agent.py`：适配新 ToolDef
- [x] 3.2.3 `sub_agents/skill_agent.py`：适配新 SkillDef，实现 skill 匹配与 prompt 注入逻辑
- [x] 3.2.4 `tools/memory_query.py`、`memory_search.py`：改为调用 MemoryInterface（旧文件删除，由 built-in `memory_recall` / `memory_store` 替代）
- [x] 3.2.5 `tools/tool_registry.py`：支持合并 built-in 与注入的 tools
- [x] 3.2.6 新增 built-in tools：`memory_recall` / `memory_store` / `inner_monologue`（LLM 可见包装）

### 3.3 追踪与配置

- [x] 3.3.1 `tracing.py`：确认追踪点仍然有效（大概率不需要改）
- [x] 3.3.2 `config.py`、`llm.py`：保持不动，确认未受波及

## 阶段 4：默认世界引擎实现

- [x] 4.1 创建 `src/annie/world_engine/memory.py`：默认 MemoryInterface 实现
  - 包装 EpisodicMemory + SemanticMemory（ChromaDB）
  - 提供 type 过滤（用 metadata）
- [x] 4.2 创建 `src/annie/world_engine/default_engine.py`：最小 WorldEngine 实现
  - 用于测试两层接通；不含业务逻辑
  - 负责从 NPC YAML 加载基本信息、构造 character_prompt、装配 AgentContext
- [x] 4.3 提供 built-in tools 的默认实例化辅助函数（`annie.npc.tools.builtin.default_builtin_tools`）

## 阶段 5：最小 end-to-end 验收

- [x] 5.1 编写集成测试：一个 NPC + 默认 WorldEngine + 一次 run
  - 触发事件 → Planner → Executor 调用记忆工具 → Reflector 写反思 → AgentResponse 返回
  - `tests/test_integration/test_decoupled_flow.py`
- [x] 5.2 验证 tracing 输出完整（Tracer 在 run() 中贯穿 Planner/Executor/Reflector 节点）
- [x] 5.3 验证 ChromaDB 中记忆实际写入（集成测试中 `recall` 返回非空）
- [x] 5.4 验证无 social_graph / cognitive 相关导入残留（`grep` 仅余文档注释）
- [x] 5.5 pyright / mypy 无严重报错（新增 / 重写代码 pyright 0 error；遗留 chromadb SDK 自带的类型存根问题不计入）
- [x] 5.6 ruff / lint 通过

## 阶段 6：文档与收尾

- [x] 6.1 更新 README：描述新的两层架构（顶部加入重构提示段；旧架构章节待后续 change 全面重写）
- [ ] 6.2 归档本 change（`openspec archive`）— 留待用户确认后执行

---

## 验收标准

本次 change 完成的标志：

1. 项目中不存在任何 `social_graph` / `cognitive` 相关代码
2. `NPCAgent` 构造不需要 SocialGraph、ChromaDB client、NPC YAML 路径
3. 存在 `AgentContext` / `AgentResponse` / `MemoryInterface` / `WorldEngine` 四个新抽象
4. 默认 `WorldEngine` 可以驱动一个 NPC 完成一次完整 run 循环
5. 5 个 capability spec.md 写完

## 不在验收标准中的

- 旧剧本杀 demo 的运行（由后续 change 恢复）
- AI 主持人 / 沙盒引擎的实现（独立 change）
- Skill 匹配算法的优化（首版关键字匹配即可）
- 性能优化
