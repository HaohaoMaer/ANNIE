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

- `agent.py` — `NPCAgent(llm, skills_dir=None)`. One instance can drive any number of NPCs; all per-NPC data enters through `AgentContext` on each `run()` call and leaves as `AgentResponse`. `skills_dir` points to a filesystem directory of `<name>/skill.yaml` + `<name>/prompt.md` bundles loaded once at construction. Internally compiles a LangGraph: **Planner → Executor → Reflector**, with a retry edge from Executor back to Planner when the Executor produces no results. At run start, `render_todo_text(context.memory)` is computed and written to `state["todo_list_text"]` so the Executor can render `<todo>`.
- `context.py` / `response.py` — the *only* input and output channels. `AgentContext` is three-tier: strong-typed core (`npc_id`, `input_event`, `tools`, `skills`, `memory`), prompt text (`character_prompt`, `world_rules`, `situation`, `history`), and open `extra: dict`. `AgentContext.model_rebuild()` runs at import time to resolve forward refs.
- `memory/interface.py` — the `MemoryInterface` **Protocol** (`recall` / `grep` / `remember` / `build_context`). `recall` is vector-similarity RAG; `grep(pattern, category=None, metadata_filters=None, k=20)` is the complementary literal-substring / metadata channel for proper-name & exact-phrase lookups (case-insensitive, sorted newest-first, `relevance_score=1.0`). `category` is an open string, not an enum. Five conventional values: `episodic` (legacy — no longer written), `semantic`, `reflection`, `impression`, `todo`. `grep("")` with `pattern=""` skips substring matching and returns all entries matching the filters only.
- `tools/base_tool.py` — `ToolDef` ABC + `ToolContext`. `ToolContext.agent_context` gives tools access to `memory` and `extra` at call time (never via ctor injection).
- `tools/builtin.py` — built-in tools always registered: `memory_recall`, `memory_grep`, `memory_store`, `inner_monologue`, `use_skill`, `plan_todo`. `inner_monologue` appends to `AgentContext.extra["_inner_thoughts"]`; `plan_todo` reads/writes `category="todo"` memories (event-stream model: `add` stores `status=open`, `complete` appends `status=closed`); `use_skill` delegates to `SkillAgent.activate`.
- `prompts.py` — shared prompt fragments: `render_identity(ctx)`, `render_skills_text(skills)`, `render_todo_text(memory)`, and `MEMORY_CATEGORIES_BLOCK`. `render_todo_text` computes the live open-todo list (open minus closed) for the `<todo>` XML section.
- `tools/tool_registry.py` — merges built-ins with `AgentContext.tools`. **Conflict policy: built-in wins.** Also supports a **frame stack** (`push_frame(tools) → frame_id` / `pop_frame(frame_id)`): `use_skill` pushes skill `extra_tools` as a temporary frame; the Executor pops all frames in `finally` at loop end.
- `context_budget.py` — `ContextBudget` runs inside the Executor's tool-use loop and **Emergency-folds** the earliest tool rounds into a summary SystemMessage when messages approach the model context limit.
- `executor.py` — native **tool-use loop**. System prompt uses fixed XML sections in order: `<character>`, `<world_rules>`, `<situation>`, `<memory_categories>`, `<working_memory>`, `<todo>`, `<available_skills>`. `<todo>` renders `state["todo_list_text"]` (pre-computed via `render_todo_text` at run start). `<available_skills>` renders the union of `AgentContext.skills` and the global `SkillRegistry` (de-duped by name, context wins). Each loop iteration re-reads `tool_registry.list_tools()` so newly-pushed skill frames are immediately visible.
- `planner.py` — **skip-first** default. Static prompt instructs the model to return `{"skip": true, ...}` unless the event genuinely requires sequential stages (cap at 3 tasks). Dynamic prompt does NOT render `history` — that is only consumed by Executor as messages. On retry (`retry_count > 0`), user_content appends a `<retry_context>` block containing `loop_reason` and the previous task list.
- `skills/base_skill.py` — `SkillDef(name, one_line, prompt, extra_tools, triggers)` + `SkillRegistry`. `skills/registry.py` — `load_dir(path)` scans `<path>/*/skill.yaml` + `prompt.md`; raises `FileNotFoundError` if `prompt.md` is absent; defers `extra_tools` resolution to activate time.
- `sub_agents/` — `MemoryAgent` (thin `MemoryInterface` adapter), `ToolAgent` (native tool_call dispatcher + Micro compression), `SkillAgent` (active: `activate(skill_name, args, messages, tool_registry)` pushes the skill's frame and appends a SystemMessage with `skill.prompt`; raises `ValueError` for unknown skill or unresolvable `extra_tools`).
- `tracing.py` — `Tracer` accumulates `TraceEvent`s through the run; nodes wrap work in `tracer.node_span(...)` and emit `tracer.trace(node, EventType, ...)`.

- `agent.py` run start also sets `context.extra.setdefault("_recall_seen_ids", set())`. `MemoryAgent.build_context` and `MemoryRecallTool`/`MemoryGrepTool` use this set to deduplicate records within a single run — records returned in `<working_memory>` won't be returned again by tool calls in the same run.

Key invariant: **anything per-NPC flows through `AgentContext`, not through `NPCAgent.__init__`.** If you find yourself adding state to `self`, reconsider.

### World Engine layer — `src/annie/world_engine/`

Owns all business complexity: world state, memory backends, business tools, skills, action arbitration, scene progression. Every concrete engine (scripted-murder, AI-GM, sandbox, …) subclasses `WorldEngine`.

- `base.py` — `WorldEngine` ABC. Minimum contract: `build_context`, `handle_response`, `memory_for`; optional `history_for(npc_id) -> HistoryStore`, `compressor_for(npc_id) -> Compressor`, `step()`.
- `memory.py` — `DefaultMemoryInterface`: single per-NPC ChromaDB collection (`npc_memory_{npc_id}`) with `category` metadata. `recall` (RAG) gives `impression` hits a 1.2× relevance boost; `grep` does substring-match via `collection.get(where=...)` + Python-side `casefold()` and returns results newest-first (no similarity weighting). **Vector store only holds distilled content** (`reflection`, `semantic`, `impression`, `todo`) — no `episodic` writes. `remember()` uses `upsert` + stable `sha1(category|content|person)[:16]` id for `semantic`/`reflection` (dedup on same content+person); other categories use `add` + uuid.
- `store.py` / `chroma_lock.py` — ChromaDB primitives. **Only this layer imports `chromadb`.** Uses `from chromadb.api import ClientAPI`.
- `history.py` — `HistoryStore`: per-NPC JSONL rolling dialogue/event history at `./data/history/{npc_id}.jsonl`; supports `append` / `read_last` / `estimate_tokens` / `prune(keep_last=N | before_turn_id=X)`. Also reads/writes a `.meta.json` sidecar that persists `last_folded_turn_id` (fold cursor). `HistoryEntry.is_folded` / `folded_from` are deprecated — `_read_all` skips `is_folded=True` entries when building history for rendering, but they are not deleted from disk.
- `compressor.py` — `Compressor.maybe_fold()`: cursor-driven; counts tokens only for entries with `turn_id > last_folded_turn_id`; when over threshold, LLM-summarises the oldest slice past the cursor and writes `category="impression"` to MemoryInterface; updates cursor in sidecar. **Does not modify JSONL** (no `HistoryStore.replace` call). Recursive folds are prevented by the cursor advancing past already-folded material.
- `default_engine.py` — `DefaultWorldEngine`: owns per-NPC `DefaultMemoryInterface`, `HistoryStore`, and optional `Compressor` (needs an LLM). `build_context` renders the last 20 history turns (skipping deprecated `is_folded=True` stubs); `handle_response` appends dialogue to JSONL and calls `compressor.maybe_fold` — **does not write `episodic` to the vector store** (vector store stores only distilled content).

### Four compressors — boundary summary

| Compressor | Where | Data lifetime | Trigger | Output |
|---|---|---|---|---|
| `Compressor` (`world_engine/compressor.py`) | World Engine, cross-run | Persistent (JSONL cursor + impression memory) | End of `handle_response` when unfolded tokens > threshold | `impression` MemoryRecord; JSONL cursor advances |
| `ContextBudget` (`npc/context_budget.py`) | NPC Agent, single Executor loop | Ephemeral (messages list only) | Before each LLM call when message tokens approach model limit | In-place summary SystemMessage injected into messages |
| `ToolAgent.micro` (`npc/sub_agents/tool_agent.py`) | NPC Agent, per ToolMessage | Ephemeral (single tool response) | ToolMessage content > 2000 chars | Head+tail truncation of the single ToolMessage |
| `HistoryStore.prune` (`world_engine/history.py`) | World Engine, cross-run | Permanent (deletes JSONL rows) | Explicitly called by WorldEngine (strategy is caller's responsibility) | Rows removed from JSONL; fold cursor unchanged |

**Rule**: only `Compressor` writes to the vector store. `ContextBudget` and `ToolAgent.micro` are purely in-memory. `prune` is purely destructive JSONL truncation.

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
- **Skills are not tools.** They never appear in `AgentContext.tools` and are never emitted as `tool_call` names. The LLM uses the `use_skill` built-in tool to activate a skill by name; that is the only entry point. Wrong mental model = architectural violation.
- **Skill directory convention.** Global skills live in `skills/<name>/` (repo root). Each entry requires `skill.yaml` (fields: `name`, `one_line`, `extra_tools`, `triggers`) and `prompt.md` (the SystemMessage text appended on activation). Pass the parent directory to `NPCAgent(skills_dir=...)`. Per-NPC skill whitelists are injected via `AgentContext.skills`.
- **`plan_todo` storage convention.** Todos are `category="todo"` memories. `add` writes `{status: open, todo_id: <8-hex>, created_at: <ISO8601>}`; `complete` first verifies the id exists and is open (errors otherwise), then appends a second record `{status: closed, closes: <todo_id>}`. `list` returns `{todo_id, content, timestamp}` sorted newest-first. `render_todo_text` computes alive = open − closed. Never update the original record — the protocol has no update semantic.
- **`NPCProfile` is slim.** It is a carrier for `name`, `personality`, `background`, `goals`, `memory_seed`, `skills`, `tools`. YAML loading (`load_npc_profile`) is called from the world engine, never the NPC layer.
- **OpenSpec governs big refactors.** New architectural change → new `openspec/changes/<name>/` directory with `proposal.md`, `design.md`, `tasks.md`, `specs/<capability>/spec.md`. Work the tasks in order, archive with `npx openspec archive` (or `/opsx:archive`) when done.

## Testing notes

- `tests/test_integration/test_decoupled_flow.py` — canonical end-to-end example. Stubs the LLM via `_StubLLM` (canned `AIMessage` responses, records all `invoke` calls in `.calls`). Always passes a tmpdir `chromadb.PersistentClient` so the global vector store is not touched.
- `tests/test_integration/test_cross_run_todo.py` — cross-run todo persistence: add in run1, visible in run2 `<todo>`, complete in run2, absent in run3.
- `tests/test_npc/test_skill_registry.py` — unit tests for `skills/registry.py:load_dir`.
- `tests/test_npc/test_tool_registry_frames.py` — unit tests for `ToolRegistry` frame stack.
- `tests/test_npc/test_plan_todo.py` — unit tests for the `plan_todo` built-in tool.
- Older suites (`tests/test_npc/`, `tests/test_social_graph/`, `tests/test_world_engine/`) predate the refactor and are largely broken. Don't fix them piecemeal; they'll be replaced as specs stabilize.
