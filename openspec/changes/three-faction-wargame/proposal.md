## Why

ANNIE's NPC Agent layer and WorldEngine framework are stable (40 tests pass, 0 lint/type errors) but have never been exercised in a real game. The previous murder-mystery demo is dead code. Building a small, complete game validates the architecture end-to-end and surfaces any gaps before further framework investment. A three-faction language-deception strategy game is an ideal first application: it exercises NPC memory, multi-NPC interaction, tool-based decision-making, and WorldEngine state management, while being scoped tightly enough to ship as a CLI prototype.

## What Changes

- New `WarGameEngine(WorldEngine)` subclass implementing the full game: map state, central force pool, 4-phase round loop (Declaration → Diplomacy → Deployment → Resolution), combat resolution including 2v1 negotiation, and elimination logic.
- New game-specific tools (`deploy_forces`, `declare_intent`, `negotiate_response`, `withdraw_or_fight`) that AI factions use via the existing `ToolDef` interface.
- Two AI faction personality prompts (pure prompt-driven behavior, no parameter layer).
- 15-city symmetric map with adjacency graph (three-way rotational symmetry, 2 front + 2 flank + 1 rear per faction).
- CLI game loop: player input for declarations, diplomacy chat, force deployment, and round result display.
- Game-specific NPC profile YAML files for the two AI factions.

## Capabilities

### New Capabilities
- `war-game-engine`: Core game engine — map state, central force pool, 4-phase round orchestration, combat resolution (1v1 attrition, 2v1 with negotiation), production, elimination, and information disclosure rules.
- `war-game-tools`: Game-specific ToolDef implementations for AI deployment decisions, declarations, negotiation responses, and withdraw/fight choices.
- `war-game-cli`: Terminal-based game loop — player input handling for each phase, round status display, map rendering (ASCII), and game configuration (diplomacy round limits, etc.).

### Modified Capabilities

(none — the NPC Agent layer and WorldEngine ABC are used as-is, no spec-level requirement changes)

## Impact

- **New code**: `src/annie/war_game/` (engine, tools, CLI, map, prompts)
- **New data**: `data/war_game/` (NPC profile YAMLs, optional map definitions)
- **Dependencies**: No new external dependencies. Uses existing `langchain-core`, `chromadb`, `langgraph`.
- **Existing code**: No modifications to `src/annie/npc/` or `src/annie/world_engine/`. This is a pure consumer of the existing framework.
- **Tests**: New test suite under `tests/test_war_game/` — combat resolution unit tests, round orchestration integration tests, tool validation tests.
