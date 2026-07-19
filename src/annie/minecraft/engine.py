"""MinecraftWorldEngine — ANNIE World Engine for Minecraft companion NPCs.

Architecture (mindcraft-inspired dual-layer)
--------------------------------------------

**Layer 1 — Hardcoded Reflexes (300 ms, no LLM)**
  Environment perception, danger detection, danger avoidance, item pickup,
  and stuck detection run as priority-ordered reflexes.  Every reflex checks
  conditions and may execute a bridge action directly — no LLM involvement.
  Results are logged as informational events for the next cognition cycle.

**Layer 2 — LLM Cognition (on-demand only)**
  Triggered exclusively by:
  1. Player messages (chat events from the game or commands from the dashboard)
  2. Active task execution (NPC is mid-task and needs to plan the next step)

  When no player interaction is pending and no task is active, the LLM is
  never called — the NPC simply stands by, kept safe by the reflex layer.

Composes bridge, reflexes, perception, tools, and memory into a complete
Minecraft NPC runtime.  The NPC Agent layer runs unchanged — all Minecraft
complexity is confined to this engine.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

from annie.npc.context import AgentContext
from annie.npc.graph_registry import AgentGraphID
from annie.npc.memory.interface import MemoryInterface
from annie.npc.response import ActionRequest, ActionResult, AgentResponse
from annie.npc.routes import AgentRoute
from annie.world_engine.base import WorldEngine
from annie.world_engine.compressor import Compressor
from annie.world_engine.history import HistoryStore
from annie.world_engine.memory import DefaultMemoryInterface
from annie.world_engine.profile import NPCProfile, load_npc_profile, profile_to_character_prompt

from annie.minecraft.bot_connection import AbstractBridge, BridgeEvent, FakeBridge
from annie.minecraft.perception import MinecraftPerception
from annie.minecraft.prompts import build_minecraft_system_prompt
from annie.minecraft.reflexes import Reflex, ReflexResult, default_reflexes
from annie.minecraft.tools import (
    GoToCoordinatesTool,
    GoToBlockTool,
    StopMovingTool,
    MoveAwayTool,
    DigDownTool,
    GoToSurfaceTool,
    FollowPlayerTool,
    GoToPlayerTool,
    CheckSurroundingsTool,
    CheckInventoryTool,
    CheckCraftableTool,
    BreakBlockTool,
    CollectItemTool,
    EquipTool,
    ConsumeTool,
    DiscardTool,
    PlaceBlockTool,
    PickupNearbyTool,
    CraftTool,
    GetCraftingPlanTool,
    SmeltItemTool,
    ClearFurnaceTool,
    AttackTool,
    DefendTool,
    EquipHighestAttackTool,
    SendChatTool,
    GiveToPlayerTool,
    ViewChestTool,
    TakeFromChestTool,
    PutInChestTool,
)

logger = logging.getLogger(__name__)

# ── Constants ───────────────────────────────────────────────────────────────

MAX_HISTORY_TURNS = 30
DEFAULT_MAX_ACTION_STEPS = 8
DEFAULT_REFLECTION_INTERVAL = 120   # seconds between reflection checks
MIN_COGNITION_INTERVAL = 1.0        # seconds — rate-limit LLM calls
MAX_CONSECUTIVE_ACTION_CYCLES = 5   # safety limit for task execution loops

# Event tags that indicate player interaction (trigger LLM cognition)
_PLAYER_EVENT_TAGS = ("[聊天]", "[私聊]", "[玩家指令]")


class MinecraftWorldEngine(WorldEngine):
    """World Engine driving an ANNIE NPC inside Minecraft.

    Construction
    ------------
    bridge : AbstractBridge
        Connection to Minecraft (real subprocess or FakeBridge for tests).
    profile : NPCProfile
        The NPC's personality, goals, and memory seeds.
    history_dir : Path, optional
        Where to persist per-NPC JSONL history.  Defaults to ``./data/minecraft/history``.
    chroma_client : optional
        Pre-existing ChromaDB client.  Created fresh if omitted.
    llm : optional
        BaseChatModel for the Compressor (history folding).  No fold if None.
    """

    def __init__(
        self,
        bridge: AbstractBridge,
        profile: NPCProfile,
        *,
        history_dir: str = "./data/minecraft/history",
        chroma_client=None,
        llm=None,
        reflexes: list[Reflex] | None = None,
        difficulty: str = "normal",
        event_hook: "Callable[[BridgeEvent], None] | None" = None,
    ):
        self._bridge = bridge
        self._profile = profile
        self._difficulty = difficulty
        self._llm = llm

        self._perception = MinecraftPerception(bridge)
        self._reflexes = reflexes or default_reflexes()

        # Optional callback for external observers (e.g. monitor dashboard)
        self._event_hook = event_hook

        # Per-NPC state
        self._npc_id = profile.name
        self._memory: DefaultMemoryInterface | None = None
        self._history: HistoryStore | None = None
        self._compressor: Compressor | None = None

        # Event / task tracking
        self._pending_events: list[str] = []       # events waiting for LLM processing
        self._current_goal: str = "等待玩家指令，观察周围环境"
        self._last_reflection_time: float = 0.0
        self._action_log: list[dict] = []
        self._responses: list[AgentResponse] = []

        # ── Dual-layer state (new) ──────────────────────────────────────
        # Task execution tracking
        self._active_task: bool = False
        self._task_goal: str = ""
        self._consecutive_action_cycles: int = 0

        # Perception cache (populated by reflex_tick, read by monitor)
        self._cached_snapshot: dict[str, Any] = {}
        self._cached_perception_text: str = ""

        # LLM rate limiting
        self._last_cognition_time: float = 0.0

        # Paths
        from pathlib import Path
        self._history_dir = Path(history_dir)
        self._history_dir.mkdir(parents=True, exist_ok=True)

        # Character prompt (cached)
        self._character_prompt = profile_to_character_prompt(profile)

    # ═══════════════════════════════════════════════════════════════════════
    # Layer 1 — Hardcoded Reflex Tick (300 ms, no LLM)
    # ═══════════════════════════════════════════════════════════════════════

    def reflex_tick(self) -> ReflexResult | None:
        """Fast hardcoded tick — call every ~300 ms.  **No LLM.**

        1. Drain bridge events (chat → queue for cognition, damage/death → log)
        2. Run reflexes in priority order (first triggered reflex wins)
        3. Refresh the perception cache so the monitor stays live

        Returns
        -------
        ReflexResult or None
            The result if a reflex triggered, ``None`` otherwise.
        """
        # 1. Drain bridge events
        self._poll_bridge_events()

        # 2. Run reflexes (first triggered wins)
        reflex_result = self._check_reflexes()

        # 3. Refresh perception cache for monitor / state updates
        try:
            self._cached_snapshot = self._perception.snapshot()
            self._cached_perception_text = self._perception.render(self._cached_snapshot)
        except Exception:
            logger.debug("Perception cache refresh failed", exc_info=True)

        if reflex_result.triggered:
            # Log the reflex event — it will be seen by the next LLM cognition
            # (whenever that happens), but does NOT trigger LLM by itself.
            self._pending_events.append(reflex_result.event_text)

        return reflex_result if reflex_result.triggered else None

    @property
    def cached_perception_text(self) -> str:
        """Most recent perception snapshot as rendered text (no bridge call)."""
        return self._cached_perception_text

    @property
    def cached_snapshot(self) -> dict[str, Any]:
        """Most recent perception snapshot dict (no bridge call)."""
        return self._cached_snapshot

    # ═══════════════════════════════════════════════════════════════════════
    # Layer 2 — LLM Cognition (on-demand only)
    # ═══════════════════════════════════════════════════════════════════════

    def should_activate_cognition(self) -> bool:
        """Gate: should we call the LLM this tick?

        Returns ``True`` ONLY when:
        - A player-related event is queued (chat / dashboard command)
        - The NPC is actively executing a task

        Damage, death, reflex events, and idle observation do **not** trigger
        LLM — they are handled by the hardcoded reflex layer.
        """
        # Rate limit: at most one LLM call per MIN_COGNITION_INTERVAL
        if time.time() - self._last_cognition_time < MIN_COGNITION_INTERVAL:
            return False

        # Active task execution → always allow
        if self._active_task:
            return True

        # Player interaction → allow
        if self._has_player_events():
            return True

        return False

    def cognition_tick(self, agent, npc_id: str) -> AgentResponse | None:
        """Run one LLM cognition cycle.

        Only call this when :meth:`should_activate_cognition` returned ``True``.
        Returns ``None`` if there is nothing for the LLM to process.
        """
        # Build the activation event
        event = self._build_activation_event(npc_id)
        if event is None:
            # No pending events and no active task → deactivate
            self._active_task = False
            self._consecutive_action_cycles = 0
            return None

        # Run LLM cognition
        self._last_cognition_time = time.time()
        response = self.drive_npc(agent, npc_id, event)

        # ── Update task state ──────────────────────────────────────────
        if response and response.actions:
            # NPC used tools → task is ongoing, allow another cycle
            self._active_task = True
            self._consecutive_action_cycles += 1
            if self._consecutive_action_cycles >= MAX_CONSECUTIVE_ACTION_CYCLES:
                logger.warning(
                    "Task hit %d consecutive action cycles — forcing deactivation",
                    MAX_CONSECUTIVE_ACTION_CYCLES,
                )
                self._active_task = False
                self._consecutive_action_cycles = 0
        else:
            # No tool calls → task complete (or waiting for input)
            self._active_task = False
            self._consecutive_action_cycles = 0

        # Periodic reflection (piggybacks on existing LLM context)
        self._maybe_reflect(agent, npc_id)

        return response

    def activate_task(self, goal: str = "") -> None:
        """Mark the NPC as actively working on a task.

        This opens the cognition gate so the LLM can plan and execute.
        Call this when a player command arrives.

        Parameters
        ----------
        goal : str
            Human-readable task description (e.g. "收集10个橡木原木").
        """
        self._active_task = True
        self._consecutive_action_cycles = 0
        if goal:
            self._task_goal = goal
            self._current_goal = goal
        logger.info("Task activated: %s", goal or "(continued)")

    # ═══════════════════════════════════════════════════════════════════════
    # step() — backward-compatible combined tick
    # ═══════════════════════════════════════════════════════════════════════

    def step(self, agent, npc_id: str) -> AgentResponse | None:
        """One simulation tick: reflex layer → (conditional) cognition layer.

        Prefer using :meth:`reflex_tick` + :meth:`cognition_tick` separately
        in the main loop for finer control over timing.  This method exists
        for backward compatibility with code that expects a single ``step()``
        entry point.
        """
        # Layer 1: Reflexes (always)
        self.reflex_tick()

        # Layer 2: Cognition (conditional)
        if self.should_activate_cognition():
            return self.cognition_tick(agent, npc_id)

        return None

    def _create_danger_hook(self):
        """Create a pre-tool-check closure that interrupts LLM tasks on danger.

        This closure is injected into ``AgentContext.extra["_pre_tool_hook"]``
        and called by ``ToolDispatcher`` before EVERY tool execution during
        the ReAct loop.  If critical danger is detected the tool is skipped,
        an escape action runs, and an interrupt message is returned to the
        LLM so it knows why its task was interrupted.

        This is the mechanism that ensures the hardcoded reflex layer can
        interrupt LLM task execution mid-flight — without it, the NPC would
        be defenseless during long-running tool calls (e.g. walking across
        the map to ``go_to_coordinates``).
        """
        bridge = self._bridge  # capture for closure

        def _check(tool_call: dict) -> str | None:
            """Return interrupt message if danger detected, None if safe."""
            try:
                stats = bridge.call("get_stats")
            except Exception:
                return None

            if not stats.get("ok", True):
                return None

            # ── 1. On fire → stop and flee ───────────────────────────
            if stats.get("on_fire"):
                bridge.call("stop_moving")
                bridge.call("move_away", {"distance": 10})
                return "[危险中断] 着火了！已停止当前任务并远离10格。请确认安全后决定是否继续。"

            # ── 2. Drowning → surface ────────────────────────────────
            if stats.get("submerged"):
                bridge.call("stop_moving")
                bridge.call("go_to_surface")
                return "[危险中断] 溺水！已停止当前任务并上浮到水面。请确认安全后决定是否继续。"

            # ── 3. Critical HP → flee ───────────────────────────────
            health = stats.get("health", 20)
            if health <= 6:
                bridge.call("stop_moving")
                bridge.call("move_away", {"distance": 10})
                return f"[危险中断] 血量危急({health}/20)！已停止当前任务并远离。请确认安全后决定是否继续。"

            # ── 4. Lava/fire nearby (< 3 blocks) → flee ─────────────
            danger_blocks = stats.get("nearby_danger_blocks", [])
            close_dangers = [b for b in danger_blocks if b.get("distance", 99) <= 3]
            if close_dangers:
                bridge.call("stop_moving")
                bridge.call("move_away", {"distance": 10})
                names = {b.get("name", "?") for b in close_dangers}
                return f"[危险中断] 附近有危险方块({', '.join(names)})！已停止当前任务并远离。"

            # ── 5. High fall risk → stop and warn ────────────────────
            if stats.get("fall_risk", 0) >= 8:
                bridge.call("stop_moving")
                return "[危险中断] 前方有坠落风险(8+格)！已停止移动。请重新规划路线。"

            return None  # all clear

        return _check

    # ── WorldEngine contract ────────────────────────────────────────────

    def build_context(self, npc_id: str, event: str) -> AgentContext:
        """Assemble AgentContext with Minecraft perception, tools, and memory."""
        # Use cached perception if available, otherwise take a fresh snapshot
        if self._cached_perception_text:
            perception_text = self._cached_perception_text
        else:
            snapshot = self._perception.snapshot()
            perception_text = self._perception.render(snapshot)

        # Build memory context
        memory = self.memory_for(npc_id)
        memory_context = memory.build_context(event)

        # Build history text
        history_text = self._render_history(npc_id)

        # Build system prompt
        system_prompt = build_minecraft_system_prompt(
            name=self._profile.name,
            character_prompt=self._character_prompt,
            difficulty=self._difficulty,
            perception_summary=perception_text,
            current_goal=self._current_goal,
        )

        # Assemble tools (30 total — matches mindcraft library)
        tools = [
            # Movement (8)
            GoToCoordinatesTool(), GoToBlockTool(), StopMovingTool(),
            MoveAwayTool(), DigDownTool(), GoToSurfaceTool(),
            FollowPlayerTool(), GoToPlayerTool(),
            # Perception (3)
            CheckSurroundingsTool(), CheckInventoryTool(), CheckCraftableTool(),
            # Operation (7)
            BreakBlockTool(), CollectItemTool(), EquipTool(), ConsumeTool(),
            DiscardTool(), PlaceBlockTool(), PickupNearbyTool(),
            # Crafting (4)
            CraftTool(), GetCraftingPlanTool(), SmeltItemTool(), ClearFurnaceTool(),
            # Combat (3)
            AttackTool(), DefendTool(), EquipHighestAttackTool(),
            # Interaction (2)
            SendChatTool(), GiveToPlayerTool(),
            # Storage (3)
            ViewChestTool(), TakeFromChestTool(), PutInChestTool(),
        ]

        ctx = AgentContext(
            npc_id=npc_id,
            input_event=event,
            tools=tools,
            memory=memory,
            graph_id=AgentGraphID.ACTION_EXECUTOR_DEFAULT,
            route=AgentRoute.ACTION,
            character_prompt=system_prompt,
            world_rules="",
            situation="",
            history=history_text,
            extra={
                "_minecraft_bridge": self._bridge,
                "_minecraft_perception": self._perception,
                "difficulty": self._difficulty,
                "action_only": True,
                "disabled_tools": ["inner_monologue"],
                "_pre_tool_hook": self._create_danger_hook(),
            },
        )
        return ctx

    def handle_response(self, npc_id: str, response: AgentResponse) -> None:
        """Persist dialogue to history, memory updates, trigger compressor."""
        self._responses.append(response)

        if response.dialogue and self._history:
            self._history.append(speaker=npc_id, content=response.dialogue)

        memory = self.memory_for(npc_id)
        for update in response.memory_updates:
            try:
                memory.remember(
                    content=update.content,
                    category=update.type,
                    metadata=update.metadata,
                )
            except Exception:
                logger.warning("Failed to store memory update for %s", npc_id, exc_info=True)

        if self._compressor:
            try:
                self._compressor.maybe_fold(scene=f"minecraft:{self._difficulty}")
            except Exception:
                logger.warning("Compressor fold failed for %s", npc_id, exc_info=True)

    def execute_action(self, npc_id: str, action: ActionRequest) -> ActionResult:
        """Execute world actions — fallback path (tools handle most cases)."""
        return ActionResult(
            action_id=action.action_id,
            action_type=action.type,
            status="failed",
            reason="unsupported_action",
            observation=f"Minecraft engine does not support action '{action.type}' through execute_action. Use the tool interface.",
        )

    def memory_for(self, npc_id: str) -> MemoryInterface:
        if self._memory is None:
            from pathlib import Path
            persist_dir = Path("./data/minecraft/vector_store")
            persist_dir.mkdir(parents=True, exist_ok=True)
            import chromadb
            client = chromadb.PersistentClient(path=str(persist_dir))
            self._memory = DefaultMemoryInterface(npc_id=npc_id, chroma_client=client)
        return self._memory

    def history_for(self, npc_id: str) -> HistoryStore | None:
        if self._history is None:
            self._history = HistoryStore(
                npc_id=npc_id,
                path=self._history_dir / f"{npc_id}.jsonl",
            )
        return self._history

    def compressor_for(self, npc_id: str) -> Compressor | None:
        if self._llm is None:
            return None
        if self._compressor is None:
            history = self.history_for(npc_id)
            memory = self.memory_for(npc_id)
            if history is not None:
                self._compressor = Compressor(
                    history_store=history,
                    memory=memory,
                    llm=self._llm,
                )
        return self._compressor

    # ── Internals ───────────────────────────────────────────────────────

    def _poll_bridge_events(self) -> None:
        """Drain bridge events and convert to pending events.

        Event routing
        -------------
        - ``chat`` — always queues (player interaction → triggers LLM)
        - ``damage`` / ``death`` — informational only (reflexes handle the response);
          does NOT trigger LLM by itself
        - ``action_completed`` — dropped (the tool result already informed the LLM)
        """
        for ev in self._bridge.poll_events():
            # Notify external observers (e.g. monitor dashboard)
            if self._event_hook:
                try:
                    self._event_hook(ev)
                except Exception:
                    pass

            if ev.event_type == "chat":
                d = ev.data
                prefix = "私聊" if d.get("private") else "聊天"
                self._pending_events.append(
                    f"[{prefix}] {d.get('player', '?')}: {d.get('message', '')}"
                )
            elif ev.event_type == "damage":
                d = ev.data
                self._pending_events.append(
                    f"[事件] 受到伤害！血量降至 {d.get('health', '?')}/20。"
                )
            elif ev.event_type == "death":
                d = ev.data
                pos = d.get("position", [0, 0, 0])
                self._pending_events.append(
                    f"[事件] 你死亡了！原因: {d.get('reason', 'unknown')}，"
                    f"死亡位置: ({pos[0]}, {pos[1]}, {pos[2]})。"
                    f"所有物品已掉落。你将在重生点重生。"
                )
                mem = self.memory_for(self._npc_id)
                mem.remember(
                    content=f"死亡于{d.get('reason', 'unknown')}，位置{pos}",
                    category="reflection",
                    metadata={"type": "death", "position": pos},
                )
            # action_completed events are dropped — tools report results inline

    def _check_reflexes(self) -> ReflexResult:
        """Run reflex checks in priority order.  First triggered reflex wins."""
        snapshot = self._cached_snapshot or self._perception.snapshot()
        perception_text = self._cached_perception_text or self._perception.render(snapshot)
        inv = snapshot.get("inventory", {})

        for reflex in self._reflexes:
            result = reflex.run(perception_text, inv, self._bridge)
            if result.triggered:
                logger.info("Reflex triggered: %s", reflex.name)
                self._action_log.append({
                    "tick": time.time(),
                    "type": "reflex",
                    "reflex": reflex.name,
                    "event": result.event_text,
                })
                return result

        return ReflexResult(triggered=False)

    def _has_player_events(self) -> bool:
        """Check whether any pending event is player-related."""
        for event in self._pending_events:
            if any(tag in event for tag in _PLAYER_EVENT_TAGS):
                return True
        return False

    def _build_activation_event(self, npc_id: str) -> str | None:
        """Return the next event for NPC cognition.

        Priority:
        1. Pending events queue (player commands, chat, damage, etc.)
        2. Task continuation (when task is active but queue is empty)
        3. None (nothing to do)
        """
        if self._pending_events:
            return self._pending_events.pop(0)

        # Active task but no pending events → send continuation prompt
        if self._active_task:
            perception = self._cached_perception_text or "无感知数据"
            return (
                f"[任务继续] 当前目标：{self._current_goal}\n"
                f"环境数据：\n{perception}\n\n"
                f"继续执行任务。如果任务已完成，简洁报告结果。"
            )

        return None

    def _maybe_reflect(self, agent, npc_id: str) -> None:
        """Run reflection if enough time has passed."""
        now = time.time()
        if now - self._last_reflection_time < DEFAULT_REFLECTION_INTERVAL:
            return
        self._last_reflection_time = now

        try:
            ctx = self._build_reflection_context(npc_id)
            ctx.graph_id = AgentGraphID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE
            ctx.route = AgentRoute.REFLECTION
            response = agent.run(ctx)
            self.handle_response(npc_id, response)
        except Exception:
            logger.warning("Reflection failed for %s", npc_id, exc_info=True)

    def _build_reflection_context(self, npc_id: str) -> AgentContext:
        """Build a reflection-only AgentContext."""
        memory = self.memory_for(npc_id)
        history_text = self._render_history(npc_id)

        return AgentContext(
            npc_id=npc_id,
            input_event="回顾过去一段时间的经历，提炼重要的收获和经验。",
            memory=memory,
            graph_id=AgentGraphID.REFLECTION_EVIDENCE_TO_MEMORY_CANDIDATE,
            route=AgentRoute.REFLECTION,
            character_prompt=self._character_prompt,
            world_rules="",
            situation="",
            history=history_text,
            extra={"_minecraft_bridge": self._bridge},
        )

    def _render_history(self, npc_id: str) -> str:
        """Render recent rolling history as text lines."""
        history = self.history_for(npc_id)
        if history is None:
            return ""
        entries = history.read_last(MAX_HISTORY_TURNS)
        lines: list[str] = []
        for entry in entries:
            prefix = "[folded]" if entry.is_folded else ""
            lines.append(f"{prefix}[{entry.speaker}] {entry.content}")
        return "\n".join(lines)

    # ── Public helpers ──────────────────────────────────────────────────

    @property
    def npc_id(self) -> str:
        """The NPC's identifier."""
        return self._npc_id

    @property
    def current_goal(self) -> str:
        """The NPC's current task / goal."""
        return self._current_goal

    @property
    def active_task(self) -> bool:
        """Whether the NPC is actively working on a task (cognition gate open)."""
        return self._active_task

    @property
    def pending_event_count(self) -> int:
        """Number of events waiting for LLM processing."""
        return len(self._pending_events)

    def set_goal(self, goal: str) -> None:
        """Set the NPC's current long-term goal."""
        self._current_goal = goal

    def push_event(self, event_text: str) -> None:
        """Manually push an event for the next cognition cycle."""
        self._pending_events.append(event_text)

    @property
    def responses(self) -> list[AgentResponse]:
        return list(self._responses)

    @property
    def action_log(self) -> list[dict]:
        return list(self._action_log)

    @property
    def bridge(self) -> AbstractBridge:
        return self._bridge


# ── Convenience constructor for tests ───────────────────────────────────────

def create_test_engine(
    profile: NPCProfile | None = None,
    startup_state: dict | None = None,
    llm=None,
) -> MinecraftWorldEngine:
    """Create a MinecraftWorldEngine wired to a FakeBridge for testing."""
    bridge = FakeBridge(startup_state=startup_state)
    if profile is None:
        profile = _default_survivor_profile()
    return MinecraftWorldEngine(
        bridge=bridge,
        profile=profile,
        history_dir="./data/minecraft/test_history",
        llm=llm,
    )


def _default_survivor_profile() -> NPCProfile:
    from annie.world_engine.profile import Personality, Background, Goals
    return NPCProfile(
        name="Survivor",
        personality=Personality(traits=["cautious", "resourceful", "persistent"], values=["survival", "efficiency"]),
        background=Background(biography="A Minecraft survivor who knows the basics of crafting and combat."),
        goals=Goals(
            short_term=["collect wood", "craft stone tools", "find food"],
            long_term=["build a safe house", "explore the world"],
        ),
        relationships=[],
        memory_seed=["Minecraft 世界中，徒手获取原木是第一步。"],
        skills=[],
        tools=[],
    )
