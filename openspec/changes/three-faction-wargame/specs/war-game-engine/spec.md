# War Game Engine Capability Spec

Core game engine for the three-faction language-deception strategy game. Covers map state, central force pool, 4-phase round orchestration, combat resolution, production, elimination, and information disclosure.

## ADDED Requirements

### Requirement: WarGameEngine must subclass WorldEngine

`WarGameEngine` SHALL inherit from `WorldEngine` and implement all abstract methods (`build_context`, `handle_response`, `memory_for`). It SHALL accept a `GameConfig`, an `NPCAgent`, and an LLM at construction.

#### Scenario: Engine satisfies WorldEngine contract

- **WHEN** `WarGameEngine` is instantiated
- **THEN** it SHALL pass `isinstance(engine, WorldEngine)` check
- **AND** `build_context`, `handle_response`, `memory_for` SHALL be callable

#### Scenario: Engine requires NPCAgent and LLM

- **WHEN** constructing `WarGameEngine` without an `NPCAgent` or LLM
- **THEN** construction SHALL fail with a clear error

---

### Requirement: GameState must represent a 15-city three-faction map with central force pools

`GameState` SHALL track: a graph of cities (id, owner, adjacency, captured-this-round flag), three factions (id, force pool, eliminated flag), current round number, and per-round transient state (declarations, deployments, battle results).

Each faction's force pool is a single integer representing all available troops. There is no per-city garrison between rounds — forces are centrally allocated each round.

#### Scenario: Initial state is balanced

- **WHEN** a new game is created with default config
- **THEN** each faction SHALL own exactly 5 cities
- **AND** each faction SHALL have equal initial force pools
- **AND** the city adjacency graph SHALL have 3-fold rotational symmetry

#### Scenario: Force pool is central, not per-city

- **WHEN** querying a faction's available forces
- **THEN** the answer SHALL be a single integer (`faction.force_pool`)
- **AND** there SHALL be no per-city troop count between rounds

---

### Requirement: Round must execute four phases in strict order

Each round SHALL execute: Declaration → Diplomacy → Deployment → Resolution. No phase may be skipped or reordered.

#### Scenario: Phase order is enforced

- **WHEN** a round executes
- **THEN** Declaration phase SHALL complete before Diplomacy begins
- **AND** Diplomacy SHALL complete before Deployment begins
- **AND** Deployment SHALL complete before Resolution begins

#### Scenario: Eliminated factions are skipped

- **WHEN** a faction has been eliminated
- **THEN** it SHALL be skipped in all phases
- **AND** diplomacy pairs involving the eliminated faction SHALL not occur

---

### Requirement: Declaration phase must collect one public statement per active faction

In the Declaration phase, each active faction (including the player) SHALL produce a single public text statement. All statements SHALL be visible to all factions for the remainder of the round.

#### Scenario: AI faction produces declaration via NPCAgent

- **WHEN** it is an AI faction's turn to declare
- **THEN** the engine SHALL call `NPCAgent.run()` with tools containing `declare_intent`
- **AND** the response dialogue SHALL be recorded as that faction's declaration

#### Scenario: All declarations are visible

- **WHEN** all declarations are collected
- **THEN** subsequent phases' `AgentContext.situation` SHALL include all declarations

---

### Requirement: Diplomacy phase must support pairwise multi-round private conversations

The Diplomacy phase SHALL conduct private conversations between all active faction pairs. Each pair SHALL exchange up to `config.max_diplomacy_rounds` messages. The three conversation pairs are: player-AI_A, player-AI_B, AI_A-AI_B.

#### Scenario: Player-AI conversation

- **WHEN** the player is in conversation with an AI faction
- **THEN** the player SHALL input messages via CLI
- **AND** the AI SHALL respond via `NPCAgent.run()` with a `send_message` tool
- **AND** conversation SHALL end when the round limit is reached or the player explicitly ends it

#### Scenario: AI-AI conversation is invisible to player

- **WHEN** AI_A and AI_B conduct their private conversation
- **THEN** the player SHALL NOT see any content from this conversation
- **AND** the player SHALL NOT be informed that the conversation occurred
- **AND** each AI's memory SHALL record the exchange via the Reflector

#### Scenario: Diplomacy round limit is configurable

- **WHEN** `config.max_diplomacy_rounds` is set to N
- **THEN** each pair SHALL exchange at most N messages per round

---

### Requirement: Deployment phase must collect a complete force allocation from each active faction

In the Deployment phase, each active faction SHALL allocate its entire force pool across defense assignments (to owned cities) and attack assignments (to enemy cities adjacent to owned territory). The total allocated MUST equal the faction's force pool exactly.

#### Scenario: Valid deployment

- **WHEN** a faction allocates forces such that defense + attack totals equal its force pool
- **AND** all attack targets are adjacent to at least one city the faction owns
- **THEN** the deployment SHALL be accepted

#### Scenario: Invalid deployment is rejected

- **WHEN** a faction's allocation does not sum to its force pool, or targets a non-adjacent city
- **THEN** the deployment SHALL be rejected with an error message
- **AND** the faction SHALL be prompted to retry (AI via Executor retry, player via CLI re-prompt)

#### Scenario: Fallback on repeated failure

- **WHEN** an AI faction fails to produce a valid deployment after the Executor's retry limit
- **THEN** the engine SHALL assign a default deployment (all forces to defense, equally distributed)

