from __future__ import annotations

import enum
from dataclasses import dataclass, field
from typing import Dict, List, Any

class GamePhase(enum.Enum):
    INITIAL_INT = "INITIAL_INTERROGATION"
    SEARCH_1 = "SEARCH_PHASE_1"
    SECOND_INT = "SECOND_INTERROGATION"
    SEARCH_2 = "SEARCH_PHASE_2"
    FINAL_INT = "FINAL_INTERROGATION"
    VERDICT = "VERDICT_PHASE"

@dataclass
class InterrogationState:
    current_phase: GamePhase = GamePhase.INITIAL_INT
    evidence_bag: List[str] = field(default_factory=list)
    unlocked_locations: List[str] = field(default_factory=list)
    npc_turns_left: Dict[str, int] = field(default_factory=dict)
    npc_heart_rates: Dict[str, int] = field(default_factory=dict)
    dialogue_history: Dict[str, List[str]] = field(default_factory=dict) # Tracks recent turns
    is_game_over: bool = False
    player_verdict: str = ""
    
    def reset_turns(self, npc_ids: List[str]):
        self.npc_turns_left = {nid: 3 for nid in npc_ids}
        for nid in npc_ids:
            if nid not in self.npc_heart_rates:
                self.npc_heart_rates[nid] = 60
            if nid not in self.dialogue_history:
                self.dialogue_history[nid] = []

    def add_history(self, npc_id: str, role: str, content: str):
        if npc_id not in self.dialogue_history:
            self.dialogue_history[npc_id] = []
        self.dialogue_history[npc_id].append(f"{role}: {content}")
        # Keep only last 6 messages (3 rounds) to manage context
        if len(self.dialogue_history[npc_id]) > 6:
            self.dialogue_history[npc_id] = self.dialogue_history[npc_id][-6:]
