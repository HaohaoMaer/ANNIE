# Proposal: Skill 解冻 + 跨回合 Todo

## Why

Change 1 把 NPC 侧的记忆双索引与 prompt 结构打磨干净后，NPC 能力补齐只剩两块：

1. **Skill 仍是冻结态**。`SkillAgent.try_activate` 固定返回 None + DeprecationWarning，`<available_skills>` 渲染硬编码 `(none this run)`。Skill 的使命是承载"带流程指导的 prompt 模板 + 受限工具子集"，比单个 Tool 复杂、比独立 Agent 轻量——当前缺位会把一切复杂行为塞进 Tool，把 Tool 胖成四不像。
2. **NPC 没有跨回合目标载体**。一次 `run()` 产生的"我待会儿要去厨房拿证据"的意图在流程结束时蒸发；下一次 `run()` 里 Planner / Executor 完全看不见这个目标。长程推理 / 连续行动全靠世界引擎侧事件循环触发，NPC 自己无法"记着一件事"。

本 change 同时做这两件事，因为它们在 prompt 结构与工具注册路径上强耦合：

- Skill 解冻后 `<available_skills>` 需要接入 SkillRegistry；`plan_todo` 引入的 `<todo>` 段和 skill 的 `<available_skills>` 段并列，适合一次性定稿 Executor system 模板的"可见能力区"。
- 两者都走 "built-in tool 入口 + 具体内容由 prompt 段落动态渲染" 模式，实现代价可分摊。

## What Changes

### 1. Skill 统一派发：`SkillTool(name, args)`（tool-skill-system 修订）

一个 built-in 工具 `use_skill` 作为**所有 skill 的唯一调用入口**，避免每个 skill 各自注册成独立 tool 污染 tool schema。

```python
use_skill(skill_name: str, args: dict) -> str
```

调用时由 `SkillRegistry` 查名，加载 skill manifest 并在**当前 Executor tool loop 内同进程展开**（不 fork 子 agent）。展开动作：

- 把 `skill.prompt` 作为 `SystemMessage` 追加到当前 messages
- 把 `skill.extra_tools` 临时加入 tool_registry，仅在后续 loop 迭代中对模型可见
- tool 返回 `"skill '{name}' activated; continuing with additional context"`，推动模型下一轮带着新 prompt + 工具继续

Skill 的退出条件为自然退出：当模型下一轮不再 tool_call 即 Executor loop 自然结束。不设显式 `exit_skill`。

### 2. Skill manifest：YAML + prompt.md + extra_tools

磁盘布局：

```
skills/
  <skill_name>/
    skill.yaml     # name, one_line, triggers, extra_tools (list of tool ids)
    prompt.md      # 展开时追加的 SystemMessage 内容
```

`SkillRegistry` 启动时扫描 `skills/` 根，加载所有 `skill.yaml`。`extra_tools` 中引用的 tool id 必须在 `ToolRegistry` 或 `AgentContext.tools` 中已注册；注册缺失时加载期报错。

### 3. `<available_skills>` 接 SkillRegistry（npc-agent 修订）

Executor system 的 `<available_skills>` 段改为从 `SkillRegistry` 渲染：每个 skill 一行 `- {name}: {one_line}`。这是渐进披露第一层：模型只看到 name + 一句话，无 prompt 全文、无工具清单。未激活时不占用 context。

### 4. `plan_todo` built-in tool（tool-skill-system 修订）

```python
plan_todo(
    action: Literal["add", "complete", "list"],
    content: str | None = None,
    todo_id: str | None = None,
) -> dict
```

数据落地方案：作为 `category="todo"` 的长期记忆（不新增 TodoStore）。

- `add(content)` → `memory.remember(content, category="todo", metadata={"status": "open", "todo_id": uuid4()})`
- `complete(todo_id)` → 新增一条"completed"记忆，content 为 `"DONE: {原 content}"`，metadata 带 `closes={todo_id}`
- `list()` → `memory.grep(pattern="", category="todo")` 过滤 `status=="open"` 且未被 `closes` 关闭的项

### 5. `<todo>` 段接入（npc-agent 修订）

Executor system 在 `<working_memory>` 之后渲染 `<todo>` 段。内容由 `TodoRenderer` helper 生成：

- `memory.grep(pattern="", category="todo", metadata_filters={"status": "open"})` 拉出 open todos
- 过滤掉已被 complete 事件关闭的项
- 渲染为 `- [{id_short}] {content}`；空时渲染 `(none)`

此 helper 运行在 `Agent.run()` 入口（与 `working_memory` 同阶段预计算），渲染结果写入 `state["todo_list_text"]`，Executor 直接读。

### 6. Skill 冻结状态解除（tool-skill-system 修订）

- `SkillAgent.try_activate` 的 DeprecationWarning 去除。
- 保留 `SkillAgent.try_activate` 作为占位接口（关键词自动激活不恢复，仍返回 None），实际激活通过 `use_skill` tool 走。`SkillAgent` 余下职责：暴露 `SkillRegistry` 给 `use_skill` tool 访问。

## Impact

### 受影响模块

- `src/annie/npc/skills/base_skill.py` — `SkillDef` 扩展 `one_line / prompt / extra_tools` 字段
- `src/annie/npc/skills/registry.py`（新建）— `SkillRegistry` 扫描 `skills/` 加载 YAML + prompt.md
- `src/annie/npc/sub_agents/skill_agent.py` — 去 DeprecationWarning；新增 `activate(name, args, messages, tool_registry)` 供 `use_skill` 调用
- `src/annie/npc/tools/builtin.py` — 新增 `UseSkillTool`、`PlanTodoTool`
- `src/annie/npc/tools/tool_registry.py` — 支持临时工具注册/反注册（`activate(skill) → unregister on executor return`）
- `src/annie/npc/executor.py` — `<available_skills>` / `<todo>` 段动态渲染；tool loop 允许临时工具增量可见
- `src/annie/npc/agent.py` — 入口计算 `todo_list_text` 写入 state；构造 SkillRegistry 传入 Executor
- `src/annie/npc/state.py` — 新增 `todo_list_text: str`、`active_skills: list[str]`（调试用）

### 新增目录

- 仓库根 `skills/<name>/skill.yaml` + `prompt.md`（首批可只放 1-2 个样例 skill 验证机制）

### 破坏性变更

- `SkillDef` 字段扩展：老的只有 `name / description / prompt_template / allowed_tools`，需迁移为 `name / one_line / prompt / extra_tools`。由于上一 change 已把 Skill 冻结，事实上无老调用方，零业务影响。
- `SkillAgent` 构造签名可能变化（接受 `SkillRegistry`）。

### 不受影响

- MemoryInterface / grep 接口（change 1 已定）
- Executor tool-use 主循环骨架
- AgentContext / AgentResponse 公共字段（extra 依旧是非规约通道）

## Non-Goals

- Skill fork 子 Agent 执行（约定 in-loop，后续如需 isolation 再独立 change）
- Skill 的 `triggers` 字段自动激活（当前仅作 manifest 元数据，供人类和未来 UI 索引；不做关键词匹配）
- Todo 的优先级 / 截止时间 / 依赖关系（首版只有 open/closed 两态）
- 跨 NPC 共享 skill 注册表分域（当前一个 SkillRegistry 扫整个 `skills/` 目录，后续需要按 NPC 白名单再说）
- 多 NPC / 事件总线（属 change 3）
