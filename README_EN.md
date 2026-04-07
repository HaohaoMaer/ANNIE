[中文](./README.md) | **English**

# ANNIE — AI NPC Narrative Simulation Engine

**ANNIE** is a LangGraph-powered multi-agent framework for building intelligent NPCs with persistent memory, dynamic social relationships, and autonomous behavior. It is a **simulation engine**, not a chatbot — each NPC is an independent agent that perceives the world, forms beliefs, feels emotions, and acts from its own motivations.

> **Live Demo: 午夜列车 (Midnight Train)** — A fully automated murder mystery where 6 AI-driven NPCs interrogate each other, reason about evidence, and vote on a verdict. Every run produces a unique story.

---

![ANNIE Web UI](docs/assets/main.png)

---

## Table of Contents

- [Why ANNIE](#why-annie)
- [Features](#features)
- [Architecture](#architecture)
- [How an NPC Thinks](#how-an-npc-thinks)
- [Social Graph & Information Asymmetry](#social-graph--information-asymmetry)
- [Demo — 午夜列车](#demo--午夜列车-midnight-train)
- [Quick Start](#quick-start)
- [Project Structure](#project-structure)
- [Configuration](#configuration)
- [Running Tests](#running-tests)
- [Roadmap](#roadmap)
- [Contributing](#contributing)

---

## Why ANNIE

Most "AI NPC" projects are wrappers around a single LLM prompt. ANNIE takes a different approach:

| Typical AI NPC | ANNIE |
|---|---|
| Single prompt → single response | Full LangGraph agent: Plan → Execute → Reflect |
| No memory between sessions | ChromaDB-backed episodic + semantic memory |
| All NPCs share the same world view | Each NPC has a private subjective perception |
| Relationships are static strings | Live social graph with trust-based gossip propagation |
| No internal state | Cognitive layer: motivation, belief, emotion, decision |
| Hard-coded behavior | File-based skill system, loaded per character |

The result is NPCs that can surprise you — they lie, form alliances, change their minds, and occasionally say things that contradict what they believe.

---

## Features

| Feature | Description |
|---|---|
| **Autonomous NPC Agents** | Each NPC runs its own LangGraph `StateGraph` (Plan → Execute → Reflect) in isolation |
| **Cognitive Layer** | Four interacting subsystems per NPC: `MotivationEngine`, `BeliefSystem`, `EmotionalStateManager`, `DecisionMaker` |
| **Social Graph** | NetworkX DiGraph storing objective relationship truth; NPCs never own this data directly |
| **Information Asymmetry** | 3-stage Perception Pipeline transforms graph truth into each NPC's subjective worldview |
| **Gossip Propagation** | BFS-based event spreading with trust thresholds, visibility rules, and automatic distortion prefixes |
| **Persistent Memory** | ChromaDB-backed episodic (timestamped events) and semantic (facts) memory, retrieved as compressed summaries |
| **Two-tier Skill System** | Base skills loaded for every NPC; personalized skills loaded per character YAML definition |
| **World Engine / Game Master** | Reads script files via OCR, summarizes characters, controls game phases, tallies votes |
| **Resume Support** | Interrupted games persist in backend memory; reconnecting frontend replays full event history and continues live |
| **Real-time Web UI** | Next.js + FastAPI/SSE: live dialogue stream, social graph visualization, clue board |

---

## Architecture

ANNIE is built on three strictly decoupled layers. Data flows one way: World Engine orchestrates NPCs, NPCs query the Social Graph, never the reverse.

```
┌──────────────────────────────────────────────────────────────────┐
│                      Layer 3: World Engine                        │
│                    (Director / Game Master)                       │
│                                                                   │
│   WorldEngineAgent  ·  GameMaster  ·  ClueManager                │
│   ScriptParser  ·  PhaseController  ·  TurnManager               │
│                                                                   │
│   Reads: PDF / DOCX / images (OCR)                               │
│   Controls: game phases, NPC turn order, vote counting           │
└──────────────────────────┬───────────────────────────────────────┘
                           │  spawns & orchestrates
         ┌─────────────────┼─────────────────┐
         ▼                 ▼                 ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Layer 1: NPC Agent Layer                      │
│                                                                  │
│  ┌──────────────────────────────────────────────────────────┐   │
│  │  NPCAgent  (LangGraph StateGraph)                         │   │
│  │                                                           │   │
│  │   START → Planner → Executor → Reflector → END           │   │
│  │                                                           │   │
│  │   Cognitive Layer            Sub-Agents                  │   │
│  │   ├─ MotivationEngine        ├─ MemoryAgent              │   │
│  │   ├─ BeliefSystem            ├─ SocialAgent              │   │
│  │   ├─ EmotionalStateManager   ├─ SkillAgent               │   │
│  │   └─ DecisionMaker           └─ ToolAgent                │   │
│  │                                                           │   │
│  │   Memory                     Skills                      │   │
│  │   ├─ EpisodicMemory          ├─ conversation             │   │
│  │   ├─ SemanticMemory          ├─ observation / reasoning  │   │
│  │   └─ RelationshipMemory      └─ deduction / interrogation│   │
│  └──────────────────────────────────────────────────────────┘   │
└──────────────────────────┬──────────────────────────────────────┘
                           │  queries & applies deltas
┌──────────────────────────▼──────────────────────────────────────┐
│                   Layer 2: Social Graph Layer                    │
│                    (Objective Relationship Truth)                │
│                                                                  │
│   SocialGraph (NetworkX)  ·  SocialEventLog  ·  PropagationEngine│
│                                                                  │
│   Perception Pipeline (read-only for NPCs):                     │
│   KnowledgeFilter (L1) → BeliefEvaluator (L2) →                │
│   PerceptionBuilder (L3) → EnrichedRelationshipDef              │
└─────────────────────────────────────────────────────────────────┘
```

### Key Design Principles

- **NPCs perceive, they do not own.** World state lives in World Engine; relationship truth lives in Social Graph. An NPC's "view" is always derived, never authoritative.
- **Information asymmetry by design.** L1 filters what an NPC knows, L2 decides how much they believe it, L3 assembles their complete worldview. The same event can look completely different to two NPCs.
- **Opt-in integration.** All Phase 2/3 components wire in via optional constructor params — `social_graph=None` gives you the clean Phase 1 single-NPC behavior.
- **Context compression.** Memory is stored in ChromaDB and injected as compressed summaries, not raw history, keeping token costs bounded across long games.

---

## How an NPC Thinks

Every time the World Engine calls an NPC, the following sequence runs inside a single LangGraph tick:

```
Event arrives (e.g. "林乘客 accused you of lying")
        │
        ▼
EmotionalStateManager.update_from_event()
   → keyword scan → update primary emotion + intensity
        │
        ▼
MotivationEngine.generate_motivations()
   → goal + event + relationship + script → ranked motivation list
        │
        ▼
Planner  (LLM call)
   → decomposes event into Task list  e.g. [gather_info, respond, update_beliefs]
        │
        ▼
Executor  (per task)
   ├─ MemoryAgent  → retrieve episodic + semantic + relationship context
   ├─ SocialAgent  → build social context from Perception Pipeline
   ├─ SkillAgent   → select & invoke skill (deduction / interrogation / …)
   ├─ ToolAgent    → invoke tools (item inspection, location search, …)
   └─ LLM call     → generate 【内心活动】 + 【说的话】 [+ 【投票】]
        │
        ▼
Reflector  (LLM call)
   → generate reflection → store EpisodicMemory + SemanticMemory
   → parse RELATIONSHIP_UPDATES → apply GraphDeltas to SocialGraph
```

The split between `【内心活动】` (private) and `【说的话】` (public) is enforced at the prompt level — an NPC's stated position can deliberately contradict its inner reasoning.

---

## Social Graph & Information Asymmetry

The Social Graph stores multi-dimensional relationship edges:

```
trust · familiarity · emotional_valence · intensity · status
```

When NPC **A** tries to learn about the relationship between **B** and **C**, the Perception Pipeline transforms objective graph truth into A's subjective view:

```
SocialGraph (god's eye)
        │
        ▼  L1: KnowledgeFilter
   "What does A actually know?"
   → filter by EventVisibility (PUBLIC / WITNESSED / PRIVATE / SECRET)
        │
        ▼  L2: BeliefEvaluator
   "Does A believe it?"
   → source trust → credibility bracket → BeliefStatus
     (ACCEPTED / SKEPTICAL / DOUBTED / REJECTED)
   → conflict detection (opposing sentiment about same person)
        │
        ▼  L3: PerceptionBuilder
   "What's A's complete worldview?"
   → EnrichedRelationshipDef list + perceived events
   → build_social_context() string injected into NPC prompt
```

Gossip propagation uses BFS with:
- Relationship-type willingness (trusted ally = 0.9 → enemy = 0.1)
- Visibility rules (PUBLIC → all; WITNESSED → BFS reach; SECRET → needs trust ≥ 0.7)
- Automatic distortion prefixes (`"Reportedly, …"` / `"Rumor has it that …"`) for hostile-path propagation

---

## Demo — 午夜列车 (Midnight Train)

A complete murder mystery powered by a commercial 剧本杀 script. Six AI characters — a detective, a flight attendant, and four passengers — are locked on a trans-Siberian train with a dead body.

![Game In Progress](docs/assets/game.png)

### What the pipeline does

1. **OCR** — reads 6 character PDFs + 57 clue images (EasyOCR + PyTorch, fallback to pypdf)
2. **Summarize** — LLM condenses each character PDF into a structured JSON profile (identity, background, secrets, goals, `murderer: true/false`)
3. **Initialize** — builds one `NPCAgent` per character, each seeded with their private script knowledge and a fresh `EphemeralClient` ChromaDB
4. **Game loop** — World Engine cycles through phases, calling each NPC in turn order:
   - `自由交流` (free discussion)
   - `深度推理` (deep deduction)
   - `投票指控` (vote & accuse)
5. **Results** — `Counter` tallies votes, compares against real murderer, Game Master LLM narrates the reveal

### NPC output format (every turn)

```
【内心活动】  private reasoning — drawn from secret script, never shown to other NPCs
【说的话】    public speech — strategic, may contradict inner thoughts
【投票】      voting phase only — constrained to named NPC list
```

### Running the Demo

**Terminal mode** (no UI, fastest):
```bash
python scripts/run_midnight_train_demo.py
```

**Web UI mode** (live visualization):
```bash
# Terminal 1 — Backend (FastAPI + SSE)
uvicorn web.backend.main:app --host 0.0.0.0 --port 8000 --reload

# Terminal 2 — Frontend (Next.js)
cd web/frontend
npm install
npm run dev
# Open http://localhost:3000
```

If the browser tab is refreshed mid-game, clicking Live will detect the in-progress session and offer to resume from where it left off.

> **Note:** The `午夜列车/` script folder is not included in the repository (copyrighted commercial content). Place your own 剧本杀 script folder at the repo root and update `SCRIPT_FOLDER` in `web/backend/main.py`.

---

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+ (web UI only)
- A [DeepSeek API key](https://platform.deepseek.com/) — or any OpenAI-compatible endpoint (OpenAI, Qwen, Ollama, etc.)

### Install

```bash
git clone https://github.com/HaohaoMaer/ANNIE.git
cd ANNIE

# Create environment
conda create -n annie python=3.11 && conda activate annie
# or: python -m venv .venv && source .venv/bin/activate

# Install (editable, includes dev tools)
pip install -e ".[dev]"
```

### Configure

```bash
cp .env.example .env
# Set your API key:
# DEEPSEEK_API_KEY=your_key_here
```

Model, embedding, and memory settings are in `config/model_config.yaml` — see [Configuration](#configuration).

### Run your first NPC

```python
from annie.npc.agent import NPCAgent
from annie.npc.config import load_model_config
from annie.npc.state import load_npc_profile

config = load_model_config("config/model_config.yaml")
profile = load_npc_profile("data/npcs/example_npc.yaml")
agent = NPCAgent(profile=profile, config=config)

result = agent.run("A stranger approaches you at the market.")
print(result.action)
```

---

## Project Structure

```
ANNIE/
├── config/
│   └── model_config.yaml              # Model provider, embeddings, memory backend
├── data/
│   ├── npcs/
│   │   └── example_npc.yaml           # Minimal NPC definition for testing
│   └── skills/
│       ├── base/                      # conversation, observation, reasoning
│       │   └── <skill>/               # description.md · script.py · prompt.j2
│       └── personalized/              # deduction, interrogation (loaded per NPC)
├── docs/                              # Guides, explanations, screenshots
├── scripts/
│   └── run_midnight_train_demo.py     # Full pipeline demo (terminal)
├── src/annie/
│   ├── npc/
│   │   ├── agent.py                   # NPCAgent — top-level orchestrator
│   │   ├── planner.py                 # Event → Task list (LLM)
│   │   ├── executor.py                # Task execution, social event logging
│   │   ├── reflector.py               # Post-execution memory + graph updates
│   │   ├── cognitive/                 # MotivationEngine, BeliefSystem,
│   │   │                              # EmotionalStateManager, DecisionMaker
│   │   ├── memory/                    # EpisodicMemory, SemanticMemory,
│   │   │                              # RelationshipMemory (ChromaDB)
│   │   ├── sub_agents/                # MemoryAgent, SocialAgent,
│   │   │                              # SkillAgent, ToolAgent
│   │   └── tools/                     # PDF/DOCX/image readers,
│   │                                  # item inspection, location search
│   ├── social_graph/
│   │   ├── graph.py                   # SocialGraph (NetworkX DiGraph)
│   │   ├── event_log.py               # Append-only social event store
│   │   ├── propagation.py             # BFS gossip with trust filtering
│   │   └── perception/                # 3-stage perception pipeline (L1/L2/L3)
│   └── world_engine/
│       ├── world_engine_agent.py      # WorldEngineAgent — Game Master
│       ├── clue_manager.py            # Clue discovery tracking
│       └── game_master/               # PhaseController, TurnManager,
│                                      # RuleEnforcer, ScriptProgression
├── tests/                             # 286 unit tests
└── web/
    ├── backend/                       # FastAPI + SSE real-time event bridge
    └── frontend/                      # Next.js 16 · Tailwind · D3 · shadcn/ui
```

---

## Configuration

`config/model_config.yaml`:

```yaml
model:
  provider: deepseek
  model_name: deepseek-chat
  base_url: https://api.deepseek.com
  api_key_env: DEEPSEEK_API_KEY   # name of the env var holding your key
  temperature: 0.7

embedding:
  provider: local
  model: BAAI/bge-m3              # runs fully locally, no API key needed

memory:
  vector_store: chromadb
  persist_directory: ./data/vector_store

world:
  tick_interval_seconds: 1
  default_time_scale: 1.0
```

**Switching providers** — change `base_url` + `model_name` + `api_key_env` and set the corresponding env var:

| Provider | `base_url` | `model_name` example |
|---|---|---|
| DeepSeek | `https://api.deepseek.com` | `deepseek-chat` |
| OpenAI | `https://api.openai.com/v1` | `gpt-4o` |
| Ollama (local) | `http://localhost:11434/v1` | `qwen2.5:14b` |

---

## Running Tests

```bash
# All 286 tests
pytest

# Single module
pytest tests/test_npc/test_agent.py

# Skip tests that require a live LLM API
pytest -m "not integration"

# Lint and format
ruff check src/
ruff format src/
```

Tests use `chromadb.EphemeralClient()` with unique collection names per test — no cross-test memory pollution, no files written to disk.

---

## Roadmap

| Phase | Status | Description |
|---|---|---|
| Phase 1 | ✅ Done | Single NPC agent — LangGraph workflow, two-tier skill system, 4 sub-agents, 165 tests |
| Phase 2 | ✅ Done | Multi-NPC — Social Graph, information asymmetry, 3-stage perception pipeline, 121 new tests |
| Phase 3 | ✅ Done | 剧本杀 Demo — World Engine as Game Master, cognitive layer, web UI, resume support |
| Phase 4 | Planned | Emergent storytelling, narrative control, personality-driven perception bias |

---

## Tech Stack

**Core engine**
- [LangGraph](https://github.com/langchain-ai/langgraph) `≥0.2` — agent workflow (`StateGraph`)
- [LangChain](https://github.com/langchain-ai/langchain) `≥0.3` — LLM abstraction, prompt templates
- [ChromaDB](https://www.trychroma.com/) `≥0.5` — vector memory store
- [NetworkX](https://networkx.org/) `≥3.3` — social relationship graph
- [Pydantic](https://docs.pydantic.dev/) `≥2.7` — data validation throughout
- [EasyOCR](https://github.com/JaidedAI/EasyOCR) `≥1.7` — script image and PDF parsing

**Web layer**
- [FastAPI](https://fastapi.tiangolo.com/) — REST + SSE real-time event stream
- [Next.js 16](https://nextjs.org/) + React 19 — frontend framework
- [Tailwind CSS](https://tailwindcss.com/) + [shadcn/ui](https://ui.shadcn.com/) — UI components
- [D3.js](https://d3js.org/) `v7` — live social graph visualization
- [Framer Motion](https://www.framer.com/motion/) — dialogue animations
- [Zustand](https://github.com/pmndrs/zustand) `v5` — frontend state management

---

## Contributing

1. Fork the repo and create a feature branch off `main`
2. Keep components in the correct layer — NPC Agent, Social Graph, or World Engine. Cross-layer dependencies go downward only.
3. Never hardcode model names in source — always read from `config/model_config.yaml`
4. Run `pytest` and `ruff check src/` before opening a PR
5. Integration tests (marked `@pytest.mark.integration`) require a real API key and are skipped in CI by default

---

<p align="center">Built with LangGraph · DeepSeek · ChromaDB · NetworkX</p>
