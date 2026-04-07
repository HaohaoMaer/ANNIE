"""Game Master - Main orchestrator for the murder mystery game.

Integrates phase control, turn management, script progression, and rule enforcement.
"""

from __future__ import annotations

from datetime import datetime, UTC
from typing import Any

from annie.script_parser.models import ParsedScript
from annie.world_engine.game_master.phase_controller import Phase, PhaseController
from annie.world_engine.game_master.rule_enforcer import RuleEnforcer, Violation
from annie.world_engine.game_master.script_progression import PlotPoint, ScriptProgression
from annie.world_engine.game_master.turn_manager import TurnManager


class GameMaster:
    """Main game master that orchestrates the murder mystery game."""

    def __init__(self, script: ParsedScript | None = None) -> None:
        """Initialize the game master.

        Args:
            script: Parsed script data (optional).
        """
        self._script = script

        phases = []
        if script:
            phases = [
                Phase(
                    id=f"phase_{i}",
                    name=p.name,
                    description=p.description,
                    allowed_actions=p.allowed_actions,
                    npc_order=p.npc_order,
                )
                for i, p in enumerate(script.phases)
            ]

        self._phase_controller = PhaseController(phases if phases else None)
        self._turn_manager = TurnManager()
        self._script_progression = ScriptProgression()
        self._rule_enforcer = RuleEnforcer()

        self._game_state: dict[str, Any] = {
            "started": False,
            "start_time": None,
            "end_time": None,
            "current_round": 1,
            "discovered_items": [],
            "known_facts": [],
            "npc_locations": {},
            "item_holders": {},
            "events_log": [],
        }

        self._npc_names: list[str] = []
        self._min_rounds_per_phase: int = 1

        if script:
            self._initialize_from_script(script)

    def _initialize_from_script(self, script: ParsedScript) -> None:
        """Initialize game master from parsed script."""
        self._npc_names = [char.name for char in script.characters]

        self._turn_manager = TurnManager(self._npc_names)

        for char in script.characters:
            self._game_state["npc_locations"][char.name] = char.initial_location or "start"

        plot_points = [
            PlotPoint(
                id=f"pp_{i}",
                name=pp.name,
                description=pp.description,
                trigger_conditions=pp.trigger_conditions,
                consequences=pp.consequences,
                required_items=pp.required_items,
                required_knowledge=pp.required_knowledge,
                phase=pp.phase,
            )
            for i, pp in enumerate(script.plot_points)
        ]

        self._script_progression = ScriptProgression(plot_points)

        for clue in script.clues:
            self._game_state["discovered_items"].append(clue.id)

    def start_game(self) -> None:
        """Start the game."""
        self._game_state["started"] = True
        self._game_state["start_time"] = datetime.now(UTC)

        if self._npc_names:
            self._turn_manager = TurnManager(self._npc_names)

    def is_game_over(self) -> bool:
        """Check if the game is over.

        Returns:
            True if game is over, False otherwise.
        """
        return self._phase_controller.is_game_over()

    def get_current_phase(self) -> Phase | None:
        """Get the current game phase.

        Returns:
            Current phase, or None.
        """
        return self._phase_controller.get_current_phase()

    def advance_phase(self) -> bool:
        """Advance to the next phase.

        Returns:
            True if advanced, False if at last phase.
        """
        return self._phase_controller.advance_phase()

    def get_current_turn_npc(self) -> str | None:
        """Get the NPC whose turn it is.

        Returns:
            NPC name, or None.
        """
        return self._turn_manager.get_current_npc()

    def next_turn(self) -> str | None:
        """Advance to the next turn.

        Returns:
            Name of next NPC, or None.
        """
        turn = self._turn_manager.next_turn()
        if turn:
            return turn.npc_name
        return None

    def is_npc_turn(self, npc_name: str) -> bool:
        """Check if it's a specific NPC's turn.

        Args:
            npc_name: Name of the NPC.

        Returns:
            True if it's their turn.
        """
        return self._turn_manager.is_npc_turn(npc_name)

    def get_npc_order(self) -> list[str]:
        """Get the NPC action order for current phase.

        Returns:
            List of NPC names in action order.
        """
        current_phase = self.get_current_phase()
        if current_phase and current_phase.npc_order:
            return current_phase.npc_order
        return self._npc_names

    def validate_action(
        self,
        npc_name: str,
        action: str,
    ) -> tuple[bool, Violation | None]:
        """Validate an action.

        Args:
            npc_name: Name of NPC attempting action.
            action: Action description.

        Returns:
            Tuple of (is_valid, violation_if_any).
        """
        current_phase = self.get_current_phase()
        context = {
            "current_turn": self.get_current_turn_npc(),
            "current_phase": current_phase.name if current_phase else "",
            "allowed_actions": current_phase.allowed_actions if current_phase else [],
            "npc_location": self._game_state["npc_locations"].get(npc_name, ""),
            "available_items": self._game_state["discovered_items"],
        }

        return self._rule_enforcer.validate_action(npc_name, action, context)

    def execute_action(
        self,
        npc_name: str,
        action_result: dict,
    ) -> dict:
        """Execute an NPC's action.

        Args:
            npc_name: Name of the NPC.
            action_result: Result from NPC agent.

        Returns:
            Execution result.
        """
        self._turn_manager.record_action(str(action_result))

        self._game_state["events_log"].append({
            "npc": npc_name,
            "action": action_result,
            "timestamp": datetime.now(UTC).isoformat(),
            "phase": self.get_current_phase().name if self.get_current_phase() else "",
            "round": self._turn_manager.get_round_number(),
        })

        return {
            "success": True,
            "npc": npc_name,
            "action_recorded": True,
        }

    def update_world_state(self, updates: dict) -> None:
        """Update the world state.

        Args:
            updates: Dictionary of state updates.
        """
        for key, value in updates.items():
            if key in self._game_state:
                if isinstance(self._game_state[key], list):
                    if isinstance(value, list):
                        self._game_state[key].extend(value)
                    else:
                        self._game_state[key].append(value)
                elif isinstance(self._game_state[key], dict):
                    self._game_state[key].update(value)
                else:
                    self._game_state[key] = value

    def build_context(self, npc_name: str) -> str:
        """Build context string for an NPC.

        Args:
            npc_name: Name of the NPC.

        Returns:
            Context string.
        """
        context_parts = []

        current_phase = self.get_current_phase()
        if current_phase:
            context_parts.append(f"当前阶段: {current_phase.name}")
            context_parts.append(f"阶段描述: {current_phase.description}")

        round_num = self._turn_manager.get_round_number()
        context_parts.append(f"当前回合: 第{round_num}轮")

        npc_location = self._game_state["npc_locations"].get(npc_name, "未知位置")
        context_parts.append(f"你的位置: {npc_location}")

        other_npcs = [name for name in self._npc_names if name != npc_name]
        if other_npcs:
            context_parts.append(f"其他角色: {', '.join(other_npcs)}")

        available_actions = self._phase_controller.get_allowed_actions()
        if available_actions:
            context_parts.append(f"可用行动: {', '.join(available_actions)}")

        return "\n".join(context_parts)

    def check_plot_triggers(self) -> list[PlotPoint]:
        """Check for plot points that should trigger.

        Returns:
            List of triggered plot points.
        """
        world_state = {
            "discovered_items": self._game_state["discovered_items"],
            "known_facts": self._game_state["known_facts"],
            "current_phase": self.get_current_phase().name if self.get_current_phase() else "",
            "npc_states": {},
        }

        return self._script_progression.check_triggers(world_state)

    def get_ending(self) -> str:
        """Get the game ending.

        Returns:
            Ending description.
        """
        if self._script and self._script.endings:
            return self._script.endings[0].description

        return "游戏结束"

    def get_game_state(self) -> dict:
        """Get the current game state.

        Returns:
            Game state dictionary.
        """
        return self._game_state.copy()

    def get_npc_names(self) -> list[str]:
        """Get all NPC names.

        Returns:
            List of NPC names.
        """
        return self._npc_names.copy()

    def set_npc_location(self, npc_name: str, location: str) -> None:
        """Set an NPC's location.

        Args:
            npc_name: Name of the NPC.
            location: New location.
        """
        self._game_state["npc_locations"][npc_name] = location

    def get_npc_location(self, npc_name: str) -> str:
        """Get an NPC's location.

        Args:
            npc_name: Name of the NPC.

        Returns:
            Location name.
        """
        return self._game_state["npc_locations"].get(npc_name, "")

    def discover_item(self, item_id: str) -> None:
        """Record an item discovery.

        Args:
            item_id: ID of discovered item.
        """
        if item_id not in self._game_state["discovered_items"]:
            self._game_state["discovered_items"].append(item_id)

    def add_known_fact(self, fact: str) -> None:
        """Add a known fact.

        Args:
            fact: The fact to add.
        """
        if fact not in self._game_state["known_facts"]:
            self._game_state["known_facts"].append(fact)

    def get_progress(self) -> dict:
        """Get game progress information.

        Returns:
            Progress dictionary.
        """
        return {
            "phase": self._phase_controller.get_phase_progress(),
            "phase_number": self._phase_controller.get_current_phase_number(),
            "total_phases": self._phase_controller.get_phase_count(),
            "round": self._turn_manager.get_round_number(),
            "turn": self._turn_manager.get_turn_number(),
            "plot_progress": self._script_progression.get_progress(),
        }

    def should_advance_phase(self) -> bool:
        """Check if the game should advance to the next phase.

        Returns:
            True if should advance.
        """
        npc_count = len(self._npc_names)
        if npc_count == 0:
            return False

        # Check rounds completed in current phase
        rounds_completed = self._turn_manager.get_round_number() - 1
        if self._turn_manager.is_round_complete():
            rounds_completed = self._turn_manager.get_round_number()

        # Require minimum rounds per phase
        if rounds_completed < self._min_rounds_per_phase:
            return False

        # Check plot triggers
        triggered = self.check_plot_triggers()
        for pp in triggered:
            if "advance_phase" in pp.trigger_conditions:
                return True

        return rounds_completed >= self._min_rounds_per_phase

    def to_dict(self) -> dict:
        """Export game master state to dictionary.

        Returns:
            Dictionary representation.
        """
        return {
            "game_state": self._game_state,
            "phase_controller": self._phase_controller.to_dict(),
            "turn_manager": self._turn_manager.to_dict(),
            "script_progression": self._script_progression.to_dict(),
            "rule_enforcer": self._rule_enforcer.to_dict(),
            "npc_names": self._npc_names,
        }
