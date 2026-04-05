"""
Basic image editor using Pillow for non-AI operations.
No GPU required.
"""
from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from providers.base import AIEditResult, AIImageEditor, EditRequest


class BasicImageEditor(AIImageEditor):
    provider_id = "basic_editor"
    display_name = "Basic Image Editor (PIL)"
    requires_gpu = False
    vram_mb = 0

    async def is_available(self) -> bool:
        try:
            from PIL import Image  # noqa: F401
            return True
        except ImportError:
            return False

    async def health_check(self) -> dict[str, Any]:
        ok = await self.is_available()
        return {"ok": ok, "latency_ms": 0, "details": {}}

    async def get_supported_operations(self) -> list[str]:
        return [
            "crop_to_aspect",
            "extend_canvas",
            "flip_horizontal",
            "rotate",
            "resize",
            "normalize_exposure",
            "remove_border",
        ]

    async def edit(self, request: EditRequest) -> AIEditResult:
        op = request.operation
        params = request.params
        t0 = time.monotonic()
        try:
            if op == "flip_horizontal":
                return await self.flip_horizontal(request.asset_id)
            elif op == "rotate":
                return await self.rotate(request.asset_id, params.get("degrees", 90))
            elif op == "resize":
                return await self.resize(
                    request.asset_id,
                    params.get("width", 512),
                    params.get("height", 512),
                    params.get("mode", "lanczos"),
                )
            elif op == "crop_to_aspect":
                return await self.crop_to_aspect(
                    request.asset_id,
                    params.get("target_w", 1),
                    params.get("target_h", 1),
                )
            elif op == "extend_canvas":
                fill = params.get("fill_color", [128, 128, 128])
                return await self.extend_canvas(
                    request.asset_id,
                    params.get("target_w", 512),
                    params.get("target_h", 512),
                    tuple(fill),
                )
            elif op == "normalize_exposure":
                return await self.normalize_exposure(request.asset_id)
            elif op == "remove_border":
                return await self.remove_border(request.asset_id)
            else:
                return AIEditResult(
                    success=False,
                    output_path="",
                    operation=op,
                    params_used=params,
                    provider=self.provider_id,
                    model="pillow",
                    latency_ms=0,
                    error=f"Unknown operation: {op}",
                )
        except Exception as e:
            return AIEditResult(
                success=False,
                output_path="",
                operation=op,
                params_used=params,
                provider=self.provider_id,
                model="pillow",
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(e),
            )

    def _output_path(self, source_path: str, suffix: str) -> str:
        p = Path(source_path)
        return str(p.parent / f"{p.stem}_{suffix}{p.suffix}")

    async def crop_to_aspect(self, asset_id: str, target_w: int, target_h: int) -> AIEditResult:
        t0 = time.monotonic()
        from PIL import Image

        img = Image.open(asset_id)
        src_w, src_h = img.size
        target_ratio = target_w / target_h
        src_ratio = src_w / src_h
        if src_ratio > target_ratio:
            new_w = int(src_h * target_ratio)
            left = (src_w - new_w) // 2
            img = img.crop((left, 0, left + new_w, src_h))
        else:
            new_h = int(src_w / target_ratio)
            top = (src_h - new_h) // 2
            img = img.crop((0, top, src_w, top + new_h))
        out = self._output_path(asset_id, f"crop_{target_w}x{target_h}")
        img.save(out)
        return AIEditResult(
            success=True,
            output_path=out,
            operation="crop_to_aspect",
            params_used={"target_w": target_w, "target_h": target_h},
            provider=self.provider_id,
            model="pillow",
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    async def extend_canvas(
        self,
        asset_id: str,
        target_w: int,
        target_h: int,
        fill_color: tuple = (128, 128, 128),
    ) -> AIEditResult:
        t0 = time.monotonic()
        from PIL import Image

        img = Image.open(asset_id)
        src_w, src_h = img.size
        new_img = Image.new("RGB", (target_w, target_h), fill_color)
        paste_x = (target_w - src_w) // 2
        paste_y = (target_h - src_h) // 2
        new_img.paste(img, (paste_x, paste_y))
        out = self._output_path(asset_id, f"canvas_{target_w}x{target_h}")
        new_img.save(out)
        return AIEditResult(
            success=True,
            output_path=out,
            operation="extend_canvas",
            params_used={"target_w": target_w, "target_h": target_h},
            provider=self.provider_id,
            model="pillow",
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    async def flip_horizontal(self, asset_id: str) -> AIEditResult:
        t0 = time.monotonic()
        from PIL import Image

        img = Image.open(asset_id).transpose(Image.FLIP_LEFT_RIGHT)
        out = self._output_path(asset_id, "fliph")
        img.save(out)
        return AIEditResult(
            success=True,
            output_path=out,
            operation="flip_horizontal",
            params_used={},
            provider=self.provider_id,
            model="pillow",
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    async def rotate(self, asset_id: str, degrees: int) -> AIEditResult:
        t0 = time.monotonic()
        from PIL import Image

        img = Image.open(asset_id).rotate(-degrees, expand=True)
        out = self._output_path(asset_id, f"rot{degrees}")
        img.save(out)
        return AIEditResult(
            success=True,
            output_path=out,
            operation="rotate",
            params_used={"degrees": degrees},
            provider=self.provider_id,
            model="pillow",
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    async def resize(self, asset_id: str, width: int, height: int, mode: str = "lanczos") -> AIEditResult:
        t0 = time.monotonic()
        from PIL import Image

        resample_map = {
            "lanczos": Image.LANCZOS,
            "nearest": Image.NEAREST,
            "bilinear": Image.BILINEAR,
        }
        resample = resample_map.get(mode, Image.LANCZOS)
        img = Image.open(asset_id).resize((width, height), resample)
        out = self._output_path(asset_id, f"resize_{width}x{height}")
        img.save(out)
        return AIEditResult(
            success=True,
            output_path=out,
            operation="resize",
            params_used={"width": width, "height": height, "mode": mode},
            provider=self.provider_id,
            model="pillow",
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    async def normalize_exposure(self, asset_id: str) -> AIEditResult:
        t0 = time.monotonic()
        from PIL import Image, ImageOps

        img = Image.open(asset_id)
        if img.mode != "RGB":
            img = img.convert("RGB")
        img = ImageOps.autocontrast(img, cutoff=0.5)
        out = self._output_path(asset_id, "norm_exp")
        img.save(out)
        return AIEditResult(
            success=True,
            output_path=out,
            operation="normalize_exposure",
            params_used={},
            provider=self.provider_id,
            model="pillow",
            latency_ms=int((time.monotonic() - t0) * 1000),
        )

    async def remove_border(self, asset_id: str) -> AIEditResult:
        t0 = time.monotonic()
        import numpy as np
        from PIL import Image

        img = Image.open(asset_id)
        bg = Image.new(img.mode, img.size, img.getpixel((0, 0)))
        diff = Image.fromarray(
            np.abs(np.array(img, dtype=np.int16) - np.array(bg, dtype=np.int16)).astype(np.uint8)
        )
        bbox = diff.getbbox()
        if bbox:
            img = img.crop(bbox)
        out = self._output_path(asset_id, "noborder")
        img.save(out)
        return AIEditResult(
            success=True,
            output_path=out,
            operation="remove_border",
            params_used={},
            provider=self.provider_id,
            model="pillow",
            latency_ms=int((time.monotonic() - t0) * 1000),
        )
