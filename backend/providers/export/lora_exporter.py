"""
LoRA Training Format Exporter (full rebuild).
Output: {dataset_name}/{repeats}_{trigger_word}/*.png + *.txt + metadata.json
Standard Kohya SS / SimpleTuner / OneTrainer format.
"""
from __future__ import annotations

import asyncio
import json
import logging
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from providers.base import ExportManifest, ExportProvider
from providers.export.base_exporter import create_zip, sanitize_filename

logger = logging.getLogger(__name__)


@dataclass
class LoRAExportConfig:
    trigger_word: str
    repeats: int = 10
    caption_style: str = "active"
    include_only_captioned: bool = True
    include_only_approved: bool = False
    min_score: Optional[float] = None
    max_images: Optional[int] = None
    image_format: str = "png"
    resize_to: Optional[tuple[int, int]] = None
    create_zip: bool = True
    dataset_name: str = "dataset"
    include_metadata_json: bool = True


class LoRAExporter(ExportProvider):
    provider_id = "lora_exporter"
    display_name = "LoRA Training Format Exporter"

    async def is_available(self) -> bool:
        return True

    async def health_check(self) -> dict[str, Any]:
        return {"ok": True, "latency_ms": 0, "details": {}}

    async def export(
        self,
        asset_ids: list[str],
        output_dir: str,
        options: dict[str, Any] | None = None,
    ) -> ExportManifest:
        """Legacy interface — wraps _do_export using assets_data from options."""
        opts = options or {}
        config = LoRAExportConfig(
            trigger_word=sanitize_filename(opts.get("trigger_word", "subject")),
            repeats=opts.get("repeats", opts.get("n_repeats", 10)),
            caption_style=opts.get("caption_style", "active"),
            include_only_captioned=opts.get("include_only_captioned", True),
            include_only_approved=opts.get("include_only_approved", False),
            min_score=opts.get("min_score"),
            max_images=opts.get("max_images"),
            image_format=opts.get("image_format", "png"),
            resize_to=opts.get("resize_to"),
            create_zip=opts.get("create_zip", True),
            dataset_name=sanitize_filename(opts.get("dataset_name", opts.get("project_name", "dataset"))),
            include_metadata_json=opts.get("include_metadata_json", True),
        )
        assets_data: list[dict] = opts.get("assets_data", [])
        return await self._do_export(asset_ids, output_dir, config, assets_data)

    async def export_from_db(
        self,
        project_id: str,
        asset_ids: list[str],
        output_dir: str,
        config: LoRAExportConfig,
        db: AsyncSession,
        job_id: str | None = None,
    ) -> ExportManifest:
        """Full DB-aware export. Loads assets + captions from DB."""
        from models.asset import Asset, ReviewState
        from models.caption import CaptionVersion

        # Build filter
        conditions = [
            Asset.project_id == project_id,
            Asset.is_rejected.is_(False),
        ]
        if asset_ids:
            conditions.append(Asset.id.in_(asset_ids))
        if config.include_only_approved:
            conditions.append(Asset.review_state == ReviewState.APPROVED.value)
        if config.min_score is not None:
            conditions.append(Asset.composite_score >= config.min_score)
        if config.include_only_captioned:
            conditions.append(Asset.active_caption_id.isnot(None))

        result = await db.execute(select(Asset).where(*conditions))
        assets = result.scalars().all()

        if not assets:
            return ExportManifest(
                format="lora",
                asset_count=0,
                output_path=output_dir,
                files=[],
                metadata={"error": "No eligible assets found"},
            )

        # Load active captions
        caption_result = await db.execute(
            select(CaptionVersion).where(
                CaptionVersion.asset_id.in_([a.id for a in assets]),
                CaptionVersion.is_active.is_(True),
            )
        )
        captions_by_asset = {cv.asset_id: cv for cv in caption_result.scalars().all()}

        # Build assets_data list
        assets_data: list[dict] = []
        for a in assets:
            cv = captions_by_asset.get(a.id)
            caption_text = cv.text if cv else ""

            # caption_style handling
            if config.caption_style == "active":
                caption = caption_text
            elif config.caption_style == "trigger_prefix":
                caption = f"{config.trigger_word}, {caption_text}".strip(", ")
            else:
                caption = caption_text

            assets_data.append({
                "id": a.id,
                "filepath": a.filepath,
                "filename": a.filename,
                "caption": caption,
                "composite_score": a.composite_score,
            })

        # Apply max_images if set (keep highest scored)
        if config.max_images is not None and len(assets_data) > config.max_images:
            assets_data = sorted(
                assets_data,
                key=lambda x: x.get("composite_score") or 0.0,
                reverse=True,
            )[: config.max_images]

        ids = [d["id"] for d in assets_data]
        return await self._do_export(ids, output_dir, config, assets_data)

    async def _do_export(
        self,
        asset_ids: list[str],
        output_dir: str,
        config: LoRAExportConfig,
        assets_data: list[dict],
    ) -> ExportManifest:
        """Core export logic."""
        out = Path(output_dir) / config.dataset_name
        img_dir = out / f"{config.repeats}_{config.trigger_word}"
        img_dir.mkdir(parents=True, exist_ok=True)

        files: list[str] = []
        asset_map = {a["id"]: a for a in assets_data}
        included_assets: list[dict] = []

        loop = asyncio.get_event_loop()

        def _copy_asset(asset: dict) -> list[str]:
            src = Path(asset["filepath"])
            if not src.exists():
                logger.warning("Export: source not found: %s", src)
                return []
            written: list[str] = []

            # Target filename
            stem = src.stem
            target_ext = f".{config.image_format}" if config.image_format != "original" else src.suffix
            dest_img = img_dir / f"{stem}{target_ext}"

            if config.resize_to and config.image_format != "original":
                try:
                    from PIL import Image

                    img = Image.open(src)
                    img = img.resize(config.resize_to, Image.LANCZOS)
                    if img.mode not in ("RGB", "RGBA") and config.image_format == "png":
                        img = img.convert("RGB")
                    img.save(dest_img)
                except Exception as e:
                    logger.warning("Resize failed for %s: %s — copying original", src, e)
                    shutil.copy2(src, dest_img)
            elif config.image_format != "original" and src.suffix.lower().lstrip(".") != config.image_format:
                try:
                    from PIL import Image

                    img = Image.open(src).convert("RGB")
                    img.save(dest_img)
                except Exception:
                    shutil.copy2(src, dest_img)
            else:
                shutil.copy2(src, dest_img)

            written.append(str(dest_img))

            # Write caption sidecar
            caption = asset.get("caption", "")
            caption_file = img_dir / f"{stem}.txt"
            caption_file.write_text(caption, encoding="utf-8")
            written.append(str(caption_file))

            return written

        for asset_id in asset_ids:
            asset = asset_map.get(asset_id)
            if not asset:
                continue
            written = await loop.run_in_executor(None, _copy_asset, asset)
            if written:
                files.extend(written)
                included_assets.append(asset)

        # Metadata JSON
        if config.include_metadata_json:
            metadata_obj = {
                "format": "lora",
                "trigger_word": config.trigger_word,
                "repeats": config.repeats,
                "caption_style": config.caption_style,
                "asset_count": len(included_assets),
                "exported_at": datetime.now(timezone.utc).isoformat(),
                "assets": [
                    {
                        "id": a["id"],
                        "filename": Path(a["filepath"]).name,
                        "caption": a.get("caption", ""),
                    }
                    for a in included_assets
                ],
            }
            meta_path = out / "metadata.json"
            meta_path.write_text(json.dumps(metadata_obj, indent=2), encoding="utf-8")
            files.append(str(meta_path))
        else:
            metadata_obj = {
                "format": "lora",
                "trigger_word": config.trigger_word,
                "repeats": config.repeats,
                "asset_count": len(included_assets),
                "exported_at": datetime.now(timezone.utc).isoformat(),
            }

        zip_path = ""
        if config.create_zip:
            zip_path = str(Path(output_dir) / f"{config.dataset_name}_lora.zip")
            zip_output = Path(zip_path)
            await loop.run_in_executor(None, create_zip, out, zip_output)
            files.append(zip_path)

        return ExportManifest(
            format="lora",
            asset_count=len(included_assets),
            output_path=zip_path or str(out),
            files=files,
            metadata=metadata_obj,
        )
