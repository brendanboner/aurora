"""FastAPI entrypoint for the Content Creator Service."""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import db
from .migrations_runner import apply_all_migrations
from .routes import agents, feed, posts, preferences, admin
from .services.scheduler import AgentScheduler
from .settings import get_settings

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

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(feed.router)
app.include_router(agents.router)
app.include_router(posts.router)
app.include_router(preferences.router)
app.include_router(admin.router)


@app.on_event("startup")
async def startup() -> None:
    logger.info("Starting Content Creator Service")
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
