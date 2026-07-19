"""Minecraft survival task — full test run with first-person screenshots.

Usage
-----
    # Start Minecraft → Open to LAN → note port
    $env:DEEPSEEK_API_KEY = "sk-..."
    PYTHONPATH=src python scripts/run_minecraft_task.py --port 55916

What it does
------------
1. Connects a bot to your Minecraft LAN world
2. Opens a first-person browser viewer at http://localhost:3000
3. Runs 6 cognition ticks (survival: wood→planks→sticks→tools)
4. Captures a screenshot at each step
5. Writes a timeline report + all screenshots to data/minecraft/recordings/

Output
------
    data/minecraft/recordings/<timestamp>/
    ├── timeline.txt          # step-by-step log
    ├── step_01_connect.png   # bot spawns
    ├── step_02_perceive.png  # first perception
    ├── step_03_act.png       # first action
    ├── ...
    └── index.html            # flip through screenshots
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("mc_task")

# ── Screenshot helper ──────────────────────────────────────────────────────


def capture_screen(bbox: tuple | None = None):
    """Capture a region of the screen. Requires Pillow."""
    try:
        from PIL import ImageGrab
        return ImageGrab.grab(bbox=bbox)
    except ImportError:
        return None


def capture_viewer(port: int = 3000):
    """Try to capture the prismarine-viewer browser window.

    Falls back to full-screen capture since we can't know exact browser position.
    The user should arrange the browser window to be visible.
    """
    # Try to capture a reasonable region — top-left quadrant of primary monitor
    # User should position the browser window in the upper-left area
    return capture_screen(bbox=(0, 0, 960, 600))


# ── Main test ──────────────────────────────────────────────────────────────


def run_task(host: str, port: int, viewer_port: int, output_dir: Path):
    """Run the full survival task: 6 cognition ticks with screenshots."""

    from annie.minecraft.bot_connection import MinecraftBridge
    from annie.minecraft.engine import MinecraftWorldEngine, _default_survivor_profile
    from annie.npc.agent import NPCAgent
    from annie.npc.llm import create_chat_model
    from annie.npc.config import load_model_config

    output_dir.mkdir(parents=True, exist_ok=True)
    timeline_lines: list[str] = []
    screenshots: list[Path] = []

    def log_step(msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line)
        timeline_lines.append(line)

    def snap(label: str) -> Path | None:
        """Capture a screenshot and save it."""
        img = capture_viewer(viewer_port)
        if img is None:
            return None
        fpath = output_dir / f"{label}.png"
        img.save(str(fpath))
        screenshots.append(fpath)
        log_step(f"  [screenshot] {fpath.name}")
        return fpath

    # ── Setup ──────────────────────────────────────────────────────────

    log_step("Starting Minecraft bridge + viewer...")
    bridge = MinecraftBridge(
        host=host, port=port,
        username="ANNIE_TaskBot",
        viewer_port=viewer_port,
    )

    try:
        bridge.start()
        stats = bridge.call("get_stats")
        log_step(f"Bot connected at {stats['position']}, "
                 f"time={stats.get('time','?')}, health={stats['health']}/20")
        log_step(f"Open http://localhost:{viewer_port} for first-person view")
        log_step("Position the browser window in the upper-left of your screen")
        time.sleep(2)  # let viewer render
        snap("step_01_connect")

        # ── Load LLM ───────────────────────────────────────────────────

        config_path = Path("config/model_config.yaml")
        if not config_path.exists():
            log_step("ERROR: config/model_config.yaml not found")
            return
        model_config = load_model_config(str(config_path))
        llm = create_chat_model(model_config)
        agent = NPCAgent(llm=llm)

        engine = MinecraftWorldEngine(
            bridge=bridge,
            profile=_default_survivor_profile(),
            history_dir=str(output_dir.parent / "history"),
            llm=llm,
        )

        # ── Define the task sequence ───────────────────────────────────

        goals = [
            "环顾四周，了解你所在的环境。你看到了什么？",
            "收集附近可用的资源。优先收集木头（原木）。",
            "检查你的物品栏。如果有原木，合成为木板。",
            "用木板合成木棍，然后合成一个工作台。",
            "用工作台合成一把木镐。如果没有足够的材料，继续收集。",
            "总结你目前的进度。你接下来打算做什么？",
        ]

        # ── Run 6 ticks ────────────────────────────────────────────────

        for i, goal in enumerate(goals):
            log_step(f"--- Tick {i+1}/6 ---")
            log_step(f"Goal: {goal}")
            engine.set_goal(goal)

            snap(f"step_{i+2:02d}a_before")

            start = time.time()
            response = engine.step(agent, engine._npc_id)
            elapsed = time.time() - start

            if response:
                dialogue = response.dialogue[:200]
                thought = response.inner_thought[:200] if response.inner_thought else ""
                acts = [a.type for a in response.actions]
                log_step(f"  Dialogue: {dialogue}")
                if thought:
                    log_step(f"  Thought: {thought}")
                log_step(f"  Actions: {acts if acts else 'none'}")
                log_step(f"  Took: {elapsed:.1f}s")
            else:
                log_step(f"  Reflex-only (took {elapsed:.1f}s)")

            time.sleep(1)  # let viewer update
            snap(f"step_{i+2:02d}b_after")

        # ── Final state ────────────────────────────────────────────────

        stats = bridge.call("get_stats")
        inv = bridge.call("get_inventory")
        items = {k: v for k, v in inv.get("items", {}).items() if v > 0}
        log_step(f"--- Final ---")
        log_step(f"Position: {stats['position']}")
        log_step(f"Health: {stats['health']}/20  Hunger: {stats['hunger']}/20")
        log_step(f"Inventory: {json.dumps(items) if items else 'empty'}")
        if inv.get("held_item"):
            log_step(f"Held: {inv['held_item']}")
        snap("step_08_final")

        # ── Write outputs ──────────────────────────────────────────────

        # Timeline
        (output_dir / "timeline.txt").write_text("\n".join(timeline_lines), encoding="utf-8")
        log_step(f"Timeline: {output_dir / 'timeline.txt'}")

        # HTML viewer
        html = _build_html_viewer(screenshots, timeline_lines)
        (output_dir / "index.html").write_text(html, encoding="utf-8")
        log_step(f"Viewer:   {output_dir / 'index.html'}")
        log_step(f"Screenshots: {len(screenshots)} images in {output_dir}")

    finally:
        bridge.stop()
        log_step("Done.")


def _build_html_viewer(screenshots: list[Path], timeline: list[str]) -> str:
    """Generate a simple HTML page to flip through screenshots."""
    img_tags = "\n".join(
        f'    <div class="step">'
        f'<h3>Step {i+1}</h3>'
        f'<img src="{p.name}" style="max-width:100%;border:2px solid #333">'
        f'</div>'
        for i, p in enumerate(screenshots)
    )
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>ANNIE Minecraft Task</title>
<style>
  body {{ font-family: monospace; background: #111; color: #0f0; max-width: 1000px; margin: auto; padding: 20px; }}
  h1 {{ color: #fff; }}
  .step {{ margin: 20px 0; }}
  .step img {{ display: block; margin: 10px 0; }}
  .timeline {{ background: #1a1a2e; padding: 15px; white-space: pre-wrap; font-size: 13px; margin: 20px 0; }}
</style></head><body>
<h1>ANNIE Minecraft Survival Task</h1>
<div class="timeline">{chr(10).join(timeline)}</div>
<h2>Screenshots</h2>
{img_tags}
</body></html>"""


# ── Entry point ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Minecraft survival task test")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=55916)
    parser.add_argument("--viewer-port", type=int, default=3000)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()

    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = Path(args.output or f"data/minecraft/recordings/{ts}")

    run_task(
        host=args.host,
        port=args.port,
        viewer_port=args.viewer_port,
        output_dir=output_dir,
    )


if __name__ == "__main__":
    main()
