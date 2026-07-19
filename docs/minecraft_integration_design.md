# Minecraft 集成设计方案

> 将 ANNIE 的 NPC 认知框架接入 Minecraft，以 mindcraft 项目为参考。

## 决策记录

| 决策 | 选择 | 原因 |
|---|---|---|
| 连接方案 | Node.js 子进程桥接（mineflayer） | 复用成熟的路径规划、方块数据、战斗系统，不重造轮子 |
| 感知方式 | 文本为主 + 可选截图 | 结构化数据转文本确定性高、成本低；截图作为工具按需调用 |
| 第一阶段 | 基础生存 NPC | 移动→躲避→收集→合成，跑通完整链路后再加长期目标 |

---

## 1. 架构总览

ANNIE 的两层解耦对 Minecraft 完全适用。所有 Minecraft 特有逻辑锁在
`MinecraftWorldEngine` 内部，NPC 层零改动。

```
┌──────────────────────────────────────────┐
│  MinecraftWorldEngine (新增)             │
│  src/annie/minecraft/                    │
│  ┌─────────────┐  ┌──────────────────┐  │
│  │ 反射层       │  │ 认知调度          │  │
│  │ (tick级,     │  │ AgentContext     │  │
│  │  不用LLM)    │  │ → NPCAgent.run() │  │
│  │ 自保/脱困/   │  │ ← AgentResponse  │  │
│  │ 捡物/插火把  │  │ → handle_response│  │
│  └─────────────┘  └──────────────────┘  │
│  ┌──────────────────────────────────┐    │
│  │ 感知管线                          │    │
│  │ 3D世界状态 → 文本描述             │    │
│  └──────────────────────────────────┘    │
│  ┌──────────────────────────────────┐    │
│  │ Minecraft 桥接层                  │    │
│  │ Python ←JSON→ Node.js 子进程      │    │
│  │              (mineflayer)         │    │
│  └──────────────────────────────────┘    │
├──────────────────────────────────────────┤
│  NPC Agent Layer (不改)                  │
│  NPCAgent / 五图路由 / ToolDef / Memory  │
└──────────────────────────────────────────┘
```

### 核心循环

```
WorldEngine.step(agent, npc_id):
    1. [反射层] _check_reflexes()
       → 触发反射动作 → 直接执行 → 结果作为事件注入
    2. 如果没有反射中断：
       → build_context(npc_id, 当前事件)
          ├─ 感知管线：周围方块/实体/物品栏 → 文本
          ├─ 记忆：recall 最近经历 + build_context
          └─ 目标（如有）
       → Agent 五图路由
          ├─ action.executor_default（日常生存）
          └─ reflection（定期反思）
       → drive_npc() 执行行动序列
       → handle_response() 持久化
    3. 如果没有待处理事件（idle）：
       → 注入 self-prompt 事件："继续你的目标：{goal}"
       → 回到步骤 2
```

---

## 2. Minecraft 桥接层 (`bot_connection.py`)

### 2.1 进程架构

```
┌─────────────────┐     JSON over stdio     ┌──────────────────────┐
│  Python (ANNIE)  │ ◄──────────────────────► │  Node.js (mineflayer) │
│  MinecraftBridge │  请求: {method, params}  │  minecraft_bridge.js  │
│                  │  响应: {ok, data/error}  │                       │
└─────────────────┘                          └──────┬───────────────┘
                                                    │
                                            ┌───────┴────────┐
                                            │  Minecraft 服务器 │
                                            │  (局域网/远程)    │
                                            └────────────────┘
```

### 2.2 通信协议

JSON-RPC 风格，一行一个 JSON 对象，通过 stdin/stdout：

```json
// Python → Node (请求)
{"id": "req_001", "method": "go_to", "params": {"x": 100, "y": 64, "z": 200}, "timeout_ms": 30000}

// Node → Python (即时响应：请求是否被接受)
{"id": "req_001", "status": "accepted"}

// Node → Python (异步通知：动作完成/失败)
{"id": "req_001", "status": "completed", "data": {"ok": true, "reason": "arrived"}}
{"id": "req_001", "status": "failed", "data": {"ok": false, "reason": "path blocked"}}

// Node → Python (主动推送：事件)
{"type": "event", "event": "damage", "data": {"source": "zombie", "amount": 3, "health": 17}}
{"type": "event", "event": "death", "data": {"reason": "fell from a high place", "position": [0,70,0]}}
{"type": "event", "event": "chat", "data": {"player": "Steve", "message": "hey bot"}}
```

