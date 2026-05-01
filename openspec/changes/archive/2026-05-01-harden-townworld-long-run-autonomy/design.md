## Context

TownWorld currently has a semantic Generative Agents baseline: world-owned
resident state, daily planning contexts, bounded perception, conversation
sessions, reflection triggers, replay snapshots, and opt-in real-LLM validation.
That is enough for a convincing one-day smoke run, but long-running autonomy has
stricter requirements. A resident must carry context from yesterday into
tomorrow, generate a new schedule from memory and current circumstances, avoid
repeating low-value actions, and leave enough replay evidence for debugging.

`GenerativeAgentsCN` provides the next behavioral reference. Its `Agent` creates
a schedule only when the current day has no valid schedule, updates
`scratch.currently` from retrieved memory, asks for wake-up time, asks for a
coarse daily plan, expands that into an hourly schedule, decomposes the current
plan segment, and revises a decomposed segment when events such as chat or
waiting interrupt the plan. ANNIE should preserve that lifecycle while keeping
the architectural split: `TownWorldEngine` owns durable simulation state and
`NPCAgent` remains a stateless cognitive backend.

## Goals / Non-Goals

**Goals:**

- Support deterministic and real-LLM multi-day town runs.
- Make daily schedules generated per simulated day from resident persona,
  lifestyle seeds, previous-day memories, reflections, relationships, known
  places, and unresolved topics.
- Decompose and revise current schedule segments without letting revisions
  corrupt the rest of the day.
- Expand semantic town content through more locations, objects, affordances, and
  town tools while staying map-free.
- Make conversation and reflection outcomes influence future planning through
  distilled memory and relationship summaries.
- Add loop/drift guards and replay evidence so behavior can be explained and
  regression-tested.
- Keep `src/annie/npc/` stateless, business-agnostic, and unaware of town
  schedules, maps, relationships, or memory backends.

**Non-Goals:**

- No visual map, tile-backed navigation, frontend replay UI, or pathfinding
  renderer in this phase.
- No direct port of `GenerativeAgentsCN` modules into `src/annie/npc/`.
- No new durable state inside `NPCAgent`.
- No replacement of ANNIE memory categories with a separate associative-memory
  subsystem.

## Decisions

### Decision: Add an explicit resident day lifecycle

TownWorld should make day boundaries first-class. At the beginning of each
simulated day, the engine evaluates whether each resident needs a new schedule,
updates resident scratch/currently from memory, generates the daily plan, and
stores the accepted schedule in `TownResidentState`.

```text
day_start(npc)
  -> retrieve planning memories
  -> update scratch.currently
  -> generate wake-up / daily intent / schedule proposal
  -> validate and persist accepted schedule
  -> emit replay planning checkpoint

tick(npc)
  -> render local perception
  -> decompose current schedule segment if needed
  -> choose action or conversation
  -> execute tools through TownWorldEngine
  -> accumulate evidence for reflection

day_end(npc)
  -> summarize day
  -> store distilled memory / relationship updates
  -> prepare next-day planning context
```

Alternative considered: reuse the current fixed schedule as the long-run
schedule. Rejected because it cannot express day-to-day memory influence and
would make multi-day runs look deterministic but socially inert.

### Decision: Model schedule generation after GenerativeAgentsCN, not as one JSON pass

Daily planning should be staged rather than asking the LLM for a single final
schedule from scratch:

1. retrieve relevant plan, reflection, relationship, and todo memory;
2. update `resident.scratch.currently`;
3. generate or choose wake-up time;
4. generate coarse daily intentions;
5. expand intentions into validated schedule segments;
6. decompose only the active segment when needed;
7. revise the active segment after interruptions.

This follows `GenerativeAgentsCN`'s `wake_up`, `schedule_init`,
`schedule_daily`, `schedule_decompose`, `schedule_revise`, and
`retrieve_currently` shape while adapting outputs to ANNIE's `ScheduleSegment`
model and semantic locations.

Alternative considered: keep one `build_daily_planning_context` call returning
the entire day. Rejected as the only path because it gives fewer control points
for validation, retry, deterministic tests, and replay explanation. A compact
single-call path can remain as a fallback or smoke mode.

### Decision: Keep schedules semantic and engine-validated

Generated schedules should reference semantic `location_id`, intent,
approximate time window, optional affordance targets, and optional subtasks.
TownWorld must validate ownership, time windows, overlap, location existence,
reachable semantic paths, and fallback behavior before persisting a schedule.

Alternative considered: let the LLM freely invent locations or object names and
resolve them later. Rejected for this phase because explainable replay and
stable tests require bounded, known town content.

### Decision: Expand town tools around affordances, not visual navigation

New tools should unlock more resident behavior in the semantic world:
inspecting affordances, using objects, posting/reading notices, buying/selling
or requesting simple services, sharing information, choosing conversation
topics, and marking schedule progress. Tools should be implemented as
world-engine tools that mutate or query `TownState`, not as NPC-layer concepts.

Alternative considered: add tile movement and visual map first. Rejected because
the current need is long-run behavioral stability; visual fidelity would add
complexity before resident cognition is stable.

### Decision: Make relationship and reflection outputs planning inputs

Conversation summaries, unresolved topics, trust/affinity hints if added,
reflection evidence, and day summaries should be written as distilled memory
with metadata. Next-day planning must retrieve and render these items so a
resident can change plans based on what happened yesterday.

Alternative considered: keep relationship cues only in immediate conversation
context. Rejected because the target is multi-day social simulation, where
conversations and reflections need future behavioral consequences.

### Decision: Treat replay as an explanation artifact

Replay checkpoints should include the decision evidence needed to explain
behavior: current schedule segment, generated/revised schedule reason, local
perception inputs, selected action, rejected/retried actions, relationship
cues, retrieved planning memories, reflection evidence, loop-guard outcomes,
and validation summaries.

Alternative considered: rely on timeline text and action logs. Rejected because
long-run regressions require structured evidence and machine-checkable fields.

## Risks / Trade-offs

- Prompt instability in daily planning -> stage outputs, validate them, and keep
  deterministic fake agents for golden tests.
- Multi-day runs become expensive -> support bounded day windows, compact
  planning modes, deterministic validations, and opt-in real-LLM scripts.
- Loop guards may over-constrain natural behavior -> record guard decisions in
  replay and start with warnings/soft discouragement before hard rejection.
- Relationship modeling can become too game-like -> begin with pairwise
  summaries and unresolved topics; add numeric signals only if tests show a
  concrete need.
- Replay can become too verbose -> separate compact timeline, structured JSONL,
  and periodic explanation checkpoints.

## Migration Plan

1. Preserve existing one-day fixtures and tests as compatibility baseline.
2. Add resident day lifecycle APIs without removing current schedule accessors.
3. Introduce staged daily planning behind deterministic fake cognitive outputs.
4. Expand semantic content and tools in small slices with replay evidence.
5. Add deterministic multi-day validation before opt-in real-LLM long-run
   scripts.
6. Keep fallback fixed schedules for tests and debugging.

Rollback is additive: disable generated multi-day planning and continue using
fixture schedules plus the existing one-day runner.

## Open Questions

- Should wake-up time be a separate structured cognition call or part of daily
  schedule generation for ANNIE's first implementation?
- How much numeric relationship state is useful before it becomes overfitted?
- What loop metrics should block a run versus only warn in validation output?
- How many simulated days and NPCs should define the first real-LLM long-run
  acceptance target?
