"""
Caption workflow service — complete implementation.
Manages caption generation, versioning, bulk operations, and consistency analysis.
"""
from __future__ import annotations

import logging
import re
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import and_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from config import settings
from models.asset import Asset
from models.caption import CaptionVersion
from services.caption_strategy import build_model_aware_prompt
from services.runtime_config import resolve_provider_for_task

logger = logging.getLogger(__name__)

VALID_STYLES = frozenset({"natural", "concise", "danbooru_tags", "wd_tags", "training_literal"})


@dataclass
class CaptionConsistencyReport:
    total_captioned: int
    total_uncaptioned: int
    avg_length: float
    length_std: float
    common_words: list[tuple[str, int]]
    rare_words: list[tuple[str, int]]
    trigger_word_presence: dict[str, int]
    inconsistent_formatting: list[str]  # asset IDs
    recommendations: list[str]


class CaptionService:
    """Full caption workflow: generate, version, bulk-edit, export, analyze."""

    # ── Core generation ───────────────────────────────────────────────────────

    async def generate(
        self,
        asset_id: str,
        provider_name: str,
        style: str,
        db: AsyncSession,
        options: dict[str, Any] | None = None,
        set_active: bool = True,
    ) -> CaptionVersion:
        if style not in VALID_STYLES:
            raise ValueError(f"Invalid style '{style}'. Valid: {sorted(VALID_STYLES)}")

        asset = await db.get(Asset, asset_id)
        if asset is None:
            raise LookupError(f"Asset {asset_id} not found")

        resolved = await resolve_provider_for_task(
            db,
            asset.project_id,
            "caption",
            explicit_provider_name=provider_name,
        )
        provider = resolved.provider
        effective_provider_name = resolved.provider_name or provider_name
        if provider is None:
            raise ValueError(f"Caption provider '{provider_name}' not registered")

        merged_options = dict(resolved.options)
        if options:
            merged_options.update(options)

        target_model = str(merged_options.get("target_model") or "flux_1")
        character_mode = bool(merged_options.get("character_mode"))
        if not merged_options.get("prompt"):
            provider_prompt = provider.get_prompt_for_style(style, custom_prompt=None)
            merged_options["prompt"] = build_model_aware_prompt(
                style=style,
                target_model=target_model,
                character_mode=character_mode,
                provider_prompt=provider_prompt,
            )

        result = await provider.generate(asset.filepath, style, merged_options)
        if not result.text:
            raise RuntimeError(f"Provider {effective_provider_name} returned empty caption")

        if set_active:
            await db.execute(
                update(CaptionVersion)
                .where(
                    and_(
                        CaptionVersion.asset_id == asset_id,
                        CaptionVersion.is_active.is_(True),
                    )
                )
                .values(is_active=False)
            )

        version = CaptionVersion(
            id=str(uuid.uuid4()),
            asset_id=asset_id,
            text=result.text,
            style=style,
            provider=result.provider,
            model=result.model or "",
            confidence=result.confidence,
            latency_ms=result.latency_ms,
            is_active=set_active,
        )
        db.add(version)

        if set_active:
            asset.active_caption_id = version.id
            asset.caption_provider = effective_provider_name

        await db.flush()
        logger.debug(
            "Generated %s/%s caption for %s (%d chars)",
            effective_provider_name, style, asset_id[:8], len(result.text),
        )
        return version

    async def generate_batch(
        self,
        asset_ids: list[str],
        provider_name: str,
        style: str,
        db: AsyncSession,
        options: dict[str, Any] | None = None,
        job_id: str | None = None,
    ) -> str:
        """Queue batch caption generation. Returns the real queue job_id."""
        from workers.tasks import queue_caption_task
        return await queue_caption_task(asset_ids, provider_name, style, options)

    async def compare_providers(
        self,
        asset_id: str,
        provider_names: list[str],
        style: str,
        db: AsyncSession,
        options: dict[str, Any] | None = None,
    ) -> list[CaptionVersion]:
        """Generate captions from multiple providers sequentially, each with its own session."""
        from database import AsyncSessionLocal

        versions: list[CaptionVersion] = []
        for pname in provider_names:
            try:
                async with AsyncSessionLocal() as provider_db:
                    version = await self.generate(
                        asset_id, pname, style, provider_db, options, set_active=False
                    )
                    await provider_db.commit()
                    versions.append(version)
            except Exception as exc:
                logger.warning("compare_providers: %s failed: %s", pname, exc)
        return versions

    # ── Version management ────────────────────────────────────────────────────

    async def set_active(
        self,
        asset_id: str,
        caption_version_id: str,
        db: AsyncSession,
    ) -> Asset:
        await db.execute(
            update(CaptionVersion)
            .where(CaptionVersion.asset_id == asset_id)
            .values(is_active=False)
        )

        version = await db.get(CaptionVersion, caption_version_id)
        if version is None or version.asset_id != asset_id:
            raise LookupError(f"CaptionVersion {caption_version_id} not found for asset {asset_id}")

        version.is_active = True

        asset = await db.get(Asset, asset_id)
        if asset:
            asset.active_caption_id = caption_version_id

        await db.flush()
        return asset  # type: ignore[return-value]

    async def edit(
        self,
        caption_version_id: str,
        new_text: str,
        db: AsyncSession,
        author: str = "human",
    ) -> CaptionVersion:
        """Create a new edited version (immutable history)."""
        original = await db.get(CaptionVersion, caption_version_id)
        if original is None:
            raise LookupError(f"CaptionVersion {caption_version_id} not found")

        if original.is_active:
            await db.execute(
                update(CaptionVersion)
                .where(CaptionVersion.asset_id == original.asset_id)
                .values(is_active=False)
            )

        new_version = CaptionVersion(
            id=str(uuid.uuid4()),
            asset_id=original.asset_id,
            text=new_text.strip(),
            style=original.style,
            provider=author,
            model=None,
            confidence=None,
            latency_ms=None,
            is_active=True,
            is_edited=True,
            edited_at=datetime.now(timezone.utc),
        )
        db.add(new_version)

        asset = await db.get(Asset, original.asset_id)
        if asset:
            asset.active_caption_id = new_version.id

        await db.flush()
        return new_version

    async def list_versions(self, asset_id: str, db: AsyncSession) -> list[CaptionVersion]:
        result = await db.execute(
            select(CaptionVersion)
            .where(CaptionVersion.asset_id == asset_id)
            .order_by(CaptionVersion.created_at.desc())
        )
        return list(result.scalars().all())

    async def delete_version(self, caption_version_id: str, db: AsyncSession) -> None:
        version = await db.get(CaptionVersion, caption_version_id)
        if version is None:
            raise LookupError(f"CaptionVersion {caption_version_id} not found")
        if version.is_active:
            raise ValueError("Cannot delete the active caption version")
        await db.delete(version)
        await db.flush()

    # ── Bulk operations ───────────────────────────────────────────────────────

    async def bulk_prepend(
        self,
        asset_ids: list[str],
        text: str,
        db: AsyncSession,
    ) -> int:
        count = 0
        for asset_id in asset_ids:
            version = await self._get_active_version(asset_id, db)
            if version and version.text:
                sep = "" if text.endswith(" ") else " "
                new_text = text + sep + version.text
                await self._replace_active(asset_id, version, new_text.strip(), db)
                count += 1
        return count

    async def bulk_append(
        self,
        asset_ids: list[str],
        text: str,
        db: AsyncSession,
    ) -> int:
        count = 0
        for asset_id in asset_ids:
            version = await self._get_active_version(asset_id, db)
            if version and version.text:
                separator = ", " if not version.text.rstrip().endswith(",") else " "
                new_text = version.text + separator + text
                await self._replace_active(asset_id, version, new_text.strip(), db)
                count += 1
        return count

    async def bulk_find_replace(
        self,
        asset_ids: list[str],
        find: str,
        replace: str,
        db: AsyncSession,
        use_regex: bool = False,
    ) -> int:
        count = 0
        for asset_id in asset_ids:
            version = await self._get_active_version(asset_id, db)
            if version and version.text:
                if use_regex:
                    try:
                        if len(find) > 500:
                            raise re.error("Pattern too long (max 500 characters)")
                        new_text = re.sub(find, replace, version.text)
                    except re.error as exc:
                        logger.warning("Invalid regex '%s': %s", find, exc)
                        continue
                else:
                    new_text = version.text.replace(find, replace)

                if new_text != version.text:
                    await self._replace_active(asset_id, version, new_text, db)
                    count += 1
        return count

    async def normalize(self, asset_ids: list[str], db: AsyncSession) -> int:
        """Trim whitespace, fix double spaces, clean commas."""
        count = 0
        for asset_id in asset_ids:
            version = await self._get_active_version(asset_id, db)
            if version and version.text:
                normalized = version.text.strip()
                normalized = re.sub(r"  +", " ", normalized)
                normalized = re.sub(r",\s*,+", ",", normalized)
                normalized = re.sub(r"\s+,", ",", normalized)
                normalized = re.sub(r",(?!\s)", ", ", normalized)
                normalized = normalized.rstrip(", ").rstrip()
                if normalized != version.text:
                    await self._replace_active(asset_id, version, normalized, db)
                    count += 1
        return count

    # ── Export ────────────────────────────────────────────────────────────────

    async def export_sidecars(
        self,
        project_id: str,
        asset_ids: list[str],
        db: AsyncSession,
        output_dir: str | None = None,
    ) -> str:
        """Write .txt sidecar files. Returns the real queue job_id."""
        from workers.tasks import queue_export_sidecars_task
        return await queue_export_sidecars_task(
            project_id=project_id,
            asset_ids=asset_ids,
            output_dir=output_dir,
        )

    async def write_sidecar_direct(
        self,
        asset_id: str,
        db: AsyncSession,
        output_dir: str | None = None,
    ) -> str | None:
        """Write a single sidecar file synchronously. Returns output path or None."""
        asset = await db.get(Asset, asset_id)
        if asset is None:
            return None
        version = await self._get_active_version(asset_id, db)
        if version is None or not version.text:
            return None
        src_path = Path(asset.filepath)
        if output_dir:
            dest_dir = Path(output_dir).resolve()
            storage_root = settings.storage_path
            if not dest_dir.is_relative_to(storage_root):
                raise ValueError(
                    f"output_dir must be within storage root ({storage_root})"
                )
            dest = dest_dir / src_path.with_suffix(".txt").name
        else:
            dest = src_path.with_suffix(".txt")
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(version.text, encoding="utf-8")
        return str(dest)

    # ── Consistency analysis ──────────────────────────────────────────────────

    async def analyze_consistency(
        self,
        project_id: str,
        db: AsyncSession,
        trigger_words: list[str] | None = None,
    ) -> CaptionConsistencyReport:
        assets_result = await db.execute(
            select(Asset).where(Asset.project_id == project_id)
        )
        assets = list(assets_result.scalars().all())
        total = len(assets)

        captioned_ids = [a.id for a in assets if a.active_caption_id]
        uncaptioned = total - len(captioned_ids)

        if not captioned_ids:
            return CaptionConsistencyReport(
                total_captioned=0,
                total_uncaptioned=total,
                avg_length=0.0,
                length_std=0.0,
                common_words=[],
                rare_words=[],
                trigger_word_presence={},
                inconsistent_formatting=[],
                recommendations=["No captions found. Generate captions first."],
            )

        cap_result = await db.execute(
            select(CaptionVersion).where(
                and_(
                    CaptionVersion.asset_id.in_(captioned_ids),
                    CaptionVersion.is_active.is_(True),
                )
            )
        )
        captions = list(cap_result.scalars().all())
        texts = [c.text for c in captions if c.text]
        lengths = [len(t) for t in texts]

        avg_len = sum(lengths) / len(lengths) if lengths else 0.0
        if len(lengths) > 1:
            import statistics
            std_len = statistics.stdev(lengths)
        else:
            std_len = 0.0

        word_counter: Counter[str] = Counter()
        for text in texts:
            words = re.findall(r"\b[a-z][a-z'-]{1,}\b", text.lower())
            word_counter.update(words)

        common = word_counter.most_common(20)
        rare = [(w, c) for w, c in word_counter.items() if c == 1][:20]

        trigger_presence: dict[str, int] = {}
        if trigger_words:
            for tw in trigger_words:
                tw_lower = tw.lower()
                trigger_presence[tw] = sum(1 for t in texts if tw_lower in t.lower())

        cap_by_asset = {c.asset_id: c for c in captions}
        inconsistent: list[str] = []
        for aid in captioned_ids:
            cap = cap_by_asset.get(aid)
            if cap is None:
                continue
            t = cap.text
            issues = (
                t != t.strip()
                or "  " in t
                or bool(re.search(r",\s*,", t))
                or len(t) < 10
                or len(t) > 800
            )
            if issues:
                inconsistent.append(aid)

        recs: list[str] = []
        if uncaptioned > 0:
            recs.append(f"{uncaptioned} assets missing captions — run bulk generate.")
        if inconsistent:
            recs.append(f"{len(inconsistent)} captions have formatting issues — run Normalize.")
        if trigger_words:
            for tw, count in trigger_presence.items():
                coverage = count / len(texts) if texts else 0
                if coverage < 0.5:
                    recs.append(
                        f"Trigger word '{tw}' in only {count}/{len(texts)} captions ({coverage:.0%})."
                    )
        if avg_len < 30:
            recs.append("Average caption is very short — consider 'training_literal' style.")
        if std_len > avg_len * 0.5 and avg_len > 0:
            recs.append("Caption lengths vary widely — consider normalizing style.")
        if not recs:
            recs.append("Caption consistency looks good!")

        return CaptionConsistencyReport(
            total_captioned=len(captioned_ids),
            total_uncaptioned=uncaptioned,
            avg_length=round(avg_len, 1),
            length_std=round(std_len, 1),
            common_words=common,
            rare_words=rare,
            trigger_word_presence=trigger_presence,
            inconsistent_formatting=inconsistent,
            recommendations=recs,
        )

    # ── Internal helpers ──────────────────────────────────────────────────────

    async def _get_active_version(
        self, asset_id: str, db: AsyncSession
    ) -> CaptionVersion | None:
        result = await db.execute(
            select(CaptionVersion).where(
                and_(
                    CaptionVersion.asset_id == asset_id,
                    CaptionVersion.is_active.is_(True),
                )
            )
        )
        return result.scalar_one_or_none()

    async def _replace_active(
        self,
        asset_id: str,
        old_version: CaptionVersion,
        new_text: str,
        db: AsyncSession,
    ) -> CaptionVersion:
        old_version.is_active = False
        new_version = CaptionVersion(
            id=str(uuid.uuid4()),
            asset_id=asset_id,
            text=new_text,
            style=old_version.style,
            provider="bulk_edit",
            model=None,
            confidence=None,
            latency_ms=None,
            is_active=True,
            is_edited=True,
            edited_at=datetime.now(timezone.utc),
        )
        db.add(new_version)
        asset = await db.get(Asset, asset_id)
        if asset:
            asset.active_caption_id = new_version.id
        await db.flush()
        return new_version


