## 1. Baseline And Reference Mapping

- [x] 1.1 Document the `GenerativeAgentsCN` behavior loop mapped to `TownResident` state plus stateless `NPCAgent` cognitive calls.
- [x] 1.2 Add or update deterministic TownWorld tests that capture the current semantic baseline before new behavior is added.
- [x] 1.3 Define the minimal resident fixture data needed for a richer one-day town run with 3-5 NPCs.

## 2. Resident State And Daily Planning

- [x] 2.1 Add `TownResident` or `TownResidentState` data structures for persistent per-NPC simulation state.
- [x] 2.2 Move or adapt schedule/current-action access so daily plans can live under resident state while preserving current tests.
- [x] 2.3 Implement deterministic resident planning calls for tests and scripted smoke runs.
- [x] 2.4 Add optional NPCAgent-backed daily planning using project model configuration.
- [x] 2.5 Support resident schedule decomposition or revision after significant town events.
- [x] 2.6 Test that schedules remain town-owned resident state and are rendered through `AgentContext`.

## 3. Spatial Perception

- [x] 3.1 Add a bounded perception policy for visible events, objects, NPCs, and locations.
- [x] 3.2 Add resident-owned spatial knowledge rendering for known places and object affordances.
- [x] 3.3 Make deterministic perception selection stable for tests.
- [x] 3.4 Test that hidden or out-of-scope events do not enter NPC context.

## 4. Conversation And Relationships

- [x] 4.1 Extend conversation context with recent interaction and relationship memory cues.
- [x] 4.2 Keep conversation start, turn-taking, cooldown, termination, and repeat checks town/resident-owned.
- [x] 4.3 Store distilled conversation outcomes in memory with relationship metadata.
- [x] 4.4 Test relationship-aware conversation prompts and cooldown rejection paths.

## 5. Reflection

- [x] 5.1 Add a resident-local importance or poignancy accumulator for town events and conversations.
- [x] 5.2 Trigger reflection opportunities when thresholds are reached.
- [x] 5.3 Store reflections as `reflection` or `impression` memory with traceable evidence metadata.
- [x] 5.4 Test that reflection writes distilled memory and does not write raw episodic dialogue.

## 6. Replay And Smoke Runs

- [x] 6.1 Extend replay artifacts with periodic structured town-state snapshots.
- [x] 6.2 Include schedule state, current actions, conversation sessions, and reflection events in replay output.
- [x] 6.3 Add deterministic replay comparison tests for key fields.
- [x] 6.4 Update town smoke documentation and scripts for the richer one-day run.
- [x] 6.5 Add an opt-in live LLM smoke once deterministic behavior is stable.

## 7. Validation

- [x] 7.1 Run `pytest tests/test_town`.
- [x] 7.2 Run `pytest tests/test_integration/test_decoupled_flow.py`.
- [x] 7.3 Run `ruff check src/annie/npc src/annie/world_engine src/annie/town`.
- [x] 7.4 Run `openspec validate evolve-townworld-generative-agents --strict`.
