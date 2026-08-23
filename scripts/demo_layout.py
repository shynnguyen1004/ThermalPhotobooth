#!/usr/bin/env python3
"""Render (+ optional print) a layout from an existing JPEG — no camera required."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.application.layout_service import LayoutRenderer
from app.application.photobooth_service import PhotoboothService
from app.infrastructure.camera.gphoto_camera import GPhotoCamera
from app.infrastructure.printer.pos58_printer import POS58Printer
from app.infrastructure.storage.file_storage import FileStorage
from config.settings import settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Demo photobooth layout pipeline")
    parser.add_argument("image", type=Path, help="Path to a sample JPEG/PNG")
    parser.add_argument("--faculty", default="Khoa Khoa học và Kỹ thuật Máy tính")
    parser.add_argument("--qr-base", default=None, help="Override QR base URL")
    args = parser.parse_args()

    if not args.image.exists():
        raise SystemExit(f"File not found: {args.image}")

    settings.ensure_dirs()
    from app.infrastructure.storage.cloudinary_storage import CloudinaryStorage

    layout = LayoutRenderer(
        template_path=settings.print_template_path,
        template_colored_path=settings.print_template_colored_path,
        register_qr_url=settings.register_qr_url,
        output_dir=settings.prints_dir,
        portrait_aspect_w=settings.portrait_aspect_w,
        portrait_aspect_h=settings.portrait_aspect_h,
        remove_background=settings.remove_background,
        frame_border_path=settings.frame_border_path,
    )
    service = PhotoboothService(
        camera=GPhotoCamera(temp_dir=settings.temp_dir),
        layout=layout,
        printer=POS58Printer(
            vendor_id=settings.printer_vendor_id,
            product_id=settings.printer_product_id,
            cups_name=settings.printer_cups_name,
            backend=settings.printer_backend,  # type: ignore[arg-type]
            dry_run_dir=settings.prints_dir,
        ),
        storage=FileStorage(settings.photos_dir),
        cloudinary=CloudinaryStorage(
            cloud_name=settings.cloudinary_cloud_name,
            api_key=settings.cloudinary_api_key,
            api_secret=settings.cloudinary_api_secret,
            folder=settings.cloudinary_folder,
        )
        if settings.cloudinary_enabled
        else None,
        qr_base_url=settings.qr_base_url,
        burst_count=settings.burst_count,
        burst_interval_sec=settings.burst_interval_sec,
    )

    result = service.demo_from_image(
        image_path=args.image,
        faculty=args.faculty,
        qr_base_url=args.qr_base or settings.qr_base_url,
    )
    print(result.message)
    print(f"photo_id : {result.photo_id}")
    print(f"layout   : {result.layout_path}")
    print(f"qr_url   : {result.qr_url}")
    print(f"printed  : {result.printed}")


if __name__ == "__main__":
    main()
