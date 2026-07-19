# ANNIE — AI NPC Narrative Simulation Engine

ANNIE is a Python framework for AI-driven NPCs that plan, act, reflect, and
interact within simulated worlds. It provides a reusable, game-agnostic NPC
cognitive layer that plugs into different game engines via three protocols.

**Tech stack:** Python 3.11+ · LangGraph · LangChain · ChromaDB · Pydantic ·
pytest

## Architecture: Strict Two-Layer Split

```
┌──────────────────────────────────────┐
│  Game Engines (business logic)       │
│  src/annie/town/                     │
│  src/annie/war_game/                 │
│  src/annie/interrogation/            │
├──────────────────────────────────────┤
│  World Engine Layer                  │
│  src/annie/world_engine/             │
│  - world state, NPC profiles         │
│  - ChromaDB memory backends          │
│  - JSONL history + compressor        │
│  - business tools (PlanTodo, etc.)   │
├─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─│
│  NPC Agent Layer (game-agnostic)     │
│  src/annie/npc/                      │
│  - stateless cognitive framework     │
│  - 5 cognitive graphs (action,       │
│    dialogue, reflection, json)       │
│  - graph routed by world engine      │
│  - tool-use ReAct loop               │
│  - skill activation system           │
│  - context budget / compression      │
└──────────────────────────────────────┘
```

### Hard Boundaries

**NPC Agent layer (`src/annie/npc/`)** must NOT:
- Import `chromadb`
- Hold world state or parse NPC YAML
- Contain business vocabulary (script, clue, sandbox, EmotionalState, etc.)

**World Engine layer (`src/annie/world_engine/`)** owns all:
- World state and NPC profiles
- Memory backends (ChromaDB)
- History persistence and compression
- Business tools and skill definitions
- Action arbitration and scene progression

### Three Protocols

| Protocol | Direction | Purpose |
|---|---|---|
| `AgentContext` | World Engine → Agent | All per-run data: npc_id, event, tools, skills, memory, prompts, extra |
| `AgentResponse` | Agent → World Engine | Dialogue, actions, memory_updates, reflection, inner_thought |
| `MemoryInterface` | Bidirectional (Protocol) | recall, grep, remember, build_context |

`MemoryInterface` is a `typing.Protocol`, not an ABC — any object with the right
method signatures works, no inheritance needed.

### AgentContext Three-Tier Structure

1. **Typed core:** `npc_id`, `input_event`, `tools`, `skills`, `memory`, `graph_id`, `route`
2. **Prompt text:** `character_prompt`, `world_rules`, `situation`, `history`, `todo` — free-form strings
3. **Extension:** `extra: dict[str, Any]` — open-ended metadata channel

## Source Code Map

