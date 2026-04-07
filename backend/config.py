"""
Application configuration via Pydantic Settings.
All values are driven by environment variables (or .env file).
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import field_validator
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
    DATA_DIR: str = "./data"
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
    CORS_ORIGINS: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:18082",
        "http://127.0.0.1:18082",
    ]
    DEBUG: bool = False
    # Set to true only when running behind a trusted reverse proxy or in Docker.
    # When false (default), the server rejects any request not from loopback.
    ALLOW_REMOTE_ACCESS: bool = False
    # Semicolon-separated list of additional allowed directories for ingest-directory.
    # User home and DATA_DIR are always allowed.
    ALLOWED_INGEST_ROOTS: str = ""

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

    @field_validator("DEBUG", "ALLOW_REMOTE_ACCESS", "LOG_JSON", mode="before")
    @classmethod
    def _parse_boolish(cls, value):
        if isinstance(value, bool) or value is None:
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"1", "true", "yes", "on", "debug", "development", "dev"}:
                return True
            if normalized in {"0", "false", "no", "off", "release", "production", "prod"}:
                return False
        return value

    # ── Data dir helper ───────────────────────────────────────────────────────
    @property
    def storage_path(self) -> Path:
        return Path(self.STORAGE_PATH).resolve()

    @property
    def data_dir(self) -> Path:
        return Path(self.DATA_DIR).resolve()

    @property
    def qdrant_path(self) -> Path:
        return Path(self.QDRANT_PATH).resolve()


# Singleton — import this everywhere
settings = Settings()