### 2.3 Python 侧接口

```python
class MinecraftBridge:
    """与 mineflayer 子进程的通信桥"""

    def __init__(self, host: str, port: int, username: str):
        self._proc = None       # Node.js 子进程
        self._pending: dict[str, Future] = {}  # 异步等待队列
        self._event_queue: deque = deque()     # 推送事件队列

    async def start(self) -> None:
        """启动子进程并连接到 Minecraft 服务器"""

    async def call(self, method: str, params: dict, timeout_ms: int = 30000) -> dict:
        """发送请求，等待完成/失败"""

    def poll_events(self) -> list[dict]:
        """取出所有待处理事件"""

    async def stop(self) -> None:
        """断开连接，终止子进程"""
```

### 2.4 Node.js 侧 (`minecraft_bridge.js`)

基于 mindcraft 的核心依赖，精简为一个桥接程序：

```javascript
// 核心依赖（从 mindcraft 继承方案）
const mineflayer = require('mineflayer');
const { pathfinder, Movements, goals } = require('mineflayer-pathfinder');
const { plugin: pvp } = require('mineflayer-pvp');
const minecraftData = require('minecraft-data');

// 不引入 mindcraft 的 agent/LLM/modes 层——那些逻辑全部在 ANNIE 侧
// 只暴露底层能力：移动、方块操作、物品操作、战斗、感知

const bot = mineflayer.createBot({ host, port, username });

// 处理来自 Python 的请求
process.stdin.on('line', (line) => {
    const req = JSON.parse(line);
    const result = handleRequest(req);  // 同步/异步执行
    process.stdout.write(JSON.stringify(result) + '\n');
});

// MC 事件自动推送
bot.on('entityHurt', (entity) => { pushEvent('damage', ...); });
bot.on('death', () => { pushEvent('death', ...); });
bot.on('chat', (username, message) => { pushEvent('chat', ...); });
```

### 2.5 桥接层暴露的底层方法

| 类别 | 方法 | 说明 |
|---|---|---|
| **移动** | `go_to(x, y, z)` | 路径规划走到目标坐标 |
| | `follow(entity_id)` | 跟随实体 |
| | `move_away(distance)` | 远离当前位置 |
| | `dig_down()` / `go_to_surface()` | 垂直移动 |
| | `stop()` | 停止所有移动 |
| **感知** | `get_stats()` | 位置、血量、饥饿度、生物群系 |
| | `get_nearby_blocks(radius)` | 周围方块及其上下文 |
| | `get_nearby_entities(radius)` | 周围实体（含玩家、生物） |
| | `get_inventory()` | 完整物品栏 |
| | `get_craftable()` | 当前可合成的物品 |
| **方块操作** | `break_block(x, y, z)` | 挖掘方块 |
| | `place_block(x, y, z, block_type)` | 放置方块 |
| **物品操作** | `collect_block(block_type, count)` | 收集指定类型方块 |
| | `craft_recipe(item_name, count)` | 合成 |
| | `smelt_item(item_name, count)` | 烧炼 |
| | `equip(item_name, destination)` | 装备物品 |
| | `consume(item_name)` | 食用 |
| | `discard(item_name, count)` | 丢弃 |
| | `open_chest(pos)` / `put_in_chest(...)` / `take_from_chest(...)` | 箱子操作 |
| **战斗** | `attack_entity(entity_id)` | 攻击实体 |
| | `defend_self()` | 防御模式 |
| **交互** | `use_on(x, y, z)` | 使用手中工具于目标 |
| | `interact_with_entity(entity_id)` | 与实体交互（村民等） |

---

## 3. 反射层 (`reflexes.py`)

在 LLM 认知循环之前执行，tick 级检查（每次 `step()` 都跑），不经过 LLM。
触发时直接调用桥接层执行动作，结果作为 `input_event` 注入下一次 LLM 认知循环。

### 3.1 反射定义

```python
class Reflex(ABC):
    name: str
    priority: int          # 数值越小优先级越高
    cooldown_ticks: int    # 触发后冷却

    @abstractmethod
    def should_trigger(self, perception: dict, memory: dict) -> bool: ...
    @abstractmethod
    def execute(self, bridge: MinecraftBridge) -> str: ...  # 返回事件描述
```

