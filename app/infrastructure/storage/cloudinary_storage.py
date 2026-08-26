"""Cloudinary upload adapter — returns HTTPS URL for QR codes."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


class CloudinaryError(RuntimeError):
    """Raised when Cloudinary upload fails."""


class CloudinaryStorage:
    def __init__(
        self,
        cloud_name: str,
        api_key: str,
        api_secret: str,
        folder: str = "bk-fire-photobooth",
    ) -> None:
        self.cloud_name = cloud_name.strip()
        self.api_key = api_key.strip()
        self.api_secret = api_secret.strip()
        self.folder = folder.strip().strip("/")
        self._configured = False

    @property
    def enabled(self) -> bool:
        return bool(self.cloud_name and self.api_key and self.api_secret)

    def public_id_for(self, photo_id: str) -> str:
        return f"{self.folder}/{photo_id}" if self.folder else photo_id

    def public_id_photo(self, photo_id: str) -> str:
        return self.public_id_for(f"{photo_id}_photo")

    def public_id_layout(self, photo_id: str) -> str:
        return self.public_id_for(f"{photo_id}_layout")

    def expected_url(self, photo_id: str, ext: str = "png") -> str:
        """URL ổn định (không version) — dùng trước khi upload để nhúng QR."""
        if not self.cloud_name:
            raise CloudinaryError("Thiếu CLOUDINARY_CLOUD_NAME")
        public_id = self.public_id_for(photo_id)
        return (
            f"https://res.cloudinary.com/{self.cloud_name}/image/upload/"
            f"{public_id}.{ext.lstrip('.')}"
        )

    def configure(self) -> None:
        if not self.enabled:
            raise CloudinaryError(
                "Thiếu Cloudinary credentials. Thêm CLOUDINARY_CLOUD_NAME, "
                "CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET vào file .env"
            )
        if self._configured:
            return
        try:
            import cloudinary
        except ImportError as exc:
            raise CloudinaryError("Chưa cài cloudinary. Chạy: pip install cloudinary") from exc

        cloudinary.config(
            cloud_name=self.cloud_name,
            api_key=self.api_key,
            api_secret=self.api_secret,
            secure=True,
        )
        self._configured = True

    def upload_photo(
        self,
        local_path: Path,
        photo_id: str,
        *,
        image_format: Optional[str] = None,
    ) -> str:
        """Upload image and return secure_url used for QR."""
        self.configure()
        import cloudinary.uploader

        if not local_path.exists():
            raise CloudinaryError(f"File không tồn tại: {local_path}")

        fmt = (image_format or local_path.suffix.lstrip(".") or "jpg").lower()
        if fmt == "jpeg":
            fmt = "jpg"

        public_id = self.public_id_for(photo_id)
        try:
            # Hard timeout — never block the print queue on a hung CDN.
            result = cloudinary.uploader.upload(
                str(local_path),
                public_id=public_id,
                overwrite=True,
                resource_type="image",
                format=fmt,
                unique_filename=False,
                use_filename=False,
                timeout=25,
            )
        except Exception as exc:  # noqa: BLE001
            raise CloudinaryError(f"Upload Cloudinary thất bại: {exc}") from exc

        url = result.get("secure_url") or result.get("url")
        if not url:
            raise CloudinaryError(f"Cloudinary không trả URL: {result}")
        logger.info("Uploaded %s → %s", photo_id, url)
        return str(url)

    def status(self) -> dict:
        return {
            "enabled": self.enabled,
            "cloud_name": self.cloud_name or None,
            "folder": self.folder or None,
            "configured": self._configured,
        }
