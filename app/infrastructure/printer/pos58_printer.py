"""POS58 thermal printer adapter (python-escpos)."""

from __future__ import annotations

import logging
import subprocess
import time
from pathlib import Path
from typing import Literal, Optional

from PIL import Image

logger = logging.getLogger(__name__)

Backend = Literal["usb", "cups", "file"]

# Wrap cột nặng khi một GS v 0 dài (~1000 dòng) bị mất byte giữa chừng:
# parser vẫn đếm đủ width_bytes/dòng → toàn bộ phần sau lệch pha (đúng như ảnh).
# Cách xử lý: nhiều GS v 0 ngắn (mỗi dải vài chục dòng), mỗi dải = 1 USB write.
# KHÔNG sleep giữa dải → giấy không tạo khoảng trắng (khác banding+pace cũ).
BAND_ROWS = 16  # 16×48B = 768B/dải — vừa một bulk transfer ổn định
USB_WRITE_CHUNK = 4096  # lớn hơn một dải → hầu hết dải gửi 1 write
JOB_SETTLE_SEC = 1.0
USB_JOB_RETRIES = 2

HEAT_DOTS = 7
HEAT_TIME = 70
HEAT_INTERVAL = 4

LEADER_LINE_PX = 4
LEADER_PAD_PX = 2
PRINT_WIDTH_PX = 384

CREDIT_LINE = "developed by @shyn._.nguyen"


class PrinterError(RuntimeError):
    """Raised when the thermal printer cannot complete a job."""


