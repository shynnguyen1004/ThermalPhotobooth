#!/usr/bin/env python3
"""Render a sample print strip through the real LayoutRenderer.

Usage:
    python scripts/preview_template_print.py [photo.jpg] [--print]

Defaults to the sample portrait in "test layout print/". Preview lands in
"test layout print/_preview/". With ``--print`` the strip is also sent to the
printer configured in .env.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.application.layout_service import LayoutRenderer  # noqa: E402
from app.infrastructure.printer.pos58_printer import POS58Printer  # noqa: E402
from config.settings import settings  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("photo", nargs="?", type=Path, help="Sample photo")
    parser.add_argument(
        "--print",
        dest="do_print",
        action="store_true",
        help="Send the strip to the configured printer",
    )
    args = parser.parse_args()

    photo = args.photo or (ROOT / "test layout print" / "portrait.jpg")
    if not photo.exists():
        raise SystemExit(f"File not found: {photo}")

    out_dir = ROOT / "test layout print" / "_preview"
    out_dir.mkdir(exist_ok=True)

    qr_url = settings.qr_base_url.replace("{id}", "a1b2c3d4e5f6")
    print(f"QR download : {qr_url}")
    print(f"QR register : {settings.register_qr_url}")

    renderer = LayoutRenderer(
        template_path=settings.print_template_path,
        template_colored_path=settings.print_template_colored_path,
        register_qr_url=settings.register_qr_url,
        remove_background=settings.remove_background,
        frame_border_path=settings.frame_border_path,
    )
    strip = renderer.render(photo, qr_url=qr_url, save=False)
    out = out_dir / "pipeline_single.png"
    strip.save(out)
    print(f"preview → {out}")

    if args.do_print:
        printer = POS58Printer(
            vendor_id=settings.printer_vendor_id,
            product_id=settings.printer_product_id,
            cups_name=settings.printer_cups_name,
            backend=settings.printer_backend,  # type: ignore[arg-type]
            dry_run_dir=settings.prints_dir,
        )
        printer.print_image(
            strip,
            download_url=qr_url,
            register_url=settings.register_qr_url,
        )
        print(f"printed via {settings.printer_backend}")


if __name__ == "__main__":
    main()
