# Tasks: Skill 解冻 + 跨回合 Todo

依赖：change 1 (`npc-memory-and-prompt-overhaul`) 已 apply。

---

## 阶段 0：准备

- [ ] 0.1 从 change 1 的分支基础上新建 `refactor/skills-and-todo`
- [ ] 0.2 在仓库根 `skills/` 下准备一个样例 skill（如 `skills/deduction/`）用于冒烟

## 阶段 1：SkillDef / SkillRegistry

- [ ] 1.1 `src/annie/npc/skills/base_skill.py`：`SkillDef` 字段重定义为 `name / one_line / prompt / extra_tools / triggers`
- [ ] 1.2 新建 `src/annie/npc/skills/registry.py`：`SkillRegistry.load_dir(path)` 扫描 YAML + 读取 prompt.md
- [ ] 1.3 样例 skill `skills/deduction/skill.yaml` + `prompt.md` 落地
- [ ] 1.4 单元测试：空目录、缺 prompt.md、缺 yaml、extra_tools 引用未注册 tool 时的错误

## 阶段 2：ToolRegistry 帧栈

- [ ] 2.1 `src/annie/npc/tools/tool_registry.py`：新增 `push_frame(tools)` / `pop_frame()`
- [ ] 2.2 `list_tools()` / `get()` 合并 base + 所有 frames
- [ ] 2.3 单元测试：push/pop 正常、多层叠加、pop 空栈兜底

## 阶段 3：use_skill built-in tool + SkillAgent.activate

- [ ] 3.1 `src/annie/npc/sub_agents/skill_agent.py`：
  - 去 DeprecationWarning
  - 新增 `activate(skill_name, args, messages, tool_registry) -> str`
- [ ] 3.2 `src/annie/npc/tools/builtin.py`：`UseSkillTool`，调用 `ctx.agent_context.extra["_skill_agent"].activate(...)`
- [ ] 3.3 `NPCAgent.run()`：把 SkillAgent 实例放进 `context.extra["_skill_agent"]`（与 inner_monologue 的传递模式一致）
- [ ] 3.4 Executor loop：tool 调用后若是 `use_skill`，在 `finally` 阶段调用 `tool_registry.pop_frame()`（以 activate 返回的 frame_id 识别）
- [ ] 3.5 集成测试：StubLLM 先 use_skill → 再 tool_call extra_tools 之一 → 最后 final answer

## 阶段 4：plan_todo built-in tool

- [ ] 4.1 `src/annie/npc/tools/builtin.py`：`PlanTodoTool` + `PlanTodoInput`
- [ ] 4.2 `default_builtin_tools()` 加入
- [ ] 4.3 memory_grep 的空 pattern 行为验证 / 修正（与 change 1 任务 1.4 的"空 pattern 返回 []"相反，这里要求空 pattern 只按 filter 过滤）
- [ ] 4.4 单元测试：add → list 含该项；complete → list 不再含；双 complete 幂等

## 阶段 5：Prompt 段落接入

- [ ] 5.1 `src/annie/npc/prompts.py`：新增 `render_skills_text(skills)` / `render_todo_text(memory)`
- [ ] 5.2 `src/annie/npc/executor.py`：
  - `<available_skills>` 改读 `AgentContext.skills ∪ registry`
  - `<todo>` 改读 `state["todo_list_text"]`
- [ ] 5.3 `src/annie/npc/agent.py`：入口预计算 `todo_list_text = render_todo_text(context.memory)` 写入 state
- [ ] 5.4 `src/annie/npc/state.py`：新增 `todo_list_text: str`、`active_skills: list[str]`

## 阶段 6：集成测试

- [ ] 6.1 `tests/test_npc/test_skill_registry.py`
- [ ] 6.2 `tests/test_npc/test_tool_registry_frames.py`
- [ ] 6.3 `tests/test_npc/test_plan_todo.py`
- [ ] 6.4 扩展 `tests/test_integration/test_decoupled_flow.py`：
  - 断言 `<available_skills>` 列出 manifest 中的 skill
  - 断言 `<todo>` 在添加 todo 后反映 open 项
  - use_skill 路径：system 含追加 SystemMessage + extra_tools 可被调用 + loop 结束后 pop
- [ ] 6.5 新增 `tests/test_integration/test_cross_run_todo.py`：
  - run1 调用 `plan_todo(add, "去厨房找匕首")`
  - run2 启动后 `<todo>` 反映该条
  - run2 调用 `plan_todo(complete, todo_id)`
  - run3 `<todo>` 回到 (none)

## 阶段 7：文档与收尾

- [ ] 7.1 更新 `CLAUDE.md`：
  - Skill 解冻状态
  - `skills/<name>/` 目录约定
  - plan_todo 的 category="todo" 存储
  - `<todo>` / `<available_skills>` 段落接入
- [ ] 7.2 `pyright` / `ruff check` 干净
- [ ] 7.3 归档：`npx openspec archive`

---

## 验收标准

1. `SkillRegistry` 能从 `skills/` 目录加载至少一个样例 skill
2. `use_skill(name, args)` 调用后，当前 Executor loop 的后续 iteration 可看到 `extra_tools` 中声明的工具
3. loop 结束时 `extra_tools` 不再可见（pop_frame 生效）
4. `plan_todo(add)` 的内容跨 run 可见于 `<todo>` 段
5. `plan_todo(complete)` 后 `<todo>` 不再显示该项
6. Executor system 的 `<available_skills>` 渲染 registry + AgentContext.skills 的并集
7. pyright / ruff 干净，集成测试通过

## 不在验收中

- Skill fork 子 Agent 执行
- triggers 字段的自动激活
- Todo 优先级 / 截止日期
- 业务 tool hook（属 change 3）
