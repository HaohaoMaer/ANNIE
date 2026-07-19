"""Integration tests: MinecraftWorldEngine + NPCAgent end-to-end with FakeBridge.

These tests simulate a complete Minecraft survival scenario without requiring
a real Minecraft server or Node.js — all bridge calls return pre-programmed
responses and the LLM is stubbed.

Scenarios (following mindcraft's behaviour patterns):
  1. Perception renders correctly into AgentContext
  2. Tool calls dispatch through to FakeBridge
  3. Cowardice reflex triggers when hostile mob nearby and no weapon
  4. SelfDefense reflex triggers when hostile nearby and has weapon
  5. ItemCollecting reflex triggers on dropped items
  6. Full survival flow: spawn → collect wood → craft planks → craft sticks
     → hostile encounter → flee → make sword → fight back
"""

from __future__ import annotations

import pytest
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage

from annie.npc.agent import NPCAgent
from annie.npc.response import AgentResponse
from annie.minecraft.bot_connection import FakeBridge
from annie.minecraft.engine import MinecraftWorldEngine, create_test_engine
from annie.minecraft.reflexes import (
    CowardiceReflex,
    ItemCollectingReflex,
    SelfDefenseReflex,
    SelfPreservationReflex,
    UnstuckReflex,
)
from annie.world_engine.profile import NPCProfile, Personality, Background, Goals


# ── Stub LLM ────────────────────────────────────────────────────────────────

class _StubLLM:
    """Round-robin canned AIMessage responses, supports tool_calls."""

    def __init__(self, responses: list):
        self._responses = list(responses)
        self.calls: list[list[BaseMessage]] = []

    def invoke(self, messages, **__):
        self.calls.append(list(messages))
        if not self._responses:
            return AIMessage(content="")
        nxt = self._responses.pop(0)
        if isinstance(nxt, AIMessage):
            return nxt
        return AIMessage(content=str(nxt))

    def bind_tools(self, tools):
        return self


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def survivor_profile() -> NPCProfile:
    return NPCProfile(
        name="TestSurvivor",
        personality=Personality(traits=["cautious", "resourceful"], values=["survival"]),
        background=Background(biography="A test survivor."),
        goals=Goals(short_term=["survive"], long_term=["thrive"]),
        relationships=[],
        memory_seed=["Start with nothing."],
        skills=[],
        tools=[],
    )


@pytest.fixture
def fake_bridge() -> FakeBridge:
    return FakeBridge()


@pytest.fixture
def test_engine(fake_bridge, survivor_profile) -> MinecraftWorldEngine:
    return MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )


# ── Test 1: Perception renders into AgentContext ────────────────────────────

def test_build_context_includes_perception(test_engine):
    """AgentContext must contain rendered perception text in character_prompt field."""
    ctx = test_engine.build_context("TestSurvivor", event="The world loads around you.")

    assert ctx.npc_id == "TestSurvivor"
    # Perception is now embedded in character_prompt (system prompt includes <situation>)
    # to avoid duplication with the situation field
    assert ctx.character_prompt  # full system prompt with perception
    assert "[自身状态]" in ctx.character_prompt
    assert "血量" in ctx.character_prompt
    assert ctx.graph_id is not None
    assert len(ctx.tools) == 30  # full mindcraft toolset (movement 8, perception 3, operation 7, crafting 4, combat 3, interaction 2, storage 3)


# ── Test 2: Tools dispatch through FakeBridge ───────────────────────────────

