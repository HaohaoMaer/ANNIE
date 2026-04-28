## 1. Foundations

- [ ] 1.1 Decide module location for the concrete town engine.
- [ ] 1.2 Define semantic town state models for time, locations, exits, objects, occupants, events, schedules, and current actions.
- [ ] 1.3 Add deterministic fixtures for a 3-5 NPC town with at least 5 locations.
- [ ] 1.4 Add tests for town state initialization and location occupancy updates.

## 2. Multi-NPC Integration

- [ ] 2.1 Reuse or complete EventBus/NPCRegistry support from `world-engine-multi-npc`.
- [ ] 2.2 Implement town tick progression with configurable time stride.
- [ ] 2.3 Add activation rules for schedule transitions, pending events, and visible local events.
- [ ] 2.4 Add tests for tick ordering and skipped idle NPCs.

## 3. Perception and Context

- [ ] 3.1 Implement world-owned local perception for current time, location, visible NPCs, objects, events, schedule segment, history, todo, and memory.
- [ ] 3.2 Render town perception into `AgentContext.situation` and `input_event` without leaking town data structures into the NPC layer.
- [ ] 3.3 Add tests that same-location events are visible and remote hidden events are not visible.

## 4. Town Action Tools

- [ ] 4.1 Add town action tools for move, observe, speak, interact, and wait through engine tool injection.
- [ ] 4.2 Implement move arbitration with reachable/unreachable results.
- [ ] 4.3 Implement speak/event routing between NPCs.
- [ ] 4.4 Implement object interaction as structured world events.
- [ ] 4.5 Add tests for successful and failed action observations.

## 5. Scheduling

- [ ] 5.1 Implement world-owned daily schedule storage.
- [ ] 5.2 Implement current schedule segment lookup by simulated time.
- [ ] 5.3 Implement schedule interruption or revision when conversations or waits occur.
- [ ] 5.4 Add tests for schedule-driven actions and schedule revision.

## 6. Replay and Inspection

- [ ] 6.1 Define replay JSON schema for tick time, NPC id, action type, location, and summary.
- [ ] 6.2 Generate a human-readable simulation timeline.
- [ ] 6.3 Add checkpoint/replay writing for every tick.
- [ ] 6.4 Add tests that movement and conversation appear in replay artifacts.

## 7. Small-Town Validation

- [ ] 7.1 Build a deterministic one-day small-town smoke scenario.
- [ ] 7.2 Verify the smoke scenario demonstrates movement, observation, and at least one NPC-to-NPC interaction.
- [ ] 7.3 Run focused tests for the town engine.
- [ ] 7.4 Document how to run the small-town simulation and inspect replay output.
