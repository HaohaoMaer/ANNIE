## 1. Town Behavior Stabilization

- [x] 1.1 Add OpenSpec artifacts for the TownWorld behavior stabilization change.
- [x] 1.2 Implement one-hop shortest-path routing for `move_to(destination_id)`.
- [x] 1.3 Add NPC-facing `talk_to` and remove `speak_to`/`start_conversation` from TownWorld AgentContext tools.
- [x] 1.4 Add NPC-facing `complete_current_schedule` with validated ledger writes and keep `finish_schedule_segment` as a compatibility alias.
- [x] 1.5 Normalize schedule completion types and remove empty conversations from inferred completion.
- [x] 1.6 Make `memory_recall` tolerate string/JSON/comma category values and numeric string `k`.
- [x] 1.7 Simplify TownWorld executor rules around movement, dialogue, schedule completion, and action time.
- [x] 1.8 Add focused unit/integration coverage for the stabilized behavior.
- [x] 1.9 Run focused regression tests and OpenSpec validation.
