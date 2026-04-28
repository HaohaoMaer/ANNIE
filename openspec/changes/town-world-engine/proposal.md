## Why

ANNIE's current validation scenarios are strong at language reasoning, memory, deception, and dialogue, but they under-exercise the architecture's action loop and world-state ownership. A town simulation gives the project a primary sandbox for validating autonomous NPC life: schedules, movement, perception, interaction, event propagation, memory, and replay over many ticks.

## What Changes

- Introduce a `TownWorldEngine` direction as a concrete, long-term validation target for ANNIE.
- Model a small semantic town before attempting a full 25-NPC Stanford-style town.
- Add world-owned concepts for time, locations, occupants, visible events, NPC schedules, and action state.
- Add town action tools such as move, observe, speak, interact, and wait through the world-engine tool injection path.
- Add a simulation tick loop that lets NPCs act from schedules and local perception, not only from player-style dialogue prompts.
- Add structured replay/checkpoint outputs so long-running simulations can be inspected without requiring a full frontend first.
- Preserve the strict boundary: the NPC layer remains stateless and business-agnostic; all town-specific state and rules live in the world engine.

## Capabilities

### New Capabilities

- `town-world-simulation`: Defines the semantic town simulation behavior: time progression, map/location state, schedules, perception, town actions, interaction events, and replay outputs.

### Modified Capabilities

- `world-engine`: Extends concrete engine expectations to support multi-NPC ticking, world-owned perception, action arbitration, and replay-friendly state snapshots.

## Impact

- Affected code will likely live under `src/annie/world_engine/` and possibly a new concrete package such as `src/annie/town/`.
- The NPC layer should not import town modules or learn town-specific data structures.
- The existing `world-engine-multi-npc` change is a natural prerequisite or stepping stone, especially its EventBus, NPCRegistry, and `tools_for(npc_id)` direction.
- Future tests should cover small-town behavior first: 3-5 NPCs, 5 locations, 1 simulated day, deterministic/stubbed LLM runs, and replay artifact generation.
