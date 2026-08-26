"""FastAPI routes & app factory."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.concurrency import iterate_in_threadpool

from app.application.layout_service import LayoutRenderer
from app.application.photobooth_service import CaptureMode, PhotoboothService
from app.domain.models import PrintJobRequest
from app.infrastructure.camera.auto_camera import AutoCamera
from app.infrastructure.camera.gphoto_camera import CameraError, GPhotoCamera
from app.infrastructure.camera.liveview import BOUNDARY, LiveViewError, live_view
from app.infrastructure.camera.webcam_camera import WebcamCamera
from app.infrastructure.printer.pos58_printer import POS58Printer
from app.infrastructure.storage.cloudinary_storage import CloudinaryStorage
from app.infrastructure.storage.file_storage import FileStorage
from config.settings import Settings, settings

logger = logging.getLogger(__name__)

PRESENTATION_DIR = Path(__file__).resolve().parent
ROOT_DIR = PRESENTATION_DIR.parent.parent
FRONTEND_DIST = ROOT_DIR / "frontend" / "dist"
TEMPLATES = Jinja2Templates(directory=str(PRESENTATION_DIR / "templates"))


def _session_payload(result) -> dict:
    return {
        "ok": True,
        "photo_id": result.photo_id,
        "printed": result.printed,
        "qr_url": result.qr_url,
        "cloudinary_url": result.cloudinary_url,
        "cloudinary_photo_url": result.cloudinary_photo_url,
        "cloudinary_layout_url": result.cloudinary_layout_url,
        "layout_url": f"/prints/{result.photo_id}_print.png",
        "layout_color_url": f"/prints/{result.photo_id}_layout.png",
        "photo_url": f"/photos/{result.photo_id}.jpg",
        "frame_urls": [
            f"/photos/{result.photo_id}_{i}.jpg"
            for i in range(1, len(result.frame_paths) + 1)
        ],
        "burst_count": len(result.frame_paths),
        "message": result.message,
        "captured_at": result.captured_at.strftime("%Y-%m-%d %H:%M:%S"),
    }


def build_service(cfg: Settings | None = None) -> PhotoboothService:
    cfg = cfg or settings
    cfg.ensure_dirs()

    backend = (cfg.camera_backend or "auto").strip().lower()
    if backend not in ("auto", "gphoto", "webcam"):
        backend = "auto"

    gphoto = GPhotoCamera(
        temp_dir=cfg.temp_dir,
        model_hint=cfg.camera_model_hint,
        timeout_sec=cfg.capture_timeout_sec,
    )
    webcam = WebcamCamera(
        temp_dir=cfg.temp_dir,
        device_index=cfg.webcam_device_index,
        aspect_w=cfg.webcam_portrait_aspect_w,
        aspect_h=cfg.webcam_portrait_aspect_h,
    )
    camera = AutoCamera(
        gphoto=gphoto,
        webcam=webcam,
        backend=backend,  # type: ignore[arg-type]
    )

    layout = LayoutRenderer(
        template_path=cfg.print_template_path,
        template_colored_path=cfg.print_template_colored_path,
        register_qr_url=cfg.register_qr_url,
        output_dir=cfg.prints_dir,
        portrait_aspect_w=cfg.portrait_aspect_w,
        portrait_aspect_h=cfg.portrait_aspect_h,
        remove_background=cfg.remove_background,
        frame_border_path=cfg.frame_border_path,
    )
    printer = POS58Printer(
        vendor_id=cfg.printer_vendor_id,
        product_id=cfg.printer_product_id,
        cups_name=cfg.printer_cups_name,
        backend=cfg.printer_backend,  # type: ignore[arg-type]
        dry_run_dir=cfg.prints_dir,
        band_pace_sec=cfg.printer_band_pace_sec,
        heat_dots=cfg.printer_heat_dots,
        heat_time=cfg.printer_heat_time,
        heat_interval=cfg.printer_heat_interval,
    )
    storage = FileStorage(photos_dir=cfg.photos_dir)
    cloudinary = CloudinaryStorage(
        cloud_name=cfg.cloudinary_cloud_name,
        api_key=cfg.cloudinary_api_key,
        api_secret=cfg.cloudinary_api_secret,
        folder=cfg.cloudinary_folder,
    )
    return PhotoboothService(
        camera=camera,
        layout=layout,
        printer=printer,
        storage=storage,
        cloudinary=cloudinary,
        qr_base_url=cfg.qr_base_url,
        public_base_url=cfg.public_base_url,
        prints_dir=cfg.prints_dir,
        gphoto_mode=CaptureMode(
            burst_count=1,
            burst_interval_sec=0.0,
            portrait_aspect_w=cfg.portrait_aspect_w,
            portrait_aspect_h=cfg.portrait_aspect_h,
        ),
        webcam_mode=CaptureMode(
            burst_count=1,
            burst_interval_sec=0.0,
            portrait_aspect_w=cfg.webcam_portrait_aspect_w,
            portrait_aspect_h=cfg.webcam_portrait_aspect_h,
        ),
    )


def create_app(cfg: Settings | None = None, service: Optional[PhotoboothService] = None) -> FastAPI:
    cfg = cfg or settings
    booth = service or build_service(cfg)

    app = FastAPI(title="UTS Photobooth", version="1.0.0")
    app.state.service = booth
    app.state.settings = cfg

    static_dir = PRESENTATION_DIR / "static"
    static_dir.mkdir(exist_ok=True)
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    spa_enabled = (FRONTEND_DIST / "index.html").is_file()
    if spa_enabled:
        assets_dir = FRONTEND_DIST / "assets"
        img_dir = FRONTEND_DIST / "img"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="spa_assets")
        if img_dir.is_dir():
            app.mount("/img", StaticFiles(directory=str(img_dir)), name="spa_img")
        logger.info("Serving React SPA from %s", FRONTEND_DIST)

    @app.get("/api/config")
    async def api_config() -> JSONResponse:
        return JSONResponse(
            {
                "org_name": cfg.org_name,
                "cloudinary_enabled": cfg.cloudinary_enabled,
                "cloudinary_folder": cfg.cloudinary_folder,
                "burst_count": cfg.burst_count,
                "burst_interval_sec": cfg.burst_interval_sec,
            }
        )

    def _spa_index() -> FileResponse:
        return FileResponse(
            FRONTEND_DIST / "index.html",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
            },
        )

    @app.get("/")
    async def index(request: Request):
        if spa_enabled:
            return _spa_index()
        return TEMPLATES.TemplateResponse(
            "index.html",
            {
                "request": request,
                "org_name": cfg.org_name,
                "cloudinary_enabled": cfg.cloudinary_enabled,
                "cloudinary_folder": cfg.cloudinary_folder,
                "burst_count": cfg.burst_count,
                "burst_interval_sec": cfg.burst_interval_sec,
            },
        )

    @app.get("/api/status")
    async def api_status() -> JSONResponse:
        liveview_status = live_view.status()
        # IMPORTANT: do not probe Sony PTP while USB live view is active.
        # Re-probing can steal the session from `gphoto2 --capture-movie`
        # and cause preview to drop after a few seconds.
        if liveview_status.get("active"):
            webcam_status = {"connected": False, "source": "webcam"}
            webcam_obj = getattr(booth.camera, "webcam", None)
            if webcam_obj is not None:
                try:
                    webcam_status = webcam_obj.check_connection()
                except Exception as exc:  # noqa: BLE001
                    webcam_status = {"connected": False, "source": "webcam", "error": str(exc)}

            payload = {
                "camera": {
                    "connected": True,
                    "source": "gphoto",
                    "note": "Sony USB live view active",
                },
                "cameras": {
                    "gphoto": {
                        "connected": True,
                        "source": "gphoto",
                        "note": "Sony USB live view active",
                    },
                    "webcam": webcam_status,
                },
                "printer": booth.printer.check_connection(),
                "cloudinary": booth.cloudinary.status() if booth.cloudinary else {"enabled": False},
                "last_print": booth.last_print_info(),
                "liveview": liveview_status,
            }
            return JSONResponse(payload)

        payload = booth.status()
        payload["liveview"] = liveview_status
        return JSONResponse(payload)

    @app.get("/api/liveview")
    async def api_liveview():
        """MJPEG stream from Sony USB (gphoto2 --capture-movie)."""
        try:
            # Probe start early so HTTP errors are JSON, not a hung stream
            gen = live_view.iter_multipart()
            # Force first ensure by peeking — consume is lazy, so call status after start attempt
            first = next(gen)
        except LiveViewError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except StopIteration as exc:
            raise HTTPException(status_code=503, detail="Live view has no frames") from exc

        def stream():
            yield first
            yield from gen

        return StreamingResponse(
            iterate_in_threadpool(stream()),
            media_type=f"multipart/x-mixed-replace; boundary={BOUNDARY.decode()}",
            headers={
                "Cache-Control": "no-cache, no-store, must-revalidate",
                "Pragma": "no-cache",
                "Connection": "close",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/liveview/stop")
    async def api_liveview_stop() -> JSONResponse:
        live_view.stop()
        return JSONResponse({"ok": True, **live_view.status()})

    @app.post("/api/capture-print")
    async def api_capture_print(
        source: str = Form("auto"),
        dither_style: str = Form("floyd"),
        faculty: str = Form(""),
    ) -> JSONResponse:
        src = (source or "auto").strip().lower()
        if src not in ("auto", "gphoto", "webcam", "camera"):
            raise HTTPException(
                status_code=400,
                detail="source must be auto | webcam | gphoto (camera).",
            )
        style = (dither_style or "floyd").strip().lower()
        if style not in ("comic", "floyd"):
            raise HTTPException(
                status_code=400,
                detail="dither_style must be comic | floyd.",
            )
        camera_source = None if src == "auto" else ("gphoto" if src in ("gphoto", "camera") else "webcam")
        # Live view giữ USB PTP — phải tắt trước khi chụp Sony / auto
        if camera_source in (None, "gphoto"):
            live_view.stop()
        try:
            result = booth.capture_and_print(
                PrintJobRequest(faculty=faculty.strip(), dither_style=style),
                camera_source=camera_source,  # type: ignore[arg-type]
            )
        except CameraError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("capture-print failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc

        return JSONResponse(_session_payload(result))

    @app.get("/api/recent-prints")
    async def api_recent_prints(limit: int = 6) -> JSONResponse:
        return JSONResponse({"items": booth.recent_prints(limit=limit)})

    @app.post("/api/reprint")
    async def api_reprint(
        photo_id: str = Form(...),
        dither_style: str = Form(""),
        faculty: str = Form(""),
        copies: int = Form(1),
    ) -> JSONResponse:
        pid = (photo_id or "").strip()
        if not pid:
            raise HTTPException(status_code=400, detail="photo_id is required.")
        style = (dither_style or "").strip().lower()
        if style and style not in ("comic", "floyd"):
            raise HTTPException(
                status_code=400,
                detail="dither_style must be comic | floyd.",
            )
        n = max(1, min(20, int(copies or 1)))
        try:
            result = booth.reprint(
                photo_id=pid,
                faculty=faculty.strip(),
                dither_style=style or "floyd",
                copies=n,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("reprint failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return JSONResponse(_session_payload(result))

    @app.post("/api/reprint-last")
    async def api_reprint_last(
        dither_style: str = Form(""),
        faculty: str = Form(""),
        copies: int = Form(1),
    ) -> JSONResponse:
        style = (dither_style or "").strip().lower()
        if style and style not in ("comic", "floyd"):
            raise HTTPException(
                status_code=400,
                detail="dither_style must be comic | floyd.",
            )
        n = max(1, min(20, int(copies or 1)))
        try:
            result = booth.reprint_last(
                faculty=faculty.strip(),
                dither_style=style,
                copies=n,
            )
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("reprint-last failed")
            raise HTTPException(status_code=500, detail=str(exc)) from exc
        return JSONResponse(_session_payload(result))

    @app.get("/d/{photo_id}")
    async def download_redirect(photo_id: str) -> RedirectResponse:
        target = booth.resolve_download_target(photo_id)
        if not target:
            raise HTTPException(status_code=404, detail="Photo not found")
        return RedirectResponse(url=target, status_code=302)

    @app.get("/api/photo/{photo_id}")
    async def api_photo_assets(photo_id: str) -> JSONResponse:
        assets = booth.guest_assets(photo_id)
        if assets is None:
            raise HTTPException(status_code=404, detail="Photo not found")
        return JSONResponse(assets)

    @app.get("/photos/{photo_id}.jpg")
    async def get_photo(photo_id: str) -> FileResponse:
        path = booth.storage.get_photo(photo_id)
        if path is None:
            raise HTTPException(status_code=404, detail="Photo not found")
        return FileResponse(path, media_type="image/jpeg")

    @app.get("/prints/{filename}")
    async def get_print(filename: str) -> FileResponse:
        path = cfg.prints_dir / filename
        if not path.exists() or not path.is_file():
            raise HTTPException(status_code=404, detail="Print not found")
        return FileResponse(path, media_type="image/png")

    @app.get("/photo/{photo_id}")
    async def public_photo_page(photo_id: str, request: Request) -> HTMLResponse:
        if booth.guest_assets(photo_id) is None:
            raise HTTPException(status_code=404, detail="Photo not found")
        if spa_enabled:
            return _spa_index()
        assets = booth.guest_assets(photo_id) or {}
        return TEMPLATES.TemplateResponse(
            "photo.html",
            {
                "request": request,
                "photo_id": photo_id,
                "photo_url": assets.get("photo_url") or f"/photos/{photo_id}.jpg",
                "layout_url": assets.get("layout_url") or f"/prints/{photo_id}_layout.png",
                "org_name": cfg.org_name,
            },
        )

    return app
