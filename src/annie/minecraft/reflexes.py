"""Reflex layer — tick-level reactive behaviours that run BEFORE LLM cognition.

Mirrors mindcraft's modes.js pattern: priority-ordered, each reflex checks
conditions and may execute an action that interrupts any ongoing LLM operation.

Reflexes execute via the bridge directly — no LLM involvement.
Results are injected as informational events for the next LLM cognition cycle
(whenever that happens), but do NOT trigger LLM by themselves.

Priority order (lower = higher priority, first triggered wins)
---------------------------------------------------------------
1. SelfPreservation — fire, drowning, lava, critical HP, fall risk, cactus
2. Unstuck          — same position too long
3. Cowardice        — hostile nearby, no weapon → flee
4. SelfDefense      — hostile nearby, has weapon → fight
5. TorchPlacing     — light < 7 at night, has torches → place torch
6. Hunger           — hunger < 6, has food → eat
7. ItemCollecting   — dropped items nearby → pickup
"""

from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from annie.minecraft.bot_connection import AbstractBridge

logger = logging.getLogger(__name__)

# ── Hostile mobs ────────────────────────────────────────────────────────────
_HOSTILE_MOBS = frozenset({
    "zombie", "skeleton", "creeper", "spider", "cave_spider",
    "enderman", "witch", "slime", "phantom", "drowned", "husk", "stray",
    "blaze", "ghast", "magma_cube", "wither_skeleton", "piglin",
    "hoglin", "zoglin", "piglin_brute", "warden", "guardian", "elder_guardian",
})

# ── Dangerous blocks (mindcraft: self_preservation checks) ──────────────────
_DANGER_BLOCKS = frozenset({
    "lava", "flowing_lava", "fire", "soul_fire",
    "campfire", "soul_campfire", "magma_block",
})
_CONTACT_DANGER_BLOCKS = frozenset({
    "cactus", "sweet_berry_bush", "wither_rose", "powder_snow",
})

# ── Edible items (for hunger reflex) ────────────────────────────────────────
_FOOD_ITEMS = frozenset({
    "apple", "golden_apple", "enchanted_golden_apple",
    "bread", "cooked_beef", "cooked_porkchop", "cooked_chicken",
    "cooked_mutton", "cooked_rabbit", "cooked_cod", "cooked_salmon",
    "beef", "porkchop", "chicken", "mutton", "rabbit",
    "cod", "salmon", "tropical_fish",
    "carrot", "golden_carrot", "potato", "baked_potato",
    "beetroot", "beetroot_soup", "mushroom_stew", "rabbit_stew",
    "melon_slice", "pumpkin_pie", "cookie", "cake",
    "dried_kelp", "sweet_berries", "glow_berries",
    "chorus_fruit", "honey_bottle", "suspicious_stew",
    "rotten_flesh", "spider_eye", "poisonous_potato", "pufferfish",
})


# ── Reflex result ───────────────────────────────────────────────────────────

@dataclass
class ReflexResult:
    triggered: bool
    reflex_name: str = ""
    event_text: str = ""  # informational — does NOT trigger LLM by itself
    data: dict[str, Any] = field(default_factory=dict)


# ── Abstract base ───────────────────────────────────────────────────────────

class Reflex(ABC):
    """One tick-level reactive behaviour."""

    name: str = "base"
    priority: int = 100          # lower = higher priority
    cooldown_seconds: float = 0  # minimum seconds between triggers

    def __init__(self):
        self._last_triggered: float = 0.0

    def on_cooldown(self) -> bool:
        if self.cooldown_seconds <= 0:
            return False
        return time.time() - self._last_triggered < self.cooldown_seconds

    @abstractmethod
    def should_trigger(self, perception_text: str, inventory: dict,
                       bridge: AbstractBridge) -> bool:
        """Check whether this reflex should fire."""

    @abstractmethod
    def execute(self, bridge: AbstractBridge) -> str:
        """Execute the reflex action. Returns an event description string."""

    def run(self, perception_text: str, inventory: dict,
            bridge: AbstractBridge) -> ReflexResult:
        if self.on_cooldown():
            return ReflexResult(triggered=False)
        if self.should_trigger(perception_text, inventory, bridge):
            self._last_triggered = time.time()
            event_text = self.execute(bridge)
            logger.debug("Reflex [%s] fired: %s", self.name, event_text[:120])
            return ReflexResult(
                triggered=True,
                reflex_name=self.name,
                event_text=event_text,
            )
        return ReflexResult(triggered=False)


