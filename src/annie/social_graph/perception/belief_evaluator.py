"""Belief Evaluator — Level 2 of the Perception Pipeline.

Decides whether an NPC *believes* each piece of knowledge it holds.
Updates ``belief_status`` and ``credibility`` on KnowledgeItems based on:
  1. First-hand vs. second-hand
  2. Source trust level
  3. Conflict with existing accepted knowledge
"""

from __future__ import annotations

from annie.social_graph.graph import SocialGraph
from annie.social_graph.models import BeliefStatus, KnowledgeItem

# Credibility thresholds for belief-status assignment.
_THRESHOLD_ACCEPTED = 0.7
_THRESHOLD_SKEPTICAL = 0.4
_THRESHOLD_DOUBTED = 0.15

# Trust-based credibility brackets.
_HIGH_TRUST = 0.7
_MED_TRUST = 0.3

_CREDIBILITY_HIGH_TRUST = 0.8
_CREDIBILITY_MED_TRUST = 0.5
_CREDIBILITY_LOW_TRUST = 0.2
_CREDIBILITY_ENEMY = 0.1

# Conflict cap — if a new item conflicts with an accepted item, cap its
# credibility so it never lands higher than SKEPTICAL.
_CONFLICT_CREDIBILITY_CAP = 0.4


class BeliefEvaluator:
    """Evaluates belief status for a list of KnowledgeItems."""

    def __init__(self, graph: SocialGraph) -> None:
        self._graph = graph

    def evaluate(
        self,
        npc_name: str,
        knowledge_items: list[KnowledgeItem],
    ) -> list[KnowledgeItem]:
        """Evaluate each item's credibility and belief_status.

        Returns a **new** list of KnowledgeItems with updated fields.
        The originals are not mutated.
        """
        evaluated: list[KnowledgeItem] = []

        for item in knowledge_items:
            new_item = item.model_copy()

            # 1. First-hand → always ACCEPTED.
            if new_item.source_npc is None:
                new_item.credibility = 1.0
                new_item.belief_status = BeliefStatus.ACCEPTED
                evaluated.append(new_item)
                continue

            # 2. Determine base credibility from source trust.
            base = self._credibility_from_trust(npc_name, new_item.source_npc)

            # 3. Conflict detection against already-evaluated (accepted) items.
            conflict_ids: list[str] = []
            for prev in evaluated:
                if prev.belief_status != BeliefStatus.ACCEPTED:
                    continue
                if self._items_conflict(prev, new_item):
                    conflict_ids.append(prev.event_id)
            if conflict_ids:
                base = min(base, _CONFLICT_CREDIBILITY_CAP)
                new_item.conflicting_with = conflict_ids

            # 4. Assign final credibility and belief status.
            new_item.credibility = max(0.0, min(1.0, base))
            new_item.belief_status = _status_from_credibility(new_item.credibility)
            evaluated.append(new_item)

        return evaluated

    def get_conflicts(
        self,
        npc_name: str,
        knowledge_items: list[KnowledgeItem],
    ) -> list[tuple[KnowledgeItem, KnowledgeItem]]:
        """Return pairs of conflicting items (for debugging / display)."""
        evaluated = self.evaluate(npc_name, knowledge_items)
        pairs: list[tuple[KnowledgeItem, KnowledgeItem]] = []
        item_map = {ki.event_id: ki for ki in evaluated}

        for ki in evaluated:
            for cid in ki.conflicting_with:
                other = item_map.get(cid)
                if other is not None:
                    pairs.append((ki, other))
        return pairs

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _credibility_from_trust(self, knower: str, source: str) -> float:
        """Map the trust score on the knower→source edge to a credibility value."""
        edge = self._graph.get_edge(knower, source)
        if edge is None:
            return _CREDIBILITY_LOW_TRUST

        # Enemy override.
        if edge.type == "enemy":
            return _CREDIBILITY_ENEMY

        if edge.trust >= _HIGH_TRUST:
            return _CREDIBILITY_HIGH_TRUST
        if edge.trust >= _MED_TRUST:
            return _CREDIBILITY_MED_TRUST
        return _CREDIBILITY_LOW_TRUST

    @staticmethod
    def _items_conflict(a: KnowledgeItem, b: KnowledgeItem) -> bool:
        """Heuristic: two items conflict if they mention the same actor/target
        pair but with opposing sentiment keywords."""
        # Simple keyword-overlap approach for Phase 2.
        positive = {"praised", "helped", "supported", "defended", "praised", "trusted", "allied"}
        negative = {"accused", "attacked", "betrayed", "stole", "tampered", "threatened", "lied"}

        a_words = set(a.summary.lower().split())
        b_words = set(b.summary.lower().split())

        a_pos = bool(a_words & positive)
        a_neg = bool(a_words & negative)
        b_pos = bool(b_words & positive)
        b_neg = bool(b_words & negative)

        # Conflict = one positive and one negative about overlapping subjects.
        if (a_pos and b_neg) or (a_neg and b_pos):
            # Check that they share at least one proper-noun-like token
            # (capitalized word longer than 2 chars).
            a_names = {w for w in a.summary.split() if w[0].isupper() and len(w) > 2}
            b_names = {w for w in b.summary.split() if w[0].isupper() and len(w) > 2}
            if a_names & b_names:
                return True
        return False


def _status_from_credibility(credibility: float) -> BeliefStatus:
    if credibility >= _THRESHOLD_ACCEPTED:
        return BeliefStatus.ACCEPTED
    if credibility >= _THRESHOLD_SKEPTICAL:
        return BeliefStatus.SKEPTICAL
    if credibility >= _THRESHOLD_DOUBTED:
        return BeliefStatus.DOUBTED
    return BeliefStatus.REJECTED
