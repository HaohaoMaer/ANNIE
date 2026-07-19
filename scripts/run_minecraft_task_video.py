"""Minecraft survival task — records NPC first-person view via headless rendering.

Usage
-----
    # Start Minecraft → Open to LAN → note port
    $env:DEEPSEEK_API_KEY = "sk-..."
    PYTHONPATH=src python scripts/run_minecraft_task_video.py --port 55916

How it works
------------
1. Starts FrameReceiver (TCP server on port 8089)
2. Connects bot to Minecraft with headless viewer streaming to port 8089
3. Headless viewer renders NPC first-person perspective server-side and
   sends JPEG frames over TCP (just like mindcraft's camera.js)
4. FrameReceiver decodes frames and writes them to MP4 with OpenCV
5. Runs NPC through: chop tree → planks → crafting table → wooden pickaxe

This produces a clean video of exactly what the NPC sees — no desktop, no browser.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger("mc_video_task")

RECORD_PORT = 8089  # TCP port for headless frame streaming


def run_task(host: str, port: int, viewer_port: int, output_dir: Path):
    from annie.minecraft.bot_connection import MinecraftBridge
    from annie.minecraft.engine import MinecraftWorldEngine
    from annie.minecraft.frame_receiver import FrameReceiver
    from annie.npc.agent import NPCAgent
    from annie.npc.llm import create_chat_model
    from annie.npc.config import load_model_config

    output_dir.mkdir(parents=True, exist_ok=True)
    video_path = output_dir / "recording.mp4"
    timeline_lines: list[str] = []

    def log_step(msg: str) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        line = f"[{ts}] {msg}"
        print(line.encode("gbk", errors="replace").decode("gbk", errors="replace"), flush=True)
        timeline_lines.append(line)

    log_step("=" * 60)
    log_step("ANNIE Minecraft NPC — Server-Side First-Person Recording")
    log_step("=" * 60)
    log_step(f"Output: {output_dir}")

    # ── 1. Start frame receiver ─────────────────────────────────────────

    log_step("Starting frame receiver on port %d..." % RECORD_PORT)
    receiver = FrameReceiver(video_path, port=RECORD_PORT, fps=20.0)
    receiver.start()

    bridge = None
    engine = None

    try:
        # ── 2. Connect bridge with headless viewer streaming ───────────

        log_step("Connecting to Minecraft with headless recording...")
        bridge = MinecraftBridge(
            host=host,
            port=port,
            username="ANNIE_TaskBot",
            viewer_port=viewer_port,       # browser viewer (optional)
            record_port=RECORD_PORT,       # headless → TCP stream
        )

        try:
            bridge.start()
            stats = bridge.call("get_stats")
            pos = stats.get("position", [0, 0, 0])
            log_step(f"Bot connected! Pos=({pos[0]:.0f},{pos[1]:.0f},{pos[2]:.0f}) "
                     f"HP={stats.get('health')}/20")

            # Wait for headless viewer to connect and send first frame
            log_step("Waiting for headless viewer to connect...")
            if receiver.wait_ready(timeout=20.0):
                log_step("Headless viewer connected! Recording NPC first-person view...")
            else:
                log_step("WARNING: Headless viewer didn't connect within timeout. "
                         "Video may be empty.")
            time.sleep(1)

            # ── 3. Load LLM ───────────────────────────────────────────

            model_config = load_model_config(str(Path("config/model_config.yaml")))
            llm = create_chat_model(model_config)
            agent = NPCAgent(llm=llm)

            from annie.world_engine.profile import NPCProfile, Personality, Background, Goals

            profile = NPCProfile(
                name="Survivor",
                personality=Personality(
                    traits=["resourceful", "determined", "methodical"],
                    values=["survival", "efficiency"]),
                background=Background(
                    biography="Minecraft生存专家。1原木=4木板，4木板=1工作台，3木板+2木棍=1木镐(需工作台)。"),
                goals=Goals(
                    short_term=["收集原木", "合成工作台", "合成本镐"],
                    long_term=["建造基地"]),
                relationships=[],
                memory_seed=["生存流程:徒手取木→合木板→合工作台→放置→合木镐"],
                skills=[], tools=[])

            engine = MinecraftWorldEngine(
                bridge=bridge, profile=profile,
                history_dir=str(output_dir.parent / "history"), llm=llm)

            # ── 4. Run task sequence ──────────────────────────────────

            tasks = [
                ("PERCEPTION",
                 "环顾四周，仔细观察环境。你看到了什么？确认最近的树木位置。"),
                ("COLLECT_WOOD",
                 "走到最近的树旁，用 break_block 或 collect_item 收集至少4个原木。"
                 "用 go_to_block('oak_log') 走到树旁。检查物品栏确认。"),
                ("CRAFT_PLANKS",
                 "合成木板：craft(item_name='oak_planks', count=16)。全部原木都合成。检查物品栏。"),
                ("CRAFT_TABLE",
                 "合成工作台：craft(item_name='crafting_table', count=1)。4木板=1工作台。"),
                ("PLACE_AND_PICKAXE",
                 "1) equip('crafting_table')拿手中 "
                 "2) check_surroundings获取脚下坐标 "
                 "3) place_block放工作台到面前地面 "
                 "4) craft(item_name='wooden_pickaxe', count=1)在工作台上合成本镐！"
                 "缺木棍先craft(item_name='stick', count=4)。"),
                ("VERIFY",
                 "检查物品栏确认木镐已到手。总结流程。没完成就继续！"),
            ]

            for i, (phase, goal) in enumerate(tasks):
                print()
                log_step(f"{'='*50}")
                log_step(f"PHASE {i+1}/{len(tasks)}: {phase}")
                log_step(f"{'='*50}")
                engine.set_goal(goal)
                max_t = 4 if phase in ("COLLECT_WOOD", "PLACE_AND_PICKAXE") else 3

                for tick in range(max_t):
                    print(f"\n  --- Tick {tick+1}/{max_t} ---")
                    t0 = time.time()
                    try:
                        resp = engine.step(agent, engine._npc_id)
                        dt = time.time() - t0
                        if resp:
                            d = (resp.dialogue or "")[:200]
                            th = (resp.inner_thought or "")[:150]
                            acts = [a.type for a in resp.actions] if resp.actions else []
                            log_step(f"  [{phase}] T{tick+1}: {dt:.1f}s")
                            if d: log_step(f"    Said: {d}")
                            if th: log_step(f"    Thought: {th}")
                            if acts: log_step(f"    Acts: {acts}")
                        else:
                            log_step(f"  [{phase}] T{tick+1}: reflex ({time.time()-t0:.1f}s)")
                    except Exception as e:
                        log_step(f"  [{phase}] T{tick+1} ERR: {e}")

                    time.sleep(0.6)
                    try:
                        inv = bridge.call("get_inventory")
                        items = {k: v for k, v in inv.get("items", {}).items() if v > 0}
                        h = inv.get("held_item")
                        hs = f" | Held: {h['name']}" if h else ""
                        if items: log_step(f"    Inv: {items}{hs}")
                        if "wooden_pickaxe" in items:
                            log_step("    >>> WOODEN PICKAXE IN INVENTORY! <<<")
                            break
                    except Exception: pass
                time.sleep(1.0)

            # ── 5. Final state ────────────────────────────────────────

            print()
            log_step("=" * 50 + "\nFINAL STATE\n" + "=" * 50)
            stats = bridge.call("get_stats")
            inv = bridge.call("get_inventory")
            items = {k: v for k, v in inv.get("items", {}).items() if v > 0}
            held = inv.get("held_item")

            log_step(f"Pos: {stats.get('position')}  HP: {stats.get('health')}/20")
            log_step(f"Inv: {json.dumps(items, ensure_ascii=False)}")
            if held: log_step(f"Held: {held}")

            has_pick = "wooden_pickaxe" in items
            has_table = "crafting_table" in items
            log_step(f"Result: Pickaxe={has_pick}, Table={has_table}")

            (output_dir / "timeline.txt").write_text(
                "\n".join(timeline_lines), encoding="utf-8")
            (output_dir / "final_state.json").write_text(
                json.dumps({"inventory": items, "held_item": held,
                            "has_wooden_pickaxe": has_pick, "has_crafting_table": has_table},
                           indent=2, ensure_ascii=False), encoding="utf-8")

            if has_pick:
                log_step("\n*** SUCCESS! Tree->Planks->Table->Pickaxe! ***")
            else:
                log_step("\n*** INCOMPLETE. Check video for details. ***")

        finally:
            if engine is not None and engine._bridge is not None:
                try: engine._bridge.stop()
                except Exception: pass

    finally:
        # ── 6. Stop recording ────────────────────────────────────────

        # Give a moment for final frames to flush
        time.sleep(1)
        receiver.stop()

        if video_path.exists():
            size_mb = video_path.stat().st_size / 1024 / 1024
            log_step(f"\nVideo: {video_path}")
            log_step(f"Frames: {receiver.frame_count}  Duration: {receiver.elapsed:.0f}s")
            log_step(f"Size: {size_mb:.1f} MB")

            if size_mb < 0.1:
                log_step("WARNING: Video file is very small. The headless viewer "
                         "may not have connected. Check node-canvas-webgl/gl packages.")
        else:
            log_step("\nWARNING: No video generated!")

        log_step("Done.")


def main():
    parser = argparse.ArgumentParser(description="Minecraft NPC — headless first-person recording")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=55916)
    parser.add_argument("--viewer-port", type=int, default=3000)
    parser.add_argument("--output", type=str, default=None)
    args = parser.parse_args()
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    output_dir = Path(args.output or f"data/minecraft/recordings/{ts}")
    run_task(host=args.host, port=args.port, viewer_port=args.viewer_port, output_dir=output_dir)


if __name__ == "__main__":
    main()