# ══════════════════════════════════════════════════════════════════════════════
# Priority 1: SelfPreservation — ALL immediate life threats
# ══════════════════════════════════════════════════════════════════════════════

class SelfPreservationReflex(Reflex):
    """mindcraft: self_preservation — fire, drowning, lava, low HP, fall risk.

    The single highest-priority reflex.  Covers every immediately
    life-threatening condition that mindcraft's self_preservation mode
    handles.  Runs every 500 ms (cooldown) to avoid spamming.
    """

    name = "self_preservation"
    priority = 1   # highest — beats everything
    cooldown_seconds = 0.5

    # HP thresholds
    CRITICAL_HP = 6
    LOW_HP = 10

    # Hunger threshold for forced eating
    STARVATION_HUNGER = 4

    def should_trigger(self, perception_text, inventory, bridge) -> bool:
        """Check ALL danger conditions.  Returns True if ANY are met."""
        try:
            stats = bridge.call("get_stats")
        except Exception:
            return False  # can't determine — don't trigger

        if not stats.get("ok", True):
            return False

        health = stats.get("health", 20)
        hunger = stats.get("hunger", 20)

        # ── 1. On fire ──────────────────────────────────────────────
        if stats.get("on_fire"):
            return True

        # ── 2. Drowning (submerged in water) ────────────────────────
        if stats.get("submerged"):
            return True

        # ── 3. Critical HP (any cause) ──────────────────────────────
        if health <= self.CRITICAL_HP:
            return True

        # ── 4. Lava / fire / magma nearby ───────────────────────────
        danger_blocks = stats.get("nearby_danger_blocks", [])
        if danger_blocks:
            # Check for immediate threats (within 3 blocks)
            close_dangers = [b for b in danger_blocks if b.get("distance", 99) <= 3]
            if close_dangers:
                return True
            # Lava within 5 blocks is always dangerous
            for b in danger_blocks:
                if "lava" in b.get("name", ""):
                    return True

        # ── 5. Fall risk (drop > 4 blocks below) ────────────────────
        if stats.get("fall_risk", 0) >= 5:
            return True

        # ── 6. Starvation (hunger ≤ 4 AND health already dropping) ──
        if hunger <= self.STARVATION_HUNGER and health < 10:
            return True

        # ── 7. Keyword fallback (in case bridge fields are missing) ─
        lower = perception_text.lower()
        if any(kw in lower for kw in ("lava", "岩浆", "on fire", "着火", "burning")):
            return True

        return False

    def execute(self, bridge: AbstractBridge) -> str:
        """Execute the appropriate escape action based on the danger type."""
        try:
            stats = bridge.call("get_stats")
        except Exception:
            bridge.call("move_away", {"distance": 10})
            return "[反射: 自保] 检测到危险，自动远离。"

        # ── On fire → move away (prefer water direction if possible) ─
        if stats.get("on_fire"):
            bridge.call("move_away", {"distance": 10})
            return "[反射: 自保] 着火了！自动远离10格。"

        # ── Drowning → go to surface ────────────────────────────────
        if stats.get("submerged"):
            bridge.call("go_to_surface")
            return "[反射: 自保] 溺水！自动上浮到水面。"

        # ── Lava / fire nearby → move away ──────────────────────────
        danger_blocks = stats.get("nearby_danger_blocks", [])
        if danger_blocks:
            bridge.call("move_away", {"distance": 10})
            names = {b.get("name", "?") for b in danger_blocks[:3]}
            return f"[反射: 自保] 附近有危险方块({', '.join(names)})，自动远离10格。"

        # ── Critical HP → move away from any threat ─────────────────
        health = stats.get("health", 20)
        if health <= self.CRITICAL_HP:
            bridge.call("move_away", {"distance": 10})
            return f"[反射: 自保] 血量危急({health}/20)，自动远离10格。"

        # ── Fall risk → move to safe position ───────────────────────
        if stats.get("fall_risk", 0) >= 5:
            bridge.call("move_away", {"distance": 5})
            return "[反射: 自保] 坠落风险，自动移动到安全位置。"

        # ── Starvation → try to eat ─────────────────────────────────
        hunger = stats.get("hunger", 20)
        if hunger <= self.STARVATION_HUNGER:
            inv = bridge.call("get_inventory")
            items = inv.get("items", {})
            for food in _FOOD_ITEMS:
                if food in items and items[food] > 0:
                    bridge.call("consume", {"item_name": food})
                    return f"[反射: 自保] 饥饿危急({hunger}/20)，自动进食{food}。"

        # Fallback
        bridge.call("move_away", {"distance": 10})
        return "[反射: 自保] 检测到危险情况，自动远离当前位置10格。"


