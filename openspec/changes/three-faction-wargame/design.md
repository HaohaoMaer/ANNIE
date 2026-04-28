## Context

ANNIE's two-layer architecture (NPC Agent + WorldEngine) is stable and tested but has no concrete game built on it. This change implements the first real game: a three-faction language-deception strategy game. The NPC Agent layer is used as-is; all game logic lives in a new `WarGameEngine(WorldEngine)` subclass.

Key architectural constraints from existing specs:
- All business logic must live in the WorldEngine layer (`world-engine` spec)
- NPC Agent layer must not be modified (`npc-agent` spec)
- Tools follow unified `ToolDef` interface; skills are not tools (`tool-skill-system` spec)
- Memory isolation per NPC; vector store holds only distilled content (`memory-interface` spec)

The game's core is not simulation but information asymmetry: players and AI factions declare, negotiate, then secretly deploy — the gap between words and actions drives the experience.

## Goals / Non-Goals

**Goals:**
- Playable CLI prototype that exercises the full round loop (declare → diplomacy → deploy → resolve)
- Two AI factions with distinct personalities driven purely by prompts + NPC memory
- AI factions that make their own deployment decisions via tool calls
- Combat resolution including the 2v1 negotiation sub-game
- Information disclosure system that enables players to learn AI behavior patterns over time
- Tunable parameters (diplomacy rounds, production rate, initial forces) for balance iteration

**Non-Goals:**
- Web UI (future follow-up)
- Multiplayer (human vs human vs AI)
- AI personality parameter layer or behavioral guardrails beyond prompts
- Save/load game state
- Replay system
- Sound, animation, or rich media
- Internationalization (Chinese-first is fine for prototype)

## Decisions

### D1: Module structure — flat `src/annie/war_game/` package

All game code lives under `src/annie/war_game/`:

```
src/annie/war_game/
├── __init__.py
├── engine.py          # WarGameEngine(WorldEngine)
├── game_state.py      # GameState, City, Faction, Map dataclasses
├── combat.py          # resolve_battle(), resolve_2v1()
├── tools.py           # deploy_forces, declare_intent, negotiate_response, withdraw_or_fight
├── phases.py          # declaration_phase(), diplomacy_phase(), deployment_phase(), resolution_phase()
├── map_preset.py      # default 15-city symmetric map definition
├── display.py         # CLI rendering (ASCII map, round summary, battle reports)
├── cli.py             # main game loop + player input handling
└── prompts/
    ├── faction_a.yaml # AI faction A profile
    └── faction_b.yaml # AI faction B profile
```

**Why not under `src/annie/world_engine/`**: The `world_engine/` package contains the framework (ABC, default engine, memory, history, compressor). Concrete games are consumers, not framework code. Keeping them separate prevents framework pollution.

**Why not a separate top-level package**: The game depends heavily on ANNIE internals (`WorldEngine`, `AgentContext`, `ToolDef`, etc.). Co-locating under `src/annie/` avoids import gymnastics.

### D2: GameState is a pure dataclass, engine orchestrates phases

```python
@dataclass
class City:
    id: str
    owner: str          # faction_id
    adjacent: list[str]  # city_ids
    captured_this_round: bool = False  # delays production by 1 round

@dataclass
class Faction:
    id: str
    force_pool: int
    is_eliminated: bool = False

@dataclass
class GameState:
    cities: dict[str, City]
    factions: dict[str, Faction]
    round_number: int = 0
    declarations: dict[str, str] = field(default_factory=dict)   # faction_id → text
    deployments: dict[str, list[Deployment]] = field(default_factory=dict)  # faction_id → orders
    round_log: list[BattleResult] = field(default_factory=list)
```

The engine holds a `GameState` and mutates it through phase functions. Each phase is a standalone function that takes `(state, engine, agent, ...)` — easy to test in isolation.

**Why dataclasses over Pydantic**: GameState is mutable and internal. Pydantic's immutability and validation overhead aren't needed for game state that's only modified by the engine.

### D3: One NPCAgent instance, multiple AgentContext builds per round

A single `NPCAgent(llm)` instance drives both AI factions. Per the existing architecture, all per-NPC differentiation flows through `AgentContext`. In one round, the engine calls `agent.run()` multiple times with different contexts:

