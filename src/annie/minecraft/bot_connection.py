"""Minecraft bridge — Python side.

MinecraftBridge launches a Node.js mineflayer subprocess and communicates
via JSON-RPC over stdin/stdout.  Communication is fully synchronous: a
background thread reads stdout, while ``call()`` writes to stdin and blocks
on a response queue.

FakeBridge provides a deterministic in-process stub for tests.
"""

from __future__ import annotations

import json
import logging
import queue
import signal
import subprocess
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_BRIDGE_JS = Path(__file__).resolve().parent / "minecraft_bridge.js"

# ── Data types ─────────────────────────────────────────────────────────────

@dataclass
class BridgeEvent:
    event_type: str
    data: dict[str, Any]
    timestamp: float = field(default_factory=time.time)


# ── Abstract interface ─────────────────────────────────────────────────────

class AbstractBridge(ABC):
    """Interface that both MinecraftBridge and FakeBridge implement."""

    @abstractmethod
    def start(self) -> None:
        """Connect to Minecraft and block until the bot is ready."""

    @abstractmethod
    def call(self, method: str, params: dict | None = None, timeout_ms: int = 30_000) -> dict:
        """Send a request and block until completion/failure/timeout."""

    @abstractmethod
    def poll_events(self) -> list[BridgeEvent]:
        """Return and clear all pending pushed events."""

    @abstractmethod
    def stop(self) -> None:
        """Disconnect and clean up."""


# ── Real bridge (sync subprocess + background reader thread) ────────────────

class MinecraftBridge(AbstractBridge):
    """Manages a Node.js mineflayer subprocess via synchronous JSON-RPC over stdio.

    A background daemon thread reads stdout and routes responses / events.
    ``call()`` writes a request to stdin and blocks on a response queue.
    """

    READY_TIMEOUT_MS = 120_000

    def __init__(
        self,
        host: str = "localhost",
        port: int = 25565,
        username: str = "ANNIE_bot",
        version: str | None = None,
        auth: str = "offline",
        viewer_port: int | None = None,
        record_port: int | None = None,
        node_cmd: str = "node",
    ):
        self.host = host
        self.port = port
        self.username = username
        self.version = version
        self.auth = auth
        self.viewer_port = viewer_port
        self.record_port = record_port
        self.node_cmd = node_cmd

        self._proc: subprocess.Popen | None = None
        self._pending: dict[str, queue.Queue[dict]] = {}  # req_id → response queue
        self._events: deque[BridgeEvent] = deque()
        self._next_id = 0
        self._reader_thread: threading.Thread | None = None
        self._running = False
        self._lock = threading.Lock()

    # ── Lifecycle ──────────────────────────────────────────────────────

    def start(self) -> None:
        args = [
            self.node_cmd,
            str(_BRIDGE_JS),
            "--host", self.host,
            "--port", str(self.port),
            "--username", self.username,
            "--auth", self.auth,
        ]
        if self.version:
            args.extend(["--version", self.version])
        if self.viewer_port is not None:
            args.extend(["--viewer-port", str(self.viewer_port)])
        if self.record_port is not None:
            args.extend(["--record-port", str(self.record_port)])

        self._proc = subprocess.Popen(
            args,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
        )
        self._running = True

        # Start background reader thread
        self._reader_thread = threading.Thread(target=self._read_loop, daemon=True)
        self._reader_thread.start()

        logger.info("Minecraft bridge subprocess started (pid=%d)", self._proc.pid)

        # Wait for the "ready" event
        self._wait_ready(timeout_ms=self.READY_TIMEOUT_MS)

    def _wait_ready(self, timeout_ms: int) -> None:
        deadline = time.time() + timeout_ms / 1000
        while time.time() < deadline:
            if self._proc is None or self._proc.poll() is not None:
                stderr_output = ""
                if self._proc and self._proc.stderr:
                    stderr_output = self._proc.stderr.read()[:500]
                raise RuntimeError(
                    f"Bridge process exited early (code={self._proc.returncode if self._proc else '?'}). "
                    f"stderr: {stderr_output}"
                )
            with self._lock:
                for i, ev in enumerate(list(self._events)):
                    if ev.event_type == "ready":
                        del self._events[i]
                        logger.info("Bot ready: %s", ev.data)
                        return
            time.sleep(0.2)
        raise TimeoutError(f"Bot did not send 'ready' event within {timeout_ms}ms")

    def _read_loop(self) -> None:
        """Background thread: read stdout lines, route to events or responses."""
        assert self._proc is not None
        assert self._proc.stdout is not None
        try:
            for line in self._proc.stdout:
                line = line.strip()
                if not line:
                    continue
                self._handle_line(line)
        except Exception:
            logger.exception("Bridge reader thread error")
        finally:
            self._running = False

    def _handle_line(self, line: str) -> None:
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            logger.warning("Bridge: unparseable line: %s", line[:200])
            return

        # Event push
        if obj.get("type") == "event":
            with self._lock:
                self._events.append(BridgeEvent(
                    event_type=obj["event"],
                    data=obj.get("data", {}),
                ))
            return

        # Error
        if obj.get("type") == "error":
            logger.error("Bridge error: %s", obj.get("error", ""))
            return

        # Response to a pending request
        req_id = obj.get("id")
        if req_id and req_id in self._pending:
            self._pending[req_id].put(obj)

    # ── Request/response ───────────────────────────────────────────────

    def _next_req_id(self) -> str:
        self._next_id += 1
        return f"req_{self._next_id:04d}"

    def call(self, method: str, params: dict | None = None, timeout_ms: int = 30_000) -> dict:
        if self._proc is None or self._proc.stdin is None:
            raise RuntimeError("Bridge not started")

        req_id = self._next_req_id()
        req = {
            "id": req_id,
            "method": method,
            "params": params or {},
            "timeout_ms": timeout_ms,
        }
        resp_queue: queue.Queue[dict] = queue.Queue()
        self._pending[req_id] = resp_queue

        payload = json.dumps(req, ensure_ascii=False) + "\n"
        try:
            self._proc.stdin.write(payload)
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            self._pending.pop(req_id, None)
            return {"ok": False, "reason": f"Bridge pipe broken: {e}"}

        deadline = time.time() + timeout_ms / 1000 + 5
        while time.time() < deadline:
            try:
                result = resp_queue.get(timeout=min(1.0, deadline - time.time()))
            except queue.Empty:
                self._pending.pop(req_id, None)
                return {"ok": False, "reason": f"request {req_id} timed out"}

            status = result.get("status")
            data = result.get("data", {})

            # Skip intermediate "accepted" — wait for "completed"/"failed"/"timeout"
            if status == "accepted":
                continue

            self._pending.pop(req_id, None)
            if status == "completed":
                return data
            elif status in ("failed", "timeout"):
                return data
            else:
                return {"ok": False, "reason": f"unknown status: {status}"}

        self._pending.pop(req_id, None)
        return {"ok": False, "reason": f"request {req_id} timed out"}

    def poll_events(self) -> list[BridgeEvent]:
        with self._lock:
            out = list(self._events)
            self._events.clear()
        return out

    def stop(self) -> None:
        self._running = False
        if self._proc:
            try:
                self._proc.send_signal(signal.SIGTERM)
                try:
                    self._proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    self._proc.kill()
                    self._proc.wait()
            except (ProcessLookupError, OSError):
                pass  # already dead
            logger.info("Minecraft bridge subprocess stopped")