# ══════════════════════════════════════════════════════════════════════════════
# Priority 2: Unstuck
# ══════════════════════════════════════════════════════════════════════════════

class UnstuckReflex(Reflex):
    """mindcraft: unstuck — stuck in same position for too long."""

    name = "unstuck"
    priority = 2
    cooldown_seconds = 10.0

    def __init__(self):
        super().__init__()
        self._last_position: tuple | None = None
        self._stuck_since: float | None = None
        self._stuck_threshold = 120.0  # companion mode: waiting is normal

    def should_trigger(self, perception_text, inventory, bridge) -> bool:
        try:
            stats = bridge.call("get_stats")
        except Exception:
            return False

        pos = tuple(round(c) for c in stats.get("position", [0, 0, 0]))
        now = time.time()

        if self._last_position is None or pos != self._last_position:
            self._last_position = pos
            self._stuck_since = None
            return False

        if self._stuck_since is None:
            self._stuck_since = now

        return (now - self._stuck_since) > self._stuck_threshold

    def execute(self, bridge: AbstractBridge) -> str:
        bridge.call("move_away", {"distance": 5})
        self._stuck_since = None
        return "[反射: 脱困] 检测到卡住超过120秒，尝试随机移动5格。"


# ══════════════════════════════════════════════════════════════════════════════
# Priority 3: Cowardice — hostile nearby, no weapon → flee
# ══════════════════════════════════════════════════════════════════════════════

class CowardiceReflex(Reflex):
    """mindcraft: cowardice — hostile mob within 16 blocks, no weapon.

    Checks inventory for any weapon-type item.  If none found, flees.
    """

    name = "cowardice"
    priority = 3
    cooldown_seconds = 5.0

    # Items that count as weapons
    _WEAPON_KEYWORDS = ("sword", "axe", "pickaxe", "trident", "mace")

    def should_trigger(self, perception_text, inventory, bridge) -> bool:
        # Quick check: are there hostile indicators?
        lower = perception_text.lower()
        has_hostile_indicator = any(
            h in lower for h in ("zombie", "skeleton", "creeper", "spider", "⚠")
        )
        if not has_hostile_indicator:
            return False

        # Verify with entity data
        try:
            entities_data = bridge.call("get_nearby_entities", {"radius": 16})
        except Exception:
            return False

        entities = entities_data.get("entities", [])
        hostiles = [e for e in entities if e.get("is_hostile")]
        if not hostiles:
            return False

        # Check weapons
        return not self._has_weapon(bridge)

    def _has_weapon(self, bridge) -> bool:
        """Check if NPC has any weapon in inventory or hand."""
        try:
            inv = bridge.call("get_inventory")
        except Exception:
            return False

        held = inv.get("held_item") or {}
        held_name = (held.get("name") or "").lower()
        if any(w in held_name for w in self._WEAPON_KEYWORDS):
            return True

        items = inv.get("items", {})
        for item_name in items:
            if any(w in item_name.lower() for w in self._WEAPON_KEYWORDS):
                return True

        return False

    def execute(self, bridge: AbstractBridge) -> str:
        bridge.call("move_away", {"distance": 16})
        return "[反射: 逃跑] 检测到敌对生物且无武器，自动远离16格。"


