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

Long-term memory backed by ChromaDB. **In the demo/WorldEngineAgent context, always use `EphemeralClient` (passed via `chroma_client=`) to avoid cross-game memory pollution.** Context is passed as compressed summaries, not raw history.

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

## Implementation Progress

### Phase 1 (MVP) — Completed
Single NPC with full LangGraph agent workflow, two-tier skill/tool system, and all four sub-agents. 165 unit tests passing.

**Implemented modules (`src/annie/npc/`):**
- `agent.py` — `NPCAgent`: top-level orchestrator, builds `StateGraph(START → planner → executor → reflector → END)`, wires SkillRegistry, ToolRegistry, and all sub-agents, exposes `run(event) -> AgentRunResult`
- `config.py` — `ModelConfig` + `load_model_config()`: reads `config/model_config.yaml`, resolves API key from env
- `state.py` — `NPCProfile` (with `skills`/`tools` fields), `Task`, `AgentState(TypedDict)`, `load_npc_profile()`: shared data types for all components
- `tracing.py` — `Tracer`, `TraceEvent`, `EventType` (includes `TOOL_INVOKE`), `TraceFormatter`: structured execution tracing with `node_span()` context manager, console/JSON output
- `llm.py` — `create_chat_model()`, `create_embeddings()`: thin factory using `ChatOpenAI` (DeepSeek-compatible) and `HuggingFaceEmbeddings`
- `planner.py` — `Planner`: prompts LLM to decompose events into `Task` list (JSON parsing with markdown code block handling)
- `executor.py` — `Executor`: iterates tasks, queries `MemoryAgent` for context, invokes `SkillAgent` and `ToolAgent`, generates actions via LLM
- `reflector.py` — `Reflector`: generates reflection from execution results, stores episodic + semantic memories
- `memory/episodic.py` — `EpisodicMemory`: ChromaDB-backed timestamped event storage with similarity search
- `memory/semantic.py` — `SemanticMemory`: ChromaDB-backed fact storage with category filtering
- `memory/relationship.py` — `RelationshipMemory`: Phase 1 in-memory dict or Phase 2 delegates to PerceptionBuilder when `perception_builder` param is set
- `skills/base_skill.py` — `BaseSkill` + `SkillRegistry`: two-tier loading (base skills from `data/skills/base/` always loaded, personalized skills from `data/skills/personalized/` loaded per NPC YAML `skills` field)
- `tools/base_tool.py` — `BaseTool(ABC)`: abstract interface for all NPC tools
- `tools/tool_registry.py` — `ToolRegistry`: programmatic base + personalized tool registration
- `tools/perception.py` — `PerceptionTool`: heuristic entity/environment/threat parser (base tool)
- `tools/memory_query.py` — `MemoryQueryTool`: wraps MemoryAgent for targeted queries (base tool, dependency injected via `set_memory_agent()`)
- `sub_agents/memory_agent.py` — `MemoryAgent`: aggregates episodic/semantic/relationship into unified context string
- `sub_agents/skill_agent.py` — `SkillAgent`: selects and invokes skills via improved keyword matching (stop-word filtering)
- `sub_agents/tool_agent.py` — `ToolAgent`: selects and invokes tools via keyword matching
- `sub_agents/social_agent.py` — `SocialAgent`: Phase 1 wraps RelationshipMemory; Phase 2 delegates to PerceptionBuilder for full social context with events + belief status

**Skill/Tool architecture:**
- **Base skills** (`data/skills/base/`): conversation, observation, reasoning — loaded for every NPC
- **Personalized skills** (`data/skills/personalized/`): negotiation, storytelling — loaded per NPC YAML
- **Base tools**: PerceptionTool, MemoryQueryTool — registered for every NPC
- **Personalized tools**: extensible via `_PERSONALIZED_TOOL_CLASSES` mapping in `tool_registry.py`

**Data files:**
- `data/npcs/village_elder.yaml` — full NPC definition with personality, background, goals, relationships, memory seeds, skills (negotiation, storytelling)
- `data/npcs/example_npc.yaml` — minimal NPC for testing
- `data/skills/base/` — conversation, observation, reasoning skills
- `data/skills/personalized/` — negotiation, storytelling skills
- `data/skills/example_skill/` — template skill for reference/testing

**Demo:** `python scripts/run_demo.py` — runs Village Elder through 3 events with colored trace output

**Key technical decisions:**
- ChromaDB collection names are sanitized via `_sanitize_collection_name()` (spaces/special chars → underscores)
- `AgentState.tracer` typed as `Any` to avoid circular import issues with LangGraph's runtime `get_type_hints()`
- Tracing uses explicit `Tracer` object (not LangGraph callbacks) for domain-aware, version-stable events
- Tests use `chromadb.EphemeralClient()` with unique collection names per test to avoid cross-test pollution
- Skills are file-based (description.md/script.py/prompt.j2), tools are class-based (ABC with programmatic registration)
- SkillRegistry falls back to flat-directory loading when `base/` subdir is absent (backward compat)

