"""MacBook / built-in webcam capture via ffmpeg (AVFoundation on macOS)."""

from __future__ import annotations

import logging
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Optional

from PIL import Image, ImageOps

from app.domain.models import CaptureResult, SessionResult
from app.infrastructure.camera.gphoto_camera import CameraError

logger = logging.getLogger(__name__)


class WebcamCamera:
    """Capture a single JPEG from the built-in FaceTime / USB webcam."""

    def __init__(
        self,
        temp_dir: Path,
        device_index: int = 0,
        aspect_w: int = 2,
        aspect_h: int = 3,
        max_long_edge: int = 1920,
        warmup_sec: float = 0.8,
    ) -> None:
        self.temp_dir = temp_dir
        self.device_index = device_index
        # Portrait 3:2 film format → width:height = 2:3
        self.aspect_w = aspect_w
        self.aspect_h = aspect_h
        self.max_long_edge = max_long_edge
        self.warmup_sec = warmup_sec
        self.temp_dir.mkdir(parents=True, exist_ok=True)

    def check_connection(self) -> dict:
        ffmpeg = _which_ffmpeg()
        if not ffmpeg:
            return {
                "connected": False,
                "backend": "webcam",
                "error": "Chưa có ffmpeg. Cài: brew install ffmpeg",
            }

        devices = self._list_avfoundation_devices(ffmpeg)
        if devices is None:
            return {
                "connected": False,
                "backend": "webcam",
                "error": (
                    "Không liệt kê được webcam. "
                    "System Settings → Privacy & Security → Camera → cho phép Terminal."
                ),
            }
        if not devices:
            return {
                "connected": False,
                "backend": "webcam",
                "error": "Không thấy camera nào trên Mac.",
            }

        model = devices[self.device_index] if self.device_index < len(devices) else devices[0]
        return {
            "connected": True,
            "backend": "webcam",
            "model": model,
            "device_index": self.device_index,
            "devices": devices,
            "aspect": f"{self.aspect_w}:{self.aspect_h}",
            "matches_hint": True,
        }

    def capture_photo(self, photo_id: Optional[str] = None) -> CaptureResult:
        photo_id = photo_id or SessionResult.new_id()
        dest = self.temp_dir / f"{photo_id}.jpg"
        raw = self.temp_dir / f"{photo_id}_raw.jpg"

        ffmpeg = _which_ffmpeg()
        if not ffmpeg:
            raise CameraError("Chưa có ffmpeg. Cài: brew install ffmpeg")

        # video:audio — "0:none" = first camera, no mic
        input_spec = f"{self.device_index}:none"
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "avfoundation",
            "-framerate",
            "30",
            "-video_size",
            "1280x720",
            "-i",
            input_spec,
            "-ss",
            str(self.warmup_sec),
            "-frames:v",
            "1",
            str(raw),
        ]
        logger.info("Webcam capture: %s", " ".join(cmd))
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=30)
        if result.returncode != 0 or not raw.exists() or raw.stat().st_size == 0:
            # Retry without forced resolution (some cams reject 1280x720)
            cmd_fallback = [
                ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-f",
                "avfoundation",
                "-framerate",
                "30",
                "-i",
                input_spec,
                "-ss",
                str(self.warmup_sec),
                "-frames:v",
                "1",
                str(raw),
            ]
            result = subprocess.run(
                cmd_fallback, capture_output=True, text=True, check=False, timeout=30
            )

        if result.returncode != 0 or not raw.exists() or raw.stat().st_size == 0:
            err = (result.stderr or result.stdout or "").strip() or "unknown"
            raise CameraError(
                "Không chụp được bằng camera MacBook. "
                "Cho phép Camera trong System Settings → Privacy & Security "
                f"cho Terminal/ffmpeg. Chi tiết: {err[:200]}"
            )

        try:
            with Image.open(raw) as image:
                image = ImageOps.exif_transpose(image)
                # Mirror ngang — khớp preview selfie (CSS scaleX(-1)) người dùng đã quen nhìn.
                portrait = self._to_portrait_crop(image.convert("RGB"))
                portrait = ImageOps.mirror(portrait)
                portrait.save(dest, format="JPEG", quality=92, optimize=True)
        finally:
            raw.unlink(missing_ok=True)

        if not dest.exists() or dest.stat().st_size == 0:
            raise CameraError("Lưu JPEG từ webcam thất bại.")

        logger.info("Webcam captured %s → %s", photo_id, dest)
        return CaptureResult(
            photo_id=photo_id,
            local_path=dest,
            captured_at=datetime.now(),
        )

    def _to_portrait_crop(self, image: Image.Image) -> Image.Image:
        """Center-crop to portrait aspect, then cap long edge size."""
        target_ratio = self.aspect_w / self.aspect_h  # e.g. 2/3
        if image.width >= image.height:
            out_h = min(image.height, self.max_long_edge)
            out_w = int(out_h * target_ratio)
        else:
            out_w = min(image.width, int(self.max_long_edge * target_ratio))
            out_h = int(out_w / target_ratio)
            if out_h > self.max_long_edge:
                out_h = self.max_long_edge
                out_w = int(out_h * target_ratio)

        out_w = max(1, out_w)
        out_h = max(1, out_h)
        return ImageOps.fit(image, (out_w, out_h), method=Image.Resampling.LANCZOS)

    @staticmethod
    def _list_avfoundation_devices(ffmpeg: str) -> Optional[list[str]]:
        result = subprocess.run(
            [ffmpeg, "-f", "avfoundation", "-list_devices", "true", "-i", ""],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        # ffmpeg prints device list to stderr
        text = (result.stderr or "") + (result.stdout or "")
        if "AVFoundation" not in text and "avfoundation" not in text.lower():
            return None

        devices: list[str] = []
        in_video = False
        for line in text.splitlines():
            low = line.lower()
            if "avfoundation video devices" in low:
                in_video = True
                continue
            if "avfoundation audio devices" in low:
                break
            if not in_video:
                continue
            # e.g. [AVFoundation indev @ ...] [0] FaceTime HD Camera
            if "] [" in line:
                try:
                    name = line.split("] ", 2)[-1].strip()
                    if name:
                        devices.append(name)
                except Exception:  # noqa: BLE001
                    continue
        return devices


def _which_ffmpeg() -> Optional[str]:
    return shutil.which("ffmpeg")
