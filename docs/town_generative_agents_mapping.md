# TownWorld Generative Agents Mapping

TownWorld is adopting Stanford-style Generative Agents lifecycle concepts while
preserving ANNIE's two-layer architecture. Durable town simulation state lives in
`src/annie/town/` and world-engine owned memory, while `NPCAgent` remains a
stateless cognitive backend invoked with an `AgentContext`.

| GenerativeAgentsCN | ANNIE |
|---|---|
| `Agent.schedule` | `TownResidentState.schedule` |
| `Agent.action` | `TownResidentState.current_action` |
| `Agent.spatial` | `TownResidentState.spatial_memory` |
| `Agent.scratch.currently` | `TownResidentState.scratch.currently` |
| `Agent.status["poignancy"]` | `TownResidentState.poignancy` |
| `Agent.associate` | `WorldEngine.memory_for(npc_id)` |
| `Agent.completion(...)` | `NPCAgent.run(AgentContext)` |
| `Maze` | `TownState.locations/objects` now, tile adapter later |

The first migration pass keeps legacy `TownState.npc_locations`,
`TownState.schedules`, and `TownState.current_actions` as compatibility mirrors.
New town code should prefer `TownState.resident_for()`, `resident_ids()`,
`location_id_for()`, `set_location()`, `schedule_for()`,
`current_schedule_segment()`, `current_action_for()`, `set_current_action()`,
and `set_schedule()`.

Daily planning, reflection triggers, tile-backed navigation, and replay UI are
intentionally deferred. Future `NPCAgent` planning outputs should be accepted or
revised by `TownWorldEngine` and then persisted back into `TownResidentState`,
not stored inside the NPC layer.