```
src/annie/
├── npc/                          # NPC Agent Layer (stateless, game-agnostic)
│   ├── agent.py                  # NPCAgent.run() — main entry point
│   ├── context.py                # AgentContext (three-tier input)
│   ├── response.py               # AgentResponse, ActionRequest, ActionResult, MemoryUpdate
│   ├── state.py                  # AgentState TypedDict, Task, TaskStatus
│   ├── routes.py                 # AgentRoute enum (action/dialogue/structured_json/reflection)
│   ├── graph_registry.py         # 5 cognitive graphs with runner dispatch
│   ├── planner.py                # Planner node — skip-first task decomposition
│   ├── executor.py               # Executor node — tool-use ReAct loop (max 8)
│   ├── reflector.py              # Reflector node — REFLECTION/FACTS/RELATIONSHIP_NOTES
│   ├── prompts.py                # Prompt templates and message builders
│   ├── config.py                 # ModelConfig, LLMConfig, EmbeddingConfig (YAML loader)
│   ├── llm.py                    # create_chat_model(), create_embeddings()
│   ├── context_budget.py         # ContextBudget — emergency context folding
│   ├── tracing.py                # Tracer — per-run node/event observability
│   ├── memory/
│   │   └── interface.py          # MemoryInterface Protocol, MemoryRecord, category constants
│   ├── tools/
│   │   ├── base_tool.py          # ToolDef ABC, ToolContext
│   │   ├── builtin.py            # 7 built-in tools (memory_recall, memory_grep, etc.)
│   │   └── tool_registry.py      # ToolRegistry with frame stack for skill scoping
│   ├── skills/
│   │   ├── base_skill.py         # SkillDef, SkillRegistry
│   │   └── registry.py           # load_dir() — file-system skill loader
│   └── runtime/
│       ├── memory_context.py     # MemoryContextBuilder (thin adapter)
│       ├── skill_runtime.py      # SkillRuntime.activate() — prompt injection + frame push
│       └── tool_dispatcher.py    # ToolDispatcher — dispatch + micro-compression
│
├── world_engine/                 # World Engine Layer (business owner)
│   ├── base.py                   # WorldEngine ABC — build_context, handle_response, drive_npc
│   ├── default_engine.py         # DefaultWorldEngine — minimal concrete implementation
│   ├── memory.py                 # DefaultMemoryInterface — ChromaDB-backed MemoryInterface
│   ├── history.py                # HistoryStore — JSONL-based rolling dialogue history
│   ├── compressor.py             # Compressor — cursor-driven cross-run history folding
│   ├── store.py                  # MemoryStore — ChromaDB collection per NPC
│   ├── profile.py                # NPCProfile, load_npc_profile(), profile_to_character_prompt()
│   ├── tools.py                  # PlanTodoTool, WorldActionTool, render_todo_text()
│   └── chroma_lock.py            # ChromaWriteGuard — thread-safe write serialization
│
├── town/                         # Town Simulation (Generative Agents style)
│   ├── engine.py                 # TownWorldEngine — full spatial/social simulation
│   ├── eventing.py               # NPCRegistry, TownEventBus — event routing
│   ├── prompt_policy.py          # Deterministic decision hints (no LLM calls)
│   ├── domain/
│   │   ├── models.py             # 21 dataclasses (Location, TownEvent, ScheduleSegment, etc.)
│   │   └── state.py              # TownState aggregate
│   ├── content/
│   │   └── small_town.py         # create_small_town_state() — 3 NPC / 8 location fixture
│   ├── tools/
│   │   └── actions.py            # 10 town-specific ToolDefs (move_to, speak_to, etc.)
│   └── runtime/
│       ├── day_runner.py         # run_single_npc_day() — single NPC day harness
│       └── multi_npc_runner.py   # run_multi_npc_day() / run_multi_npc_days()
│
├── war_game/                     # Three-Faction Strategy Game
│   ├── engine.py                 # WarGameEngine — phase-based turn strategy
│   ├── game_state.py             # GameState, City, Faction, Deployment, BattleResult
│   ├── phases.py                 # 5 phase functions + round report
│   ├── combat.py                 # Battle resolution (1v1, 2v1, negotiation standoff)
│   ├── config.py                 # GameConfig (initial forces, production, round limits)
│   ├── prompts.py                # WORLD_RULES, render_situation()
│   ├── tools.py                  # 5 phase-specific ToolDefs
│   ├── map_preset.py             # 15-city symmetric map, create_default_state()
│   ├── cli.py                    # Interactive CLI game runner
│   └── display.py                # Terminal rendering (map, force pools, declarations)
│
├── interrogation/                # Detective Interrogation Game
│   ├── engine.py                 # InterrogationEngine — phases, stress, evidence
│   └── state.py                  # InterrogationState, GamePhase enum
│
└── script_parser/
    └── pdf_parser.py             # PDF script parsing utility
```

## NPCAgent Execution Flow

### Graph Dispatch

`NPCAgent.run(ctx)` resolves which graph to use via `_resolve_graph_id(ctx)`:

| Priority | Source | Example |
|---|---|---|
| 1 | `ctx.graph_id` (explicit) | `AgentGraphID.ACTION_PLAN_EXECUTE` |
| 2 | `ctx.route` (intent-based) | `AgentRoute.DIALOGUE` → `dialogue.memory_then_output` |
| 3 | `ctx.extra["npc_direct_mode"]` | `"reflection"` → `reflection.evidence_to_memory_candidate` |

