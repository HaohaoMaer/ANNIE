"""Decision Maker - Generates and selects actions based on motivations and beliefs.

The decision maker integrates motivations, beliefs, and emotions to make choices.
"""

from __future__ import annotations

from datetime import datetime, UTC
from enum import Enum
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from annie.npc.cognitive.belief_system import BeliefSystem
    from annie.npc.cognitive.emotional_state import EmotionalState
    from annie.npc.cognitive.motivation import Motivation, MotivationEngine
    from annie.npc.state import NPCProfile


class ActionType(str, Enum):
    """Types of actions an NPC can take."""

    INVESTIGATE = "investigate"
    TALK = "talk"
    SEARCH = "search"
    DEDUCE = "deduce"
    ACCUSE = "accuse"
    PROTECT = "protect"
    DECEIVE = "deceive"
    SHARE_INFO = "share_info"
    HIDE_INFO = "hide_info"
    MOVE = "move"
    WAIT = "wait"
    REFLECT = "reflect"


class Decision(BaseModel):
    """A decision made by an NPC."""

    action: str
    action_type: ActionType = ActionType.INVESTIGATE
    motivation: str = ""
    expected_outcome: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    target: str | None = None
    location: str | None = None
    context: dict = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    reasoning: str = ""
    risks: list[str] = Field(default_factory=list)
    benefits: list[str] = Field(default_factory=list)


class DecisionOption(BaseModel):
    """A possible decision option."""

    action: str
    action_type: ActionType
    score: float = 0.0
    motivation_alignment: float = 0.0
    emotional_fit: float = 0.0
    belief_consistency: float = 0.0
    feasibility: float = 0.5
    description: str = ""


