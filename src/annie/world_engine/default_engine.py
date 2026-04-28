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
from annie.npc.memory.interface import MemoryInterface
from annie.npc.response import ActionRequest, ActionResult, AgentResponse
from annie.world_engine.profile import NPCProfile, load_npc_profile, profile_to_character_prompt
from annie.world_engine.tools import PlanTodoTool, WorldActionTool, render_todo_text
from annie.world_engine.base import WorldEngine
from annie.world_engine.compressor import Compressor
from annie.world_engine.history import HistoryStore
from annie.world_engine.memory import DefaultMemoryInterface

logger = logging.getLogger(__name__)

_DEFAULT_HISTORY_DIR = Path("./data/history")
MAX_HISTORY_TURNS: int = 20


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
        self._locations: dict[str, str] = {}
        self._exits: dict[str, set[str]] = {}

        for npc_id, path in (npc_yaml_paths or {}).items():
            self._profiles[npc_id] = load_npc_profile(path)

    # ---- WorldEngine contract -----------------------------------------
    def build_context(self, npc_id: str, event: str) -> AgentContext:
        profile = self._profiles.get(npc_id)
        memory = self.memory_for(npc_id)
        character_prompt = profile_to_character_prompt(profile) if profile else ""
        history_text = self._render_history(npc_id)
        return AgentContext(
            npc_id=npc_id,
            input_event=event,
            tools=[PlanTodoTool(), WorldActionTool(npc_id, self.execute_action)],
            skills=[],
            memory=memory,
            character_prompt=character_prompt,
            world_rules=self._world_rules,
            situation=self._situation,
            history=history_text,
            todo=render_todo_text(memory),
            extra={},
        )

    def handle_response(self, npc_id: str, response: AgentResponse) -> None:
        self._responses.append((npc_id, response))
        history = self.history_for(npc_id)

        if response.dialogue and history is not None:
            history.append(speaker=npc_id, content=response.dialogue)

        memory = self.memory_for(npc_id)
        for update in response.memory_updates:
            memory.remember(
                update.content,
                category=update.type,
                metadata=update.metadata,
            )

        compressor = self.compressor_for(npc_id)
        if compressor is not None:
            compressor.maybe_fold(scene=self._situation or None)

        logger.info(
            "DefaultWorldEngine received response from %s: %d actions, reflection=%s",
            npc_id, len(response.actions), bool(response.reflection),
        )

    def execute_action(self, npc_id: str, action: ActionRequest) -> ActionResult:
        if action.type == "move":
            return self._execute_move(npc_id, action)
        if action.type == "inspect":
            target = str(action.payload.get("target", "the area"))
            return ActionResult(
                action_id=action.action_id,
                action_type=action.type,
                status="succeeded",
                observation=f"{npc_id} inspects {target}.",
                facts={"target": target},
            )
        return super().execute_action(npc_id, action)

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

    def set_location(self, npc_id: str, location: str) -> None:
        self._locations[npc_id] = location

    def set_exits(self, location: str, exits: list[str]) -> None:
        self._exits[location] = set(exits)

    def register_profile(self, npc_id: str, profile: NPCProfile) -> None:
        self._profiles[npc_id] = profile

    @property
    def responses(self) -> list[tuple[str, AgentResponse]]:
        return list(self._responses)

    def extra_for(self, npc_id: str) -> dict[str, Any]:  # pragma: no cover - hook
        return {}

    def _execute_move(self, npc_id: str, action: ActionRequest) -> ActionResult:
        target = action.payload.get("to")
        if not isinstance(target, str) or not target:
            return ActionResult(
                action_id=action.action_id,
                action_type=action.type,
                status="failed",
                reason="invalid_payload",
                observation="Move requires a non-empty 'to' location.",
            )

        current = self._locations.get(npc_id)
        if current is None:
            return ActionResult(
                action_id=action.action_id,
                action_type=action.type,
                status="failed",
                reason="unknown_current_location",
                observation=f"{npc_id}'s current location is unknown.",
                facts={"to": target},
            )

        if target == current:
            return ActionResult(
                action_id=action.action_id,
                action_type=action.type,
                status="succeeded",
                reason="already_at_destination",
                observation=f"{npc_id} is already at {target}.",
                facts={
                    "from": current,
                    "to": target,
                    "reachable": sorted(self._exits.get(current, set())),
                },
            )

        reachable = sorted(self._exits.get(current, set()))
        if target not in reachable:
            return ActionResult(
                action_id=action.action_id,
                action_type=action.type,
                status="failed",
                reason="unreachable",
                observation=f"{target} is not directly reachable from {current}.",
                facts={"from": current, "to": target, "reachable": reachable},
            )

        self._locations[npc_id] = target
        reachable_from_target = sorted(self._exits.get(target, set()))
        return ActionResult(
            action_id=action.action_id,
            action_type=action.type,
            status="succeeded",
            observation=f"{npc_id} moved from {current} to {target}.",
            facts={"from": current, "to": target, "reachable": reachable_from_target},
        )
