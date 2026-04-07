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
    loop: asyncio.AbstractEventLoop = field(default=None)  # type: ignore[assignment]
    # "initializing" | "running" | "game_over" | "error" | "ended"
    status: str = "initializing"
    # All events appended here; SSE clients read by index for reconnect support.
    event_buffer: list = field(default_factory=list)
    # Signals waiting SSE generators that new events are available.
    notify: asyncio.Event = field(default_factory=asyncio.Event)


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


@app.get("/api/games/active")
async def get_active_game() -> dict:
    """Return the most recent in-progress game session, if any.

    The frontend calls this on page load to decide whether to offer a resume.
    """
    in_progress = [
        s for s in GAMES.values()
        if s.status not in ("game_over", "error", "ended")
    ]
    if not in_progress:
        return {"game_id": None}

    session = in_progress[-1]
    turn_count = sum(1 for e in session.event_buffer if e.get("type") == "dialogue")
    return {
        "game_id": session.game_id,
        "status": session.status,
        "turn_count": turn_count,
    }


@app.get("/api/games/{game_id}/status")
async def get_game_status(game_id: str) -> dict:
    """Return status and progress of a specific game session."""
    if game_id not in GAMES:
        raise HTTPException(status_code=404, detail="Game not found")
    session = GAMES[game_id]
    turn_count = sum(1 for e in session.event_buffer if e.get("type") == "dialogue")
    return {
        "game_id": game_id,
        "status": session.status,
        "turn_count": turn_count,
    }


@app.get("/api/games/{game_id}/stream")
async def stream_game(game_id: str) -> EventSourceResponse:
    """SSE stream for a game.

    Supports reconnection: a returning client receives all buffered events
    from the beginning (so the frontend can rebuild full state), then
    continues receiving live events as they arrive.
    """
    if game_id not in GAMES:
        raise HTTPException(status_code=404, detail="Game not found")

    session = GAMES[game_id]

    async def event_generator():
        # ── Callback wired into game thread ───────────────────────────
        def callback(event: dict) -> None:
            """Thread-safe: called from ThreadPoolExecutor thread."""
            session.event_buffer.append(event)
            # Update status for terminal events
            etype = event.get("type")
            if etype == "game_over":
                session.status = "game_over"
            elif etype == "error":
                session.status = "error"
            elif event.get("__sentinel__"):
                session.status = "ended"
            # Wake up any waiting SSE generators
            session.loop.call_soon_threadsafe(session.notify.set)

        # ── Launch the game thread only on the first connection ───────
        # If the session already has buffered events, we're reconnecting —
        # the game thread is still running; skip re-launching it.
        first_connection = len(session.event_buffer) == 0
        if first_connection:
            def run_game() -> None:
                try:
                    callback({"type": "initializing", "message": "正在加载配置..."})
                    config = load_model_config(str(CONFIG_PATH))

                    engine = WorldEngineAgent(
                        script_folder=SCRIPT_FOLDER,
                        config=config,
                    )
                    engine.read_all_files(event_callback=callback)

                    callback({"type": "initializing", "message": "正在生成游戏流程..."})
                    engine.generate_game_flow()

                    callback({"type": "initializing", "message": "正在初始化角色..."})
                    engine.initialize_npcs()
                    engine.start_game()

                    initial_state = engine.get_initial_state()
                    callback({"type": "game_ready", "game_id": game_id, **initial_state})

                    engine.run_game_loop(max_rounds=2, event_callback=callback)

                    try:
                        engine.save_session(REPLAYS_DIR, game_id=game_id)
                    except Exception as save_exc:
                        import logging
                        logging.getLogger(__name__).warning(f"Failed to save session: {save_exc}")

                except Exception as exc:
                    callback({"type": "error", "message": str(exc)})
                finally:
                    session.loop.call_soon_threadsafe(
                        session.event_buffer.append, {"__sentinel__": True}
                    )
                    session.loop.call_soon_threadsafe(session.notify.set)

            session.loop.run_in_executor(_executor, run_game)

        # ── Stream events to client (buffer-index based) ──────────────
        # Both first connections and reconnections use this same loop.
        # First connections start at idx=0 and see events as they arrive.
        # Reconnections also start at idx=0 and replay all buffered events
        # before catching up to live.
        idx = 0
        try:
            while True:
                # Drain all available events from buffer starting at idx
                while idx < len(session.event_buffer):
                    event = session.event_buffer[idx]
                    idx += 1
                    if event.get("__sentinel__"):
                        return
                    event_type = event.get("type", "message")
                    yield {
                        "event": event_type,
                        "data": json.dumps(event, ensure_ascii=False),
                    }

                # If game is over and we've drained everything, close stream
                if session.status in ("game_over", "error", "ended"):
                    return

                # Wait for new events; clear first, then re-check to avoid
                # the race where an event arrived between drain and clear.
                session.notify.clear()
                if idx < len(session.event_buffer):
                    continue  # new event slipped in before clear
                try:
                    await asyncio.wait_for(session.notify.wait(), timeout=20.0)
                except asyncio.TimeoutError:
                    # Heartbeat to keep the SSE connection alive
                    yield {
                        "event": "heartbeat",
                        "data": json.dumps({"type": "heartbeat", "ts": int(time.time())}),
                    }
        finally:
            # Only evict finished sessions; keep in-progress ones for reconnect.
            if session.status in ("game_over", "error", "ended"):
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
