"""Oracle Service - FastAPI Application Entry Point."""

from fastapi import FastAPI
import logging

# Import OpenTelemetry instrumentation
from common.telemetry import init_telemetry, instrument_fastapi

from src.routes.health import router as health_router
from src.routes.query import router as query_router
from src.routes.history import router as history_router
from src.routes.documents import router as documents_router
from src.routes.metrics import router as metrics_router
from src.routes.admin import router as admin_router
from src.routes.agent import router as agent_router
from src.routes.ingest import router as ingest_router
from src.services.query_history import get_query_history_service
from src.services.rollup_scheduler import RollupScheduler
from src.settings import settings

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level.upper()),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Reduce noise from third-party libraries
logging.getLogger('httpcore').setLevel(logging.WARNING)
logging.getLogger('httpx').setLevel(logging.WARNING)
logging.getLogger('openai').setLevel(logging.WARNING)
logging.getLogger('openai._base_client').setLevel(logging.WARNING)
logging.getLogger('urllib3').setLevel(logging.WARNING)
# Reduce Neo4j query logs (every query gets logged)
logging.getLogger('aurora.neo4j').setLevel(logging.WARNING)

# Initialize OpenTelemetry
tracer, meter = init_telemetry(
    service_name="oracle-service",
    service_version="0.1.0"
)

# Create FastAPI app
app = FastAPI(
    title="Oracle Service",
    description="Enhanced question-answering service with graph-aware RAG",
    version="0.1.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# Instrument FastAPI with OpenTelemetry
instrument_fastapi(app)

# Global scheduler instance
rollup_scheduler = RollupScheduler()

# Include routers
app.include_router(health_router)
app.include_router(query_router)
app.include_router(history_router)
app.include_router(documents_router)
app.include_router(metrics_router)
app.include_router(admin_router)
app.include_router(agent_router)
app.include_router(ingest_router)


@app.on_event("startup")
async def startup():
    """Initialize services on startup."""
    logger.info("Oracle Service starting up...")
    logger.info(f"Neo4j URI: {settings.neo4j_uri}")
    logger.info(f"LLM configured: {bool(settings.azure_openai_api_key and settings.azure_openai_deployment)}")
    
    # Load persisted configuration from database
    try:
        from src.services.config_persistence import initialize_config_from_db
        logger.info("Loading persisted configuration from database...")
        initialize_config_from_db()
        logger.info("✓ Configuration loaded from database")
    except Exception as e:
        logger.error(f"Failed to load persisted config: {e}", exc_info=True)
        logger.warning("Continuing with environment variable defaults")
    
    # Initialize fast pipeline database schema (PostgreSQL)
    if settings.fast_pipeline_enabled:
        try:
            from src.models.db_models import init_db
            logger.info("Initializing fast pipeline database schema...")
            init_db(settings.postgres_dsn)
            logger.info("✓ Fast pipeline database schema ready")
        except Exception as e:
            logger.error(f"Failed to initialize fast pipeline database: {e}", exc_info=True)
            if settings.fast_fallback_to_baseline:
                logger.warning("Fast pipeline database init failed, will fallback to baseline on errors")
            else:
                logger.error("Fast pipeline enabled but database init failed - service may have issues")
    
    # Initialize query history storage
    if settings.query_history_enabled:
        query_history = get_query_history_service()
        initialized = await query_history.initialize()
        if initialized:
            logger.info("Query history storage initialized")
        else:
            logger.warning("Query history storage failed to initialize")
    
    # Start rollup generation scheduler
    if settings.fast_pipeline_enabled and settings.fast_rollup_generation_enabled:
        try:
            logger.info("Starting rollup generation scheduler...")
            await rollup_scheduler.start()
            logger.info("✓ Rollup scheduler started")
        except Exception as e:
            logger.error(f"Failed to start rollup scheduler: {e}", exc_info=True)


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    logger.info("Oracle Service shutting down...")
    
    # Stop rollup scheduler
    if settings.fast_pipeline_enabled and settings.fast_rollup_generation_enabled:
        try:
            await rollup_scheduler.shutdown()
            logger.info("✓ Rollup scheduler stopped")
        except Exception as e:
            logger.error(f"Error stopping rollup scheduler: {e}", exc_info=True)


# Root endpoint for basic connectivity check
@app.get("/")
async def root():
    """Root endpoint."""
    return {"service": "oracle", "version": "0.1.0"}