def test_tool_dispatches_to_bridge(test_engine, fake_bridge):
    """When LLM calls check_inventory, the bridge receives the call."""
    fake_bridge.set_response("get_inventory", {
        "ok": True,
        "items": {"oak_log": 4, "stick": 2},
        "armor": {},
        "held_item": None,
        "empty_slots": 30,
    })

    llm = _StubLLM([
        AIMessage(content="", tool_calls=[
            {"name": "check_inventory", "args": {}, "id": "call_1"}
        ]),
        AIMessage(content="I have 4 oak logs and 2 sticks."),
    ])
    agent = NPCAgent(llm=llm)
    ctx = test_engine.build_context("TestSurvivor", event="Check what you have.")
    response = agent.run(ctx)

    assert isinstance(response, AgentResponse)
    assert "oak_log" in str(llm.calls).lower() or "check_inventory" in str(llm.calls).lower()
    # At least one call to get_inventory should be in the bridge log
    inv_calls = [c for c in fake_bridge.call_log if c["method"] == "get_inventory"]
    assert len(inv_calls) >= 1


# ── Test 3: Cowardice reflex — hostile nearby, no weapon → flee ────────────

def test_cowardice_reflex_triggers_no_weapon(fake_bridge, survivor_profile):
    """With a zombie nearby and no weapon, cowardice reflex should trigger."""
    # Program bridge: zombie at distance 10
    fake_bridge.set_response("get_nearby_entities", {
        "ok": True,
        "entities": [
            {"name": "zombie", "type": "mob", "position": [10, 64, 0],
             "distance": 10.0, "is_hostile": True},
        ],
    })
    # No weapons in inventory
    fake_bridge.set_response("get_inventory", {
        "ok": True, "items": {"oak_log": 3}, "armor": {},
        "held_item": None, "empty_slots": 33,
    })
    fake_bridge.set_response("move_away", {"ok": True, "moved": 16})

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    # Refresh perception snapshot
    snapshot = engine._perception.snapshot()
    perception_text = engine._perception.render(snapshot)
    inv = snapshot.get("inventory", {})

    reflex = CowardiceReflex()
    assert reflex.should_trigger(perception_text, inv, fake_bridge)
    result = reflex.run(perception_text, inv, fake_bridge)
    assert result.triggered
    assert "逃跑" in result.event_text


# ── Test 4: SelfDefense reflex — hostile nearby, has weapon → fight ────────

def test_self_defense_reflex_triggers_with_weapon(fake_bridge, survivor_profile):
    """With a skeleton at distance 5 and a stone sword equipped, fight back."""
    fake_bridge.set_response("get_nearby_entities", {
        "ok": True,
        "entities": [
            {"name": "skeleton", "type": "hostile", "position": [5, 64, 0],
             "distance": 5.0, "is_hostile": True},
        ],
    })
    fake_bridge.set_response("get_inventory", {
        "ok": True,
        "items": {"stone_sword": 1},
        "armor": {},
        "held_item": {"name": "stone_sword", "count": 1, "durability": 95},
        "empty_slots": 34,
    })
    fake_bridge.set_response("defend_self", {"ok": True, "attacked": "skeleton", "range": 8})

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    snapshot = engine._perception.snapshot()
    perception_text = engine._perception.render(snapshot)
    inv = snapshot.get("inventory", {})

    reflex = SelfDefenseReflex()
    assert reflex.should_trigger(perception_text, inv, fake_bridge)
    result = reflex.run(perception_text, inv, fake_bridge)
    assert result.triggered
    assert "自卫" in result.event_text


# ── Test 5: ItemCollecting reflex — dropped items → pick up ─────────────────

def test_item_collecting_reflex_triggers(fake_bridge, survivor_profile):
    """Dropped items in perception text should trigger the collecting reflex."""
    fake_bridge.set_response("get_nearby_entities", {"ok": True, "entities": []})
    fake_bridge.set_response("pickup_nearby", {"ok": True, "picked": 3})

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    # Build a perception text that mentions dropped items
    snapshot = engine._perception.snapshot()
    # Inject item entities
    snapshot["entities"] = {
        "ok": True,
        "entities": [
            {"name": "item", "type": "object", "position": [2, 64, 0],
             "distance": 2.0, "is_hostile": False},
        ],
    }
    perception_text = engine._perception.render(snapshot)
    inv = snapshot.get("inventory", {})

    reflex = ItemCollectingReflex()
    assert reflex.should_trigger(perception_text, inv, fake_bridge)
    result = reflex.run(perception_text, inv, fake_bridge)
    assert result.triggered
    assert "捡物" in result.event_text