### Phase 2 (Multi-NPC + Social Graph) — Completed
Multiple NPCs with information asymmetry via Social Graph layer. 121 new tests (286 total passing).

**Social Graph layer (`src/annie/social_graph/`):**
- `models.py` — `RelationshipEdge` (multi-dimensional: trust/familiarity/emotional_valence/intensity/status), `SocialEvent` (with `EventVisibility`: PUBLIC/WITNESSED/PRIVATE/SECRET), `KnowledgeItem` (with `BeliefStatus`: ACCEPTED/SKEPTICAL/DOUBTED/REJECTED + credibility score + conflicting_with), `GraphDelta`
- `graph.py` — `SocialGraph`: NetworkX DiGraph storing god's-eye truth. CRUD for nodes/edges, `apply_deltas()` with clamping, knowledge tracking. No subjective transformation.
- `event_log.py` — `SocialEventLog`: append-only event store with query by actor/target/timerange/visibility
- `propagation.py` — `PropagationEngine`: BFS information spreading with two semantic-filtering dimensions:
  - Relationship-type willingness (trusted_ally=0.9 → enemy=0.1, hostile types add +0.3 distortion)
  - Event visibility rules (PUBLIC→all, WITNESSED→BFS, PRIVATE→principals only, SECRET→gossip needs trust≥0.7)
  - `propagate_event()`, `propagate_gossip()`, `tick()` methods. Personality dimension deferred to Phase 3.

**Perception Pipeline (`src/annie/social_graph/perception/`) — three-stage debuggable pipeline:**
- `knowledge_filter.py` — `KnowledgeFilter` (L1): "What does this NPC know?" Pure data filtering from graph's knowledge store.
- `belief_evaluator.py` — `BeliefEvaluator` (L2): "Does the NPC believe it?" Source trust → credibility brackets, conflict detection (opposing sentiment keywords about same person), final belief_status assignment.
- `perception_builder.py` — `PerceptionBuilder` (L3): "What's the NPC's worldview?" Assembles filtered+evaluated data into `EnrichedRelationshipDef` list + perceived events + `build_social_context()` string for NPC Agent.

**NPC layer integration (backward-compatible, all new params default to None):**
- `agent.py` — `NPCAgent` accepts optional `social_graph` and `event_log`; builds Perception Pipeline internally, seeds YAML relationships into SocialGraph
- `executor.py` — `Executor` accepts optional `event_log`; auto-logs `SocialEvent` when actions mention other NPCs
- `reflector.py` — `Reflector` accepts optional `social_graph`; parses `RELATIONSHIP_UPDATES` from LLM response and applies `GraphDelta`s
- `state.py` — added `EnrichedRelationshipDef(RelationshipDef)` subclass with trust/familiarity/emotional_valence/status

**New NPC definitions:**
- `data/npcs/blacksmith_gareth.yaml` — bold/proud/direct/stubborn, rival with Carpenter
- `data/npcs/merchant_lina.yaml` — shrewd/social/observant/cautious, information trader

**Demo:** `python scripts/run_phase2_demo.py` — 3 NPCs with preset events, trigger event, per-NPC processing, god's-eye vs subjective view comparison

**Key technical decisions:**
- SocialGraph stores only objective truth; subjective transformation is entirely in Perception Pipeline
- Perception Pipeline is split into 3 independent stages for debuggability (each stage has clear input/output, can be inspected independently)
- Personality-based perception bias deferred to Phase 3 to keep Phase 2 scope focused on information asymmetry
- All integration is opt-in via optional constructor params; Phase 1 code path unchanged when social_graph=None
- Propagation uses deterministic rules (not LLM calls) for distortion — adds prefixes like "Reportedly, " / "Rumor has it that "

### Phase 3 (剧本杀Demo — 午夜列车) — Completed
Murder mystery demo using "午夜列车" commercial script. 286 tests passing.

**剧本目录结构 (`午夜列车/`):**
- `人物剧本/*.pdf` — 6 character PDFs (何侦探, 撒乘客, 林乘客, 白乘客, 董乘客, 鸥乘务)
- `线索/*/` — 57 clue images (OCR via EasyOCR+PyTorch)
- `背景.docx`, `游戏流程.docx`, `真相.pdf`

