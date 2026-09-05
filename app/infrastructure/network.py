"""LAN helpers for selfbooth remote QR on the kiosk."""

from __future__ import annotations

import socket


def get_lan_ip() -> str | None:
    """Best-effort IPv4 on the active default route (WiFi / hotspot)."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("8.8.8.8", 80))
            ip = sock.getsockname()[0]
            if ip and not ip.startswith("127."):
                return ip
    except OSError:
        pass
    return None


def remote_control_url(lan_ip: str | None, port: int) -> str | None:
    if not lan_ip:
        return None
    return f"http://{lan_ip}:{port}/remote"
