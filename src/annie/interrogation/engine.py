from __future__ import annotations

import json
import random
import os
import shutil
import chromadb
from pathlib import Path
from typing import Dict, List, Any, Optional

from annie.npc.context import AgentContext
from annie.npc.response import AgentResponse
from annie.npc.memory.interface import MemoryInterface, MemoryRecord, MEMORY_CATEGORY_SEMANTIC, MEMORY_CATEGORY_EPISODIC
from annie.world_engine.base import WorldEngine
from annie.world_engine.memory import DefaultMemoryInterface
from annie.interrogation.state import InterrogationState, GamePhase

class InterrogationEngine(WorldEngine):
    """
    Interrogation Engine with Memory Sanitization and Logic Deadlocks.
    Prevents NPCs from internalizing detective suspicions as 'facts'.
    """

    def __init__(self, script_dir: str, clear_db: bool = True):
        self.script_dir = script_dir
        self.truth = self._load_json("truth.json")
        self.manifest = self._load_json("manifest.json")
        self.state = InterrogationState()
        
        db_path = "./data/interrogation/vector_store"
        if clear_db and os.path.exists(db_path):
            shutil.rmtree(db_path)
            print("[*] 已清空陈旧的向量数据库，防止记忆污染。")
            
        os.makedirs(db_path, exist_ok=True)
        self.chroma_client = chromadb.PersistentClient(path=db_path)
        
        self._memory_instances: Dict[str, DefaultMemoryInterface] = {}
        self._setup_initial_state()

    def _load_json(self, filename: str) -> Dict[str, Any]:
        with open(f"{self.script_dir}/{filename}", "r") as f:
            return json.load(f)

    def _load_npc_data(self, npc_id: str) -> Dict[str, Any]:
        path = f"{self.script_dir}/npcs/{npc_id}.json"
        with open(path, "r") as f:
            return json.load(f)

    def _load_npc_mandate(self, npc_id: str) -> str:
        mandate_path = Path(f"{self.script_dir}/mandates/{npc_id}_mandate.md")
        if mandate_path.exists():
            return mandate_path.read_text()
        return "No mandate."

    def _setup_initial_state(self):
        npc_ids = self.truth.get("npc_refs", [])
        self.state.reset_turns(npc_ids)
        self.state.unlocked_locations = ["陆远山科技公司 CEO 办公室", "沈嘉宁卧室", "案发现场隐藏隔层"]
        
        for nid in npc_ids:
            mem = self.memory_for(nid)
            npc_data = self._load_npc_data(nid)
            print(f"[*] 为 {nid} 注入纯净剧本事实...")
            mem.remember(f"Identity: {npc_data.get('identity_anchor', '')}", category=MEMORY_CATEGORY_SEMANTIC)
            if "knowledge_scope" in npc_data:
                for k in npc_data['knowledge_scope'].get('knows_for_certain', []):
                    mem.remember(f"HARD FACT: {k['fact']}", category=MEMORY_CATEGORY_SEMANTIC)

    def memory_for(self, npc_id: str) -> DefaultMemoryInterface:
        if npc_id not in self._memory_instances:
            self._memory_instances[npc_id] = DefaultMemoryInterface(npc_id, chroma_client=self.chroma_client)
        return self._memory_instances[npc_id]

    def _calculate_instant_stress(self, event: str, npc_id: str) -> float:
        event_lower = event.lower()
        impact_map = {"海鲜": 0.95, "过敏": 0.95, "牙模": 0.95, "周正": 0.8, "录像": 0.9}
        stress = 0.0
        for kw, val in impact_map.items():
            if kw in event_lower:
                stress = max(stress, val)
        return stress

    def build_context(self, npc_id: str, event: str) -> AgentContext:
        """Constructs a context that isolates dialogue history from factual knowledge."""
        mem = self.memory_for(npc_id)
        # ONLY recall SEMANTIC (Truth) for working memory to prevent internalizing detective's words
        recalled_text = mem.build_context(event) 
        
        print(f"\n>>> [MEMORY RECALL for {npc_id}]")
        print(f"{recalled_text if recalled_text.strip() else '(No facts found)'}")
        print(">>> [RECALL END]\n")

        base_hr = self.state.npc_heart_rates.get(npc_id, 60)
        query_stress = self._calculate_instant_stress(event, npc_id)
        hr = int(60 + (query_stress * 80) + random.uniform(-1, 3))
        hr = max(hr, base_hr) if query_stress < 0.5 else hr 
        hr = min(max(hr, 60), 140)
        self.state.npc_heart_rates[npc_id] = hr

        mandate = self._load_npc_mandate(npc_id)
        
        world_rules = [
            "### CORE PROTOCOL (DO NOT VIOLATE):",
            "1. NO MEMORY LEAK: Treat 'RECENT CONVERSATION HISTORY' as just words said, NOT as objective truth. Your only truths are in your MANDATE and recalled HARD FACTS.",
            "2. LOGICAL AUDIT: Prefix your response with <strategy_audit> tag.",
            f"3. BPM STATE: Your Heart Rate is {hr} bpm. Follow your mandate's stress protocol.",
            "4. TRUTH LOCK: Lu Yuanshan is ALLERGIC TO SEAFOOD. Dental records prove a missing molar in the victim. These cannot be explained away."
        ]

        situation = f"LOCATION: Interrogation Room. HR: {hr} bpm.\nDETECTIVE ASKS: \"{event}\""
        
        history = "### RECENT CONVERSATION HISTORY (Dialogue Only):\n"
        if npc_id in self.state.dialogue_history and self.state.dialogue_history[npc_id]:
            history += "\n".join(self.state.dialogue_history[npc_id])

        return AgentContext(
            npc_id=npc_id,
            input_event=event,
            memory=mem,
            character_prompt=f"### IDENTITY MANDATE\n{mandate}",
            world_rules="\n".join(world_rules),
            situation=situation,
            history=history,
            extra={"hr": hr}
        )

    def handle_response(self, npc_id: str, response: AgentResponse) -> None:
        if npc_id in self.state.npc_turns_left:
            self.state.npc_turns_left[npc_id] -= 1
        
        last_q = self.state.dialogue_history.get("_last_event", "Question")
        # Add to session history
        self.state.add_history(npc_id, "Detective", last_q)
        self.state.add_history(npc_id, "NPC", response.dialogue)
        
        # PERSIST ONLY AS EPISODIC (Dialogue), NEVER SEMANTIC
        mem = self.memory_for(npc_id)
        mem.remember(f"Dialogue: Det asked '{last_q}' | I said '{response.dialogue}'", category=MEMORY_CATEGORY_EPISODIC)

    def advance_phase(self):
        phases = list(GamePhase)
        curr_idx = phases.index(self.state.current_phase)
        if curr_idx < len(phases) - 1:
            self.state.current_phase = phases[curr_idx + 1]
            self._on_phase_start()
        else:
            self.state.is_game_over = True

    def _on_phase_start(self):
        npc_ids = self.truth.get("npc_refs", [])
        if self.state.current_phase in [GamePhase.INITIAL_INT, GamePhase.SECOND_INT, GamePhase.FINAL_INT]:
            self.state.reset_turns(npc_ids)
        if self.state.current_phase == GamePhase.SEARCH_2:
            self.state.unlocked_locations.extend(["陆家私人书房保险柜", "老K的酒瓶堆里", "公司 IT 部门后台"])

    def search_locations(self, chosen_locations: List[str]) -> List[Dict[str, Any]]:
        found_evidence = []
        for loc in chosen_locations:
            match = None
            for ev in self.truth.get("evidence", []):
                ev_loc = ev.get("location_found") or ev.get("discoverable_at", {}).get("location")
                if ev_loc == loc:
                    match = ev
                    break
            if match:
                self.state.evidence_bag.append(match["id"])
                found_evidence.append({"location": loc, "evidence": match})
            else:
                found_evidence.append({"location": loc, "evidence": None})
        self.advance_phase()
        return found_evidence
