## Context

ANNIE has a strict NPC/world split. The NPC layer is a stateless capability framework, while the world engine owns state, memory backends, business tools, action arbitration, scene progression, and history compression. Existing murder-mystery and war-game validation paths exercise language reasoning and strategic dialogue, but they do not fully stress autonomous action in a persistent world.

GenerativeAgentsCN demonstrates the missing simulation pattern: each tick advances time, each NPC follows or revises a schedule, movement changes tile events, perception is scoped by location, NPCs react to visible events, and checkpoints/replay artifacts make the simulation inspectable. ANNIE should adopt that pattern as a concrete engine while preserving its cleaner boundary.

## Goals / Non-Goals

**Goals:**

- Define a long-term `TownWorldEngine` direction that validates ANNIE's action-capable architecture.
- Keep all town concepts in the world layer: time, map, locations, objects, schedules, perception, action state, replay, and event routing.
- Start with a small semantic town before a full 25-NPC tilemap.
- Reuse and build on `world-engine-multi-npc` concepts such as EventBus, NPCRegistry, and `tools_for(npc_id)`.
- Produce replay/checkpoint artifacts early, so simulation quality can be inspected without building a full frontend.

**Non-Goals:**

- Do not port GenerativeAgentsCN's fat Agent object into ANNIE.
- Do not move maze, schedule, perception, or social state into `src/annie/npc/`.
- Do not require a graphical frontend for the first implementation.
- Do not require 25 NPCs, tile-level pathfinding, or full Stanford-town parity in the first milestone.
- Do not revive deleted legacy layers such as `social_graph` or `cognitive`.

## Decisions

### Decision: Implement TownWorldEngine as a concrete world engine

`TownWorldEngine` should live under the world-engine side of the boundary, either in `src/annie/world_engine/town/` or a concrete package such as `src/annie/town/` that depends on `annie.world_engine` and `annie.npc` contracts only.

Alternative considered: extend `DefaultWorldEngine`. That would blur its role as a minimal integration engine and make tests harder to reason about.

### Decision: Use a semantic location graph before a tile maze

The first implementation should model locations, exits, objects, occupants, and visible events. Tilemap/pathfinding can be added later once simulation semantics are stable.

Alternative considered: port `maze.json` and grid movement immediately. This would make early validation depend on map tooling and rendering rather than the core action loop.

### Decision: WorldEngine owns perception

`build_context(npc_id, event)` should render only what the NPC can perceive: current time, current location, nearby NPCs, visible objects, local events, current schedule segment, recent history, todo, and relevant memories.

Alternative considered: let the NPC agent ask for arbitrary world state. That weakens the world authority boundary and makes perception hard to test.

### Decision: Schedules are world state, not NPC state

Daily plans and current action state should be world-owned data. The NPC may propose plan changes through actions or tools, but the engine stores and arbitrates the final schedule.

Alternative considered: put schedule generation and revision in the NPC agent. GenerativeAgentsCN does this, but ANNIE's invariant requires business state to remain in the world layer.

### Decision: Town actions use injected tools

Town-specific tools should be injected through `tools_for(npc_id)`, with verbs such as `move_to`, `observe`, `speak_to`, `interact_with`, and `wait`. Each tool returns structured observations and updates world state only through engine methods.

Alternative considered: rely only on the generic `world_action` tool. That is useful for early tests, but named town tools give clearer schemas and better model behavior once the town engine is real.

### Decision: Replay artifacts are first-class outputs

Every tick should be serializable to a compact checkpoint or replay event stream. The first replay surface can be Markdown plus JSON; visual replay can come later.

Alternative considered: defer replay until frontend work. That would make long-run simulation debugging much harder.

## Risks / Trade-offs

- [Risk] LLM cost and latency grow quickly with many NPCs. → Mitigation: start with 3-5 NPCs, deterministic fixtures, and tick-level activation rules.
- [Risk] NPCs may overreact to every visible event. → Mitigation: keep perception scoped and add attention limits before scaling.
- [Risk] Schedules can become stale after interruptions. → Mitigation: model schedule revision as explicit world-owned operations.
- [Risk] The town engine could leak business concepts into `src/annie/npc/`. → Mitigation: enforce imports and keep town state behind `AgentContext` text/extra and injected tools.
- [Risk] Replay snapshots can become too large. → Mitigation: record deltas and distilled action summaries rather than full prompt/debug payloads.

## Migration Plan

1. Finish or reuse the multi-NPC infrastructure from `world-engine-multi-npc`.
2. Add a minimal semantic town model and deterministic tests.
3. Add town action tools and perception rendering.
4. Add schedule and tick progression.
5. Add checkpoint/replay artifacts.
6. Scale from 3-5 NPCs to larger populations only after the small simulation is stable.

## Open Questions

- Should the first concrete package be `src/annie/world_engine/town/` or `src/annie/town/`?
- Should schedule generation use the main `NPCAgent`, a separate world-side LLM helper, or deterministic fixtures for the first milestone?
- What is the minimum replay schema that can also feed the existing `web/` frontend later?
