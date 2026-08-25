"""Sony USB live view via gphoto2 --capture-movie → MJPEG multipart stream."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
import time
from typing import Generator, Optional

from app.infrastructure.camera.gphoto_camera import GPhotoCamera

logger = logging.getLogger(__name__)

BOUNDARY = b"frame"
SOI = b"\xff\xd8"
EOI = b"\xff\xd9"


class LiveViewError(RuntimeError):
    """Raised when live view cannot start."""


class GPhotoLiveView:
    """Exclusive gphoto2 movie-preview session for browser MJPEG."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: Optional[subprocess.Popen[bytes]] = None
        self._clients = 0
        self._last_error: Optional[str] = None

    @property
    def active(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    @property
    def last_error(self) -> Optional[str]:
        return self._last_error

    def status(self) -> dict:
        return {
            "active": self.active,
            "clients": self._clients,
            "error": self._last_error,
        }

    def stop(self) -> None:
        """Kill live-view process so still capture can claim USB."""
        with self._lock:
            self._stop_unlocked()

    def _stop_unlocked(self) -> None:
        proc = self._proc
        self._proc = None
        if proc is None:
            return
        logger.info("Stopping gphoto live view (pid=%s)", proc.pid)
        try:
            proc.terminate()
            try:
                proc.wait(timeout=2.5)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=1.5)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Live view stop: %s", exc)
        # Brief settle so PTP releases before capture
        time.sleep(0.35)

    def _ensure_started(self) -> subprocess.Popen[bytes]:
        if self._proc is not None and self._proc.poll() is None:
            return self._proc

        gphoto2_bin = shutil.which("gphoto2")
        if not gphoto2_bin:
            self._last_error = "gphoto2 CLI not available"
            raise LiveViewError(self._last_error)

        GPhotoCamera.release_macos_ptp_claim()
        time.sleep(0.2)

        cmd = [gphoto2_bin, "--quiet", "--stdout", "--capture-movie"]
        logger.info("Starting live view: %s", " ".join(cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                bufsize=0,
            )
        except OSError as exc:
            self._last_error = f"Could not start live view: {exc}"
            raise LiveViewError(self._last_error) from exc

        # Fail fast if process dies immediately
        time.sleep(0.4)
        if proc.poll() is not None:
            err = b""
            try:
                err = proc.stderr.read() if proc.stderr else b""
            except Exception:  # noqa: BLE001
                pass
            msg = err.decode("utf-8", errors="replace").strip() or f"exit {proc.returncode}"
            self._last_error = f"Live view failed: {msg[:240]}"
            raise LiveViewError(self._last_error)

        self._proc = proc
        self._last_error = None
        return proc

    def iter_multipart(self) -> Generator[bytes, None, None]:
        """Yield multipart/x-mixed-replace chunks for StreamingResponse."""
        with self._lock:
            self._clients += 1
            try:
                proc = self._ensure_started()
            except LiveViewError:
                self._clients = max(0, self._clients - 1)
                raise

        stdout = proc.stdout
        if stdout is None:
            with self._lock:
                self._clients = max(0, self._clients - 1)
            raise LiveViewError("Live view has no stdout")

        buf = bytearray()
        try:
            while True:
                if proc.poll() is not None:
                    err = b""
                    try:
                        err = proc.stderr.read() if proc.stderr else b""
                    except Exception:  # noqa: BLE001
                        pass
                    msg = err.decode("utf-8", errors="replace").strip()
                    self._last_error = msg[:240] if msg else "Live view stopped"
                    break

                chunk = stdout.read(4096)
                if not chunk:
                    time.sleep(0.01)
                    continue
                buf.extend(chunk)

                while True:
                    start = buf.find(SOI)
                    if start < 0:
                        # keep last byte in case of split marker
                        if len(buf) > 1:
                            del buf[:-1]
                        break
                    end = buf.find(EOI, start + 2)
                    if end < 0:
                        if start > 0:
                            del buf[:start]
                        break
                    frame = bytes(buf[start : end + 2])
                    del buf[: end + 2]
                    header = (
                        b"--" + BOUNDARY + b"\r\n"
                        b"Content-Type: image/jpeg\r\n"
                        b"Content-Length: " + str(len(frame)).encode() + b"\r\n"
                        b"\r\n"
                    )
                    yield header + frame + b"\r\n"
        finally:
            with self._lock:
                self._clients = max(0, self._clients - 1)
                if self._clients == 0:
                    self._stop_unlocked()


# Process-wide singleton — one USB PTP session
live_view = GPhotoLiveView()
