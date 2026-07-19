"""Monitor server — HTTP API + Web Dashboard for real-time NPC observation & control.

Uses only Python stdlib (no Flask/FastAPI needed). Runs in a background daemon
thread. The dashboard is a single-page HTML app that polls /api/state every 0.5s.

Architecture
------------
::

    NPC Loop (main thread)          MonitorServer (daemon thread)
    ┌──────────────────┐            ┌──────────────────────────┐
    │ engine.step()     │            │ ThreadingHTTPServer       │
    │       │            │   lock    │   /          → dashboard  │
    │ update_state() ───┼───────────┼──→ /api/state → JSON      │
    │       │            │  shared   │   /api/command ← POST     │
    │ check_commands() ←─┼───────────┼── from dashboard          │
    └──────────────────┘            └──────────────────────────┘
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_DASHBOARD_HTML = Path(__file__).resolve().parent / "dashboard.html"


@dataclass
class MonitorState:
    """Thread-safe shared state between NPC loop and monitor HTTP server.

    The NPC loop calls ``update()`` after each tick; the HTTP handler reads
    this to serve JSON to the dashboard.
    """

    npc_id: str = ""
    running: bool = False
    tick_count: int = 0

    # Current goal
    current_goal: str = ""

    # Last cognition output
    last_dialogue: str = ""
    last_thought: str = ""
    last_actions: list[str] = field(default_factory=list)
    last_reflection: str = ""

    # World state (from perception snapshot)
    position: list[float] = field(default_factory=lambda: [0.0, 0.0, 0.0])
    health: float = 20.0
    hunger: float = 20.0
    biome: str = "unknown"
    time_of_day: str = "unknown"
    weather: str = "Clear"

    # Inventory
    inventory: dict[str, int] = field(default_factory=dict)
    held_item: str = ""
    armor: dict[str, str] = field(default_factory=dict)

    # Nearby entities
    nearby_hostiles: list[str] = field(default_factory=list)
    nearby_players: list[str] = field(default_factory=list)
    nearby_items: list[str] = field(default_factory=list)

    # Recent events (ring buffer style, max 50)
    events: list[dict] = field(default_factory=list)
    _max_events: int = 50

    # User commands waiting to be processed by NPC loop
    pending_commands: list[str] = field(default_factory=list)

    # Full action log entries
    action_log: list[dict] = field(default_factory=list)

    # Connection info
    viewer_port: int = 3000
    bridge_connected: bool = False
    last_error: str = ""
    last_update_time: float = 0.0

    # Performance
    last_tick_duration: float = 0.0

    def add_event(self, event_type: str, data: dict | None = None) -> None:
        self.events.append({
            "type": event_type,
            "data": data or {},
            "time": time.time(),
        })
        if len(self.events) > self._max_events:
            self.events = self.events[-self._max_events:]

    def add_command(self, command: str) -> None:
        self.pending_commands.append(command)

    def pop_commands(self) -> list[str]:
        cmds = list(self.pending_commands)
        self.pending_commands.clear()
        return cmds

    def snapshot(self) -> dict:
        """Return a JSON-serializable snapshot of current state."""
        return {
            "npc_id": self.npc_id,
            "running": self.running,
            "tick_count": self.tick_count,
            "current_goal": self.current_goal,
            "last_dialogue": self.last_dialogue,
            "last_thought": self.last_thought,
            "last_actions": self.last_actions,
            "last_reflection": self.last_reflection,
            "position": self.position,
            "health": self.health,
            "hunger": self.hunger,
            "biome": self.biome,
            "time_of_day": self.time_of_day,
            "weather": self.weather,
            "inventory": self.inventory,
            "held_item": self.held_item,
            "armor": self.armor,
            "nearby_hostiles": self.nearby_hostiles,
            "nearby_players": self.nearby_players,
            "nearby_items": self.nearby_items,
            "events": self.events[-20:],  # last 20 events for dashboard
            "action_log": self.action_log[-10:],  # last 10 actions
            "viewer_port": self.viewer_port,
            "bridge_connected": self.bridge_connected,
            "last_error": self.last_error,
            "last_update_time": self.last_update_time,
            "last_tick_duration": self.last_tick_duration,
        }


class _MonitorHandler(BaseHTTPRequestHandler):
    """HTTP request handler for the monitor dashboard.

    Routes
    ------
    GET  /             → dashboard.html
    GET  /api/state    → JSON state snapshot
    POST /api/command  → push a command to the NPC
    """

    # Class-level reference to shared state, set by MonitorServer
    state: MonitorState = None  # type: ignore[assignment]

    def log_message(self, format: str, *args: Any) -> None:
        """Suppress default access logs (use our own logger)."""
        logger.debug("HTTP %s", format % args)

    def _send_json(self, data: dict, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html: str, status: int = 200) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        if self.path == "/" or self.path == "/index.html":
            if _DASHBOARD_HTML.exists():
                self._send_html(_DASHBOARD_HTML.read_text("utf-8"))
            else:
                self._send_html(_FALLBACK_HTML, 200)
        elif self.path == "/api/state":
            if self.state is None:
                self._send_json({"error": "no state"}, 503)
            else:
                self._send_json(self.state.snapshot())
        elif self.path == "/api/health":
            self._send_json({"ok": True, "bridge_connected": self.state.bridge_connected if self.state else False})
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        if self.path == "/api/command":
            content_len = int(self.headers.get("Content-Length", 0))
            raw = self.rfile.read(content_len)
            # Try UTF-8 first, then GBK (for Windows terminals)
            try:
                body = raw.decode("utf-8")
            except UnicodeDecodeError:
                try:
                    body = raw.decode("gbk")
                except UnicodeDecodeError:
                    body = raw.decode("utf-8", errors="replace")
            try:
                data = json.loads(body)
                command = data.get("command", "").strip()
            except json.JSONDecodeError:
                command = body.strip()

            if not command:
                self._send_json({"ok": False, "reason": "empty command"}, 400)
                return

            if self.state is not None:
                self.state.add_command(command)
                logger.info("Command queued: %s", command)
                self._send_json({"ok": True, "queued": command})
            else:
                self._send_json({"ok": False, "reason": "no state"}, 503)
        else:
            self.send_error(404)

    def do_OPTIONS(self) -> None:
        """CORS preflight."""
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


class MonitorServer:
    """HTTP server that serves the NPC monitor dashboard and API.

    Usage
    -----
        state = MonitorState(npc_id="Survivor")
        server = MonitorServer(state, port=8080)
        server.start()

        # In NPC loop:
        while True:
            engine.step(agent, npc_id)
            state.update_from_engine(engine)
            cmds = state.pop_commands()
            for cmd in cmds:
                engine.push_event(f"[玩家指令] {cmd}")
            time.sleep(0.5)

        server.stop()
    """

    def __init__(self, state: MonitorState, port: int = 8080):
        self._state = state
        self._port = port
        self._httpd: HTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def state(self) -> MonitorState:
        return self._state

    @property
    def url(self) -> str:
        return f"http://localhost:{self._port}"

    def start(self) -> None:
        """Start the HTTP server in a background daemon thread."""
        _MonitorHandler.state = self._state

        self._httpd = HTTPServer(("127.0.0.1", self._port), _MonitorHandler)
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True, name="monitor-server")
        self._thread.start()
        logger.info("Monitor dashboard: http://localhost:%d", self._port)

    def stop(self) -> None:
        """Shut down the HTTP server."""
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None
        if self._thread:
            self._thread.join(timeout=2)
            self._thread = None
        logger.info("Monitor server stopped")

    def __enter__(self) -> "MonitorServer":
        self.start()
        return self

    def __exit__(self, *args: Any) -> None:
        self.stop()


# ── Fallback HTML (if dashboard.html not found) ──────────────────────────

_FALLBACK_HTML = """<!DOCTYPE html>
<html lang="zh-CN">
<head><meta charset="utf-8"><title>ANNIE Monitor</title></head>
<body style="font-family:monospace;background:#111;color:#0f0;padding:20px">
<h1>ANNIE NPC Monitor</h1>
<p>Dashboard file not found. Please ensure <code>dashboard.html</code> exists.</p>
<p>API endpoints:</p>
<ul>
  <li><a href="/api/state">GET /api/state</a> — NPC state JSON</li>
  <li>POST /api/command — Send command (body: {"command": "..."})</li>
</ul>
</body></html>"""
