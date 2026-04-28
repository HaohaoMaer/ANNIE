"""Game-specific ToolDef implementations for AI decision-making."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from annie.npc.tools.base_tool import ToolContext, ToolDef


# ---- Input schemas --------------------------------------------------------

class DeclareIntentInput(BaseModel):
    statement: str = Field(..., description="Your public declaration for this round.")


class SendMessageInput(BaseModel):
    message: str = Field(..., description="The message to send to the other faction.")


class DeployForcesInput(BaseModel):
    allocations: list[dict[str, Any]] = Field(
        ...,
        description=(
            "List of allocation entries, each with: "
            "'target' (city_id), 'troops' (int), 'action' ('defend' or 'attack')."
        ),
    )


class NegotiateResponseInput(BaseModel):
    message: str = Field(..., description="Your negotiation message to the opposing attacker.")


class FinalDecisionInput(BaseModel):
    choice: str = Field(..., description="Your final decision: 'withdraw' or 'fight'.")


# ---- Tool implementations ------------------------------------------------

class DeclareIntentTool(ToolDef):
    name = "declare_intent"
    description = "Make a public declaration about your intentions for this round. All factions will see this."
    input_schema = DeclareIntentInput

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> str:
        if isinstance(input, dict):
            input = DeclareIntentInput(**input)
        assert isinstance(input, DeclareIntentInput)
        if not input.statement.strip():
            raise ValueError("Declaration must not be empty.")
        ctx.agent_context.extra["_declaration"] = input.statement
        return input.statement


class SendMessageTool(ToolDef):
    name = "send_message"
    description = "Send a private message to the faction you are currently in conversation with."
    input_schema = SendMessageInput

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> str:
        if isinstance(input, dict):
            input = SendMessageInput(**input)
        assert isinstance(input, SendMessageInput)
        ctx.agent_context.extra["_message"] = input.message
        return input.message


class DeployForcesTool(ToolDef):
    name = "deploy_forces"
    description = (
        "Deploy your forces for this round. Allocate your entire force pool across "
        "defense (to your own cities) and attack (to adjacent enemy cities). "
        "The total must equal your force pool exactly."
    )
    input_schema = DeployForcesInput

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> str:
        if isinstance(input, dict):
            input = DeployForcesInput(**input)
        assert isinstance(input, DeployForcesInput)

        extra = ctx.agent_context.extra
        force_pool: int = extra["force_pool"]
        owned_city_ids: set[str] = set(extra["owned_city_ids"])
        adjacent_enemy_ids: set[str] = set(extra["adjacent_enemy_ids"])

        from annie.war_game.game_state import Deployment

        deployments: list[Deployment] = []
        total = 0
        defended_cities: set[str] = set()

        for entry in input.allocations:
            target = entry.get("target", "")
            troops = entry.get("troops", 0)
            action = entry.get("action", "")

            if action not in ("defend", "attack"):
                raise ValueError(f"Action must be 'defend' or 'attack', got '{action}'.")
            if troops < 0:
                raise ValueError(f"Troops must be non-negative, got {troops} for {target}.")

            if action == "defend":
                if target not in owned_city_ids:
                    raise ValueError(f"City {target} is not yours. You can only defend your own cities.")
                defended_cities.add(target)
            elif action == "attack":
                if target in owned_city_ids:
                    raise ValueError(f"City {target} is yours. Use 'defend' action for your own cities.")
                if target not in adjacent_enemy_ids:
                    raise ValueError(f"City {target} is not adjacent to your territory.")

            total += troops
            deployments.append(Deployment(target=target, troops=troops, action=action))

        # Check all owned cities have defense entries
        missing = owned_city_ids - defended_cities
        if missing:
            raise ValueError(
                f"Missing defense for city {', '.join(sorted(missing))}. "
                "You may assign 0 troops but must include all owned cities."
            )

        if total != force_pool:
            raise ValueError(
                f"Total allocated ({total}) does not match your force pool ({force_pool})."
            )

        extra["_deployments"] = deployments
        return f"Deployment accepted. {len(deployments)} orders recorded."


class NegotiateResponseTool(ToolDef):
    name = "negotiate_response"
    description = "Send a negotiation message to the opposing attacker in a 2v1 situation."
    input_schema = NegotiateResponseInput

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> str:
        if isinstance(input, dict):
            input = NegotiateResponseInput(**input)
        assert isinstance(input, NegotiateResponseInput)
        ctx.agent_context.extra["_negotiation_message"] = input.message
        return input.message


class FinalDecisionTool(ToolDef):
    name = "final_decision"
    description = "Submit your binding decision: 'withdraw' or 'fight'."
    input_schema = FinalDecisionInput

    def call(self, input: BaseModel | dict, ctx: ToolContext) -> str:
        if isinstance(input, dict):
            input = FinalDecisionInput(**input)
        assert isinstance(input, FinalDecisionInput)
        choice = input.choice.lower().strip()
        if choice not in ("withdraw", "fight"):
            raise ValueError("Choice must be 'withdraw' or 'fight'.")
        ctx.agent_context.extra["_final_decision"] = choice
        return f"Decision recorded: {choice}"