- Declaration phase: 2 runs (one per AI faction)
- Diplomacy phase: up to `2 × max_rounds` player-AI runs + `max_rounds` AI-AI runs
- Deployment phase: 2 runs (one per AI faction)
- 2v1 negotiation (if triggered): 2-4 runs

Each `build_context()` call injects:
- `character_prompt`: faction personality
- `world_rules`: game rules summary (condensed, stable across rounds)
- `situation`: current round state — owned cities, force pool (own only), visible declarations, diplomacy summary
- `history`: cross-round history from HistoryStore
- `tools`: phase-appropriate tools only (e.g., `deploy_forces` only in deployment phase)
- `memory`: per-faction `MemoryInterface` for cross-round behavior impressions

**Why not a separate agent per faction**: `NPCAgent` is stateless by design. One instance, different contexts. No benefit to multiple instances.

### D4: Phase-specific tool injection

Each phase injects only the tools relevant to that phase:

| Phase | Tools injected | Purpose |
|---|---|---|
| Declaration | `declare_intent` | Emit a public statement |
| Diplomacy | `send_message` | Send a message in the current 1v1 conversation |
| Deployment | `deploy_forces` | Allocate force pool to defend/attack |
| 2v1 Negotiation | `negotiate_response`, `final_decision` | Chat + submit withdraw/fight |

The Executor's tool-use loop handles the rest. For Deployment, the `deploy_forces` tool validates that total allocated forces equal the faction's force pool and that attack targets are adjacent to owned territory.

**Why tool injection over skills**: These are mechanical actions with structured I/O, not prompt-guided workflows. They belong as tools per the `tool-skill-system` spec.

### D5: Diplomacy phase — lightweight message exchange, not full agent runs

Full `Planner → Executor → Reflector` cycles are heavyweight for diplomacy, where the AI just needs to produce one message per turn. Two options considered:

- **Option A**: Full `agent.run()` per message — uses Reflector to update memory after each exchange, but ~3 LLM calls per message.
- **Option B**: Direct LLM call with diplomacy-specific system prompt — fast, but bypasses the agent framework entirely.

**Decision: Option A (full agent.run) for now, optimize later if needed.**

Rationale: The Planner will `skip` (single task), Executor produces one tool call (`send_message`), Reflector updates memory. This is ~3 LLM calls per message, but it means the AI's memory of diplomatic exchanges is captured automatically. For the CLI prototype, latency is acceptable. If it becomes a bottleneck for the Web UI, we can introduce a lightweight "chat mode" that skips Planner/Reflector.

For AI-AI diplomacy, the engine alternates: run faction A (produces message) → inject message as `input_event` for faction B → run faction B → repeat. Player doesn't see any of this.

### D6: Combat resolution — pure functions, no LLM involved

Combat is deterministic math. `resolve_battle(attackers: list[Attack], defender: Defense) -> BattleResult` is a pure function.

2v1 flow:
1. `resolve_2v1_attrition(attacker_a, attacker_b, defender)` — split defender damage equally, return remaining forces per attacker (hidden from them).
2. Engine runs 2-round negotiation sub-game (2 agent.run calls per round, interleaved).
3. Both submit `final_decision` tool call → `resolve_2v1_standoff(decision_a, decision_b, remaining_a, remaining_b)`.

**Important**: During 2v1 negotiation, the `situation` prompt does NOT include remaining forces for either side. The AI genuinely doesn't know how many troops it has left.

Player side: the CLI also doesn't show the player their remaining forces. The player knows how many they sent initially and that the defender had _some_ garrison, but not the subtraction result.

### D7: Map — hardcoded symmetric preset, future-proofable

The initial map is a hardcoded 15-city graph with 3-fold rotational symmetry:

```
          A1 ─── A2
         / |      | \
       A3  |      |  B3
       |   A4 ── B4   |
       |   |      |   |
       A5  |      |  B5
        \  |      |  /
         P3 ── B2─┘
         |      |
         P4 ── B1
         |   /
         P5─┘
        / |
      P2  |
       \  |
        P1
```

