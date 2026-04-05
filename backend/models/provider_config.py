"""ProviderConfig ORM model — stores per-provider settings + encrypted API keys."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ProviderConfig(Base):
    __tablename__ = "provider_configs"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=lambda: str(uuid.uuid4())
    )

    provider_type: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # "caption"/"face"/"embedding"/"quality"/"storage"/"export"
    provider_name: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # "ollama"/"gemini"/"insightface"/"fastembed"

    is_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)

    # Encrypted API key (Fernet-encrypted, base64)
    api_key_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Non-sensitive config (base URL, model name, etc.)
    config: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # {"base_url": "http://...", "model": "llava:13b", "temperature": 0.7}

    # Health state (cached from last check)
    last_health_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_health_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_health_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )
