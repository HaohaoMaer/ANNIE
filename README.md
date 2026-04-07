# ANNIE — AI NPC Narrative Simulation Engine

**ANNIE** is a LangGraph-powered multi-agent framework for building intelligent NPCs with persistent memory, dynamic social relationships, and autonomous behavior. It is a **simulation engine**, not a chatbot — each NPC is a complete agent that perceives the world, forms beliefs, feels emotions, and acts from its own motivations.

> **Live Demo: 午夜列车 (Midnight Train)** — A fully automated murder mystery where 6 AI-driven NPCs interrogate each other, deduce the killer, and vote on a verdict. Every run produces a unique story.

---

<!-- 截图占位：Web UI 首页 / 游戏主界面 -->
<!-- TODO: 放一张 web/frontend 首页或游戏界面的截图 -->
![Web UI Screenshot](docs/assets/screenshot_main.png)

---

## Table of Contents

- [Features](#features)
- [Architecture](#architecture)
- [Demo — 午夜列车](#demo--午夜列车-midnight-train)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Running Tests](#running-tests)
- [Roadmap](#roadmap)
- [Contributing](#contributing)

---

## Features

| Feature | Description |
|---|---|
| **Autonomous NPC Agents** | Each NPC runs its own LangGraph `StateGraph` (Plan → Execute → Reflect) independently |
| **Cognitive Layer** | Motivation engine, belief system, emotional state, and decision scoring — all per NPC |
| **Social Graph** | Global truth layer for all inter-NPC relationships, separate from NPC subjective perception |
| **Information Asymmetry** | NPCs have different knowledge states; gossip propagates through the social graph with trust-based distortion |
| **Persistent Memory** | ChromaDB-backed episodic and semantic memory per NPC, compressed across ticks |
| **Skill System** | File-based, two-tier skill loading (`base/` for all NPCs, `personalized/` per character YAML) |
| **World Engine** | Game Master agent that reads script files (PDF/DOCX/images via OCR), summarizes characters, controls game phases, and tallies votes |
| **Real-time Web UI** | Next.js frontend + FastAPI/SSE backend for live game visualization and replay |

---

## Architecture

ANNIE is built on three decoupled layers:

```
┌──────────────────────────────────────────────────────────────┐
│                    Layer 3: World Engine                      │
│                  (Director / Game Master)                     │
│                                                               │
│  WorldEngineAgent  ·  GameMaster  ·  ClueManager             │
│  ScriptParser  ·  PhaseController  ·  TurnManager            │
└───────────────────────────┬──────────────────────────────────┘
                            │ spawns & orchestrates
┌───────────────────────────▼──────────────────────────────────┐
│                    Layer 1: NPC Agent Layer                   │
│                                                               │
│  ┌─────────────────────────────────────────────────────────┐ │
│  │  NPCAgent  (LangGraph StateGraph)                        │ │
│  │                                                          │ │
│  │   Planner ──► Executor ──► Reflector                    │ │
│  │                                                          │ │
│  │   Cognitive Layer          Sub-Agents                   │ │
│  │   • MotivationEngine       • MemoryAgent                │ │
│  │   • BeliefSystem           • SocialAgent                │ │
│  │   • EmotionalState         • SkillAgent                 │ │
│  │   • DecisionMaker          • ToolAgent                  │ │
│  │                                                          │ │
│  │   Memory                   Skills / Tools               │ │
│  │   • EpisodicMemory         • conversation               │ │
│  │   • SemanticMemory         • observation / reasoning    │ │
│  │   • RelationshipMemory     • deduction / interrogation  │ │
│  └─────────────────────────────────────────────────────────┘ │
└───────────────────────────┬──────────────────────────────────┘
                            │ queries & updates
┌───────────────────────────▼──────────────────────────────────┐
│                  Layer 2: Social Graph Layer                  │
│                   (Global Relationship Truth)                 │
│                                                               │
│  SocialGraph  ·  SocialEventLog  ·  PropagationEngine        │
│  KnowledgeFilter  ·  BeliefEvaluator  ·  PerceptionBuilder   │
└──────────────────────────────────────────────────────────────┘
```

### Key Design Principles

- **NPCs perceive, they do not own.** World state lives in World Engine; relationship truth lives in Social Graph. NPCs hold only their subjective view.
- **Information asymmetry by design.** The Perception Pipeline (L1 filter → L2 belief evaluation → L3 worldview assembly) transforms objective graph truth into each NPC's subjective knowledge.
- **Opt-in integration.** All Phase 2/3 components wire in via optional constructor params — Phase 1 code paths are unchanged when `social_graph=None`.
- **Context compression.** Memory is stored in ChromaDB and retrieved as compressed summaries, not raw history, to keep prompt sizes bounded.

---

## Demo — 午夜列车 (Midnight Train)

A complete murder mystery powered by a commercial 剧本杀 script. The system:

1. **OCRs** 6 character PDFs and 57 clue images from the script folder
2. **Summarizes** each character into a structured JSON profile (identity, secrets, goals, murderer flag)
3. **Initializes** 6 NPC agents, each with their own cognitive layer and private script knowledge
4. **Runs** a multi-phase game loop: free discussion → deduction → accusation → voting
5. **Announces** results: votes are tallied by `Counter`, compared against the real murderer, and narrated by the Game Master LLM

Each NPC produces three outputs per turn:
- `【内心活动】` — private inner reasoning from their secret script (not shared)
- `【说的话】` — strategic public speech (may contradict inner thoughts)
- `【投票】` — final accusation (voting phase only)

<!-- 截图占位：游戏运行中的对话界面 -->
<!-- TODO: 放一张游戏进行中、NPC对话流的截图 -->
![Game In Progress](docs/assets/screenshot_game.png)

<!-- 截图占位：真相揭露界面 -->
<!-- TODO: 放一张投票结果 / 真相揭露界面的截图 -->
![Truth Reveal](docs/assets/screenshot_truth.png)

### Running the Demo

#### Terminal mode (no UI)

```bash
python scripts/run_midnight_train_demo.py
```

#### Web UI mode

```bash
# Terminal 1 — Backend (FastAPI + SSE)
uvicorn web.backend.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Frontend (Next.js)
cd web/frontend
npm install
npm run dev
# Open http://localhost:3000
```

> **Note:** The `午夜列车/` script folder is not included in the repository (copyrighted commercial content). Place your own 剧本杀 script folder at the repo root and update `SCRIPT_FOLDER` in `web/backend/main.py`.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (web UI only)
- A [DeepSeek API key](https://platform.deepseek.com/) (or any OpenAI-compatible endpoint)

### Install

```bash
git clone https://github.com/HaohaoMaer/ANNIE.git
cd ANNIE

# Create and activate a virtual environment
conda create -n annie python=3.11 && conda activate annie
# or: python -m venv .venv && source .venv/bin/activate

# Install the package (editable)
pip install -e ".[dev]"
```

### Configure

```bash
cp .env.example .env
# Edit .env and set your API key:
# DEEPSEEK_API_KEY=your_key_here
```

Model, embedding, and memory settings live in `config/model_config.yaml`. The defaults use DeepSeek and local `BAAI/bge-m3` embeddings.

---

## Project Structure

```
ANNIE/
├── config/
│   └── model_config.yaml          # Model provider, embeddings, memory backend
├── data/
│   ├── npcs/
│   │   └── example_npc.yaml       # Minimal NPC definition for testing
│   └── skills/
│       ├── base/                  # conversation, observation, reasoning
│       └── personalized/          # deduction, interrogation (loaded per NPC)
├── docs/                          # Guides and explanations
├── scripts/
│   └── run_midnight_train_demo.py # Full pipeline demo
├── src/annie/
│   ├── npc/
│   │   ├── agent.py               # NPCAgent — top-level LangGraph orchestrator
│   │   ├── planner.py             # Decomposes events into tasks
│   │   ├── executor.py            # Invokes sub-agents, logs social events
│   │   ├── reflector.py           # Updates memory, applies graph deltas
│   │   ├── cognitive/             # Motivation, belief, emotion, decision
│   │   ├── memory/                # Episodic, semantic, relationship memory
│   │   ├── sub_agents/            # Memory, social, skill, tool sub-agents
│   │   └── tools/                 # PDF/DOCX/image readers, item/location tools
│   ├── social_graph/
│   │   ├── graph.py               # SocialGraph (NetworkX DiGraph)
│   │   ├── event_log.py           # Append-only social event store
│   │   ├── propagation.py         # BFS gossip propagation with trust filtering
│   │   └── perception/            # 3-stage perception pipeline
│   └── world_engine/
│       ├── world_engine_agent.py  # WorldEngineAgent — Game Master
│       ├── clue_manager.py        # Clue discovery tracking
│       └── game_master/           # Phase control, turn management, rule enforcement
├── tests/                         # 286 unit tests
└── web/
    ├── backend/                   # FastAPI + SSE real-time event bridge
    └── frontend/                  # Next.js 16 + Tailwind + D3 social graph viz
```

---

## Configuration

`config/model_config.yaml`:

```yaml
model:
  provider: deepseek
  model_name: deepseek-chat
  base_url: https://api.deepseek.com
  api_key_env: DEEPSEEK_API_KEY
  temperature: 0.7

embedding:
  provider: local
  model: BAAI/bge-m3        # runs locally, no API key needed

memory:
  vector_store: chromadb
  persist_directory: ./data/vector_store

world:
  tick_interval_seconds: 1
  default_time_scale: 1.0
```

To use a different OpenAI-compatible provider (e.g. OpenAI, Qwen, Ollama), change `base_url`, `model_name`, and the `api_key_env` variable name.

---

## Running Tests

```bash
# All tests (286 total)
pytest

# Single file
pytest tests/test_npc/test_agent.py

# Skip integration tests that call the LLM API
pytest -m "not integration"

# Lint
ruff check src/
ruff format src/
```

---

## Roadmap

| Phase | Status | Description |
|---|---|---|
| Phase 1 | Done | Single NPC agent — LangGraph workflow, two-tier skill system, 4 sub-agents |
| Phase 2 | Done | Multi-NPC — Social Graph, information asymmetry, perception pipeline |
| Phase 3 | Done | 剧本杀 Demo — World Engine as Game Master, cognitive layer, web UI |
| Phase 4 | Planned | Emergent storytelling + narrative control |

---

## Tech Stack

**Backend**
- [LangGraph](https://github.com/langchain-ai/langgraph) — agent workflow orchestration
- [LangChain](https://github.com/langchain-ai/langchain) — LLM abstraction layer
- [ChromaDB](https://www.trychroma.com/) — vector memory store
- [NetworkX](https://networkx.org/) — social relationship graph
- [EasyOCR](https://github.com/JaidedAI/EasyOCR) — script image parsing
- [FastAPI](https://fastapi.tiangolo.com/) — real-time SSE game API

**Frontend**
- [Next.js 16](https://nextjs.org/) + React 19
- [Tailwind CSS](https://tailwindcss.com/) + shadcn/ui
- [D3.js](https://d3js.org/) — social graph visualization
- [Framer Motion](https://www.framer.com/motion/) — animations
- [Zustand](https://github.com/pmndrs/zustand) — state management

---

## Contributing

1. Fork the repo and create a feature branch
2. Run `pytest` and `ruff check src/` before opening a PR
3. Keep new components in the correct layer — NPC Agent, Social Graph, or World Engine
4. Never hardcode model names; always read from `config/model_config.yaml`

---

<p align="center">Built with LangGraph · DeepSeek · ChromaDB</p>
