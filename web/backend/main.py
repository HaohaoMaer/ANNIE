"""FastAPI backend for ANNIE real-time web interface.

Exposes a Server-Sent Events (SSE) stream so the frontend can watch game
events as they happen.  All LLM calls run in a ThreadPoolExecutor thread;
events are bridged back to the asyncio event loop via call_soon_threadsafe.

Usage:
    uvicorn web.backend.main:app --host 0.0.0.0 --port 8000 --reload
    # or from the repo root:
    python -m uvicorn web.backend.main:app --port 8000 --reload
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
import uuid
import warnings
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

# Suppress PyTorch pin_memory UserWarning that fires on every EasyOCR batch
# when there is no GPU.  Must be set before any torch/easyocr imports.
warnings.filterwarnings(
    "ignore",
    category=UserWarning,
    message=".*pin_memory.*",
)

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

# Make sure the project src/ is importable when running from any cwd.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

load_dotenv(_REPO_ROOT / ".env")

from annie.npc.config import load_model_config  # noqa: E402
from annie.world_engine.world_engine_agent import WorldEngineAgent  # noqa: E402

# ── Configuration ─────────────────────────────────────────────────────────────

SCRIPT_FOLDER = _REPO_ROOT / "午夜列车"
CONFIG_PATH = _REPO_ROOT / "config" / "model_config.yaml"
REPLAYS_DIR = _REPO_ROOT / "web" / "replays"

# ── Application ───────────────────────────────────────────────────────────────

app = FastAPI(title="ANNIE Game API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)

# Thread pool: limit to 2 concurrent game runs (each is very LLM-heavy).
_executor = ThreadPoolExecutor(max_workers=2)


# ── Game Session ──────────────────────────────────────────────────────────────

@dataclass
class GameSession:
    game_id: str
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    cancel_event: asyncio.Event = field(default_factory=asyncio.Event)
    loop: asyncio.AbstractEventLoop = field(default=None)  # type: ignore[assignment]


# In-memory session registry.  Single process only.
GAMES: dict[str, GameSession] = {}


# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/api/games")
async def create_game() -> dict:
    """Create a new game session and return its ID."""
    game_id = str(uuid.uuid4())[:8]
    loop = asyncio.get_running_loop()
    session = GameSession(game_id=game_id, loop=loop)
    GAMES[game_id] = session
    return {"game_id": game_id}


@app.get("/api/games/{game_id}/stream")
async def stream_game(game_id: str) -> EventSourceResponse:
    """SSE stream for a game.  Connect here after POST /api/games."""
    if game_id not in GAMES:
        raise HTTPException(status_code=404, detail="Game not found")

    session = GAMES[game_id]

    async def event_generator():
        # ── Heartbeat task ────────────────────────────────────────────
        # Prevents browser-side SSE timeout during long OCR / LLM phases.
        async def heartbeat():
            while not session.cancel_event.is_set():
                await asyncio.sleep(15)
                try:
                    session.queue.put_nowait({"type": "heartbeat", "ts": int(time.time())})
                except asyncio.QueueFull:
                    pass

        hb_task = asyncio.create_task(heartbeat())

        # ── Callback wired into game thread ───────────────────────────
        def callback(event: dict) -> None:
            """Thread-safe: called from ThreadPoolExecutor thread."""
            session.loop.call_soon_threadsafe(session.queue.put_nowait, event)

        # ── Game thread ───────────────────────────────────────────────
        def run_game() -> None:
            try:
                callback({"type": "initializing", "message": "正在加载配置..."})
                config = load_model_config(str(CONFIG_PATH))

                engine = WorldEngineAgent(
                    script_folder=SCRIPT_FOLDER,
                    config=config,
                )
                # Pass callback so read_all_files can stream per-file progress
                engine.read_all_files(event_callback=callback)

                callback({"type": "initializing", "message": "正在生成游戏流程..."})
                engine.generate_game_flow()

                callback({"type": "initializing", "message": "正在初始化角色..."})
                engine.initialize_npcs()
                engine.start_game()

                initial_state = engine.get_initial_state()
                callback({"type": "game_ready", "game_id": game_id, **initial_state})

                engine.run_game_loop(max_rounds=2, event_callback=callback)
                # game_over event is emitted inside run_game_loop

                # Save session for replay after game ends
                try:
                    engine.save_session(REPLAYS_DIR, game_id=game_id)
                except Exception as save_exc:
                    import logging
                    logging.getLogger(__name__).warning(f"Failed to save session: {save_exc}")

            except Exception as exc:
                callback({"type": "error", "message": str(exc)})
            finally:
                # Sentinel signals the SSE generator to close the stream.
                session.loop.call_soon_threadsafe(
                    session.queue.put_nowait, {"__sentinel__": True}
                )

        # Launch the game in the thread pool without blocking the event loop.
        session.loop.run_in_executor(_executor, run_game)

        # ── Stream events to client ───────────────────────────────────
        try:
            while True:
                try:
                    event = await asyncio.wait_for(session.queue.get(), timeout=120.0)
                except asyncio.TimeoutError:
                    # Send a keepalive comment so the connection stays open.
                    yield {"event": "heartbeat", "data": json.dumps({"type": "heartbeat", "ts": int(time.time())})}
                    continue

                if event.get("__sentinel__"):
                    break

                event_type = event.get("type", "message")
                yield {
                    "event": event_type,
                    "data": json.dumps(event, ensure_ascii=False),
                }
        finally:
            hb_task.cancel()
            session.cancel_event.set()
            GAMES.pop(game_id, None)

    return EventSourceResponse(event_generator())


@app.get("/api/health")
async def health() -> dict:
    return {"status": "ok", "active_games": len(GAMES)}


@app.get("/api/replays")
async def list_replays() -> dict:
    """List all saved replay sessions."""
    REPLAYS_DIR.mkdir(parents=True, exist_ok=True)
    replays = []
    for f in sorted(REPLAYS_DIR.glob("session_*.json"), reverse=True):
        try:
            with open(f, encoding="utf-8") as fh:
                data = json.load(fh)
            meta = data.get("metadata", {})
            replays.append({
                "id": f.stem,
                "filename": f.name,
                "game_name": meta.get("game_name", "Unknown"),
                "game_name_en": meta.get("game_name_en", "Unknown"),
                "created_at": meta.get("created_at", ""),
                "total_turns": meta.get("total_turns", 0),
                "npc_count": meta.get("npc_count", 0),
            })
        except Exception:
            continue
    return {"replays": replays}


@app.get("/api/replays/{replay_id}")
async def get_replay(replay_id: str) -> dict:
    """Get full replay data by ID."""
    REPLAYS_DIR.mkdir(parents=True, exist_ok=True)
    filepath = REPLAYS_DIR / f"{replay_id}.json"
    if not filepath.exists():
        raise HTTPException(status_code=404, detail="Replay not found")
    with open(filepath, encoding="utf-8") as f:
        return json.load(f)
