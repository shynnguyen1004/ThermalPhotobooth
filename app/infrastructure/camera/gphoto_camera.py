"""Sony A7S2 capture via libgphoto2 (python-gphoto2) or gphoto2 CLI on macOS."""

from __future__ import annotations

import logging
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from app.domain.models import CaptureResult, SessionResult

logger = logging.getLogger(__name__)


class CameraError(RuntimeError):
    """Raised when the camera cannot be used."""


class GPhotoCamera:
    """Capture JPEG stills from a USB-tethered Sony body (A7S II / A7S2)."""

    def __init__(self, temp_dir: Path, model_hint: str = "Sony", timeout_sec: int = 30) -> None:
        self.temp_dir = temp_dir
        self.model_hint = model_hint
        self.timeout_sec = timeout_sec
        self.temp_dir.mkdir(parents=True, exist_ok=True)
        self._jpeg_configured = False
        self.ensure_macos_hotplug_disabled()

    @property
    def jpeg_configured(self) -> bool:
        return self._jpeg_configured

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def prepare_jpeg_quality(self, force: bool = False) -> bool:
        """Set Image Quality to JPEG once so still capture skips this step.

        Safe to call when the camera is free (not in live-view / still capture).
        Returns True when JPEG quality is already configured (or just set).
        """
        if self._jpeg_configured and not force:
            return True

        self.release_macos_ptp_claim()
        time.sleep(0.15)

        if _has_python_gphoto2():
            try:
                import gphoto2 as gp

                context = gp.Context()
                camera = gp.Camera()
                try:
                    camera.init(context)
                    if self._prefer_jpeg(camera, context, gp):
                        self._jpeg_configured = True
                        logger.info("JPEG quality prepared once (binding) — skipped on later captures")
                        return True
                finally:
                    try:
                        camera.exit(context)
                    except Exception:  # noqa: BLE001
                        pass
            except Exception as exc:  # noqa: BLE001
                logger.debug("prepare_jpeg_quality binding failed: %s", exc)

        if self._prepare_jpeg_via_cli():
            self._jpeg_configured = True
            logger.info("JPEG quality prepared once (CLI) — skipped on later captures")
            return True

        return False

    def check_connection(self) -> dict:
        """Return camera status. Auto-frees PTPCamera / Imaging Edge if needed."""
        self.release_macos_ptp_claim()
        detected = self._auto_detect()
        if not detected:
            return {
                "connected": False,
                "error": "Không thấy máy ảnh. Cắm USB, USB Connection = PC Remote.",
            }

        # auto-detect alone is not enough — try a real PTP open
        claim_ok, claim_err = self._probe_ptp_session()
        return {
            "connected": claim_ok,
            "detected": True,
            "model": detected["model"],
            "port": detected.get("port"),
            "backend": detected.get("backend"),
            "matches_hint": self.model_hint.lower() in detected["model"].lower()
            or "sony" in detected["model"].lower(),
            "claim_ok": claim_ok,
            "error": None
            if claim_ok
            else (
                claim_err
                or "macOS đang giữ USB (kernel driver). "
                "Tắt Imaging Edge, rút/cắm lại cáp, rồi thử lại."
            ),
        }

    def capture_photo(self, photo_id: Optional[str] = None) -> CaptureResult:
        """Trigger shutter, download JPEG to temp_dir, return CaptureResult."""
        photo_id = photo_id or SessionResult.new_id()
        dest = self.temp_dir / f"{photo_id}.jpg"
        last_error: Optional[Exception] = None

        for attempt in range(1, 4):
            self.release_macos_ptp_claim()
            time.sleep(0.25 * attempt)
            try:
                if _has_python_gphoto2():
                    try:
                        return self._capture_via_binding(photo_id, dest)
                    except CameraError as exc:
                        logger.warning("binding attempt %s failed: %s", attempt, exc)
                        last_error = exc
                return self._capture_via_cli(photo_id, dest)
            except CameraError as exc:
                last_error = exc
                logger.warning("capture attempt %s failed: %s", attempt, exc)
                if not _is_retryable(str(exc)):
                    break

        raise CameraError(
            f"{last_error}. Gợi ý: tắt Imaging Edge Desktop + Remote, "
            "rút USB → tắt/bật máy ảnh → cắm thẳng vào Mac (không qua hub), "
            "Allow accessory nếu macOS hỏi, rồi bấm CHỤP lại."
        )

    # ------------------------------------------------------------------
    # Detection / probe
    # ------------------------------------------------------------------

    def _auto_detect(self) -> Optional[dict]:
        if _has_python_gphoto2():
            try:
                import gphoto2 as gp

                cameras = gp.Camera.autodetect()
                if cameras:
                    model, port = cameras[0]
                    return {"model": model, "port": port, "backend": "python-gphoto2"}
            except Exception as exc:  # noqa: BLE001
                logger.debug("autodetect binding failed: %s", exc)

        gphoto2_bin = _which("gphoto2")
        if not gphoto2_bin:
            return None
        result = subprocess.run(
            [gphoto2_bin, "--auto-detect"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        output = (result.stdout or "") + (result.stderr or "")
        for ln in output.splitlines():
            if "usb:" in ln.lower():
                model = ln.split("usb:")[0].strip()
                port = "usb:" + ln.split("usb:", 1)[1].strip().split()[0]
                return {"model": model, "port": port, "backend": "gphoto2-cli"}
        return None

    def _probe_ptp_session(self) -> tuple[bool, Optional[str]]:
        """Return (ok, error_message)."""
        if _has_python_gphoto2():
            import gphoto2 as gp

            context = gp.Context()
            camera = gp.Camera()
            try:
                camera.init(context)
                camera.exit(context)
                return True, None
            except gp.GPhoto2Error as exc:
                return False, f"PTP init lỗi ({exc.code}): {exc}"

        gphoto2_bin = _which("gphoto2")
        if not gphoto2_bin:
            return False, "Chưa có gphoto2 CLI"
        result = subprocess.run(
            [gphoto2_bin, "--summary"],
            capture_output=True,
            text=True,
            check=False,
            timeout=15,
        )
        err = (result.stderr or result.stdout or "").strip()
        if result.returncode == 0 and "Manufacturer" in (result.stdout or ""):
            return True, None
        return False, err.splitlines()[-1] if err else "PTP summary failed"

    # ------------------------------------------------------------------
    # python-gphoto2 path
    # ------------------------------------------------------------------

    def _capture_via_binding(self, photo_id: str, dest: Path) -> CaptureResult:
        import gphoto2 as gp

        from app.infrastructure.storage.file_storage import discard_raw_files, pick_jpeg

        context = gp.Context()
        camera = gp.Camera()
        work = self.temp_dir / f"_capture_{photo_id}"
        work.mkdir(parents=True, exist_ok=True)
        for old in work.glob("*"):
            old.unlink(missing_ok=True)

        try:
            camera.init(context)
            logger.info("Camera initialized (binding) — capturing %s", photo_id)
            if not self._jpeg_configured:
                if self._prefer_jpeg(camera, context, gp):
                    self._jpeg_configured = True
            else:
                logger.debug("Skip imagequality — already prepared")

            file_path = camera.capture(gp.GP_CAPTURE_IMAGE, context)
            # Sony RAW+JPEG may emit multiple files — pull the capture event path,
            # then also scan for a JPEG sibling if capture pointed at RAW.
            paths = [(file_path.folder, file_path.name)]
            # Drain a couple of file-added events (Sony often queues JPEG after RAW)
            for _ in range(8):
                try:
                    ev_type, ev_data = camera.wait_for_event(200, context)
                except gp.GPhoto2Error:
                    break
                if ev_type == gp.GP_EVENT_TIMEOUT:
                    break
                if ev_type == gp.GP_EVENT_FILE_ADDED and ev_data is not None:
                    paths.append((ev_data.folder, ev_data.name))

            seen: set[tuple[str, str]] = set()
            for folder, name in paths:
                key = (folder, name)
                if key in seen:
                    continue
                seen.add(key)
                camera_file = gp.CameraFile()
                camera.file_get(folder, name, gp.GP_FILE_TYPE_NORMAL, camera_file, context)
                target = work / name
                camera_file.save(str(target))
                try:
                    camera.file_delete(folder, name, context)
                except gp.GPhoto2Error:
                    pass

            discard_raw_files(work)
            jpeg = pick_jpeg(work)
            if jpeg is None:
                raise CameraError(
                    "Không có JPEG sau khi chụp (chỉ thấy RAW?). "
                    "Trên A7S2 đặt Image Quality = Fine/Standard (tắt RAW+JPEG)."
                )
            shutil.move(str(jpeg), str(dest))
            discard_raw_files(work)
            for leftover in work.glob("*"):
                leftover.unlink(missing_ok=True)
            try:
                work.rmdir()
            except OSError:
                pass

            if not dest.exists() or dest.stat().st_size == 0:
                raise CameraError("File JPEG tải về trống hoặc không tồn tại.")

            return CaptureResult(
                photo_id=photo_id,
                local_path=dest,
                captured_at=datetime.now(),
            )
        except gp.GPhoto2Error as exc:
            raise CameraError(f"Capture thất bại (gphoto2 {exc.code}): {exc}") from exc
        finally:
            try:
                camera.exit(context)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------
    # gphoto2 CLI fallback
    # ------------------------------------------------------------------

    def _capture_via_cli(self, photo_id: str, dest: Path) -> CaptureResult:
        gphoto2_bin = _require_gphoto2_cli()
        work = self.temp_dir / f"_capture_{photo_id}"
        work.mkdir(parents=True, exist_ok=True)

        for old in work.glob("*"):
            old.unlink(missing_ok=True)

        detected = self._auto_detect()
        port = detected.get("port") if detected else None

        cmd = [
            gphoto2_bin,
            "--capture-image-and-download",
            "--filename",
            str(work / "%f.%C"),
            "--force-overwrite",
        ]
        if port:
            cmd[1:1] = ["--port", port]

        logger.info("Capturing via CLI: %s", " ".join(cmd))
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            timeout=self.timeout_sec,
            cwd=str(work),
        )
        if result.returncode != 0:
            err = (result.stderr or result.stdout or "").strip()
            # Keep message short for UI
            compact = _compact_gphoto_error(err)
            raise CameraError(f"gphoto2 capture thất bại: {compact}")

        from app.infrastructure.storage.file_storage import discard_raw_files, pick_jpeg

        discarded = discard_raw_files(work)
        if discarded:
            logger.info("Discarded %s RAW sidecar(s) from capture %s", discarded, photo_id)

        jpeg = pick_jpeg(work)
        if jpeg is None:
            raise CameraError(
                "Không có JPEG sau khi chụp. "
                "Trên A7S2 đặt Image Quality = Fine/Standard (tắt RAW+JPEG)."
            )

        shutil.move(str(jpeg), str(dest))
        discard_raw_files(work)
        for leftover in work.glob("*"):
            leftover.unlink(missing_ok=True)
        try:
            work.rmdir()
        except OSError:
            pass

        return CaptureResult(
            photo_id=photo_id,
            local_path=dest,
            captured_at=datetime.now(),
        )

    # ------------------------------------------------------------------
    # macOS PTP / Camera daemon handling
    # ------------------------------------------------------------------

    @staticmethod
    def ensure_macos_hotplug_disabled() -> None:
        """Stop macOS Image Capture from auto-claiming PTP cameras on plug-in."""
        subprocess.run(
            [
                "defaults",
                "-currentHost",
                "write",
                "com.apple.ImageCapture",
                "disableHotPlug",
                "-bool",
                "YES",
            ],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

    @staticmethod
    def release_macos_ptp_claim() -> None:
        """
        Free USB PTP from macOS Image Capture + Sony Imaging Edge so libgphoto2
        can claim the Sony body.
        """
        GPhotoCamera.ensure_macos_hotplug_disabled()

        for pattern in (
            "PTPCamera",
            "ptpcamera",
            "Imaging Edge Desktop",
            "Remote",
            "Viewer",
            "Image Capture",
        ):
            subprocess.run(
                ["killall", "-9", pattern],
                check=False,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        subprocess.run(
            ["pkill", "-9", "-f", "PTPCamera"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["pkill", "-9", "-f", "Imaging Edge"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        subprocess.run(
            ["pkill", "-9", "-f", "com.sony.ImagingEdge"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        # Image Capture daemon — restarts automatically but briefly releases USB
        subprocess.run(
            ["killall", "-9", "icdd"],
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        time.sleep(0.35)
        logger.debug("Released macOS/Sony PTP claim (if any)")

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _prefer_jpeg(self, camera, context, gp) -> bool:
        """Force JPEG-only quality when the camera exposes imagequality.

        Returns True if a JPEG (non-RAW) quality value was applied successfully.
        """
        applied = False
        try:
            config = camera.get_config(context)
            try:
                child = gp.check_result(gp.gp_widget_get_child_by_name(config, "imagequality"))
            except gp.GPhoto2Error:
                child = None
            if child is not None:
                # Prefer pure JPEG labels; avoid anything containing RAW
                choices: list[str] = []
                try:
                    count = child.count_choices()
                    choices = [child.get_choice(i) for i in range(count)]
                except Exception:  # noqa: BLE001
                    choices = []
                preferred = [
                    c
                    for c in choices
                    if "raw" not in c.lower()
                    and any(k in c.lower() for k in ("fine", "extra", "standard", "normal", "jpeg", "jpg"))
                ]
                fallback = [c for c in choices if "raw" not in c.lower()]
                for choice in preferred + fallback + ["Fine", "Extra Fine", "Standard", "JPEG"]:
                    try:
                        child.set_value(choice)
                        camera.set_config(config, context)
                        logger.info("Set imagequality → %s", choice)
                        applied = True
                        break
                    except gp.GPhoto2Error:
                        continue

            try:
                target = gp.check_result(gp.gp_widget_get_child_by_name(config, "capturetarget"))
            except gp.GPhoto2Error:
                target = None
            if target is not None:
                for choice in ("Memory card", "Card", "SDRAM", "Internal RAM"):
                    try:
                        target.set_value(choice)
                        camera.set_config(config, context)
                        break
                    except gp.GPhoto2Error:
                        continue
        except gp.GPhoto2Error as exc:
            logger.debug("Could not tune camera config: %s", exc)
        return applied

    def _prepare_jpeg_via_cli(self) -> bool:
        gphoto2_bin = _which("gphoto2")
        if not gphoto2_bin:
            return False
        detected = self._auto_detect()
        port = detected.get("port") if detected else None
        for value in ("Standard", "Fine", "Extra Fine", "JPEG", "Normal"):
            cmd = [gphoto2_bin, "--set-config", f"imagequality={value}"]
            if port:
                cmd[1:1] = ["--port", port]
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=12,
            )
            if result.returncode == 0:
                logger.info("Set imagequality → %s (CLI)", value)
                return True
        return False


def _which(binary: str) -> Optional[str]:
    from shutil import which

    return which(binary)


def _has_python_gphoto2() -> bool:
    try:
        import gphoto2  # noqa: F401

        return True
    except ImportError:
        return False


def _require_gphoto2_cli() -> str:
    path = _which("gphoto2")
    if not path:
        raise CameraError(
            "Chưa có gphoto2. Cài: brew install gphoto2 libgphoto2 "
            "rồi (tuỳ chọn) pip install gphoto2"
        )
    return path


def _is_retryable(message: str) -> bool:
    keys = (
        "claim",
        "busy",
        "ptp",
        "kernel driver",
        "unspecified",
        "i/o problem",
        "detach",
        "-53",
        "-1",
    )
    lower = message.lower()
    return any(k in lower for k in keys)


def _compact_gphoto_error(err: str) -> str:
    for line in err.splitlines():
        low = line.lower()
        if "could not claim" in low or "kernel driver" in low or "ptp" in low:
            return line.strip()
        if line.startswith("*** Error") or "ERROR:" in line:
            continue
    # fallback: last non-empty line
    lines = [ln.strip() for ln in err.splitlines() if ln.strip()]
    return lines[-1] if lines else err[:200]
