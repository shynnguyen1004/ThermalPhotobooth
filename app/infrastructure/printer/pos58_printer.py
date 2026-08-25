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

# Gửi CẢ strip trong 1 lệnh GS v 0; ghi USB theo chunk 512 byte (ổn định hơn full dump).
USB_WRITE_CHUNK = 512
JOB_SETTLE_SEC = 0.55

# ESC 7 — heat (n2 càng cao càng đen; n3 cao hơn → đầu nhiệt kịp nguội, ít ghost dọc).
HEAT_DOTS = 7
HEAT_TIME = 70
HEAT_INTERVAL = 4

# Dòng ngang “mồi” trước layout — giúp sync raster, giảm wrap logo đầu phiếu.
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
        # Giữ param settings cũ — hiện không dùng để chia chunk (in thử full-speed).
        self.usb_chunk_delay_sec = max(0.0, float(band_pace_sec))
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
        del download_url, register_url  # QR đã nằm trong raster template
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

        if self.backend == "file":
            self._print_file(img)
        elif self.backend == "cups":
            self._print_cups(img)
        else:
            self._print_usb(img)

    # ------------------------------------------------------------------

    def _print_usb(self, img: Image.Image) -> None:
        try:
            import usb.core
            from escpos.constants import GS
            from escpos.image import EscposImage
            from escpos.printer import Usb
        except ImportError as exc:
            raise PrinterError("python-escpos chưa được cài.") from exc

        class _UsbNoReset(Usb):
            """POS58 clone trên macOS: bỏ ``device.reset()``; ghi USB theo chunk 512B."""

            def _configure_usb(self) -> None:
                if not self.device:
                    return
                try:
                    self.device.set_configuration()
                except usb.core.USBError as exc:
                    logger.warning("USB set_configuration: %s", exc)
                for ep in (self.out_ep, self.in_ep):
                    try:
                        self.device.clear_halt(ep)
                    except Exception as exc:  # noqa: BLE001
                        logger.debug("USB clear_halt(0x%02x): %s", ep, exc)

            def _raw(self, msg: bytes) -> None:
                """Ghi theo chunk 512 byte — không sleep giữa chunk."""
                assert self.device
                view = memoryview(msg)
                sent = 0
                while sent < len(view):
                    piece = view[sent : sent + USB_WRITE_CHUNK]
                    n = self.device.write(self.out_ep, piece, self.timeout)
                    if n is None or n <= 0:
                        raise PrinterError(
                            f"USB write trả về {n} tại offset {sent}/{len(view)}"
                        )
                    sent += n

        try:
            printer = _UsbNoReset(
                self.vendor_id, self.product_id, timeout=30_000, profile="POS-5890"
            )
            printer.open()
        except Exception as exc:  # noqa: BLE001
            raise PrinterError(
                f"Không mở được POS58 USB ({hex(self.vendor_id)}:{hex(self.product_id)}): {exc}. "
                "Kiểm tra cáp, quyền USB, hoặc đặt PRINTER_BACKEND=cups."
            ) from exc

        try:
            printer._raw(b"\x1b\x40")  # ESC @
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
            printer._raw(b"\x1b\x61\x00")  # left

            leader = self._leader_line_image(img.width)
            self._usb_send_raster(printer, leader, EscposImage, GS)

            # CẢ layout 1 lệnh GS v 0 — USB ghi theo chunk 512B
            self._usb_send_raster(printer, img, EscposImage, GS)

            printer._raw(b"\x1b\x61\x01")  # center
            printer.text(f"\n{CREDIT_LINE}\n")
            printer._raw(b"\x1b\x61\x00")
            trailer = self._leader_line_image(img.width)
            self._usb_send_raster(printer, trailer, EscposImage, GS)
            printer.text("\n")
            try:
                printer.cut(mode="PART")
            except Exception:  # noqa: BLE001
                printer.cut()
            time.sleep(JOB_SETTLE_SEC)
            logger.info(
                "Printed via USB ESC/POS (full raster %sx%s, chunk=%dB, heat=%d/%d/%d)",
                img.width,
                img.height,
                USB_WRITE_CHUNK,
                self.heat_dots,
                self.heat_time,
                self.heat_interval,
            )
        except Exception as exc:  # noqa: BLE001
            raise PrinterError(f"Lỗi khi in ESC/POS: {exc}") from exc
        finally:
            try:
                printer.close()
            except Exception:  # noqa: BLE001
                pass

    @staticmethod
    def _leader_line_image(width: int) -> Image.Image:
        """Ảnh 1-bit: pad trắng + line đen ngang LEADER_LINE_PX."""
        height = LEADER_PAD_PX + LEADER_LINE_PX + LEADER_PAD_PX
        img = Image.new("1", (width, height), 1)
        y0 = LEADER_PAD_PX
        black = Image.new("1", (width, LEADER_LINE_PX), 0)
        img.paste(black, (0, y0))
        return img

    @staticmethod
    def _usb_send_raster(printer, band: Image.Image, escpos_image_cls, gs) -> None:
        esc_im = escpos_image_cls(band.convert("1"))
        if esc_im.width_bytes * 8 != band.width:
            raise PrinterError(
                f"Raster width lệch: image={band.width}px nhưng "
                f"width_bytes={esc_im.width_bytes} ({esc_im.width_bytes * 8}px)"
            )
        payload = esc_im.to_raster_format()
        header = (
            gs
            + b"v0"
            + bytes((0,))
            + bytes(
                (
                    esc_im.width_bytes & 0xFF,
                    (esc_im.width_bytes >> 8) & 0xFF,
                    esc_im.height & 0xFF,
                    (esc_im.height >> 8) & 0xFF,
                )
            )
        )
        printer._raw(header + payload)

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