### Five Cognitive Graphs

| Graph ID | Runner | Behavior |
|---|---|---|
| `action.executor_default` | `action` | Executor-first, Planner on retry only |
| `action.plan_execute` | `action` | Planner always runs first |
| `dialogue.memory_then_output` | `dialogue` | Memory recall + 2-tool-loop dialogue output |
| `output.structured_json` | `structured_json` | Single LLM call → JSON |
| `reflection.evidence_to_memory_candidate` | `reflection` | Single LLM call → reflection text |

### Action Graph Detail (one of five cognitive graphs)

The two action graphs (`executor_default` and `plan_execute`) are the only
graphs that compose Planner + Executor + Reflector nodes. The other three
graphs (dialogue, structured_json, reflection) use different, simpler node
compositions and never touch Planner or Reflector.

```
WorldEngine.build_context(npc_id, event)
  │
  ▼
NPCAgent.run(ctx):
  ├─ MemoryContextBuilder.build_context → working_memory (with seen_ids for dedup)
  ├─ render_todo_text(memory) → todo_list_text
  │
  ├─ [Executor-first path, default]
  │   ├─ Executor runs with __skip__ marker task
  │   ├─ If retry needed (empty result): Planner → Executor (max 1 retry)
  │   └─ Reflector
  │
  ├─ [Planner-first path, when explicitly requested]
  │   ├─ Planner: skip-first → tasks (max 3)
  │   ├─ Executor: per-task tool-use loop (max 8)
  │   │   ├─ ContextBudget.check (emergency fold)
  │   │   ├─ llm.bind_tools(registry.list_tools())
  │   │   ├─ For each tool_call: ToolDispatcher.dispatch → micro-compress
  │   │   └─ On use_skill: SkillRuntime.activate → push frame + SystemMessage
  │   └─ Reflector: REFLECTION + FACTS + RELATIONSHIP_NOTES
  │
  ▼
AgentResponse → WorldEngine.handle_response()
  ├─ HistoryStore.append(dialogue)
  ├─ memory.remember() per MemoryUpdate
  └─ Compressor.maybe_fold() → impression memory
```

### Key Design Decisions (action graphs)

- **Executor-first is the default.** Most NPC events are single-turn; skip
  Planner unless tasks fail or the world engine explicitly requests planning.
- **Planner is skip-first.** Even when Planner does run, it defaults to "skip"
  — only decomposes genuinely multi-step events (max 3 tasks).
- **Executor re-reads tools each loop iteration.** This is how `use_skill`
  activation surfaces new tools to the LLM mid-loop.
- **Frame-based tool scoping.** Every `use_skill` pushes a frame onto
  `ToolRegistry`. The executor's `finally` block pops all frames pushed during
  the task — no skill tool leakage across tasks.
- **Agent declares intents, World Engine arbitrates.** The agent produces
  `ActionRequest` and `MemoryUpdate` objects. The engine decides whether to
  execute, reject, or modify them. This applies to all graphs, not just action.

## Memory System

### Dual-Channel Retrieval

| Channel | Method | Strength | Use Case |
|---|---|---|---|
| Vector recall | `memory.recall(query, categories, k)` | Semantic similarity | "What do I know about the bar?" |
| Literal grep | `memory.grep(pattern, category, metadata_filters, k)` | Exact substring + metadata | "Did Li Si mention the key?" |

Both exposed as LLM-callable tools (`memory_recall`, `memory_grep`). The model
decides which to use — no application-level routing needed.

### Memory Categories

| Category | Content | Write Policy | Storage |
|---|---|---|---|
| `semantic` | Facts, knowledge | Upsert (content-hash dedup) | ChromaDB |
| `reflection` | Self-reflection, relationship notes | Upsert (content-hash dedup) | ChromaDB |
| `impression` | Folded history summaries | Add (no dedup — different time windows) | ChromaDB |
| `todo` | Open/closed task records | Add (event-sourced, never mutate) | ChromaDB |
| `episodic` | Legacy raw dialogue | — | Deprecated for new flows |

