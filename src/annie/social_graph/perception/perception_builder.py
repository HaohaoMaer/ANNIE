"""Perception Builder — Level 3 of the Perception Pipeline.

Assembles a filtered + evaluated knowledge set into an NPC's subjective
worldview.  Pure assembly logic — no additional judgment.
"""

from __future__ import annotations

from annie.npc.state import EnrichedRelationshipDef
from annie.social_graph.models import BeliefStatus, KnowledgeItem, RelationshipEdge
from annie.social_graph.perception.belief_evaluator import BeliefEvaluator
from annie.social_graph.perception.knowledge_filter import KnowledgeFilter


def _trust_label(trust: float) -> str:
    if trust >= 0.7:
        return "high"
    if trust >= 0.4:
        return "moderate"
    return "low"


def _valence_label(v: float) -> str:
    if v >= 0.3:
        return "positive"
    if v <= -0.3:
        return "negative"
    return "neutral"


def _belief_label(ki: KnowledgeItem) -> str:
    source = "witnessed" if ki.source_npc is None else f"heard from {ki.source_npc}"
    return f"[{ki.belief_status.value.upper()}] {ki.summary} ({source})"


class PerceptionBuilder:
    """Builds an NPC's subjective worldview from filtered + evaluated data."""

    def __init__(
        self,
        knowledge_filter: KnowledgeFilter,
        belief_evaluator: BeliefEvaluator,
    ) -> None:
        self._filter = knowledge_filter
        self._evaluator = belief_evaluator

    # ------------------------------------------------------------------
    # Perceived relationships
    # ------------------------------------------------------------------

    def build_perceived_relationships(
        self, npc_name: str
    ) -> list[EnrichedRelationshipDef]:
        """Return the NPC's subjective relationship list.

        Only includes edges the NPC is aware of.  Converts raw
        ``RelationshipEdge`` objects to ``EnrichedRelationshipDef``.
        """
        raw_edges = self._filter.get_known_relationships(npc_name)
        result: list[EnrichedRelationshipDef] = []
        for edge in raw_edges:
            target = edge.target if edge.source == npc_name else edge.source
            result.append(EnrichedRelationshipDef(
                target=target,
                type=edge.type,
                intensity=edge.intensity,
                trust=edge.trust,
                familiarity=edge.familiarity,
                emotional_valence=edge.emotional_valence,
                status=edge.status,
            ))
        return result

    # ------------------------------------------------------------------
    # Perceived events
    # ------------------------------------------------------------------

    def build_perceived_events(
        self, npc_name: str
    ) -> list[dict]:
        """Return the NPC's subjective event list.

        Excludes REJECTED events.  Each dict contains:
        ``summary``, ``belief_status``, ``credibility``, ``source``,
        ``learned_at``, ``event_id``.
        """
        raw_items = self._filter.get_known_events(npc_name)
        evaluated = self._evaluator.evaluate(npc_name, raw_items)
        result: list[dict] = []
        for ki in evaluated:
            if ki.belief_status == BeliefStatus.REJECTED:
                continue
            result.append({
                "event_id": ki.event_id,
                "summary": ki.summary,
                "belief_status": ki.belief_status.value,
                "credibility": ki.credibility,
                "source": ki.source_npc,
                "learned_at": ki.learned_at,
            })
        return result

    # ------------------------------------------------------------------
    # Full social context string (for NPC Agent)
    # ------------------------------------------------------------------

    def build_social_context(self, npc_name: str, query: str = "") -> str:
        """Build a human-readable social context string for the NPC Agent.

        This is what gets injected into the Planner/Executor prompt as the
        NPC's social knowledge.
        """
        sections: list[str] = []

        # --- Relationships ---
        rels = self.build_perceived_relationships(npc_name)
        if rels:
            lines = []
            for r in rels:
                trust_s = _trust_label(r.trust)
                valence_s = _valence_label(r.emotional_valence)
                lines.append(
                    f"- {r.target}: {r.type} (trust={trust_s}, warmth={valence_s})"
                )
            sections.append("Relationships (my perception):\n" + "\n".join(lines))

        # --- Events ---
        events = self.build_perceived_events(npc_name)
        if events:
            lines = []
            for e in events:
                source = "witnessed" if e["source"] is None else f"heard from {e['source']}"
                lines.append(
                    f"- [{e['belief_status'].upper()}] {e['summary']} ({source})"
                )
            sections.append("Events I know about:\n" + "\n".join(lines))

        # --- Unresolved (SKEPTICAL / DOUBTED) ---
        raw_items = self._filter.get_known_events(npc_name)
        evaluated = self._evaluator.evaluate(npc_name, raw_items)
        unresolved = [
            ki for ki in evaluated
            if ki.belief_status in (BeliefStatus.SKEPTICAL, BeliefStatus.DOUBTED)
        ]
        if unresolved:
            lines = [f"- {ki.summary} (credibility={ki.credibility:.1f})" for ki in unresolved]
            sections.append("Unresolved concerns:\n" + "\n".join(lines))

        if not sections:
            return "No social knowledge available."
        return "\n\n".join(sections)
