"""DefaultWorldEngine — a minimal WorldEngine used for tests / integration.

Responsibilities:

* Loads NPC profiles from YAML and folds personality / background / goals /
  relationships into a natural-language ``character_prompt`` string.
* Owns one ``DefaultMemoryInterface`` per NPC.
* Builds AgentContext and handles AgentResponse by merely logging /
  collecting — no real-world arbitration is performed.

This is *not* a game engine; it's the smallest thing that satisfies the
``WorldEngine`` contract so the NPC layer can be exercised end-to-end.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import chromadb
from chromadb.api import ClientAPI
from langchain_core.language_models import BaseChatModel

from annie.npc.context import AgentContext
from annie.npc.memory.interface import (
    MEMORY_CATEGORY_EPISODIC,
    MemoryInterface,
)
from annie.npc.response import AgentResponse
from annie.npc.state import NPCProfile, load_npc_profile
from annie.world_engine.base import WorldEngine
from annie.world_engine.compressor import Compressor
from annie.world_engine.history import HistoryStore
from annie.world_engine.memory import DefaultMemoryInterface

logger = logging.getLogger(__name__)

_DEFAULT_HISTORY_DIR = Path("./data/history")
MAX_HISTORY_TURNS: int = 20


def _profile_to_character_prompt(profile: NPCProfile) -> str:
    parts: list[str] = [f"Name: {profile.name}"]
    if profile.personality.traits:
        parts.append("Traits: " + ", ".join(profile.personality.traits))
    if profile.personality.values:
        parts.append("Values: " + ", ".join(profile.personality.values))
    if profile.background.biography:
        parts.append(f"Biography: {profile.background.biography}")
    if profile.background.past_events:
        parts.append("Past events:\n" + "\n".join(f"- {e}" for e in profile.background.past_events))
    if profile.goals.short_term:
        parts.append("Short-term goals:\n" + "\n".join(f"- {g}" for g in profile.goals.short_term))
    if profile.goals.long_term:
        parts.append("Long-term goals:\n" + "\n".join(f"- {g}" for g in profile.goals.long_term))
    return "\n\n".join(parts)


class DefaultWorldEngine(WorldEngine):
    """Minimal WorldEngine for exercising the NPC Agent layer."""

    def __init__(
        self,
        npc_yaml_paths: dict[str, str | Path] | None = None,
        chroma_client: ClientAPI | None = None,
        world_rules: str = "",
        history_dir: str | Path | None = None,
        llm: BaseChatModel | None = None,
    ) -> None:
        self._client = chroma_client or chromadb.PersistentClient(path="./data/vector_store")
        self._profiles: dict[str, NPCProfile] = {}
        self._memories: dict[str, DefaultMemoryInterface] = {}
        self._histories: dict[str, HistoryStore] = {}
        self._compressors: dict[str, Compressor] = {}
        self._world_rules = world_rules
        self._responses: list[tuple[str, AgentResponse]] = []
        self._situation: str = ""
        self._history_dir = Path(history_dir) if history_dir else _DEFAULT_HISTORY_DIR
        self._llm = llm

        for npc_id, path in (npc_yaml_paths or {}).items():
            self._profiles[npc_id] = load_npc_profile(path)

    # ---- WorldEngine contract -----------------------------------------
    def build_context(self, npc_id: str, event: str) -> AgentContext:
        profile = self._profiles.get(npc_id)
        character_prompt = _profile_to_character_prompt(profile) if profile else ""
        history_text = self._render_history(npc_id)
        return AgentContext(
            npc_id=npc_id,
            input_event=event,
            tools=[],
            skills=[],
            memory=self.memory_for(npc_id),
            character_prompt=character_prompt,
            world_rules=self._world_rules,
            situation=self._situation,
            history=history_text,
            extra={},
        )

    def handle_response(self, npc_id: str, response: AgentResponse) -> None:
        self._responses.append((npc_id, response))
        history = self.history_for(npc_id)
        memory = self.memory_for(npc_id)

        if response.dialogue and history is not None:
            history.append(speaker=npc_id, content=response.dialogue)
            memory.remember(
                response.dialogue,
                category=MEMORY_CATEGORY_EPISODIC,
                metadata={"speaker": npc_id},
            )

        compressor = self.compressor_for(npc_id)
        if compressor is not None:
            compressor.maybe_fold(scene=self._situation or None)

        logger.info(
            "DefaultWorldEngine received response from %s: %d actions, reflection=%s",
            npc_id, len(response.actions), bool(response.reflection),
        )

    def memory_for(self, npc_id: str) -> MemoryInterface:
        if npc_id not in self._memories:
            self._memories[npc_id] = DefaultMemoryInterface(npc_id, chroma_client=self._client)
        return self._memories[npc_id]

    def history_for(self, npc_id: str) -> HistoryStore:
        if npc_id not in self._histories:
            self._histories[npc_id] = HistoryStore(
                npc_id, self._history_dir / f"{npc_id}.jsonl",
            )
        return self._histories[npc_id]

    def compressor_for(self, npc_id: str) -> Compressor | None:
        if self._llm is None:
            return None
        if npc_id not in self._compressors:
            self._compressors[npc_id] = Compressor(
                history_store=self.history_for(npc_id),
                memory=self.memory_for(npc_id),
                llm=self._llm,
            )
        return self._compressors[npc_id]

    # ---- Input ingestion ----------------------------------------------
    def ingest_external(self, npc_id: str, speaker: str, content: str) -> None:
        """Record an inbound utterance into NPC history (player/other-NPC speech)."""
        self.history_for(npc_id).append(speaker=speaker, content=content)

    # ---- internals -----------------------------------------------------
    def _render_history(self, npc_id: str) -> str:
        if npc_id not in self._histories and not (self._history_dir / f"{npc_id}.jsonl").exists():
            return ""
        entries = self.history_for(npc_id).read_last(MAX_HISTORY_TURNS)
        if not entries:
            return ""
        lines: list[str] = []
        for e in entries:
            prefix = "[folded]" if e.is_folded else ""
            lines.append(f"{prefix}[{e.speaker}] {e.content}")
        return "\n".join(lines)

    # ---- Convenience for tests ----------------------------------------
    def set_situation(self, text: str) -> None:
        self._situation = text

    def register_profile(self, npc_id: str, profile: NPCProfile) -> None:
        self._profiles[npc_id] = profile

    @property
    def responses(self) -> list[tuple[str, AgentResponse]]:
        return list(self._responses)

    def extra_for(self, npc_id: str) -> dict[str, Any]:  # pragma: no cover - hook
        return {}
