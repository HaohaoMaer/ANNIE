## Context

The current TownWorld implementation already has the first semantic milestone:
world-owned locations, objects, schedules, local perception, action tools,
multi-NPC ticks, conversations, and replay artifacts. `GenerativeAgentsCN`
offers a richer reference loop, but its `Agent` owns spatial memory, schedule
memory, associative memory, action state, map movement, reflection, and LLM
prompting in one object.

The target is not a stricter game-style world engine. The target is a
Stanford-style town simulation whose resident lifecycle aligns with Generative
Agents, with one architectural difference: ANNIE's `NPCAgent` remains a
stateless cognitive capability layer invoked by the town runtime.

```text
TownWorldEngine
  owns simulation loop, map, time, events, replay, resident registry
        |
        v
TownResident
  owns durable per-NPC simulation state:
  persona, scratch/currently, daily schedule, current action,
  spatial memory, poignancy, relationship cues
        |
        v
NPCAgent
  stateless cognitive backend for planning, action selection,
  conversation, and reflection
        |
        v
AgentResponse / structured cognitive output / action tool calls
```

## Goals / Non-Goals

**Goals:**

- Preserve the current semantic TownWorld milestone and extend it toward a full
  Generative Agents style daily simulation.
- Introduce world-owned per-NPC resident state that mirrors Stanford agent
  lifecycle state without putting durable town state into `src/annie/npc/`.
- Let residents generate daily plans through `NPCAgent`, while TownWorld
  persists those plans in resident state.
- Add bounded spatial/local perception that can start semantic and later support
  tile-backed maps.
- Add relationship-aware conversation decisions and reflection hooks using
  existing memory categories and metadata conventions.
- Improve replay/checkpoint output so long runs can be inspected and compared.

**Non-Goals:**

- Do not copy `GenerativeAgentsCN`'s monolithic agent model.
- Do not introduce legacy `cognitive`, old `BaseTool`, or old Jinja skill
  assumptions.
- Do not move `chromadb`, town YAML/profile parsing, schedules, spatial memory,
  or business vocabulary into `src/annie/npc/`.
- Do not make the web frontend the primary success criterion for this change.

## Decisions

### Decision: Align TownWorld behavior with GenerativeAgentsCN

Use `GenerativeAgentsCN` to define the target resident lifecycle:

- wake-up and daily schedule generation
- schedule decomposition and revision
- local perception with attention bandwidth
- spatial memory over places/objects
- event and chat memory retrieval
- poignancy/importance-triggered reflection
- conversation cooldown, termination, and repeat checks
- compressed replay output

Do not reuse its monolithic `Agent` class. In ANNIE, the equivalent durable
state lives in a TownWorld-owned resident object, and each LLM-backed cognitive
step is a call to `NPCAgent` with a mode-specific `AgentContext`.

Alternative considered: port `GenerativeAgentsCN/generative_agents/modules`.
Rejected because it would duplicate LLM config, violate stateless NPC contracts,
and reintroduce durable town state into the NPC capability layer.

### Decision: Add TownResident as the Stanford Agent state equivalent

The current `TownState.schedules`, `npc_locations`, and `current_actions`
capture useful global data, but Stanford-style simulation needs per-resident
continuity. Add or evolve toward a `TownResident` / `TownResidentState` concept
owned by TownWorld. It should hold resident-local durable state such as:

- profile/persona references
- scratch/currently text
- daily schedule and decomposed current plan
- current action
- spatial memory over known places and objects
- poignancy/importance accumulator
- recent conversation summaries or relationship cues
- cursors for reflection and replay

`NPCAgent` may generate plan, reflection, relationship, and action-selection
outputs. It must not retain those outputs as durable simulation state.

Alternative considered: store schedules only in top-level `TownState` maps.
Rejected because it pushes the design toward a game-server schedule table rather
than a resident-centric Generative Agents simulation.

### Decision: Keep the next milestone semantic-first

The current town fixture is semantic locations, not a tile maze. The next change
should strengthen the behavior loop before adding pixel/tile navigation:

1. richer semantic spatial graph and object affordances
2. resident-owned daily plan generation and decomposition via `NPCAgent`
3. relationship-aware conversation and reflection memory
4. replay snapshots suitable for later visual playback
5. optional tile-backed adapter after behavior tests are stable

Alternative considered: start with tile map import and pathfinding. Rejected as
premature because it adds UI/map complexity before the autonomous loop is stable.

### Decision: Invoke NPCAgent for resident cognition

Town planning, schedule decomposition, action selection, conversation, and
reflection should be initiated by TownWorld for a specific resident. TownWorld
constructs a mode-specific `AgentContext`, calls `NPCAgent`, then stores the
result in resident state or memory. The cognitive result may become a daily
schedule, current action, `reflection`, `impression`, relationship note, or
conversation turn.

Alternative considered: make TownWorld generate schedules without resident
cognition. Rejected because the goal is a Stanford-style simulation where plans
come from each resident's persona, memory, and current situation.

### Decision: Make long-run observability part of the contract

Replay should include action stream, checkpoints, conversation turns, schedule
state, NPC locations/actions, and memory/reflection summaries at configurable
intervals. This mirrors `GenerativeAgentsCN`'s compressed replay idea while
using ANNIE's JSONL-friendly artifacts.

Alternative considered: rely only on human-readable timeline text. Rejected
because debugging autonomous behavior needs structured, testable output.

## Risks / Trade-offs

- Prompt-driven resident plans may be unstable -> start with deterministic fake
  cognitive calls and golden-structure assertions before live LLM tests.
- Reflection can create noisy memory -> gate by importance/poignancy and store
  distilled content only in vector memory.
- Relationship logic can become a hidden global relationship system -> keep it
  as resident/world-owned memory metadata and rendered context, not a new
  NPC-layer system.
- Tile map work can distract from behavior correctness -> defer tile-backed
  navigation until semantic behavior has repeatable tests.
- Long simulations can become expensive -> support bounded tick windows,
  deterministic fake agents, and opt-in live LLM smoke runs.

## Migration Plan

1. Introduce or adapt resident state while keeping existing TownWorld tools
   compatible.
2. Add resident daily planning/decomposition behind deterministic cognitive
   interfaces.
3. Add spatial memory, perception, and reflection metadata gradually, with tests
   for context rendering and memory writes.
4. Extend replay artifacts in a backward-compatible way by adding fields rather
   than renaming existing fields.
5. Add live LLM scripts only after deterministic tests cover the loop.

Rollback is straightforward while this remains additive: disable resident
cognitive planning/reflection and keep the current schedule fixtures.

## Open Questions

- What exact shape should `TownResidentState` take in the first implementation,
  and how much of the existing `TownState.schedules` shape should be preserved
  for compatibility?
- Should daily planning be generated once per simulated day at wake-up, or
  pre-generated for deterministic tests and live-generated in smoke runs?
- What is the minimum relationship model: pairwise memory summaries, scalar
  affinity/trust, or only retrieved impressions?
- How soon do we need a tile-backed adapter versus a richer semantic graph?
- Should replay snapshots be optimized for a future web UI or for debugging
  first?
