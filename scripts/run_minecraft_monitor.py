"""Minecraft NPC Monitor — real-time observation & command dashboard.

Launches everything needed for live companion NPC play:
  1. Minecraft bridge (connects bot to your LAN world)
  2. First-person viewer (prismarine-viewer in browser at localhost:3000)
  3. Monitor dashboard (web UI at localhost:8080 with status, command input)
  4. Dual-layer NPC loop:
     - Layer 1: Hardcoded reflexes every 300 ms (danger avoidance, item pickup, etc.)
     - Layer 2: LLM cognition on-demand only (player commands, active tasks)

Usage
-----
    # 1. Open Minecraft → Open to LAN → note the port (e.g. 55916)
    # 2. Set your API key:
    #    $env:DEEPSEEK_API_KEY = "sk-..."
    # 3. Run:
    PYTHONPATH=src python scripts/run_minecraft_monitor.py --port 55916

What opens
----------
    - http://localhost:8080  → Monitor dashboard (status + command input)
    - http://localhost:3000  → First-person view (prismarine-viewer)

Controls
--------
    - Type commands in the dashboard input box and press Enter
    - Click 🎥 to toggle first-person overlay in dashboard
    - Press Ctrl+C in terminal to stop
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
import webbrowser
from pathlib import Path

# ── Logging setup ────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("mc_monitor")

# Enable info for our own logger
logger.setLevel(logging.INFO)

# ── Constants ────────────────────────────────────────────────────────────

DEFAULT_MONITOR_PORT = 8080
DEFAULT_VIEWER_PORT = 3000
REFRESH_INTERVAL = 0.3      # 300 ms — fast reflex loop
MIN_COGNITION_INTERVAL = 1.0  # seconds — rate-limit LLM calls


def update_monitor_state(state, engine):
    """Populate MonitorState fields from the engine's perception cache.

    Called after each reflex tick.  No extra bridge calls — reads from
    ``engine.cached_snapshot`` which is refreshed by the reflex layer.
    """
    state.last_update_time = time.time()

    # From engine
    state.current_goal = engine.current_goal
    state.action_log = engine.action_log[-20:]

    # From perception cache (populated by reflex_tick)
    snapshot = engine.cached_snapshot
    if snapshot:
        stats = snapshot.get("stats", {})
        if stats.get("ok"):
            state.position = stats.get("position", [0, 0, 0])
            state.health = stats.get("health", 20)
            state.hunger = stats.get("hunger", 20)
            state.biome = stats.get("biome", "unknown")
            state.time_of_day = stats.get("time", "unknown")
            state.weather = stats.get("weather", "Clear")

        inv_data = snapshot.get("inventory", {})
        if inv_data.get("ok"):
            state.inventory = {k: v for k, v in inv_data.get("items", {}).items() if v > 0}
            held = inv_data.get("held_item")
            state.held_item = held.get("name", "") if held else ""

        entities_data = snapshot.get("entities", {})
        if entities_data.get("ok"):
            ent_list = entities_data.get("entities", [])
            state.nearby_hostiles = [
                f"{e.get('name','?')}({e.get('distance',0):.0f}m)"
                for e in ent_list if e.get("is_hostile")
            ][:8]
            state.nearby_players = [
                f"{e.get('name','?')}({e.get('distance',0):.0f}m)"
                for e in ent_list if e.get("type") == "player"
            ][:4]
            state.nearby_items = [
                f"{e.get('name','?')}x{e.get('count',1)}"
                for e in ent_list if e.get("type") == "item"
            ][:8]


def run_monitor(
    host: str = "127.0.0.1",
    port: int = 55916,
    viewer_port: int = DEFAULT_VIEWER_PORT,
    monitor_port: int = DEFAULT_MONITOR_PORT,
    username: str = "ANNIE_Bot",
    no_browser: bool = False,
):
    """Start everything and run the NPC loop until interrupted."""
    from annie.minecraft.bot_connection import MinecraftBridge
    from annie.minecraft.engine import MinecraftWorldEngine
    from annie.minecraft.monitor import MonitorServer, MonitorState
    from annie.npc.agent import NPCAgent
    from annie.npc.llm import create_chat_model
    from annie.npc.config import load_model_config

    # Helper to safely print on GBK terminals
    def safe_print(msg: str) -> None:
        try:
            print(msg)
        except UnicodeEncodeError:
            print(msg.encode("gbk", errors="replace").decode("gbk", errors="replace"))

    # ── Banner ─────────────────────────────────────────────────────────

    safe_print("=" * 60)
    safe_print("  ANNIE Minecraft NPC Monitor (Dual-Layer)")
    safe_print("=" * 60)
    safe_print(f"  Minecraft:    {host}:{port}")
    safe_print(f"  Dashboard:    http://localhost:{monitor_port}")
    safe_print(f"  First-person: http://localhost:{viewer_port}")
    safe_print(f"  Bot name:     {username}")
    safe_print(f"  Reflex loop:  {int(REFRESH_INTERVAL * 1000)}ms (hardcoded, no LLM)")
    safe_print(f"  LLM trigger:  player commands & active tasks only")
    safe_print("=" * 60)
    safe_print("")

    # ── Start bridge ───────────────────────────────────────────────────

    safe_print("[1/4] Connecting to Minecraft...")
    bridge = MinecraftBridge(
        host=host,
        port=port,
        username=username,
        viewer_port=viewer_port,
    )

    try:
        bridge.start()
        stats = bridge.call("get_stats")
        pos = stats.get("position", [0, 0, 0])
        safe_print(f"      [OK] Connected! Position: ({pos[0]:.0f}, {pos[1]:.0f}, {pos[2]:.0f})")
        safe_print(f"      Health: {stats.get('health', '?')}/20  "
              f"Time: {stats.get('time', '?')}  "
              f"Biome: {stats.get('biome', '?')}")
    except Exception as e:
        safe_print(f"      [FAIL] Failed to connect: {e}")
        safe_print("      Make sure Minecraft is running and open to LAN.")
        return 1

    # ── Initialize monitor state ───────────────────────────────────────

    safe_print("[2/4] Starting monitor dashboard...")
    state = MonitorState(
        npc_id=username,
        running=True,
        bridge_connected=True,
        viewer_port=viewer_port,
        position=stats.get("position", [0, 0, 0]),
        health=stats.get("health", 20),
        hunger=stats.get("hunger", 20),
        biome=stats.get("biome", "unknown"),
        time_of_day=stats.get("time", "unknown"),
        weather=stats.get("weather", "Clear"),
    )
    state.add_event("bridge_connected", {"position": state.position, "health": state.health})

    server = MonitorServer(state, port=monitor_port)
    server.start()
    safe_print(f"      [OK] Dashboard: http://localhost:{monitor_port}")

    # ── Initialize LLM & Agent ─────────────────────────────────────────

    safe_print("[3/4] Loading AI model...")
    config_path = Path("config/model_config.yaml")
    if not config_path.exists():
        safe_print("      [FAIL] config/model_config.yaml not found!")
        safe_print("      Create one with your LLM configuration.")
        bridge.stop()
        server.stop()
        return 1

    try:
        model_config = load_model_config(str(config_path))
        llm = create_chat_model(model_config)
        agent = NPCAgent(llm=llm)
        safe_print(f"      [OK] Model loaded: {model_config.model}")
    except Exception as e:
        safe_print(f"      [FAIL] Failed to load model: {e}")
        bridge.stop()
        server.stop()
        return 1

    # ── Initialize engine ──────────────────────────────────────────────

    from annie.world_engine.profile import NPCProfile, Personality, Background, Goals

    profile = NPCProfile(
        name=username,
        personality=Personality(
            traits=["loyal", "helpful", "reliable", "observant"],
            values=["cooperation", "safety", "efficiency"],
        ),
        background=Background(
            biography=(
                "玩家的忠实 Minecraft 伙伴。不擅自行动，只执行玩家指令。"
                "熟悉所有合成配方和生存技巧。"
                "没有指令时保持待命，由反射层自动处理危险和收集物品。"
            ),
        ),
        goals=Goals(
            short_term=["等待玩家指令", "确保自身安全"],
            long_term=["协助玩家完成各种任务"],
        ),
        relationships=[],
        memory_seed=[
            "我是玩家的助手，不是自主决策者。",
            "没有指令时保持待命，由反射层自动处理危险。",
            "收到指令后快速准确地执行。",
        ],
        skills=[],
        tools=[],
    )

    # Create event hook that forwards bridge events to monitor state
    def on_bridge_event(ev):
        state.add_event(ev.event_type, ev.data)

    engine = MinecraftWorldEngine(
        bridge=bridge,
        profile=profile,
        history_dir="./data/minecraft/history",
        llm=llm,
        event_hook=on_bridge_event,
    )
    safe_print("      [OK] Engine initialized (dual-layer: reflexes + on-demand LLM)")

    # ── Open browser ───────────────────────────────────────────────────

    safe_print("[4/4] Opening browser...")

    dashboard_url = f"http://localhost:{monitor_port}"
    viewer_url = f"http://localhost:{viewer_port}"

    if not no_browser:
        try:
            webbrowser.open(dashboard_url)
            safe_print(f"      [OK] Dashboard opened: {dashboard_url}")
            time.sleep(0.8)
            webbrowser.open(viewer_url)
            safe_print(f"      [OK] First-person view opened: {viewer_url}")
        except Exception:
            safe_print(f"      [WARN] Could not open browser automatically.")
            safe_print(f"      Open {dashboard_url} and {viewer_url} manually.")

    safe_print("")
    safe_print("=" * 60)
    safe_print("  [RUNNING] NPC companion active!")
    safe_print(f"  Dashboard: {dashboard_url}")
    safe_print(f"  Viewer:    {viewer_url}")
    safe_print("  Layer 1: Reflexes run every 300ms (no LLM)")
    safe_print("  Layer 2: LLM triggered by player commands only")
    safe_print("  Type commands in the dashboard to instruct the NPC.")
    safe_print("  Press Ctrl+C to stop.")
    safe_print("=" * 60)
    safe_print("")

    # ═══════════════════════════════════════════════════════════════════════
    # Main Loop — Dual-Layer Architecture
    # ═══════════════════════════════════════════════════════════════════════
    #
    # Layer 1 (300 ms): Hardcoded reflexes — danger avoidance, item pickup,
    #   stuck detection.  Runs every tick.  No LLM involvement.
    #
    # Layer 2 (on-demand): LLM cognition — triggered ONLY by player commands
    #   or active task execution.  Rate-limited to once per second.
    # ═══════════════════════════════════════════════════════════════════════

    tick = 0
    last_cognition_tick = 0
    shutdown_requested = False

    def on_sigint(sig, frame):
        nonlocal shutdown_requested
        safe_print("\n[WARN] Ctrl+C - shutting down...")
        shutdown_requested = True

    original_sigint = signal.signal(signal.SIGINT, on_sigint)

    try:
        while not shutdown_requested:
            tick += 1
            loop_start = time.time()

            # ── Process user commands from dashboard ──────────────────
            commands = state.pop_commands()
            for cmd in commands:
                state.add_event("command", {"message": cmd})
                engine.push_event(f"[玩家指令] {cmd}")
                engine.activate_task(goal=cmd)
                logger.info("Command received: %s", cmd)

            # ── Layer 1: Hardcoded Reflex Tick (always, no LLM) ───────
            try:
                reflex_result = engine.reflex_tick()
            except Exception as e:
                state.last_error = str(e)[:200]
                state.add_event("error", {"message": str(e)[:200]})
                logger.error("Reflex tick %d error: %s", tick, e)

            # Update monitor state from perception cache (no bridge calls)
            try:
                update_monitor_state(state, engine)
            except Exception as e:
                logger.debug("Monitor update error: %s", e)

            state.tick_count = tick
            state.running = True
            state.bridge_connected = True

            # Log reflex triggers
            if reflex_result:
                state.add_event("reflex", {
                    "name": reflex_result.reflex_name,
                    "event": reflex_result.event_text[:200],
                })

            # ── Layer 2: LLM Cognition (conditional, rate-limited) ────
            if engine.should_activate_cognition():
                t0 = time.time()
                try:
                    response = engine.cognition_tick(agent, engine.npc_id)
                    dt = time.time() - t0
                    last_cognition_tick = tick
                    state.last_tick_duration = dt

                    if response:
                        acts = [a.type for a in response.actions] if response.actions else []
                        thought_preview = (response.inner_thought or "")[:80]
                        dialogue_preview = (response.dialogue or "")[:80]
                        logger.info(
                            "Tick %d LLM (%.1fs): acts=%s thought=%s",
                            tick, dt, acts, thought_preview,
                        )
                        if dialogue_preview:
                            logger.info("  Said: %s", dialogue_preview)

                        # Update state from response
                        state.last_dialogue = (response.dialogue or "")[:500]
                        state.last_thought = (response.inner_thought or "")[:500]
                        state.last_actions = acts
                        state.last_reflection = (response.reflection or "")[:500]

                        for a in (response.actions or []):
                            state.add_event("action", {
                                "type": a.type,
                                "action_id": a.action_id,
                            })
                    else:
                        logger.info("Tick %d LLM: no response (task complete?)", tick)
                        state.last_dialogue = ""
                        state.last_thought = ""
                        state.last_actions = []
                        state.last_reflection = ""

                except Exception as e:
                    state.last_error = str(e)[:200]
                    state.add_event("error", {"message": str(e)[:200]})
                    logger.error("Cognition tick %d error: %s", tick, e)

            # ── Status logging (every ~30 ticks / ~10 seconds) ────────
            if tick % 30 == 0:
                status_parts = [f"Tick {tick}"]
                status_parts.append(f"pos=({state.position[0]:.0f},{state.position[1]:.0f},{state.position[2]:.0f})")
                status_parts.append(f"HP={state.health:.0f}")
                status_parts.append(f"events={engine.pending_event_count}")
                status_parts.append(f"task={'active' if engine.active_task else 'idle'}")
                status_parts.append(f"last_LLM={tick - last_cognition_tick}t ago" if last_cognition_tick else "no LLM yet")
                logger.info(" | ".join(status_parts))

            # ── Maintain 300ms cadence ────────────────────────────────
            elapsed = time.time() - loop_start
            if elapsed < REFRESH_INTERVAL:
                time.sleep(REFRESH_INTERVAL - elapsed)

    except KeyboardInterrupt:
        pass
    finally:
        signal.signal(signal.SIGINT, original_sigint)

    # ── Shutdown ───────────────────────────────────────────────────────

    safe_print("\nShutting down...")
    state.running = False
    state.bridge_connected = False
    state.add_event("shutdown", {"tick_count": tick})

    bridge.stop()
    server.stop()

    safe_print("[OK] Monitor stopped.")
    safe_print(f"[OK] Total ticks: {tick} (reflex layer)")
    safe_print(f"[OK] LLM calls: ~{sum(1 for e in state.events if e.get('type') == 'action')} tool actions")
    return 0


# ── Entry point ──────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="ANNIE Minecraft NPC Monitor — dual-layer companion NPC",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python scripts/run_minecraft_monitor.py --port 55916
  python scripts/run_minecraft_monitor.py --port 55916 --no-browser
  python scripts/run_minecraft_monitor.py --host 192.168.1.5 --port 55916 \\
      --monitor-port 9090 --viewer-port 4000

Architecture:
  Layer 1 (300ms): Hardcoded reflexes — danger, items, stuck. No LLM.
  Layer 2 (on-demand): LLM only for player commands & active tasks.
        """,
    )
    parser.add_argument("--host", default="127.0.0.1", help="Minecraft server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=55916, help="Minecraft LAN port (default: 55916)")
    parser.add_argument("--viewer-port", type=int, default=DEFAULT_VIEWER_PORT,
                        help=f"First-person viewer HTTP port (default: {DEFAULT_VIEWER_PORT})")
    parser.add_argument("--monitor-port", type=int, default=DEFAULT_MONITOR_PORT,
                        help=f"Monitor dashboard HTTP port (default: {DEFAULT_MONITOR_PORT})")
    parser.add_argument("--username", default="ANNIE_Bot", help="Bot display name (default: ANNIE_Bot)")
    parser.add_argument("--no-browser", action="store_true", help="Don't auto-open browser windows")
    args = parser.parse_args()

    return run_monitor(
        host=args.host,
        port=args.port,
        viewer_port=args.viewer_port,
        monitor_port=args.monitor_port,
        username=args.username,
        no_browser=args.no_browser,
    )


if __name__ == "__main__":
    sys.exit(main())