### 3.2 第一阶段反射（5 个核心反射）

按优先级排序：

| # | 反射 | 触发条件 | 动作 | 冷却 |
|---|---|---|---|---|
| 1 | `SelfPreservation` | 着火/在岩浆中/溺水/血量<4 | 脱离危险方块/游泳上浮 | 0（立即） |
| 2 | `Unstuck` | 连续 20 秒位置不变（且不在 IntentionalWait 中） | 随机方向移动 2 格 + 跳跃 | 5 tick |
| 3 | `Cowardice` | 16 格内有僵尸/骷髅/苦力怕/蜘蛛，且无武器盔甲 | 向反方向跑 10 格 | 10 tick |
| 4 | `SelfDefense` | 8 格内有敌对生物，且有武器 | 攻击最近的敌人 | 3 tick |
| 5 | `ItemCollecting` | 8 格内有掉落物（物品实体） | 走到掉落物位置拾取 | 2 tick |

### 3.3 反射与 LLM 认知的交互

```python
class MinecraftWorldEngine(WorldEngine):

    def step(self, agent, npc_id):
        perception = self._get_perception(npc_id)
        memory = self.memory_for(npc_id)

        # 1. 反射检查（不经过 LLM）
        for reflex in self._reflexes:  # 按 priority 排序
            if reflex.on_cooldown():
                continue
            if reflex.should_trigger(perception, memory):
                event = reflex.execute(self._bridge)
                self._record_reflex(npc_id, reflex.name, event)
                # 把反射动作结果注入为事件，让 LLM 感知到
                return self.drive_npc(agent, npc_id, f"[反射动作: {reflex.name}] {event}")

        # 2. 时间推进 + 感知
        event = self._build_activation_event(npc_id, perception)
        if event is None:
            # idle：注入 self-prompt
            goal = self._current_goal(npc_id)
            if goal:
                event = f"继续你当前的目标：{goal}\n你周围的状况：{perception.summary}"
            else:
                event = f"环顾四周，决定接下来做什么。\n{perception.summary}"

        return self.drive_npc(agent, npc_id, event)
```

---

## 4. 感知管线 (`perception.py`)

### 4.1 设计原则

Minecraft 的 3D 世界信息密度远高于 Town。感知管线需要做到：
- **抑制**：不把所有信息全部塞进 prompt。LLM 需要详细信息时调用工具。
- **摘要优先**：先给摘要（"周围 4 格有橡木×3、草方块×12、前方 15 米有一只僵尸"），
  再通过工具获取细节。
- **空间排序**：按距离排序，最近的优先。
- **异常突出**：危险物品和实体比普通方块排列更靠前。

### 4.2 感知输出格式

```text
[自身状态]
位置: (-128, 64, 256), 朝向: 北
血量: 17/20, 饥饿度: 15/20
生物群系: 平原, 天气: 晴

[周围方块 (半径4格)]
前方2m: 橡木原木 (树干), 橡木树叶×5
脚下: 草方块
右侧3m: 砂砾
后方1m: 水 (深2格)

[周围实体 (半径16格)]
⚠ 前方12m: 僵尸 (距离12.7m, 正在接近)
左侧8m: 猪×2
后方15m: 玩家 Steve

[掉落物 (半径8格)]
脚下: 橡树树苗×1
右侧3m: 羽毛×2

[物品栏摘要]
主手: 石剑 (耐久 87%)
盔甲: 无
关键物品: 橡木原木×17, 苹果×3, 木棍×5
```

### 4.3 实现

```python
class MinecraftPerception:
    def __init__(self, bridge: MinecraftBridge):
        self._bridge = bridge

    def snapshot(self) -> dict:
        """获取当前时刻的全部感知数据（结构化）"""
        return {
            "stats": self._bridge.call_sync("get_stats", {}),
            "blocks": self._bridge.call_sync("get_nearby_blocks", {"radius": 4}),
            "entities": self._bridge.call_sync("get_nearby_entities", {"radius": 16}),
            "inventory": self._bridge.call_sync("get_inventory", {}),
        }

    def render(self, snapshot: dict) -> str:
        """渲染为 AgentContext 可用的文本"""
        # 按优先级排序：危险实体 > 掉落物 > 方块 > 被动生物 > 玩家
        # 摘要物品栏（高价值物品 + 武器 + 盔甲）
        # 输出前述格式的文本
```

