"""Emotional State - Manages NPC emotional states and triggers.

Emotions influence NPC decision-making and behavior.
"""

from __future__ import annotations

from datetime import datetime, timedelta, UTC
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from annie.npc.state import NPCProfile


class EmotionType(str, Enum):
    """Types of emotions."""

    JOY = "joy"
    SADNESS = "sadness"
    ANGER = "anger"
    FEAR = "fear"
    SURPRISE = "surprise"
    DISGUST = "disgust"
    TRUST = "trust"
    ANTICIPATION = "anticipation"
    NEUTRAL = "neutral"


class EmotionIntensity(str, Enum):
    """Intensity levels of emotions."""

    MILD = "mild"
    MODERATE = "moderate"
    STRONG = "strong"
    INTENSE = "intense"


class EmotionalState(BaseModel):
    """Current emotional state of an NPC."""

    primary_emotion: EmotionType = EmotionType.NEUTRAL
    intensity: float = Field(default=0.5, ge=0.0, le=1.0)
    secondary_emotions: dict[EmotionType, float] = Field(default_factory=dict)
    triggers: list[str] = Field(default_factory=list)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def get_intensity_level(self) -> EmotionIntensity:
        """Get the intensity level category."""
        if self.intensity < 0.25:
            return EmotionIntensity.MILD
        elif self.intensity < 0.5:
            return EmotionIntensity.MODERATE
        elif self.intensity < 0.75:
            return EmotionIntensity.STRONG
        else:
            return EmotionIntensity.INTENSE

    def add_secondary_emotion(
        self,
        emotion: EmotionType,
        intensity: float,
    ) -> None:
        """Add a secondary emotion."""
        self.secondary_emotions[emotion] = min(1.0, intensity)

    def get_dominant_emotion(self) -> tuple[EmotionType, float]:
        """Get the dominant emotion and its intensity."""
        if not self.secondary_emotions:
            return self.primary_emotion, self.intensity

        all_emotions = {self.primary_emotion: self.intensity}
        all_emotions.update(self.secondary_emotions)

        dominant = max(all_emotions.items(), key=lambda x: x[1])
        return dominant


class EmotionalTrigger(BaseModel):
    """A trigger that can cause emotional changes."""

    name: str
    emotion: EmotionType
    intensity_delta: float
    conditions: dict = Field(default_factory=dict)
    description: str = ""


