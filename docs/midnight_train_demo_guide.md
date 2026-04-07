# 午夜列车剧本杀Demo使用说明

## 快速开始

### 1. 环境准备

确保已安装所有依赖：

```bash
# 激活conda环境
conda activate annie

# 安装新依赖
pip install easyocr python-docx Pillow
```

### 2. 配置API Key

确保`.env`文件中包含DeepSeek API Key：

```env
DEEPSEEK_API_KEY=your_api_key_here
```

### 3. 运行Demo

```bash
python scripts/run_midnight_train_demo.py
```

---

## 系统架构

### 三层架构

```
┌─────────────────────────────────────────────────────────┐
│                    World Engine Agent                    │
│                      (主持人/导演)                         │
│                                                          │
│  • 读取所有剧本文件 (PDF, DOCX, 图片)                      │
│  • 使用LLM生成游戏流程                                     │
│  • 初始化所有NPC                                          │
│  • 控制游戏进程                                           │
│  • 管理线索揭示                                           │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                      NPC Agents                          │
│                       (角色代理)                          │
│                                                          │
│  鸥乘务  │  白乘客  │  董乘客  │  林乘客  │  何侦探  │ 撒乘客 │
│                                                          │
│  • 认知层 (动机、信念、情绪、决策)                          │
│  • 个人视角                                              │
│  • 目标驱动行为                                           │
└─────────────────────────────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────┐
│                    Social Graph                          │
│                      (社交图谱)                           │
│                                                          │
│  • 共有知识存储                                           │
│  • 角色关系网络                                           │
│  • 信息传播                                               │
│  • 事件记录                                               │
└─────────────────────────────────────────────────────────┘
```

---

## 剧本文件结构

```
午夜列车/
├── 人物剧本/              # NPC初始化来源
│   ├── 鸥乘务.pdf
│   ├── 白乘客.pdf
│   ├── 董乘客.pdf
│   ├── 林乘客.pdf
│   ├── 何侦探.pdf
│   └── 撒乘客.pdf
│
├── 线索/                  # 线索图片 (OCR提取文字)
│   ├── 鸥乘务/ (11张)
│   ├── 董乘客/ (9张)
│   ├── 白乘客/ (9张)
│   ├── 死者的房间/ (10张)
│   ├── 林乘客/ (9张)
│   └── 撒乘客/ (9张)
│
├── 背景.docx              # 背景故事
├── 游戏流程.docx          # 游戏流程文档
└── 真相.pdf               # 真相揭晓
```

---

## 核心组件

### 1. 文件读取Tools

#### ImageReaderTool
- **功能**: 读取jpg/png图片，使用EasyOCR提取文字
- **支持**: 中文简体、英文
- **用法**:
  ```python
  tool = ImageReaderTool()
  result = tool.execute({"image_path": "clue.jpg"})
  text = result["text"]
  ```

#### DOCXReaderTool
- **功能**: 读取.docx文档
- **支持**: 全文读取、结构化读取
- **用法**:
  ```python
  tool = DOCXReaderTool()
  result = tool.execute({"docx_path": "背景.docx"})
  text = result["text"]
  ```

#### PDFReaderTool
- **功能**: 读取PDF文件
- **支持**: 全文、分页、关键词搜索
- **用法**:
  ```python
  tool = PDFReaderTool()
  result = tool.execute({"pdf_path": "真相.pdf"})
  content = result["content"]
  ```

### 2. WorldEngineAgent

**核心功能**：

```python
# 初始化
world_engine = WorldEngineAgent(
    script_folder="午夜列车",
    config=model_config,
)

# 读取所有文件
world_engine.read_all_files()

# 生成游戏流程
game_flow = world_engine.generate_game_flow()

# 初始化NPC
world_engine.initialize_npcs()

# 运行游戏
world_engine.start_game()
world_engine.run_game_loop()
```

**与NPC Agent的区别**：

| 特性 | WorldEngineAgent | NPC Agent |
|------|------------------|-----------|
| 角色 | 主持人/导演 | 角色/玩家 |
| 视角 | 上帝视角 | 个人视角 |
| 知识 | 全知 | 有限 |
| 目标 | 推进剧情 | 完成个人目标 |
| 行为 | 管理、控制 | 调查、交流 |

### 3. ClueManager

**线索管理**：

```python
# 添加线索
clue = Clue(
    id="死者的房间_01",
    category="死者的房间",
    file_name="01.jpg",
    content="OCR提取的文字",
)
clue_manager.add_clue(clue)

# 揭示线索
clue_manager.reveal_clue("死者的房间_01", "鸥乘务")

# 查询
discovered = clue_manager.get_discovered_clues()
by_category = clue_manager.get_clues_by_category("死者的房间")
```

---

## 游戏流程

### 1. 初始化阶段

```
[系统] 正在初始化世界引擎...
[系统] 正在读取剧本文件...
  - 读取背景.docx ✓
  - 读取游戏流程.docx ✓
  - 读取真相.pdf ✓
  - 读取6个人物剧本 ✓
  - 读取55张线索图片 ✓
[系统] 正在生成游戏流程...
[系统] 正在初始化NPC...
  - 鸥乘务 ✓
  - 白乘客 ✓
  - 董乘客 ✓
  - 林乘客 ✓
  - 何侦探 ✓
  - 撒乘客 ✓
```

