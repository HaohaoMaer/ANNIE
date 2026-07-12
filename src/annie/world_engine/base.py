"""WorldEngine — abstract base class for every concrete world implementation.

Concrete engines (scripted-murder, AI-GM, sandbox, …) must inherit from this
class and provide the minimum contract below. The NPC Agent layer only sees
this interface; it has no knowledge of which engine is driving it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from annie.npc.core.context import AgentContext
from annie.npc.memory.interface import MemoryInterface
from annie.npc.core.response import ActionRequest, ActionResult, AgentResponse
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
        """Persist response outputs and any already-executed tool statuses."""

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
        """Drive one NPC run.

        World side effects happen during engine-owned tool execution inside
        the selected NPC graph. There is no post-response declarative action
        loop.
        """
        _ = max_action_steps
        ctx = self.build_context(npc_id, event)
        response = agent.run(ctx)  # type: ignore[attr-defined]
        self.handle_response(npc_id, response)
        return response

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
