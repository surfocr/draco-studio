"""
LocalStorageProvider — full filesystem-backed storage.
All project assets live under STORAGE_PATH/{project_id}/assets/
Thumbnails under STORAGE_PATH/{project_id}/thumbnails/
Trash under STORAGE_PATH/{project_id}/.trash/
"""
from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import mimetypes
import shutil
import time
from pathlib import Path
from typing import Any

import aiofiles
from PIL import Image

from config import settings
from providers.base import StorageProvider

logger = logging.getLogger(__name__)

# Lazy imports for imagehash — graceful if not installed
try:
    import imagehash
    _IMAGEHASH_AVAILABLE = True
except ImportError:
    _IMAGEHASH_AVAILABLE = False
    logger.warning("imagehash not installed — perceptual hashes will be empty strings")


class LocalStorageProvider(StorageProvider):
    provider_id = "local_storage"
    display_name = "Local Filesystem Storage"

    def __init__(self) -> None:
        self._base = settings.storage_path
        self._base.mkdir(parents=True, exist_ok=True)

    def _project_dir(self, project_id: str) -> Path:
        d = self._base / project_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _assets_dir(self, project_id: str) -> Path:
        d = self._project_dir(project_id) / "assets"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _thumbnails_dir(self, project_id: str) -> Path:
        d = self._project_dir(project_id) / "thumbnails"
        d.mkdir(parents=True, exist_ok=True)
        return d

    def _trash_dir(self, project_id: str) -> Path:
        d = self._project_dir(project_id) / ".trash"
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ── ProviderBase ──────────────────────────────────────────────────────────

    async def is_available(self) -> bool:
        return self._base.exists() and self._base.is_dir()

    async def health_check(self) -> dict[str, Any]:
        t0 = time.monotonic()
        ok = await self.is_available()
        return {
            "ok": ok,
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "details": {"storage_path": str(self._base)},
        }

    # ── StorageProvider ───────────────────────────────────────────────────────

    async def save_original(
        self, file_bytes: bytes, filename: str, project_id: str
    ) -> str:
        """Save original file. Returns absolute path string."""
        dest = self._assets_dir(project_id) / filename
        # If file already exists (same name), suffix it
        if dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            counter = 1
            while dest.exists():
                dest = dest.parent / f"{stem}_{counter}{suffix}"
                counter += 1

        async with aiofiles.open(dest, "wb") as f:
            await f.write(file_bytes)

        logger.debug("Saved original: %s (%d bytes)", dest, len(file_bytes))
        return str(dest)

    async def save_original_from_path(
        self, source_path: str, filename: str, project_id: str
    ) -> str:
        """Copy an existing file into managed storage. Returns absolute path string."""
        dest = self._assets_dir(project_id) / filename
        if dest.exists():
            stem = dest.stem
            suffix = dest.suffix
            counter = 1
            while dest.exists():
                dest = dest.parent / f"{stem}_{counter}{suffix}"
                counter += 1

        def _copy() -> None:
            shutil.copy2(source_path, dest)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _copy)
        logger.debug("Copied original: %s <- %s", dest, source_path)
        return str(dest)

    async def get_original(self, asset_path: str) -> bytes:
        async with aiofiles.open(asset_path, "rb") as f:
            return await f.read()

    async def save_thumbnail(
        self, image_path: str, asset_id: str, size: int
    ) -> str:
        """Generate thumbnail from image_path, save as WebP. Returns path."""
        # Infer project_id from image_path structure
        p = Path(image_path)
        # Walk up to find the project dir (parent of "assets" dir)
        project_id = self._infer_project_id(p)
        thumb_dir = self._thumbnails_dir(project_id)
        thumb_filename = f"{asset_id}_{size}.webp"
        thumb_path = thumb_dir / thumb_filename

        if thumb_path.exists():
            return str(thumb_path)

        def _make_thumb() -> None:
            with Image.open(image_path) as img:
                img = img.convert("RGB")
                img.thumbnail((size, size), Image.LANCZOS)
                img.save(
                    thumb_path,
                    format="WEBP",
                    quality=settings.THUMBNAIL_QUALITY,
                    method=4,
                )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _make_thumb)
        logger.debug("Generated thumbnail %s at %dx%d", thumb_path.name, size, size)
        return str(thumb_path)

    async def save_thumbnail_bytes(
        self, image_bytes: bytes, asset_id: str, project_id: str, size: int
    ) -> str:
        """Generate thumbnail from raw bytes. Returns path."""
        thumb_dir = self._thumbnails_dir(project_id)
        thumb_path = thumb_dir / f"{asset_id}_{size}.webp"

        def _make_thumb() -> None:
            with Image.open(io.BytesIO(image_bytes)) as img:
                img = img.convert("RGB")
                img.thumbnail((size, size), Image.LANCZOS)
                img.save(
                    thumb_path,
                    format="WEBP",
                    quality=settings.THUMBNAIL_QUALITY,
                    method=4,
                )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _make_thumb)
        return str(thumb_path)

    async def get_thumbnail(self, asset_id: str, size: int) -> bytes | None:
        # Search across all project thumbnail dirs
        for project_dir in self._base.iterdir():
            if not project_dir.is_dir():
                continue
            thumb_path = project_dir / "thumbnails" / f"{asset_id}_{size}.webp"
            if thumb_path.exists():
                async with aiofiles.open(thumb_path, "rb") as f:
                    return await f.read()
        return None

    async def get_thumbnail_path(self, asset_id: str, project_id: str, size: int) -> Path | None:
        thumb_path = self._thumbnails_dir(project_id) / f"{asset_id}_{size}.webp"
        return thumb_path if thumb_path.exists() else None

    async def list_project_files(self, project_id: str) -> list[str]:
        assets_dir = self._assets_dir(project_id)
        image_extensions = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tiff", ".tif", ".gif"}
        return [
            str(p)
            for p in sorted(assets_dir.iterdir())
            if p.is_file() and p.suffix.lower() in image_extensions
        ]

    async def delete_asset(self, asset_path: str, asset_id: str) -> None:
        """Move to trash — non-destructive."""
        p = Path(asset_path)
        if not p.exists():
            return
        project_id = self._infer_project_id(p)
        trash = self._trash_dir(project_id)
        dest = trash / p.name
        # Avoid collision in trash
        if dest.exists():
            dest = trash / f"{p.stem}_{asset_id}{p.suffix}"

        def _move() -> None:
            shutil.move(str(p), str(dest))

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _move)
        logger.info("Moved %s to trash: %s", asset_path, dest)

    async def compute_hashes(self, file_bytes: bytes) -> dict[str, str]:
        """Compute SHA-256 + perceptual hashes from raw bytes."""

        def _compute() -> dict[str, str]:
            sha256 = hashlib.sha256(file_bytes).hexdigest()
            result: dict[str, str] = {
                "sha256": sha256,
                "phash": "",
                "dhash": "",
                "ahash": "",
            }
            if _IMAGEHASH_AVAILABLE:
                try:
                    img = Image.open(io.BytesIO(file_bytes)).convert("RGB")
                    result["phash"] = str(imagehash.phash(img))
                    result["dhash"] = str(imagehash.dhash(img))
                    result["ahash"] = str(imagehash.average_hash(img))
                except Exception as exc:
                    logger.warning("Could not compute perceptual hashes: %s", exc)
            return result

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _compute)

    async def compute_hashes_from_path(self, file_path: str) -> dict[str, str]:
        """Compute SHA-256 + perceptual hashes from a file on disk."""

        def _compute() -> dict[str, str]:
            sha256 = hashlib.sha256()
            with open(file_path, "rb") as f:
                while True:
                    chunk = f.read(1024 * 1024)
                    if not chunk:
                        break
                    sha256.update(chunk)

            result: dict[str, str] = {
                "sha256": sha256.hexdigest(),
                "phash": "",
                "dhash": "",
                "ahash": "",
            }
            if _IMAGEHASH_AVAILABLE:
                try:
                    with Image.open(file_path) as img:
                        rgb = img.convert("RGB")
                        result["phash"] = str(imagehash.phash(rgb))
                        result["dhash"] = str(imagehash.dhash(rgb))
                        result["ahash"] = str(imagehash.average_hash(rgb))
                except Exception as exc:
                    logger.warning("Could not compute perceptual hashes: %s", exc)
            return result

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _compute)

    async def get_image_dimensions(self, image_path: str) -> tuple[int, int]:
        """Return (width, height)."""
        def _dims() -> tuple[int, int]:
            with Image.open(image_path) as img:
                return img.width, img.height

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _dims)

    async def inspect_image(self, image_path: str) -> dict[str, Any]:
        """Validate an image and return normalized metadata."""

        def _inspect() -> dict[str, Any]:
            with Image.open(image_path) as img:
                img.load()
                mime_type = Image.MIME.get(img.format or "")
                if mime_type is None:
                    mime_type, _ = mimetypes.guess_type(image_path)
                return {
                    "width": img.width,
                    "height": img.height,
                    "mime_type": mime_type or "application/octet-stream",
                }

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _inspect)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _infer_project_id(self, path: Path) -> str:
        """Walk up from path to find project_id (the dir under storage_path)."""
        try:
            rel = path.relative_to(self._base)
            return rel.parts[0]
        except (ValueError, IndexError):
            return "unknown"

    def get_project_storage_size(self, project_id: str) -> int:
        """Return total bytes used by a project."""
        project_dir = self._project_dir(project_id)
        return sum(f.stat().st_size for f in project_dir.rglob("*") if f.is_file())
