# CHANGELOG

## 2026-07-19 — Minecraft 集成：双层架构 + 全工具集

### 新增：Minecraft 游戏引擎 (`src/annie/minecraft/`)

**双层认知架构（核心设计）**

将 NPC 决策分为两层，大幅降低 LLM 调用频率：

- **Layer 1 — 硬编码反射层 (300ms)**：纯规则驱动，无 LLM 调用。每 tick 轮询
  bridge 事件、检查危险、更新感知缓存。仅在触发反射或收集到玩家事件时才产生输出。
- **Layer 2 — 按需 LLM 认知层**：仅在以下情况激活：
  - 玩家发送消息/指令
  - NPC 正在执行活跃任务 (`_active_task`)
  - 受 `MIN_COGNITION_INTERVAL=1s` 速率限制

**7 个硬编码反射 (`reflexes.py`)**

按优先级排序，高优先级可打断低优先级：

| 优先级 | 反射 | 触发条件 | 行为 |
|--------|------|----------|------|
| 1 | SelfPreservation | 着火/溺水/危险方块<3格/血量≤6/坠落风险≥5/饥饿≤4+HP<10 | 停止移动，远离10格或上浮 |
| 2 | Unstuck | 120秒内无位置变化 | 随机移动尝试脱困 |
| 3 | Cowardice | 16格内敌对生物 + 无武器 | 远离16格 |
| 4 | SelfDefense | 8格内敌对 + 有武器，或<4格无武器 | 迎战 |
| 5 | TorchPlacing | 光照<7 + 夜晚/洞穴 + 有火把 (15s冷却) | 在最暗处放置火把 |
| 6 | Hunger | 饥饿度≤6 + 有食物 | 吃最优食物 |
| 7 | ItemCollecting | 附近有掉落物 | 捡起物品 |

**Pre-tool Hook 危险中断机制**

- `engine._create_danger_hook()` 生成闭包，注入 `AgentContext.extra["_pre_tool_hook"]`
- `ToolDispatcher.dispatch_result()` 在每次工具调用前执行 hook 检查
- 检测到危险时返回 `interrupted=True`，阻断工具执行，LLM 收到中断原因文本
- 确保 LLM 任务执行期间也能被危险反射中断

**感知缓存**

- `reflex_tick()` 结束时刷新 `_cached_snapshot` 和 `_cached_perception_text`
- Monitor 脚本直接读缓存，无需额外 bridge 调用
- `should_activate_cognition()` 用缓存判断是否有玩家事件

### 新增：Minecraft 工具集 (`src/annie/minecraft/tools/`)

30 个工具，覆盖 mindcraft 全技能库，分 7 类：

| 类别 | 数量 | 工具 |
|------|------|------|
| 移动 (movement) | 8 | go_to_coordinates, go_to_block, stop_moving, move_away, dig_down, go_to_surface, follow_player, go_to_player |
| 感知 (perception) | 3 | check_surroundings, check_inventory, check_craftable |
| 操作 (operation) | 7 | break_block, collect_item, equip, consume, discard, place_block, pickup_nearby |
| 合成 (crafting) | 4 | craft, get_crafting_plan, smelt_item, clear_furnace |
| 战斗 (combat) | 3 | attack, defend, equip_best_weapon |
| 交互 (interaction) | 2 | send_chat, give_to_player |
| 存储 (storage) | 3 | view_chest, take_from_chest, put_in_chest |

所有工具使用原生 LLM tool calling（`bind_tools` + JSON Schema），与 mindcraft
的文本解析 `!command()` 方式本质不同。

### 新增：Minecraft Bridge (`data/minecraft/`)

- Node.js mineflayer 子进程，通过 stdin/stdout newline-delimited JSON-RPC 通信
- 增强的 `getStats()` 返回：着火状态、水中/溺水、光照等级、坠落风险、附近危险方块
- 新增 bridge 方法：`placeTorchNearby`, `smeltItem`, `clearFurnace`, `giveToPlayer`, `followPlayer`, `goToPlayer`

### 新增：运行脚本

- `scripts/run_minecraft_monitor.py` — 双层架构主循环（300ms reflex + 条件 LLM）
- `scripts/run_minecraft_task.py` — 任务执行模式
- `scripts/run_minecraft_task_video.py` — 带录屏的任务执行
- `scripts/run_headless_task.py` — 无头模式任务执行
- `scripts/smoke_minecraft_bridge.py` — Bridge 连通性烟雾测试

### 新增：ToolDispatcher Pre-tool Hook

- `src/annie/npc/runtime/tool_dispatcher.py` — `dispatch_result()` 在执行工具前检查
  `agent_context.extra.get("_pre_tool_hook")`，返回中断结果以阻断危险操作
- 此机制为通用设计，不限于 Minecraft——任何 WorldEngine 可注入自定义 hook

### 新增：测试 (`tests/test_minecraft/`)

22 个测试覆盖：
- 双层架构：reflex_tick/cognition_tick 分离、认知门控、速率限制
- 7 个反射：自保、脱困、怯懦、自卫、火把、饥饿、拾取
- 危险中断：pre-tool hook 阻断、恢复
- 工具构建：build_context 包含全部 30 个工具

### 清理：移除旧模块

- 移除 `src/annie/war_game/` — 三阵营策略游戏
- 移除 `src/annie/interrogation/` — 侦探审讯游戏
- 移除 `double_shadow/` — 审讯游戏脚本资源
- 移除 `data/skills/` — 旧 Jinja 技能文件
- 移除 `data/war_game/` — 战棋历史数据
- 移除 `data/npcs/example_npc.yaml`
- 移除 `docs/assets/game.png`, `docs/assets/main.png`

### 修改：现有模块

- **`src/annie/npc/prompts.py`** — 优化提示词模板
- **`src/annie/world_engine/base.py`** — drive_npc 循环改进
- **`AGENTS.md`** — 更新架构文档，添加 Minecraft 模块说明
- **`CLAUDE.md`** — 指针同步
- **`PROJECT_INTERVIEW.md`** — 面试稿更新
- **`scripts/show_town_replay_snapshot.py`** — 兼容性修复
- **测试更新** — test_decoupled_flow, test_skill_registry, test_town_multi_npc

### .gitignore 更新

- 添加 `data/minecraft/recordings/` — 测试录屏产物
- 添加 `data/minecraft/test_run/` — 测试运行输出
- 添加 `data/minecraft/*_history/` — 运行时历史记录
- 添加 `data/minecraft/history/` — 运行时历史记录

---

## 2026-07-18 及之前

参见 git log 获取早期变更历史：
- `f3b4a2a` feat(town): harden long-run autonomy
- `40d9f06` first phase
- `fe09ff1` refactor(npc,world): decouple agent runtime and add game engines
- `c92b5b1` refactor(npc,world_engine): skills/todo/tool-frames + history/compressor overhaul
- `568ecf9` chore(openspec): archive npc-memory-and-prompt-overhaul