class DecisionMaker:
    """Makes decisions based on motivations, beliefs, and emotions."""

    def __init__(self) -> None:
        self._decision_history: list[Decision] = []
        self._max_history: int = 100

    def generate_options(
        self,
        context: dict,
        motivations: list[Motivation],
        npc_profile: NPCProfile | None = None,
    ) -> list[DecisionOption]:
        """Generate possible decision options.

        Args:
            context: Current situation context.
            motivations: List of active motivations.
            npc_profile: The NPC's profile (optional).

        Returns:
            List of possible decision options.
        """
        options = []

        primary_motivation = motivations[0] if motivations else None

        if primary_motivation:
            options.extend(self._generate_motivation_based_options(primary_motivation))

        options.extend(self._generate_context_based_options(context))

        options.extend(self._generate_exploration_options(context))

        seen_actions = set()
        unique_options = []
        for opt in options:
            if opt.action not in seen_actions:
                seen_actions.add(opt.action)
                unique_options.append(opt)

        return unique_options[:10]

    def _generate_motivation_based_options(
        self,
        motivation: Motivation,
    ) -> list[DecisionOption]:
        """Generate options based on a motivation."""
        options = []

        motivation_type = motivation.motivation_type.value

        if motivation_type == "investigation":
            options.append(DecisionOption(
                action=f"Investigate {motivation.target or 'the situation'}",
                action_type=ActionType.INVESTIGATE,
                motivation_alignment=0.9,
                description=f"Directly investigate to achieve: {motivation.goal}",
            ))

        elif motivation_type == "social":
            if motivation.target:
                options.append(DecisionOption(
                    action=f"Talk to {motivation.target}",
                    action_type=ActionType.TALK,
                    motivation_alignment=0.9,
                    target=motivation.target,
                    description=f"Communicate with {motivation.target}",
                ))

        elif motivation_type == "discovery":
            options.append(DecisionOption(
                action="Search for clues",
                action_type=ActionType.SEARCH,
                motivation_alignment=0.8,
                description="Look for new information",
            ))

        elif motivation_type == "deception":
            options.append(DecisionOption(
                action="Hide information",
                action_type=ActionType.HIDE_INFO,
                motivation_alignment=0.7,
                description="Conceal relevant information",
            ))

        elif motivation_type == "protection":
            if motivation.target:
                options.append(DecisionOption(
                    action=f"Protect {motivation.target}",
                    action_type=ActionType.PROTECT,
                    motivation_alignment=0.9,
                    target=motivation.target,
                    description=f"Keep {motivation.target} safe",
                ))

        return options

    def _generate_context_based_options(
        self,
        context: dict,
    ) -> list[DecisionOption]:
        """Generate options based on current context."""
        options = []

        available_npcs = context.get("available_npcs", [])
        for npc in available_npcs[:3]:
            options.append(DecisionOption(
                action=f"Talk to {npc}",
                action_type=ActionType.TALK,
                target=npc,
                description=f"Have a conversation with {npc}",
            ))

        available_locations = context.get("available_locations", [])
        for location in available_locations[:3]:
            options.append(DecisionOption(
                action=f"Search {location}",
                action_type=ActionType.SEARCH,
                location=location,
                description=f"Examine {location} for clues",
            ))

        available_items = context.get("available_items", [])
        for item in available_items[:3]:
            options.append(DecisionOption(
                action=f"Inspect {item}",
                action_type=ActionType.INVESTIGATE,
                description=f"Take a closer look at {item}",
            ))

        return options

    def _generate_exploration_options(
        self,
        context: dict,
    ) -> list[DecisionOption]:
        """Generate exploration and reflection options."""
        options = []

        options.append(DecisionOption(
            action="Reflect on current situation",
            action_type=ActionType.REFLECT,
            description="Think about what has happened and what to do next",
        ))

        options.append(DecisionOption(
            action="Wait and observe",
            action_type=ActionType.WAIT,
            description="Take time to see what develops",
        ))

        return options

    def predict_consequences(
        self,
        decision: Decision,
        context: dict,
    ) -> str:
        """Predict the likely consequences of a decision.

        Args:
            decision: The decision to analyze.
            context: Current context.

        Returns:
            Description of predicted consequences.
        """
        consequences = []

        action_type = decision.action_type

        if action_type == ActionType.TALK and decision.target:
            consequences.append(f"Will learn information from {decision.target}")
            consequences.append(f"May affect relationship with {decision.target}")

        elif action_type == ActionType.SEARCH:
            consequences.append("May discover new clues or items")
            consequences.append("Takes time and may be noticed by others")

        elif action_type == ActionType.ACCUSE:
            consequences.append("Will create conflict with accused person")
            consequences.append("May reveal your suspicions to others")

        elif action_type == ActionType.DECEIVE:
            consequences.append("May protect information but risks being caught")
            consequences.append("Could damage trust if discovered")

        elif action_type == ActionType.SHARE_INFO:
            consequences.append("Builds trust with recipient")
            consequences.append("Loses exclusive access to information")

        return "; ".join(consequences) if consequences else "Outcome uncertain"

    def select_best_action(
        self,
        options: list[DecisionOption],
        emotional_state: EmotionalState | None = None,
        belief_system: BeliefSystem | None = None,
    ) -> Decision:
        """Select the best action from available options.

        Args:
            options: List of decision options.
            emotional_state: Current emotional state (optional).
            belief_system: Belief system (optional).

        Returns:
            The selected decision.
        """
        if not options:
            return Decision(
                action="Wait and observe",
                action_type=ActionType.WAIT,
                reasoning="No clear options available",
            )

        scored_options = []
        for option in options:
            score = self._calculate_option_score(
                option,
                emotional_state,
                belief_system,
            )
            option.score = score
            scored_options.append(option)

        scored_options.sort(key=lambda x: x.score, reverse=True)

        best_option = scored_options[0]

        decision = Decision(
            action=best_option.action,
            action_type=best_option.action_type,
            motivation=best_option.description,
            confidence=best_option.score,
            target=best_option.target,
            location=best_option.location,
            reasoning=self._generate_reasoning(best_option, scored_options),
        )

        self._decision_history.append(decision)
        if len(self._decision_history) > self._max_history:
            self._decision_history.pop(0)

        return decision

    def _calculate_option_score(
        self,
        option: DecisionOption,
        emotional_state: EmotionalState | None,
        belief_system: BeliefSystem | None,
    ) -> float:
        """Calculate a score for an option."""
        score = 0.0

        score += option.motivation_alignment * 0.4

        score += option.feasibility * 0.3

        if emotional_state:
            emotional_modifier = self._get_emotional_modifier(
                option.action_type,
                emotional_state,
            )
            score += emotional_modifier * 0.2

        if belief_system:
            belief_modifier = self._get_belief_modifier(option, belief_system)
            score += belief_modifier * 0.1

        return min(1.0, score)

    def _get_emotional_modifier(
        self,
        action_type: ActionType,
        emotional_state: EmotionalState,
    ) -> float:
        """Get modifier based on emotional state."""
        from annie.npc.cognitive.emotional_state import EmotionType

        emotion = emotional_state.primary_emotion

        emotion_action_fit = {
            EmotionType.ANGER: {
                ActionType.ACCUSE: 0.3,
                ActionType.DECEIVE: 0.2,
                ActionType.TALK: 0.1,
            },
            EmotionType.FEAR: {
                ActionType.HIDE_INFO: 0.3,
                ActionType.PROTECT: 0.2,
                ActionType.WAIT: 0.2,
            },
            EmotionType.JOY: {
                ActionType.SHARE_INFO: 0.3,
                ActionType.TALK: 0.2,
            },
            EmotionType.SADNESS: {
                ActionType.REFLECT: 0.3,
                ActionType.WAIT: 0.2,
            },
        }

        fits = emotion_action_fit.get(emotion, {})
        return fits.get(action_type, 0.0)

    def _get_belief_modifier(
        self,
        option: DecisionOption,
        belief_system: BeliefSystem,
    ) -> float:
        """Get modifier based on beliefs."""
        if not option.target:
            return 0.0

        beliefs = belief_system.get_beliefs_about(option.target)
        if not beliefs:
            return 0.0

        avg_confidence = sum(b.confidence for b in beliefs) / len(beliefs)
        return avg_confidence * 0.2

    def _generate_reasoning(
        self,
        selected: DecisionOption,
        all_options: list[DecisionOption],
    ) -> str:
        """Generate reasoning for the decision."""
        reasons = []

        if selected.motivation_alignment > 0.7:
            reasons.append("aligns well with current motivations")

        if selected.feasibility > 0.7:
            reasons.append("highly feasible")

        if len(all_options) > 1:
            second_best = all_options[1]
            reasons.append(f"preferred over '{second_best.action}'")

        return "; ".join(reasons) if reasons else "seemed like the best option"

    def get_decision_history(self, limit: int = 10) -> list[Decision]:
        """Get recent decision history.

        Args:
            limit: Maximum number of decisions to return.

        Returns:
            List of recent decisions.
        """
        return self._decision_history[-limit:]

    def clear_history(self) -> None:
        """Clear decision history."""
        self._decision_history.clear()
