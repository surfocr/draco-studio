"""
Asset ingest pipeline.
Handles file validation, hashing, deduplication, thumbnail generation,
and database record creation.
"""
from __future__ import annotations

import asyncio
import logging
import mimetypes
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.asset import Asset
from models.project import Project
from providers.registry import get_registry

logger = logging.getLogger(__name__)

SUPPORTED_MIME_TYPES = {
    "image/jpeg", "image/png", "image/webp",
    "image/bmp", "image/gif", "image/tiff",
}

SUPPORTED_EXTENSIONS = {
    ".jpg", ".jpeg", ".png", ".webp",
    ".bmp", ".gif", ".tiff", ".tif",
}


@dataclass
class IngestProgress:
    total: int = 0
    completed: int = 0
    current_file: str = ""
    errors: list[str] = field(default_factory=list)
    duplicates_found: int = 0
    assets_created: list[str] = field(default_factory=list)

    @property
    def pct(self) -> float:
        if self.total == 0:
            return 0.0
        return round(self.completed / self.total * 100, 1)


async def ingest_files(
    file_paths: list[str],
    project_id: str,
    db: AsyncSession,
    queue_analysis: bool = True,
) -> AsyncGenerator[IngestProgress, None]:
    """
    Ingest a list of file paths into a project.
    Yields IngestProgress updates as each file is processed.
    """
    registry = get_registry()
    storage = registry.get("storage", "local")

    progress = IngestProgress(total=len(file_paths))

    for file_path in file_paths:
        progress.current_file = file_path
        path = Path(file_path)

        try:
            # Validate file exists
            if not path.exists() or not path.is_file():
                progress.errors.append(f"File not found: {file_path}")
                progress.completed += 1
                yield progress
                continue

            # Validate extension
            if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
                progress.errors.append(f"Unsupported format: {path.name}")
                progress.completed += 1
                yield progress
                continue

            # Read file bytes
            with open(path, "rb") as f:
                file_bytes = f.read()

            if len(file_bytes) == 0:
                progress.errors.append(f"Empty file: {path.name}")
                progress.completed += 1
                yield progress
                continue

            # Compute hashes
            hashes = await storage.compute_hashes(file_bytes)

            # Check for exact duplicate (SHA-256)
            existing = await db.execute(
                select(Asset).where(
                    Asset.project_id == project_id,
                    Asset.sha256_hash == hashes["sha256"],
                )
            )
            existing_asset = existing.scalar_one_or_none()

            if existing_asset is not None:
                logger.debug("Duplicate found (exact hash): %s", path.name)
                progress.duplicates_found += 1
                progress.completed += 1
                yield progress
                continue

            # Detect MIME type
            mime_type, _ = mimetypes.guess_type(str(path))
            if mime_type not in SUPPORTED_MIME_TYPES:
                mime_type = "image/jpeg"  # fallback

            # Get image dimensions
            try:
                width, height = await storage.get_image_dimensions(str(path))
            except Exception:
                width, height = None, None

            # Save original (copy to project storage)
            saved_path = await storage.save_original(file_bytes, path.name, project_id)

            # Generate thumbnails
            thumbnail_path = None
            thumbnail_small_path = None
            try:
                thumbnail_path = await storage.save_thumbnail(
                    saved_path, str(uuid.uuid4()), settings.THUMBNAIL_SIZE
                )
            except Exception as exc:
                logger.warning("Failed to generate thumbnail for %s: %s", path.name, exc)

            # Create Asset record
            asset_id = str(uuid.uuid4())
            asset = Asset(
                id=asset_id,
                project_id=project_id,
                filename=path.name,
                filepath=saved_path,
                file_size=len(file_bytes),
                mime_type=mime_type,
                width=width,
                height=height,
                sha256_hash=hashes["sha256"],
                phash=hashes.get("phash"),
                dhash=hashes.get("dhash"),
                ahash=hashes.get("ahash"),
                thumbnail_path=thumbnail_path,
                thumbnail_small_path=thumbnail_small_path,
            )

            # Also save a small thumbnail using the proper asset_id
            if thumbnail_path:
                try:
                    # Regenerate with correct asset_id
                    thumbnail_path = await storage.save_thumbnail(
                        saved_path, asset_id, settings.THUMBNAIL_SIZE
                    )
                    thumbnail_small_path = await storage.save_thumbnail(
                        saved_path, f"{asset_id}_sm", settings.THUMBNAIL_SMALL_SIZE
                    )
                    asset.thumbnail_path = thumbnail_path
                    asset.thumbnail_small_path = thumbnail_small_path
                except Exception:
                    pass

            db.add(asset)
            await db.flush()  # get ID before updating project

            # Update project stats
            project = await db.get(Project, project_id)
            if project:
                project.asset_count += 1

            progress.assets_created.append(asset_id)

            # Queue analysis job
            if queue_analysis:
                from workers.tasks import queue_analysis_task
                await queue_analysis_task(asset_id)

        except Exception as exc:
            logger.exception("Failed to ingest %s: %s", file_path, exc)
            progress.errors.append(f"Error processing {Path(file_path).name}: {exc}")

        progress.completed += 1
        yield progress

    await db.commit()
    logger.info(
        "Ingest complete: %d files, %d created, %d duplicates, %d errors",
        progress.total,
        len(progress.assets_created),
        progress.duplicates_found,
        len(progress.errors),
    )


async def ingest_directory(
    dir_path: str,
    project_id: str,
    db: AsyncSession,
    recursive: bool = True,
    queue_analysis: bool = True,
) -> AsyncGenerator[IngestProgress, None]:
    """Collect all image files from a directory and ingest them."""
    d = Path(dir_path)
    if not d.is_dir():
        raise ValueError(f"Not a directory: {dir_path}")

    glob = "**/*" if recursive else "*"
    file_paths = [
        str(p)
        for p in d.glob(glob)
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    file_paths.sort()

    async for progress in ingest_files(file_paths, project_id, db, queue_analysis):
        yield progress