Actual topology defined in `map_preset.py` as an adjacency dict. Each faction has:
- 1 rear city (only adjacent to own cities)
- 2 front cities (adjacent to one enemy)
- 2 flank cities (adjacent to the other enemy)

**Why hardcoded**: For the prototype, balance-testing a fixed map is more productive than building a map generator. The `GameState` dataclass accepts any `dict[str, City]`, so custom maps are trivially pluggable later.

### D8: Information disclosure — battle details with force numbers, no totals

After resolution, the player sees per-battle reports:

```
═══ Round 3 Results ═══
[Battle] 甲 attacks your city P3: 甲 sends 400, your garrison 300 → 甲 wins, occupies P3 (甲 remaining: 100)
[Battle] You attack 乙 city B1: You send 500, 乙 garrison 200 → You win, occupy B1 (your remaining: 300)
[No battle] Your city P1: no attack received

═══ Declaration vs Reality ═══
甲 declared: "本轮重点防守"  →  Actually: attacked your city P3 with 400 troops
乙 declared: "联合玩家进攻甲"  →  Actually: defended all cities
```

NOT disclosed: faction total force pools, defense allocations for non-attacked cities, AI-AI diplomacy content.

Players can infer minimum force levels from attack numbers but never see the full picture.

### D9: AI personality — two contrasting prompt archetypes

Faction A: **The Hawk** — aggressive, risk-taking, tends toward deception. Will often declare defense while actually attacking. Respects strength, exploits perceived weakness.

Faction B: **The Fox** — cautious, calculating, prefers to let others fight. More likely to honor agreements when it's strategically advantageous. Breaks promises when the gain is overwhelming.

These are pure `character_prompt` strings. No numeric parameters, no sanity checks, no behavioral guardrails. The LLM interprets and executes — emergent behavior is a feature. NPC memory (`reflection`, `impression` categories) naturally accumulates cross-round patterns that influence future decisions.

### D10: Balance parameters — externalized constants

All tunable values live in a `GameConfig` dataclass:

```python
@dataclass
class GameConfig:
    initial_forces: int = 1000       # per faction
    production_per_city: int = 50    # per city per round
    max_diplomacy_rounds: int = 3    # per pair per round
    max_negotiation_rounds: int = 2  # 2v1 only
    # ... more as needed
```

Passed to `WarGameEngine.__init__`. Default values are placeholder — will be tuned through playtesting.

## Risks / Trade-offs

**[LLM deployment quality]** AI may make mathematically suboptimal or incoherent deployments via the `deploy_forces` tool (e.g., allocating more than available, forgetting a city, invalid target).
→ **Mitigation**: `deploy_forces` tool validates strictly (total must match pool, targets must be adjacent). On validation failure, return error message to LLM for retry within the Executor loop. After N failures, engine assigns a safe default (equal distribution to defense).

**[LLM cost per round]** Each round requires many LLM calls: ~2 declaration + ~9 diplomacy (3 pairs × 3 rounds) + ~3 AI-AI diplomacy + ~2 deployment + ~2 reflection = ~18 calls minimum. At ~$0.03/call (Sonnet), that's ~$0.50/round.
→ **Mitigation**: Acceptable for prototype. For production: consider Haiku for diplomacy messages, cache system prompts aggressively, reduce diplomacy rounds.

**[AI-AI diplomacy coherence]** When two LLMs talk to each other, conversations may be shallow or circular.
→ **Mitigation**: Character prompts include specific diplomatic goals per round (e.g., "try to learn what the other faction plans to do while revealing as little as possible"). Memory of past interactions adds depth over rounds.

**[Snowball despite mitigation]** Even with delayed production, a faction that takes 2 cities early may become unstoppable.
→ **Mitigation**: Two-weaker-gang-up-on-stronger is an emergent behavior in 3-player games. The diplomacy phase exists precisely for this. If playtesting shows it's insufficient, consider: defender advantage multiplier, max force cap, or escalating production cost.

**[Player waiting time]** Each round involves multiple sequential LLM calls. Player may wait 30-60 seconds for AI turns.
→ **Mitigation**: CLI displays progress indicators. AI-AI diplomacy can potentially run in parallel with player input phases where there's no dependency. Future Web UI can show animations during AI think time.
