"""Compressor — Fold/Trim logic over HistoryStore + MemoryInterface.

The Compressor is owned by the WorldEngine and invoked during
``handle_response`` (or manually). When the unfolded portion of the
history crosses a token threshold, it picks the oldest contiguous
unfolded slice of ~target_tokens, asks the LLM to summarise it, and:

* Replaces those N entries in HistoryStore with a single ``is_folded=True``
  entry (details gone from "now")
* Writes the summary to MemoryInterface under ``category="impression"``
  (details retrievable as "impression" — lower fidelity than episodic)

The original turns remain independently recoverable via
``memory_recall(categories=["episodic"])`` because ``handle_response``
already persisted them at occurrence time.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage

from annie.npc.memory.interface import MEMORY_CATEGORY_IMPRESSION, MemoryInterface
from annie.world_engine.history import HistoryEntry, HistoryStore

logger = logging.getLogger(__name__)

FOLD_TOKEN_THRESHOLD: int = 3000
FOLD_TARGET_TOKENS: int = 1500
_CHARS_PER_TOKEN: float = 2.5

FOLD_SUMMARY_PROMPT = """\
You are a memory compressor for a role-playing NPC.
Summarize the following dialogue / events into 2-5 short sentences that preserve:

1. WHO did WHAT to WHOM (concrete actions and utterances, not filler).
2. The emotional tone (tense? playful? guarded? suspicious?).
3. Any fact explicitly asserted by a participant.

Write in third person, past tense, from an outside observer's perspective.
Avoid generic language; keep names and concrete details that would be hard to re-derive.
Respond with the summary only — no preface, no bullets.
"""


class Compressor:
    """Folds old history into ``impression`` memory."""

    def __init__(
        self,
        history_store: HistoryStore,
        memory: MemoryInterface,
        llm: BaseChatModel,
        fold_threshold: int = FOLD_TOKEN_THRESHOLD,
        target_fold_tokens: int = FOLD_TARGET_TOKENS,
    ) -> None:
        self._history = history_store
        self._memory = memory
        self._llm = llm
        self._fold_threshold = fold_threshold
        self._target_tokens = target_fold_tokens

    def maybe_fold(self, scene: str | None = None) -> HistoryEntry | None:
        """Fold if over threshold. Returns the new folded entry or None."""
        if self._history.estimate_tokens() <= self._fold_threshold:
            return None
        return self.force_fold(scene=scene)

    def force_fold(self, scene: str | None = None) -> HistoryEntry | None:
        candidates = self._history.unfolded_entries()
        if len(candidates) < 2:
            return None

        selected = self._select_slice(candidates, self._target_tokens)
        if len(selected) < 2:
            return None

        raw_text = self._render_for_summary(selected)
        summary = self._summarize(raw_text)
        if not summary:
            logger.warning("Compressor: LLM returned empty summary; skipping fold")
            return None

        turn_ids = [e.turn_id for e in selected]
        t0 = selected[0].timestamp
        t1 = selected[-1].timestamp

        folded = HistoryEntry(
            turn_id=0,  # overwritten below
            timestamp=datetime.now(UTC).isoformat(),
            speaker="system",
            content=summary,
            is_folded=True,
            folded_from=turn_ids,
            metadata={"scene": scene, "time_range": [t0, t1]} if scene else {"time_range": [t0, t1]},
        )
        # Preserve monotonic turn_id: use first replaced id so position stays stable.
        folded = folded.model_copy(update={"turn_id": turn_ids[0]})
        self._history.replace(turn_ids, folded)

        self._memory.remember(
            summary,
            category=MEMORY_CATEGORY_IMPRESSION,
            metadata={
                "scene": scene or "",
                "time_range_start": t0,
                "time_range_end": t1,
                "source": "fold",
                "folded_turn_count": len(turn_ids),
            },
        )
        return folded

    # ---- internals -----------------------------------------------------
    def _select_slice(
        self,
        candidates: list[HistoryEntry],
        target_tokens: int,
    ) -> list[HistoryEntry]:
        """Walk from oldest, accumulating until we hit target_tokens."""
        target_chars = int(target_tokens * _CHARS_PER_TOKEN)
        out: list[HistoryEntry] = []
        chars = 0
        for e in candidates:
            if e.is_folded:
                # defensive: unfolded_entries already filters, but guard recursion.
                continue
            out.append(e)
            chars += len(e.content)
            if chars >= target_chars:
                break
        return out

    def _render_for_summary(self, entries: list[HistoryEntry]) -> str:
        return "\n".join(f"[{e.speaker}] {e.content}" for e in entries)

    def _summarize(self, raw: str) -> str:
        resp = self._llm.invoke([
            SystemMessage(content=FOLD_SUMMARY_PROMPT),
            HumanMessage(content=raw),
        ])
        content = resp.content
        if isinstance(content, list):
            # langchain can return list-of-parts; stringify defensively.
            content = "".join(str(p) for p in content)
        return str(content).strip()
