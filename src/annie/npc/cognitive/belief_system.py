"""Belief System - Manages NPC beliefs about the world, self, and others.

Beliefs represent what the NPC thinks is true, with varying confidence levels.
"""

from __future__ import annotations

from datetime import datetime, UTC
from enum import Enum
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from annie.npc.state import NPCProfile


class BeliefCategory(str, Enum):
    """Category of belief."""

    WORLD = "world"
    SELF = "self"
    OTHER = "other"
    EVENT = "event"
    FACT = "fact"
    RUMOR = "rumor"
    SECRET = "secret"


class BeliefStatus(str, Enum):
    """Status of a belief."""

    ACTIVE = "active"
    DOUBTFUL = "doubtful"
    DISPROVEN = "disproven"
    CONFIRMED = "confirmed"


class Belief(BaseModel):
    """A single belief held by an NPC."""

    content: str
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    category: BeliefCategory = BeliefCategory.FACT
    status: BeliefStatus = BeliefStatus.ACTIVE
    source: str = "unknown"
    subject: str | None = None
    last_updated: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    evidence: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)

    def strengthen(self, amount: float = 0.1) -> None:
        """Increase confidence in this belief."""
        self.confidence = min(1.0, self.confidence + amount)
        self.last_updated = datetime.now(UTC)

    def weaken(self, amount: float = 0.1) -> None:
        """Decrease confidence in this belief."""
        self.confidence = max(0.0, self.confidence - amount)
        self.last_updated = datetime.now(UTC)
        if self.confidence < 0.3:
            self.status = BeliefStatus.DOUBTFUL

    def add_evidence(self, evidence: str) -> None:
        """Add supporting evidence."""
        self.evidence.append(evidence)
        self.strengthen(0.1)

    def add_contradiction(self, contradiction: str) -> None:
        """Add contradicting evidence."""
        self.contradictions.append(contradiction)
        self.weaken(0.15)


