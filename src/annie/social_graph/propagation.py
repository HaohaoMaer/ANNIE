"""Propagation Engine - Controls how information spreads through the social graph.

Determines *who might hear about* an event and with what fidelity.
Does NOT decide whether an NPC believes the information — that is the
BeliefEvaluator's job in the Perception Pipeline.

Two semantic-filtering dimensions (personality dimension deferred to Phase 3):
  A. Relationship-type willingness — how likely a holder is to share with a given relation
  B. Event visibility level — PUBLIC / WITNESSED / PRIVATE / SECRET
"""

from __future__ import annotations

from collections import deque
from datetime import UTC, datetime

from annie.social_graph.event_log import SocialEventLog
from annie.social_graph.graph import SocialGraph
from annie.social_graph.models import (
    BeliefStatus,
    EventVisibility,
    KnowledgeItem,
    SocialEvent,
)

# ---------------------------------------------------------------------------
# Relationship-type willingness to propagate (0 = never, 1 = always)
# ---------------------------------------------------------------------------
WILLINGNESS: dict[str, float] = {
    "trusted_ally": 0.9,
    "friend": 0.8,
    "mentor": 0.7,
    "trade_partner": 0.5,
    "acquaintance": 0.3,
    "rival": 0.2,
    "enemy": 0.1,
}
_DEFAULT_WILLINGNESS = 0.4

# Enemies / rivals add extra distortion when they do propagate.
_HOSTILE_TYPES = {"enemy", "rival"}
_HOSTILE_EXTRA_DISTORTION = 0.3

# ---------------------------------------------------------------------------
# Propagation parameters
# ---------------------------------------------------------------------------
_DISTORTION_PER_HOP = 0.15
_MAX_DEPTH = 2
_MIN_PROPAGATION_PROBABILITY = 0.15
_SECRET_TRUST_THRESHOLD = 0.7

# Distorted-summary prefixes per hop depth.
_DISTORTION_PREFIXES = [
    "",                     # depth 0: first-hand
    "Reportedly, ",         # depth 1: one hop away
    "Rumor has it that ",   # depth 2: two hops away
]