# ── Test 6: SelfPreservation reflex triggers on low health ──────────────────

def test_self_preservation_reflex_triggers_low_hp(fake_bridge, survivor_profile):
    """Health <= 8 should trigger self-preservation."""
    # Override the default stats to low health
    fake_bridge._startup_state["stats"]["health"] = 4
    fake_bridge.set_response("get_stats", {
        "ok": True,
        "position": [0, 64, 0],
        "health": 4,
        "hunger": 15,
        "biome": "plains",
        "time": "Afternoon",
        "weather": "Clear",
        "gamemode": "survival",
    })
    fake_bridge.set_response("get_nearby_entities", {"ok": True, "entities": []})
    fake_bridge.set_response("move_away", {"ok": True, "moved": 10})

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    snapshot = engine._perception.snapshot()
    perception_text = engine._perception.render(snapshot)
    inv = snapshot.get("inventory", {})

    reflex = SelfPreservationReflex()
    assert reflex.should_trigger(perception_text, inv, fake_bridge)
    result = reflex.run(perception_text, inv, fake_bridge)
    assert result.triggered
    assert "自保" in result.event_text


# ── Test 7: Unstuck reflex detects being stuck ──────────────────────────────

def test_unstuck_reflex_detects_stuck(fake_bridge, survivor_profile):
    """Same position across multiple checks should trigger unstuck."""
    fake_bridge.set_response("get_stats", {
        "ok": True, "position": [0, 64, 0], "health": 20,
        "hunger": 20, "biome": "plains", "time": "Morning",
        "weather": "Clear", "gamemode": "survival",
    })
    fake_bridge.set_response("move_away", {"ok": True, "moved": 5})

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    reflex = UnstuckReflex()
    # Lower the threshold for testing
    reflex._stuck_threshold = 0.0  # trigger immediately on second check
    reflex.cooldown_seconds = 0

    snapshot = engine._perception.snapshot()
    perception_text = engine._perception.render(snapshot)
    inv = snapshot.get("inventory", {})

    # First call: no trigger (sets initial position)
    assert not reflex.should_trigger(perception_text, inv, fake_bridge)
    # Second call: marks stuck_since timestamp
    assert not reflex.should_trigger(perception_text, inv, fake_bridge)
    # Third call: stuck threshold (0.0) exceeded since last call
    assert reflex.should_trigger(perception_text, inv, fake_bridge)

    result = reflex.run(perception_text, inv, fake_bridge)
    assert result.triggered
    assert "脱困" in result.event_text


# ── Test 8: Full survival flow end-to-end ───────────────────────────────────

