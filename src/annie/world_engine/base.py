"""WorldEngine — abstract base class for every concrete world implementation.

Concrete engines (scripted-murder, AI-GM, sandbox, …) must inherit from this
class and provide the minimum contract below. The NPC Agent layer only sees
this interface; it has no knowledge of which engine is driving it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from annie.npc.context import AgentContext
from annie.npc.memory.interface import MemoryInterface
from annie.npc.response import AgentResponse


class WorldEngine(ABC):
    """Minimum contract every world engine must implement."""

    # ---- NPC drive loop ------------------------------------------------
    @abstractmethod
    def build_context(self, npc_id: str, event: str) -> AgentContext:
        """Assemble an AgentContext for one NPC run."""

    @abstractmethod
    def handle_response(self, npc_id: str, response: AgentResponse) -> None:
        """Arbitrate the agent's action/memory intents and update world state."""

    # ---- Memory provisioning ------------------------------------------
    @abstractmethod
    def memory_for(self, npc_id: str) -> MemoryInterface:
        """Return a per-NPC MemoryInterface scoped to this engine's backend."""

    # ---- World progression --------------------------------------------
    def step(self) -> None:
        """Advance world state one tick. Default no-op; engines override."""
        return None