class BeliefSystem:
    """Manages all beliefs held by an NPC."""

    def __init__(self) -> None:
        self._beliefs: dict[str, Belief] = {}
        self._belief_index: dict[str, list[str]] = {}

    def add_belief(self, belief: Belief) -> None:
        """Add a new belief to the system.

        Args:
            belief: The belief to add.
        """
        belief_id = self._generate_belief_id(belief)
        self._beliefs[belief_id] = belief

        self._index_belief(belief_id, belief)

    def _generate_belief_id(self, belief: Belief) -> str:
        """Generate a unique ID for a belief."""
        import hashlib
        content_hash = hashlib.md5(belief.content.encode()).hexdigest()[:8]
        return f"{belief.category.value}_{content_hash}"

    def _index_belief(self, belief_id: str, belief: Belief) -> None:
        """Index belief by category and subject."""
        category_key = f"category:{belief.category.value}"
        if category_key not in self._belief_index:
            self._belief_index[category_key] = []
        self._belief_index[category_key].append(belief_id)

        if belief.subject:
            subject_key = f"subject:{belief.subject}"
            if subject_key not in self._belief_index:
                self._belief_index[subject_key] = []
            self._belief_index[subject_key].append(belief_id)

    def get_beliefs_about(self, subject: str) -> list[Belief]:
        """Get all beliefs about a specific subject.

        Args:
            subject: The subject to query.

        Returns:
            List of beliefs about the subject.
        """
        subject_key = f"subject:{subject}"
        belief_ids = self._belief_index.get(subject_key, [])
        return [self._beliefs[bid] for bid in belief_ids if bid in self._beliefs]

    def get_beliefs_by_category(
        self,
        category: BeliefCategory,
    ) -> list[Belief]:
        """Get all beliefs of a specific category.

        Args:
            category: The category to query.

        Returns:
            List of beliefs in that category.
        """
        category_key = f"category:{category.value}"
        belief_ids = self._belief_index.get(category_key, [])
        return [self._beliefs[bid] for bid in belief_ids if bid in self._beliefs]

    def update_belief(
        self,
        content: str,
        new_confidence: float,
    ) -> Belief | None:
        """Update confidence in a belief.

        Args:
            content: Content to match.
            new_confidence: New confidence value.

        Returns:
            Updated belief, or None if not found.
        """
        for belief in self._beliefs.values():
            if belief.content == content:
                belief.confidence = new_confidence
                belief.last_updated = datetime.now(UTC)
                return belief
        return None

    def detect_contradictions(self) -> list[tuple[Belief, Belief]]:
        """Detect pairs of contradictory beliefs.

        Returns:
            List of contradictory belief pairs.
        """
        contradictions = []

        beliefs_list = list(self._beliefs.values())
        for i, b1 in enumerate(beliefs_list):
            for b2 in beliefs_list[i + 1:]:
                if self._are_contradictory(b1, b2):
                    contradictions.append((b1, b2))

        return contradictions

    def _are_contradictory(self, b1: Belief, b2: Belief) -> bool:
        """Check if two beliefs are contradictory."""
        if b1.subject != b2.subject:
            return False

        if b1.category != b2.category:
            return False

        negation_words = ["不", "没有", "不是", "not", "no", "never"]
        b1_has_negation = any(w in b1.content.lower() for w in negation_words)
        b2_has_negation = any(w in b2.content.lower() for w in negation_words)

        return b1_has_negation != b2_has_negation

    def resolve_contradiction(
        self,
        belief1: Belief,
        belief2: Belief,
        keep: int = 1,
    ) -> None:
        """Resolve a contradiction between two beliefs.

        Args:
            belief1: First belief.
            belief2: Second belief.
            keep: Which belief to keep (1 or 2).
        """
        if keep == 1:
            belief1.strengthen(0.2)
            belief2.weaken(0.3)
            belief2.status = BeliefStatus.DOUBTFUL
        else:
            belief2.strengthen(0.2)
            belief1.weaken(0.3)
            belief1.status = BeliefStatus.DOUBTFUL

    def get_strongest_beliefs(self, limit: int = 5) -> list[Belief]:
        """Get the beliefs with highest confidence.

        Args:
            limit: Maximum number to return.

        Returns:
            List of strongest beliefs.
        """
        sorted_beliefs = sorted(
            self._beliefs.values(),
            key=lambda b: b.confidence,
            reverse=True,
        )
        return sorted_beliefs[:limit]

    def get_weak_beliefs(self, threshold: float = 0.3) -> list[Belief]:
        """Get beliefs with low confidence.

        Args:
            threshold: Confidence threshold.

        Returns:
            List of weak beliefs.
        """
        return [
            b for b in self._beliefs.values()
            if b.confidence < threshold
        ]

    def remove_disproven(self) -> int:
        """Remove all disproven beliefs.

        Returns:
            Number of beliefs removed.
        """
        to_remove = [
            bid for bid, b in self._beliefs.items()
            if b.status == BeliefStatus.DISPROVEN
        ]
        for bid in to_remove:
            del self._beliefs[bid]

        self._rebuild_index()
        return len(to_remove)

    def _rebuild_index(self) -> None:
        """Rebuild the belief index."""
        self._belief_index.clear()
        for belief_id, belief in self._beliefs.items():
            self._index_belief(belief_id, belief)

    def initialize_from_profile(self, npc_profile: NPCProfile) -> None:
        """Initialize beliefs from NPC profile.

        Args:
            npc_profile: The NPC's character profile.
        """
        if npc_profile.background.biography:
            self.add_belief(Belief(
                content=f"I am {npc_profile.name}",
                category=BeliefCategory.SELF,
                confidence=1.0,
                source="profile",
            ))

        for trait in npc_profile.personality.traits:
            self.add_belief(Belief(
                content=f"I am {trait}",
                category=BeliefCategory.SELF,
                confidence=0.9,
                source="profile",
            ))

        for event in npc_profile.background.past_events:
            self.add_belief(Belief(
                content=event,
                category=BeliefCategory.EVENT,
                confidence=0.8,
                source="memory",
            ))

        for rel in npc_profile.relationships:
            self.add_belief(Belief(
                content=f"{rel.target} is my {rel.type}",
                category=BeliefCategory.OTHER,
                confidence=0.8,
                source="profile",
                subject=rel.target,
            ))

    def get_belief_count(self) -> int:
        """Get total number of beliefs."""
        return len(self._beliefs)

    def to_dict(self) -> dict:
        """Export beliefs to a dictionary."""
        return {
            "beliefs": {
                bid: belief.model_dump()
                for bid, belief in self._beliefs.items()
            },
            "index": self._belief_index,
        }