class POS58Printer:
    """
    Send a dithered 1-bit image to a Generic POS58 (58 mm / 384 px).

    Layout (photo + template text + QR) is a pre-rendered raster. After the
    image, only the credit line is printed with the printer's ESC/POS font.

    Backends:
      - ``usb``  : python-escpos Usb (default Vendor 0x0416 / Product 0x5011)
      - ``cups`` : ``lp -d <name>`` via CUPS
      - ``file`` : dry-run — only confirm the raster exists (dev / no hardware)
    """

    def __init__(
        self,
        vendor_id: int = 0x0416,
        product_id: int = 0x5011,
        cups_name: str = "POS58",
        backend: Backend = "usb",
        dry_run_dir: Optional[Path] = None,
        band_pace_sec: float = 0.0,
        heat_dots: int = HEAT_DOTS,
        heat_time: int = HEAT_TIME,
        heat_interval: int = HEAT_INTERVAL,
    ) -> None:
        self.vendor_id = vendor_id
        self.product_id = product_id
        self.cups_name = cups_name
        self.backend: Backend = backend  # type: ignore[assignment]
        self.dry_run_dir = dry_run_dir
        # Giữ param settings — mặc định 0 = không sleep giữa dải (tránh vệt trắng).
        self.band_pace_sec = max(0.0, float(band_pace_sec))
        self.heat_dots = max(1, min(11, int(heat_dots)))
        self.heat_time = max(1, min(255, int(heat_time)))
        self.heat_interval = max(0, min(255, int(heat_interval)))

    def check_connection(self) -> dict:
        if self.backend == "file":
            return {"connected": True, "backend": "file", "note": "Dry-run mode"}
        if self.backend == "cups":
            result = subprocess.run(
                ["lpstat", "-p", self.cups_name],
                capture_output=True,
                text=True,
                check=False,
            )
            ok = result.returncode == 0
            return {
                "connected": ok,
                "backend": "cups",
                "printer": self.cups_name,
                "detail": (result.stdout or result.stderr).strip(),
            }
        try:
            import usb.core

            dev = usb.core.find(idVendor=self.vendor_id, idProduct=self.product_id)
            return {
                "connected": dev is not None,
                "backend": "usb",
                "vendor_id": hex(self.vendor_id),
                "product_id": hex(self.product_id),
            }
        except Exception as exc:  # noqa: BLE001
            return {"connected": False, "backend": "usb", "error": str(exc)}

    def print_image(
        self,
        image: Image.Image | Path,
        *,
        download_url: str = "",
        register_url: str = "",
    ) -> None:
        """Print 1-bit strip (comic-dot / threshold đã xử lý ở layout)."""
        del download_url, register_url
        img = self._prepare_bitmap(image)

        if self.backend == "file":
            self._print_file(img)
        elif self.backend == "cups":
            self._print_cups(img)
        else:
            self._print_usb(img)

    def _prepare_bitmap(self, image: Image.Image | Path) -> Image.Image:
        img = self._as_image(image)
        if img.mode != "1":
            img = img.convert("L").convert("1", dither=Image.Dither.NONE)

        if img.width != PRINT_WIDTH_PX:
            ratio = PRINT_WIDTH_PX / img.width
            img = img.resize(
                (PRINT_WIDTH_PX, max(1, int(img.height * ratio))),
                Image.Resampling.NEAREST,
            )
            img = img.convert("1", dither=Image.Dither.NONE)

        if img.width % 8 != 0:
            pad = 8 - (img.width % 8)
            canvas = Image.new("1", (img.width + pad, img.height), 1)
            canvas.paste(img, (0, 0))
            img = canvas
        return img

    def _print_usb(self, img: Image.Image) -> None:
        try:
            import usb.core
            from escpos.constants import GS
            from escpos.printer import Usb
        except ImportError as exc:
            raise PrinterError("python-escpos chưa được cài.") from exc

        last_error: Exception | None = None
        for attempt in range(1, USB_JOB_RETRIES + 1):
            printer = None
            try:
                printer = self._open_usb_printer(Usb, usb_core=usb.core)
                self._run_usb_job(printer, img, GS)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(
                    "USB print attempt %s/%s failed: %s",
                    attempt,
                    USB_JOB_RETRIES,
                    exc,
                )
                if printer is not None:
                    try:
                        self._clear_usb_halts(printer)
                    except Exception:  # noqa: BLE001
                        pass
                    try:
                        printer.close()
                    except Exception:  # noqa: BLE001
                        pass
                if attempt < USB_JOB_RETRIES and self._is_retryable_usb(exc):
                    time.sleep(0.8 * attempt)
                    continue
                break

        raise PrinterError(f"Lỗi khi in ESC/POS: {last_error}") from last_error

    def _open_usb_printer(self, usb_cls, *, usb_core):
        class _UsbNoReset(usb_cls):
            """POS58 clone trên macOS: bỏ device.reset()."""

            def _configure_usb(self) -> None:
                if not self.device:
                    return
                try:
                    self.device.set_configuration()
                except usb_core.USBError as exc:
                    logger.warning("USB set_configuration: %s", exc)
                for ep in (self.out_ep, self.in_ep):
                    try:
                        self.device.clear_halt(ep)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("USB clear_halt(0x%02x): %s", ep, exc)

            def _raw(self, msg: bytes) -> None:
                """Ghi bulk; ưu tiên 1 write nếu vừa chunk."""
                assert self.device
                view = memoryview(msg)
                total = len(view)
                sent = 0
                while sent < total:
                    piece = view[sent : sent + USB_WRITE_CHUNK]
                    n = self.device.write(self.out_ep, piece, self.timeout)
                    if n is None or n <= 0:
                        raise PrinterError(
                            f"USB write trả về {n} tại offset {sent}/{total}"
                        )
                    sent += int(n)

        try:
            printer = _UsbNoReset(
                self.vendor_id, self.product_id, timeout=30_000, profile="POS-5890"
            )
            printer.open()
            return printer
        except Exception as exc:  # noqa: BLE001
            raise PrinterError(
                f"Không mở được POS58 USB ({hex(self.vendor_id)}:{hex(self.product_id)}): {exc}. "
                "Kiểm tra cáp, quyền USB, hoặc đặt PRINTER_BACKEND=cups."
            ) from exc

    def _run_usb_job(self, printer, img: Image.Image, gs: bytes) -> None:
        # Một ESC @ thôi — nhiều lần dễ tạo khoảng trắng / rác đầu phiếu.
        printer._raw(b"\x1b\x40")
        time.sleep(0.05)
        printer._raw(
            bytes(
                [
                    0x1B,
                    0x37,
                    self.heat_dots,
                    self.heat_time,
                    self.heat_interval,
                ]
            )
        )
        printer._raw(b"\x1b\x61\x00")

        strip = self._stack_leader_and_trailer(img)
        bands = 0
        for y in range(0, strip.height, BAND_ROWS):
            band = strip.crop((0, y, strip.width, min(y + BAND_ROWS, strip.height)))
            self._usb_send_raster(printer, band, gs)
            bands += 1
            # Chỉ pace nếu user chủ động set > 0 (mặc định 0 = liền mạch, không vệt trắng).
            if self.band_pace_sec > 0:
                time.sleep(self.band_pace_sec)

        printer._raw(b"\x1b\x61\x01")
        printer.text(f"\n{CREDIT_LINE}\n")
        printer._raw(b"\x1b\x61\x00")
        printer.text("\n")
        try:
            printer.cut(mode="PART")
        except Exception:  # noqa: BLE001
            printer.cut()
        time.sleep(JOB_SETTLE_SEC)
        logger.info(
            "Printed via USB ESC/POS (%sx%s, %d bands×%d rows, pace=%s, no mid-command chunking)",
            strip.width,
            strip.height,
            bands,
            BAND_ROWS,
            f"{self.band_pace_sec*1000:.0f}ms" if self.band_pace_sec > 0 else "off",
        )
        try:
            printer.close()
        except Exception:  # noqa: BLE001
            pass

    @staticmethod
    def _leader_line_image(width: int) -> Image.Image:
        height = LEADER_PAD_PX + LEADER_LINE_PX + LEADER_PAD_PX
        img = Image.new("1", (width, height), 1)
        black = Image.new("1", (width, LEADER_LINE_PX), 0)
        img.paste(black, (0, LEADER_PAD_PX))
        return img

    @classmethod
    def _stack_leader_and_trailer(cls, img: Image.Image) -> Image.Image:
        """Horizontal sync lines above and below the layout (same thickness)."""
        bar = cls._leader_line_image(img.width)
        body = img.convert("1")
        out = Image.new("1", (img.width, bar.height * 2 + body.height), 1)
        out.paste(bar, (0, 0))
        out.paste(body, (0, bar.height))
        out.paste(bar, (0, bar.height + body.height))
        return out

    @staticmethod
    def _to_escpos_raster(img: Image.Image) -> tuple[int, int, bytes]:
        """Pack mode-1 image → GS v 0 payload.

        PIL mode 1: 0=black, 1=white. ESC/POS raster: bit 1 = black dot.
        MSB = leftmost pixel.
        """
        im = img.convert("1")
        width, height = im.size
        if width % 8 != 0:
            raise PrinterError(f"Raster width must be multiple of 8, got {width}")
        width_bytes = width // 8
        # Invert so black (0) becomes printable 1-bits in packed bytes.
        raw = im.tobytes()
        payload = bytes((~b) & 0xFF for b in raw)
        if len(payload) != width_bytes * height:
            raise PrinterError(
                f"Raster pack lỗi: {len(payload)} != {width_bytes}×{height}"
            )
        return width_bytes, height, payload

    @classmethod
    def _usb_send_raster(cls, printer, band: Image.Image, gs: bytes) -> None:
        width_bytes, height, payload = cls._to_escpos_raster(band)
        header = (
            gs
            + b"v0"
            + bytes((0,))  # m=0 normal
            + bytes(
                (
                    width_bytes & 0xFF,
                    (width_bytes >> 8) & 0xFF,
                    height & 0xFF,
                    (height >> 8) & 0xFF,
                )
            )
        )
        cmd = header + payload
        # Một dải đủ nhỏ → thường 1 USB write, không cắt giữa payload.
        printer._raw(cmd)

    @staticmethod
    def _clear_usb_halts(printer) -> None:
        if not getattr(printer, "device", None):
            return
        for ep in (getattr(printer, "out_ep", None), getattr(printer, "in_ep", None)):
            if ep is None:
                continue
            try:
                printer.device.clear_halt(ep)
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _is_retryable_usb(exc: BaseException) -> bool:
        msg = str(exc).lower()
        keys = (
            "timeout",
            "timed out",
            "input/output",
            "errno 5",
            "errno 60",
            "pipe",
            "busy",
            "overflow",
        )
        return any(k in msg for k in keys)

    def _print_cups(self, img: Image.Image) -> None:
        if not self.dry_run_dir:
            raise PrinterError("dry_run_dir required for CUPS temp file")
        tmp = self.dry_run_dir / "_cups_job.png"
        img.save(tmp)
        result = subprocess.run(
            ["lp", "-d", self.cups_name, "-o", "fit-to-page", str(tmp)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise PrinterError(f"CUPS lp failed: {result.stderr or result.stdout}")
        logger.info("Submitted CUPS job to %s: %s", self.cups_name, result.stdout.strip())

    def _print_file(self, img: Image.Image) -> None:
        if not self.dry_run_dir:
            raise PrinterError("dry_run_dir required for file backend")
        out = self.dry_run_dir / "_last_dry_run.png"
        img.save(out)
        logger.info("Dry-run print saved → %s", out)

    @staticmethod
    def _as_image(image: Image.Image | Path) -> Image.Image:
        if isinstance(image, Path):
            return Image.open(image)
        return image
