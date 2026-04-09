"""
FastAPI application entry point.
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from config import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s %(levelname)-8s %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


# ── Lifespan ──────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    logger.info("Starting Draco Dataset Studio backend v6.0.0")

    # Init database
    from database import init_db
    await init_db()
    logger.info("Database ready")

    try:
        from database import AsyncSessionLocal
        from api.export import recover_stale_export_jobs

        async with AsyncSessionLocal() as db:
            recovered_exports = await recover_stale_export_jobs(db)
        if recovered_exports:
            logger.warning("Recovered %d stale export job(s) after restart", recovered_exports)
    except Exception as exc:
        logger.warning("Could not recover stale export jobs: %s", exc)

    # Init providers
    from providers.registry import (
        get_registry,
        register_default_providers,
        register_optional_providers,
    )
    registry = get_registry()
    register_default_providers(registry)
    register_optional_providers(registry)

    logger.info("Providers registered: %s", registry)

    # Load persisted provider configs and inject into registry
    try:
        from database import AsyncSessionLocal
        from api.providers import _get_fernet
        from services.provider_config import apply_all_provider_configs

        fernet = _get_fernet()

        async with AsyncSessionLocal() as _db:
            applied = await apply_all_provider_configs(_db, fernet=fernet)
            for item in applied:
                logger.info(
                    "Loaded provider config for %s/%s (%s)",
                    item["provider_type"],
                    item["provider_name"],
                    ", ".join(item["config_keys"]) if item["config_keys"] else "no config",
                )
    except Exception as exc:
        logger.warning("Could not load persisted provider configs: %s", exc)

    # Load embedding provider eagerly (FastEmbed downloads model on first use)
    embed_provider = registry.get("embedding", "fastembed")
    if embed_provider:
        try:
            await asyncio.wait_for(embed_provider.load(), timeout=60)
        except asyncio.TimeoutError:
            logger.warning("FastEmbed pre-load timed out (>60 s) — will load on first use")
        except Exception as exc:
            logger.warning("Could not pre-load FastEmbed: %s", exc)

    # Start job queue
    from workers.job_queue import get_job_queue
    queue = get_job_queue()
    await queue.start()
    logger.info("Job queue started")

    logger.info(
        "Draco backend ready at http://%s:%d",
        settings.HOST,
        settings.PORT,
    )

    yield

    # Shutdown
    await queue.stop()
    logger.info("Shutdown complete")


# ── App factory ───────────────────────────────────────────────────────────────

def create_app() -> FastAPI:
    app = FastAPI(
        title="Draco Dataset Studio",
        version="6.0.0",
        description="AI-powered image dataset curation and management",
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    # ── CORS ──────────────────────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"] if settings.DEBUG else settings.CORS_ORIGINS,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ── Loopback-only guard ───────────────────────────────────────────────────
    if not settings.ALLOW_REMOTE_ACCESS:
        @app.middleware("http")
        async def loopback_only(request: Request, call_next):
            request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID") or str(uuid.uuid4())
            request.state.request_id = request_id
            client_ip = request.client.host if request.client else "unknown"
            if client_ip not in ("127.0.0.1", "::1", "localhost"):
                logger.warning("Rejected remote request [%s] from %s to %s", request_id, client_ip, request.url.path)
                return JSONResponse(
                    status_code=403,
                    content={
                        "detail": "Remote access is disabled. Set ALLOW_REMOTE_ACCESS=true to enable.",
                        "request_id": request_id,
                    },
                    headers={"X-Request-ID": request_id},
                )
            return await call_next(request)

    # ── Request timing middleware ─────────────────────────────────────────────
    @app.middleware("http")
    async def add_timing(request: Request, call_next):
        t0 = time.monotonic()
        request_id = getattr(request.state, "request_id", None) or request.headers.get("X-Request-ID") or str(uuid.uuid4())
        request.state.request_id = request_id
        try:
            response = await call_next(request)
        except Exception:
            raise
        elapsed = round((time.monotonic() - t0) * 1000, 1)
        response.headers["X-Process-Time"] = f"{elapsed}ms"
        response.headers["X-Request-ID"] = request_id
        if elapsed > 1000:
            logger.warning(
                "Slow request [%s]: %s %s - %sms",
                request_id,
                request.method,
                request.url.path,
                elapsed,
            )
        return response

    # ── Global exception handler ──────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        request_id = getattr(request.state, "request_id", str(uuid.uuid4()))
        logger.exception("Unhandled exception [%s]: %s %s", request_id, request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={
                "detail": "Internal server error",
                "type": type(exc).__name__,
                "request_id": request_id,
            },
            headers={"X-Request-ID": request_id},
        )

    # ── Routes ────────────────────────────────────────────────────────────────
    from api.projects import router as projects_router
    from api.assets import router as assets_router
    from api.captions import router as captions_router
    from api.faces import router as faces_router
    from api.ranking import router as ranking_router
    from api.export import router as export_router
    from api.providers import router as providers_router
    from api.jobs import router as jobs_router
    from api.coach import router as coach_router
    from api.augmentation import router as augmentation_router
    from api.benchmark import router as benchmark_router
    from api.duplicates import router as duplicates_router
    from api.search import router as search_router
    from api.embeddings import router as embeddings_router
    from api.admin import router as admin_router
    from api.preferences import router as preferences_router
    from api.runtime import router as runtime_router

    app.include_router(projects_router)
    app.include_router(assets_router)
    app.include_router(captions_router)
    app.include_router(faces_router)
    app.include_router(ranking_router)
    app.include_router(export_router)
    app.include_router(providers_router)
    app.include_router(jobs_router)
    app.include_router(coach_router)
    app.include_router(augmentation_router)
    app.include_router(benchmark_router)
    app.include_router(duplicates_router)
    app.include_router(search_router)
    app.include_router(embeddings_router)
    app.include_router(admin_router)
    app.include_router(preferences_router)
    app.include_router(runtime_router)

    # ── Health check ──────────────────────────────────────────────────────────
    @app.get("/health")
    async def health() -> dict:
        from database import check_db
        db_ok = await check_db()
        return {
            "status": "ok" if db_ok else "degraded",
            "database": db_ok,
            "version": "6.0.0",
        }

    @app.get("/api/health", include_in_schema=False)
    async def health_legacy() -> dict:
        return await health()

    # ── Static files (thumbnails, originals via direct URL) ───────────────────
    storage_path = settings.storage_path
    storage_path.mkdir(parents=True, exist_ok=True)
    app.mount(
        "/files",
        StaticFiles(directory=str(storage_path)),
        name="files",
    )

    return app


app = create_app()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "backend.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG,
        log_level=settings.LOG_LEVEL.lower(),
    )