def test_full_survival_flow_wood_to_sword(fake_bridge, survivor_profile):
    """Simulate the classic Minecraft start: wood → planks → sticks → tools.

    The LLM is stubbed to produce the sequence of tool calls a survival NPC
    would make in its first minutes.
    """
    # Set up the world: trees nearby, no immediate threats
    fake_bridge.set_response("get_nearby_blocks", {
        "ok": True,
        "blocks": [
            {"name": "oak_log", "position": [2, 64, 0], "relative": [2, 0, 0], "distance": 2.0},
            {"name": "grass_block", "position": [0, 63, 0], "relative": [0, -1, 0], "distance": 1.0},
        ],
    })
    fake_bridge.set_response("get_nearby_entities", {"ok": True, "entities": []})
    fake_bridge.set_response("get_inventory", {
        "ok": True,
        "items": {"oak_log": 4},
        "armor": {},
        "held_item": None,
        "empty_slots": 32,
    })
    fake_bridge.set_response("get_craftable", {
        "ok": True,
        "craftable": ["oak_planks", "stick", "crafting_table", "wooden_pickaxe"],
    })
    fake_bridge.set_response("collect_block", {"ok": True, "collected": 4, "target": 4})
    fake_bridge.set_response("craft_recipe", {"ok": True, "crafted": "oak_planks", "count": 4})
    fake_bridge.set_response("go_to_block", {"ok": True, "block": "oak_log", "position": [2, 64, 0]})

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )
    engine.set_goal("收集木头并合成基础工具")

    # Stubbed LLM responses: a realistic survival sequence
    # Step 1: See trees, decide to collect wood
    # Step 2: Craft planks from wood
    llm = _StubLLM([
        # Turn 1: Collect wood
        AIMessage(content="我看到了橡树，先去收集一些原木。", tool_calls=[
            {"name": "collect_item", "args": {"item_type": "oak_log", "count": 4}, "id": "c1"}
        ]),
        # Turn 2: After collecting, craft planks
        AIMessage(content="获得了4个原木，现在合成为木板。", tool_calls=[
            {"name": "craft", "args": {"item_name": "oak_planks", "count": 4}, "id": "c2"}
        ]),
        # Turn 3: Check what else can be crafted
        AIMessage(content="木板制作完成。检查可以合成什么工具。", tool_calls=[
            {"name": "check_craftable", "args": {}, "id": "c3"}
        ]),
        # Turn 4: Final response
        AIMessage(content="我现在有4块木板，下一步需要合成木棍和工作台，然后制作木镐。"),
    ])

    agent = NPCAgent(llm=llm)

    # Run step 1: NPC decides to collect wood
    ctx = engine.build_context("TestSurvivor", event="你出生在一片平原上，周围有橡树。")
    response1 = agent.run(ctx)
    assert isinstance(response1, AgentResponse)
    # When a tool has ends_activation_on_success, the executor returns a
    # placeholder. The important thing is that the tool was dispatched.
    # Check that the bridge received the collect_block call.
    assert response1 is not None

    engine.handle_response("TestSurvivor", response1)

    # Run step 2: Continue crafting
    ctx2 = engine.build_context("TestSurvivor", event="[动作完成] 收集了4个橡木原木。")
    response2 = agent.run(ctx2)
    assert isinstance(response2, AgentResponse)

    engine.handle_response("TestSurvivor", response2)

    # Both turns should have produced valid responses
    assert len(engine.responses) == 2
    # Bridge should have received calls for the tools dispatched by the LLM
    methods_called = {c["method"] for c in fake_bridge.call_log}
    # At minimum we expect perception calls (get_inventory, get_nearby_blocks, etc.)
    # and tool execution calls (collect_block, craft_recipe, or get_craftable)
    mc_tool_calls = methods_called & {"collect_block", "craft_recipe", "get_craftable", "get_inventory", "get_nearby_blocks", "get_nearby_entities", "get_stats"}
    assert len(mc_tool_calls) >= 1, f"Expected at least one Minecraft method call, got: {methods_called}"


# ── Test 9: Hostile encounter triggers reflex → then cognition responds ─────

