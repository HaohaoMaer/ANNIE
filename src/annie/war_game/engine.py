"""WarGameEngine — WorldEngine subclass for the three-faction war game."""

from __future__ import annotations

import logging
from pathlib import Path

from chromadb.api import ClientAPI
from langchain_core.language_models import BaseChatModel

from annie.npc.agent import NPCAgent
from annie.npc.context import AgentContext
from annie.npc.graph_registry import AgentGraphID
from annie.npc.memory.interface import MemoryInterface
from annie.npc.response import AgentResponse
from annie.war_game.config import GameConfig
from annie.war_game.game_state import GameState
from annie.war_game.map_preset import (
    FACTION_A,
    FACTION_B,
    create_default_state,
)
from annie.war_game.prompts import WORLD_RULES, render_situation
from annie.war_game.tools import (
    DeclareIntentTool,
    DeployForcesTool,
    FinalDecisionTool,
    NegotiateResponseTool,
    SendMessageTool,
)
from annie.world_engine.base import WorldEngine
from annie.world_engine.history import HistoryStore
from annie.world_engine.memory import DefaultMemoryInterface
from annie.world_engine.profile import load_npc_profile, profile_to_character_prompt

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).parent / "prompts"
_DEFAULT_HISTORY_DIR = Path("./data/war_game/history")


def _load_character_prompt(faction_id: str) -> str:
    """Load faction profile YAML and build a character prompt string."""
    yaml_map = {
        FACTION_A: _PROMPTS_DIR / "faction_a.yaml",
        FACTION_B: _PROMPTS_DIR / "faction_b.yaml",
    }
    path = yaml_map.get(faction_id)
    if path is None:
        return ""
    profile = load_npc_profile(path)
    return profile_to_character_prompt(profile)


# Phase → tools mapping
_PHASE_TOOLS = {
    "declaration": lambda: [DeclareIntentTool()],
    "diplomacy": lambda: [SendMessageTool()],
    "deployment": lambda: [DeployForcesTool()],
    "negotiation": lambda: [NegotiateResponseTool()],
    "final_decision": lambda: [FinalDecisionTool()],
}


class WarGameEngine(WorldEngine):
    """Game engine for the three-faction war game."""

    def __init__(
        self,
        config: GameConfig | None = None,
        agent: NPCAgent | None = None,
        llm: BaseChatModel | None = None,
        chroma_client: ClientAPI | None = None,
        history_dir: Path | str | None = None,
    ) -> None:
        self.config = config or GameConfig()
        self.agent = agent
        self.llm = llm

        import chromadb
        self._client = chroma_client or chromadb.PersistentClient(path="./data/war_game/vector_store")
        self._history_dir = Path(history_dir) if history_dir else _DEFAULT_HISTORY_DIR

        self.state: GameState = create_default_state(self.config)

        # Per-faction caches
        self._memories: dict[str, DefaultMemoryInterface] = {}
        self._histories: dict[str, HistoryStore] = {}
        self._character_prompts: dict[str, str] = {}

        # Pre-load character prompts for AI factions
        for fid in [FACTION_A, FACTION_B]:
            self._character_prompts[fid] = _load_character_prompt(fid)

    # ---- WorldEngine contract --------------------------------------------

    def build_context(
        self,
        npc_id: str,
        event: str,
        phase: str = "declaration",
    ) -> AgentContext:
        """Build an AgentContext for one AI faction run.

        ``phase`` controls which tools are injected.
        """
        tools = _PHASE_TOOLS.get(phase, lambda: [])()
        situation = render_situation(self.state, npc_id)
        history_text = self._render_history(npc_id)

        extra: dict = {
            "phase": phase,
            "faction_id": npc_id,
        }

        # Inject deployment validation data
        if phase == "deployment":
            extra["force_pool"] = self.state.factions[npc_id].force_pool
            extra["owned_city_ids"] = [c.id for c in self.state.owned_cities(npc_id)]
            extra["adjacent_enemy_ids"] = [c.id for c in self.state.adjacent_enemies(npc_id)]

        return AgentContext(
            npc_id=npc_id,
            input_event=event,
            tools=tools,
            skills=[],
            memory=self.memory_for(npc_id),
            graph_id=AgentGraphID.ACTION_EXECUTOR_DEFAULT,
            character_prompt=self._character_prompts.get(npc_id, ""),
            world_rules=WORLD_RULES,
            situation=situation,
            history=history_text,
            extra=extra,
        )

    def handle_response(self, npc_id: str, response: AgentResponse) -> None:
        """Record response and append dialogue to history."""
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

        logger.info(
            "WarGameEngine received response from %s: dialogue=%s",
            npc_id, bool(response.dialogue),
        )

    def memory_for(self, npc_id: str) -> MemoryInterface:
        if npc_id not in self._memories:
            self._memories[npc_id] = DefaultMemoryInterface(
                npc_id, chroma_client=self._client,
            )
        return self._memories[npc_id]

    def history_for(self, npc_id: str) -> HistoryStore:
        if npc_id not in self._histories:
            self._histories[npc_id] = HistoryStore(
                npc_id, self._history_dir / f"{npc_id}.jsonl",
            )
        return self._histories[npc_id]

    # ---- Internals -------------------------------------------------------

    def _render_history(self, npc_id: str, max_turns: int = 20) -> str:
        if npc_id not in self._histories and not (self._history_dir / f"{npc_id}.jsonl").exists():
            return ""
        entries = self.history_for(npc_id).read_last(max_turns)
        if not entries:
            return ""
        lines: list[str] = []
        for e in entries:
            lines.append(f"[{e.speaker}] {e.content}")
        return "\n".join(lines)
