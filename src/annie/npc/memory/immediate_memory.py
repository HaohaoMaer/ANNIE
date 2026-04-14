"""Immediate Memory (Layer 1) - The NPC's current conscious focus.

Acts as a lightweight index/directory analogous to Claude Code's MEMORY.md:
- Stores pointers (topic tags) to Layer-2 knowledge chunks
- Holds the NPC's currently active beliefs and focus items
- Injected directly into the dynamic system prompt each turn
- Hard-capped at max_tokens to prevent context bloat

Updated:
- At the START of each run(): refresh active_focus from top-5 L2 topics
- At the END of each run() (after Reflector): refresh active_beliefs from new facts
"""

from __future__ import annotations

from dataclasses import dataclass, field

# Approximate chars-per-token ratio for CJK text
_CHARS_PER_TOKEN: float = 2.0


@dataclass
class ImmediateMemory:
    """NPC's current working memory — small, fast, always in context."""

    active_focus: list[str] = field(default_factory=list)
    """Current entities/topics the NPC is paying attention to (max 5)."""

    active_beliefs: list[str] = field(default_factory=list)
    """Currently strongest beliefs — updated from Reflector facts (max 5)."""

    topic_pointers: list[str] = field(default_factory=list)
    """Tags of Layer-2 knowledge chunks relevant this turn (for retrieval hints)."""

    max_tokens: int = 500

    _MAX_FOCUS: int = 5
    _MAX_BELIEFS: int = 5

    def update_focus(self, items: list[str]) -> None:
        """Replace active focus with the most relevant items (capped at _MAX_FOCUS)."""
        self.active_focus = items[: self._MAX_FOCUS]

    def update_beliefs(self, beliefs: list[str]) -> None:
        """Update active beliefs (capped at _MAX_BELIEFS)."""
        self.active_beliefs = beliefs[: self._MAX_BELIEFS]

    def add_belief(self, belief: str) -> None:
        """Insert a new belief, evicting the oldest if at capacity."""
        if belief not in self.active_beliefs:
            self.active_beliefs.insert(0, belief)
            if len(self.active_beliefs) > self._MAX_BELIEFS:
                self.active_beliefs = self.active_beliefs[: self._MAX_BELIEFS]

    def set_topic_pointers(self, tags: list[str]) -> None:
        """Set the Layer-2 topic tags retrieved this turn."""
        self.topic_pointers = tags

    def to_prompt_str(self) -> str:
        """Render the immediate memory as a compact string for system prompt injection."""
        parts: list[str] = []
        if self.active_focus:
            parts.append("Current focus: " + ", ".join(self.active_focus))
        if self.active_beliefs:
            parts.append("Active beliefs:\n" + "\n".join(f"- {b}" for b in self.active_beliefs))
        result = "\n".join(parts)
        # Hard cap
        max_chars = int(self.max_tokens * _CHARS_PER_TOKEN)
        if len(result) > max_chars:
            result = result[:max_chars] + "\n[immediate memory truncated]"
        return result

    def estimate_tokens(self) -> int:
        """Rough token estimate for the current content."""
        return max(0, int(len(self.to_prompt_str()) / _CHARS_PER_TOKEN))
