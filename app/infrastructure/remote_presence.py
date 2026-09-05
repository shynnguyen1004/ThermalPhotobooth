"""Track /remote page heartbeats for desktop system bar."""

from __future__ import annotations

import threading
import time

STALE_SEC = 20.0


class RemotePresence:
    """Last-seen timestamps per remote client tab."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._clients: dict[str, float] = {}

    def ping(self, client_id: str) -> None:
        key = (client_id or "default").strip()[:64] or "default"
        now = time.monotonic()
        with self._lock:
            self._clients[key] = now
            cutoff = now - STALE_SEC
            self._clients = {k: v for k, v in self._clients.items() if v > cutoff}

    def status(self) -> dict:
        now = time.monotonic()
        with self._lock:
            cutoff = now - STALE_SEC
            active = [k for k, v in self._clients.items() if v > cutoff]
            self._clients = {k: self._clients[k] for k in active}
            count = len(active)
        return {
            "connected": count > 0,
            "clients": count,
        }


remote_presence = RemotePresence()
