"""
Helpers for choosing the most useful representative asset for review flows.
"""
from __future__ import annotations

from models.asset import Asset


def asset_quality_tuple(asset: Asset) -> tuple[float, ...]:
    """
    Prefer the asset most likely to be useful for LoRA training.

    The ordering deliberately favors the existing composite score first, then
    training usefulness and technical/face quality, while de-prioritizing
    already-redundant images.
    """
    pixel_count = float((asset.width or 0) * (asset.height or 0))
    return (
        float(asset.composite_score or 0.0),
        float(asset.training_usefulness or 0.0),
        float(asset.technical_quality or 0.0),
        float(asset.face_quality or 0.0),
        float(asset.aesthetic_score or 0.0),
        float(asset.uniqueness_score or 0.0),
        -float(asset.redundancy_score or 0.0),
        pixel_count,
    )


def pick_best_asset(asset_ids: list[str], asset_lookup: dict[str, Asset]) -> str:
    """Return the highest-quality asset id from the provided candidates."""
    return max(
        asset_ids,
        key=lambda asset_id: (
            asset_quality_tuple(asset_lookup[asset_id]),
            asset_lookup[asset_id].id,
        ),
    )
