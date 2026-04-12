"""Memory Agent — Phase 1 cleanup.

RelationshipMemory removed; relationship-type notes are now semantic-store
entries tagged via metadata. Phase 3 turns this into a MemoryInterface
adapter.
"""

from __future__ import annotations

from datetime import UTC, datetime

from annie.npc.memory.episodic import EpisodicMemory
from annie.npc.memory.semantic import SemanticMemory

_MIN_RELEVANCE_SCORE: float = 0.35
_BUILD_CONTEXT_MAX_CHARS: int = 1500


class MemoryAgent:
    """Wraps episodic + semantic memory with unified access."""

    def __init__(self, episodic: EpisodicMemory, semantic: SemanticMemory):
        self.episodic = episodic
        self.semantic = semantic

    def search_semantic(self, query: str, memory_type: str = "all", k: int = 5) -> list[dict]:
        seen: set[str] = set()
        results: list[dict] = []
        if memory_type in ("episodic", "all"):
            for e in self.episodic.retrieve(query, k=k):
                if e.relevance_score >= _MIN_RELEVANCE_SCORE and e.content not in seen:
                    seen.add(e.content)
                    results.append({"content": e.content, "source": "episodic", "relevance_score": e.relevance_score})
        if memory_type in ("knowledge", "all"):
            for f in self.semantic.retrieve(query, k=k):
                if f.relevance_score >= _MIN_RELEVANCE_SCORE and f.content not in seen:
                    seen.add(f.content)
                    results.append({"content": f.content, "source": "semantic", "relevance_score": f.relevance_score})
        results.sort(key=lambda x: x["relevance_score"], reverse=True)
        return results

    def search_keyword(self, keywords: list[str], memory_type: str = "episodic", k: int = 10) -> list[dict]:
        seen: set[str] = set()
        results: list[dict] = []

        def _matches(text: str) -> bool:
            t = text.lower()
            return any(kw.lower() in t for kw in keywords)

        if memory_type in ("episodic", "all"):
            recent = self.episodic.get_recent(n=200)
            for e in recent:
                if _matches(e.content) and e.content not in seen:
                    seen.add(e.content)
                    results.append({"content": e.content, "source": "episodic"})
        if memory_type == "all":
            all_facts = self.semantic.retrieve(" ".join(keywords), k=50)
            for f in all_facts:
                if _matches(f.content) and f.content not in seen:
                    seen.add(f.content)
                    results.append({"content": f.content, "source": "semantic"})
        return results[:k]

    def build_context(self, query: str, k: int = 5, max_chars: int = _BUILD_CONTEXT_MAX_CHARS) -> str:
        seen: set[str] = set()
        sections: list[str] = []
        episodes = self.episodic.retrieve(query, k=k)
        ep_lines = []
        for e in episodes:
            if e.relevance_score >= _MIN_RELEVANCE_SCORE and e.content not in seen:
                seen.add(e.content)
                ep_lines.append(f"- {e.content}")
        if ep_lines:
            sections.append("Recent experiences:\n" + "\n".join(ep_lines))
        facts = self.semantic.retrieve(query, k=k)
        fact_lines = []
        for f in facts:
            if f.relevance_score >= _MIN_RELEVANCE_SCORE and f.content not in seen:
                seen.add(f.content)
                fact_lines.append(f"- {f.content}")
        if fact_lines:
            sections.append("Known facts:\n" + "\n".join(fact_lines))
        result = "\n\n".join(sections) if sections else "No relevant memories."
        if len(result) > max_chars:
            result = result[:max_chars] + "\n[memory truncated]"
        return result

    def store_episodic(self, event: str, timestamp: datetime | None = None, metadata: dict | None = None) -> str:
        return self.episodic.store(event, timestamp=timestamp or datetime.now(UTC), metadata=metadata)

    def store_semantic(self, fact: str, category: str = "general") -> str:
        return self.semantic.store(fact, category=category)

    def store_relationship_note(self, person: str, observation: str) -> str:
        """Relationship notes live in semantic store tagged with metadata."""
        return self.semantic.store(observation, category="relationship", metadata={"person": person})