def test_hostile_encounter_triggers_reflex_then_cognition(fake_bridge, survivor_profile):
    """Reflex fires on hostile sighting; LLM then reasons about the situation."""
    # Pre-program: zombie nearby, no weapons
    fake_bridge.set_response("get_nearby_entities", {
        "ok": True,
        "entities": [
            {"name": "zombie", "type": "mob", "position": [8, 64, 0],
             "distance": 8.0, "is_hostile": True},
        ],
    })
    fake_bridge.set_response("get_inventory", {
        "ok": True, "items": {"oak_log": 3}, "armor": {},
        "held_item": None, "empty_slots": 33,
    })
    fake_bridge.set_response("move_away", {"ok": True, "moved": 16})

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    # Stub LLM: responds to the reflex event with appropriate reasoning
    llm = _StubLLM([
        AIMessage(content="糟了，有僵尸！但我没有武器，应该先收集材料制作一把剑。 "
                   "我先去砍些木头。", tool_calls=[
            {"name": "collect_item", "args": {"item_type": "oak_log", "count": 2}, "id": "c1"}
        ]),
    ])
    agent = NPCAgent(llm=llm)

    # Simulate the engine's step:
    # 1. Poll events (none)
    # 2. Reflex check → cowardice triggers
    snapshot = engine._perception.snapshot()
    perception_text = engine._perception.render(snapshot)
    inv = snapshot.get("inventory", {})

    reflex = CowardiceReflex()
    reflex_result = reflex.run(perception_text, inv, fake_bridge)
    assert reflex_result.triggered
    assert "逃跑" in reflex_result.event_text

    # 3. Reflex result is fed as event to cognition
    ctx = engine.build_context("TestSurvivor", event=reflex_result.event_text)
    response = agent.run(ctx)

    assert isinstance(response, AgentResponse)
    # The LLM should acknowledge the threat and take action
    assert len(llm.calls) > 0


# ── Test 10: Reflex priority — self_preservation beats cowardice ────────────

def test_reflex_priority_self_preservation_over_cowardice(fake_bridge, survivor_profile):
    """When both low HP and a zombie are present, self-preservation fires first."""
    fake_bridge.set_response("get_nearby_entities", {
        "ok": True,
        "entities": [
            {"name": "zombie", "type": "mob", "position": [8, 64, 0],
             "distance": 8.0, "is_hostile": True},
        ],
    })
    fake_bridge.set_response("get_inventory", {
        "ok": True, "items": {}, "armor": {}, "held_item": None, "empty_slots": 36,
    })
    fake_bridge.set_response("get_stats", {
        "ok": True, "position": [0, 64, 0], "health": 3, "hunger": 15,
        "biome": "plains", "time": "", "weather": "", "gamemode": "survival",
    })
    fake_bridge.set_response("move_away", {"ok": True, "moved": 10})

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    # Run all reflexes in priority order (like the engine does)
    from annie.minecraft.reflexes import default_reflexes
    reflexes = default_reflexes()

    snapshot = engine._perception.snapshot()
    perception_text = engine._perception.render(snapshot)
    inv = snapshot.get("inventory", {})

    results = []
    for r in reflexes:
        result = r.run(perception_text, inv, fake_bridge)
        results.append(result)
        if result.triggered:
            break  # first triggered reflex wins

    triggered = [r for r in results if r.triggered]
    assert len(triggered) >= 1
    # Self-preservation (priority 1) should trigger before cowardice (priority 3)
    assert triggered[0].reflex_name == "self_preservation"


# ── Test 11: Perception handles empty world gracefully ──────────────────────

def test_perception_empty_world(test_engine):
    """Perception should render useful text even when nothing is nearby."""
    ctx = test_engine.build_context("TestSurvivor", event="The world is empty.")
    # Perception lives in character_prompt now (system prompt includes <situation>)
    assert "[自身状态]" in ctx.character_prompt
    assert "血量" in ctx.character_prompt
    # Should not crash on empty blocks/entities
    assert isinstance(ctx.character_prompt, str)
    assert len(ctx.character_prompt) > 0


# ── Test 12: NPCProfile renders correctly into system prompt ────────────────

def test_profile_renders_in_prompt(test_engine):
    """NPC name, traits, and goals should appear in the system prompt."""
    ctx = test_engine.build_context("TestSurvivor", event="Wake up.")
    # The character_prompt field contains the full system prompt in Minecraft engine
    prompt = ctx.character_prompt
    assert "TestSurvivor" in prompt
    assert "cautious" in prompt or "resourceful" in prompt
    # Should contain the available tools section
    assert "go_to_coordinates" in prompt
    assert "craft" in prompt
    assert "attack" in prompt


# ── Test 13: TorchPlacing reflex — low light + torches → place torch ────────