**World Engine as Game Master (`src/annie/world_engine/`):**
- `world_engine_agent.py` — `WorldEngineAgent`: reads all script files, LLM-summarizes each character PDF into structured JSON, generates game phases, initializes NPCs, runs game loop with phase control and vote counting
  - `_read_character_scripts()` — OCR → fallback to standard PDF reader if content < 100 chars
  - `_summarize_character_scripts()` — full script → LLM → JSON with identity/background/secrets/goals/murderer fields; validates completeness and retries
  - `_extract_npc_profile()` — parses summary JSON directly into NPCProfile (skips extra LLM call)
  - `build_npc_context()` — injects current-phase dialogue history so NPCs hear what others said
  - `_find_real_murderer()` — scans `character_summaries` for `"murderer": true`
  - `_announce_final_results()` — deterministic `Counter` vote tallying → compare vs real murderer → LLM narrates result
  - `advance_phase()` — resets `TurnManager` on each phase transition
  - Uses `chromadb.EphemeralClient()` shared across all NPCs for clean per-game memory
- `game_master/game_master.py` — `should_advance_phase()` respects `_min_rounds_per_phase` (default 1)
- `clue_manager.py` — tracks clue discovery by NPC and phase

**Cognitive Layer (`src/annie/npc/cognitive/`) — now integrated:**
- `motivation.py` — `MotivationEngine`: goal/event/relationship/script-driven motivations with intensity prioritization
- `belief_system.py` — `BeliefSystem`: confidence-tracked beliefs with contradiction detection
- `emotional_state.py` — `EmotionalStateManager`: keyword-based emotion updates (Chinese + English), decay, profile initialization
- `decision_maker.py` — `DecisionMaker`: scores options by motivation(40%) + feasibility(30%) + emotional(20%) + belief(10%)
- All four components instantiated in `NPCAgent.__init__()` and wired to `Executor`
- `NPCAgent.run()` calls `emotional_state_manager.update_from_event()` and `motivation_engine.generate_motivations()` before each graph invocation

**Executor updates (`src/annie/npc/executor.py`):**
- Both `EXECUTOR_SYSTEM_PROMPT` and `VOTING_SYSTEM_PROMPT` are Chinese; non-voting prompt now includes `{script_summary}`, `{motivations}`, `{emotional_state}`
- `VOTING_SYSTEM_PROMPT` includes `{voteable_names}` list to constrain vote targets
- `set_script_summary()` method — sets summary independently of voting phase
- Vote parsing: exact match → substring match → surname (first char) match
- `_all_npc_names` back-propagated to all NPCs after `initialize_npcs()` completes

**NPC output format (every turn):**
- `【内心活动】` — private reasoning from script/secrets/motivations (not shown to others)
- `【说的话】` — strategic public speech (may differ from inner thoughts)
- `【投票】` — voting phase only; constrained to named NPC list

**New tools (`src/annie/npc/tools/`):**
- `pdf_reader.py` — text-based PDF extraction (pypdf)
- `pdf_ocr.py` — OCR PDF extraction (EasyOCR + pdf2image/fitz fallbacks), lazy-loads reader
- `docx_reader.py` — DOCX extraction, structured or plain text
- `image_reader.py` — single image or batch folder OCR (EasyOCR)
- `item_inspection.py` — inspect game-world items via injected item registry
- `location_search.py` — search game-world locations via injected location registry

**Script parsing (`src/annie/script_parser/`):**
- `models.py` — `CharacterInfo`, `Phase`, `PlotPoint`, `ScriptedEvent`, `Clue`, `Ending`, `ParsedScript`
- `pdf_parser.py` — `ScriptPDFParser`: section detection (背景/人物/剧本/线索/结局), character/personality/goals/secrets extraction via regex

**Personalized skills (`data/skills/personalized/`):**
- `interrogation/` — Chinese; target NPC + known info → focused questions + contradiction analysis
- `deduction/` — Chinese; clues list → reasoning steps + conclusion + confidence score

**Key technical decisions:**
- `WorldEngineAgent` uses `chromadb.EphemeralClient()` — prevents cross-game memory leakage (stale votes/reflections from prior runs cause NPCs to act as if already in voting phase)
- `GAME_MASTER_SYSTEM_PROMPT` used as `SystemMessage` for all WE LLM calls to maintain GM persona
- NPC profile built directly from `_summarize_character_scripts()` JSON output — avoids a third LLM round-trip per character
- `should_advance_phase()` uses round-based counting (`_min_rounds_per_phase`) rather than raw turn count
- `dialogue_history` stored on `WorldEngineAgent` and injected into each NPC's context (last 12 entries from current phase)

**Demo:** `python scripts/run_midnight_train_demo.py` — full pipeline: OCR → character summaries → profile validation → game phases → game loop → vote counting → truth reveal

### Phase 4 — Not started
Emergent storytelling + Narrative control.