# ══════════════════════════════════════════════════════════════════════════════
# Priority 4: SelfDefense — hostile nearby, has weapon → fight
# ══════════════════════════════════════════════════════════════════════════════

class SelfDefenseReflex(Reflex):
    """mindcraft: self_defense — hostile within 8 blocks, has weapon."""

    name = "self_defense"
    priority = 4
    cooldown_seconds = 2.0

    _WEAPON_KEYWORDS = ("sword", "axe")

    def should_trigger(self, perception_text, inventory, bridge) -> bool:
        lower = perception_text.lower()
        has_hostile = any(
            h in lower for h in ("zombie", "skeleton", "creeper", "spider", "⚠")
        )
        if not has_hostile:
            return False

        try:
            entities_data = bridge.call("get_nearby_entities", {"radius": 8})
        except Exception:
            return False

        entities = entities_data.get("entities", [])
        hostiles = [e for e in entities if e.get("is_hostile")]
        if not hostiles:
            return False

        # Check for weapon
        try:
            inv = bridge.call("get_inventory")
        except Exception:
            return False

        held = inv.get("held_item") or {}
        held_name = (held.get("name") or "").lower()
        has_weapon = any(w in held_name for w in self._WEAPON_KEYWORDS)

        # Also fight if enemy is very close (< 4 blocks) even without weapon
        close_hostiles = [e for e in hostiles if e.get("distance", 99) <= 4]
        return has_weapon or bool(close_hostiles)

    def execute(self, bridge: AbstractBridge) -> str:
        result = bridge.call("defend_self", {"range": 8})
        return f"[反射: 自卫] 8格内有敌对生物，自动反击。结果: {result}"


# ══════════════════════════════════════════════════════════════════════════════
# Priority 5: TorchPlacing — darkness → mob spawning danger
# ══════════════════════════════════════════════════════════════════════════════

class TorchPlacingReflex(Reflex):
    """mindcraft: torch_placing — light < 7 at night/cave, has torches.

    Mobs spawn at light level < 7.  Placing torches prevents this.
    Only activates at night or when underground (low sky light).
    """

    name = "torch_placing"
    priority = 5
    cooldown_seconds = 15.0  # don't spam torch placement

    MIN_LIGHT = 7

    def should_trigger(self, perception_text, inventory, bridge) -> bool:
        try:
            stats = bridge.call("get_stats")
        except Exception:
            return False

        light = stats.get("light_level", 15)
        if light >= self.MIN_LIGHT:
            return False  # bright enough, no need

        # Only place torches at night or when underground (low sky light)
        time_of_day = stats.get("time", "")
        biome = stats.get("biome", "")

        # Night time or in a cave
        is_dark_time = time_of_day in ("Night", "") or "cave" in biome.lower()
        if not is_dark_time:
            return False

        # Check for torches
        try:
            inv = bridge.call("get_inventory")
        except Exception:
            return False

        items = inv.get("items", {})
        if items.get("torch", 0) <= 0:
            return False

        return True

    def execute(self, bridge: AbstractBridge) -> str:
        result = bridge.call("place_torch")
        if result.get("ok"):
            pos = result.get("position", [0, 0, 0])
            return f"[反射: 插火把] 光照不足，在({pos[0]}, {pos[1]}, {pos[2]})放置火把防止刷怪。"
        return f"[反射: 插火把] 尝试放置火把但失败: {result.get('reason', 'unknown')}"