# ── Singleton ─────────────────────────────────────────────────────────────────

_caption_service: CaptionService | None = None


def get_caption_service() -> CaptionService:
    global _caption_service
    if _caption_service is None:
        _caption_service = CaptionService()
    return _caption_service


# ── Legacy function helpers (backwards compat) ────────────────────────────────

async def generate_caption(
    asset_id: str,
    provider_name: str,
    style: str,
    db: AsyncSession,
    options: dict | None = None,
    set_active: bool = True,
) -> CaptionVersion | None:
    try:
        return await get_caption_service().generate(
            asset_id, provider_name, style, db, options, set_active
        )
    except Exception as exc:
        logger.error("generate_caption: %s", exc)
        return None


async def bulk_generate(
    asset_ids: list[str],
    provider_name: str,
    style: str,
    db: AsyncSession,
    options: dict | None = None,
) -> str:
    return await get_caption_service().generate_batch(
        asset_ids, provider_name, style, db, options
    )


async def update_caption(caption_id: str, new_text: str, db: AsyncSession) -> CaptionVersion | None:
    try:
        return await get_caption_service().edit(caption_id, new_text, db)
    except LookupError:
        return None


async def set_active_caption(asset_id: str, caption_id: str, db: AsyncSession) -> bool:
    try:
        await get_caption_service().set_active(asset_id, caption_id, db)
        return True
    except LookupError:
        return False


async def get_caption_history(asset_id: str, db: AsyncSession) -> list[CaptionVersion]:
    return await get_caption_service().list_versions(asset_id, db)
