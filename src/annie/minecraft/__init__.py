"""ANNIE Minecraft integration — MinecraftWorldEngine for survival NPCs.

Layers
------
reflexes   — tick-level reactive behaviours (no LLM), runs before cognition
perception — 3D world state → LLM-readable text summary
tools      — 16 ToolDef subclasses for movement, perception, operation,
             crafting, and combat
engine     — MinecraftWorldEngine composing all of the above

Bridge
------
bot_connection — AbstractBridge, MinecraftBridge (Node.js subprocess),
                 FakeBridge (test stub)
minecraft_bridge.js — Node.js mineflayer process
"""

from annie.minecraft.bot_connection import (
    AbstractBridge,
    BridgeEvent,
    FakeBridge,
    MinecraftBridge,
)
from annie.minecraft.engine import MinecraftWorldEngine, create_test_engine
from annie.minecraft.perception import MinecraftPerception
from annie.minecraft.reflexes import Reflex, ReflexResult, default_reflexes

__all__ = [
    "AbstractBridge",
    "BridgeEvent",
    "FakeBridge",
    "MinecraftBridge",
    "MinecraftPerception",
    "MinecraftWorldEngine",
    "Reflex",
    "ReflexResult",
    "create_test_engine",
    "default_reflexes",
]