### Todo: Event-Sourced Model

- `plan_todo add` → writes record with `status=open`, returns `todo_id`
- `plan_todo complete` → writes NEW record with `status=closed, closes=todo_id`
- Original records are never mutated — full audit trail
- `<todo>` block in executor prompt renders alive (open − closed) items

### Single-Run Dedup

`runtime["recall_seen_ids"]` tracks content strings already in the working
memory context. Both `memory_recall` and `memory_grep` filter already-seen
records. Reset per `NPCAgent.run()` call.

## Three-Level Context Compression

| Level | Scope | Trigger | Output |
|---|---|---|---|
| **Micro** | Single ToolMessage | `len(content) > 2000` chars | Head 40% + tail 60%, truncation marker |
| **Emergency** | Executor message list | Tokens exceed 90% of model limit | LLM summary of earliest rounds → SystemMessage |
| **Fold** | Cross-run JSONL history | Unfolded window > 3000 tokens | LLM summary → `impression` memory, cursor advance |

- **Micro**: `ToolDispatcher._micro_compress()` — instantaneous, no LLM cost
- **Emergency**: `ContextBudget.check()` — in-memory only, preserves last 2
  Human-initiated rounds
- **Fold**: `Compressor.maybe_fold()` — writes to vector DB, advances cursor in
  meta sidecar. JSONL is never modified (append-only).

## Town Simulation

The Town is a Generative Agents-style semantic world simulation built on
`TownWorldEngine`. It features:

- **Spatial system**: 8 locations, 17 interactive objects with semantic
  affordances (not tile-based)
- **Schedule system**: Daily schedules with segments (location + intent +
  subtasks), schedule revision on significant events
- **Perception**: Bounded policy (max N events/objects/NPCs/exits), attention
  selection, spatial visibility
- **Conversation**: `start_conversation` with multi-turn paired exchange,
  natural close detection, cooldown enforcement
- **Reflection**: Poignancy-based triggering, evidence accumulation from
  events/schedules/conversations
- **Loop guards**: Detection of repeated failed actions, repeated low-value
  chatter, schedule drift
- **Replay**: Full artifact generation (action log, timeline, checkpoints,
  reflections)

### Town Tools (11 total)

`move_to`, `observe`, `wait`, `finish_schedule_segment`, `speak_to`,
`start_conversation`, `interact_with`, `inspect_affordances`, `use_affordance`,
plus built-in `memory_recall` and `memory_grep`.

## War Game

A three-faction language-deception strategy game:

- 15-city symmetric map, 3 factions (Player + 2 AI)
- 5 phases per round: Declaration → Diplomacy → Deployment → Resolution → Production
- AI factions use the full NPCAgent stack for strategic decisions
- 2v1 combat with negotiation subgame (withdraw/fight decisions)
- Interactive CLI with deployment minigame

## Interrogation Game

A detective interrogation prototype ("Double Shadow"):

- Phase-based structure: Initial Interrogation → Search 1 → Second
  Interrogation → Search 2 → Final Interrogation → Verdict
- NPC heart rate (BPM) system based on stress keyword detection
- Evidence bag tracking across search phases
- Memory contamination prevention (NPC dialogue → episodic only, facts → semantic only)
- Player scores verdict by keyword matching

## Common Commands

Use the existing Conda environment:

```bash
conda activate annie
# or: conda run -n annie <command>
```

LLM API settings are project-owned in `config/model_config.yaml` and `.env`.

```bash
# Install editable package with dev tools
pip install -e ".[dev]"

# Tests — full suite
pytest

# Integration tests (require LLM access via API key)
pytest tests/test_integration/test_decoupled_flow.py
pytest tests/test_integration/test_cross_run_todo.py

# NPC layer unit tests
pytest tests/test_npc/

# Town tests (deterministic stubs, no LLM)
pytest tests/test_town/test_town_multi_npc.py

# War game tests
pytest tests/test_war_game/

# World engine tests
pytest tests/test_world_engine/

# Skip integration tests (external API)
pytest -m "not integration"

# Specific test
pytest -k test_name

# Lint / type-check
ruff check src/annie/npc src/annie/world_engine src/annie/town src/annie/war_game
npx pyright src/annie/npc src/annie/world_engine
```

