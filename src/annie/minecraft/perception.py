"""Perception pipeline — 3D Minecraft world → LLM-readable text.

Design principles (from mindcraft queries.js patterns):
- Summary-first: concise overview in context, details via tools.
- Spatial ordering: nearest items first.
- Threat prioritisation: dangerous entities above passive ones.
- Inventory suppression: only key items in summary; full list via tool.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from annie.minecraft.bot_connection import AbstractBridge

# ── Hostile mob set (matches minecraft_bridge.js isHostile) ─────────────────
_HOSTILE_MOBS = frozenset({
    "zombie", "skeleton", "creeper", "spider", "cave_spider",
    "enderman", "witch", "slime", "phantom", "drowned", "husk", "stray",
    "blaze", "ghast", "magma_cube", "wither_skeleton", "piglin",
    "hoglin", "zoglin", "piglin_brute", "warden", "guardian", "elder_guardian",
})

# ── Drops list (items worth picking up from ground) ────────────────────────
_DROP_ITEMS = {
    "item",  # mineflayer entity name for dropped items
}

# ── Key inventory items to highlight even if count is low ──────────────────
_KEY_ITEMS = frozenset({
    "diamond", "diamond_pickaxe", "diamond_sword", "diamond_axe",
    "iron_ingot", "iron_pickaxe", "iron_sword", "golden_apple",
    "ender_pearl", "ender_eye", "obsidian", "enchanting_table",
    "bucket", "water_bucket", "lava_bucket", "flint_and_steel",
    "bow", "arrow", "shield", "fishing_rod", "saddle",
    "elytra", "netherite_scrap", "netherite_ingot",
})


class MinecraftPerception:
    """Snapshot and render the world around one NPC."""

    SUMMARY_MAX_CHARS = 2000

    def __init__(self, bridge: AbstractBridge):
        self._bridge = bridge

    # ── Data gathering ─────────────────────────────────────────────────

    def snapshot(self) -> dict[str, Any]:
        """Gather raw data from the bridge. Fully synchronous — works with
        both FakeBridge and MinecraftBridge (sync subprocess)."""
        stats = self._bridge.call("get_stats")
        blocks = self._bridge.call("get_nearby_blocks", {"radius": 4})
        entities = self._bridge.call("get_nearby_entities", {"radius": 16})
        inventory = self._bridge.call("get_inventory")
        return {
            "stats": stats,
            "blocks": blocks,
            "entities": entities,
            "inventory": inventory,
        }

    # snapshot() is always synchronous — see above.

    # ── Rendering ──────────────────────────────────────────────────────

    def render(self, snapshot: dict) -> str:
        """Render a perception snapshot into LLM-ready text.

        Order follows mindcraft's !stats + !nearbyBlocks + !entities + !inventory
        pattern: self-state → danger → drops → blocks → passive → players → inventory summary.
        """
        parts: list[str] = []

        # 1. Self state (stats)
        stats = snapshot.get("stats", {})
        if stats.get("ok"):
            parts.append(self._render_stats(stats))

        # 2. Nearby blocks
        blocks_data = snapshot.get("blocks", {})
        if blocks_data.get("ok") and blocks_data.get("blocks"):
            parts.append(self._render_blocks(blocks_data["blocks"]))

        # 3. Nearby entities (sorted: hostile > items > passive > players)
        entities_data = snapshot.get("entities", {})
        if entities_data.get("ok") and entities_data.get("entities"):
            parts.append(self._render_entities(entities_data["entities"]))

        # 4. Inventory summary
        inv_data = snapshot.get("inventory", {})
        if inv_data.get("ok"):
            parts.append(self._render_inventory_summary(inv_data))

        text = "\n\n".join(parts)
        if len(text) > self.SUMMARY_MAX_CHARS:
            text = text[:self.SUMMARY_MAX_CHARS - 50] + "\n[... perception summary truncated ...]"
        return text

    # ── Sub-renderers ──────────────────────────────────────────────────

    @staticmethod
    def _render_stats(stats: dict) -> str:
        pos = stats.get("position", [0, 0, 0])
        lines = [
            "[自身状态]",
            f"位置: ({pos[0]:.1f}, {pos[1]:.1f}, {pos[2]:.1f})",
            f"血量: {stats.get('health', '?')}/20, 饥饿度: {stats.get('hunger', '?')}/20",
            f"生物群系: {stats.get('biome', 'unknown')}, 天气: {stats.get('weather', 'Clear')}",
            f"时间: {stats.get('time', 'unknown')}",
        ]
        return "\n".join(lines)

    @staticmethod
    def _render_blocks(blocks: list[dict]) -> str:
        if not blocks:
            return "[周围方块]\n无特殊方块"

        # Group by name, count
        by_name: dict[str, int] = {}
        closest_per_type: dict[str, dict] = {}
        for b in blocks:
            name = b.get("name", "unknown")
            by_name[name] = by_name.get(name, 0) + 1
            if name not in closest_per_type:
                closest_per_type[name] = b

        lines = ["[周围方块 (半径4格)]"]
        for name, count in sorted(by_name.items(), key=lambda x: -x[1]):
            b = closest_per_type[name]
            rel = b.get("relative", [0, 0, 0])
            direction = _direction_label(rel)
            lines.append(f"{direction}: {name}×{count}")
        return "\n".join(lines)

    @staticmethod
    def _render_entities(entities: list[dict]) -> str:
        hostiles = [e for e in entities if e.get("is_hostile")]
        items = [e for e in entities if e.get("name") == "item"]
        players = [e for e in entities if e.get("type") == "player"]
        passive = [e for e in entities if not e.get("is_hostile") and e.get("name") != "item" and e.get("type") != "player"]

        lines = ["[周围实体 (半径16格)]"]
        for e in hostiles:
            dist = e.get("distance", 0)
            lines.append(f"⚠ {e.get('name', 'unknown')} (距离{dist:.1f}m)")

        if items:
            item_names: dict[str, int] = {}
            for e in items:
                n = e.get("name", "item")
                item_names[n] = item_names.get(n, 0) + 1
            for name, count in item_names.items():
                lines.append(f"掉落物×{count}")

        for e in passive:
            dist = e.get("distance", 0)
            lines.append(f"{e.get('name', 'unknown')} (距离{dist:.1f}m)")

        for e in players:
            dist = e.get("distance", 0)
            lines.append(f"玩家 {e.get('name', 'unknown')} (距离{dist:.1f}m)")

        if len(lines) == 1:
            lines.append("无实体")
        return "\n".join(lines)

    @staticmethod
    def _render_inventory_summary(inv: dict) -> str:
        items: dict[str, int] = inv.get("items", {})
        armor = inv.get("armor", {})
        held = inv.get("held_item")
        empty = inv.get("empty_slots", 0)

        lines = ["[物品栏摘要]"]

        # Held item
        if held:
            dur = f" 耐久{held.get('durability', '?')}%" if held.get("durability") is not None else ""
            lines.append(f"主手: {held.get('name', '?')}×{held.get('count', 1)}{dur}")

        # Armor
        armor_parts = []
        if armor.get("head"): armor_parts.append(f"头:{armor['head']}")
        if armor.get("chest"): armor_parts.append(f"身:{armor['chest']}")
        if armor.get("legs"): armor_parts.append(f"腿:{armor['legs']}")
        if armor.get("feet"): armor_parts.append(f"脚:{armor['feet']}")
        if armor_parts:
            lines.append(f"盔甲: {', '.join(armor_parts)}")
        else:
            lines.append("盔甲: 无")

        # Key/abundant items (top 8 by count, plus any _KEY_ITEMS)
        key_items = {k: v for k, v in items.items() if k in _KEY_ITEMS}
        abundant = sorted(
            [(k, v) for k, v in items.items() if k not in _KEY_ITEMS],
            key=lambda x: -x[1],
        )[:8]
        shown = dict(abundant)
        shown.update(key_items)
        if shown:
            item_strs = [f"{k}×{v}" for k, v in sorted(shown.items(), key=lambda x: -x[1])[:12]]
            lines.append(f"物品: {', '.join(item_strs)}")
        else:
            lines.append("物品: 空")

        lines.append(f"空格: {empty}/36")
        return "\n".join(lines)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _direction_label(rel: list[float]) -> str:
    """Convert relative coords to a Chinese direction label."""
    x, y, z = rel[0], rel[1], abs(rel[2]) if len(rel) > 2 else 0
    h_parts = []
    if abs(x) > abs(z):
        h_parts.append("前方" if z > 0 else "后方")
        h_parts.append("左" if x < 0 else "右" if x > 0 else "")
    else:
        h_parts.append("左" if x < 0 else "右" if x > 0 else "")
        h_parts.append("前方" if z > 0 else "后方")
    h = "".join(h_parts) or "脚下"
    if y > 1:
        return f"{h}上方"
    elif y < -1:
        return f"{h}下方"
    return h
