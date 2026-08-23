"""Domain models — pure data, no I/O."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from uuid import uuid4


@dataclass(frozen=True)
class CaptureResult:
    photo_id: str
    local_path: Path
    captured_at: datetime


@dataclass(frozen=True)
class PrintJobRequest:
    faculty: str = ""
    qr_base_url: str = ""
    photo_id: str | None = None
    dither_style: str = "floyd"  # "comic" | "floyd"


@dataclass
class SessionResult:
    photo_id: str
    faculty: str
    source_path: Path
    layout_path: Path
    qr_url: str
    printed: bool
    message: str
    captured_at: datetime = field(default_factory=datetime.now)
    cloudinary_url: str | None = None
    cloudinary_photo_url: str | None = None
    cloudinary_layout_url: str | None = None
    layout_color_path: Path | None = None
    frame_paths: list[Path] = field(default_factory=list)

    @staticmethod
    def new_id() -> str:
        return uuid4().hex[:12]
