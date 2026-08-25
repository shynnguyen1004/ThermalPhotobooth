#!/usr/bin/env python3
"""UTS Photobooth — entry point.

Chạy một lệnh: ``python main.py`` → http://127.0.0.1:8000
(UI React được build vào ``frontend/dist`` rồi FastAPI serve).
"""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

# Ensure project root is on sys.path when launched as `python main.py`
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

from app.presentation.api import create_app
from config.settings import settings

logger = logging.getLogger(__name__)

FRONTEND_DIR = ROOT / "frontend"
FRONTEND_DIST = FRONTEND_DIR / "dist"
FRONTEND_INDEX = FRONTEND_DIST / "index.html"


def _newest_mtime(paths: list[Path]) -> float:
    newest = 0.0
    for path in paths:
        if not path.exists():
            continue
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
            continue
        for child in path.rglob("*"):
            if child.is_file():
                newest = max(newest, child.stat().st_mtime)
    return newest


def frontend_needs_build() -> bool:
    if not (FRONTEND_DIR / "package.json").is_file():
        return False
    if not FRONTEND_INDEX.is_file():
        return True
    sources = [
        FRONTEND_DIR / "src",
        FRONTEND_DIR / "public",
        FRONTEND_DIR / "index.html",
        FRONTEND_DIR / "package.json",
        FRONTEND_DIR / "vite.config.ts",
        FRONTEND_DIR / "tsconfig.json",
        FRONTEND_DIR / "tsconfig.app.json",
    ]
    return _newest_mtime(sources) > FRONTEND_INDEX.stat().st_mtime


def ensure_frontend_built() -> bool:
    """Build React SPA when missing/stale. Returns True if dist is ready."""
    if os.environ.get("SKIP_FRONTEND_BUILD", "").strip().lower() in {"1", "true", "yes"}:
        return FRONTEND_INDEX.is_file()

    if not (FRONTEND_DIR / "package.json").is_file():
        return False

    if not frontend_needs_build():
        return True

    npm = shutil.which("npm")
    if not npm:
        logger.warning(
            "Frontend cần build nhưng không tìm thấy npm. "
            "Chạy thủ công: cd frontend && npm run build"
        )
        return FRONTEND_INDEX.is_file()

    logger.info("Building React frontend → %s", FRONTEND_DIST)
    subprocess.run([npm, "run", "build"], cwd=str(FRONTEND_DIR), check=True)
    return FRONTEND_INDEX.is_file()


# ASGI app for Render / `uvicorn main:app --host 0.0.0.0 --port $PORT`
# Prefer a pre-built dist (CI / Render build step). Local `python main.py` rebuilds if stale.
app = create_app()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    settings.ensure_dirs()

    global app
    built = ensure_frontend_built()
    if built:
        app = create_app()
        logger.info("UI: React SPA (frontend/dist) → http://%s:%s", settings.host, os.environ.get("PORT", settings.port))
    else:
        logger.warning(
            "UI: template Jinja (chưa có frontend/dist). "
            "Chạy: cd frontend && npm install && npm run build"
        )

    port = int(os.environ.get("PORT", settings.port))
    uvicorn.run(
        app,
        host=settings.host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
