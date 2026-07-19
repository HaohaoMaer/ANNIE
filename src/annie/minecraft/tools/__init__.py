"""Minecraft tool set — ToolDef subclasses for NPC-Minecraft interaction.

Matches mindcraft's complete skills library across 7 categories.
"""

from annie.minecraft.tools.movement import (
    GoToCoordinatesTool,
    GoToBlockTool,
    StopMovingTool,
    MoveAwayTool,
    DigDownTool,
    GoToSurfaceTool,
    FollowPlayerTool,
    GoToPlayerTool,
)
from annie.minecraft.tools.perception import (
    CheckSurroundingsTool,
    CheckInventoryTool,
    CheckCraftableTool,
)
from annie.minecraft.tools.operation import (
    BreakBlockTool,
    CollectItemTool,
    EquipTool,
    ConsumeTool,
    DiscardTool,
    PlaceBlockTool,
    PickupNearbyTool,
)
from annie.minecraft.tools.crafting import (
    CraftTool,
    GetCraftingPlanTool,
    SmeltItemTool,
    ClearFurnaceTool,
)
from annie.minecraft.tools.combat import (
    AttackTool,
    DefendTool,
    EquipHighestAttackTool,
)
from annie.minecraft.tools.interaction import (
    SendChatTool,
    GiveToPlayerTool,
)
from annie.minecraft.tools.storage import (
    ViewChestTool,
    TakeFromChestTool,
    PutInChestTool,
)

__all__ = [
    # Movement (8)
    "GoToCoordinatesTool",
    "GoToBlockTool",
    "StopMovingTool",
    "MoveAwayTool",
    "DigDownTool",
    "GoToSurfaceTool",
    "FollowPlayerTool",
    "GoToPlayerTool",
    # Perception (3)
    "CheckSurroundingsTool",
    "CheckInventoryTool",
    "CheckCraftableTool",
    # Operation (7)
    "BreakBlockTool",
    "CollectItemTool",
    "EquipTool",
    "ConsumeTool",
    "DiscardTool",
    "PlaceBlockTool",
    "PickupNearbyTool",
    # Crafting (4)
    "CraftTool",
    "GetCraftingPlanTool",
    "SmeltItemTool",
    "ClearFurnaceTool",
    # Combat (3)
    "AttackTool",
    "DefendTool",
    "EquipHighestAttackTool",
    # Interaction (2)
    "SendChatTool",
    "GiveToPlayerTool",
    # Storage (3)
    "ViewChestTool",
    "TakeFromChestTool",
    "PutInChestTool",
]
