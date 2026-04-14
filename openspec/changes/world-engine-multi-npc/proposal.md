# Proposal: 多 NPC 并发 + 事件总线 + 业务工具注入

## Why

前两个 change 把 NPC 层的能力补齐（记忆双索引 + Prompt 体检 + Skill 解冻 + Todo）。世界引擎侧仍停在单 NPC 闭环：

1. **`DefaultWorldEngine` 没有多 NPC 并发编排**。单次 `run_turn(npc_id, event)` 由调用方串行驱动，无共享事件时间线、无"场景 tick"概念、无 NPC-间消息路由。任何涉及两个以上 NPC 互动的场景（剧本杀对质、两 NPC 对话）都要在外部脚本里手写循环。
2. **业务工具无注入机制**。前两个 change 约定 "世界引擎通过 `AgentContext.tools` 注入业务工具"，但 `DefaultWorldEngine.build_context` 没有任何注入路径。具体 engine（将来的 MurderMysteryEngine）要开发时会被迫重写 `build_context` 全体，非加法式。
3. **Skill 的 `extra_tools` 依赖世界侧注入未落地**。change 2 的 skill 可以声明 `evidence_cross_check` 之类的业务工具，但没有地方让世界引擎把这些工具暴露出来；相当于 skill 能力只能跑纯 built-in。

本 change 的目标是把 **`WorldEngine` 基类升级为支持多 NPC + 事件总线 + 业务工具注入的稳定底座**，为后续具体 engine（剧本杀 / AI-GM / 沙盒）提供加法式扩展点。不落地任何具体 engine 实现。

## What Changes

### 1. `WorldEngine.tools_for(npc_id)` 注入 hook（world-engine 修订）

基类新增可选方法：

```python
def tools_for(self, npc_id: str) -> list[ToolDef]:
    return []
```

`DefaultWorldEngine.build_context` 把 `self.tools_for(npc_id)` 的返回合并进 `AgentContext.tools`。具体 engine 通过覆写此方法注入业务工具，不需重写 `build_context`。

### 2. 业务工具抽象模板（tool-skill-system 修订）

在 `src/annie/world_engine/builtin_action_tools.py` 提供四个常见业务动作的**抽象基类模板**，具体 engine 继承填写实现细节：

- `ObserveTool(ABC)` — 感知当前场景 / 附近他人 / 可见物体
- `SpeakToTool(ABC)` — 定向对话（被事件总线路由到目标 NPC）
- `MoveToTool(ABC)` — 位置变更
- `InteractTool(ABC)` — 与场景物体交互

这些是**模板类**而非落地实现；`DefaultWorldEngine` 不实例化它们（不假设世界有位置 / 对象系统）。目的是让具体 engine 作者知道"这四个动词应该长什么样"，形成风格统一。

### 3. 事件总线（world-engine 修订）

新增 `src/annie/world_engine/event_bus.py`：

```python
@dataclass
class WorldEvent:
    kind: str                       # "speak" / "move" / "observe_broadcast" / ...
    source: str                     # npc_id / "world" / "gm"
    targets: list[str]              # 定向接收者；["*"] 表广播
    payload: dict                   # kind 相关字段
    metadata: dict                  # scene / timestamp / ...

class EventBus:
    def publish(event: WorldEvent): ...
    def drain_for(npc_id: str) -> list[WorldEvent]: ...
    def history(limit=50) -> list[WorldEvent]: ...
```

EventBus 只负责路由与临时缓冲，不负责持久化。持久化（HistoryStore）由 `DefaultWorldEngine.handle_response` 在消费 event 时承担。

### 4. 多 NPC 编排：`step()` 与 `run_tick()`

`WorldEngine` 基类的 `step()` 从"可选"升格为"有默认实现"。

```python
def step(self) -> list[tuple[str, AgentResponse]]:
    """
    Default: run_tick() 的默认实现 = 按固定顺序为每个注册 NPC
    调用 npc_agent.run()，收集 AgentResponse 并通过 handle_response 路由。
    具体 engine 可覆盖以实现优先级、触发条件、并发策略。
    """
```

- `NPCRegistry`：`register(npc_id, profile)` / `list_active()` / `remove(npc_id)`。
- 每个 tick：`for npc_id in active:` pull inbound events → 构造 AgentContext → `npc_agent.run()` → `handle_response()` 产出事件发布回 EventBus → 其他 NPC 下一 tick 可感知。
- **并发策略**：首版串行（按注册顺序），避免并发带来的测试不确定性。具体 engine 可覆盖 `step()` 做并发。

### 5. `build_context` 吸收 inbound events（world-engine 修订）

`DefaultWorldEngine.build_context(npc_id, event=None)` 行为扩展：

- 若显式传入 `event`（向后兼容路径），按原逻辑作为 `input_event`。
- 若 `event is None` 且 EventBus 中有该 NPC 的待处理事件：拼装 `input_event = 首个事件的 payload 叙述` + `situation` 补上其余事件背景；其余事件 mark as consumed。
- 若两者皆无，作 idle tick 处理：`input_event = "(idle moment)"` 或跳过该 NPC。

### 6. AgentContext 扩展：`nearby_npcs: list[str]`（agent-interface 修订）

`AgentContext.extra` 之外，新增一个强类型字段（可选 list）`nearby_npcs`，让 NPC 能感知"当前场景里还有谁"。`Observe` / `SpeakTo` 等业务 tool 会读它。世界引擎 `build_context` 时填充。

## Impact

### 受影响模块

- `src/annie/world_engine/base.py` — `tools_for(npc_id)` 新方法；`step()` 默认实现；`NPCRegistry` 协议
- `src/annie/world_engine/default_engine.py` — `build_context` 吸收 events；`tools_for` 默认返回空；`step()` 默认实现
- `src/annie/world_engine/event_bus.py`（新建）
- `src/annie/world_engine/builtin_action_tools.py`（新建，抽象模板）
- `src/annie/npc/context.py` — `AgentContext.nearby_npcs: list[str]` 字段

### 新增模块

- `src/annie/world_engine/event_bus.py`
- `src/annie/world_engine/builtin_action_tools.py`
- `src/annie/world_engine/npc_registry.py`

### 破坏性变更

- `WorldEngine.build_context` 签名保持兼容（`event` 仍为位置参数），但语义上"event 是主入口"向"event 与 EventBus 二选一"迁移。现有调用 `engine.build_context(npc_id, event)` 不受影响。
- `AgentContext.nearby_npcs` 新字段默认值 `[]`。老构造不受影响。

### 不受影响

- NPC Agent 层所有代码
- MemoryInterface / MemoryRecord
- Compressor / HistoryStore
- 所有 built-in tools / skills 定义

## Non-Goals

- **具体 engine 实装**（MurderMysteryEngine / SandboxEngine 等）——留待独立 change，用本 change 的底座组装。
- **perception / 可见性过滤层**——`nearby_npcs` 是粗粒度占位；真正的 FoV / 听力距离 / 视线阻挡留给具体 engine 或后续 change。
- **事件总线持久化**——EventBus 只是内存路由器；跨进程 / 跨 session 的事件持久化不在范围。
- **NPC 间并发执行**——首版串行 tick，避免 ChromaDB 写锁争用与测试不确定性。
- **Midnight Train demo 复活**——本 change 只打底座；复活 demo 需要具体 engine 支撑。
- **角色调度优先级 / 反应性触发**——首版按注册顺序 tick；触发器式调度留给具体 engine。