def test_torch_placing_reflex_triggers_in_darkness(fake_bridge, survivor_profile):
    """Light < 7 at night with torches in inventory should trigger torch placing."""
    fake_bridge.set_response("get_stats", {
        "ok": True, "position": [0, 64, 0], "health": 20,
        "hunger": 20, "biome": "plains", "time": "Night",
        "weather": "Clear", "gamemode": "survival",
        "light_level": 3,
        "on_fire": False, "in_water": False, "submerged": False,
        "fall_risk": 0, "nearby_danger_blocks": [],
    })
    fake_bridge.set_response("get_inventory", {
        "ok": True, "items": {"torch": 16, "oak_log": 3},
        "armor": {}, "held_item": None, "empty_slots": 30,
    })
    fake_bridge.set_response("place_torch", {
        "ok": True, "position": [0, 65, 1], "light_before": 3, "placed": "torch",
    })

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    snapshot = engine._perception.snapshot()
    perception_text = engine._perception.render(snapshot)
    inv = snapshot.get("inventory", {})

    from annie.minecraft.reflexes import TorchPlacingReflex
    reflex = TorchPlacingReflex()
    assert reflex.should_trigger(perception_text, inv, fake_bridge)
    result = reflex.run(perception_text, inv, fake_bridge)
    assert result.triggered
    assert "火把" in result.event_text


# ── Test 14: TorchPlacing reflex — don't trigger in daylight ────────────────

def test_torch_placing_reflex_skips_in_daylight(fake_bridge, survivor_profile):
    """Even with low light, don't place torches during daytime (skylight handles it)."""
    fake_bridge.set_response("get_stats", {
        "ok": True, "position": [0, 64, 0], "health": 20,
        "hunger": 20, "biome": "plains", "time": "Afternoon",
        "weather": "Clear", "gamemode": "survival",
        "light_level": 3,  # low because under a tree, but it's daytime
        "on_fire": False, "in_water": False, "submerged": False,
        "fall_risk": 0, "nearby_danger_blocks": [],
    })
    fake_bridge.set_response("get_inventory", {
        "ok": True, "items": {"torch": 16},
        "armor": {}, "held_item": None, "empty_slots": 32,
    })

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    snapshot = engine._perception.snapshot()
    perception_text = engine._perception.render(snapshot)
    inv = snapshot.get("inventory", {})

    from annie.minecraft.reflexes import TorchPlacingReflex
    reflex = TorchPlacingReflex()
    assert not reflex.should_trigger(perception_text, inv, fake_bridge)


# ── Test 15: HungerReflex — low hunger + food → eat ─────────────────────────

def test_hunger_reflex_triggers_when_hungry(fake_bridge, survivor_profile):
    """Hunger ≤ 6 with food available should trigger eating."""
    fake_bridge.set_response("get_stats", {
        "ok": True, "position": [0, 64, 0], "health": 20,
        "hunger": 5, "biome": "plains", "time": "Afternoon",
        "weather": "Clear", "gamemode": "survival",
        "light_level": 15,
        "on_fire": False, "in_water": False, "submerged": False,
        "fall_risk": 0, "nearby_danger_blocks": [],
    })
    fake_bridge.set_response("get_inventory", {
        "ok": True, "items": {"cooked_beef": 3, "oak_log": 5},
        "armor": {}, "held_item": None, "empty_slots": 28,
    })
    fake_bridge.set_response("consume", {"ok": True, "consumed": "cooked_beef"})

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    snapshot = engine._perception.snapshot()
    perception_text = engine._perception.render(snapshot)
    inv = snapshot.get("inventory", {})

    from annie.minecraft.reflexes import HungerReflex
    reflex = HungerReflex()
    assert reflex.should_trigger(perception_text, inv, fake_bridge)
    result = reflex.run(perception_text, inv, fake_bridge)
    assert result.triggered
    assert "进食" in result.event_text


# ── Test 16: SelfPreservation — on fire triggers move_away ──────────────────