---

### Requirement: Combat resolution must use attrition with defender advantage on ties

All battles in a round SHALL resolve simultaneously. For each attacked city: attacker forces and defender forces cancel. If attacker > defender, attacker occupies the city with (attacker - defender) troops returning to pool. If attacker <= defender, defender keeps the city with (defender - attacker) troops returning to pool. Attacker loses all committed troops. Ties go to the defender.

#### Scenario: Attacker wins

- **WHEN** 500 troops attack a city defended by 300
- **THEN** the attacker SHALL occupy the city
- **AND** 200 troops SHALL return to the attacker's force pool
- **AND** the defender loses 300 troops

#### Scenario: Defender wins

- **WHEN** 200 troops attack a city defended by 500
- **THEN** the defender SHALL keep the city
- **AND** 300 troops SHALL return to the defender's force pool
- **AND** the attacker loses 200 troops

#### Scenario: Tie goes to defender

- **WHEN** 300 troops attack a city defended by 300
- **THEN** the defender SHALL keep the city
- **AND** both sides lose 300 troops (defender has 0 remaining in pool from this battle)

#### Scenario: Undefended city is auto-captured

- **WHEN** any number of troops attack a city with 0 defense
- **THEN** the attacker SHALL occupy the city
- **AND** all attacking troops return to the attacker's force pool

---

### Requirement: 2v1 combat must use equal split attrition followed by negotiation

When two factions attack the same city, defender damage SHALL be split equally between the two attackers. After the defender is eliminated, the two attackers SHALL enter a 2-round negotiation (neither side knows remaining forces), then simultaneously submit "withdraw" or "fight".

#### Scenario: Defender damage split equally

- **WHEN** attacker A (400) and attacker B (500) attack a city with 300 defenders
- **THEN** each attacker SHALL absorb 150 defender damage
- **AND** A has 250 remaining, B has 350 remaining (hidden from both)

#### Scenario: Both withdraw — city returns to defender

- **WHEN** both attackers choose "withdraw"
- **THEN** the city SHALL remain with the original defending faction
- **AND** the city SHALL have 0 garrison (defender's troops were consumed)
- **AND** both attackers' remaining troops return to their respective pools

#### Scenario: One withdraws, one stays

- **WHEN** attacker A chooses "withdraw" and attacker B chooses "fight"
- **THEN** attacker B SHALL occupy the city
- **AND** B's remaining troops return to B's pool
- **AND** A's remaining troops return to A's pool

#### Scenario: Both fight — final attrition

- **WHEN** both attackers choose "fight"
- **THEN** their remaining forces SHALL cancel (same attrition rules as normal combat)
- **AND** the winner (if any) occupies the city

#### Scenario: Negotiation participants do not know remaining forces

- **WHEN** a 2v1 negotiation begins
- **THEN** neither participant's `AgentContext.situation` SHALL include remaining force numbers
- **AND** the player's CLI SHALL NOT display remaining force numbers

---

### Requirement: Production must add forces per owned city with capture delay

At the end of each round's Resolution phase, each active faction SHALL receive `config.production_per_city` troops per owned city. Cities captured this round SHALL NOT produce troops until the following round.

#### Scenario: Normal production

- **WHEN** a faction owns 6 cities (none captured this round) and production is 50
- **THEN** the faction SHALL receive 300 troops added to its force pool

#### Scenario: Captured city delays production

- **WHEN** a faction captures a city this round
- **THEN** that city SHALL NOT contribute to this round's production
- **AND** that city SHALL contribute to production starting next round

---

### Requirement: Elimination occurs when a faction loses all cities

A faction SHALL be eliminated when it owns zero cities at the end of a Resolution phase. The game SHALL end when only one faction remains.

#### Scenario: Faction eliminated

- **WHEN** a faction loses its last city during Resolution
- **THEN** the faction SHALL be marked as eliminated
- **AND** its remaining force pool SHALL be discarded
- **AND** subsequent rounds SHALL skip this faction in all phases

#### Scenario: Game ends with one survivor

- **WHEN** only one faction remains after elimination check
- **THEN** the game SHALL end
- **AND** the surviving faction SHALL be declared the winner

---

### Requirement: Information disclosure must reveal battle details but not force totals

After Resolution, the engine SHALL produce a round report showing: per-battle participants, committed force numbers, and outcomes; declaration-vs-reality comparison for each faction; city ownership changes. The report SHALL NOT include any faction's total force pool or defense allocations for cities that were not attacked.

#### Scenario: Battle details are disclosed

- **WHEN** AI_A attacks player city P3 with 400 troops against 300 defense
- **THEN** the round report SHALL state the attacker, target, attacking force (400), defending force (300), and result (A wins, 100 remaining)

#### Scenario: Non-attacked city defense is hidden

- **WHEN** player city P1 was not attacked this round
- **THEN** the round report SHALL only state "no attack received"
- **AND** SHALL NOT reveal how many troops the player allocated to P1

#### Scenario: Declaration vs reality comparison

- **WHEN** AI_A declared "本轮重点防守" but actually attacked
- **THEN** the round report SHALL show the declaration text alongside the actual actions taken

#### Scenario: Total force pool is never disclosed

- **WHEN** the round report is generated
- **THEN** no faction's total force pool SHALL appear in the report
