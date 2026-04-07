"""Real-ESRGAN upscaling provider."""
from __future__ import annotations
import time
from pathlib import Path
from typing import Any, Optional
from providers.base import ProviderBase

class RealESRGANProvider(ProviderBase):
    """Real-ESRGAN x4+ upscaling provider (non-destructive).

    Registered under 'upscaling' type — not ImageEditor, since upscaling
    doesn't implement flip/rotate/crop operations.
    """

    provider_id = "realesrgan"
    display_name = "Real-ESRGAN x4+"
    provider_type = "upscaling"
    requires_gpu = True
    vram_mb = 1500

    name = "realesrgan"
    version = "x4plus"

    def __init__(self, scale: int = 4, model_name: str = "RealESRGAN_x4plus", **kwargs):
        self.scale = scale
        self.model_name = model_name
        self._upsampler = None
        self._load_error: Optional[str] = None

    async def is_available(self) -> bool:
        try:
            from realesrgan import RealESRGANer  # noqa: F401
            return True
        except ImportError:
            return False

    def _load(self):
        if self._upsampler is not None or self._load_error:
            return
        try:
            import torch
            from basicsr.archs.rrdbnet_arch import RRDBNet
            from realesrgan import RealESRGANer

            # Select correct arch
            if self.model_name in ("RealESRGAN_x4plus", "RealESRGAN_x4plus_anime_6B"):
                num_block = 6 if "anime" in self.model_name else 23
                model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64,
                                num_block=num_block, num_grow_ch=32, scale=4)
            else:
                model = RRDBNet(num_in_ch=3, num_out_ch=3, num_feat=64,
                                num_block=23, num_grow_ch=32, scale=4)

            cache_dir = Path.home() / ".cache" / "draco"
            cache_dir.mkdir(parents=True, exist_ok=True)
            model_path = cache_dir / f"{self.model_name}.pth"

            device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
            self._upsampler = RealESRGANer(
                scale=self.scale,
                model_path=str(model_path),
                model=model,
                tile=512,
                tile_pad=10,
                pre_pad=0,
                half=torch.cuda.is_available(),
                device=device,
            )
        except Exception as e:
            self._load_error = str(e)

    async def apply(self, image_path: str, output_path: str, options: Optional[dict] = None) -> str:
        """Upscale image and save to output_path. Returns output_path."""
        self._load()
        if self._load_error:
            raise RuntimeError(f"RealESRGAN not available: {self._load_error}")
        try:
            import cv2
            import numpy as np

            img = cv2.imread(image_path, cv2.IMREAD_UNCHANGED)
            if img is None:
                raise ValueError(f"Could not read image: {image_path}")

            output, _ = self._upsampler.enhance(img, outscale=self.scale)
            Path(output_path).parent.mkdir(parents=True, exist_ok=True)
            cv2.imwrite(output_path, output)
            return output_path
        except Exception as e:
            raise RuntimeError(f"Upscaling failed: {e}")

    async def health_check(self) -> dict[str, Any]:
        self._load()
        return {
            "ok": self._load_error is None,
            "provider": self.name,
            "version": self.version,
            "latency_ms": 0,
            "details": {
                "model": self.model_name,
                "scale": self.scale,
                "error": self._load_error,
            },
        }
