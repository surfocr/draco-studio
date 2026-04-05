"""
ZIP Archive Exporter — simple ZIP of images with caption sidecars.
"""
from __future__ import annotations

import json
import logging
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from providers.base import ExportManifest, ExportProvider

logger = logging.getLogger(__name__)


class ZipExporter(ExportProvider):
    provider_id = "zip_exporter"
    display_name = "ZIP Archive Exporter"

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
        opts = options or {}
        dataset_name = opts.get("dataset_name", "dataset")
        include_metadata = opts.get("include_metadata", True)
        assets_data: list[dict] = opts.get("assets_data", [])

        Path(output_dir).mkdir(parents=True, exist_ok=True)
        zip_path = str(Path(output_dir) / f"{dataset_name}.zip")
        asset_map = {a["id"]: a for a in assets_data}
        included: list[str] = []
        metadata_entries: list[dict] = []

        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for asset_id in asset_ids:
                asset = asset_map.get(asset_id)
                if not asset:
                    continue
                src = Path(asset["filepath"])
                if not src.exists():
                    logger.warning("ZIP export: source not found: %s", src)
                    continue
                zf.write(src, src.name)
                included.append(src.name)

                caption = asset.get("caption", "")
                if caption:
                    txt_name = f"{src.stem}.txt"
                    zf.writestr(txt_name, caption)
                    included.append(txt_name)

                metadata_entries.append({
                    "id": asset_id,
                    "filename": src.name,
                    "caption": caption,
                })

            if include_metadata:
                metadata = {
                    "exported_at": datetime.now(timezone.utc).isoformat(),
                    "total_images": len(metadata_entries),
                    "assets": metadata_entries,
                }
                zf.writestr("metadata.json", json.dumps(metadata, indent=2))
                included.append("metadata.json")

        return ExportManifest(
            format="zip",
            asset_count=len(metadata_entries),
            output_path=zip_path,
            files=included,
            metadata={"dataset_name": dataset_name},
        )
