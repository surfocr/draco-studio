from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path


def _bootstrap_backend_path() -> None:
    repo_root = Path(__file__).resolve().parent.parent
    backend_dir = repo_root / "backend"
    if str(backend_dir) not in sys.path:
        sys.path.insert(0, str(backend_dir))


async def _main() -> int:
    _bootstrap_backend_path()

    try:
        from providers.registry import (
            get_registry,
            register_default_providers,
            register_optional_providers,
        )
    except Exception as exc:
        print(f"[model-health] Could not import provider registry: {exc}")
        return 1

    registry = get_registry()
    register_default_providers(registry)
    register_optional_providers(registry)
    checks: list[tuple[str, str, str]] = [
        ("caption", "ollama", "Ollama"),
        ("embedding", "fastembed", "FastEmbed"),
        ("face_detection", "insightface", "InsightFace"),
        ("scene_understanding", "clip_scene", "CLIP Scene"),
    ]

    overall_ok = True
    for provider_type, provider_name, label in checks:
        try:
            provider = registry.get(provider_type, provider_name)
        except Exception as exc:
            print(f"[model-health] {label}: unavailable ({exc})")
            overall_ok = False
            continue

        if provider is None:
            print(f"[model-health] {label}: unavailable (provider not registered)")
            overall_ok = False
            continue

        try:
            health = await provider.health_check()
        except Exception as exc:
            print(f"[model-health] {label}: health check failed ({exc})")
            overall_ok = False
            continue

        ok = bool(health.get("ok"))
        details = health.get("details") or {}
        summary_bits: list[str] = []
        if "device" in details and details["device"]:
            summary_bits.append(f"device={details['device']}")
        if "model" in details and details["model"]:
            summary_bits.append(f"model={details['model']}")
        if "error" in details and details["error"]:
            summary_bits.append(f"error={details['error']}")
        suffix = f" ({', '.join(summary_bits)})" if summary_bits else ""
        print(f"[model-health] {label}: {'ok' if ok else 'not ready'}{suffix}")
        overall_ok = overall_ok and ok

    if not overall_ok:
        print("[model-health] Some optional local providers are not ready. Draco can still start.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
