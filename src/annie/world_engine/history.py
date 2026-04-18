"""HistoryStore — per-NPC rolling dialogue/event history on JSONL.

Owned by the World Engine; the NPC Agent sees only its rendered form via
``AgentContext.history``.

Storage layout
--------------
* ``{path}``          — JSONL of ``HistoryEntry`` records (append-only from new code).
* ``{path}.meta.json`` — JSON sidecar with ``{"last_folded_turn_id": int}``.
  Read/written exclusively by ``HistoryStore``; the Compressor calls the
  helper methods rather than touching the file directly.

Deprecated fields
-----------------
``HistoryEntry.is_folded`` and ``folded_from`` remain in the model for
backwards-compat with existing JSONL files.  ``_read_all`` skips entries
where ``is_folded=True`` so they are no longer rendered into history.
New code never writes ``is_folded=True``; the Compressor uses the cursor
instead.
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
    is_folded: bool = False          # deprecated — kept for compat; skipped on read
    folded_from: list[int] | None = None  # deprecated
    metadata: dict[str, Any] = Field(default_factory=dict)


class HistoryStore:
    """JSONL-backed rolling history for a single NPC."""

    def __init__(self, npc_id: str, path: str | Path) -> None:
        self._npc_id = npc_id
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._meta_path = self._path.with_suffix(self._path.suffix + ".meta.json")

    @property
    def path(self) -> Path:
        return self._path

    # ---- fold cursor (sidecar) ----------------------------------------
    def last_folded_turn_id(self) -> int:
        """Return the current fold cursor (0 = nothing has been folded yet)."""
        if not self._meta_path.exists():
            return 0
        try:
            data = json.loads(self._meta_path.read_text(encoding="utf-8"))
            return int(data.get("last_folded_turn_id", 0))
        except (json.JSONDecodeError, ValueError, TypeError):
            return 0

    def set_last_folded_turn_id(self, turn_id: int) -> None:
        """Persist the fold cursor atomically."""
        data: dict[str, Any] = {}
        if self._meta_path.exists():
            try:
                data = json.loads(self._meta_path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, ValueError, TypeError):
                data = {}
        data["last_folded_turn_id"] = turn_id
        self._write_meta(data)

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

        Deprecated — kept for backwards-compat with old Compressor code.
        New Compressor no longer calls this; cursor-based folding is used instead.
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

    def prune(
        self,
        keep_last: int | None = None,
        before_turn_id: int | None = None,
    ) -> int:
        """Delete history entries, returning the number of deleted rows.

        Exactly one of ``keep_last`` or ``before_turn_id`` must be given.

        * ``keep_last=N`` — retain only the *N* most recent entries.
        * ``before_turn_id=X`` — delete all entries with ``turn_id < X``.

        The fold cursor (``last_folded_turn_id``) is left unchanged.  If the
        cursor pointed to a pruned entry, the next fold naturally re-starts
        from the oldest remaining entry.
        """
        if (keep_last is None) == (before_turn_id is None):
            raise ValueError(
                "prune() requires exactly one of keep_last or before_turn_id"
            )
        entries = self._read_all_raw()  # include is_folded stubs for accurate count
        if not entries:
            return 0

        if keep_last is not None:
            if keep_last < 0:
                raise ValueError("keep_last must be >= 0")
            n_delete = max(0, len(entries) - keep_last)
            surviving = entries[n_delete:]
        else:
            assert before_turn_id is not None
            surviving = [e for e in entries if e.turn_id >= before_turn_id]
            n_delete = len(entries) - len(surviving)

        if n_delete > 0:
            self._rewrite(surviving)
        return n_delete

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

    def estimate_tokens_after_cursor(self) -> int:
        """Token estimate for entries with turn_id > last_folded_turn_id."""
        cursor = self.last_folded_turn_id()
        chars = sum(
            len(e.content)
            for e in self._read_all()
            if e.turn_id > cursor
        )
        return int(chars / _CHARS_PER_TOKEN)

    def unfolded_entries(self) -> list[HistoryEntry]:
        """Return entries not yet folded (turn_id > last_folded_turn_id).

        The old ``is_folded`` field is respected for backwards-compat: any
        entry with ``is_folded=True`` is also excluded.
        """
        cursor = self.last_folded_turn_id()
        return [
            e for e in self._read_all()
            if e.turn_id > cursor and not e.is_folded
        ]

    # ---- internals -----------------------------------------------------
    def _read_all(self) -> list[HistoryEntry]:
        """Read entries, skipping deprecated ``is_folded=True`` stubs."""
        return [e for e in self._read_all_raw() if not e.is_folded]

    def _read_all_raw(self) -> list[HistoryEntry]:
        """Read all entries including deprecated ``is_folded=True`` stubs."""
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

    def _write_meta(self, data: dict[str, Any]) -> None:
        fd, tmp_path = tempfile.mkstemp(
            prefix=self._meta_path.name + ".",
            suffix=".tmp",
            dir=str(self._meta_path.parent),
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f)
            os.replace(tmp_path, self._meta_path)
        except Exception:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise
