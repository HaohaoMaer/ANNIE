"""Minecraft NPC task — headless first-person recording via separate camera bot.

Launches two Node.js processes:
1. Main bridge bot — handles NPC logic (fast, no rendering overhead)
2. Camera bot — separate Minecraft connection, renders first-person view,
   streams frames via TCP to Python FrameReceiver → MP4 video

This architecture mirrors mindcraft's Camera approach but uses a separate
connection to avoid event-loop blocking.
"""
import time, json, subprocess, signal
from pathlib import Path
from datetime import datetime

output_dir = Path("data/minecraft/recordings/full_task")
output_dir.mkdir(parents=True, exist_ok=True)
video_path = output_dir / "recording.mp4"
timeline = []
RECORD_PORT = 8089

def log(msg):
    ts = datetime.now().strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line.encode("gbk", errors="replace").decode("gbk", errors="replace"), flush=True)
    timeline.append(line)

log("=== NPC Task with Camera Bot Recording ===")
log(f"Output: {output_dir}")

# ── 1. Start FrameReceiver ──────────────────────────────────────────────
from annie.minecraft.frame_receiver import FrameReceiver

recv = FrameReceiver(video_path, port=RECORD_PORT, fps=8)
recv.start()
log(f"FrameReceiver listening on port {RECORD_PORT}")

# ── 2. Start main bridge bot ────────────────────────────────────────────
from annie.minecraft.bot_connection import MinecraftBridge
from annie.minecraft.engine import MinecraftWorldEngine
from annie.npc.agent import NPCAgent
from annie.npc.llm import create_chat_model
from annie.npc.config import load_model_config
from annie.world_engine.profile import NPCProfile, Personality, Background, Goals

bridge = MinecraftBridge(host="127.0.0.1", port=55916, username="ANNIE_Bot")
bridge.start()
stats = bridge.call("get_stats")
pos = stats["position"]
log(f"Main bot at ({pos[0]:.0f},{pos[1]:.0f},{pos[2]:.0f})")

# ── 3. Start camera bot (separate Node.js process) ─────────────────────
_cam_stderr = []
camera_js = Path("src/annie/minecraft/camera_bot.js").resolve()
camera_proc = subprocess.Popen(
    ["node", str(camera_js),
     "--host", "127.0.0.1", "--port", "55916",
     "--target", "ANNIE_Bot", "--record-port", str(RECORD_PORT),
     "--fps", "8", "--width", "854", "--height", "480", "--quality", "92"],
    stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8"
)
log(f"Camera bot started (pid={camera_proc.pid})")

# Read camera stderr in background
import threading as _threading
_cam_stderr = []
def _read_cam_err():
    for line in camera_proc.stderr:
        _cam_stderr.append(line.rstrip())
_cam_thread = _threading.Thread(target=_read_cam_err, daemon=True)
_cam_thread.start()

# Wait for camera bot to connect
if recv.wait_ready(30):
    log("Camera bot connected! Recording NPC first-person view...")
else:
    log("WARNING: Camera bot did not connect within 30s")

# ── 4. Load LLM ────────────────────────────────────────────────────────
config = load_model_config("config/model_config.yaml")
llm = create_chat_model(config)
agent = NPCAgent(llm=llm)

profile = NPCProfile(
    name="Steve", personality=Personality(traits=["resourceful","determined"], values=["survival"]),
    background=Background(biography="Minecraft expert. 1 log=4 planks. 4 planks=1 crafting_table. 3 planks+2 sticks=1 wooden_pickaxe (needs crafting table)."),
    goals=Goals(short_term=["collect logs","craft table","craft pickaxe"], long_term=["build"]),
    relationships=[], memory_seed=[], skills=[], tools=[])

engine = MinecraftWorldEngine(bridge=bridge, profile=profile,
    history_dir=str(output_dir.parent/"history"), llm=llm)

# ── 5. Discard all existing items first (fresh start) ──────────────────
inv = bridge.call("get_inventory")
existing = {k: v for k, v in inv.get("items", {}).items() if v > 0}
if existing:
    log(f"Discarding existing items: {existing}")
    for item_name, count in existing.items():
        try:
            bridge.call("discard", {"item_name": item_name, "count": count})
            log(f"  Discarded {count}x {item_name}")
        except Exception as e:
            log(f"  Failed to discard {item_name}: {e}")
    time.sleep(1)

# Verify empty
inv = bridge.call("get_inventory")
remaining = {k: v for k, v in inv.get("items", {}).items() if v > 0}
log(f"Starting inventory: {remaining if remaining else 'EMPTY'}")

# ── 6. Task sequence (fresh start!) ────────────────────────────────────
tasks = [
    ("COLLECT",
     "Find a tree. Walk to it using go_to_block('oak_log'). "
     "Mine the wood using break_block to collect at least 3 oak_log. "
     "Check inventory after each action."),
    ("CRAFT_PLANKS_AND_TABLE",
     "Craft planks from ALL logs: craft(item_name='oak_planks'). "
     "Then craft a crafting table: craft(item_name='crafting_table'). "
     "Check inventory. Do NOT skip these steps!"),
    ("PLACE_AND_PICKAXE",
     "STEP 1: equip('crafting_table'). "
     "STEP 2: check_surroundings to find ground coordinates. "
     "STEP 3: place_block with x/y/z of ground in front of you, block_type='crafting_table'. "
     "STEP 4: craft(item_name='stick') first. "
     "STEP 5: craft(item_name='wooden_pickaxe'). "
     "Check inventory after each step!"),
]

for i, (phase, goal) in enumerate(tasks):
    print()
    log(f"{'='*40}\nPHASE {i+1}/{len(tasks)}: {phase}\n{'='*40}")
    engine.set_goal(goal)

    for tick in range(3):
        t0 = time.time()
        try:
            resp = engine.step(agent, engine._npc_id)
            dt = time.time() - t0
            if resp:
                acts = [a.type for a in resp.actions] if resp.actions else []
                log(f"  T{tick+1}: {dt:.0f}s {acts}")
                if resp.dialogue:
                    log(f"    Said: {(resp.dialogue or '')[:200]}")
            else:
                log(f"  T{tick+1}: reflex ({time.time()-t0:.0f}s)")
        except Exception as e:
            log(f"  T{tick+1}: ERR {e}")

        time.sleep(0.5)
        try:
            inv = bridge.call("get_inventory")
            items = {k: v for k, v in inv.get("items", {}).items() if v > 0}
            h = inv.get("held_item")
            hs = f" Held:{h['name']}" if h else ""
            log(f"    Inv: {items}{hs}")
            if "wooden_pickaxe" in items:
                log("    >>> PICKAXE DONE! <<<")
                break
        except Exception:
            pass

# ── 6. Final ───────────────────────────────────────────────────────────
print()
log("=" * 40 + "\nFINAL\n" + "=" * 40)
stats = bridge.call("get_stats")
inv = bridge.call("get_inventory")
items = {k: v for k, v in inv.get("items", {}).items() if v > 0}
has_pick = "wooden_pickaxe" in items
log(f"Inv: {items}")
log(f"Wooden pickaxe: {has_pick}")

# Record a few more seconds of final state
time.sleep(3)

# ── 7. Cleanup ─────────────────────────────────────────────────────────
# Stop main bot first (camera bot will fall back to last known position)
bridge.stop()
log("Main bot stopped")

# Let camera bot record a few more frames of the final scene
time.sleep(2)

# Gracefully stop camera bot
if camera_proc:
    camera_proc.send_signal(signal.SIGTERM)
    try:
        camera_proc.wait(timeout=8)
    except subprocess.TimeoutExpired:
        camera_proc.kill()
    log(f"Camera bot stopped (rc={camera_proc.returncode})")
    if _cam_stderr:
        # Show only camera-specific log lines (filter out THREE.js geometry dumps)
        cam_lines = [l for l in _cam_stderr if '[camera]' in l]
        log(f"Camera log ({len(cam_lines)} lines):")
        for l in cam_lines[:20]:
            log(f"  {l}")

time.sleep(0.5)
recv.stop()
log(f"FrameReceiver stopped ({recv.frame_count} frames)")

# ── 8. Save ────────────────────────────────────────────────────────────
(output_dir / "timeline.txt").write_text("\n".join(timeline), encoding="utf-8")
(output_dir / "final_state.json").write_text(
    json.dumps({"inventory": items, "has_pickaxe": has_pick}, indent=2), encoding="utf-8")

if video_path.exists():
    import cv2
    cap = cv2.VideoCapture(str(video_path))
    frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    fps = cap.get(cv2.CAP_PROP_FPS)
    w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    size_mb = video_path.stat().st_size / 1024 / 1024
    cap.release()
    log(f"\nVideo: {video_path}")
    log(f"  {w}x{h}, {fps}fps, {frames} frames, {size_mb:.1f}MB")
else:
    log("\nWARNING: No video generated!")

if has_pick:
    log("\n*** SUCCESS! Tree -> Planks -> Table -> Pickaxe! ***")
else:
    log("\n*** Task not completed. Check video. ***")
log("Done!")
