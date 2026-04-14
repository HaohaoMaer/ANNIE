# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository status

ANNIE is mid-refactor. The repo was an end-to-end "Midnight Train" murder-mystery demo built on top of a `social_graph` + `cognitive` layer; that layer has been deleted. The current architecture is a two-layer, decoupled split — see *Architecture* below. The old demo (`scripts/run_midnight_train_demo.py`, `午夜列车/`, `web/`) is **not expected to run** until a follow-up change restores it on the new architecture.

Source of truth for the refactor: `openspec/specs/` (synced capability specs) and `openspec/changes/archive/2026-04-12-decouple-npc-world-engine/`.

## Common commands

```bash
# Install (editable + dev extras)
pip install -e ".[dev]"

# Test
pytest                                                # full suite (old suite largely broken)
pytest tests/test_integration/test_decoupled_flow.py  # the one suite that exercises the new architecture end-to-end
pytest -k test_name                                   # single test
pytest -m "not integration"                           # skip tests that need an external LLM

# Lint / type-check
ruff check src/annie/npc src/annie/world_engine
npx pyright src/annie/npc src/annie/world_engine      # expect 0 errors on refactored code; chromadb SDK stubs emit noise

# OpenSpec workflow (spec-driven changes under openspec/changes/<name>/)
npx openspec list --json
npx openspec status --change "<name>" --json
npx openspec instructions apply --change "<name>" --json
```

ChromaDB writes a local vector store to `./data/vector_store/` by default; tests should always pass their own `chromadb.PersistentClient(path=tmp_path)` to avoid polluting it.

## Architecture

Two layers, strict separation. This separation is the whole point of the refactor — it is enforced by the specs in `openspec/specs/` and must not drift.

### NPC Agent layer — `src/annie/npc/`

A stateless, business-agnostic AI framework. **Must not** import `chromadb`, hold world state, or contain any business vocabulary (no "剧本", "线索", "沙盒", no `EmotionalState` / `BeliefSystem` / `SocialGraph`).

- `agent.py` — `NPCAgent(llm)`. One instance can drive any number of NPCs; all per-NPC data enters through `AgentContext` on each `run()` call and leaves as `AgentResponse`. Internally compiles a LangGraph: **Planner → Executor → Reflector**, with a retry edge from Executor back to Planner when the Executor produces no results.
- `context.py` / `response.py` — the *only* input and output channels. `AgentContext` is three-tier: strong-typed core (`npc_id`, `input_event`, `tools`, `skills`, `memory`), prompt text (`character_prompt`, `world_rules`, `situation`, `history`), and open `extra: dict`. `AgentContext.model_rebuild()` runs at import time to resolve forward refs.
- `memory/interface.py` — the `MemoryInterface` **Protocol** (`recall(query, categories)` / `remember(content, category)` / `build_context`). `category` is an open string, not an enum. Conventional values: `episodic`, `semantic`, `reflection`, `impression`.
- `tools/base_tool.py` — `ToolDef` ABC + `ToolContext`. `ToolContext.agent_context` gives tools access to `memory` and `extra` at call time (never via ctor injection).
- `tools/builtin.py` — built-in tools always registered: `memory_recall` (categories filter), `memory_store`, `inner_monologue`.
- `tools/tool_registry.py` — merges built-ins with `AgentContext.tools`. **Conflict policy: built-in wins with a warning log.**
- `context_budget.py` — `ContextBudget` runs inside the Executor's tool-use loop and **Emergency-folds** the earliest tool rounds into a summary SystemMessage when messages approach the model context limit.
- `executor.py` — native **tool-use loop**: builds XML-sectioned SystemMessage + rolling history turns + current task, runs `llm.bind_tools(all_tools).invoke(messages)` until no tool_calls (or `MAX_TOOL_LOOPS=8`). Dispatches tool_calls via `ToolAgent.dispatch` which **Micro-compresses** outputs >2000 chars.
- `skills/base_skill.py` — `SkillDef` / `SkillRegistry` kept for future reuse. **Currently frozen**: `SkillAgent.try_activate` always returns `None` + DeprecationWarning.
- `sub_agents/` — `MemoryAgent` (thin `MemoryInterface` adapter), `ToolAgent` (native tool_call dispatcher + Micro compression), `SkillAgent` (frozen).
- `tracing.py` — `Tracer` accumulates `TraceEvent`s through the run; nodes wrap work in `tracer.node_span(...)` and emit `tracer.trace(node, EventType, ...)`.

