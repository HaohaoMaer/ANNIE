## 1. Baseline And Acceptance Shape

- [x] 1.1 Document the current one-day TownWorld behavior as the baseline for this change.
- [x] 1.2 Define the first deterministic multi-day acceptance scenario with target day count, NPC count, and fixture content.
- [x] 1.3 Define the first opt-in real-LLM multi-day acceptance scenario and required reporting fields.
- [x] 1.4 Add or update mapping notes for the GenerativeAgentsCN schedule lifecycle as adapted to TownWorld.

## 2. Resident Day Lifecycle

- [x] 2.1 Add day-specific resident planning metadata while preserving existing schedule accessors.
- [x] 2.2 Add day-start lifecycle orchestration for each active resident.
- [x] 2.3 Add day-end summary orchestration for each active resident.
- [x] 2.4 Persist day summaries as distilled memory with traceable metadata.
- [x] 2.5 Test that resident lifecycle state is town-owned and not retained by `NPCAgent`.

## 3. Staged Daily Schedule Generation

- [x] 3.1 Build Phase 1 planning-memory retrieval for prior plans, reflections, conversations, and todos; relationship influence remains deferred to 6.x.
- [x] 3.2 Add resident `currently` update context and deterministic fake output path.
- [x] 3.3 Add wake-up or start-of-day planning context and deterministic fake output path.
- [x] 3.4 Add coarse daily intention generation context and deterministic fake output path.
- [x] 3.5 Add schedule segment generation context and parser for accepted `ScheduleSegment` data.
- [x] 3.6 Add validation and fallback repair for ownership, time bounds, overlap, known locations, and required fields.
- [x] 3.7 Test that schedules renew across simulated days instead of silently reusing stale schedules.

## 4. Segment Decomposition And Revision

- [x] 4.1 Add active schedule segment decomposition state and context.
- [x] 4.2 Persist decomposed subtasks under town-owned schedule state.
- [x] 4.3 Add schedule revision context for conversations, waiting, failed actions, and significant events.
- [x] 4.4 Preserve completed segment evidence when future or active segments are revised.
- [x] 4.5 Test deterministic decomposition and revision paths.

## 5. Expanded Semantic Town Content And Tools

- [x] 5.1 Expand the small-town fixture with additional semantic locations and objects.
- [x] 5.2 Add object/location affordance metadata and context rendering.
- [x] 5.3 Add town tools for richer semantic interaction against affordances.
- [x] 5.4 Add rejection paths for unknown or unsupported affordances.
- [x] 5.5 Test new tools without introducing visual map or tile navigation assumptions.

## 6. Memory, Relationship, And Planning Influence

- [x] 6.1 Store distilled conversation outcomes with pairwise relationship metadata.
- [x] 6.2 Track unresolved topics or follow-up intentions as planning evidence.
- [x] 6.3 Ensure reflection outputs are retrievable for next-day planning.
- [x] 6.4 Render relevant relationship and memory evidence into staged planning contexts.
- [x] 6.5 Test that conversation or reflection evidence can change a later deterministic schedule.

## 7. Loop Guards And Drift Checks

- [x] 7.1 Add repeated failed-action detection for movement and object interactions.
- [x] 7.2 Add repeated low-value action or immediate chatter detection.
- [x] 7.3 Add schedule drift detection for residents spending too long away from plausible goals.
- [x] 7.4 Render loop-guard hints into context or reject actions where appropriate.
- [x] 7.5 Test loop/drift guard replay output and validation warnings.

## 8. Explainable Replay And Validation

- [x] 8.1 Extend replay checkpoints with planning evidence, schedule revisions, guard events, and next-day plan changes.
- [x] 8.2 Keep human-readable timeline output compatible with existing replay artifacts.
- [x] 8.3 Add deterministic multi-day replay comparison tests for key fields.
- [x] 8.4 Add `scripts/validate_townworld_long_run_real_llm.py` as an opt-in real-LLM validation script.
- [x] 8.5 Report model call counts, replay paths, schedule quality, loop warnings, and memory/reflection outcomes.

## 9. Validation

- [x] 9.1 Run `pytest tests/test_town`.
- [x] 9.2 Run targeted deterministic multi-day TownWorld tests.
- [x] 9.3 Run `pytest tests/test_integration/test_decoupled_flow.py`.
- [x] 9.4 Run `ruff check src/annie/npc src/annie/world_engine src/annie/town`.
- [x] 9.5 Run `openspec validate harden-townworld-long-run-autonomy --strict`.
