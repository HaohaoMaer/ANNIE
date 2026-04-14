# Design: Skill 解冻 + 跨回合 Todo

## Skill 激活的生命周期（in-loop）

```
Executor loop iteration N:
  llm.bind_tools([base_tools, use_skill]).invoke(messages)
  → tool_call: use_skill(skill_name="deduction", args={...})

dispatch use_skill:
  skill = registry.get("deduction")
  messages.append(SystemMessage(content=skill.prompt))         # 加勺子
  tool_registry.push_frame(skill.extra_tools)                   # 临时注册
  return f"skill '{skill.name}' activated"

iteration N+1:
  llm.bind_tools([base_tools, use_skill, *skill.extra_tools]).invoke(messages)
  → 正常 tool_call / final answer

loop exit (no tool_calls):
  tool_registry.pop_frame()                                    # 卸下
```

**关键点**：

- `extra_tools` 的可见性以"帧（frame）"为单位压栈。Executor loop 主循环在每轮 `llm.bind_tools` 前读取**当前帧内所有可见工具**。
- loop 结束时无论成功与否都 pop_frame（try/finally）。防止 skill 工具泄漏到后续 task。
- 多个 skill 可叠栈（模型可在同一 loop 内 `use_skill` 两次），pop 顺序反向。

## Skill manifest 格式

`skills/deduction/skill.yaml`：

```yaml
name: deduction
one_line: "基于已知事实进行推理，列出可能的结论与证据链"
triggers: ["推理", "分析可能"]     # 仅作人类/未来 UI 索引，不参与自动激活
extra_tools:
  - memory_grep                    # 引用已存在的 tool id
  - evidence_cross_check           # 世界引擎层注入的业务 tool
```

`skills/deduction/prompt.md`：

```markdown
You are now in deduction mode. Work through the reasoning as follows:

1. 列出所有已知事实
2. 列出所有未知但可推断的事实
3. 对每个可能结论给出支持证据链
...
```

`SkillDef` Python 模型：

```python
class SkillDef(BaseModel):
    name: str
    one_line: str
    prompt: str                    # loaded from prompt.md
    extra_tools: list[str]          # tool ids to unlock
    triggers: list[str] = []        # metadata only
```

## SkillRegistry 加载时机

- `SkillRegistry.load_dir(path)` 扫描 `<path>/*/skill.yaml`，为每个 skill 读取同目录的 `prompt.md` 作为 `prompt`。
- `NPCAgent.__init__` 接受可选 `skills_dir: Path | None`；传入时懒加载一次，缓存为 `self._skill_registry`。None 时构造空 registry。
- `AgentContext.skills: list[SkillDef]` 仍然存在（已在 agent-interface spec 中），用于世界引擎**注入 per-NPC 可见 skill 白名单**。Executor 在渲染 `<available_skills>` 时取 `AgentContext.skills ∪ global_registry` 的并集（以 name 去重，AgentContext 覆盖）。首版 global_registry 为空也能跑。

## `use_skill` 工具的参数处理

```python
class UseSkillInput(BaseModel):
    skill_name: str
    args: dict = Field(default_factory=dict)
```

`args` 当前版本**不强制 schema**，skill.yaml 也不声明参数结构。`args` 会以 JSON 字符串形式塞进追加的 SystemMessage 末尾 `"User args: {args_json}"`，由 skill.prompt 自行引导如何使用。

**决定理由**：首版保持轻量。如果未来 skill 需要参数结构化，再在 skill.yaml 加 `input_schema` 字段。

## `plan_todo` 的存储约定

选用"category=todo 的记忆"路径后，几个细节锁定：

- `add`：`remember(content, category="todo", metadata={"status": "open", "todo_id": uuid4().hex[:8]})`
- `complete(todo_id)`：写入第二条记忆 `content=f"[DONE] {原 content?}"`，metadata `{"status": "closed", "closes": todo_id, "category": "todo"}` 实际为 open→closed 的事件流而非修改原记录。
- `list()`：`memory.grep(pattern="", category="todo", metadata_filters={"status": "open"})` 得候选 A；`grep(pattern="", category="todo", metadata_filters={"status": "closed"})` 得 closed 集合 B，从 A 中剔除 `todo_id ∈ B.closes`。

**为什么不 update 原记录**：MemoryInterface 协议没有 update 语义，且 ChromaDB 的更新成本 ≈ 删除+重写。追加事件流更简单，且保留"曾经存在过这个 todo"的历史。

**grep 空 pattern 约定**：`pattern=""` 语义为"只按 filter 过滤，不做子串匹配"。在 memory_grep 实现中显式支持空字符串短路。此语义回灌 change 1 的 grep 实现（`pattern == "" → 跳过子串匹配，只返回 filter 命中的前 k 条`）。需在 change 1 tasks 1.4 "空 pattern 返回 []" 的测试用例反向修正——本 change 的 task 会 override 之。

### TodoRenderer

```python
def render_todo_text(memory: MemoryInterface) -> str:
    opens = memory.grep("", category="todo", metadata_filters={"status": "open"}, k=50)
    closeds = memory.grep("", category="todo", metadata_filters={"status": "closed"}, k=50)
    closed_ids = {r.metadata.get("closes") for r in closeds}
    alive = [r for r in opens if r.metadata.get("todo_id") not in closed_ids]
    if not alive:
        return "(none)"
    return "\n".join(f"- [{r.metadata.get('todo_id', '?')}] {r.content}" for r in alive)
```

## Executor system 模板定稿（与 change 1 对齐）

```
<character>...</character>
<world_rules>...</world_rules>
<situation>...</situation>
<memory_categories>
- episodic: 原始经历
- semantic: 客观事实
- reflection: 自我反思与人物印象
- impression: 折叠产生的模糊印象
- todo: 跨回合未完成目标
</memory_categories>
<working_memory>...</working_memory>
<todo>{todo_list_text}</todo>
<available_skills>
- deduction: 基于已知事实进行推理
- interrogation: 审问一个可疑对象
</available_skills>
```

change 1 为 `<todo>` / `<available_skills>` 留了口子（前者在 memory_categories 列名；后者保留占位）。本 change 把内容接上。

## 临时工具注册（`ToolRegistry.push_frame` / `pop_frame`）

ToolRegistry 改造为"帧栈"：

```python
class ToolRegistry:
    def __init__(self, injected):
        self._base: dict[str, ToolDef] = {...}    # built-in + injected
        self._frames: list[dict[str, ToolDef]] = []

    def list_tools(self) -> list[str]:
        merged = dict(self._base)
        for frame in self._frames:
            merged.update(frame)
        return list(merged)

    def get(self, name) -> ToolDef | None: ...

    def push_frame(self, tools: list[ToolDef]): ...
    def pop_frame(self): ...
```

Executor tool loop 在每次 iteration 前重新读取 `list_tools() / get()`，因此新帧工具在下一轮自动可见。

## Skill 与 inner_monologue / memory_* 的关系

Skill.prompt 可以引导模型使用 memory_grep / inner_monologue / plan_todo 等既有 built-in；不需要在 `extra_tools` 重复声明。`extra_tools` 只用来解锁**非 built-in、非 AgentContext.tools 默认可见的额外能力**——典型场景是世界引擎侧为特定 skill 注册的"evidence_cross_check"、"show_card"这类业务工具。

## 和 change 3 的衔接

`extra_tools` 引用的业务 tool id 必须在 `ToolRegistry` 中已注册。在 change 3 `WorldEngine.tools_for(npc_id)` hook 落地前，业务 tool 必须通过 `AgentContext.tools` 手动注入。Skill 本身先跑通"纯 built-in extra_tools"场景足矣。