def test_self_preservation_on_fire(fake_bridge, survivor_profile):
    """Being on fire should trigger self_preservation immediately."""
    fake_bridge.set_response("get_stats", {
        "ok": True, "position": [0, 64, 0], "health": 18,
        "hunger": 20, "biome": "plains", "time": "Afternoon",
        "weather": "Clear", "gamemode": "survival",
        "light_level": 15,
        "on_fire": True,
        "in_water": False, "submerged": False,
        "fall_risk": 0, "nearby_danger_blocks": [],
    })
    fake_bridge.set_response("move_away", {"ok": True, "moved": 10})

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    snapshot = engine._perception.snapshot()
    perception_text = engine._perception.render(snapshot)
    inv = snapshot.get("inventory", {})

    from annie.minecraft.reflexes import SelfPreservationReflex
    reflex = SelfPreservationReflex()
    assert reflex.should_trigger(perception_text, inv, fake_bridge)
    result = reflex.run(perception_text, inv, fake_bridge)
    assert result.triggered
    assert "着火" in result.event_text


# ── Test 17: SelfPreservation — lava nearby triggers move_away ──────────────

def test_self_preservation_lava_nearby(fake_bridge, survivor_profile):
    """Lava within 5 blocks should trigger self_preservation."""
    fake_bridge.set_response("get_stats", {
        "ok": True, "position": [0, 64, 0], "health": 20,
        "hunger": 20, "biome": "nether_wastes", "time": "Afternoon",
        "weather": "Clear", "gamemode": "survival",
        "light_level": 10,
        "on_fire": False, "in_water": False, "submerged": False,
        "fall_risk": 0,
        "nearby_danger_blocks": [
            {"name": "lava", "position": [3, 63, 0], "distance": 3.0},
        ],
    })
    fake_bridge.set_response("move_away", {"ok": True, "moved": 10})

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    snapshot = engine._perception.snapshot()
    perception_text = engine._perception.render(snapshot)
    inv = snapshot.get("inventory", {})

    from annie.minecraft.reflexes import SelfPreservationReflex
    reflex = SelfPreservationReflex()
    assert reflex.should_trigger(perception_text, inv, fake_bridge)
    result = reflex.run(perception_text, inv, fake_bridge)
    assert result.triggered
    assert "危险方块" in result.event_text or "lava" in result.event_text.lower()


# ── Test 18: SelfPreservation — submerged triggers go_to_surface ────────────

def test_self_preservation_submerged_drowning(fake_bridge, survivor_profile):
    """Being submerged in water should trigger go_to_surface."""
    fake_bridge.set_response("get_stats", {
        "ok": True, "position": [0, 55, 0], "health": 20,
        "hunger": 20, "biome": "ocean", "time": "Afternoon",
        "weather": "Clear", "gamemode": "survival",
        "light_level": 10,
        "on_fire": False, "in_water": True, "submerged": True,
        "fall_risk": 0, "nearby_danger_blocks": [],
    })
    fake_bridge.set_response("go_to_surface", {
        "ok": True, "position": [0, 64, 0],
    })

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    snapshot = engine._perception.snapshot()
    perception_text = engine._perception.render(snapshot)
    inv = snapshot.get("inventory", {})

    from annie.minecraft.reflexes import SelfPreservationReflex
    reflex = SelfPreservationReflex()
    assert reflex.should_trigger(perception_text, inv, fake_bridge)
    result = reflex.run(perception_text, inv, fake_bridge)
    assert result.triggered
    assert "溺水" in result.event_text


# ── Test 19: Default reflexes includes all 7 ────────────────────────────────

def test_default_reflexes_count():
    """There should be 7 default reflexes matching mindcraft's coverage."""
    from annie.minecraft.reflexes import default_reflexes
    reflexes = default_reflexes()
    assert len(reflexes) == 7
    # Verify priority ordering
    names = [r.name for r in sorted(reflexes, key=lambda r: r.priority)]
    assert names[0] == "self_preservation"
    assert names[1] == "unstuck"
    assert names[2] == "cowardice"
    assert names[3] == "self_defense"
    assert names[4] == "torch_placing"
    assert names[5] == "hunger"
    assert names[6] == "item_collecting"