class PropagationEngine:
    """Spreads event knowledge through the social graph.

    After an event is logged in the SocialEventLog, calling
    ``propagate_event`` determines which NPCs learn about it and creates
    KnowledgeItem records in the SocialGraph.
    """

    def __init__(self, graph: SocialGraph, event_log: SocialEventLog) -> None:
        self._graph = graph
        self._event_log = event_log
        # Track which events have been fully propagated (id -> set of informed NPCs).
        self._propagated: dict[str, set[str]] = {}

    # ------------------------------------------------------------------
    # Core propagation
    # ------------------------------------------------------------------

    def propagate_event(
        self,
        event: SocialEvent,
        all_npc_names: list[str] | None = None,
    ) -> list[KnowledgeItem]:
        """Determine who learns about *event* and record KnowledgeItems.

        Returns the list of newly created KnowledgeItems.
        """
        if all_npc_names is None:
            all_npc_names = self._graph.get_all_npcs()

        created: list[KnowledgeItem] = []
        already_knows = self._propagated.setdefault(event.id, set())

        # --- Step 1: determine initial knowers based on visibility ---
        initial_knowers: set[str] = set()

        if event.visibility == EventVisibility.PUBLIC:
            # Everyone learns immediately.
            initial_knowers = set(all_npc_names)
        elif event.visibility in (EventVisibility.WITNESSED, EventVisibility.PRIVATE, EventVisibility.SECRET):
            # Actor always knows.
            if event.actor in all_npc_names:
                initial_knowers.add(event.actor)
            # Target knows (if present and is an NPC).
            if event.target and event.target in all_npc_names:
                initial_knowers.add(event.target)
            # Witnesses know (WITNESSED only).
            if event.visibility == EventVisibility.WITNESSED:
                for w in event.witnesses:
                    if w in all_npc_names:
                        initial_knowers.add(w)

        # Record first-hand knowledge for initial knowers.
        for npc in initial_knowers:
            if npc in already_knows:
                continue
            ki = KnowledgeItem(
                event_id=event.id,
                knower=npc,
                learned_at=event.timestamp,
                source_npc=None,
                distortion=0.0,
                summary=event.description,
                belief_status=BeliefStatus.ACCEPTED,
                credibility=1.0,
            )
            self._graph.record_knowledge(ki)
            created.append(ki)
            already_knows.add(npc)

        # --- Step 2: BFS propagation for WITNESSED events ---
        if event.visibility == EventVisibility.WITNESSED:
            bfs_created = self._bfs_propagate(event, initial_knowers, already_knows)
            created.extend(bfs_created)

        # PRIVATE and SECRET: no automatic propagation beyond principals.

        return created

    def propagate_gossip(
        self,
        spreader: str,
        event_id: str,
        recipients: list[str] | None = None,
        distortion_factor: float = 0.2,
    ) -> list[KnowledgeItem]:
        """Explicit gossip: *spreader* tells others about an event.

        If *recipients* is None, defaults to the spreader's trusted contacts.
        Respects SECRET trust threshold.
        """
        event = self._event_log.get(event_id)
        if event is None:
            return []

        # Spreader must actually know the event.
        spreader_knowledge = self._graph.get_knowledge(spreader, event_id)
        if not spreader_knowledge:
            return []
        spreader_ki = spreader_knowledge[0]

        already_knows = self._propagated.setdefault(event_id, set())

        if recipients is None:
            recipients = self._get_trusted_contacts(spreader, event)

        created: list[KnowledgeItem] = []
        for recipient in recipients:
            if recipient in already_knows:
                continue

            new_distortion = spreader_ki.distortion + distortion_factor
            prefix = _DISTORTION_PREFIXES[min(2, int(new_distortion / _DISTORTION_PER_HOP))]
            base_desc = event.description
            summary = f"{prefix}{base_desc}" if prefix else base_desc

            ki = KnowledgeItem(
                event_id=event_id,
                knower=recipient,
                learned_at=datetime.now(UTC),
                source_npc=spreader,
                distortion=new_distortion,
                summary=summary,
                belief_status=BeliefStatus.ACCEPTED,
                credibility=max(0.0, 1.0 - new_distortion),
            )
            self._graph.record_knowledge(ki)
            created.append(ki)
            already_knows.add(recipient)

        return created

    def tick(self, all_npc_names: list[str] | None = None) -> list[KnowledgeItem]:
        """Process one time-step of propagation.

        Finds WITNESSED events that haven't fully propagated and spreads
        them one hop further.  Returns newly created KnowledgeItems.
        """
        if all_npc_names is None:
            all_npc_names = self._graph.get_all_npcs()

        created: list[KnowledgeItem] = []
        for event in self._event_log.all_events():
            if event.visibility != EventVisibility.WITNESSED:
                continue
            already_knows = self._propagated.get(event.id, set())
            if not already_knows:
                continue
            # Try one more hop from current knowers.
            current_knowers = set(already_knows)
            bfs_created = self._bfs_propagate(
                event, current_knowers, already_knows, max_depth=1,
            )
            created.extend(bfs_created)
        return created

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _bfs_propagate(
        self,
        event: SocialEvent,
        seed_npcs: set[str],
        already_knows: set[str],
        max_depth: int = _MAX_DEPTH,
    ) -> list[KnowledgeItem]:
        """BFS from *seed_npcs* along trust edges."""
        created: list[KnowledgeItem] = []
        # queue items: (npc_name, current_depth, cumulative_distortion, source_npc)
        queue: deque[tuple[str, int, float, str]] = deque()
        for npc in seed_npcs:
            queue.append((npc, 0, 0.0, npc))

        while queue:
            spreader, depth, base_distortion, source = queue.popleft()
            if depth >= max_depth:
                continue

            for edge in self._graph.get_outgoing_edges(spreader):
                recipient = edge.target
                if recipient in already_knows:
                    continue

                willingness = WILLINGNESS.get(edge.type, _DEFAULT_WILLINGNESS)
                probability = edge.trust * willingness
                if probability < _MIN_PROPAGATION_PROBABILITY:
                    continue

                hop_distortion = _DISTORTION_PER_HOP
                if edge.type in _HOSTILE_TYPES:
                    hop_distortion += _HOSTILE_EXTRA_DISTORTION

                new_distortion = base_distortion + hop_distortion
                new_depth = depth + 1

                prefix_idx = min(new_depth, len(_DISTORTION_PREFIXES) - 1)
                prefix = _DISTORTION_PREFIXES[prefix_idx]
                summary = f"{prefix}{event.description}" if prefix else event.description

                ki = KnowledgeItem(
                    event_id=event.id,
                    knower=recipient,
                    learned_at=datetime.now(UTC),
                    source_npc=spreader,
                    distortion=new_distortion,
                    summary=summary,
                    belief_status=BeliefStatus.ACCEPTED,
                    credibility=max(0.0, 1.0 - new_distortion),
                )
                self._graph.record_knowledge(ki)
                created.append(ki)
                already_knows.add(recipient)

                queue.append((recipient, new_depth, new_distortion, spreader))

        return created

    def _get_trusted_contacts(self, npc: str, event: SocialEvent) -> list[str]:
        """Return NPCs that *npc* would share gossip with."""
        contacts = []
        trust_threshold = _SECRET_TRUST_THRESHOLD if event.visibility == EventVisibility.SECRET else 0.3
        for edge in self._graph.get_outgoing_edges(npc):
            if edge.trust >= trust_threshold:
                contacts.append(edge.target)
        return contacts
