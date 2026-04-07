"""Cognitive Layer for NPC decision-making.

This module provides the cognitive architecture that drives NPC behavior,
including motivations, beliefs, emotions, and decision-making.
"""

from annie.npc.cognitive.motivation import Motivation, MotivationEngine
from annie.npc.cognitive.belief_system import Belief, BeliefSystem
from annie.npc.cognitive.emotional_state import EmotionalState, EmotionalStateManager
from annie.npc.cognitive.decision_maker import Decision, DecisionMaker

__all__ = [
    "Motivation",
    "MotivationEngine",
    "Belief",
    "BeliefSystem",
    "EmotionalState",
    "EmotionalStateManager",
    "Decision",
    "DecisionMaker",
]
