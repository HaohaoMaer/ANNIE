"""HistoryStore — per-NPC rolling dialogue/event history on JSONL.

Owned by the World Engine; the NPC Agent sees only its rendered form via
``AgentContext.history``. Supports append, read_last, estimate_tokens,
and replace (used by the Compressor when folding old turns).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

# Approximate chars-per-token ratio; CJK-heavy content pushes this down a bit.
_CHARS_PER_TOKEN: float = 2.5


class HistoryEntry(BaseModel):
    turn_id: int
    timestamp: str
    speaker: str
    content: str
    is_folded: bool = False
    folded_from: list[int] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class HistoryStore:
    """JSONL-backed rolling history for a single NPC."""

    def __init__(self, npc_id: str, path: str | Path) -> None:
        self._npc_id = npc_id
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        return self._path

    # ---- write ---------------------------------------------------------
    def append(
        self,
        speaker: str,
        content: str,
        metadata: dict[str, Any] | None = None,
        is_folded: bool = False,
        folded_from: list[int] | None = None,
    ) -> HistoryEntry:
        entries = self._read_all()
        next_id = (entries[-1].turn_id + 1) if entries else 1
        entry = HistoryEntry(
            turn_id=next_id,
            timestamp=datetime.now(UTC).isoformat(),
            speaker=speaker,
            content=content,
            is_folded=is_folded,
            folded_from=folded_from,
            metadata=metadata or {},
        )
        with self._path.open("a", encoding="utf-8") as f:
            f.write(entry.model_dump_json() + "\n")
        return entry

    def replace(self, turn_ids: list[int], new_entry: HistoryEntry) -> None:
        """Replace the given turn_ids with a single new entry (preserves order).

        The new entry is inserted at the position of the *first* replaced id.
        """
        if not turn_ids:
            return
        entries = self._read_all()
        target = set(turn_ids)
        out: list[HistoryEntry] = []
        inserted = False
        for e in entries:
            if e.turn_id in target:
                if not inserted:
                    out.append(new_entry)
                    inserted = True
                continue
            out.append(e)
        if not inserted:
            out.append(new_entry)
        self._rewrite(out)

    # ---- read ----------------------------------------------------------
    def read_all(self) -> list[HistoryEntry]:
        return self._read_all()

    def read_last(self, n: int) -> list[HistoryEntry]:
        entries = self._read_all()
        if n <= 0:
            return []
        return entries[-n:]

    def estimate_tokens(self) -> int:
        total_chars = sum(len(e.content) for e in self._read_all())
        return int(total_chars / _CHARS_PER_TOKEN)

    def unfolded_entries(self) -> list[HistoryEntry]:
        return [e for e in self._read_all() if not e.is_folded]

    # ---- internals -----------------------------------------------------
    def _read_all(self) -> list[HistoryEntry]:
        if not self._path.exists():
            return []
        out: list[HistoryEntry] = []
        with self._path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, start=1):
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    out.append(HistoryEntry(**data))
                except (json.JSONDecodeError, ValueError, TypeError) as exc:
                    logger.warning(
                        "HistoryStore %s: skipping corrupt line %d (%s)",
                        self._path, i, exc,
                    )
                    continue
        return out

    def _rewrite(self, entries: list[HistoryEntry]) -> None:
        # Atomic replace via temp file in the same directory.
        fd, tmp_path = tempfile.mkstemp(
            prefix=self._path.name + ".",
            suffix=".tmp",
            dir=str(self._path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                for e in entries:
                    f.write(e.model_dump_json() + "\n")
            os.replace(tmp_path, self._path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
