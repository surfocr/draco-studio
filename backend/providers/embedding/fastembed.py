"""
FastEmbedProvider — CLIP ViT-B/32 image embeddings via FastEmbed (ONNX).
Integrated with Qdrant embedded for storage + similarity search.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any

import numpy as np
from PIL import Image

from config import settings
from providers.base import EmbeddingProvider, EmbeddingResult

logger = logging.getLogger(__name__)

try:
    from fastembed import ImageEmbedding
    _FASTEMBED_AVAILABLE = True
except ImportError:
    _FASTEMBED_AVAILABLE = False
    logger.warning("fastembed not installed — embedding provider unavailable")

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import (
        Distance,
        FieldCondition,
        Filter,
        MatchValue,
        PointIdsList,
        PointStruct,
        VectorParams,
    )
    _QDRANT_AVAILABLE = True
except ImportError:
    _QDRANT_AVAILABLE = False
    logger.warning("qdrant-client not installed — vector search unavailable")


EMBEDDING_DIM = 512  # CLIP ViT-B/32 output dimension


class FastEmbedProvider(EmbeddingProvider):
    provider_id = "fastembed_clip"
    display_name = "FastEmbed CLIP ViT-B/32"
    requires_gpu = False
    vram_mb = 0  # CPU-only via ONNX

    def __init__(self) -> None:
        self._model: Any | None = None
        self._text_model: Any | None = None
        self._qdrant: Any | None = None
        self._init_lock = asyncio.Lock()
        self._text_init_lock = asyncio.Lock()

    async def is_available(self) -> bool:
        return _FASTEMBED_AVAILABLE and _QDRANT_AVAILABLE

    async def health_check(self) -> dict[str, Any]:
        t0 = time.monotonic()
        ok = await self.is_available()
        return {
            "ok": ok,
            "latency_ms": round((time.monotonic() - t0) * 1000, 1),
            "details": {
                "fastembed": _FASTEMBED_AVAILABLE,
                "qdrant": _QDRANT_AVAILABLE,
                "model_loaded": self._model is not None,
                "qdrant_connected": self._qdrant is not None,
            },
        }

    async def load(self) -> None:
        async with self._init_lock:
            if self._model is None and _FASTEMBED_AVAILABLE:
                loop = asyncio.get_event_loop()
                self._model = await loop.run_in_executor(
                    None,
                    lambda: ImageEmbedding(model_name=settings.FASTEMBED_MODEL),
                )
                logger.info("Loaded FastEmbed model: %s", settings.FASTEMBED_MODEL)

            if self._qdrant is None and _QDRANT_AVAILABLE:
                settings.qdrant_path.mkdir(parents=True, exist_ok=True)
                loop = asyncio.get_event_loop()
                self._qdrant = await loop.run_in_executor(
                    None,
                    lambda: QdrantClient(path=str(settings.qdrant_path)),
                )
                await self._ensure_collection(settings.QDRANT_COLLECTION)
                logger.info("Connected to Qdrant at %s", settings.qdrant_path)

    async def _ensure_model(self) -> None:
        if self._model is None:
            await self.load()

    async def _ensure_collection(self, collection_name: str) -> None:
        """Create collection if it doesn't exist."""
        if not _QDRANT_AVAILABLE or self._qdrant is None:
            return

        def _create() -> None:
            existing = [c.name for c in self._qdrant.get_collections().collections]
            if collection_name not in existing:
                self._qdrant.create_collection(
                    collection_name=collection_name,
                    vectors_config=VectorParams(
                        size=EMBEDDING_DIM,
                        distance=Distance.COSINE,
                    ),
                )
                logger.info("Created Qdrant collection: %s", collection_name)

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _create)

    # ── EmbeddingProvider interface ───────────────────────────────────────────

    async def embed_image(self, image_path: str) -> EmbeddingResult:
        await self._ensure_model()
        if self._model is None:
            raise RuntimeError("FastEmbed model not loaded")

        t0 = time.monotonic()

        def _embed() -> list[float]:
            embeddings = list(self._model.embed([image_path]))
            return embeddings[0].tolist()

        loop = asyncio.get_event_loop()
        vector = await loop.run_in_executor(None, _embed)
        latency_ms = round((time.monotonic() - t0) * 1000)

        return EmbeddingResult(
            vector=vector,
            dimension=len(vector),
            model=settings.FASTEMBED_MODEL,
            provider=self.provider_id,
            latency_ms=latency_ms,
        )

    async def embed_batch(
        self, image_paths: list[str], batch_size: int | None = None
    ) -> list[EmbeddingResult]:
        await self._ensure_model()
        if self._model is None:
            raise RuntimeError("FastEmbed model not loaded")

        bs = batch_size or settings.EMBEDDING_BATCH_SIZE
        results: list[EmbeddingResult] = []

        for i in range(0, len(image_paths), bs):
            batch = image_paths[i : i + bs]
            t0 = time.monotonic()

            def _embed_batch(paths: list[str]) -> list[list[float]]:
                return [e.tolist() for e in self._model.embed(paths)]

            loop = asyncio.get_event_loop()
            vectors = await loop.run_in_executor(None, _embed_batch, batch)
            latency_ms = round((time.monotonic() - t0) * 1000)

            for j, vector in enumerate(vectors):
                results.append(
                    EmbeddingResult(
                        vector=vector,
                        dimension=len(vector),
                        model=settings.FASTEMBED_MODEL,
                        provider=self.provider_id,
                        latency_ms=latency_ms // max(len(batch), 1),
                    )
                )

        return results

    async def upsert_embedding(
        self,
        asset_id: str,
        vector: list[float],
        payload: dict | None = None,
    ) -> None:
        await self._ensure_model()
        if not _QDRANT_AVAILABLE or self._qdrant is None:
            return

        point = PointStruct(
            id=self._asset_id_to_point_id(asset_id),
            vector=vector,
            payload={"asset_id": asset_id, **(payload or {})},
        )

        def _upsert() -> None:
            self._qdrant.upsert(
                collection_name=settings.QDRANT_COLLECTION,
                points=[point],
            )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _upsert)

    async def upsert_batch(
        self, items: list[tuple[str, list[float]]], payload_map: dict | None = None
    ) -> None:
        """Upsert many embeddings efficiently."""
        if not _QDRANT_AVAILABLE or self._qdrant is None:
            return

        points = [
            PointStruct(
                id=self._asset_id_to_point_id(asset_id),
                vector=vector,
                payload={
                    "asset_id": asset_id,
                    **((payload_map or {}).get(asset_id, {})),
                },
            )
            for asset_id, vector in items
        ]

        def _upsert() -> None:
            self._qdrant.upsert(
                collection_name=settings.QDRANT_COLLECTION,
                points=points,
            )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _upsert)

    async def search_similar(
        self,
        vector: list[float],
        top_k: int = 10,
        threshold: float | None = None,
        filter_project_id: str | None = None,
    ) -> list[tuple[str, float]]:
        """Return [(asset_id, cosine_score), ...] sorted by descending score."""
        if not _QDRANT_AVAILABLE or self._qdrant is None:
            return []

        score_threshold = threshold or settings.SIMILARITY_THRESHOLD

        query_filter = None
        if filter_project_id:
            query_filter = Filter(
                must=[
                    FieldCondition(
                        key="project_id",
                        match=MatchValue(value=filter_project_id),
                    )
                ]
            )

        def _search() -> list[tuple[str, float]]:
            hits = self._qdrant.search(
                collection_name=settings.QDRANT_COLLECTION,
                query_vector=vector,
                limit=top_k,
                score_threshold=score_threshold,
                query_filter=query_filter,
            )
            return [(h.payload["asset_id"], h.score) for h in hits]

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _search)

    async def delete_embedding(self, asset_id: str) -> None:
        if not _QDRANT_AVAILABLE or self._qdrant is None:
            return

        point_id = self._asset_id_to_point_id(asset_id)

        def _delete() -> None:
            self._qdrant.delete(
                collection_name=settings.QDRANT_COLLECTION,
                points_selector=PointIdsList(points=[point_id]),
            )

        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _delete)

    async def get_collection_count(self) -> int:
        if not _QDRANT_AVAILABLE or self._qdrant is None:
            return 0

        def _count() -> int:
            return self._qdrant.count(settings.QDRANT_COLLECTION).count

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _count)

    async def embed_text(self, text: str) -> list[float]:
        """Embed a text query into CLIP space for text-to-image search (512-dim)."""
        async with self._text_init_lock:
            if self._text_model is None and _FASTEMBED_AVAILABLE:
                try:
                    from fastembed import TextEmbedding
                    loop = asyncio.get_event_loop()
                    self._text_model = await loop.run_in_executor(
                        None,
                        lambda: TextEmbedding(model_name="Qdrant/clip-ViT-B-32-text"),
                    )
                    logger.info("Loaded FastEmbed CLIP text model")
                except Exception as exc:
                    logger.warning("Could not load CLIP text model: %s", exc)
                    raise RuntimeError(f"CLIP text model unavailable: {exc}") from exc

        if self._text_model is None:
            raise RuntimeError("FastEmbed text model not loaded")

        def _embed() -> list[float]:
            return list(self._text_model.embed([text]))[0].tolist()

        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, _embed)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _asset_id_to_point_id(asset_id: str) -> int:
        """Convert UUID string to integer point ID for Qdrant."""
        # Qdrant supports UUID strings directly; use as-is if it's a valid UUID
        try:
            return uuid.UUID(asset_id).int & 0xFFFFFFFFFFFFFFFF  # 64-bit int
        except ValueError:
            return abs(hash(asset_id)) % (2**63)
