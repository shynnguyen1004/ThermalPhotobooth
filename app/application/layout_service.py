"""UTS thermal + Cloudinary layout renderer.

Three assets drive the pipeline:

1. ``assets/uts_frame_border.png`` — RGBA film-strip overlay on the photo.
2. ``assets/uts_upload_layout_template.png`` — color strip (photo + frame) uploaded
   to Cloudinary for guest download.
3. ``assets/uts_print_layout_template.png`` — B&W strip for POS58: dithered photo
   + frame + QR pointing at the Cloudinary color layout URL.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Literal, Optional, Sequence

import qrcode
from app.application.bg_remove import cutout_on_white
from app.infrastructure.url_shortener import shorten_url
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

logger = logging.getLogger(__name__)

DitherStyle = Literal["comic", "floyd"]

# Native template sizes (printer scales print strip → 384 px at send time)
PRINT_SIZE = (409, 1067)
UPLOAD_SIZE = (439, 806)

# Photo / frame placement — frame asset is 409×546
PRINT_PHOTO_BOX = (0, 90, 409, 546)       # x, y, w, h on print template
UPLOAD_PHOTO_BOX = (15, 103, 409, 546)    # centered on wider upload canvas

# Single QR — SCAN TO DOWNLOAD (white band ~848–1028); +10% vs 157
QR_DOWNLOAD_BOX = (118, 852, 173, 173)
QR_QUIET_PX = 2
QR_MIN_MODULE_PX = 3
QR_SIZE_RATIO = 0.92
QR_RENDER_SIZE = int(
    round((min(QR_DOWNLOAD_BOX[2], QR_DOWNLOAD_BOX[3]) - 2 * QR_QUIET_PX) * QR_SIZE_RATIO)
)

DOWNLOAD_SCALE = 3

# Comic-dot (circular halftone) — tuned for ~409 px photo width @ 203 DPI.
HALFTONE_CELL = 5
HALFTONE_SHARPEN = 1.2
SKIN_LIFT_GAMMA = 0.80
SKIN_DENSITY = 0.90
HIGHLIGHT_START = 0.55
HIGHLIGHT_PUSH = 1.5
DOT_COVERAGE_GAMMA = 1.0


class LayoutRenderer:
    """Compose UTS upload (color) and print (1-bit) strips from one capture."""

    def __init__(
        self,
        template_path: Path,
        register_qr_url: str = "",
        output_dir: Optional[Path] = None,
        portrait_aspect_w: int = 3,
        portrait_aspect_h: int = 4,
        remove_background: bool = False,
        frame_border_path: Optional[Path] = None,
        template_colored_path: Optional[Path] = None,
    ) -> None:
        self.register_qr_url = register_qr_url  # kept for API compat; UTS print has no register QR
        self.output_dir = output_dir
        self.portrait_aspect_w = portrait_aspect_w
        self.portrait_aspect_h = portrait_aspect_h
        self.remove_background = remove_background
        self.dither_style: DitherStyle = "floyd"
        if self.output_dir:
            self.output_dir.mkdir(parents=True, exist_ok=True)

        template_path = Path(template_path)
        colored_path = Path(template_colored_path) if template_colored_path else template_path
        self._template = self._load_template(template_path, expected=PRINT_SIZE, label="print")
        self._template_colored_rgb = self._load_template_colored(
            colored_path, expected=UPLOAD_SIZE, label="upload"
        )
        self._frame = self._load_frame(Path(frame_border_path) if frame_border_path else None)
        self._frame_resized: dict[tuple[int, int], Image.Image] = {}

    def render(
        self,
        photo_paths: Path | Sequence[Path],
        qr_url: str,
        photo_id: Optional[str] = None,
        save: bool = True,
        dither_style: Optional[DitherStyle] = None,
    ) -> Image.Image:
        """Compose B&W print template + dithered photo + frame + download QR."""
        style: DitherStyle = dither_style or self.dither_style
        if style not in ("comic", "floyd"):
            style = "floyd"
        paths = self._normalize_paths(photo_paths)
        canvas = self._template.copy()
        x, y, w, h = PRINT_PHOTO_BOX

        photo = paths[0] if paths else None
        photo_block = self._photo_block(photo, (w, h), as_gray=True)
        if style == "floyd":
            photo_block = photo_block.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")
        else:
            photo_block = self._comic_dot(photo_block)
        photo_block = self._apply_frame(photo_block, binary=True)
        canvas.paste(photo_block, (x, y))

        if qr_url.strip():
            self._paste_qr(canvas, qr_url.strip(), QR_DOWNLOAD_BOX, label="download")

        strip = canvas.convert("1", dither=Image.Dither.NONE)
        if save and self.output_dir and photo_id:
            out = self.output_dir / f"{photo_id}_print.png"
            strip.save(out)
            logger.info("Saved print layout → %s (%s)", out, style)
        return strip

    def render_to_path(
        self,
        photo_paths: Path | Sequence[Path],
        qr_url: str,
        photo_id: str,
        dither_style: Optional[DitherStyle] = None,
    ) -> Path:
        if not self.output_dir:
            raise ValueError("output_dir is required for render_to_path")
        self.render(
            photo_paths=photo_paths,
            qr_url=qr_url,
            photo_id=photo_id,
            save=True,
            dither_style=dither_style,
        )
        return self.output_dir / f"{photo_id}_print.png"

    def render_layout_color(
        self,
        photo_paths: Path | Sequence[Path],
        qr_url: str = "",
        photo_id: Optional[str] = None,
        save: bool = True,
    ) -> Image.Image:
        """Color upload strip — photo + frame only (no QR; QR lives on the print)."""
        del qr_url  # upload layout has no QR slots
        paths = self._normalize_paths(photo_paths)
        canvas = self._template_colored_rgb.copy()
        x, y, w, h = UPLOAD_PHOTO_BOX

        photo = paths[0] if paths else None
        photo_block = self._photo_block(photo, (w, h), as_gray=False)
        photo_block = self._apply_frame(photo_block, binary=False)
        canvas.paste(photo_block.convert("RGB"), (x, y))

        if save and self.output_dir and photo_id:
            out = self.output_dir / f"{photo_id}_layout.png"
            canvas.save(out)
            logger.info("Saved color upload layout → %s", out)
        return canvas

    def render_layout_color_to_path(
        self,
        photo_paths: Path | Sequence[Path],
        qr_url: str,
        photo_id: str,
    ) -> Path:
        if not self.output_dir:
            raise ValueError("output_dir is required for render_layout_color_to_path")
        self.render_layout_color(
            photo_paths=photo_paths,
            qr_url=qr_url,
            photo_id=photo_id,
            save=True,
        )
        return self.output_dir / f"{photo_id}_layout.png"

    def render_photo_color(
        self,
        photo_paths: Path | Sequence[Path],
        photo_id: str,
    ) -> Path:
        """Save a color JPEG (framed crop) for local archive / Cloudinary photo asset."""
        if not self.output_dir:
            raise ValueError("output_dir is required")
        paths = self._normalize_paths(photo_paths)
        size = (PRINT_PHOTO_BOX[2] * DOWNLOAD_SCALE, PRINT_PHOTO_BOX[3] * DOWNLOAD_SCALE)
        photo = self._photo_block(paths[0] if paths else None, size, as_gray=False)
        photo = self._apply_frame(photo, binary=False)
        photos_dir = self.output_dir.parent / "photos"
        photos_dir.mkdir(parents=True, exist_ok=True)
        out = photos_dir / f"{photo_id}_full.jpg"
        photo.convert("RGB").save(out, quality=92)
        return out

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_template(
        path: Path,
        *,
        expected: tuple[int, int],
        label: str,
    ) -> Image.Image:
        if not path.exists():
            raise FileNotFoundError(
                f"Không tìm thấy template {label}: {path} "
                f"(cần {expected[0]}x{expected[1]})."
            )
        rgba = Image.open(path).convert("RGBA")
        if rgba.size != expected:
            raise ValueError(
                f"Template {label} {path} phải đúng {expected[0]}x{expected[1]} px "
                f"(hiện là {rgba.size[0]}x{rgba.size[1]})."
            )
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        gray = Image.alpha_composite(white, rgba).convert("L")
        # Floyd–Steinberg giữ tone xám logo/badge sau khi chỉnh sáng trên file nguồn.
        return gray.convert("1", dither=Image.Dither.FLOYDSTEINBERG).convert("L")

    @staticmethod
    def _load_template_colored(
        path: Path,
        *,
        expected: tuple[int, int],
        label: str,
    ) -> Image.Image:
        if not path.exists():
            raise FileNotFoundError(
                f"Không tìm thấy template {label}: {path} "
                f"(cần {expected[0]}x{expected[1]})."
            )
        rgba = Image.open(path).convert("RGBA")
        white = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        rgb = Image.alpha_composite(white, rgba).convert("RGB")
        if rgb.size != expected:
            logger.info(
                "Scaled %s template %s from %sx%s → %sx%s",
                label,
                path,
                rgb.width,
                rgb.height,
                expected[0],
                expected[1],
            )
            rgb = rgb.resize(expected, Image.Resampling.LANCZOS)
        return rgb

    @staticmethod
    def _load_frame(path: Optional[Path]) -> Optional[Image.Image]:
        if path is None:
            return None
        if not path.exists():
            logger.warning("Không tìm thấy frame border: %s — in ảnh không overlay.", path)
            return None
        frame = Image.open(path).convert("RGBA")
        logger.info("Loaded frame border %s (%sx%s)", path, frame.width, frame.height)
        return frame

    def _frame_for_size(self, size: tuple[int, int]) -> Optional[Image.Image]:
        if self._frame is None:
            return None
        cached = self._frame_resized.get(size)
        if cached is None:
            cached = self._frame.resize(size, Image.Resampling.LANCZOS)
            self._frame_resized[size] = cached
        return cached

    def _apply_frame(self, photo: Image.Image, *, binary: bool) -> Image.Image:
        """Composite the film-strip overlay on a fitted photo.

        Transparent pixels show the photo; opaque black is the matte; white
        is sprockets / TNE / FEIT marks.
        """
        overlay = self._frame_for_size(photo.size)
        if overlay is None:
            return photo
        if binary:
            base = photo.convert("L")
            ink = overlay.convert("L").point(lambda v: 0 if v < 128 else 255)
            mask = overlay.getchannel("A").point(lambda v: 255 if v >= 16 else 0)
            return Image.composite(ink, base, mask)
        return Image.alpha_composite(photo.convert("RGBA"), overlay).convert("RGB")

    @staticmethod
    def _normalize_paths(photo_paths: Path | Sequence[Path]) -> list[Path]:
        if isinstance(photo_paths, Path):
            return [photo_paths]
        return [Path(p) for p in photo_paths]

    def _photo_block(
        self,
        photo_path: Optional[Path],
        size: tuple[int, int],
        as_gray: bool,
    ) -> Image.Image:
        """One photo center-cropped to fill ``size`` (white block if missing)."""
        mode = "L" if as_gray else "RGB"
        fill = 255 if as_gray else (255, 255, 255)
        if photo_path is None or not Path(photo_path).exists():
            return Image.new(mode, size, color=fill)
        photo = Image.open(photo_path)
        photo = ImageOps.exif_transpose(photo).convert("RGB")
        fitted = ImageOps.fit(photo, size, method=Image.Resampling.LANCZOS)
        if self.remove_background:
            fitted = cutout_on_white(fitted)
        if not as_gray:
            return fitted
        gray = self._skin_protect_tone(fitted.convert("L"))
        gray = ImageEnhance.Sharpness(gray).enhance(HALFTONE_SHARPEN)
        return gray

    @staticmethod
    def _skin_protect_tone(gray: Image.Image) -> Image.Image:
        gray = ImageOps.autocontrast(gray.convert("L"), cutoff=1)
        lut = []
        for i in range(256):
            x = i / 255.0
            x = x ** SKIN_LIFT_GAMMA
            x = min(1.0, x * SKIN_DENSITY)
            if x > HIGHLIGHT_START:
                t = (x - HIGHLIGHT_START) / max(1e-6, 1.0 - HIGHLIGHT_START)
                t = t ** (1.0 / HIGHLIGHT_PUSH)
                x = HIGHLIGHT_START + (1.0 - HIGHLIGHT_START) * t
            lut.append(int(round(min(1.0, x) * 255)))
        return gray.point(lut)

    @staticmethod
    def _comic_dot(gray: Image.Image, cell: int = HALFTONE_CELL) -> Image.Image:
        gray = gray.convert("L")
        w, h = gray.size
        sampled = gray.filter(ImageFilter.BoxBlur(1))
        out = Image.new("1", (w, h), 1)
        pixels = sampled.load()
        draw = out.load()
        max_r2 = (cell * 0.48) ** 2
        half = cell / 2.0

        for cy in range(0, h, cell):
            for cx in range(0, w, cell):
                sx = min(cx + cell // 2, w - 1)
                sy = min(cy + cell // 2, h - 1)
                tone = pixels[sx, sy] / 255.0
                coverage = (1.0 - tone) ** DOT_COVERAGE_GAMMA
                r2 = max_r2 * coverage
                if r2 <= 0.12:
                    continue
                y1 = min(cy + cell, h)
                x1 = min(cx + cell, w)
                for y in range(cy, y1):
                    dy = (y + 0.5) - (cy + half)
                    for x in range(cx, x1):
                        dx = (x + 0.5) - (cx + half)
                        if dx * dx + dy * dy <= r2:
                            draw[x, y] = 0
        return out.convert("L")

    def _paste_qr(
        self,
        canvas: Image.Image,
        url: str,
        box: tuple[int, int, int, int],
        label: str,
    ) -> None:
        x, y, w, h = box
        cache = None
        if self.output_dir:
            cache = self.output_dir.parent / "short_urls.json"
        short = shorten_url(url.strip(), cache_path=cache)
        qr = qrcode.QRCode(
            version=None,
            error_correction=qrcode.constants.ERROR_CORRECT_L,
            box_size=1,
            border=0,
        )
        qr.add_data(short)
        qr.make(fit=True)
        modules = qr.modules_count
        target = min(QR_RENDER_SIZE, min(w, h) - 2 * QR_QUIET_PX)
        target = max(target, 1)
        scale = target / modules
        if scale < QR_MIN_MODULE_PX:
            logger.warning(
                "QR %s: URL rút còn %d ký tự → %dx%d modules, ~%.1f px/module "
                "(nên ≥ %d). short=%s",
                label,
                len(short),
                modules,
                modules,
                scale,
                QR_MIN_MODULE_PX,
                short,
            )
        else:
            logger.info(
                "QR %s: %d chars → %d modules @ %.1f px/module (%s)",
                label,
                len(short),
                modules,
                scale,
                short,
            )
        img = qr.make_image(fill_color="black", back_color="white").convert("L")
        img = img.resize((target, target), Image.Resampling.NEAREST)

        ox = x + (w - img.width) // 2
        oy = y + (h - img.height) // 2
        wipe = 255 if canvas.mode == "L" else (255, 255, 255)
        canvas.paste(wipe, (ox, oy, ox + img.width, oy + img.height))
        if canvas.mode == "RGB":
            canvas.paste(img.convert("RGB"), (ox, oy))
        else:
            canvas.paste(img, (ox, oy))
