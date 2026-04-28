## 1. Package scaffold and data model

- [x] 1.1 Create `src/annie/war_game/` package with `__init__.py`
- [x] 1.2 Implement `GameConfig` dataclass with all tunable parameters (initial_forces, production_per_city, max_diplomacy_rounds, max_negotiation_rounds)
- [x] 1.3 Implement `City`, `Faction`, `Deployment`, `BattleResult` dataclasses in `game_state.py`
- [x] 1.4 Implement `GameState` dataclass with city graph, factions, round state, and helper methods (owned_cities, adjacent_enemies, is_game_over)
- [x] 1.5 Implement `map_preset.py` with the default 15-city symmetric map (adjacency dict, faction assignments, 3-fold rotational symmetry)
- [x] 1.6 Write unit tests for GameState helpers and map preset validation (symmetry, adjacency, per-faction city counts)

## 2. Combat resolution

- [x] 2.1 Implement `resolve_battle(attacks, defense) -> BattleResult` pure function — 1v1 attrition with defender-wins-ties
- [x] 2.2 Implement `resolve_2v1_attrition(attacker_a, attacker_b, defender) -> (remaining_a, remaining_b)` — equal damage split
- [x] 2.3 Implement `resolve_2v1_standoff(decision_a, decision_b, remaining_a, remaining_b) -> BattleResult` — withdraw/fight matrix
- [x] 2.4 Implement `resolve_all_battles(state) -> list[BattleResult]` — simultaneous resolution of all deployments in a round, including detection and routing of 2v1 situations
- [x] 2.5 Write unit tests: 1v1 attacker wins, defender wins, tie, undefended city, 2v1 all outcome combinations (both withdraw, one withdraws, both fight with various force ratios)

## 3. Game-specific tools

- [x] 3.1 Implement `DeclareIntentTool(ToolDef)` — accepts statement string, validates non-empty
- [x] 3.2 Implement `SendMessageTool(ToolDef)` — accepts message string for diplomacy
- [x] 3.3 Implement `DeployForcesTool(ToolDef)` — accepts allocation list, validates sum/adjacency/completeness via `ctx.agent_context.extra`
- [x] 3.4 Implement `NegotiateResponseTool(ToolDef)` — accepts message string for 2v1 negotiation
- [x] 3.5 Implement `FinalDecisionTool(ToolDef)` — accepts "withdraw"/"fight" choice, validates
- [x] 3.6 Write unit tests for each tool: valid input, invalid input, error messages, ToolContext access pattern

## 4. AI faction prompts

- [x] 4.1 Write faction A ("The Hawk") NPC profile YAML — aggressive, deceptive personality
- [x] 4.2 Write faction B ("The Fox") NPC profile YAML — cautious, calculating personality
- [x] 4.3 Write `world_rules` prompt text — condensed game rules summary for AI context
- [x] 4.4 Write `situation` template logic — renders current round state (owned cities, own force pool, visible declarations, diplomacy history) into natural language for AgentContext

## 5. WarGameEngine core

- [x] 5.1 Implement `WarGameEngine.__init__` — accepts GameConfig, NPCAgent, LLM, ChromaDB client; initializes GameState, per-faction MemoryInterface and HistoryStore
- [x] 5.2 Implement `build_context(npc_id, event)` — constructs AgentContext with phase-appropriate tools, situation text, character prompt, and memory
- [x] 5.3 Implement `handle_response(npc_id, response)` — records response, appends to history
- [x] 5.4 Implement `memory_for(npc_id)` — returns per-faction DefaultMemoryInterface

## 6. Phase orchestration

- [x] 6.1 Implement `declaration_phase(state, engine, agent)` — collect declarations from player (CLI input) and both AI factions (NPCAgent.run)
- [x] 6.2 Implement `diplomacy_phase(state, engine, agent)` — run player-AI_A, player-AI_B, and AI_A-AI_B conversations with round limits
- [x] 6.3 Implement `deployment_phase(state, engine, agent)` — collect force allocations from player (CLI input + validation) and both AI factions (NPCAgent.run with deploy_forces tool); apply fallback on AI failure
- [x] 6.4 Implement `resolution_phase(state, engine)` — run resolve_all_battles, detect 2v1 situations, trigger negotiation sub-game if needed, apply production, check elimination
- [x] 6.5 Implement `negotiation_subgame(state, engine, agent, attacker_a, attacker_b, city)` — 2-round dialog + simultaneous decision + resolution
- [x] 6.6 Implement `generate_round_report(state, battles) -> str` — battle details, declaration-vs-reality, city changes
- [x] 6.7 Write integration test: full round cycle with stubbed LLM (declaration → diplomacy → deployment → resolution → production → report)

## 7. CLI game loop

- [x] 7.1 Implement `display.py` — ASCII map renderer, round report formatter, force pool display
- [x] 7.2 Implement player input handlers — declaration (free text), diplomacy (multi-round chat with "end" support), deployment (structured input with validation and re-prompt), 2v1 negotiation + withdraw/fight choice
- [x] 7.3 Implement `cli.py` main game loop — init engine, loop rounds, display results, handle victory/quit
- [x] 7.4 Add CLI argument parsing — `--diplomacy-rounds`, `--production`, `--initial-forces`, `--model` (LLM selection)
- [x] 7.5 Add progress indicators for AI thinking (spinner or "甲方正在思考..." text)

## 8. End-to-end integration

- [x] 8.1 Write integration test: 2-round game with stubbed LLM covering declaration, diplomacy, deployment, combat, production, and elimination
- [ ] 8.2 Manual playtest: run a full game against real LLM, note prompt quality issues and balance observations
- [ ] 8.3 Tune GameConfig defaults based on playtest (forces, production, diplomacy rounds)
- [x] 8.4 Verify lint (ruff) and type check (pyright) pass for `src/annie/war_game/`
