"""
FastAPI application entry point.
"""
from __future__ import annotations

import logging
import time
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

    # Init providers
    from providers.registry import get_registry, register_default_providers
    registry = get_registry()
    register_default_providers(registry)

    # Register additional caption providers
    try:
        from providers.caption.joycaption import JoyCaptionProvider
        registry.register("caption", "joycaption", JoyCaptionProvider)
        logger.info("Registered caption/joycaption")
    except ImportError as e:
        logger.warning("Could not register caption/joycaption: %s", e)
    try:
        from providers.caption.qwen_vl import QwenVLProvider
        registry.register("caption", "qwen_vl", QwenVLProvider)
        logger.info("Registered caption/qwen_vl")
    except ImportError as e:
        logger.warning("Could not register caption/qwen_vl: %s", e)
    try:
        from providers.caption.moondream import MoondreamProvider
        registry.register("caption", "moondream", MoondreamProvider)
        logger.info("Registered caption/moondream")
    except ImportError as e:
        logger.warning("Could not register caption/moondream: %s", e)
    try:
        from providers.caption.llava_next import LLaVANextProvider
        registry.register("caption", "llava_next", LLaVANextProvider)
        logger.info("Registered caption/llava_next")
    except ImportError as e:
        logger.warning("Could not register caption/llava_next: %s", e)
    try:
        from providers.quality.laion_aesthetic import LAIONAestheticProvider
        registry.register("quality", "laion_aesthetic", LAIONAestheticProvider)
        logger.info("Registered quality/laion_aesthetic")
    except ImportError as e:
        logger.warning("Could not register quality/laion_aesthetic: %s", e)
    try:
        from providers.editing.realesrgan import RealESRGANProvider
        registry.register("editing", "realesrgan", RealESRGANProvider)
        logger.info("Registered editing/realesrgan")
    except ImportError as e:
        logger.warning("Could not register editing/realesrgan: %s", e)
    try:
        from providers.pose.mmpose_provider import MMPoseProvider
        registry.register("pose", "mmpose", MMPoseProvider)
        logger.info("Registered pose/mmpose")
    except ImportError as e:
        logger.warning("Could not register pose/mmpose: %s", e)
    try:
        from providers.face.openface_provider import OpenFaceProvider
        registry.register("head_pose", "openface", OpenFaceProvider)
        registry.register("action_units", "openface", OpenFaceProvider)
        logger.info("Registered head_pose/openface and action_units/openface")
    except ImportError as e:
        logger.warning("Could not register openface providers: %s", e)

    logger.info("Providers registered: %s", registry)

    # Load persisted provider API keys and inject into registry
    try:
        from database import AsyncSessionLocal
        from models.provider_config import ProviderConfig
        from sqlalchemy import select as _select
        from api.providers import _get_fernet
        fernet = _get_fernet()
        async with AsyncSessionLocal() as _db:
            rows = (await _db.execute(
                _select(ProviderConfig).where(ProviderConfig.api_key_encrypted.isnot(None))
            )).scalars().all()
            for row in rows:
                try:
                    key = fernet.decrypt(row.api_key_encrypted.encode()).decode()
                    registry.set_config(row.provider_type, row.provider_name, {"api_key": key})
                    logger.info("Loaded saved API key for %s/%s", row.provider_type, row.provider_name)
                except Exception as exc:
                    logger.warning("Could not decrypt key for %s/%s: %s", row.provider_type, row.provider_name, exc)
    except Exception as exc:
        logger.warning("Could not load persisted provider API keys: %s", exc)

    # Load embedding provider eagerly (FastEmbed downloads model on first use)
    embed_provider = registry.get("embedding", "fastembed")
    if embed_provider:
        try:
            await embed_provider.load()
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

    # ── Request timing middleware ─────────────────────────────────────────────
    @app.middleware("http")
    async def add_timing(request: Request, call_next):
        t0 = time.monotonic()
        response = await call_next(request)
        elapsed = round((time.monotonic() - t0) * 1000, 1)
        response.headers["X-Process-Time"] = f"{elapsed}ms"
        if elapsed > 1000:
            logger.warning("Slow request: %s %s — %sms", request.method, request.url.path, elapsed)
        return response

    # ── Global exception handler ──────────────────────────────────────────────
    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception):
        logger.exception("Unhandled exception: %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error", "type": type(exc).__name__},
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