# ══════════════════════════════════════════════════════════════════════════════
# Priority 6: Hunger — starvation prevention
# ══════════════════════════════════════════════════════════════════════════════

class HungerReflex(Reflex):
    """mindcraft-style hunger management — eat before starving.

    Separate from SelfPreservation because hunger isn't immediately
    life-threatening until very low.  This reflex prevents starvation
    proactively.
    """

    name = "hunger"
    priority = 6
    cooldown_seconds = 3.0

    HUNGER_THRESHOLD = 6  # eat when hunger drops to 6 or below

    def should_trigger(self, perception_text, inventory, bridge) -> bool:
        try:
            stats = bridge.call("get_stats")
        except Exception:
            return False

        hunger = stats.get("hunger", 20)
        if hunger > self.HUNGER_THRESHOLD:
            return False

        # Check for food
        try:
            inv = bridge.call("get_inventory")
        except Exception:
            return False

        items = inv.get("items", {})
        return any(food in items and items[food] > 0 for food in _FOOD_ITEMS)

    def execute(self, bridge: AbstractBridge) -> str:
        # Find best food (prefer cooked/high-saturation foods first)
        inv = bridge.call("get_inventory")
        items = inv.get("items", {})

        # Priority: cooked meats > bread > raw meats > anything edible
        priority_foods = [
            "cooked_beef", "cooked_porkchop", "golden_carrot", "golden_apple",
            "cooked_mutton", "cooked_chicken", "cooked_salmon", "cooked_cod",
            "bread", "baked_potato",
            "beef", "porkchop", "mutton", "chicken",
            "apple", "carrot", "melon_slice", "sweet_berries",
        ]

        for food in priority_foods:
            if items.get(food, 0) > 0:
                bridge.call("consume", {"item_name": food})
                stats = bridge.call("get_stats")
                hunger = stats.get("hunger", "?")
                return f"[反射: 进食] 饥饿度低({hunger}/20)，自动进食{food}。"

        # Fallback: any food item
        for item_name, count in items.items():
            if count > 0 and item_name in _FOOD_ITEMS:
                bridge.call("consume", {"item_name": item_name})
                return f"[反射: 进食] 饥饿度低，自动进食{item_name}。"

        return "[反射: 进食] 饥饿度低但没有食物可用。"


# ══════════════════════════════════════════════════════════════════════════════
# Priority 7: ItemCollecting — items on ground → pickup
# ══════════════════════════════════════════════════════════════════════════════

class ItemCollectingReflex(Reflex):
    """mindcraft: item_collecting — items on ground within 8 blocks."""

    name = "item_collecting"
    priority = 7
    cooldown_seconds = 3.0

    def should_trigger(self, perception_text, inventory, bridge) -> bool:
        lower = perception_text.lower()
        return "掉落物" in lower or "item" in lower

    def execute(self, bridge: AbstractBridge) -> str:
        result = bridge.call("pickup_nearby", {"radius": 8})
        picked = result.get("picked", 0)
        return f"[反射: 捡物] 捡起周围掉落物。拾取了{picked}个物品。"


# ── Reflex registry ─────────────────────────────────────────────────────────

def default_reflexes() -> list[Reflex]:
    """Return all reflexes in priority order (mirrors mindcraft mode ordering).

    Order matters: the first reflex whose ``should_trigger`` returns True
    wins the tick.  Only one reflex fires per tick for predictable behavior.
    """
    return [
        SelfPreservationReflex(),   # 1: fire, drowning, lava, critical HP
        UnstuckReflex(),            # 2: stuck detection
        CowardiceReflex(),          # 3: hostile + no weapon → flee
        SelfDefenseReflex(),        # 4: hostile + weapon → fight
        TorchPlacingReflex(),       # 5: darkness → place torch
        HungerReflex(),             # 6: hunger → eat
        ItemCollectingReflex(),     # 7: items → pickup
    ]
