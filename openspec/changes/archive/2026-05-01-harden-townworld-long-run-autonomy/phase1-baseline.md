## Phase 1 Baseline And Acceptance

This phase narrows the change to a minimal deterministic multi-day loop for
TownWorld. It intentionally excludes semantic world expansion and relationship
influence.

### Current One-Day Baseline

- `TownWorldEngine` owns resident state, location state, action arbitration,
  memory, history, reflection evidence, schedule revision, and replay.
- `TownResidentState.schedule` is the current resident schedule and
  `TownState.schedules` remains a compatibility mirror.
- `run_multi_npc_day()` advances a bounded one-day tick window and writes
  action, timeline, checkpoint, and reflection replay artifacts.
- One-day schedule generation already accepts structured JSON through
  `generate_day_plan_for_resident()` and validates it before replacing resident
  schedule state.

### Deterministic Multi-Day Acceptance

- Target: 2 simulated days, 1 resident for the first deterministic scenario.
- Fixture: existing `create_small_town_state()` without adding new locations or
  affordances.
- Runner: `run_multi_npc_days()` wraps each day with deterministic
  `start_day_for_residents()`, `run_multi_npc_day()`, and
  `end_day_for_residents()`.
- Required evidence: day-owned schedule metadata, staged planning checkpoints,
  day summary memory, current segment decomposition, schedule revision evidence,
  loop guard events, and replay checkpoint fields.

### Opt-In Real-LLM Acceptance Shape

Phase 1 does not add the real-LLM long-run script yet. The later script should
report model call counts, replay paths, accepted schedules by day, validation
warnings, loop guard warnings, and memory/reflection outcomes.

### GenerativeAgentsCN Lifecycle Mapping

- `retrieve_currently` maps to `retrieve_planning_evidence()` plus
  `update_currently_for_resident()`.
- `wake_up` maps to `plan_wake_up_for_resident()`.
- `schedule_init` / coarse plan maps to `plan_daily_intentions_for_resident()`.
- `schedule_daily` maps to `plan_schedule_segments_for_resident()` followed by
  engine validation and `plan_day_for_resident()`.
- `schedule_decompose` maps to `decompose_current_schedule_segment()`.
- `schedule_revise` maps to deterministic event insertion through
  `revise_schedule_for_event()` and active-segment revision through
  `revise_current_schedule_segment()`.
