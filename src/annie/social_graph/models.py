"""Data models for the Social Graph layer.

Defines the core data structures for Phase 2:
- RelationshipEdge: multi-dimensional relationship between two NPCs (god's-eye truth)
- GraphDelta: a single field change to apply to a RelationshipEdge
- EventVisibility: how widely an event can be known
- SocialEvent: an append-only record of something that happened
- BeliefStatus: how much an NPC believes a piece of information
- KnowledgeItem: what an NPC knows (or thinks they know) about an event
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import Enum

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Relationship Edge (god's-eye truth stored in SocialGraph)
# ---------------------------------------------------------------------------

class RelationshipEdge(BaseModel):
    """A directed relationship from *source* to *target*.

    All numeric fields are clamped on assignment:
    - intensity, trust, familiarity: [0, 1]
    - emotional_valence: [-1, 1]
    """

    source: str
    target: str
    type: str = "acquaintance"
    intensity: float = 0.5
    trust: float = 0.5
    familiarity: float = 0.0
    emotional_valence: float = 0.0
    status: str = "active"  # active / broken / dormant
    shared_history: list[str] = Field(default_factory=list)
    last_interaction: datetime | None = None


# ---------------------------------------------------------------------------
# Graph Delta
# ---------------------------------------------------------------------------

class GraphDelta(BaseModel):
    """A single numeric change to apply to a RelationshipEdge field."""

    source: str
    target: str
    field: str  # must match a numeric field on RelationshipEdge
    delta: float
    reason: str = ""


# ---------------------------------------------------------------------------
# Event Visibility
# ---------------------------------------------------------------------------

class EventVisibility(str, Enum):
    """How widely an event can be known."""

    PUBLIC = "public"        # all NPCs learn immediately
    WITNESSED = "witnessed"  # witnesses + trust-chain propagation
    PRIVATE = "private"      # actor + target only; no automatic spread
    SECRET = "secret"        # actor + target only; gossip requires trust >= 0.7


# ---------------------------------------------------------------------------
# Social Event
# ---------------------------------------------------------------------------

class SocialEvent(BaseModel):
    """An immutable record of something that happened in the world."""

    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    actor: str
    target: str | None = None
    action: str
    description: str
    location: str = ""
    witnesses: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    visibility: EventVisibility = EventVisibility.WITNESSED
    graph_deltas: list[GraphDelta] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Belief Status
# ---------------------------------------------------------------------------

class BeliefStatus(str, Enum):
    """How much an NPC believes a piece of information."""

    ACCEPTED = "accepted"    # fully believed (first-hand or high-trust source)
    SKEPTICAL = "skeptical"  # half-believed (medium trust or mild conflict)
    DOUBTED = "doubted"      # largely disbelieved (low trust or strong conflict)
    REJECTED = "rejected"    # disbelieved entirely (contradicts known truth or enemy source)


# ---------------------------------------------------------------------------
# Knowledge Item
# ---------------------------------------------------------------------------

class KnowledgeItem(BaseModel):
    """What an NPC knows — or thinks they know — about a SocialEvent.

    Each NPC may hold a different KnowledgeItem for the same event,
    with different distortion, credibility, and belief status.
    """

    event_id: str
    knower: str
    learned_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source_npc: str | None = None  # None means first-hand witness
    distortion: float = 0.0        # 0 = accurate, higher = more distorted
    summary: str                   # what the NPC actually believes happened
    belief_status: BeliefStatus = BeliefStatus.ACCEPTED
    credibility: float = 1.0       # 0~1, NPC's confidence in this info
    conflicting_with: list[str] = Field(default_factory=list)  # event_ids of conflicting knowledge
