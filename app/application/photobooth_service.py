"""Orchestrates capture → template print → Cloudinary upload (background)."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Optional, Protocol

from app.application.layout_service import LayoutRenderer
from app.domain.models import CaptureResult, PrintJobRequest, SessionResult
from app.infrastructure.camera.gphoto_camera import CameraError
from app.infrastructure.printer.pos58_printer import POS58Printer, PrinterError
from app.infrastructure.storage.cloudinary_storage import CloudinaryError, CloudinaryStorage
from app.infrastructure.storage.file_storage import FileStorage

logger = logging.getLogger(__name__)

CameraSource = Literal["gphoto", "webcam"]


class _Camera(Protocol):
    def check_connection(self) -> dict: ...

    def capture_photo(
        self,
        photo_id: Optional[str] = None,
        source: Optional[CameraSource] = None,
    ) -> CaptureResult: ...

    @property
    def active_source(self) -> str: ...

    def probe_sources(self) -> dict: ...


@dataclass(frozen=True)
class CaptureMode:
    burst_count: int
    burst_interval_sec: float
    portrait_aspect_w: int
    portrait_aspect_h: int


class PhotoboothService:
    def __init__(
        self,
        camera: _Camera,
        layout: LayoutRenderer,
        printer: POS58Printer,
        storage: FileStorage,
        cloudinary: Optional[CloudinaryStorage] = None,
        qr_base_url: str = "",
        public_base_url: str = "",
        gphoto_mode: CaptureMode | None = None,
        webcam_mode: CaptureMode | None = None,
        burst_count: int = 1,
        burst_interval_sec: float = 0.0,
        prints_dir: Optional[Path] = None,
    ) -> None:
        self.camera = camera
        self.layout = layout
        self.printer = printer
        self.storage = storage
        self.cloudinary = cloudinary
        self.qr_base_url = qr_base_url
        self.public_base_url = (public_base_url or "").strip().rstrip("/")
        self.prints_dir = prints_dir or getattr(layout, "output_dir", None)
        self.gphoto_mode = gphoto_mode or CaptureMode(
            burst_count=1,
            burst_interval_sec=0.0,
            portrait_aspect_w=layout.portrait_aspect_w,
            portrait_aspect_h=layout.portrait_aspect_h,
        )
        self.webcam_mode = webcam_mode or CaptureMode(
            burst_count=1,
            burst_interval_sec=0.0,
            portrait_aspect_w=3,
            portrait_aspect_h=4,
        )
        self._last_print: dict | None = None
        self._apply_mode(self.gphoto_mode)
        self._recover_last_print()

    def status(self) -> dict:
        camera_status: dict
        try:
            camera_status = self.camera.check_connection()
        except CameraError as exc:
            camera_status = {"connected": False, "error": str(exc)}

        sources = camera_status.get("sources")
        if not sources and hasattr(self.camera, "probe_sources"):
            try:
                sources = self.camera.probe_sources()
            except Exception:  # noqa: BLE001
                sources = None

        source = camera_status.get("source") or getattr(self.camera, "active_source", "gphoto")
        mode = self._mode_for(str(source))
        self._apply_mode(mode)

        cloud = self.cloudinary.status() if self.cloudinary else {"enabled": False}
        last = self.last_print_info()
        return {
            "camera": camera_status,
            "cameras": sources,
            "printer": self.printer.check_connection(),
            "cloudinary": cloud,
            "burst": {
                "count": self.burst_count,
                "interval_sec": self.burst_interval_sec,
                "aspect": f"{self.layout.portrait_aspect_w}:{self.layout.portrait_aspect_h}",
                "source": source,
            },
            "last_print": last,
        }

    def last_print_info(self) -> dict | None:
        if not self._last_print:
            self._recover_last_print()
        if not self._last_print:
            return None
        return dict(self._last_print)

    def recent_prints(self, limit: int = 6) -> list[dict]:
        """Newest color layouts available for reprint (max ``limit``)."""
        limit = max(1, min(20, int(limit or 6)))
        if not self.prints_dir or not self.prints_dir.is_dir():
            return []

        layouts = sorted(
            self.prints_dir.glob("*_layout.png"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        items: list[dict] = []
        for path in layouts:
            if len(items) >= limit:
                break
            photo_id = path.name[: -len("_layout.png")]
            if not photo_id:
                continue
            photo = self.storage.get_photo(photo_id)
            frames = self.storage.get_session_frames(photo_id)
            if photo is None and not frames:
                continue
            print_path = self.prints_dir / f"{photo_id}_print.png"
            mtime = path.stat().st_mtime
            items.append(
                {
                    "photo_id": photo_id,
                    "layout_color_url": f"/prints/{photo_id}_layout.png",
                    "layout_url": (
                        f"/prints/{photo_id}_print.png" if print_path.is_file() else None
                    ),
                    "photo_url": f"/photos/{photo_id}.jpg" if photo is not None else None,
                    "captured_at": datetime.fromtimestamp(mtime).strftime("%Y-%m-%d %H:%M:%S"),
                }
            )
        return items

    def capture_and_print(
        self,
        request: PrintJobRequest,
        camera_source: Optional[CameraSource] = None,
    ) -> SessionResult:
        source: CameraSource
        if camera_source in ("gphoto", "webcam"):
            source = camera_source
        else:
            active = getattr(self.camera, "active_source", "webcam")
            source = active if active in ("gphoto", "webcam") else "webcam"

        mode = self._mode_for(str(source))
        self._apply_mode(mode)

        session_id = request.photo_id or SessionResult.new_id()
        logger.info(
            "Session %s — source=%s — dither=%s — aspect %s:%s",
            session_id,
            source,
            request.dither_style,
            self.layout.portrait_aspect_w,
            self.layout.portrait_aspect_h,
        )

        t0 = time.perf_counter()
        frame_paths = self._capture_burst(session_id, camera_source=source)
        logger.info("Capture done in %.2fs (%s)", time.perf_counter() - t0, session_id)

        t1 = time.perf_counter()
        download_path = self.layout.render_photo_color(frame_paths, session_id)
        main_photo = self.storage.archive_photo(download_path, session_id)

        # Color layout for guest download (QR points at expected Cloudinary URL).
        layout_color_path = self.layout.render_layout_color_to_path(
            photo_paths=frame_paths,
            qr_url="",
            photo_id=session_id,
        )

        # Stable QR URL — print does NOT wait for Cloudinary upload.
        download_qr, upload_note = self._download_qr_url(request.qr_base_url, session_id)
        cloudinary_photo_url, cloudinary_layout_url = self._expected_cloudinary_urls(session_id)
        if cloudinary_layout_url:
            download_qr = cloudinary_layout_url

        dither = request.dither_style if request.dither_style in ("comic", "floyd") else "floyd"
        layout_path = self.layout.render_to_path(
            photo_paths=frame_paths,
            qr_url=download_qr,
            photo_id=session_id,
            dither_style=dither,  # type: ignore[arg-type]
        )
        logger.info("Layouts rendered in %.2fs (%s)", time.perf_counter() - t1, session_id)

        register_qr = (self.layout.register_qr_url or "").strip()
        shot_label = f"{self.burst_count} shots" if self.burst_count > 1 else "1 shot"
        printed = False
        style_label = "comic-dot" if dither == "comic" else "Floyd–Steinberg"
        message = f"Captured {shot_label} ({source}, {style_label}) & rendered layout.{upload_note}"

        # Upload in parallel with print — QR URL is already known (expected_url).
        self._upload_guest_assets_async(session_id, main_photo, layout_color_path)

        t2 = time.perf_counter()
        try:
            self.printer.print_image(
                layout_path,
                download_url=download_qr,
                register_url=register_qr,
            )
            printed = True
            message = (
                f"Captured {shot_label} ({source}, {style_label}), printed successfully."
                f"{upload_note}"
            )
            logger.info("Print done in %.2fs (%s)", time.perf_counter() - t2, session_id)
        except PrinterError as exc:
            message = f"Captured & rendered, but print failed: {exc}.{upload_note}"
            logger.exception("Print failed for %s", session_id)

        logger.info(
            "Session %s total %.2fs (print-first; Cloudinary in background)",
            session_id,
            time.perf_counter() - t0,
        )

        result = SessionResult(
            photo_id=session_id,
            faculty=request.faculty or "",
            source_path=main_photo,
            layout_path=layout_path,
            layout_color_path=layout_color_path,
            qr_url=download_qr,
            printed=printed,
            message=message,
            cloudinary_url=cloudinary_layout_url,
            cloudinary_photo_url=cloudinary_photo_url,
            cloudinary_layout_url=cloudinary_layout_url,
            frame_paths=frame_paths,
        )
        self._remember_print(result, camera_source=source, dither_style=dither)
        return result

    def _capture_burst(
        self,
        session_id: str,
        camera_source: Optional[CameraSource] = None,
    ) -> list[Path]:
        frames: list[Path] = []
        for i in range(1, self.burst_count + 1):
            frame_id = f"{session_id}_f{i}"
            logger.info("Burst %s/%s — capturing %s", i, self.burst_count, frame_id)
            capture = self.camera.capture_photo(photo_id=frame_id, source=camera_source)
            archived = self.storage.archive_frame(capture.local_path, session_id, i)
            frames.append(archived)
            if i < self.burst_count and self.burst_interval_sec > 0:
                logger.info("Waiting %.1fs before next shot", self.burst_interval_sec)
                time.sleep(self.burst_interval_sec)
        return frames

    def reprint(
        self,
        photo_id: str,
        faculty: str = "",
        qr_base_url: str = "",
        dither_style: str = "floyd",
        copies: int = 1,
    ) -> SessionResult:
        frames = self.storage.get_session_frames(photo_id)
        if not frames:
            source = self.storage.get_photo(photo_id)
            if source is None:
                raise FileNotFoundError(f"Photo not found: id={photo_id}")
            frames = [source]

        layout_color_path = self.layout.render_layout_color_to_path(
            photo_paths=frames,
            qr_url="",
            photo_id=photo_id,
        )
        main_photo = self.storage.get_photo(photo_id) or frames[0]
        download_qr, _ = self._download_qr_url(qr_base_url, photo_id)
        cloudinary_photo_url, cloudinary_layout_url = self._expected_cloudinary_urls(photo_id)
        if cloudinary_layout_url:
            download_qr = cloudinary_layout_url

        dither = dither_style if dither_style in ("comic", "floyd") else "floyd"
        layout_path = self.layout.render_to_path(
            photo_paths=frames,
            qr_url=download_qr,
            photo_id=photo_id,
            dither_style=dither,  # type: ignore[arg-type]
        )

        register_qr = (self.layout.register_qr_url or "").strip()
        copies = max(1, min(20, int(copies or 1)))
        self._upload_guest_assets_async(photo_id, main_photo, layout_color_path)
        for i in range(copies):
            self.printer.print_image(
                layout_path,
                download_url=download_qr,
                register_url=register_qr,
            )
            if i + 1 < copies:
                logger.info("Reprint copy %s/%s done", i + 1, copies)

        copies_note = f" ×{copies}" if copies > 1 else ""
        result = SessionResult(
            photo_id=photo_id,
            faculty=faculty or "",
            source_path=main_photo,
            layout_path=layout_path,
            layout_color_path=layout_color_path,
            qr_url=download_qr,
            printed=True,
            message=(
                f"Reprint successful{copies_note} "
                f"({'comic-dot' if dither == 'comic' else 'Floyd–Steinberg'})."
            ),
            cloudinary_url=cloudinary_layout_url,
            cloudinary_photo_url=cloudinary_photo_url,
            cloudinary_layout_url=cloudinary_layout_url,
            frame_paths=frames,
        )
        self._remember_print(result, dither_style=dither)
        return result

    def reprint_last(
        self,
        faculty: str = "",
        dither_style: str = "",
        copies: int = 1,
    ) -> SessionResult:
        info = self.last_print_info()
        if not info or not info.get("photo_id"):
            raise FileNotFoundError("No previous print to reprint.")
        use_faculty = (faculty or info.get("faculty") or "").strip()
        use_style = dither_style if dither_style in ("comic", "floyd") else (info.get("dither_style") or "floyd")
        return self.reprint(
            photo_id=info["photo_id"],
            faculty=use_faculty,
            dither_style=str(use_style),
            copies=copies,
        )

    def demo_from_image(
        self,
        image_path: Path,
        faculty: str,
        qr_base_url: str = "",
    ) -> SessionResult:
        """Demo the full pipeline with an existing image instead of the camera."""
        session_id = SessionResult.new_id()
        frames = [self.storage.archive_frame(image_path, session_id, 1)]
        download_path = self.layout.render_photo_color(frames, session_id)
        main_photo = self.storage.archive_photo(download_path, session_id)

        layout_color_path = self.layout.render_layout_color_to_path(
            photo_paths=frames,
            qr_url="",
            photo_id=session_id,
        )
        download_qr, upload_note = self._download_qr_url(qr_base_url, session_id)
        cloudinary_photo_url, cloudinary_layout_url = self._expected_cloudinary_urls(session_id)
        if cloudinary_layout_url:
            download_qr = cloudinary_layout_url

        layout_path = self.layout.render_to_path(
            photo_paths=frames,
            qr_url=download_qr,
            photo_id=session_id,
        )

        register_qr = (self.layout.register_qr_url or "").strip()
        printed = False
        message = f"Demo rendered.{upload_note}"
        self._upload_guest_assets_async(session_id, main_photo, layout_color_path)
        try:
            self.printer.print_image(
                layout_path,
                download_url=download_qr,
                register_url=register_qr,
            )
            printed = True
            message = f"Demo: layout + print successful.{upload_note}"
        except PrinterError as exc:
            message = f"Demo: render OK, print failed: {exc}.{upload_note}"

        result = SessionResult(
            photo_id=session_id,
            faculty=faculty,
            source_path=main_photo,
            layout_path=layout_path,
            layout_color_path=layout_color_path,
            qr_url=download_qr,
            printed=printed,
            message=message,
            cloudinary_url=cloudinary_layout_url,
            cloudinary_photo_url=cloudinary_photo_url,
            cloudinary_layout_url=cloudinary_layout_url,
            frame_paths=frames,
        )
        self._remember_print(result)
        return result

    def _remember_print(
        self,
        result: SessionResult,
        camera_source: Optional[str] = None,
        dither_style: Optional[str] = None,
    ) -> None:
        self._last_print = {
            "photo_id": result.photo_id,
            "faculty": result.faculty,
            "printed": result.printed,
            "layout_url": f"/prints/{result.photo_id}_print.png",
            "layout_color_url": f"/prints/{result.photo_id}_layout.png",
            "photo_url": f"/photos/{result.photo_id}.jpg",
            "source": camera_source,
            "dither_style": dither_style or "floyd",
            "captured_at": result.captured_at.strftime("%Y-%m-%d %H:%M:%S"),
        }

    def _recover_last_print(self) -> None:
        if self._last_print or not self.prints_dir:
            return
        prints = sorted(
            self.prints_dir.glob("*_print.png"),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        for path in prints:
            photo_id = path.name[: -len("_print.png")]
            if not photo_id:
                continue
            frames = self.storage.get_session_frames(photo_id)
            photo = self.storage.get_photo(photo_id)
            if not frames and photo is None:
                continue
            self._last_print = {
                "photo_id": photo_id,
                "faculty": "",
                "printed": True,
                "layout_url": f"/prints/{photo_id}_print.png",
                "photo_url": f"/photos/{photo_id}.jpg",
                "source": None,
                "dither_style": "floyd",
                "captured_at": None,
            }
            return

    def _mode_for(self, source: str) -> CaptureMode:
        return self.webcam_mode if source == "webcam" else self.gphoto_mode

    def _apply_mode(self, mode: CaptureMode) -> None:
        self.burst_count = 1
        self.burst_interval_sec = 0.0
        self.layout.portrait_aspect_w = mode.portrait_aspect_w
        self.layout.portrait_aspect_h = mode.portrait_aspect_h

    def _download_qr_url(self, request_base: str, photo_id: str) -> tuple[str, str]:
        """URL nhúng vào QR DOWNLOAD — trỏ thẳng Cloudinary layout màu (không qua Render)."""
        if self.cloudinary and self.cloudinary.enabled:
            try:
                return (
                    self.cloudinary.expected_url(f"{photo_id}_layout", ext="png"),
                    "",
                )
            except CloudinaryError:
                pass

        if self.public_base_url:
            return f"{self.public_base_url}/d/{photo_id}", ""

        return (
            self._fallback_qr(request_base, photo_id),
            " (Cloudinary not configured — QR uses QR_BASE_URL)",
        )

    def resolve_download_target(self, photo_id: str) -> str | None:
        """Đích redirect cho ``GET /d/{photo_id}`` — layout màu trên Cloudinary hoặc local."""
        if self.cloudinary and self.cloudinary.enabled:
            try:
                return self.cloudinary.expected_url(f"{photo_id}_layout", ext="png")
            except CloudinaryError:
                pass
        assets = self.guest_assets(photo_id)
        if not assets:
            return None
        target = assets.get("cloudinary_layout_url") or assets.get("layout_url")
        return str(target).strip() if target else None

    def _expected_cloudinary_urls(self, photo_id: str) -> tuple[str | None, str | None]:
        """Deterministic guest URLs (valid once background upload finishes)."""
        if not self.cloudinary or not self.cloudinary.enabled:
            return None, None
        try:
            return (
                self.cloudinary.expected_url(f"{photo_id}_photo", ext="jpg"),
                self.cloudinary.expected_url(f"{photo_id}_layout", ext="png"),
            )
        except CloudinaryError:
            return None, None

    def _upload_guest_assets_async(
        self,
        photo_id: str,
        photo_path: Path,
        layout_color_path: Path,
    ) -> None:
        """Fire-and-forget Cloudinary upload so print is never blocked."""
        if not self.cloudinary or not self.cloudinary.enabled:
            return

        def _run() -> None:
            t0 = time.perf_counter()
            _, _, note = self._upload_guest_assets(photo_id, photo_path, layout_color_path)
            logger.info(
                "Background Cloudinary for %s finished in %.2fs%s",
                photo_id,
                time.perf_counter() - t0,
                note,
            )

        threading.Thread(
            target=_run,
            name=f"cloudinary-{photo_id}",
            daemon=True,
        ).start()
        logger.info("Cloudinary upload queued in background for %s", photo_id)

    def _upload_guest_assets(
        self,
        photo_id: str,
        photo_path: Path,
        layout_color_path: Path,
    ) -> tuple[str | None, str | None, str]:
        """Upload portrait màu + layout màu lên Cloudinary. Returns (photo_url, layout_url, note)."""
        if not self.cloudinary or not self.cloudinary.enabled:
            return None, None, " (Cloudinary not configured — photos are local only)"
        photo_asset = f"{photo_id}_photo"
        layout_asset = f"{photo_id}_layout"
        try:
            # Parallel uploads cut wall-clock roughly in half on good networks.
            with ThreadPoolExecutor(max_workers=2) as pool:
                fut_photo = pool.submit(
                    self.cloudinary.upload_photo,
                    photo_path,
                    photo_asset,
                    image_format="jpg",
                )
                fut_layout = pool.submit(
                    self.cloudinary.upload_photo,
                    layout_color_path,
                    layout_asset,
                    image_format="png",
                )
                photo_url = fut_photo.result()
                layout_url = fut_layout.result()
            return photo_url, layout_url, ""
        except CloudinaryError as exc:
            logger.exception("Cloudinary upload failed for %s", photo_id)
            return None, None, f" Cloudinary upload error: {exc}"
        except Exception as exc:  # noqa: BLE001
            logger.exception("Cloudinary upload failed for %s", photo_id)
            return None, None, f" Cloudinary upload error: {exc}"

    def guest_assets(self, photo_id: str) -> dict | None:
        """Resolve download URLs for guest page (Cloudinary preferred, local fallback)."""
        photo_local = self.storage.get_photo(photo_id)
        layout_local = (
            (self.prints_dir / f"{photo_id}_layout.png")
            if self.prints_dir
            else None
        )
        has_layout = layout_local is not None and layout_local.exists()

        cloud_photo: str | None = None
        cloud_layout: str | None = None
        if self.cloudinary and self.cloudinary.enabled:
            try:
                cloud_photo = self.cloudinary.expected_url(f"{photo_id}_photo", ext="jpg")
                cloud_layout = self.cloudinary.expected_url(f"{photo_id}_layout", ext="png")
            except CloudinaryError:
                pass

        if photo_local is None and not has_layout and not cloud_layout:
            return None

        local_photo_url = f"/photos/{photo_id}.jpg"
        local_layout_url = f"/prints/{photo_id}_layout.png"

        photo_url = cloud_photo or (local_photo_url if photo_local else None)
        layout_url = cloud_layout or (local_layout_url if has_layout else None)

        return {
            "photo_id": photo_id,
            "photo_url": photo_url,
            "layout_url": layout_url,
            "photo_url_local": local_photo_url if photo_local else None,
            "layout_url_local": local_layout_url if has_layout else None,
            "cloudinary_photo_url": cloud_photo,
            "cloudinary_layout_url": cloud_layout,
        }

    def _fallback_qr(self, request_base: str, photo_id: str) -> str:
        base = (request_base or self.qr_base_url or "").strip()
        if "{id}" in base:
            return base.replace("{id}", photo_id)
        if base:
            return f"{base.rstrip('/')}/{photo_id}"
        return f"https://res.cloudinary.com/pending/image/upload/{photo_id}_print.png"
