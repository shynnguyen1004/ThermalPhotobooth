"""Shorten long URLs before embedding into thermal QR codes."""

from __future__ import annotations

import json
import logging
import threading
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Dưới ngưỡng này coi như đủ ngắn cho QR 122 px @ EC-L (không gọi dịch vụ bên thứ ba).
SHORT_URL_MAX_LEN = 48
_USER_AGENT = "BKFirePhotobooth/1.0 (+thermal-qr)"
_LOCK = threading.Lock()
_MEMORY: dict[str, str] = {}


def shorten_url(
    url: str,
    *,
    cache_path: Optional[Path] = None,
    timeout: float = 8.0,
) -> str:
    """Return a short redirect URL, or the original if shortening fails / unnecessary."""
    original = (url or "").strip()
    if not original:
        return original
    # Thử QR trực tiếp Cloudinary — không rút gọn qua dịch vụ bên thứ ba.
    if "res.cloudinary.com" in original:
        return original
    if len(original) <= SHORT_URL_MAX_LEN and original.startswith(("http://", "https://")):
        return original

    cached = _cache_get(original, cache_path)
    if cached:
        return cached

    # cleanuri: redirect thẳng, không trang quảng cáo (TinyURL đã bỏ vì có interstitial).
    short = _try_cleanuri(original, timeout)
    if not short or not short.startswith("http"):
        logger.warning("URL shorten failed — dùng URL gốc (%d ký tự)", len(original))
        return original

    short = short.strip()
    _cache_set(original, short, cache_path)
    logger.info("Shortened URL %d→%d chars: %s", len(original), len(short), short)
    return short


def _try_cleanuri(url: str, timeout: float) -> Optional[str]:
    api = "https://cleanuri.com/api/v1/shorten"
    body = urllib.parse.urlencode({"url": url}).encode()
    try:
        raw = _http_post(api, body, timeout)
        data = json.loads(raw)
        return str(data.get("result_url") or "").strip() or None
    except Exception as exc:  # noqa: BLE001
        logger.debug("cleanuri failed: %s", exc)
        return None


def _http_get(url: str, timeout: float) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace").strip()


def _http_post(url: str, body: bytes, timeout: float) -> str:
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "User-Agent": _USER_AGENT,
            "Content-Type": "application/x-www-form-urlencoded",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace").strip()


def _cache_get(url: str, cache_path: Optional[Path]) -> Optional[str]:
    with _LOCK:
        if url in _MEMORY:
            return _MEMORY[url]
        if cache_path and cache_path.exists():
            try:
                data = json.loads(cache_path.read_text(encoding="utf-8"))
                if isinstance(data, dict) and url in data:
                    short = str(data[url])
                    _MEMORY[url] = short
                    return short
            except Exception:  # noqa: BLE001
                return None
    return None


def _cache_set(url: str, short: str, cache_path: Optional[Path]) -> None:
    with _LOCK:
        _MEMORY[url] = short
        if not cache_path:
            return
        try:
            cache_path.parent.mkdir(parents=True, exist_ok=True)
            data: dict = {}
            if cache_path.exists():
                try:
                    loaded = json.loads(cache_path.read_text(encoding="utf-8"))
                    if isinstance(loaded, dict):
                        data = loaded
                except Exception:  # noqa: BLE001
                    data = {}
            data[url] = short
            cache_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
        except Exception as exc:  # noqa: BLE001
            logger.debug("Could not persist short-url cache: %s", exc)
