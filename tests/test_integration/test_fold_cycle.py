"""Integration: Fold cycle end-to-end.

Fill HistoryStore past threshold, invoke Compressor, verify:
  * HistoryStore gets a folded entry (details removed from "now")
  * Memory gains an ``impression`` record (summary retained long-term)
  * Original episodic traces remain independently recallable
"""

from __future__ import annotations

import chromadb
import pytest
from langchain_core.messages import AIMessage

from annie.npc.memory.interface import MEMORY_CATEGORY_EPISODIC
from annie.world_engine import DefaultWorldEngine


class _StubLLM:
    def __init__(self, reply: str = "Earlier: Alice and player exchanged guarded small talk about the job.") -> None:
        self.reply = reply

    def invoke(self, messages, *args, **kwargs):
        return AIMessage(content=self.reply)


@pytest.fixture
def engine(tmp_path):
    client = chromadb.PersistentClient(path=str(tmp_path / "vs"))
    return DefaultWorldEngine(
        chroma_client=client,
        history_dir=tmp_path / "hist",
        llm=_StubLLM(),
    )


def test_fold_cycle_writes_impression_and_preserves_episodic(engine):
    npc = "alice"
    # 1. Fill engine with plenty of rolling history + episodic memory entries.
    history = engine.history_for(npc)
    memory = engine.memory_for(npc)
    for i in range(12):
        speaker = npc if i % 2 == 0 else "player"
        content = f"turn-{i}: " + ("x" * 400)
        history.append(speaker=speaker, content=content)
        memory.remember(
            content,
            category=MEMORY_CATEGORY_EPISODIC,
            metadata={"speaker": speaker, "turn": i},
        )

    # 2. Force a fold via the engine's compressor.
    compressor = engine.compressor_for(npc)
    assert compressor is not None
    folded_entry = compressor.force_fold(scene="act-1")
    assert folded_entry is not None
    assert folded_entry.is_folded is True

    # 3. HistoryStore now has a folded row.
    assert any(e.is_folded for e in history.read_all())

    # 4. Impression memory written.
    imps = memory.recall("alice player small talk", categories=["impression"], k=5)
    assert imps, "impression memory expected after fold"

    # 5. Episodic traces still recallable.
    eps = memory.recall("turn-0", categories=["episodic"], k=5)
    assert eps, "episodic memory must remain after fold"
