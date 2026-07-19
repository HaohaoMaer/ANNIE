# ANNIE — AI NPC 叙事模拟引擎

**ANNIE** 是一个 Python 框架，用于构建具有持久记忆、自主行为的 AI 驱动 NPC。它提供可复用的、游戏无关的 NPC 认知层，通过三大协议接入不同的游戏引擎。

> **当前焦点：Minecraft AI 伙伴** — 双层认知架构（硬编码反射 + 按需 LLM），实现低延迟、低成本的 NPC 自主行为。

---

## 架构：严格双层分离

```
┌──────────────────────────────────────┐
│  Game Engines（业务逻辑）             │
│  src/annie/town/   — 小镇模拟         │
│  src/annie/minecraft/ — AI 伙伴       │
├──────────────────────────────────────┤
│  World Engine 层                      │
│  src/annie/world_engine/              │
│  - 世界状态、NPC 配置                 │
│  - ChromaDB 记忆后端                  │
│  - JSONL 历史 + 压缩                  │
│  - 业务工具（PlanTodo 等）            │
├─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│
│  NPC Agent 层（游戏无关）              │
│  src/annie/npc/                       │
│  - 无状态认知框架                      │
│  - 5 种认知图路由                      │
│  - Tool-use ReAct 循环                 │
│  - 技能激活系统                        │
│  - 三级上下文压缩                      │
└──────────────────────────────────────┘
```

### 三大协议

| 协议 | 方向 | 用途 |
|------|------|------|
| `AgentContext` | World Engine → Agent | 每次运行的全部数据：npc_id、事件、工具、技能、记忆、提示词 |
| `AgentResponse` | Agent → World Engine | 对话、动作、记忆更新、反思 |
| `MemoryInterface` | 双向（Protocol） | recall、grep、remember、build_context |

`MemoryInterface` 是 `typing.Protocol`，不是 ABC——任何具有正确方法签名的对象都能接入，无需继承。

---

## Minecraft AI 伙伴（最新功能）

### 双层认知架构

| 层级 | 运行频率 | LLM 调用 | 职责 |
|------|----------|----------|------|
| Layer 1 — 硬编码反射 | 每 300ms | 无 | 危险检测、生存反射、火把放置、进食、拾取 |
| Layer 2 — LLM 认知 | 按需触发 | 是 | 玩家指令执行、任务规划与执行、对话交互 |

### 7 个硬编码反射

| 优先级 | 反射 | 触发条件 |
|--------|------|----------|
| 1 | SelfPreservation | 着火/溺水/危险方块/低血量/坠落风险/饥饿 |
| 2 | Unstuck | 120 秒无位移 |
| 3 | Cowardice | 16 格内敌对生物 + 无武器 |
| 4 | SelfDefense | 8 格内敌对 + 有武器 |
| 5 | TorchPlacing | 光照 <7 + 夜晚/洞穴 + 有火把 |
| 6 | Hunger | 饥饿度 ≤6 + 有食物 |
| 7 | ItemCollecting | 附近有掉落物 |

### Pre-tool Hook 危险中断

LLM 任务执行期间，每次工具调用前检查危险状态。检测到危险时立即中断任务，优先处理生存需求。

### 30 个工具（7 类）

移动(8) · 感知(3) · 操作(7) · 合成(4) · 战斗(3) · 交互(2) · 存储(3)

通过 Node.js mineflayer 子进程（JSON-RPC）与 Minecraft 通信。

### 运行

```bash
# 监控模式 — 双层架构主循环
python scripts/run_minecraft_monitor.py

# 任务执行模式
python scripts/run_minecraft_task.py

# 无头模式
python scripts/run_headless_task.py
```

---

## 快速开始

### 环境要求

- Python 3.11+
- Node.js 18+（仅 Minecraft 引擎需要）
- LLM API（DeepSeek 或兼容 OpenAI 接口的服务商）

### 安装

```bash
git clone https://github.com/HaohaoMaer/ANNIE.git
cd ANNIE

# 创建并激活虚拟环境
conda create -n annie python=3.11 && conda activate annie

# 安装（可编辑模式）
pip install -e ".[dev]"

# Minecraft 引擎需要额外安装 Node 依赖
cd src/annie/minecraft && npm install && cd ../../..
```

### 配置

```bash
cp .env.example .env
# 填入你的 API Key：DEEPSEEK_API_KEY=your_key_here
```

模型配置在 `config/model_config.yaml`：

```yaml
model:
  provider: deepseek
  model_name: deepseek-chat
  base_url: https://api.deepseek.com
  api_key_env: DEEPSEEK_API_KEY
  temperature: 0.7
```

---

## 项目结构

```
ANNIE/
├── config/
│   └── model_config.yaml          # 模型配置
├── src/annie/
│   ├── npc/                       # NPC Agent 层（无状态、游戏无关）
│   │   ├── agent.py               # NPCAgent.run() — 入口
│   │   ├── context.py             # AgentContext（三层结构）
│   │   ├── response.py            # AgentResponse、ActionRequest
│   │   ├── planner.py             # skip-first 任务分解
│   │   ├── executor.py            # Tool-use ReAct 循环
│   │   ├── reflector.py           # 结构化反思 → 记忆
│   │   ├── memory/                # MemoryInterface 协议
│   │   ├── tools/                 # ToolDef 基类 + 内置工具
│   │   ├── skills/                # 技能系统
│   │   └── runtime/               # ToolDispatcher、ContextBudget
│   ├── world_engine/              # World Engine 层
│   │   ├── base.py                # WorldEngine ABC
│   │   ├── memory.py              # ChromaDB 记忆实现
│   │   ├── history.py             # JSONL 对话历史
│   │   └── compressor.py          # 跨运行历史折叠
│   ├── town/                      # 小镇模拟（Generative Agents 风格）
│   └── minecraft/                 # Minecraft AI 伙伴
│       ├── engine.py              # 双层认知引擎
│       ├── reflexes.py            # 7 个硬编码反射
│       ├── perception.py          # 感知系统
│       ├── tools/                 # 30 个 Minecraft 工具
│       └── minecraft_bridge.js    # Node.js mineflayer 桥接
├── tests/
├── scripts/
└── docs/
    └── CHANGELOG.md
```

---

## 常用命令

```bash
# 测试
pytest                                    # 全部测试
pytest -m "not integration"               # 跳过集成测试
pytest tests/test_npc/                    # NPC 层单元测试
pytest tests/test_minecraft/              # Minecraft 测试

# 代码检查
ruff check src/
npx pyright src/annie/npc src/annie/world_engine

# 小镇模拟
python scripts/run_town_day_real_llm.py
python scripts/run_town_multi_npc_real_llm.py --enable-reflection
```

---

## 关键测试

| 测试文件 | 验证内容 |
|----------|----------|
| `tests/test_integration/test_decoupled_flow.py` | 端到端 NPCAgent + WorldEngine |
| `tests/test_integration/test_cross_run_todo.py` | 跨运行 Todo 持久化 |
| `tests/test_npc/test_skill_registry.py` | 技能加载、激活、工具解析 |
| `tests/test_npc/test_tool_registry_frames.py` | 工具帧栈 push/pop |
| `tests/test_town/test_town_multi_npc.py` | 完整小镇模拟 |
| `tests/test_minecraft/test_integration.py` | Minecraft 双层架构、反射、工具 |

---

## 技术栈

**核心引擎**
- [LangGraph](https://github.com/langchain-ai/langgraph) — Agent 工作流（StateGraph）
- [LangChain](https://github.com/langchain-ai/langchain) — LLM 抽象层
- [ChromaDB](https://www.trychroma.com/) — 向量记忆存储
- [Pydantic](https://docs.pydantic.dev/) — 全链路数据验证

**Minecraft 引擎**
- [mineflayer](https://github.com/PrismarineJS/mineflayer) — Minecraft Bot 框架
- [minecraft-data](https://github.com/PrismarineJS/minecraft-data) — 配方、方块、物品数据

---

## 设计规则

- **NPC Agent 层禁止**导入 `chromadb`、持有世界状态、包含游戏业务词汇
- **World Engine 层拥有**所有世界状态、记忆后端、业务工具
- **ChromaDB 写入必须序列化**通过 `ChromaWriteGuard`
- **倾向于 Protocol 而非 ABC** 用于跨层接口
- **内置工具优于文本 ReAct** — 使用原生 `bind_tools` + JSON Schema

---

<p align="center">基于 LangGraph · DeepSeek · ChromaDB · mineflayer 构建</p>
