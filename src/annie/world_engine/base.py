"""WorldEngine — abstract base class for every concrete world implementation.

Concrete engines (scripted-murder, AI-GM, sandbox, …) must inherit from this
class and provide the minimum contract below. The NPC Agent layer only sees
this interface; it has no knowledge of which engine is driving it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from annie.npc.context import AgentContext
from annie.npc.memory.interface import MemoryInterface
from annie.npc.response import ActionRequest, ActionResult, AgentResponse
from annie.world_engine.compressor import Compressor
from annie.world_engine.history import HistoryStore


class WorldEngine(ABC):
    """Minimum contract every world engine must implement."""

    # ---- NPC drive loop ------------------------------------------------
    @abstractmethod
    def build_context(self, npc_id: str, event: str) -> AgentContext:
        """Assemble an AgentContext for one NPC run."""

    @abstractmethod
    def handle_response(self, npc_id: str, response: AgentResponse) -> None:
        """Arbitrate the agent's action/memory intents and update world state."""

    def execute_action(self, npc_id: str, action: ActionRequest) -> ActionResult:
        """Attempt one world action and return a structured observation.

        Concrete engines override this to apply their own state, permissions,
        and rules. The default keeps the contract explicit for engines that
        have not adopted action execution yet.
        """
        return ActionResult(
            action_id=action.action_id,
            action_type=action.type,
            status="failed",
            reason="unsupported_action",
            observation=f"Action '{action.type}' is not supported by this world engine.",
            facts={"npc_id": npc_id, "payload": action.payload},
        )

    def drive_npc(
        self,
        agent: object,
        npc_id: str,
        event: str,
        max_action_steps: int = 8,
    ) -> AgentResponse:
        """Drive an NPC until it produces a final response or hits step budget."""
        current_event = event
        last_result: ActionResult | None = None
        for _ in range(max_action_steps):
            ctx = self.build_context(npc_id, current_event)
            response = agent.run(ctx)  # type: ignore[attr-defined]
            if not response.actions:
                self.handle_response(npc_id, response)
                return response

            result = self.execute_action(npc_id, response.actions[0])
            last_result = result
            current_event = _render_action_result_event(result)

        observation = (
            last_result.observation
            if last_result is not None
            else "NPC action loop stopped before producing a final response."
        )
        return AgentResponse(
            dialogue=(
                f"Action loop stopped after {max_action_steps} steps. "
                f"Last observation: {observation}"
            ),
        )

    # ---- Memory provisioning ------------------------------------------
    @abstractmethod
    def memory_for(self, npc_id: str) -> MemoryInterface:
        """Return a per-NPC MemoryInterface scoped to this engine's backend."""

    # ---- Rolling history / compression (optional) ---------------------
    def history_for(self, npc_id: str) -> HistoryStore | None:
        """Return a per-NPC HistoryStore, or None if this engine doesn't track history."""
        return None

    def compressor_for(self, npc_id: str) -> Compressor | None:
        """Return a per-NPC Compressor, or None if this engine doesn't fold history."""
        return None

    # ---- World progression --------------------------------------------
    def step(self) -> None:
        """Advance world state one tick. Default no-op; engines override."""
        return None


def _render_action_result_event(result: ActionResult) -> str:
    parts = [
        "World action result:",
        f"- action_id: {result.action_id}",
        f"- action_type: {result.action_type}",
        f"- status: {result.status}",
    ]
    if result.reason:
        parts.append(f"- reason: {result.reason}")
    if result.observation:
        parts.append(f"- observation: {result.observation}")
    if result.facts:
        parts.append(f"- facts: {result.facts}")
    return "\n".join(parts)
