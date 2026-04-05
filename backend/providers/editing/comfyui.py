"""
ComfyUI provider for AI image editing operations.
Connects to ComfyUI API (default: http://localhost:8188).
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any

import aiohttp

from providers.base import (
    AIEditResult,
    AIImageEditor,
    AIOutpaintingProvider,
    EditRequest,
    OutpaintRequest,
)

logger = logging.getLogger(__name__)

# ── Workflow Templates ─────────────────────────────────────────────────────────

OUTPAINT_WORKFLOW: dict[str, Any] = {
    "1": {
        "class_type": "LoadImage",
        "inputs": {"image": "__INPUT_IMAGE__"},
    },
    "2": {
        "class_type": "ImagePadForOutpaint",
        "inputs": {
            "image": ["1", 0],
            "left": "__LEFT__",
            "top": "__TOP__",
            "right": "__RIGHT__",
            "bottom": "__BOTTOM__",
            "feathering": 40,
        },
    },
    "3": {
        "class_type": "VAEEncodeForInpaint",
        "inputs": {
            "pixels": ["2", 0],
            "vae": ["5", 0],
            "mask": ["2", 1],
            "grow_mask_by": 8,
        },
    },
    "4": {
        "class_type": "KSampler",
        "inputs": {
            "model": ["6", 0],
            "positive": ["7", 0],
            "negative": ["8", 0],
            "latent_image": ["3", 0],
            "seed": "__SEED__",
            "steps": "__STEPS__",
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": "__STRENGTH__",
        },
    },
    "5": {
        "class_type": "VAELoader",
        "inputs": {"vae_name": "vae-ft-mse-840000-ema-pruned.safetensors"},
    },
    "6": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "__MODEL__"},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["6", 1], "text": "__PROMPT__"},
    },
    "8": {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["6", 1], "text": "__NEGATIVE__"},
    },
    "9": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["4", 0], "vae": ["5", 0]},
    },
    "10": {
        "class_type": "SaveImage",
        "inputs": {"images": ["9", 0], "filename_prefix": "__OUTPUT_PREFIX__"},
    },
}

UPSCALE_WORKFLOW: dict[str, Any] = {
    "1": {
        "class_type": "LoadImage",
        "inputs": {"image": "__INPUT_IMAGE__"},
    },
    "2": {
        "class_type": "UpscaleModelLoader",
        "inputs": {"model_name": "RealESRGAN_x4plus.pth"},
    },
    "3": {
        "class_type": "ImageUpscaleWithModel",
        "inputs": {"upscale_model": ["2", 0], "image": ["1", 0]},
    },
    "4": {
        "class_type": "SaveImage",
        "inputs": {"images": ["3", 0], "filename_prefix": "__OUTPUT_PREFIX__"},
    },
}

INPAINT_WORKFLOW: dict[str, Any] = {
    "1": {
        "class_type": "LoadImage",
        "inputs": {"image": "__INPUT_IMAGE__"},
    },
    "2": {
        "class_type": "LoadImage",
        "inputs": {"image": "__MASK_IMAGE__"},
    },
    "3": {
        "class_type": "VAEEncodeForInpaint",
        "inputs": {
            "pixels": ["1", 0],
            "vae": ["6", 0],
            "mask": ["2", 0],
            "grow_mask_by": 6,
        },
    },
    "4": {
        "class_type": "KSampler",
        "inputs": {
            "model": ["5", 0],
            "positive": ["7", 0],
            "negative": ["8", 0],
            "latent_image": ["3", 0],
            "seed": "__SEED__",
            "steps": "__STEPS__",
            "cfg": 7.5,
            "sampler_name": "euler_ancestral",
            "scheduler": "normal",
            "denoise": 1.0,
        },
    },
    "5": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {"ckpt_name": "__MODEL__"},
    },
    "6": {
        "class_type": "VAELoader",
        "inputs": {"vae_name": "vae-ft-mse-840000-ema-pruned.safetensors"},
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["5", 1], "text": "__PROMPT__"},
    },
    "8": {
        "class_type": "CLIPTextEncode",
        "inputs": {"clip": ["5", 1], "text": "__NEGATIVE__"},
    },
    "9": {
        "class_type": "VAEDecode",
        "inputs": {"samples": ["4", 0], "vae": ["6", 0]},
    },
    "10": {
        "class_type": "SaveImage",
        "inputs": {"images": ["9", 0], "filename_prefix": "__OUTPUT_PREFIX__"},
    },
}


class ComfyUIProvider(AIOutpaintingProvider, AIImageEditor):
    provider_id = "comfyui"
    display_name = "ComfyUI (Local)"
    requires_gpu = True
    vram_mb = 4000

    def __init__(
        self,
        base_url: str = "http://localhost:8188",
        model: str = "v1-5-pruned-emaonly.safetensors",
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def is_available(self) -> bool:
        try:
            session = self._get_session()
            async with session.get(
                f"{self.base_url}/system_stats",
                timeout=aiohttp.ClientTimeout(total=3),
            ) as resp:
                return resp.status == 200
        except Exception:
            return False

    async def health_check(self) -> dict[str, Any]:
        t0 = time.monotonic()
        try:
            session = self._get_session()
            async with session.get(
                f"{self.base_url}/system_stats",
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                latency = int((time.monotonic() - t0) * 1000)
                if resp.status == 200:
                    data = await resp.json()
                    return {"ok": True, "latency_ms": latency, "details": data}
                return {"ok": False, "latency_ms": latency, "details": {"status": resp.status}}
        except Exception as e:
            return {"ok": False, "latency_ms": -1, "details": {"error": str(e)}}

    async def get_supported_operations(self) -> list[str]:
        return ["outpaint", "upscale", "inpaint", "replace_background"]

    async def edit(self, request: EditRequest) -> AIEditResult:
        op = request.operation
        t0 = time.monotonic()
        try:
            if op == "upscale":
                return await self.upscale(request.asset_id)
            elif op == "inpaint":
                mask_path = request.params.get("mask_path", "")
                prompt = request.params.get("prompt", "")
                return await self.inpaint(request.asset_id, mask_path, prompt)
            elif op == "replace_background":
                bg_prompt = request.params.get("background_prompt", "plain studio background")
                return await self.replace_background(request.asset_id, bg_prompt)
            else:
                return AIEditResult(
                    success=False,
                    output_path="",
                    operation=op,
                    params_used=request.params,
                    provider=self.provider_id,
                    model=self.model,
                    latency_ms=0,
                    error=f"Unsupported operation: {op}",
                )
        except Exception as e:
            return AIEditResult(
                success=False,
                output_path="",
                operation=op,
                params_used=request.params,
                provider=self.provider_id,
                model=self.model,
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(e),
            )

    async def outpaint(self, request: OutpaintRequest) -> AIEditResult:
        t0 = time.monotonic()
        try:
            from PIL import Image

            img = Image.open(request.asset_id)
            src_w, src_h = img.size

            pad_left = max(0, (request.target_width - src_w) // 2)
            pad_right = max(0, request.target_width - src_w - pad_left)
            pad_top = max(0, (request.target_height - src_h) // 2)
            pad_bottom = max(0, request.target_height - src_h - pad_top)

            output_prefix = f"draco_outpaint_{uuid.uuid4().hex[:8]}"
            workflow = json.loads(json.dumps(OUTPAINT_WORKFLOW))

            workflow["1"]["inputs"]["image"] = request.asset_id
            workflow["2"]["inputs"]["left"] = pad_left
            workflow["2"]["inputs"]["top"] = pad_top
            workflow["2"]["inputs"]["right"] = pad_right
            workflow["2"]["inputs"]["bottom"] = pad_bottom
            workflow["4"]["inputs"]["seed"] = uuid.uuid4().int % (2**32)
            workflow["4"]["inputs"]["steps"] = request.steps
            workflow["4"]["inputs"]["denoise"] = request.strength
            workflow["6"]["inputs"]["ckpt_name"] = self.model
            workflow["7"]["inputs"]["text"] = request.prompt or ""
            workflow["8"]["inputs"]["text"] = request.negative_prompt or "blurry, artifacts, distorted"
            workflow["10"]["inputs"]["filename_prefix"] = output_prefix

            prompt_id = await self._queue_workflow(workflow)
            result_data = await self._poll_result(prompt_id)
            output_path = self._extract_output_path(result_data, output_prefix)
            latency = int((time.monotonic() - t0) * 1000)

            return AIEditResult(
                success=True,
                output_path=output_path,
                operation="outpaint",
                params_used={
                    "target_width": request.target_width,
                    "target_height": request.target_height,
                },
                provider=self.provider_id,
                model=self.model,
                latency_ms=latency,
            )
        except Exception as e:
            return AIEditResult(
                success=False,
                output_path="",
                operation="outpaint",
                params_used={},
                provider=self.provider_id,
                model=self.model,
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(e),
            )

    async def upscale(self, asset_id: str, scale: int = 4) -> AIEditResult:
        t0 = time.monotonic()
        try:
            output_prefix = f"draco_upscale_{uuid.uuid4().hex[:8]}"
            workflow = json.loads(json.dumps(UPSCALE_WORKFLOW))
            workflow["1"]["inputs"]["image"] = asset_id
            workflow["4"]["inputs"]["filename_prefix"] = output_prefix

            prompt_id = await self._queue_workflow(workflow)
            result_data = await self._poll_result(prompt_id)
            output_path = self._extract_output_path(result_data, output_prefix)

            return AIEditResult(
                success=True,
                output_path=output_path,
                operation="upscale",
                params_used={"scale": scale},
                provider=self.provider_id,
                model="RealESRGAN_x4plus",
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        except Exception as e:
            return AIEditResult(
                success=False,
                output_path="",
                operation="upscale",
                params_used={},
                provider=self.provider_id,
                model=self.model,
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(e),
            )

    async def inpaint(self, asset_id: str, mask_path: str, prompt: str) -> AIEditResult:
        t0 = time.monotonic()
        try:
            output_prefix = f"draco_inpaint_{uuid.uuid4().hex[:8]}"
            workflow = json.loads(json.dumps(INPAINT_WORKFLOW))
            workflow["1"]["inputs"]["image"] = asset_id
            workflow["2"]["inputs"]["image"] = mask_path
            workflow["4"]["inputs"]["seed"] = uuid.uuid4().int % (2**32)
            workflow["4"]["inputs"]["steps"] = 30
            workflow["5"]["inputs"]["ckpt_name"] = self.model
            workflow["7"]["inputs"]["text"] = prompt
            workflow["8"]["inputs"]["text"] = "blurry, artifacts, distorted"
            workflow["10"]["inputs"]["filename_prefix"] = output_prefix

            prompt_id = await self._queue_workflow(workflow)
            result_data = await self._poll_result(prompt_id)
            output_path = self._extract_output_path(result_data, output_prefix)

            return AIEditResult(
                success=True,
                output_path=output_path,
                operation="inpaint",
                params_used={"prompt": prompt},
                provider=self.provider_id,
                model=self.model,
                latency_ms=int((time.monotonic() - t0) * 1000),
            )
        except Exception as e:
            return AIEditResult(
                success=False,
                output_path="",
                operation="inpaint",
                params_used={},
                provider=self.provider_id,
                model=self.model,
                latency_ms=int((time.monotonic() - t0) * 1000),
                error=str(e),
            )

    async def replace_background(self, asset_id: str, background_prompt: str) -> AIEditResult:
        return await self.inpaint(asset_id, "", f"{background_prompt}, background replacement")

    async def auto_fit_subject(
        self,
        asset_id: str,
        target_width: int,
        target_height: int,
    ) -> AIEditResult:
        request = OutpaintRequest(
            asset_id=asset_id,
            target_width=target_width,
            target_height=target_height,
            prompt="seamless background continuation",
            negative_prompt="artifacts, distortion, blur",
        )
        return await self.outpaint(request)

    async def _queue_workflow(self, workflow: dict[str, Any]) -> str:
        session = self._get_session()
        payload = {"prompt": workflow, "client_id": "draco_studio"}
        async with session.post(
            f"{self.base_url}/prompt",
            json=payload,
            timeout=aiohttp.ClientTimeout(total=30),
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise RuntimeError(f"ComfyUI queue error {resp.status}: {text}")
            data = await resp.json()
            return data["prompt_id"]

    async def _poll_result(self, prompt_id: str, timeout: int = 120) -> dict[str, Any]:
        session = self._get_session()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            async with session.get(
                f"{self.base_url}/history/{prompt_id}",
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if prompt_id in data:
                        return data[prompt_id]
            await asyncio.sleep(1.5)
        raise TimeoutError(f"ComfyUI timed out waiting for prompt {prompt_id}")

    def _extract_output_path(self, result_data: dict[str, Any], prefix: str) -> str:
        outputs = result_data.get("outputs", {})
        for node_id, node_output in outputs.items():
            images = node_output.get("images", [])
            for img in images:
                if img.get("filename", "").startswith(prefix):
                    return img.get("filename", "")
        return ""
