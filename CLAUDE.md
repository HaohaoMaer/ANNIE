# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project

ANNIE is a **LangGraph-based multi-agent narrative simulation engine** for generating intelligent NPCs with persistent memory, dynamic social relationships, and autonomous behavior. It is a simulation engine — not a chatbot.

## Commands

```bash
# Install (editable)
pip install -e ".[dev]"

# Run tests
pytest

# Run a single test file
pytest tests/test_npc/test_agent.py

# Lint
ruff check src/
ruff format src/
```

## Architecture

Three decoupled layers:

### Layer 1: NPC Agent Layer (`src/annie/npc/`)
Each NPC is a complete, independent Agent system built on LangGraph. Everything an NPC needs is contained within this layer.

**Core workflow** — three LangGraph nodes:
- **Planner** → decomposes incoming events into tasks
- **Executor** → invokes sub-agents and tools to act
- **Reflector** → updates memory after execution

**Sub-agents** (`npc/sub_agents/`) — invoked by the Executor as needed: `MemoryAgent`, `SocialAgent`, `SkillAgent`, `ToolAgent`.

**Memory system** (`npc/memory/`) — three memory types per NPC:
- `EpisodicMemory` — timestamped events
- `SemanticMemory` — world knowledge and facts
- `RelationshipMemory` — subjective perception of others (derived from Social Graph)

Long-term memory is persisted to a vector store (ChromaDB). Context is passed as compressed summaries, not raw history.

**Skill system** (`npc/skills/`, `data/skills/`) — skills are loaded on demand to avoid context overload. Each skill lives in `data/skills/<skill_name>/` with three files: `description.md`, `script.py`, `prompt.j2`.

**Tools** (`npc/tools/`) — external APIs, file system, game interfaces.

### Layer 2: Social Graph Layer (`src/annie/social_graph/`)
**Global truth** for all inter-NPC relationships. NPCs query this layer — they never own relationship state directly.
- `SocialGraph` — nodes (NPCs) + edges (type, intensity 0–1, status)
- `SocialEventLog` — append-only event sourcing (Actor → Target → Action)
- `PropagationEngine` — gossip propagation with trust filtering and time delay

### Layer 3: World Engine Layer (`src/annie/world_engine/`)
Acts as the world "Director":
- `TimeSystem` — tick-based clock, day/night cycles
- `EventScheduler` — timed events, conditional triggers, NPC action queue
- `SceneManager` — locations, environment state, NPC positions
- `NarrativeController` — injects conflicts, controls pacing, triggers key events

### Configuration (`config/model_config.yaml`)
Model provider, embedding model, memory backend, and world tick settings. Do not hardcode model names in source — always read from config.

## Key Design Constraints
- NPCs **perceive** the world; they do not own it. World state lives in World Engine and Social Graph.
- Social relationships are **externalized** — the Social Graph is the single source of truth.
- NPC initialization uses structured YAML character definitions (`data/npcs/`), not single prompts.
- Context is **compressed and persisted** between ticks — never kept raw in the prompt.
