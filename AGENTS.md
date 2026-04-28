# ANNIE Codex Guide

This file is the primary project guide for Codex. `CLAUDE.md` is kept only as a
compatibility pointer and should not be treated as the source of truth.

## Repository Status

ANNIE is mid-refactor. The old end-to-end "Midnight Train" murder-mystery demo
was built on a deleted `social_graph` + `cognitive` layer. The current
architecture is a strict two-layer split:

- `src/annie/npc/`: stateless, business-agnostic NPC Agent framework.
- `src/annie/world_engine/`: world state, memory backends, business tools,
  action arbitration, scene progression, and concrete engines.

The old demo paths (`scripts/run_midnight_train_demo.py`, `午夜列车/`, legacy
`web/` assumptions) are not expected to work until they are rebuilt on the new
architecture.

Source of truth for large architectural work:

- Synced specs: `openspec/specs/`
- Active changes: `openspec/changes/`
- Archived refactor context:
  `openspec/changes/archive/2026-04-12-decouple-npc-world-engine/`

## Common Commands

```bash
# Install editable package with dev tools
pip install -e ".[dev]"

# Tests
pytest
pytest tests/test_integration/test_decoupled_flow.py
pytest tests/test_integration/test_cross_run_todo.py
pytest tests/test_war_game
pytest -k test_name
pytest -m "not integration"

# Lint / type-check refactored core
ruff check src/annie/npc src/annie/world_engine
npx pyright src/annie/npc src/annie/world_engine

# OpenSpec
openspec list --json
openspec status --change "<name>" --json
openspec instructions apply --change "<name>" --json
openspec validate "<name>" --strict
```

ChromaDB writes local vector stores under `data/`. Tests should pass their own
`chromadb.PersistentClient(path=tmp_path)` instead of using the shared project
store.

## Codex Workflow

- Prefer editing through `apply_patch` for manual file changes.
- Use `rg` / `rg --files` for search.
- Do not revive deleted legacy modules (`cognitive/`, `social_graph/`,
  `perception.py`, old `BaseTool`, old Jinja-driven `BaseSkill`).
- Keep changes scoped to the requested behavior and the active OpenSpec change.
- Do not modify generated Chroma/vector-store data unless the task explicitly
  asks for data regeneration.
- Treat untracked project content as user work. Do not delete or overwrite it
  without explicit instruction.

OpenSpec has been initialized for Codex under `.codex/skills/`. For spec-driven
work, use the Codex/OpenSpec flow:

```text
/opsx:propose "change idea"
/opsx:explore "<change-name>"
/opsx:apply "<change-name>"
/opsx:archive "<change-name>"
```

If slash commands are not visible, restart the IDE/Codex session after running
`openspec init --tools codex --force .`.

## Architecture Invariants

The NPC Agent layer and World Engine layer must remain separated. This is the
core refactor invariant and is enforced by `openspec/specs/`.

### NPC Agent Layer: `src/annie/npc/`

This layer is a generic AI capability framework. It must not import `chromadb`,
hold world state, parse NPC YAML, or contain business vocabulary such as script,
clue, sandbox, phase-specific game logic, `EmotionalState`, `BeliefSystem`, or
`SocialGraph`.

Key contracts:

- `NPCAgent(llm, skills_dir=None)` is stateless across runs.
- All per-NPC data enters through `AgentContext` on each `run()` call.
- All outputs leave through `AgentResponse`.
- `AgentContext` has three tiers: typed core fields, prompt text fields, and
  open-ended `extra`.
- `MemoryInterface` is a Protocol with `recall`, `grep`, `remember`, and
  `build_context`.
- Built-in tools are merged with `AgentContext.tools`; built-ins win naming
  conflicts.
- Skills are activated only through the `use_skill` built-in tool. Skill names
  are not standalone tool names.

Agent flow:

```text
WorldEngine.build_context(npc_id, event) -> AgentContext
NPCAgent.run(ctx):
  Planner -> Executor -> Reflector
  Executor may retry to Planner if all execution results fail
AgentResponse -> WorldEngine.handle_response(...)
```

Executor system prompts must keep stable XML sections:

```text
<character>
<world_rules>
<situation>
<memory_categories>
<working_memory>
<todo>
<available_skills>
```

Planner is skip-first. It should return `{"skip": true, ...}` for simple single
turn events and only emit tasks for genuine multi-stage sequences.

### World Engine Layer: `src/annie/world_engine/`

This layer owns all business complexity:

- world state
- memory backends
- business tools
- skill definitions
- action arbitration
- scene progression
- NPC YAML/profile parsing
- history persistence and compression

Only this layer may import `chromadb`.

Important files:

- `base.py`: `WorldEngine` ABC (`build_context`, `handle_response`,
  `memory_for`; optional `history_for`, `compressor_for`, `step`).
- `memory.py`: `DefaultMemoryInterface`, with vector recall and literal grep.
- `history.py`: per-NPC JSONL history and fold cursor metadata.
- `compressor.py`: cursor-based history folding into `impression` memory.
- `default_engine.py`: default concrete composition of memory/history/compressor.

Vector memory stores distilled content only: `semantic`, `reflection`,
`impression`, and `todo`. Raw dialogue belongs in `HistoryStore`, not episodic
vector memory.

## Memory Rules

- `recall`: semantic/vector search.
- `grep`: literal substring + metadata filtering; use for proper names, exact
  phrases, and todo metadata queries.
- Conventional categories: `semantic`, `reflection`, `impression`, `todo`;
  `episodic` is legacy and should not be written by new default flows.
- Single-run recall dedup uses `context.extra["_recall_seen_ids"]`.

Todo memory is event-sourced:

- `add`: writes an open todo record.
- `complete`: appends a closed record referencing the open todo id.
- Never mutate the original todo record.

## Testing Notes

Canonical tests for the refactored architecture:

- `tests/test_integration/test_decoupled_flow.py`
- `tests/test_integration/test_cross_run_todo.py`
- `tests/test_npc/test_skill_registry.py`
- `tests/test_npc/test_tool_registry_frames.py`
- `tests/test_npc/test_plan_todo.py`
- `tests/test_war_game/`

Older suites may predate the refactor. Do not fix them piecemeal unless the
active task is specifically about that compatibility work.

## Concrete Game Lines

Current content/engine work includes:

- `double_shadow/` and `src/annie/interrogation/`: Chinese interrogation and
  evidence-search murder-mystery prototype.
- `src/annie/war_game/`: three-faction language-deception strategy game used to
  exercise the architecture end to end.
- `web/`: frontend/backend work still contains legacy assumptions and should be
  migrated deliberately before being treated as the main runnable product.