### 4.4 截图工具（可选储备）

```python
class CaptureScreenshotTool(ToolDef):
    name = "capture_screenshot"
    description = "截取当前视角的游戏截图。用于需要视觉判断的场景（远处建筑外观、复杂红石电路等）。返回图片的 base64 编码。"
    is_read_only = True

    def call(self, input, ctx):
        # 通过桥接层调用 mineflayer 的 screenshot 能力
        # 要求桥接层启用 prismarine-viewer 的无头渲染
        base64_image = self._bridge.call("capture_screenshot", {})
        # 将图片填入 LLM vision API 的上下文（需要底层 LLM 配置支持 vision）
        return {"image_base64": base64_image, "format": "png"}
```

第一阶段不实现，但桥接层预留 `capture_screenshot` 方法。

---

## 5. 工具集 (`tools/`)

全部为标准 `ToolDef` 子类，通过 `AgentContext.tools` 注入。

### 5.1 工具分类

#### 移动工具

| 工具 | 参数 | 说明 |
|---|---|---|
| `go_to_coordinates` | `x, y, z` | 路径规划走到坐标。长时动作，返回 `deferred`，完成后推送事件 |
| `go_to_block` | `block_type`, `radius?` | 走到最近的指定类型方块 |
| `go_to_entity` | `entity_type`, `radius?` | 走到最近的指定类型实体 |
| `follow` | `entity_name` | 跟随指定玩家/实体 |
| `move_away` | `distance?` | 远离当前位置 |
| `stop_moving` | — | 停止所有移动 |
| `dig_down` | `depth?` | 向下挖掘 |
| `go_to_surface` | — | 向上回到地面 |
| `look_at` | `x, y, z` | 看向指定坐标 |

#### 查询工具

| 工具 | 说明 |
|---|---|
| `check_surroundings` | 感知快照：周围方块+实体+掉落物（自动注入，也可显式调用） |
| `check_inventory` | 完整物品栏 |
| `check_craftable` | 当前可合成的物品列表 |
| `check_entity` | 查看指定实体的详细信息 |

#### 操作工具

| 工具 | 参数 | 说明 |
|---|---|---|
| `break_block` | `x, y, z` | 挖掘方块 |
| `place_block` | `x, y, z`, `block_type` | 放置方块 |
| `collect_item` | `item_type`, `count?` | 收集地上的掉落物 |
| `pickup_nearby` | `radius?` | 拾取周围所有掉落物 |
| `equip` | `item_name` | 装备/切换到指定物品 |
| `consume` | `item_name` | 食用/饮用 |
| `discard` | `item_name`, `count?` | 丢弃物品 |

#### 合成工具

| 工具 | 参数 | 说明 |
|---|---|---|
| `craft` | `item_name`, `count?` | 合成物品 |
| `smelt` | `item_name`, `count?` | 烧炼物品 |
| `get_crafting_plan` | `item_name` | 递归计算合成树（缺什么材料） |

#### 交互工具

| 工具 | 参数 | 说明 |
|---|---|---|
| `open_chest` | `x, y, z` | 打开箱子 |
| `take_from_chest` | `item_name`, `count?` | 从箱子取物 |
| `put_in_chest` | `item_name`, `count?` | 往箱子放物 |
| `use_on` | `x, y, z` | 对目标使用手中物品 |
| `sleep` | — | 睡觉（如果附近有床） |

#### 战斗工具

| 工具 | 参数 | 说明 |
|---|---|---|
| `attack` | `entity_description` | 攻击指定实体 |
| `defend` | — | 切换到防御模式（自动反击靠近的敌人） |

### 5.2 工具设计要点

**长时动作与 deferred 状态**：
移动类工具（`go_to_coordinates`、`go_to_block` 等）可能需要 5-30 秒完成。
这些工具调用时返回 `ActionResult(status="deferred")`，动作完成后桥接层推送事件，
World Engine 将事件注入下一轮认知循环。

```python
class GoToCoordinatesTool(ToolDef):
    name = "go_to_coordinates"
    ends_activation_on_success = True  # 移动完成后结束当前 Executor 循环

    def call(self, input, ctx):
        # 不等待到达——返回 deferred
        self._bridge.call_async("go_to", {"x": input.x, "y": input.y, "z": input.z})
        return ActionResult(
            status="deferred",
            reason=f"正在前往 ({input.x}, {input.y}, {input.z})",
            observation="开始移动..."
        )
```

