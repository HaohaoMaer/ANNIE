# 世界引擎层 Capability Spec — Delta

本次 change 对 world-engine capability 的修订。

## ADDED Requirements

### Requirement: WorldEngine 必须提供 `tools_for(npc_id)` 注入 hook

`WorldEngine` 基类必须提供一个可覆盖的方法 `tools_for(npc_id) -> list[ToolDef]`，默认返回空列表。`build_context` 必须将该方法的返回值合并进 `AgentContext.tools`，使具体 engine 能通过加法式覆盖注入业务工具，而无需重写 `build_context`。

#### Scenario: 子类覆写 tools_for 即生效

- **WHEN** 子类 `MyEngine(DefaultWorldEngine)` 覆写 `tools_for`，返回 `[InteractTool(...)]`
- **AND** 未覆写 `build_context`
- **THEN** 通过 `MyEngine.build_context(npc_id)` 构造的 AgentContext.tools 必须包含 `InteractTool`

#### Scenario: 默认 engine 无业务工具

- **WHEN** 使用未经子类化的 `DefaultWorldEngine`
- **THEN** `tools_for(npc_id)` 返回 `[]`，不影响已注入的 `AgentContext.tools`

---

### Requirement: WorldEngine 必须支持多 NPC 并存与事件总线路由

`WorldEngine` 必须持有：

- `npcs: NPCRegistry` — 管理当前 active NPC 集合，保持注册顺序
- `event_bus: EventBus` — 提供事件定向 / 广播 / 消费

`WorldEngine.step(npc_agent)` 必须按以下默认语义实现：

1. 迭代 `npcs.list_active()` 顺序
2. 对每个 NPC，`event_bus.drain_for(npc_id)` 取出该 NPC 的待处理事件
3. 若为空，跳过该 NPC（idle）
4. 否则构造 AgentContext（首个事件作为 `input_event`，其余补入 `situation`）并调用 `npc_agent.run(ctx)`
5. `handle_response` 消费返回的 AgentResponse，将 NPC 发出的动作转为 `WorldEvent` 重新 publish 回 EventBus

具体 engine 可覆盖 `step` 实现优先级 / 并发 / 触发器驱动的调度。

#### Scenario: 两 NPC 的消息往返

- **GIVEN** A、B 两个 NPC 已注册，外部 GM 向 A publish 一条 speak event
- **WHEN** 第一次 step(): A 被推进，输出一句回话（publish 回 bus，target=B）
- **AND** 第二次 step(): B 被推进，消费 A 的消息，输出回复（target=A）
- **THEN** 每次 step() 中每个 NPC 至多被推进一次
- **AND** 同一 tick 内后发事件不会被同 tick 消费

#### Scenario: 无事件时 idle

- **WHEN** 所有 active NPC 的 inbox 均空
- **THEN** step() 返回 `[]`
- **AND** 调用方可据此判断终止 tick 循环

---

### Requirement: `build_context` 必须填充 `nearby_npcs` 字段

`AgentContext.nearby_npcs` 作为粗粒度"同场存在"的载体，必须由 `build_context` 填充。默认实现为"所有 active NPC 除自身"。具体 engine 引入位置/可见性系统后应覆盖为实际可见集合。

#### Scenario: 默认引擎的 nearby_npcs

- **GIVEN** 已注册 NPC A、B、C
- **WHEN** 为 A 构造 AgentContext
- **THEN** `nearby_npcs == ["B", "C"]`

---

### Requirement: EventBus 必须支持定向与广播，不负责持久化

`EventBus.publish(event)` 的路由规则：

- `event.targets == ["*"]` → 扇出到所有 active NPC 的 inbox（排除 event.source）
- 否则按 `targets` 列表逐个写入对应 inbox

`drain_for(npc_id)` 是销毁性读取：取走 inbox 中所有事件并返回。
`history(limit)` 仅提供最近 N 条用于调试 / 可见性查询，不作为真相源。
跨 session / 跨进程持久化不在范围；持久化由 `HistoryStore` 负责。

#### Scenario: 广播事件扇出

- **GIVEN** 已注册 A、B、C
- **WHEN** publish(kind="announce", source="gm", targets=["*"], payload=...)
- **THEN** A、B、C 的 inbox 各获得一条该事件的副本
- **AND** source=gm 的特殊来源不影响扇出（gm 不在 active NPC 列表中）

#### Scenario: drain 是销毁性读

- **WHEN** 对 A 连续两次 `drain_for("A")`
- **THEN** 第一次返回所有待处理事件
- **AND** 第二次返回 `[]`