class EmotionalStateManager:
    """Manages emotional states for an NPC."""

    def __init__(self) -> None:
        self._current_state = EmotionalState()
        self._emotional_history: list[EmotionalState] = []
        self._triggers: list[EmotionalTrigger] = []
        self._decay_rate: float = 0.1

    def update_from_event(
        self,
        event: str,
        context: dict | None = None,
    ) -> EmotionalState:
        """Update emotional state based on an event.

        Args:
            event: Description of the event.
            context: Additional context for the event.

        Returns:
            The updated emotional state.
        """
        emotion, intensity = self._analyze_event(event, context)

        self._current_state.primary_emotion = emotion
        self._current_state.intensity = intensity
        self._current_state.triggers.append(event)
        self._current_state.timestamp = datetime.now(UTC)

        self._emotional_history.append(self._current_state.model_copy())

        return self._current_state

    def _analyze_event(
        self,
        event: str,
        context: dict | None = None,
    ) -> tuple[EmotionType, float]:
        """Analyze an event to determine emotional response.

        Args:
            event: Event description.
            context: Additional context.

        Returns:
            Tuple of (emotion type, intensity).
        """
        event_lower = event.lower()

        emotion_keywords = {
            EmotionType.JOY: ["高兴", "快乐", "成功", "胜利", "happy", "joy", "success", "win"],
            EmotionType.SADNESS: ["悲伤", "难过", "失败", "死亡", "sad", "loss", "death", "fail"],
            EmotionType.ANGER: ["愤怒", "生气", "背叛", "欺骗", "angry", "betray", "lie", "cheat"],
            EmotionType.FEAR: ["害怕", "恐惧", "威胁", "危险", "fear", "threat", "danger", "scary"],
            EmotionType.SURPRISE: ["惊讶", "意外", "突然", "震惊", "surprise", "shock", "unexpected"],
            EmotionType.DISGUST: ["厌恶", "恶心", "反感", "disgust", "gross", "repulsive"],
            EmotionType.TRUST: ["信任", "相信", "友好", "trust", "believe", "friendly"],
            EmotionType.ANTICIPATION: ["期待", "希望", "预测", "anticipate", "expect", "hope"],
        }

        detected_emotions = {}
        for emotion, keywords in emotion_keywords.items():
            for keyword in keywords:
                if keyword in event_lower:
                    detected_emotions[emotion] = detected_emotions.get(emotion, 0.5) + 0.2

        if not detected_emotions:
            return EmotionType.NEUTRAL, 0.3

        dominant_emotion = max(detected_emotions.items(), key=lambda x: x[1])
        intensity = min(1.0, dominant_emotion[1])

        return dominant_emotion[0], intensity

    def get_current_state(self) -> EmotionalState:
        """Get the current emotional state.

        Returns:
            Current emotional state.
        """
        return self._current_state

    def decay_emotions(self, time_passed: timedelta) -> None:
        """Decay emotional intensity over time.

        Args:
            time_passed: Time elapsed since last update.
        """
        hours_passed = time_passed.total_seconds() / 3600
        decay_amount = self._decay_rate * hours_passed

        self._current_state.intensity = max(
            0.1,
            self._current_state.intensity - decay_amount,
        )

        secondary_decayed = {}
        for emotion, intensity in self._current_state.secondary_emotions.items():
            new_intensity = max(0.0, intensity - decay_amount)
            if new_intensity > 0.05:
                secondary_decayed[emotion] = new_intensity

        self._current_state.secondary_emotions = secondary_decayed

        if self._current_state.intensity < 0.2:
            self._current_state.primary_emotion = EmotionType.NEUTRAL

    def add_trigger(self, trigger: EmotionalTrigger) -> None:
        """Add an emotional trigger.

        Args:
            trigger: The trigger to add.
        """
        self._triggers.append(trigger)

    def check_triggers(self, context: dict) -> list[EmotionalTrigger]:
        """Check if any triggers are activated.

        Args:
            context: Current context to check against.

        Returns:
            List of activated triggers.
        """
        activated = []
        for trigger in self._triggers:
            if self._check_trigger_conditions(trigger, context):
                activated.append(trigger)

        return activated

    def _check_trigger_conditions(
        self,
        trigger: EmotionalTrigger,
        context: dict,
    ) -> bool:
        """Check if trigger conditions are met."""
        for key, value in trigger.conditions.items():
            if context.get(key) != value:
                return False
        return True

    def apply_trigger(self, trigger: EmotionalTrigger) -> None:
        """Apply an emotional trigger.

        Args:
            trigger: The trigger to apply.
        """
        self._current_state.primary_emotion = trigger.emotion
        self._current_state.intensity = min(
            1.0,
            self._current_state.intensity + trigger.intensity_delta,
        )
        self._current_state.triggers.append(trigger.name)
        self._current_state.timestamp = datetime.now(UTC)

    def get_emotional_history(
        self,
        limit: int = 10,
    ) -> list[EmotionalState]:
        """Get recent emotional history.

        Args:
            limit: Maximum number of states to return.

        Returns:
            List of past emotional states.
        """
        return self._emotional_history[-limit:]

    def initialize_from_profile(self, npc_profile: NPCProfile) -> None:
        """Initialize emotional tendencies from NPC profile.

        Args:
            npc_profile: The NPC's character profile.
        """
        traits = [t.lower() for t in npc_profile.personality.traits]

        if any(t in traits for t in ["calm", "冷静", "rational", "理性"]):
            self._decay_rate = 0.15
        elif any(t in traits for t in ["emotional", "感性", "passionate", "热情"]):
            self._decay_rate = 0.05

        if any(t in traits for t in ["optimistic", "乐观", "cheerful", "开朗"]):
            self._current_state.primary_emotion = EmotionType.JOY
            self._current_state.intensity = 0.3
        elif any(t in traits for t in ["pessimistic", "悲观", "anxious", "焦虑"]):
            self._current_state.primary_emotion = EmotionType.FEAR
            self._current_state.intensity = 0.3

    def set_emotion(
        self,
        emotion: EmotionType,
        intensity: float,
    ) -> None:
        """Directly set the emotional state.

        Args:
            emotion: The emotion to set.
            intensity: The intensity (0-1).
        """
        self._current_state.primary_emotion = emotion
        self._current_state.intensity = intensity
        self._current_state.timestamp = datetime.now(UTC)

    def get_mood_description(self) -> str:
        """Get a text description of current mood.

        Returns:
            Human-readable mood description.
        """
        emotion = self._current_state.primary_emotion
        intensity = self._current_state.get_intensity_level()

        mood_descriptions = {
            EmotionType.JOY: {
                EmotionIntensity.MILD: "slightly pleased",
                EmotionIntensity.MODERATE: "happy",
                EmotionIntensity.STRONG: "very happy",
                EmotionIntensity.INTENSE: "overjoyed",
            },
            EmotionType.SADNESS: {
                EmotionIntensity.MILD: "slightly down",
                EmotionIntensity.MODERATE: "sad",
                EmotionIntensity.STRONG: "very sad",
                EmotionIntensity.INTENSE: "devastated",
            },
            EmotionType.ANGER: {
                EmotionIntensity.MILD: "slightly annoyed",
                EmotionIntensity.MODERATE: "angry",
                EmotionIntensity.STRONG: "very angry",
                EmotionIntensity.INTENSE: "furious",
            },
            EmotionType.FEAR: {
                EmotionIntensity.MILD: "slightly worried",
                EmotionIntensity.MODERATE: "afraid",
                EmotionIntensity.STRONG: "very scared",
                EmotionIntensity.INTENSE: "terrified",
            },
            EmotionType.NEUTRAL: {
                EmotionIntensity.MILD: "calm",
                EmotionIntensity.MODERATE: "calm",
                EmotionIntensity.STRONG: "calm",
                EmotionIntensity.INTENSE: "calm",
            },
        }

        descriptions = mood_descriptions.get(emotion, mood_descriptions[EmotionType.NEUTRAL])
        return descriptions.get(intensity, "neutral")
