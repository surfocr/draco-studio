"""LAION Aesthetic Predictor v2 quality scorer provider."""
from __future__ import annotations
import time
from typing import Optional
from pathlib import Path
from providers.base import QualityScorer

class LAIONAestheticProvider(QualityScorer):
    """LAION Aesthetic Predictor v2 — linear head on CLIP ViT-L/14 embeddings."""

    name = "laion_aesthetic"
    version = "v2"

    def __init__(self):
        self._model = None
        self._clip_model = None
        self._clip_preprocess = None
        self._device = None
        self._load_error: Optional[str] = None

    def _load(self):
        if self._model is not None or self._load_error:
            return
        try:
            import torch
            import clip
            import torch.nn as nn

            self._device = "cuda" if torch.cuda.is_available() else "cpu"

            class AestheticPredictor(nn.Module):
                def __init__(self, input_size):
                    super().__init__()
                    self.layers = nn.Sequential(
                        nn.Linear(input_size, 1024), nn.Dropout(0.2),
                        nn.Linear(1024, 128), nn.Dropout(0.2),
                        nn.Linear(128, 64), nn.Dropout(0.1),
                        nn.Linear(64, 16), nn.Linear(16, 1),
                    )
                def forward(self, x):
                    return self.layers(x)

            self._clip_model, self._clip_preprocess = clip.load("ViT-L/14", device=self._device)

            # Try to load weights — download if not cached
            import torch, os
            from pathlib import Path
            cache = Path.home() / ".cache" / "draco" / "aesthetic_predictor_v2_5.pth"
            cache.parent.mkdir(parents=True, exist_ok=True)
            if not cache.exists():
                import urllib.request
                url = "https://github.com/christophschuhmann/improved-aesthetic-predictor/raw/main/sac+logos+ava1-l14-linearMSE.pth"
                urllib.request.urlretrieve(url, cache)

            self._model = AestheticPredictor(768)
            state = torch.load(cache, map_location=self._device)
            self._model.load_state_dict(state)
            self._model.to(self._device)
            self._model.eval()
        except Exception as e:
            self._load_error = str(e)

    async def score(self, image_path: str) -> float:
        """Return aesthetic score in [0, 1] (normalized from LAION's 1–10 scale)."""
        self._load()
        if self._load_error:
            return 0.5  # neutral fallback
        try:
            import torch
            from PIL import Image

            t0 = time.monotonic()
            img = Image.open(image_path).convert("RGB")
            inp = self._clip_preprocess(img).unsqueeze(0).to(self._device)
            with torch.no_grad():
                feat = self._clip_model.encode_image(inp)
                feat = feat / feat.norm(dim=-1, keepdim=True)
                score_raw = self._model(feat.float()).item()
            # LAION scores are roughly 1–9; normalize to 0–1
            return max(0.0, min(1.0, (score_raw - 1.0) / 8.0))
        except Exception:
            return 0.5

    async def score_batch(self, image_paths: list[str]) -> list[float]:
        return [await self.score(p) for p in image_paths]

    async def health_check(self) -> dict:
        self._load()
        return {
            "provider": self.name,
            "version": self.version,
            "available": self._load_error is None,
            "device": self._device or "unloaded",
            "error": self._load_error,
        }
