"""Application settings — loaded from environment / defaults."""

from __future__ import annotations

from pathlib import Path
from typing import List, Union

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parent.parent


def _parse_hex_int(value: Union[int, str]) -> int:
    if isinstance(value, int):
        return value
    text = str(value).strip().lower()
    return int(text, 16) if text.startswith("0x") else int(text)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Branding
    org_name: str = "University of Technology Sydney"

    # Print template B&W — UTS TNE commencement (409×1050; máy in scale → 384 px)
    print_template_path: Path = ROOT_DIR / "assets" / "uts_print_layout_template.png"
    # Template màu upload Cloudinary (439×806) — ảnh + frame, không QR
    print_template_colored_path: Path = ROOT_DIR / "assets" / "uts_upload_layout_template.png"
    # Film-strip overlay chèn lên ảnh sau khi chụp (RGBA, vùng trong suốt = ảnh)
    frame_border_path: Path = ROOT_DIR / "assets" / "uts_frame_border.png"

    # Print layout (POS58: 384 px @ 203 DPI)
    print_width_px: int = 384
    print_dpi: int = 203

    # Paths
    temp_dir: Path = ROOT_DIR / "data" / "temp"
    prints_dir: Path = ROOT_DIR / "data" / "prints"
    photos_dir: Path = ROOT_DIR / "data" / "photos"
    # legacy alias — same as photos_dir
    uploads_dir: Path = ROOT_DIR / "data" / "photos"

    # QR download — trang guest `{id}` = photo id (fallback khi không có PUBLIC_BASE_URL).
    qr_base_url: str = "https://my-photobooth.app/photo/{id}"

    # URL public của booth — QR DOWNLOAD trỏ tới {PUBLIC_BASE_URL}/d/{id} (302 thẳng Cloudinary, không quảng cáo).
    # Production: https://your-domain.com · LAN cùng Wi‑Fi: http://192.168.x.x:8000
    public_base_url: str = ""

    # QR "SCAN TO REGISTER" — Google Form (placeholder tới khi có link thật)
    register_qr_url: str = "https://www.youtube.com"

    # Cloudinary (QR uses secure_url after upload)
    cloudinary_cloud_name: str = ""
    cloudinary_api_key: str = ""
    cloudinary_api_secret: str = ""
    cloudinary_folder: str = "bk-fire-photobooth"

    # Faculties / majors shown in the UI dropdown
    faculties: List[str] = Field(
        default_factory=lambda: [
            "Faculty of Computer Science & Engineering",
            "Faculty of Electrical & Electronics Engineering",
            "Faculty of Mechanical Engineering",
            "Faculty of Civil Engineering",
            "Faculty of Chemical Engineering",
            "Faculty of Transportation Engineering",
            "Faculty of Industrial Management",
            "Faculty of Applied Science",
            "Faculty of Environment & Natural Resources",
            "Faculty of Geology & Petroleum Engineering",
            "Other / Guest",
        ]
    )

    # POS58 USB IDs — Generic POS58 often uses 0x0416:0x5011
    printer_vendor_id: int = 0x0416
    printer_product_id: int = 0x5011
    # Optional CUPS printer name (used when USB direct fails)
    printer_cups_name: str = "POS58"
    # "usb" | "cups" | "file" (file = save raster only, for dry-run)
    printer_backend: str = "usb"
    # USB pacing (0 = full-speed, không delay). Hiện không chia chunk ảnh.
    printer_band_pace_sec: float = 0.0
    # ESC 7 heat: dots, time, interval (interval cao → đầu nhiệt nguội hơn, ít ghost)
    printer_heat_dots: int = 7
    printer_heat_time: int = 70
    printer_heat_interval: int = 4

    # Camera: auto | gphoto | webcam
    # auto = Sony USB nếu có, không thì MacBook FaceTime
    camera_backend: str = "auto"
    camera_model_hint: str = "Sony"
    capture_timeout_sec: int = 30
    webcam_device_index: int = 0

    # Session chụp — mọi chế độ in 1 tấm dọc 3:4 giữa template
    burst_count: int = 1
    burst_interval_sec: float = 0.0
    # Portrait aspect (width:height) — khớp ô ảnh template
    portrait_aspect_w: int = 3
    portrait_aspect_h: int = 4

    # Webcam / no-Sony fallback — cũng 1 tấm 3:4
    webcam_burst_count: int = 1
    webcam_burst_interval_sec: float = 0.0
    webcam_portrait_aspect_w: int = 3
    webcam_portrait_aspect_h: int = 4

    # Print photo processing
    remove_background: bool = False  # tách nền off — giữ nền chụp; midtone da xử lý bằng tone curve

    # Web
    host: str = "0.0.0.0"
    port: int = 8000

    @field_validator("printer_vendor_id", "printer_product_id", mode="before")
    @classmethod
    def _hex_ids(cls, value: Union[int, str]) -> int:
        return _parse_hex_int(value)

    def ensure_dirs(self) -> None:
        for path in (self.temp_dir, self.prints_dir, self.photos_dir, self.uploads_dir):
            path.mkdir(parents=True, exist_ok=True)

    @property
    def cloudinary_enabled(self) -> bool:
        return bool(
            self.cloudinary_cloud_name
            and self.cloudinary_api_key
            and self.cloudinary_api_secret
        )


settings = Settings()
settings.ensure_dirs()
