"""
Application configuration via Pydantic Settings.
All values are driven by environment variables (or .env file).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── Database ──────────────────────────────────────────────────────────────
    DATABASE_URL: str = "sqlite+aiosqlite:///./draco.db"

    # ── Storage ───────────────────────────────────────────────────────────────
    STORAGE_PATH: str = "./data/storage"
    QDRANT_PATH: str = "./data/qdrant"
    QDRANT_COLLECTION: str = "draco_embeddings"
    QDRANT_FACE_COLLECTION: str = "draco_face_embeddings"

    # ── Thumbnails ────────────────────────────────────────────────────────────
    THUMBNAIL_SIZE: int = 512
    THUMBNAIL_SMALL_SIZE: int = 128
    THUMBNAIL_FORMAT: str = "WEBP"
    THUMBNAIL_QUALITY: int = 85

    # ── Workers ───────────────────────────────────────────────────────────────
    MAX_WORKERS: int = 4
    GPU_TASK_CONCURRENCY: int = 1   # serialise GPU tasks; raise for multi-GPU
    VRAM_BUDGET_MB: int = 4096       # total VRAM budget across all loaded models

    # ── Logging ───────────────────────────────────────────────────────────────
    LOG_LEVEL: str = "INFO"
    LOG_JSON: bool = False           # True = structured JSON logging

    # ── Server ────────────────────────────────────────────────────────────────
    HOST: str = "127.0.0.1"
    PORT: int = 18082
    CORS_ORIGINS: list[str] = ["http://localhost:5173", "http://localhost:18082"]
    DEBUG: bool = False

    # ── Provider API keys (all optional) ─────────────────────────────────────
    GEMINI_API_KEY: Optional[str] = None
    OPENAI_API_KEY: Optional[str] = None
    ANTHROPIC_API_KEY: Optional[str] = None
    REPLICATE_API_KEY: Optional[str] = None
    FAL_API_KEY: Optional[str] = None
    OPENROUTER_API_KEY: Optional[str] = None

    # ── Ollama ────────────────────────────────────────────────────────────────
    OLLAMA_BASE_URL: str = "http://localhost:11434"
    OLLAMA_TIMEOUT: int = 120

    # ── InsightFace ───────────────────────────────────────────────────────────
    INSIGHTFACE_MODEL: str = "buffalo_l"
    INSIGHTFACE_DET_THRESH: float = 0.5
    INSIGHTFACE_CTX_ID: int = 0      # GPU device id; -1 = CPU

    # ── FastEmbed / Qdrant ────────────────────────────────────────────────────
    FASTEMBED_MODEL: str = "Qdrant/clip-ViT-B-32-visual"
    EMBEDDING_BATCH_SIZE: int = 32
    SIMILARITY_THRESHOLD: float = 0.95
    FACE_SIMILARITY_THRESHOLD: float = 0.80
    PHASH_THRESHOLD: int = 8          # Hamming distance for near-duplicates

    # ── Quality scoring weights ───────────────────────────────────────────────
    QUALITY_WEIGHT_SHARPNESS: float = 0.20
    QUALITY_WEIGHT_FACE: float = 0.20
    QUALITY_WEIGHT_AESTHETIC: float = 0.15
    QUALITY_WEIGHT_BRIGHTNESS: float = 0.10
    QUALITY_WEIGHT_CONTRAST: float = 0.10
    QUALITY_WEIGHT_SATURATION: float = 0.05
    QUALITY_WEIGHT_FACE_CENTER: float = 0.10
    QUALITY_WEIGHT_BACKGROUND: float = 0.05
    QUALITY_WEIGHT_RESOLUTION: float = 0.05

    # ── Data dir helper ───────────────────────────────────────────────────────
    @property
    def storage_path(self) -> Path:
        return Path(self.STORAGE_PATH).resolve()

    @property
    def qdrant_path(self) -> Path:
        return Path(self.QDRANT_PATH).resolve()


# Singleton — import this everywhere
settings = Settings()