**工具合并**：`mindcraft` 有 35+ 命令，很多可以合并。例如 `collect_item` + `pickup_nearby`
合并为一个工具的两种模式，让 LLM 通过参数选择。

---

## 6. 记忆系统

ANNIE 现有的 `DefaultMemoryInterface` + `HistoryStore` 对 Minecraft 基本适用，
但需要三处扩展（全在世界引擎层，不改 `MemoryInterface` 协议）。

### 6.1 空间记忆

利用现有 `metadata` 字段承载坐标，不需要新的记忆类别：

```python
# 存储地点
memory.remember(
    content="我的橡树农场",
    category="spatial",
    metadata={"type": "place", "x": -128, "y": 64, "z": 256, "dimension": "overworld"}
)

# 按维度召回
memory.grep(pattern="农场", category="spatial", metadata_filters={"dimension": "overworld"})
```

给 NPC 一个 `save_place` 工具可以主动存储位置：

```python
class SavePlaceTool(ToolDef):
    name = "save_place"
    description = "记住当前位置，给一个名字（如'我家'、'矿洞入口'）。之后可以通过 recall_place 回查。"
    # call: 从感知中获取当前坐标，写入 spatial 记忆
```

### 6.2 物品栏记忆

物品栏不全部塞进 `AgentContext`（太大了，36 格 + 随机附魔数据）。策略：
- **感知摘要**：只放关键物品摘要（武器、盔甲、数量>10 的堆叠物、稀有物品）
- **按需查询**：LLM 需要详情时调用 `check_inventory` 工具
- **物品位置记忆**："钻石放在橡木农场旁边的箱子里" → spatial 记忆

### 6.3 死亡记忆

当桥接层推送 `death` 事件时，自动记录：
```python
# 在 handle_response 中
if event.type == "death":
    memory.remember(
        content=f"死亡于 {event.data['reason']}，位置 {event.data['position']}",
        category="reflection",
        metadata={"type": "death", "position": event.data['position']}
    )
    memory.remember(
        content="死亡位置",
        category="spatial",
        metadata={"type": "death_point", "x": ..., "y": ..., "z": ..., "dimension": "overworld"}
    )
```

---

## 7. NPC Agent 配置

### 7.1 图路由策略

Minecraft NPC 使用哪些图：

| 场景 | 图 | 触发 |
|---|---|---|
| 日常生存行为 | `action.executor_default` | `step()` 默认路径 |
| 收到玩家指令 | `action.executor_default` | 玩家聊天/私聊事件 |
| 多步骤复杂操作 | `action.plan_execute` | 当 executor 路径找不到目标物品、需要多步合成时，通过 retry 进入 Planner |
| 定期反思 | `reflection.evidence_to_memory_candidate` | 每 N 分钟或重大事件后（死亡、发现稀有物、建造完成） |
| 物品/配方判断 | `output.structured_json` | 判断"用我现有的材料，最快获得铁镐的路径是什么" |

### 7.2 System Prompt 设计

```text
<character>
你是 {name}，一个在 Minecraft 世界中自主生存的 AI 助手。
你的核心驱动力是：生存、探索、收集资源、变得更强。
{character_prompt}
</character>

<world_rules>
你在一个 Minecraft {difficulty} 难度世界中。
- 你需要食物来维持生命。饥饿度低于 6 时必须进食。
- 夜晚会刷出怪物。如果你没有武器盔甲，在夜晚要寻找庇护所。
- 你可以挖掘方块、合成物品、建造结构。
- 死亡会让你掉落所有物品。避免不必要的风险。
- 你可以与玩家交流。对玩家的请求要积极响应。
</world_rules>

<situation>
{perception_summary}
当前目标: {current_goal}
</situation>

<available_tools>
除了记忆工具外，你有以下 Minecraft 专属工具：
移动: go_to_coordinates, go_to_block, go_to_entity, follow, move_away, stop_moving
感知: check_surroundings, check_inventory, check_craftable
操作: break_block, place_block, collect_item, equip, consume, discard
合成: craft, smelt
交互: open_chest, take_from_chest, put_in_chest, use_on, sleep
战斗: attack, defend
</available_tools>
```

