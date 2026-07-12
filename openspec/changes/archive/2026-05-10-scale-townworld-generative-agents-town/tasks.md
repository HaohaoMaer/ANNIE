## 1. Scenario Content

- [x] 1.1 Add a scaled semantic town scenario YAML under `src/annie/town/content/scenarios/` with at least 25 residents and at least 20 semantic locations.
- [x] 1.2 Define homes, workplaces, shops, public-service locations, outdoor gathering places, and event locations with exits, objects, and affordances.
- [x] 1.3 Define every resident with persona fields, home/sleep locations, wake/sleep windows, at least two valid relationships, memory seeds, and initial schedule seeds.
- [x] 1.4 Ensure scenario schedules reference known reachable locations and include home/lifecycle periods, work or study periods, and public/social destinations for representative residents.

## 2. Scenario Loading And Validation

- [x] 2.1 Extend or add scenario validation helpers for scaled resident count, location count, relationship references, memory seed coverage, route reachability, and schedule seed validity.
- [x] 2.2 Add deterministic tests that load the scaled scenario and assert the content contracts from `town-generative-scale-content`.
- [x] 2.3 Verify invalid scaled scenario fixtures fail clearly before any simulation tick advances.

## 3. Runtime Scale Diagnostics

- [x] 3.1 Extend runtime diagnostics to summarize scaled action quality by resident, action type, failure reason, action lifecycle state, schedule completion, inferred completion, unfinished schedule, and loop guard count.
- [x] 3.2 Extend diagnostics for scaled social behavior: conversation session counts, cooldown or blocked-conversation evidence, relationship cue availability, and conversation-derived memory/planning evidence.
- [x] 3.3 Ensure replay checkpoints preserve enough per-resident detail to inspect selected residents in larger runs without requiring a live debugger.

## 4. Deterministic Scale Validation

- [x] 4.1 Add a deterministic scaled runtime test that runs a representative cohort across a bounded day window and writes replay, diagnostics, and snapshot artifacts under a temporary path.
- [x] 4.2 Add deterministic assertions for no runtime crash, no unreported invalid routes, bounded failed action rates, bounded loop guard counts, and inspectable schedule progress.
- [x] 4.3 Add a deterministic resume validation for the scaled scenario proving a fresh stateless agent can continue from a manifest-backed snapshot.

## 5. Real-LLM Scale Validation

- [x] 5.1 Add or extend an opt-in real-LLM validation script for the scaled scenario with controls for resident ids/count, days, start/end minute, max ticks, model config path, temperature, retries, output directory, and prompt preview length.
- [x] 5.2 Write a scaled real-LLM summary JSON with LLM call count, action counts, failed action reasons, schedule metrics, loop guard metrics, conversation metrics, reflection/day-summary metrics, final resident states, and artifact paths.
- [x] 5.3 Ensure completed real-LLM runs can report behavior-quality warnings separately from runner or artifact-generation failures.

## 6. Verification

- [x] 6.1 Run deterministic town tests for scenario loading, runtime scale behavior, replay diagnostics, and resume behavior.
- [x] 6.2 Run targeted lint/type checks for changed town modules.
- [x] 6.3 Run one opt-in scaled real-LLM smoke with a small resident subset and record artifact paths in the change notes.
