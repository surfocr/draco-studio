"""
Kohya SS Training Export.
Generates full Kohya dataset structure + config.toml + dataset.toml + train.sh
"""
from __future__ import annotations

import json
import logging
import shutil
import time
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from providers.base import ExportManifest, ExportProvider
from providers.export.base_exporter import sanitize_filename

logger = logging.getLogger(__name__)


@dataclass
class KohyaExportConfig:
    trigger_word: str
    repeats: int = 10
    dataset_name: str = "dataset"
    model_type: str = "sdxl"  # "sdxl" | "sd15" | "flux"
    learning_rate: float = 1e-4
    epochs: int = 10
    batch_size: int = 1
    network_rank: int = 32
    network_alpha: int = 16
    caption_style: str = "active"
    include_only_captioned: bool = True
    generate_train_script: bool = True
    create_zip: bool = True


class KohyaExporter(ExportProvider):
    provider_id = "kohya_exporter"
    display_name = "Kohya SS Exporter"

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
        """Legacy interface — uses assets_data from options dict."""
        opts = options or {}
        config = KohyaExportConfig(
            trigger_word=sanitize_filename(opts.get("trigger_word", "subject")),
            repeats=opts.get("repeats", opts.get("n_repeats", 10)),
            dataset_name=sanitize_filename(opts.get("dataset_name", opts.get("project_name", "dataset"))),
            model_type=opts.get("model_type", "sdxl"),
            learning_rate=opts.get("learning_rate", 1e-4),
            epochs=opts.get("epochs", 10),
            batch_size=opts.get("batch_size", 1),
            network_rank=opts.get("network_rank", 32),
            network_alpha=opts.get("network_alpha", 16),
            caption_style=opts.get("caption_style", "active"),
            include_only_captioned=opts.get("include_only_captioned", True),
            generate_train_script=opts.get("generate_train_script", True),
            create_zip=opts.get("create_zip", True),
        )
        assets_data: list[dict] = opts.get("assets_data", [])
        return await self._do_export(asset_ids, output_dir, config, assets_data)

    async def export_from_db(
        self,
        project_id: str,
        asset_ids: list[str],
        output_dir: str,
        config: KohyaExportConfig,
        db: AsyncSession,
        job_id: str | None = None,
    ) -> ExportManifest:
        """Full DB-aware export."""
        from models.asset import Asset, ReviewState
        from models.caption import CaptionVersion

        conditions = [
            Asset.project_id == project_id,
            Asset.is_rejected.is_(False),
        ]
        if asset_ids:
            conditions.append(Asset.id.in_(asset_ids))
        if config.include_only_captioned:
            conditions.append(Asset.active_caption_id.isnot(None))

        result = await db.execute(select(Asset).where(*conditions))
        assets = result.scalars().all()

        if not assets:
            return ExportManifest(
                format="kohya",
                asset_count=0,
                output_path=output_dir,
                files=[],
                metadata={"error": "No eligible assets found"},
            )

        caption_result = await db.execute(
            select(CaptionVersion).where(
                CaptionVersion.asset_id.in_([a.id for a in assets]),
                CaptionVersion.is_active == True,
            )
        )
        captions_by_asset = {cv.asset_id: cv for cv in caption_result.scalars().all()}

        assets_data: list[dict] = []
        for a in assets:
            cv = captions_by_asset.get(a.id)
            caption_text = cv.text if cv else ""

            if config.caption_style == "trigger_prefix":
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

        ids = [d["id"] for d in assets_data]
        return await self._do_export(ids, output_dir, config, assets_data)

    async def _do_export(
        self,
        asset_ids: list[str],
        output_dir: str,
        config: KohyaExportConfig,
        assets_data: list[dict],
    ) -> ExportManifest:
        out = Path(output_dir) / config.dataset_name
        img_dir = out / "img" / f"{config.repeats}_{config.trigger_word}"
        img_dir.mkdir(parents=True, exist_ok=True)
        (out / "log").mkdir(exist_ok=True)
        (out / "model").mkdir(exist_ok=True)

        asset_map = {a["id"]: a for a in assets_data}
        files: list[str] = []
        included_count = 0

        for asset_id in asset_ids:
            asset = asset_map.get(asset_id)
            if not asset:
                continue
            src = Path(asset["filepath"])
            if not src.exists():
                logger.warning("Kohya export: source not found: %s", src)
                continue
            dest = img_dir / src.name
            shutil.copy2(src, dest)
            files.append(str(dest))
            included_count += 1

            caption = asset.get("caption", "")
            caption_file = img_dir / f"{src.stem}.txt"
            caption_file.write_text(caption, encoding="utf-8")
            files.append(str(caption_file))

        # Write config.toml
        config_toml = self.generate_config_toml(config, str(out))
        config_file = out / "config.toml"
        config_file.write_text(config_toml, encoding="utf-8")
        files.append(str(config_file))

        # Write dataset.toml
        dataset_toml = self.generate_dataset_toml(str(img_dir), config.trigger_word, config.repeats)
        dataset_file = out / "dataset.toml"
        dataset_file.write_text(dataset_toml, encoding="utf-8")
        files.append(str(dataset_file))

        # Write train script
        if config.generate_train_script:
            script = self.generate_train_script(config, str(out))
            script_file = out / "train.sh"
            script_file.write_text(script, encoding="utf-8")
            files.append(str(script_file))

        # Write metadata
        metadata_obj = {
            "format": "kohya",
            "trigger_word": config.trigger_word,
            "repeats": config.repeats,
            "model_type": config.model_type,
            "asset_count": included_count,
            "exported_at": datetime.now(timezone.utc).isoformat(),
        }
        meta_file = out / "metadata.json"
        meta_file.write_text(json.dumps(metadata_obj, indent=2), encoding="utf-8")
        files.append(str(meta_file))

        zip_path = ""
        if config.create_zip:
            zip_path = str(Path(output_dir) / f"{config.dataset_name}_kohya.zip")
            with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                for f in files:
                    fp = Path(f)
                    if fp.exists():
                        try:
                            zf.write(fp, fp.relative_to(Path(output_dir)))
                        except ValueError:
                            zf.write(fp, fp.name)
            files.append(zip_path)

        return ExportManifest(
            format="kohya",
            asset_count=included_count,
            output_path=zip_path or str(out),
            files=files,
            metadata=metadata_obj,
        )

    def generate_config_toml(self, config: KohyaExportConfig, output_dir: str) -> str:
        lr = config.learning_rate
        return f"""[training]
pretrained_model_name_or_path = ""
output_dir = "{output_dir}/model"
output_name = "{config.trigger_word}_lora"
logging_dir = "{output_dir}/log"

max_train_epochs = {config.epochs}
train_batch_size = {config.batch_size}
learning_rate = {lr}
unet_lr = {lr}
text_encoder_lr = {lr / 10}

network_module = "networks.lora"
network_dim = {config.network_rank}
network_alpha = {config.network_alpha}

lr_scheduler = "cosine_with_restarts"
lr_warmup_steps = 0

mixed_precision = "fp16"
save_precision = "fp16"
save_every_n_epochs = 1

xformers = true
gradient_checkpointing = true
persistent_data_loader_workers = true

caption_extension = ".txt"
shuffle_caption = true
keep_tokens = 1
"""

    def generate_dataset_toml(self, dataset_path: str, trigger_word: str, repeats: int) -> str:
        return f"""[general]
shuffle_caption = true
caption_extension = ".txt"
keep_tokens = 1

[[datasets]]
resolution = 1024
batch_size = 1
keep_tokens = 1

  [[datasets.subsets]]
  image_dir = "{dataset_path}"
  class_tokens = "{trigger_word}"
  num_repeats = {repeats}
"""

    def generate_train_script(self, config: KohyaExportConfig, output_dir: str) -> str:
        accelerate_config = "--num_cpu_threads_per_process 2"
        if config.model_type == "sdxl":
            train_script = "train_network.py"
            extra = "--sdxl"
        elif config.model_type == "flux":
            train_script = "flux_train_network.py"
            extra = ""
        else:
            train_script = "train_network.py"
            extra = ""

        return f"""#!/bin/bash
# Kohya SS LoRA Training Script
# Generated by Draco Dataset Studio

accelerate launch {accelerate_config} {train_script} \\
  --config_file="{output_dir}/config.toml" \\
  --dataset_config="{output_dir}/dataset.toml" \\
  {extra}

echo "Training complete!"
"""