### 2. 游戏循环

```
======================================================================
  第一幕：开场
======================================================================

[主持人] 各位乘客，欢迎登上午夜列车。在这趟旅程中，你们将...

[系统] 鸥乘务 的回合
  行动：检查车厢...

[系统] 白乘客 的回合
  行动：与其他乘客交谈...

...

======================================================================
  第二幕：调查
======================================================================

[主持人] 随着调查的深入，更多线索浮出水面...

...

======================================================================
  第三幕：真相
======================================================================

[主持人] 真相即将揭晓...

======================================================================
  游戏结束
======================================================================

[主持人] 真相揭晓：
...
```

---

## 自定义剧本

### 创建新剧本

1. **准备剧本文件夹**：
   ```
   我的剧本/
   ├── 人物剧本/
   │   ├── 角色1.pdf
   │   └── 角色2.pdf
   ├── 线索/
   │   ├── 角色1/
   │   │   └── 线索1.jpg
   │   └── 公共线索/
   │       └── 线索2.png
   ├── 背景.docx
   ├── 游戏流程.docx
   └── 真相.pdf
   ```

2. **创建Demo脚本**：
   ```python
   # scripts/run_my_script_demo.py
   
   from annie.world_engine.world_engine_agent import WorldEngineAgent
   from annie.npc.config import load_model_config
   
   config = load_model_config("config/model_config.yaml")
   
   world_engine = WorldEngineAgent(
       script_folder="我的剧本",
       config=config,
   )
   
   world_engine.read_all_files()
   world_engine.generate_game_flow()
   world_engine.initialize_npcs()
   
   world_engine.start_game()
   world_engine.run_game_loop()
   ```

3. **运行**：
   ```bash
   python scripts/run_my_script_demo.py
   ```

---

## 技术细节

### OCR配置

使用EasyOCR进行图片文字提取：

```python
import easyocr

# 首次使用会下载模型 (~500MB)
reader = easyocr.Reader(['ch_sim', 'en'], gpu=False)

# 读取图片
result = reader.readtext('image.jpg')
text = '\n'.join([item[1] for item in result])
```

### LLM流程生成

WorldEngineAgent使用LLM生成游戏流程：

```python
prompt = f"""
你是一个剧本杀游戏的主持人。请根据以下信息生成游戏流程：

背景：{background}
游戏流程文档：{game_flow_doc}
角色：{characters}

请生成JSON格式的游戏流程，包含：
1. phases: 游戏阶段列表
2. 每个阶段的名称、描述、允许行动、NPC顺序
"""

response = llm.invoke(prompt)
flow = parse_json(response.content)
```

### NPC初始化

从人物剧本提取NPC信息：

```python
prompt = f"""
从以下人物剧本中提取角色信息：

角色名：{name}
剧本内容：{script}

请提取：
1. 性格特点
2. 背景故事
3. 目标
4. 秘密
5. 与其他角色的关系
"""

response = llm.invoke(prompt)
profile = parse_npc_info(response.content)
```

---

## 故障排除

### 问题1: OCR识别不准确

**解决方案**：
- 确保图片清晰度足够
- 尝试使用GPU加速：`easyocr.Reader(['ch_sim', 'en'], gpu=True)`
- 考虑使用其他OCR引擎（如Tesseract）

### 问题2: LLM生成流程不稳定

**解决方案**：
- 调整temperature参数（降低随机性）
- 提供更详细的游戏流程文档
- 使用结构化输出格式

### 问题3: NPC初始化失败

**解决方案**：
- 检查人物剧本PDF是否可读
- 确保LLM API Key有效
- 查看日志中的错误信息

---

## 性能优化

### 1. OCR缓存

EasyOCR首次加载模型较慢，建议：
- 预加载模型
- 缓存OCR结果

### 2. 批量处理

对于大量线索图片：
```python
# 批量读取
result = image_reader.execute({
    "folder_path": "线索/死者的房间",
    "recursive": False,
})
```

### 3. 异步处理

考虑使用异步处理提高效率：
```python
import asyncio

async def process_clues():
    tasks = [read_clue_async(clue) for clue in clues]
    results = await asyncio.gather(*tasks)
```

---

## 扩展功能

### 1. 添加新Tool

```python
# src/annie/npc/tools/my_tool.py

from annie.npc.tools.base_tool import BaseTool

class MyTool(BaseTool):
    name = "my_tool"
    description = "我的自定义工具"
    
    def execute(self, context: dict) -> dict:
        # 实现功能
        return {"success": True, "result": "..."}
```

### 2. 自定义认知层

```python
# 添加新的动机类型
class MyMotivationType(str, Enum):
    CUSTOM = "custom"

# 自定义决策逻辑
class MyDecisionMaker(DecisionMaker):
    def select_best_action(self, options, emotional_state, belief_system):
        # 自定义选择逻辑
        pass
```

---

## 联系与支持

如有问题或建议，请查看项目文档或提交Issue。

---

**祝您游戏愉快！** 🎭
