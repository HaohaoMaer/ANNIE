"""Context Compressor - Five-tier progressive compression with circuit breaker.

Pure utility class: no world semantics, no game concepts.
The caller (WorldEngine) is responsible for specifying protect_keywords.

Tier thresholds (as fraction of token budget):
  Snip        > 60%: drop least-relevant turns; keep protected ones
  Microcompact> 75%: merge adjacent 3-5 turns into a one-sentence summary
  Collapse    > 85%: fold all old history into one dense paragraph (LLM call)
  Autocompact > 90%: run Collapse at the end of every turn automatically
  Reactive    > 95%: block current turn and run Collapse immediately

Circuit breaker: MAX_COMPRESS_FAILURES consecutive Collapse failures →
stop compressing and hard-truncate to last FALLBACK_TURNS turns.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

logger = logging.getLogger(__name__)

# Approximate chars per token for Chinese text
_CHARS_PER_TOKEN: float = 2.5

_THRESHOLDS = {
    "snip": 0.60,
    "microcompact": 0.75,
    "collapse": 0.85,
    "autocompact": 0.90,
    "reactive": 0.95,
}

MAX_COMPRESS_FAILURES: int = 3
FALLBACK_TURNS: int = 6


class ContextCompressor:
    """Five-tier progressive context compressor.

    Operates on a list of turn dicts:
      {"role": "npc_name", "content": "...", "protected": bool}

    "protected" turns are never dropped at any tier.
    """

    def __init__(
        self,
        token_budget: int = 4000,
        llm: BaseChatModel | None = None,
        protect_keywords: list[str] | None = None,
    ) -> None:
        self._token_budget = token_budget
        self._llm = llm
        self._protect_keywords = [kw.lower() for kw in (protect_keywords or [])]
        self._compress_failures: int = 0
        self._circuit_open: bool = False

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_and_compress(
        self,
        turns: list[dict],
        *,
        force: bool = False,
    ) -> list[dict]:
        """Check utilization and apply appropriate compression tier.

        Args:
            turns: Current dialogue turns (mutated in place, also returned).
            force: Force Collapse regardless of utilization.

        Returns:
            Compressed turns list.
        """
        ratio = self._utilization(turns)

        if force or ratio > _THRESHOLDS["reactive"]:
            return self._reactive_compact(turns)

        if ratio > _THRESHOLDS["autocompact"]:
            return self._autocompact(turns)

        if ratio > _THRESHOLDS["collapse"]:
            return self._collapse(turns)

        if ratio > _THRESHOLDS["microcompact"]:
            return self._microcompact(turns)

        if ratio > _THRESHOLDS["snip"]:
            return self._snip(turns)

        return turns

    def notify_end_of_turn(self, turns: list[dict]) -> list[dict]:
        """Call at the end of each turn when autocompact is desired."""
        if self._utilization(turns) > _THRESHOLDS["autocompact"]:
            return self._autocompact(turns)
        return turns

    def mark_protected(self, turns: list[dict]) -> list[dict]:
        """Mark turns containing protect_keywords as protected (in-place)."""
        if not self._protect_keywords:
            return turns
        for turn in turns:
            content = turn.get("content", "").lower()
            if any(kw in content for kw in self._protect_keywords):
                turn["protected"] = True
        return turns

    # ------------------------------------------------------------------
    # Tier implementations
    # ------------------------------------------------------------------

    def _snip(self, turns: list[dict]) -> list[dict]:
        """Tier 1 (> 60%): Drop non-protected turns with least content."""
        non_protected = [t for t in turns if not t.get("protected")]
        protected = [t for t in turns if t.get("protected")]

        # Sort by content length ascending (shortest = least informative)
        non_protected.sort(key=lambda t: len(t.get("content", "")))

        # Drop up to 20% of non-protected turns
        drop_count = max(1, len(non_protected) // 5)
        kept_non_protected = non_protected[drop_count:]

        # Re-merge preserving original order
        kept_ids = {id(t) for t in kept_non_protected} | {id(t) for t in protected}
        result = [t for t in turns if id(t) in kept_ids]

        dropped = len(turns) - len(result)
        if dropped:
            logger.debug("ContextCompressor.snip: dropped %d turns", dropped)
        return result

    def _microcompact(self, turns: list[dict]) -> list[dict]:
        """Tier 2 (> 75%): Merge adjacent non-protected groups of 3–5 turns."""
        if len(turns) <= 6:
            return turns

        result: list[dict] = []
        buffer: list[dict] = []
        MERGE_SIZE = 4

        for turn in turns:
            if turn.get("protected"):
                if buffer:
                    result.append(self._merge_turns(buffer))
                    buffer = []
                result.append(turn)
            else:
                buffer.append(turn)
                if len(buffer) >= MERGE_SIZE:
                    result.append(self._merge_turns(buffer))
                    buffer = []

        if buffer:
            # Keep the last partial buffer as-is (most recent context is valuable)
            result.extend(buffer)

        logger.debug(
            "ContextCompressor.microcompact: %d → %d turns",
            len(turns),
            len(result),
        )
        return result

    def _collapse(self, turns: list[dict]) -> list[dict]:
        """Tier 3 (> 85%): Fold all old history into one dense summary paragraph."""
        if self._circuit_open:
            logger.warning("ContextCompressor: circuit open, falling back to hard truncate")
            return self._hard_truncate(turns)

        # Protect the most-recent FALLBACK_TURNS turns regardless
        keep_recent = turns[-FALLBACK_TURNS:]
        old_turns = turns[:-FALLBACK_TURNS]

        # Always keep explicitly protected turns
        old_protected = [t for t in old_turns if t.get("protected")]
        old_to_collapse = [t for t in old_turns if not t.get("protected")]

        if not old_to_collapse:
            return turns

        summary_text = self._llm_summarize(old_to_collapse)
        if summary_text is None:
            self._compress_failures += 1
            logger.warning(
                "ContextCompressor.collapse failed (%d/%d)",
                self._compress_failures,
                MAX_COMPRESS_FAILURES,
            )
            if self._compress_failures >= MAX_COMPRESS_FAILURES:
                self._circuit_open = True
                logger.error("ContextCompressor: circuit breaker opened — switching to hard truncate")
            return self._hard_truncate(turns)

        self._compress_failures = 0  # Reset on success

        summary_turn = {
            "role": "summary",
            "content": f"[历史摘要] {summary_text}",
            "protected": False,
        }

        result = old_protected + [summary_turn] + keep_recent
        logger.debug(
            "ContextCompressor.collapse: %d → %d turns",
            len(turns),
            len(result),
        )
        return result

    def _autocompact(self, turns: list[dict]) -> list[dict]:
        """Tier 4 (> 90%): Collapse at end of every turn."""
        logger.debug("ContextCompressor.autocompact triggered")
        return self._collapse(turns)

    def _reactive_compact(self, turns: list[dict]) -> list[dict]:
        """Tier 5 (> 95%): Block current turn, collapse immediately."""
        logger.warning("ContextCompressor.reactive_compact: context critically full, compressing now")
        return self._collapse(turns)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _utilization(self, turns: list[dict]) -> float:
        """Estimated token utilization as a fraction of budget."""
        total_chars = sum(len(t.get("content", "")) for t in turns)
        estimated_tokens = total_chars / _CHARS_PER_TOKEN
        return estimated_tokens / self._token_budget if self._token_budget > 0 else 0.0

    def _merge_turns(self, turns: list[dict]) -> dict:
        """Merge a group of turns into a single summarised turn (no LLM)."""
        lines = [f"{t.get('role', '?')}: {t.get('content', '')[:80]}" for t in turns]
        merged = " | ".join(lines)
        return {
            "role": "merged",
            "content": f"[合并摘要] {merged}",
            "protected": False,
        }

    def _llm_summarize(self, turns: list[dict]) -> str | None:
        """Call LLM to produce a single dense paragraph summarising the turns.

        Returns None if LLM is unavailable or raises.
        """
        if self._llm is None:
            # Fallback: naïve truncation summary
            lines = [f"{t.get('role', '?')}: {t.get('content', '')[:60]}" for t in turns[:10]]
            return "历史摘要：" + "；".join(lines)

        from langchain_core.messages import HumanMessage, SystemMessage

        content_block = "\n".join(
            f"{t.get('role', '?')}: {t.get('content', '')[:200]}" for t in turns
        )
        prompt = (
            "请将以下对话历史压缩成一段简洁的中文摘要（不超过300字），"
            "保留所有重要事实、人物立场和关键线索，去除重复和无关内容。\n\n"
            f"{content_block}"
        )

        try:
            response = self._llm.invoke([
                SystemMessage(content="你是一个专业的对话摘要助手。"),
                HumanMessage(content=prompt),
            ])
            return response.content.strip()
        except Exception as exc:
            logger.warning("ContextCompressor._llm_summarize failed: %s", exc)
            return None

    def _hard_truncate(self, turns: list[dict]) -> list[dict]:
        """Last-resort: keep protected turns + last FALLBACK_TURNS turns."""
        protected = [t for t in turns if t.get("protected")]
        recent = turns[-FALLBACK_TURNS:]
        seen = {id(t) for t in recent}
        extra_protected = [t for t in protected if id(t) not in seen]
        return extra_protected + recent

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------

    @property
    def circuit_open(self) -> bool:
        """True if the circuit breaker has tripped."""
        return self._circuit_open

    def reset_circuit(self) -> None:
        """Manually reset the circuit breaker (e.g. after operator intervention)."""
        self._circuit_open = False
        self._compress_failures = 0