# ── Fake bridge (for tests, no real Minecraft needed) ──────────────────────

class FakeBridge(AbstractBridge):
    """Deterministic in-process bridge for tests.  No Minecraft, no Node.js."""

    def __init__(self, startup_state: dict | None = None):
        self._startup_state = startup_state or _DEFAULT_STARTUP
        self._responses: dict[str, dict] = {}
        self._events: deque[BridgeEvent] = deque()
        self._started = False
        self._call_log: list[dict] = []

    def start(self) -> None:
        self._started = True

    def set_response(self, method: str, result: dict) -> None:
        self._responses[method] = result

    def push_event(self, event_type: str, data: dict | None = None) -> None:
        self._events.append(BridgeEvent(event_type=event_type, data=data or {}))

    def call(self, method: str, params: dict | None = None, timeout_ms: int = 30_000) -> dict:
        self._call_log.append({"method": method, "params": params or {}})
        if method in self._responses:
            return self._responses[method]
        if method == "get_stats":
            return dict(self._startup_state.get("stats", {"ok": True, "position": [0, 64, 0]}))
        if method == "get_nearby_blocks":
            return self._startup_state.get("nearby_blocks", {"ok": True, "blocks": []})
        if method == "get_nearby_entities":
            return self._startup_state.get("nearby_entities", {"ok": True, "entities": []})
        if method == "get_inventory":
            return self._startup_state.get("inventory", {"ok": True, "items": {}, "armor": {}, "held_item": None, "empty_slots": 36})
        if method == "get_craftable":
            return self._startup_state.get("craftable", {"ok": True, "craftable": []})
        return {"ok": True}

    def poll_events(self) -> list[BridgeEvent]:
        out = list(self._events)
        self._events.clear()
        return out

    @property
    def call_log(self) -> list[dict]:
        return list(self._call_log)

    def stop(self) -> None:
        self._started = False


_DEFAULT_STARTUP = {
    "stats": {"ok": True, "position": [0.0, 64.0, 0.0], "health": 20, "hunger": 20, "biome": "plains", "time": "Morning", "weather": "Clear", "gamemode": "survival"},
    "nearby_blocks": {"ok": True, "blocks": []},
    "nearby_entities": {"ok": True, "entities": []},
    "inventory": {"ok": True, "items": {}, "armor": {}, "held_item": None, "empty_slots": 36},
    "craftable": {"ok": True, "craftable": []},
}
