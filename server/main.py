"""FastAPI application entry point for the AI Radio DJ backend."""

import server._platform_fix  # noqa: F401 — must be first, fixes WMI hang on Win/Py3.13

import logging
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server.config import settings
from server.database import init_db
from server.engine.scheduler import MasterScheduler
from server.events.emitter import event_bus
from server.events.handlers import setup_default_handlers
from server.providers.registry import ProviderRegistry
from server.routers import (
    announcements,
    dashboard,
    dj_config,
    playlog,
    providers,
    recording,
    setup,
    shows,
    stream,
    streaming,
    styles,
)

# Configure structured logging
LOG_FORMAT = (
    "%(asctime)s | %(levelname)-8s | %(name)-30s | %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging() -> None:
    """Configure application logging with structured format.

    Sets up console handler with configurable level and format.
    Suppresses noisy third-party loggers.
    """
    root = logging.getLogger()
    root.setLevel(getattr(logging, settings.LOG_LEVEL.upper(), logging.INFO))

    # Remove existing handlers to avoid duplicates on reload
    root.handlers.clear()

    # Console handler
    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(root.level)
    handler.setFormatter(logging.Formatter(LOG_FORMAT, datefmt=DATE_FORMAT))
    root.addHandler(handler)

    # Suppress noisy loggers
    for noisy in [
        "httpcore",
        "httpx",
        "uvicorn.access",
        "watchfiles",
        "sqlalchemy.engine",
    ]:
        logging.getLogger(noisy).setLevel(logging.WARNING)

    # Keep our loggers at configured level
    logging.getLogger("server").setLevel(root.level)


setup_logging()
logger = logging.getLogger(__name__)

FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan handler for startup and shutdown events.

    Args:
        app: The FastAPI application instance.

    Yields:
        Control back to the application after startup tasks complete.
    """
    logger.info("Starting AI Radio DJ backend...")

    # Initialize database
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as exc:
        logger.critical("Database initialization failed: %s", exc)
        raise

    # Set up event handlers
    setup_default_handlers(event_bus)

    # Initialize providers (non-fatal — graceful degradation)
    registry = ProviderRegistry.get_instance()
    try:
        await registry.initialize(settings)
    except Exception as exc:
        logger.error(
            "Provider initialization failed (continuing without): %s", exc
        )

    # Restore saved voice provider preference from DJ config
    try:
        from server.database import get_session_factory
        from server.models.dj_config import DJConfig as DJConfigModel

        async with get_session_factory()() as db_session:
            from sqlalchemy import select as sa_select

            result = await db_session.execute(sa_select(DJConfigModel).limit(1))
            dj_config = result.scalar_one_or_none()
            if dj_config and dj_config.voice_provider:
                if registry.set_active_voice_provider(dj_config.voice_provider):
                    logger.info(
                        "Restored voice provider preference: %s",
                        dj_config.voice_provider,
                    )
    except Exception as exc:
        logger.warning("Could not restore voice provider preference: %s", exc)

    # Start scheduler (background loops only — streaming is started by the user)
    scheduler = MasterScheduler()
    app.state.scheduler = scheduler
    try:
        await scheduler.start()
        logger.info("Master scheduler started (streaming idle — waiting for user)")
    except Exception as exc:
        logger.error("Scheduler startup failed: %s", exc)

    logger.info("AI Radio DJ backend ready")
    yield

    logger.info("Shutting down AI Radio DJ backend...")
    try:
        await scheduler.stop()
    except Exception as exc:
        logger.error("Scheduler shutdown error: %s", exc)
    logger.info("Shutdown complete")


app = FastAPI(title="AI Radio DJ", version="0.1.0", lifespan=lifespan)

# The SPA is served same-origin, so CORS only matters for local dev setups.
# Credentials stay disabled because the write API is unauthenticated.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(setup.router)
app.include_router(styles.router)
app.include_router(announcements.router)
app.include_router(dj_config.router)
app.include_router(dashboard.router)
app.include_router(playlog.router)
app.include_router(stream.router)
app.include_router(shows.router)
app.include_router(recording.router)
app.include_router(providers.router)
app.include_router(streaming.router)

if FRONTEND_DIST.is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST / "assets")),
        name="assets",
    )


# Registered after the routers so real API routes match first. Covers every
# standard method so non-GET requests to unknown /api/* paths get JSON, not
# the SPA shell or a bare 405.
@app.api_route(
    "/api/{rest_of_path:path}",
    methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    include_in_schema=False,
)
async def api_not_found(rest_of_path: str) -> JSONResponse:
    """Return a JSON 404 for unknown API paths regardless of HTTP method."""
    return JSONResponse({"detail": "Not found"}, status_code=404)


@app.get("/audio/{file_path:path}")
async def serve_audio_file(file_path: str) -> FileResponse:
    """Serve generated audio files for frontend previews."""
    audio_root = Path(settings.AUDIO_DIR).resolve()
    requested_path = (audio_root / file_path).resolve()

    try:
        requested_path.relative_to(audio_root)
    except ValueError as exc:
        raise HTTPException(status_code=403, detail="Access denied") from exc

    if not requested_path.is_file():
        raise HTTPException(status_code=404, detail="Audio file not found")

    return FileResponse(str(requested_path))


@app.get("/{full_path:path}")
async def serve_spa(request: Request, full_path: str) -> FileResponse:
    """Serve the SPA index.html for any non-API route.

    Args:
        request: The incoming HTTP request.
        full_path: The requested path.

    Returns:
        The frontend index.html file, or a 404 message if not built.
    """
    if full_path.startswith("api/"):
        return JSONResponse({"detail": "Not found"}, status_code=404)

    index_file = FRONTEND_DIST / "index.html"
    if index_file.is_file():
        return FileResponse(str(index_file))

    return JSONResponse(
        {"detail": "Frontend not built. Run 'npm run build' in frontend/."},
        status_code=404,
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "server.main:app",
        host=settings.HOST,
        port=settings.PORT,
        log_level=settings.LOG_LEVEL.lower(),
        reload=True,
    )
