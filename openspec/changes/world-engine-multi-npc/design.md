# Design: 多 NPC 并发 + 事件总线 + 业务工具注入

## tools_for 的合并语义

`DefaultWorldEngine.build_context(npc_id, event)`：

```python
ctx_tools = [*(context.tools or []), *self.tools_for(npc_id)]
# 去重：name 冲突时 self.tools_for 后者覆盖调用方 (engine 优先业务工具)
```

然后装配进 `AgentContext.tools`。built-in 冲突规则（change 1 已定：built-in wins）不受影响，因为 built-in 合并发生在 `ToolRegistry` 层，更靠内。

## 事件总线的数据流

```
t=N:
  [NPC A] → AgentResponse(actions=[speak_to(B, "你昨晚在哪?")])
  handle_response(A, resp) →
    EventBus.publish(WorldEvent(kind="speak", source=A, targets=[B],
                                payload={"text": "你昨晚在哪?"}))

t=N+1 (next tick, NPC B 轮到):
  build_context(B) →
    events = EventBus.drain_for(B)       # 取走所有待处理
    input_event = "A 对你说: 你昨晚在哪?"
    situation 附加: "当前场景: 餐车; 在场: [A, B, C]"
  npc_agent.run(context) → AgentResponse(...)
  handle_response 再发 event，循环
```

EventBus 存两种队列：

- `inbox[npc_id] -> Queue[WorldEvent]`：待该 NPC 消费
- `history: list[WorldEvent]`：最近 N 条（默认 200）用于调试 / 可见性查询

**广播事件（targets=["*"]）** 被 fan-out 写入所有 active NPC 的 inbox（source 本人除外）。

## WorldEvent → input_event 的渲染

`build_context` 内部小工具 `_render_event_as_input(event, viewer_id) -> str`：

| event.kind | 渲染 |
|---|---|
| `speak` | `"{source} 对你说: {payload.text}"` |
| `move` | `"{source} 走进了 {payload.to}"` 或 `"{source} 离开了 {payload.from}"` |
| `observe_broadcast` | `"{payload.text}"` (GM 广播) |
| `world` | `"{payload.text}"` (世界旁白) |
| 其他 | `"[event: {kind}] {payload}"`（具体 engine 覆盖） |

具体 engine 可通过覆盖该方法引入更丰富的渲染。

## 多事件合并策略

若一个 NPC 的 inbox 中一次 drain 出多条 event：

- 首条作为 `input_event`（Agent 的主刺激）
- 其余拼入 `situation` 作为 `"其他近期事件:\n- ...\n- ..."` 背景补充
- 消费后全部 mark consumed

**决定理由**：`input_event` 保留"单一触发"语义，Planner/Executor prompt 不用改。其余事件作为情景信息放 situation，fits the existing "stable context" vs "active stimulus" 分层。

## NPCRegistry

```python
class NPCRegistry:
    def __init__(self):
        self._npcs: dict[str, NPCProfile] = {}
        self._order: list[str] = []            # 保持注册顺序，影响 tick 序

    def register(self, npc_id, profile): ...
    def list_active(self) -> list[str]: ...    # 按注册顺序
    def remove(self, npc_id): ...
    def profile(self, npc_id) -> NPCProfile: ...
```

`DefaultWorldEngine.__init__` 创建一个空 registry；调用方通过 `engine.npcs.register(...)` 或 engine 提供的便捷方法填充。

## step() 默认实现

```python
def step(self, npc_agent) -> list[tuple[str, AgentResponse]]:
    out = []
    for npc_id in self.npcs.list_active():
        events = self.event_bus.drain_for(npc_id)
        if not events:
            continue                           # 无事件不推进该 NPC（idle）
        ctx = self.build_context(npc_id, event=None)  # build_context 读 inbox
        resp = npc_agent.run(ctx)
        self.handle_response(npc_id, resp)
        out.append((npc_id, resp))
    return out
```

**串行保证**：一次 `step()` 内所有 NPC 顺序执行，后发事件在同一 tick 不被处理（写回 inbox，等下一 tick）。避免 "A 说话 → B 立即回 → A 又立即说" 的单 tick 雪崩。

外部驱动：

```python
while not engine.is_done():
    result = engine.step(npc_agent)
    if not result:
        break                                  # 全员 idle，结束
```

## nearby_npcs 的填充

`build_context` 默认实现：

```python
ctx.nearby_npcs = [n for n in self.npcs.list_active() if n != npc_id]
```

具体 engine（如引入位置系统后）覆盖：

```python
def _npcs_visible_to(self, viewer) -> list[str]:
    return [n for n in self.npcs.list_active()
            if n != viewer and self.location_of(n) == self.location_of(viewer)]
```

## 业务工具抽象模板

`src/annie/world_engine/builtin_action_tools.py`：

```python
class SpeakToTool(ToolDef, ABC):
    name = "speak_to"
    description = "Say something to another character."
    input_schema = SpeakToInput

    def __init__(self, engine: "WorldEngine", source_npc: str):
        self._engine = engine
        self._source = source_npc

    @abstractmethod
    def call(self, input, ctx):
        """Concrete engine: publish WorldEvent(kind='speak', ...) + return ack."""
```

`DefaultWorldEngine` **不实例化**这些类（没有假设世界有 location 概念）。具体 engine 在 `tools_for(npc_id)` 中实例化并返回：

```python
class MurderMysteryEngine(DefaultWorldEngine):
    def tools_for(self, npc_id):
        return [
            ConcreteSpeakToTool(self, npc_id),
            ConcreteObserveTool(self, npc_id),
            ConcreteMoveToTool(self, npc_id),
            EvidenceCrossCheckTool(self, npc_id),
        ]
```

Skill 的 `extra_tools` 可声明 `evidence_cross_check`，靠具体 engine 的 `tools_for` 注入到 AgentContext.tools 后才在 ToolRegistry 中可见，`SkillRegistry` 的加载期检查通过。

## 和 Compressor 的交互

`EventBus.drain_for` 之后事件被消化为 `input_event` + `situation` 补充。不直接写 HistoryStore——HistoryStore 在 `handle_response` 路径上写。EventBus.history 只是短期诊断窗口，Compressor 不读它。

## 和 change 1 / 2 的衔接验证

- change 1 的 `working_memory` 预检索不受影响。
- change 2 的 `<available_skills>` 现在能真正列出业务 skill（如 deduction 引用 evidence_cross_check）。
- `plan_todo` 跨 tick 可见：NPC 在 tick N `add` 一条 todo，tick N+k 下次被激活时 `<todo>` 段能读到。

## 边界：多 NPC 共享 ChromaDB 的并发

`DefaultMemoryInterface` 按 NPC 独立 collection；串行 tick 下无并发写。若未来具体 engine 选并发 tick，需在 `chroma_lock.py` 加 per-collection 锁（非本 change）。
