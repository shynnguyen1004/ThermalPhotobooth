#!/usr/bin/env python3
"""BK FIRE Photobooth — entry point."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

# Ensure project root is on sys.path when launched as `python main.py`
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import uvicorn

from app.presentation.api import create_app
from config.settings import settings

# ASGI app for Render / `uvicorn main:app --host 0.0.0.0 --port $PORT`
app = create_app()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    settings.ensure_dirs()
    port = int(os.environ.get("PORT", settings.port))
    uvicorn.run(
        app,
        host=settings.host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
