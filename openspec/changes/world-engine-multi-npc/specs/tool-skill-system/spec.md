# Tool / Skill System Capability Spec — Delta

本次 change 对 tool-skill-system capability 的修订。

## ADDED Requirements

### Requirement: 业务工具必须通过 `WorldEngine.tools_for(npc_id)` 注入 AgentContext.tools

业务工具（对世界状态产生副作用的工具，如 `speak_to` / `move_to` / `interact` / `evidence_cross_check`）必须由世界引擎通过 `tools_for(npc_id)` 返回，由 `build_context` 合并进 `AgentContext.tools`。不得由 NPC 层直接注册、也不得通过 built-in 通道暴露。

#### Scenario: 业务工具路径正确

- **WHEN** 具体 engine 实现一个 `EvidenceCrossCheckTool`
- **THEN** 它必须通过 `tools_for(npc_id)` 返回
- **AND** 不得出现在 `src/annie/npc/tools/builtin.py`

#### Scenario: Skill 的 extra_tools 引用业务工具

- **GIVEN** 某个 Skill 的 `extra_tools` 声明了 `evidence_cross_check`
- **WHEN** 世界引擎通过 `tools_for` 为当前 NPC 注入了 `EvidenceCrossCheckTool`
- **THEN** `use_skill` 激活时该工具能在 Executor tool loop 的后续 iteration 中可见
- **AND** 若世界引擎未注入，SkillRegistry 的加载期或激活期必须报错（见 change 2 spec）

---

### Requirement: 世界引擎应提供四种业务动作的抽象模板供具体 engine 继承

仓库应提供 `ObserveTool / SpeakToTool / MoveToTool / InteractTool` 四个**抽象基类**，作为常见业务动作的参考契约。具体 engine 通过继承并实现 `call` 方法产出落地版本。`DefaultWorldEngine` 不实例化这些模板（不假设世界有位置/物体系统）。

这些抽象类的目的是**风格统一**而非强制使用——具体 engine 可以选择不用任何一个，也可自行设计完全不同的业务动词。

#### Scenario: DefaultWorldEngine 不强加业务动词

- **WHEN** 直接使用未子类化的 DefaultWorldEngine
- **THEN** AgentContext.tools 中不包含 SpeakTo / MoveTo / Observe / Interact 的任何具体实例
- **AND** NPC 仍可通过 built-in tools（memory_*, plan_todo, inner_monologue, use_skill）完成纯思考场景
