"""FastAPI entrypoint for the Content Creator Service."""
from __future__ import annotations

import logging
import os

from fastapi import FastAPI

from . import db
from .migrations_runner import apply_all_migrations
from .routes import agents, feed, posts, preferences, admin
from .services.scheduler import AgentScheduler
from .settings import get_settings

# Configure logging early
def configure_logging():
    """Configure logging based on LOG_LEVEL environment variable."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    
    # Validate log level
    valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
    if log_level not in valid_levels:
        log_level = "INFO"
    
    logging.basicConfig(
        level=getattr(logging, log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        force=True  # Override any existing configuration
    )
    
    # Set specific loggers to appropriate levels
    if log_level == "DEBUG":
        # Enable debug logging for our services
        logging.getLogger("content_creator_service").setLevel(logging.DEBUG)
        logging.getLogger("__main__").setLevel(logging.DEBUG)
    
    logging.info(f"Logging configured at level: {log_level}")

# Configure logging before importing anything else
configure_logging()

# Import OpenTelemetry instrumentation
try:
    from common.telemetry import init_telemetry, instrument_fastapi
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

logger = logging.getLogger(__name__)

# Initialize OpenTelemetry
if OTEL_AVAILABLE:
    tracer, meter = init_telemetry(
        service_name="aurora-content-creator",
        service_version="0.1.0"
    )
else:
    tracer, meter = None, None

app = FastAPI(title="Aurora Content Creator Service", version="0.1.0")
settings = get_settings()
scheduler = AgentScheduler()

# Instrument FastAPI with OpenTelemetry
if OTEL_AVAILABLE:
    instrument_fastapi(app)

app.include_router(feed.router)
app.include_router(agents.router)
app.include_router(posts.router)
app.include_router(preferences.router)
app.include_router(admin.router)


@app.on_event("startup")
async def startup() -> None:
    logger.info("Starting Content Creator Service")
    logger.info(f"Current logging level: {logging.getLevelName(logger.getEffectiveLevel())}")
    db.init_pool()
    apply_all_migrations()
    await scheduler.start()


@app.on_event("shutdown")
async def shutdown() -> None:
    await scheduler.shutdown()
    db.close_pool()


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "service": "content_creator_service"}
