# War Game CLI Capability Spec

Terminal-based game loop for the three-faction strategy game. Handles player input, round display, and game flow.

## ADDED Requirements

### Requirement: CLI must run a complete game loop from start to victory

The CLI SHALL initialize a game (engine, agent, LLM), then loop rounds until a winner is determined. Each round SHALL walk the player through all four phases with clear prompts.

#### Scenario: Game starts and ends

- **WHEN** the player launches the game
- **THEN** the CLI SHALL display the initial map and game state
- **AND** begin the first round's Declaration phase
- **AND** continue looping rounds until one faction wins or the player quits

#### Scenario: Player can quit mid-game

- **WHEN** the player types a quit command (e.g., "quit" or Ctrl+C)
- **THEN** the CLI SHALL exit gracefully with a summary of the final state

---

### Requirement: CLI must handle player input for each phase

The CLI SHALL prompt the player for input appropriate to each phase:
- Declaration: free-text statement
- Diplomacy: free-text messages in conversation with each AI, with option to end early
- Deployment: structured force allocation input
- 2v1 Negotiation: free-text messages + final "withdraw"/"fight" choice

#### Scenario: Player declaration

- **WHEN** it is the Declaration phase
- **THEN** the CLI SHALL prompt "Your declaration:" and accept free text
- **AND** display all three declarations after collection

#### Scenario: Player diplomacy conversation

- **WHEN** it is the Diplomacy phase with AI_A
- **THEN** the CLI SHALL display AI_A's messages and prompt for player responses
- **AND** allow the player to type "end" to finish the conversation early
- **AND** show a round counter (e.g., "Message 2/3")

#### Scenario: Player deployment

- **WHEN** it is the Deployment phase
- **THEN** the CLI SHALL display the player's owned cities and total force pool
- **AND** prompt for allocation in a structured format
- **AND** validate the allocation (sum must equal pool, targets must be adjacent)
- **AND** allow correction on invalid input

#### Scenario: Player 2v1 negotiation

- **WHEN** the player is in a 2v1 negotiation
- **THEN** the CLI SHALL display the opponent's messages
- **AND** prompt for responses (up to 2 rounds)
- **AND** prompt for final "withdraw" or "fight" decision

---

### Requirement: CLI must display game state clearly after each phase

The CLI SHALL render: an ASCII map showing city ownership, a force pool summary (own forces only), and round results after Resolution.

#### Scenario: ASCII map display

- **WHEN** the game state is rendered
- **THEN** the CLI SHALL show all 15 cities with owner indicators (e.g., [A], [B], [P] for factions, with adjacency lines)

#### Scenario: Round results display

- **WHEN** Resolution phase completes
- **THEN** the CLI SHALL display all battle results with force numbers
- **AND** display declaration-vs-reality comparisons
- **AND** display city ownership changes
- **AND** display updated force pool (own only) and production gained

#### Scenario: Enemy force pool is never shown

- **WHEN** any game state is displayed
- **THEN** the CLI SHALL NOT show enemy factions' total force pools

---

### Requirement: CLI must support configurable game parameters at startup

The CLI SHALL accept optional parameters at launch for: diplomacy round limit, production per city, initial forces. Unspecified parameters SHALL use defaults from `GameConfig`.

#### Scenario: Custom diplomacy rounds

- **WHEN** the player launches with `--diplomacy-rounds 5`
- **THEN** all diplomacy conversations SHALL allow up to 5 exchanges

#### Scenario: Default config used when unspecified

- **WHEN** the player launches with no parameters
- **THEN** `GameConfig` defaults SHALL be used

---

### Requirement: CLI must show progress indicators during AI turns

The CLI SHALL display a progress indicator when waiting for AI LLM calls, so the player knows the game is not frozen.

#### Scenario: AI thinking indicator

- **WHEN** an AI faction is producing a declaration, diplomacy message, or deployment
- **THEN** the CLI SHALL display a spinner or text indicator (e.g., "甲方正在思考...")
- **AND** the indicator SHALL disappear when the AI response is received
