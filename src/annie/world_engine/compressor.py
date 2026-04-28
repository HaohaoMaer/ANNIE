"""Compressor — cursor-driven fold over HistoryStore + MemoryInterface.

The Compressor is owned by the WorldEngine and invoked during
``handle_response`` (or manually).

Algorithm
---------
1. Count tokens only for entries with ``turn_id > last_folded_turn_id``
   (the "unfolded window").
2. If that window exceeds ``FOLD_TOKEN_THRESHOLD``, pick the oldest
   ``FOLD_TARGET_TOKENS`` worth of entries from that window.
3. Ask the LLM to summarise them.
4. Write the summary as ``category="impression"`` to MemoryInterface.
5. Advance ``last_folded_turn_id`` to the highest turn_id in the slice.
6. **Do not modify the JSONL.**  The JSONL is append-only; the cursor
   tracks what has been folded without mutating past records.

The four compressors at a glance
---------------------------------
* ``Compressor`` (this file) — cross-run, writes impression to vector DB.
* ``ContextBudget``           — single Executor loop, in-memory summary msg.
* ``ToolDispatcher.micro``    — single ToolMessage truncation, in-memory.
* ``HistoryStore.prune``      — permanent JSONL row deletion, no vector write.
"""

from __future__ import annotations

import logging

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
    """Cursor-driven folder: writes impression memories, never modifies JSONL."""

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

    def maybe_fold(self, scene: str | None = None) -> bool:
        """Fold if the unfolded window exceeds the threshold.

        Returns True if a fold was performed, False otherwise.
        """
        if self._history.estimate_tokens_after_cursor() <= self._fold_threshold:
            return False
        return self.force_fold(scene=scene)

    def force_fold(self, scene: str | None = None) -> bool:
        """Fold the oldest slice of the unfolded window unconditionally.

        Returns True if a fold was performed (>= 2 candidates), False otherwise.
        """
        candidates = self._history.unfolded_entries()
        if len(candidates) < 2:
            return False

        selected = self._select_slice(candidates, self._target_tokens)
        if len(selected) < 2:
            return False

        raw_text = self._render_for_summary(selected)
        summary = self._summarize(raw_text)
        if not summary:
            logger.warning("Compressor: LLM returned empty summary; skipping fold")
            return False

        t0 = selected[0].timestamp
        t1 = selected[-1].timestamp
        new_cursor = selected[-1].turn_id

        self._memory.remember(
            summary,
            category=MEMORY_CATEGORY_IMPRESSION,
            metadata={
                "scene": scene or "",
                "time_range_start": t0,
                "time_range_end": t1,
                "source": "fold",
                "folded_turn_count": len(selected),
            },
        )
        self._history.set_last_folded_turn_id(new_cursor)
        logger.debug(
            "Compressor: folded %d turns (ids %d–%d); cursor → %d",
            len(selected), selected[0].turn_id, selected[-1].turn_id, new_cursor,
        )
        return True

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
            content = "".join(str(p) for p in content)
        return str(content).strip()