Key invariant: **anything per-NPC flows through `AgentContext`, not through `NPCAgent.__init__`.** If you find yourself adding state to `self`, reconsider.

### World Engine layer — `src/annie/world_engine/`

Owns all business complexity: world state, memory backends, business tools, skills, action arbitration, scene progression. Every concrete engine (scripted-murder, AI-GM, sandbox, …) subclasses `WorldEngine`.

- `base.py` — `WorldEngine` ABC. Minimum contract: `build_context`, `handle_response`, `memory_for`; optional `history_for(npc_id) -> HistoryStore`, `compressor_for(npc_id) -> Compressor`, `step()`.
- `memory.py` — `DefaultMemoryInterface`: single per-NPC ChromaDB collection (`npc_memory_{npc_id}`) with `category` metadata. `impression` hits get a 1.2× relevance boost.
- `store.py` / `chroma_lock.py` — ChromaDB primitives. **Only this layer imports `chromadb`.** Uses `from chromadb.api import ClientAPI`.
- `history.py` — `HistoryStore`: per-NPC JSONL rolling dialogue/event history at `./data/history/{npc_id}.jsonl`; supports `append` / `read_last` / `estimate_tokens` / `replace` (used by the Compressor).
- `compressor.py` — `Compressor.maybe_fold()`: when history tokens > 3000, the oldest contiguous unfolded slice (~1500 tokens) is LLM-summarised; the slice is replaced in `HistoryStore` by a single `is_folded=True` entry **and** the summary is also stored as `category="impression"` in long-term memory. Recursive folds are refused (already-folded entries are excluded from candidate selection).
- `default_engine.py` — `DefaultWorldEngine`: owns per-NPC `DefaultMemoryInterface`, `HistoryStore`, and optional `Compressor` (needs an LLM). `build_context` renders the last 20 history turns; `handle_response` appends dialogue + writes `episodic` memory + calls `compressor.maybe_fold`.

### Data flow for one run

```
WorldEngine.build_context(npc_id, event) → AgentContext
                        │
                        ▼
NPCAgent.run(ctx):
  Planner        — may emit tasks OR `{"skip": true}`; if skip, Executor synthesizes a single task from the event
  Executor       — per task: build messages (XML system + history turns + task) → while True: ContextBudget.check → llm.bind_tools(all).invoke → if no tool_calls: done; else ToolAgent.dispatch each and append ToolMessage
  retry edge     — if no execution_results and retry_count < max_retries, back to Planner
  Reflector      — parses REFLECTION/FACTS/RELATIONSHIP_NOTES; writes via MemoryAgent.store_reflection / store_semantic (RELATIONSHIP_NOTES merged into reflection category with `person` metadata)
                        │
                        ▼
                   AgentResponse → WorldEngine.handle_response
```

## Conventions worth knowing

- **Never revive legacy**. Deleted: `cognitive/`, `social_graph/`, `perception.py`, `memory/relationship.py`, old `BaseTool`, old Jinja-driven `BaseSkill`. If something references these names, it's dead code.
- **Memory lives in the world engine.** If you need to touch episodic/semantic storage, edit `src/annie/world_engine/`. The NPC layer only knows `MemoryInterface`.
- **Skills are not tools.** They never appear in `AgentContext.tools` and are never emitted as `tool_call` names. Wrong mental model = architectural violation.
- **`NPCProfile` is slim.** It is a carrier for `name`, `personality`, `background`, `goals`, `memory_seed`, `skills`, `tools`. YAML loading (`load_npc_profile`) is called from the world engine, never the NPC layer.
- **OpenSpec governs big refactors.** New architectural change → new `openspec/changes/<name>/` directory with `proposal.md`, `design.md`, `tasks.md`, `specs/<capability>/spec.md`. Work the tasks in order, archive with `npx openspec archive` (or `/opsx:archive`) when done.

## Testing notes

- `tests/test_integration/test_decoupled_flow.py` is the canonical end-to-end example — use it as a template. It stubs the LLM via a simple `_StubLLM` returning canned `AIMessage`s and passes a tmpdir `chromadb.PersistentClient` so the global vector store is not touched.
- Older suites (`tests/test_npc/`, `tests/test_social_graph/`, `tests/test_world_engine/`) predate the refactor and are largely broken. Don't fix them piecemeal; they'll be replaced as specs stabilize.
