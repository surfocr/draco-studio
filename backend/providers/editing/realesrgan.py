"""Real-ESRGAN upscaling image editor provider."""
from __future__ import annotations
import time
from pathlib import Path
from typing import Optional
from providers.base import ImageEditor

class RealESRGANProvider(ImageEditor):
    """Real-ESRGAN x4+ upscaling provider (non-destructive)."""

    name = "realesrgan"
    version = "x4plus"

    def __init__(self, scale: int = 4, model_name: str = "RealESRGAN_x4plus"):
        self.scale = scale
        self.model_name = model_name
        self._upsampler = None
        self._load_error: Optional[str] = None

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

    async def health_check(self) -> dict:
        self._load()
        return {
            "provider": self.name,
            "version": self.version,
            "model": self.model_name,
            "scale": self.scale,
            "available": self._load_error is None,
            "error": self._load_error,
        }
