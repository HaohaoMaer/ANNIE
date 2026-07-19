"""TCP frame receiver — receives JPEG frames from prismarine-viewer headless.

The headless viewer streams frames over TCP in this format:
    4 bytes: frame length (uint32, little-endian)
    N bytes: JPEG image data

This module starts a TCP server, receives frames, and writes them to MP4.
"""

from __future__ import annotations

import logging
import socket
import struct
import threading
import time
from pathlib import Path

import numpy as np

logger = logging.getLogger(__name__)

# Default port matches prismarine-viewer examples
DEFAULT_PORT = 8089


class FrameReceiver:
    """Listens on a TCP port, receives JPEG frames, writes to MP4 via OpenCV."""

    def __init__(self, output_path: str | Path, port: int = DEFAULT_PORT, fps: float = 20.0):
        self.output_path = Path(output_path)
        self.port = port
        self.fps = fps
        self._server_socket: socket.socket | None = None
        self._client_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._stop = threading.Event()
        self._frame_count = 0
        self._start_time: float | None = None
        self._ready = threading.Event()

    @property
    def frame_count(self) -> int:
        return self._frame_count

    @property
    def elapsed(self) -> float:
        return (time.time() - self._start_time) if self._start_time else 0.0

    def start(self) -> None:
        """Start listening for incoming frames in a background thread."""
        self.output_path.parent.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._ready.clear()
        self._thread = threading.Thread(target=self._listen_loop, daemon=True)
        self._thread.start()

    def wait_ready(self, timeout: float = 15.0) -> bool:
        """Block until a client connects and sends the first frame."""
        return self._ready.wait(timeout=timeout)

    def stop(self) -> None:
        """Stop receiving and close connections."""
        self._stop.set()
        if self._client_socket:
            try:
                self._client_socket.shutdown(socket.SHUT_RDWR)
            except Exception:
                pass
            try:
                self._client_socket.close()
            except Exception:
                pass
        if self._server_socket:
            try:
                self._server_socket.close()
            except Exception:
                pass
        if self._thread:
            self._thread.join(timeout=15.0)
            self._thread = None

    def _listen_loop(self) -> None:
        """Accept connection, then receive and encode frames."""
        import cv2

        try:
            self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            self._server_socket.bind(("127.0.0.1", self.port))
            self._server_socket.listen(1)
            self._server_socket.settimeout(5.0)
            logger.info("FrameReceiver listening on 127.0.0.1:%d", self.port)

            writer = None
            frame_size = None

            # Wait for client (headless viewer) to connect
            while not self._stop.is_set():
                try:
                    self._client_socket, addr = self._server_socket.accept()
                    logger.info("FrameReceiver: client connected from %s", addr)
                    break
                except socket.timeout:
                    continue
                except OSError:
                    # Socket was closed during stop()
                    if self._stop.is_set():
                        return
                    raise
                except Exception:
                    logger.exception("Accept error")
                    return

            if self._stop.is_set():
                return

            self._client_socket.settimeout(3.0)

            self._start_time = time.time()

            while not self._stop.is_set():
                try:
                    # Read 4-byte length prefix (little-endian uint32)
                    length_bytes = self._recv_exact(4)
                    if length_bytes is None:
                        logger.info("FrameReceiver: client disconnected")
                        break

                    length = struct.unpack("<I", length_bytes)[0]
                    if length == 0 or length > 10_000_000:  # sanity check
                        logger.warning("FrameReceiver: bad frame length %d, skipping", length)
                        continue

                    # Read JPEG frame data
                    frame_data = self._recv_exact(length)
                    if frame_data is None:
                        logger.info("FrameReceiver: incomplete frame, disconnected")
                        break

                    # Decode JPEG → numpy → BGR
                    nparr = np.frombuffer(frame_data, np.uint8)
                    frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    if frame is None:
                        continue

                    # Initialize writer on first frame
                    if writer is None:
                        h, w = frame.shape[:2]
                        frame_size = (w, h)
                        fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                        writer = cv2.VideoWriter(
                            str(self.output_path), fourcc, self.fps, frame_size
                        )
                        if not writer.isOpened():
                            raise RuntimeError(f"VideoWriter failed: {self.output_path}")
                        logger.info("FrameReceiver: recording %dx%d @ %.0ffps → %s",
                                    w, h, self.fps, self.output_path)
                        self._ready.set()

                    if frame.shape[1] != frame_size[0] or frame.shape[0] != frame_size[1]:
                        frame = cv2.resize(frame, frame_size)

                    writer.write(frame)
                    self._frame_count += 1

                except socket.timeout:
                    continue
                except Exception:
                    logger.exception("FrameReceiver: frame error")
                    continue

        except Exception:
            logger.exception("FrameReceiver: fatal error")
        finally:
            if writer is not None:
                writer.release()
                logger.info("FrameReceiver: video saved (%d frames)", self._frame_count)
            if self._client_socket:
                try:
                    self._client_socket.close()
                except Exception:
                    pass
            if self._server_socket:
                try:
                    self._server_socket.close()
                except Exception:
                    pass

    def _recv_exact(self, count: int) -> bytes | None:
        """Receive exactly `count` bytes, or None if connection closed."""
        buf = b""
        while len(buf) < count:
            try:
                chunk = self._client_socket.recv(count - len(buf))
                if not chunk:
                    return None
                buf += chunk
            except socket.timeout:
                if self._stop.is_set():
                    return None
                continue
            except Exception:
                return None
        return buf