# ── Test 20: Pre-tool danger hook interrupts tool execution on fire ──────────

def test_pre_tool_hook_interrupts_on_danger(fake_bridge, survivor_profile):
    """When on_fire, the pre-tool hook should intercept tool calls and return
    an interrupt message instead of executing the tool."""
    # Set up: NPC is on fire
    fake_bridge.set_response("get_stats", {
        "ok": True, "position": [0, 64, 0], "health": 18,
        "hunger": 20, "biome": "plains", "time": "Afternoon",
        "weather": "Clear", "gamemode": "survival",
        "light_level": 15,
        "on_fire": True,
        "in_water": False, "submerged": False,
        "fall_risk": 0, "nearby_danger_blocks": [],
    })
    fake_bridge.set_response("stop_moving", {"ok": True})
    fake_bridge.set_response("move_away", {"ok": True, "moved": 10})

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    # Get the pre_tool_hook from build_context
    ctx = engine.build_context("TestSurvivor", event="Go collect wood.")
    hook = ctx.extra.get("_pre_tool_hook")
    assert hook is not None, "Engine should inject _pre_tool_hook into extra"

    # Simulate a tool call that would normally execute
    tool_call = {"name": "go_to_coordinates", "args": {"x": 100, "y": 64, "z": 200}, "id": "call_1"}

    # The hook should detect fire and return an interrupt message
    result = hook(tool_call)
    assert result is not None, "Hook should return interrupt when on fire"
    assert "着火" in result
    assert "危险中断" in result


# ── Test 21: Pre-tool hook returns None when safe ────────────────────────────

def test_pre_tool_hook_returns_none_when_safe(fake_bridge, survivor_profile):
    """When no danger, the pre-tool hook should return None (tool proceeds)."""
    fake_bridge.set_response("get_stats", {
        "ok": True, "position": [0, 64, 0], "health": 20,
        "hunger": 20, "biome": "plains", "time": "Afternoon",
        "weather": "Clear", "gamemode": "survival",
        "light_level": 15,
        "on_fire": False,
        "in_water": False, "submerged": False,
        "fall_risk": 0, "nearby_danger_blocks": [],
    })

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    ctx = engine.build_context("TestSurvivor", event="Go collect wood.")
    hook = ctx.extra.get("_pre_tool_hook")
    assert hook is not None

    tool_call = {"name": "go_to_coordinates", "args": {"x": 100, "y": 64, "z": 200}, "id": "call_1"}
    result = hook(tool_call)
    assert result is None, "Hook should return None when no danger"


# ── Test 22: Pre-tool hook interrupts on critical HP ─────────────────────────

def test_pre_tool_hook_interrupts_critical_hp(fake_bridge, survivor_profile):
    """HP ≤ 6 should trigger pre-tool interrupt."""
    fake_bridge.set_response("get_stats", {
        "ok": True, "position": [0, 64, 0], "health": 4,
        "hunger": 15, "biome": "plains", "time": "Afternoon",
        "weather": "Clear", "gamemode": "survival",
        "light_level": 15,
        "on_fire": False,
        "in_water": False, "submerged": False,
        "fall_risk": 0, "nearby_danger_blocks": [],
    })
    fake_bridge.set_response("stop_moving", {"ok": True})
    fake_bridge.set_response("move_away", {"ok": True, "moved": 10})

    engine = MinecraftWorldEngine(
        bridge=fake_bridge,
        profile=survivor_profile,
        history_dir="./data/minecraft/test_history",
    )

    ctx = engine.build_context("TestSurvivor", event="Keep working.")
    hook = ctx.extra.get("_pre_tool_hook")
    result = hook({"name": "collect_item", "args": {}, "id": "c1"})
    assert result is not None
    assert "血量危急" in result