---

## 8. 实现阶段

### 第一阶段：基础生存 NPC（目标：跑通完整链路）

**搭建骨架**：
- `src/annie/minecraft/` 包结构创建
- `MinecraftBridge` Python 侧 + `minecraft_bridge.js` Node.js 侧
- 连接本地 Minecraft 服务器（局域网或 Docker）

**反射层**：
- 5 个核心反射（自保/脱困/懦夫/自卫/捡物品）
- 在 `step()` 中集成反射检查

**感知管线**：
- `MinecraftPerception.snapshot()` + `render()`
- 文本格式的感知摘要

**工具集（第一批 12-15 个）**：
- 移动：`go_to_coordinates`, `go_to_block`, `stop_moving`, `dig_down`, `go_to_surface`
- 查询：`check_surroundings`, `check_inventory`
- 操作：`break_block`, `collect_item`, `equip`, `consume`
- 合成：`craft`, `get_crafting_plan`
- 战斗：`attack`, `defend`

**集成测试**：
- NPC 能在世界里走动、躲避怪物、收集木头、合成木板、制作木剑
- 基于 `_StubLLM` 的确定性测试
- 可选：连接真实 Minecraft 的冒烟测试

### 第二阶段：记忆与目标

- 空间记忆（`category=spatial`）+ save_place / recall_place 工具
- 物品栏位置记忆
- Self-prompter（idle 时自动推动目标）
- 长期目标设定（"建造一个房子"、"去末地"）
- 定期反思

### 第三阶段：高级能力

- 截图视觉感知（按需调用）
- 层级化规划（建造大型结构的子任务拆解）
- 多 NPC 协作（共享空间记忆、分工合作）
- 玩家交互（对话、跟随、协助建造）

---

## 9. 文件结构

```
src/annie/minecraft/
├── __init__.py               # 导出 MinecraftWorldEngine
├── engine.py                  # MinecraftWorldEngine(WorldEngine)
├── bot_connection.py          # MinecraftBridge 类
├── minecraft_bridge.js        # Node.js 子进程入口
├── package.json               # Node.js 依赖（mineflayer 等）
├── perception.py              # MinecraftPerception
├── reflexes.py               # Reflex ABC + 5 核心反射
├── prompts.py                # Minecraft system prompt
├── config.py                 # MinecraftConfig（服务器地址/端口等）
├── tools/
│   ├── __init__.py
│   ├── movement.py           # 移动工具
│   ├── perception.py         # 查询工具
│   ├── operation.py          # 方块/物品操作工具
│   ├── crafting.py           # 合成工具
│   ├── interaction.py        # 箱子/实体交互工具
│   └── combat.py             # 战斗工具
├── memory/
│   ├── __init__.py
│   └── spatial.py            # 空间记忆辅助
└── tests/
    ├── __init__.py
    ├── test_reflexes.py      # 反射单元测试
    ├── test_perception.py    # 感知渲染测试
    ├── test_tools.py         # 工具单元测试
    └── test_integration.py   # 端到端（StubLLM + FakeBridge）
```

---

## 10. 关键风险与缓解

| 风险 | 缓解 |
|---|---|
| Node.js 子进程管理复杂 | 使用 `asyncio.create_subprocess_exec` 管理生命周期，超时自动重启 |
| 长时动作的超时处理 | 每个 `deferred` 动作设超时，超时推送 `status: "timeout"` 事件 |
| 桥接层通信延迟 | 本地 stdio/WebSocket 延迟 < 5ms，不是瓶颈 |
| LLM 对 Minecraft 知识不足 | System prompt 中嵌入关键合成配方和生存知识；`get_crafting_plan` 工具提供精确配方 |
| 反射与 LLM 动作冲突 | 反射执行时通过桥接层 `stop()` 取消所有进行中的动作；结果注入为事件让 LLM 感知 |
| 感知文本过长触发 Emergency | 摘要优先策略 + 按需工具查询；反射层的危险实体优先展示 |

---

## 参考

- mindcraft 项目：Node.js + mineflayer 的 LLM-Minecraft 集成，提供了 Modes/命令/代码生成三层自治模型
- ANNIE AGENTS.md：项目架构详述
- OpenSpec 规格：`openspec/specs/world-engine/` — WorldEngine ABC 的扩展指南
