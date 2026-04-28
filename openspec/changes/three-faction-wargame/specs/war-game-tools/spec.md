# War Game Tools Capability Spec

Game-specific `ToolDef` implementations for AI decision-making across all game phases.

## ADDED Requirements

### Requirement: declare_intent tool must emit a public declaration string

`declare_intent` SHALL accept a single `statement` string parameter and return the statement as the tool result. It SHALL be the only tool injected during the Declaration phase.

#### Scenario: AI declares intent

- **WHEN** the AI calls `declare_intent(statement="本轮我将防守所有城池")`
- **THEN** the tool SHALL return the statement text
- **AND** the engine SHALL record it as the faction's declaration for this round

#### Scenario: Empty declaration rejected

- **WHEN** the AI calls `declare_intent(statement="")`
- **THEN** the tool SHALL return an error message asking for a non-empty statement

---

### Requirement: send_message tool must emit a diplomacy message

`send_message` SHALL accept a `message` string parameter and return it as the tool result. It SHALL be the only tool injected during the Diplomacy phase. The engine uses the returned message as the faction's utterance in the current 1v1 conversation.

#### Scenario: AI sends diplomacy message

- **WHEN** the AI calls `send_message(message="我们联手进攻甲方如何？")`
- **THEN** the tool SHALL return the message text
- **AND** the engine SHALL deliver it to the conversation partner

---

### Requirement: deploy_forces tool must validate and accept a complete force allocation

`deploy_forces` SHALL accept a structured allocation: a list of `{target: city_id, troops: int, action: "defend" | "attack"}` entries. The tool SHALL validate:
1. Total troops across all entries equals the faction's force pool exactly
2. Every owned city has a defense entry (may be 0)
3. Attack targets are adjacent to at least one owned city
4. Attack targets are not owned by this faction
5. No negative troop values

On validation success, the tool SHALL record the deployment and return a confirmation. On failure, it SHALL return a specific error message describing which constraint was violated.

#### Scenario: Valid deployment accepted

- **WHEN** the AI submits a deployment where all constraints pass
- **THEN** the tool SHALL return "Deployment accepted" with a summary
- **AND** the engine SHALL record the deployment for resolution

#### Scenario: Total mismatch rejected

- **WHEN** the AI submits a deployment where troops sum to more or less than its force pool
- **THEN** the tool SHALL return an error: "Total allocated (X) does not match your force pool (Y)"

#### Scenario: Non-adjacent attack rejected

- **WHEN** the AI attacks a city not adjacent to any of its owned cities
- **THEN** the tool SHALL return an error: "City Z is not adjacent to your territory"

#### Scenario: Missing defense entry rejected

- **WHEN** the AI omits a defense assignment for one of its owned cities
- **THEN** the tool SHALL return an error: "Missing defense for city W. You may assign 0 troops but must include all owned cities"

---

### Requirement: negotiate_response tool must emit a negotiation message during 2v1

`negotiate_response` SHALL accept a `message` string parameter. It SHALL only be available during the 2v1 negotiation sub-phase. The engine uses the returned message as the faction's utterance in the negotiation.

#### Scenario: AI negotiates during 2v1

- **WHEN** the AI calls `negotiate_response(message="我损失惨重，你也撤吧")`
- **THEN** the tool SHALL return the message text
- **AND** the engine SHALL deliver it to the opposing attacker

---

### Requirement: final_decision tool must submit a binding withdraw-or-fight choice

`final_decision` SHALL accept a `choice` parameter that MUST be either `"withdraw"` or `"fight"`. It SHALL only be available during the 2v1 decision sub-phase (after negotiation rounds complete). The decision is binding and cannot be changed.

#### Scenario: Valid decision submitted

- **WHEN** the AI calls `final_decision(choice="withdraw")`
- **THEN** the tool SHALL return "Decision recorded: withdraw"
- **AND** the engine SHALL record this as the faction's binding choice

#### Scenario: Invalid choice rejected

- **WHEN** the AI calls `final_decision(choice="maybe")`
- **THEN** the tool SHALL return an error: "Choice must be 'withdraw' or 'fight'"

---

### Requirement: All game tools must follow the ToolDef contract

All game-specific tools SHALL subclass `ToolDef` from `annie.npc.tools.base_tool`. They SHALL use `ToolContext.agent_context` to access game state (via `extra` dict) at call time, never via constructor injection.

#### Scenario: Tool accesses game state through ToolContext

- **WHEN** `deploy_forces` needs to validate against the faction's force pool
- **THEN** it SHALL read the force pool from `ctx.agent_context.extra["game_state"]` or equivalent
- **AND** SHALL NOT receive game state via `__init__`

#### Scenario: Tools are registered via standard ToolRegistry

- **WHEN** the engine builds an `AgentContext` for a phase
- **THEN** phase-appropriate tools SHALL appear in `AgentContext.tools`
- **AND** SHALL be compatible with `ToolRegistry` merge behavior
