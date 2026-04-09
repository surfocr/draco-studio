#!/usr/bin/env python3
"""
DRACO v5 — Model Downloader
Downloads required model files that cannot be auto-installed via pip.

Usage:
    python download_models.py
"""

import os
import sys
import hashlib
from pathlib import Path

MODELS_DIR = Path(__file__).parent / "models"
MODELS_DIR.mkdir(parents=True, exist_ok=True)

MODELS = {
    "aesthetic_v2.onnx": {
        "url": "https://github.com/christophschuhmann/improved-aesthetic-predictor/raw/main/sac%2Blogos%2Bava1-l14-linearMSE.onnx",
        "description": "LAION Aesthetic Predictor v2 (linear layer on CLIP ViT-L/14)",
        "required": True,
    },
}


def download_file(url: str, dest: Path) -> bool:
    try:
        import requests
    except ImportError:
        print("  Installing requests...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "requests"])
        import requests

    print(f"  Downloading {dest.name}...")
    try:
        r = requests.get(url, stream=True, timeout=60)
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        downloaded = 0
        with open(dest, "wb") as f:
            for chunk in r.iter_content(chunk_size=65536):
                f.write(chunk)
                downloaded += len(chunk)
                if total:
                    pct = downloaded / total * 100
                    print(f"\r  {pct:.1f}%  ({downloaded // 1024 // 1024}MB / {total // 1024 // 1024}MB)", end="", flush=True)
        print(f"\r  Done — saved to {dest}")
        return True
    except Exception as e:
        print(f"\n  ERROR: {e}")
        if dest.exists():
            dest.unlink()
        return False


def main():
    print("\n╔══════════════════════════════════════════╗")
    print("║  DRACO v5  ·  Model Downloader           ║")
    print("╚══════════════════════════════════════════╝\n")

    all_ok = True
    for filename, info in MODELS.items():
        dest = MODELS_DIR / filename
        print(f"[{filename}]")
        print(f"  {info['description']}")

        if dest.exists():
            size_mb = dest.stat().st_size / 1024 / 1024
            print(f"  Already exists ({size_mb:.1f}MB) — skipping.")
        else:
            ok = download_file(info["url"], dest)
            if not ok and info.get("required"):
                all_ok = False
        print()

    if all_ok:
        print("All models ready. Start the server with:")
        print("  python draco_server.py")
    else:
        print("Some downloads failed. Check your internet connection and retry.")
        sys.exit(1)


if __name__ == "__main__":
    main()
