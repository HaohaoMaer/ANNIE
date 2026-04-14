# Tasks: 多 NPC 并发 + 事件总线 + 业务工具注入

依赖：change 1 + change 2 均已 apply。

---

## 阶段 0：准备

- [ ] 0.1 基于 change 2 分支新建 `refactor/world-engine-multi-npc`

## 阶段 1：EventBus + WorldEvent

- [ ] 1.1 新建 `src/annie/world_engine/event_bus.py`
  - `WorldEvent` dataclass
  - `EventBus`: `publish` / `drain_for` / `history(limit)` / `clear`
  - 广播（`targets=["*"]`）fan-out 到所有 active NPC（排除 source）
- [ ] 1.2 单元测试：
  - 单目标路由
  - 广播扇出
  - drain 后 inbox 清空
  - history 限长

## 阶段 2：NPCRegistry

- [ ] 2.1 新建 `src/annie/world_engine/npc_registry.py`
  - `register / remove / list_active / profile`
  - 保持注册顺序
- [ ] 2.2 单元测试：注册、去重、顺序、profile lookup

## 阶段 3：WorldEngine 基类升级

- [ ] 3.1 `src/annie/world_engine/base.py`：
  - 新增抽象 / 默认方法 `tools_for(npc_id) -> list[ToolDef]`（默认 `return []`）
  - 默认 `step(npc_agent)` 实现（参照 design.md）
  - 约定 engine 实例持有 `self.npcs: NPCRegistry` 与 `self.event_bus: EventBus`
- [ ] 3.2 `AgentContext`：新增 `nearby_npcs: list[str] = []` 字段
- [ ] 3.3 `AgentContext.model_rebuild()` 处理新字段

## 阶段 4：DefaultWorldEngine 改造

- [ ] 4.1 `src/annie/world_engine/default_engine.py`：
  - `__init__` 实例化 NPCRegistry + EventBus
  - `build_context(npc_id, event=None)`：
    - `event is not None` → 原路径
    - `event is None` → `events = event_bus.drain_for(npc_id)`；首条转 input_event，其余补 situation；全空时返回 None 或 "(idle)"
  - `tools_for` 默认返回 `[]`
  - `handle_response`：除了原有 HistoryStore/memory 写入，把 `resp.actions` 转为 WorldEvent publish（首版只处理 dialogue → `kind="speak"`，targets 来自 resp.actions 或默认广播）
  - 填充 `nearby_npcs`（默认 "同场所有 active NPC 除自身"）
- [ ] 4.2 `_render_event_as_input(event, viewer_id)` helper
- [ ] 4.3 `tools_for` 返回值合并进 `AgentContext.tools`
- [ ] 4.4 集成测试：两个 NPC，A speak → B 下一 tick 接收 → B 回复 → A 下一 tick 接收

## 阶段 5：业务 tool 抽象模板

- [ ] 5.1 新建 `src/annie/world_engine/builtin_action_tools.py`
  - `SpeakToTool` / `ObserveTool` / `MoveToTool` / `InteractTool` 抽象类
  - 每个带 `ToolContext` 正确透传 + source_npc ctor 参数
- [ ] 5.2 样例具体实现用于测试：`tests/test_world_engine/_sample_action_tools.py`
- [ ] 5.3 文档：在 CLAUDE.md 约定 "具体 engine 必须实例化这四个动词（或其子集）"

## 阶段 6：集成测试

- [ ] 6.1 新增 `tests/test_world_engine/test_event_bus.py`
- [ ] 6.2 新增 `tests/test_world_engine/test_npc_registry.py`
- [ ] 6.3 新增 `tests/test_integration/test_multi_npc_tick.py`:
  - 两 NPC 注册
  - A 收到 external `speak` event
  - step() 推进 A → A 说回去 → EventBus 有定向事件
  - step() 推进 B → B 看到消息 → 回复
  - 第三 tick 无人待处理 → step() 返回 []
- [ ] 6.4 新增 `tests/test_integration/test_tools_for_injection.py`:
  - 子类化 DefaultWorldEngine，覆写 `tools_for` 返回一个自定义业务 tool
  - 断言模型在 run 内可以调用该 tool（StubLLM 模拟）
- [ ] 6.5 组合测试：change 2 的 skill + change 3 的 tools_for
  - skill manifest 声明 `extra_tools=["my_biz_tool"]`
  - engine 通过 `tools_for` 注入 `my_biz_tool`
  - `use_skill` 激活后模型能调用该 tool

## 阶段 7：文档与收尾

- [ ] 7.1 更新 `CLAUDE.md` Architecture 章节：
  - `tools_for` hook
  - EventBus / NPCRegistry / step() 语义
  - 业务 tool 抽象模板约定
  - `nearby_npcs` 字段
- [ ] 7.2 更新 `src/annie/world_engine/__init__.py` 导出
- [ ] 7.3 `pyright` / `ruff check` 干净
- [ ] 7.4 归档：`npx openspec archive`

---

## 验收标准

1. `WorldEngine.tools_for(npc_id)` 存在且被 `build_context` 合并进 AgentContext.tools
2. EventBus 支持定向与广播，NPC 能消费 inbox 并在 situation 中看到伴随事件
3. `DefaultWorldEngine.step(npc_agent)` 默认实现：按注册顺序为每个有 inbox 的 NPC 推进一次，无 inbox 跳过
4. 两 NPC 集成测试：至少能完成一次 A → B → A 的三轮传球
5. `AgentContext.nearby_npcs` 在每次 build_context 中被正确填充
6. change 2 的 skill extra_tools 能引用由 `tools_for` 注入的业务 tool 并成功激活
7. pyright / ruff 干净

## 不在验收中

- 具体 engine（MurderMysteryEngine 等）
- perception / 可见性过滤
- 并发 tick 执行
- EventBus 持久化
- 调度优先级 / 触发器
- Midnight Train demo 复活