## Running the Games

```bash
# Town — single NPC day (real LLM)
python scripts/run_town_day_real_llm.py

# Town — multi-NPC tick simulation (real LLM)
python scripts/run_town_multi_npc_real_llm.py --enable-reflection

# War Game — interactive CLI
python -m src.annie.war_game.cli

# Interrogation — interactive detective game
python scripts/run_interrogation_game.py

# NPC smoke test (2-turn loop with real LLM)
python scripts/smoke_npc_loop.py
```

## Key Tests (canonical for the refactored architecture)

| Test File | What It Validates |
|---|---|
| `tests/test_integration/test_decoupled_flow.py` | End-to-end NPCAgent + DefaultWorldEngine: memory tools, inner_monologue, rolling history, skill rendering, todo section |
| `tests/test_integration/test_cross_run_todo.py` | Todo persistence across 3 runs: add → visible → complete → gone |
| `tests/test_integration/test_action_loop.py` | WorldEngine.drive_npc(): request_action stops before reflector, failed actions feed back |
| `tests/test_npc/test_skill_registry.py` | Skill loading from filesystem, activation, extra_tools resolution |
| `tests/test_npc/test_tool_registry_frames.py` | ToolRegistry frame stack: push/pop, multi-layer, scoping |
| `tests/test_npc/test_plan_todo.py` | plan_todo tool: add/complete/list, double-complete rejection |
| `tests/test_npc/test_planner.py` | Planner: skip/plan, task parsing, error handling, tracing |
| `tests/test_npc/test_executor.py` | Executor: task processing, tool loop, skill frames, request_action |
| `tests/test_npc/test_reflector.py` | Reflector: structured output, memory updates, relationship notes |
| `tests/test_town/test_town_multi_npc.py` | Full town simulation: registry, event bus, scheduling, perception, conversation, reflection, loop guards, replay |
| `tests/test_world_engine/test_compressor.py` | History compression: fold threshold, cursor advance, impression write |
| `tests/test_world_engine/test_history_store.py` | HistoryStore: append, read, persistence, corrupt-line skipping |
| `tests/test_war_game/test_e2e.py` | War game: 2-round progression, faction elimination |

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
  model: BAAI/bge-m3

memory:
  vector_store: chromadb
  persist_directory: ./data/vector_store
```

API key loaded via `python-dotenv` from `.env`:
```
DEEPSEEK_API_KEY=sk-...
```

## OpenSpec Workflow

OpenSpec specs live in `openspec/specs/`. Active changes in `openspec/changes/`.

```text
/opsx:propose "change idea"
/opsx:explore "<change-name>"
/opsx:apply "<change-name>"
/opsx:archive "<change-name>"
```

### Active Specs

| Spec | Content |
|---|---|
| `npc-agent-routing` | Agent graph dispatch, route resolution, direct modes |
| `npc-graph-registry` | CognitiveGraph, GraphEntry, 5 registered graphs |
| `town-world-simulation` | TownWorldEngine, Generative Agents lifecycle, reflection, replay |
| `world-engine` | WorldEngine ABC, DefaultWorldEngine, memory/history/compressor |

## Design Rules

- **Do not revive deleted legacy modules** (`cognitive/`, `perception.py`, old `BaseTool`, old Jinja-driven `BaseSkill`)
- **ChromaDB writes must be serialized** via `ChromaWriteGuard` (threading.Lock)
- **Tests should pass their own `chromadb.PersistentClient(path=tmp_path)` rather than using the shared project store**
- **Keep the NPC layer free of game-specific vocabulary**
- **Treat untracked project content as user work — don't delete or overwrite**
- **Prefer Protocol over ABC for cross-layer interfaces** (structural subtyping, no import dependency)
