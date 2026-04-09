"""
Asset ingest pipeline.
Handles file validation, hashing, deduplication, thumbnail generation,
sidecar import, and database record creation.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import AsyncGenerator, Iterable, Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.asset import Asset
from models.caption import CaptionVersion
from models.project import Project
from providers.registry import get_registry

logger = logging.getLogger(__name__)

SUPPORTED_MIME_TYPES = {
    "image/jpeg", "image/jpg", "image/pjpeg", "image/png", "image/webp",
    "image/bmp", "image/gif", "image/tiff", "image/x-tiff",
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


@dataclass
class IngestSource:
    file_path: str
    original_filename: str | None = None
    sidecar_text: str | None = None

    @property
    def display_name(self) -> str:
        return Path(self.original_filename or self.file_path).name


def _normalize_sources(items: Iterable[str | IngestSource]) -> list[IngestSource]:
    normalized: list[IngestSource] = []
    for item in items:
        if isinstance(item, IngestSource):
            normalized.append(item)
        else:
            normalized.append(IngestSource(file_path=str(item)))
    return normalized


def _read_sidecar_text(sidecar_path: Path) -> str | None:
    if not sidecar_path.exists() or not sidecar_path.is_file():
        return None
    try:
        text = sidecar_path.read_text(encoding="utf-8", errors="replace").strip()
    except Exception as exc:
        logger.warning("Failed to read sidecar %s: %s", sidecar_path, exc)
        return None
    return text or None


def _is_supported_mime_or_extension(mime_type: str | None, extension: str) -> bool:
    """Accept known image MIME types, but fall back to extension when MIME is missing/generic."""
    if mime_type and mime_type in SUPPORTED_MIME_TYPES:
        return True
    if mime_type in (None, "", "application/octet-stream"):
        return extension in SUPPORTED_EXTENSIONS
    return False


async def ingest_files(
    file_paths: Sequence[str | IngestSource],
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
    sources = _normalize_sources(file_paths)

    progress = IngestProgress(total=len(sources))

    # Pre-fetch all existing SHA256 hashes for this project to avoid N+1 queries
    existing_hashes_result = await db.execute(
        select(Asset.sha256_hash).where(
            Asset.project_id == project_id,
            Asset.sha256_hash.isnot(None),
        )
    )
    known_hashes: set[str] = {h for (h,) in existing_hashes_result.all()}

    for source in sources:
        progress.current_file = source.display_name
        path = Path(source.file_path)

        try:
            if not path.exists() or not path.is_file():
                progress.errors.append(f"File not found: {source.display_name}")
                progress.completed += 1
                yield progress
                continue

            extension = Path(source.display_name).suffix.lower() or path.suffix.lower()
            if extension not in SUPPORTED_EXTENSIONS:
                progress.errors.append(f"Unsupported format: {source.display_name}")
                progress.completed += 1
                yield progress
                continue

            file_size = path.stat().st_size
            if file_size == 0:
                progress.errors.append(f"Empty file: {source.display_name}")
                progress.completed += 1
                yield progress
                continue

            try:
                if hasattr(storage, "inspect_image"):
                    image_info = await storage.inspect_image(str(path))
                    width = image_info.get("width")
                    height = image_info.get("height")
                    mime_type = image_info.get("mime_type")
                else:
                    width, height = await storage.get_image_dimensions(str(path))
                    mime_type = None
            except Exception as exc:
                progress.errors.append(f"Invalid image file {source.display_name}: {exc}")
                progress.completed += 1
                yield progress
                continue

            if not _is_supported_mime_or_extension(mime_type, extension):
                progress.errors.append(f"Unsupported image type: {source.display_name}")
                progress.completed += 1
                yield progress
                continue

            if hasattr(storage, "compute_hashes_from_path"):
                hashes = await storage.compute_hashes_from_path(str(path))
            else:
                with open(path, "rb") as f:
                    hashes = await storage.compute_hashes(f.read())

            existing = hashes["sha256"] in known_hashes

            if existing:
                logger.debug("Duplicate found (exact hash): %s", source.display_name)
                progress.duplicates_found += 1
                progress.completed += 1
                yield progress
                continue

            asset_id = str(uuid.uuid4())
            filename = source.display_name

            if hasattr(storage, "save_original_from_path"):
                saved_path = await storage.save_original_from_path(str(path), filename, project_id)
            else:
                with open(path, "rb") as f:
                    saved_path = await storage.save_original(f.read(), filename, project_id)

            thumbnail_path = None
            thumbnail_small_path = None
            try:
                thumbnail_path = await storage.save_thumbnail(
                    saved_path, asset_id, settings.THUMBNAIL_SIZE
                )
                thumbnail_small_path = await storage.save_thumbnail(
                    saved_path, f"{asset_id}_sm", settings.THUMBNAIL_SMALL_SIZE
                )
            except Exception as exc:
                logger.warning("Failed to generate thumbnail for %s: %s", filename, exc)

            asset = Asset(
                id=asset_id,
                project_id=project_id,
                filename=filename,
                filepath=saved_path,
                file_size=file_size,
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
            db.add(asset)
            await db.flush()

            # Track this hash for intra-batch dedup
            known_hashes.add(hashes["sha256"])

            if source.sidecar_text:
                caption_id = str(uuid.uuid4())
                caption = CaptionVersion(
                    id=caption_id,
                    asset_id=asset_id,
                    text=source.sidecar_text,
                    style="training_literal",
                    provider="sidecar_import",
                    model="",
                    confidence=None,
                    latency_ms=None,
                    is_edited=False,
                    is_active=True,
                )
                db.add(caption)
                asset.active_caption_id = caption_id
                asset.caption_provider = "sidecar_import"

            project = await db.get(Project, project_id)
            if project:
                project.asset_count += 1

            progress.assets_created.append(asset_id)

            if queue_analysis:
                from workers.tasks import queue_analysis_task

                await queue_analysis_task(asset_id)

        except Exception as exc:
            logger.exception("Failed to ingest %s: %s", source.file_path, exc)
            progress.errors.append(f"Error processing {source.display_name}: {exc}")

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

    MAX_FILE_SIZE = 500 * 1024 * 1024  # 500 MB safety limit
    glob = "**/*" if recursive else "*"
    image_paths = sorted(
        p
        for p in d.glob(glob)
        if p.is_file()
        and not p.is_symlink()
        and not any(part.startswith(".") for part in p.relative_to(d).parts)
        and p.suffix.lower() in SUPPORTED_EXTENSIONS
        and p.stat().st_size <= MAX_FILE_SIZE
    )

    sources = [
        IngestSource(
            file_path=str(p),
            original_filename=p.name,
            sidecar_text=_read_sidecar_text(p.with_suffix(".txt")),
        )
        for p in image_paths
    ]

    async for progress in ingest_files(sources, project_id, db, queue_analysis):
        yield progress
