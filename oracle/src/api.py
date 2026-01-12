"""Oracle Service - FastAPI Application Entry Point."""

from fastapi import FastAPI
import logging

# Import OpenTelemetry instrumentation
from common.telemetry import init_telemetry, instrument_fastapi

from src.routes.health import router as health_router
from src.routes.query import router as query_router
from src.routes.history import router as history_router
from src.routes.documents import router as documents_router
from src.services.query_history import get_query_history_service
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

# Include routers
app.include_router(health_router)
app.include_router(query_router)
app.include_router(history_router)
app.include_router(documents_router)


@app.on_event("startup")
async def startup():
    """Initialize services on startup."""
    logger.info("Oracle Service starting up...")
    if settings.use_prod_data:
        logger.info(f"*** PRODUCTION DATA MODE ENABLED ***")
        logger.info(f"Neo4j URI (PROD): {settings.effective_neo4j_uri}")
        logger.info(f"All Neo4j operations will be READ-ONLY")
    else:
        logger.info(f"Neo4j URI: {settings.effective_neo4j_uri}")
    logger.info(f"LLM configured: {bool(settings.azure_openai_api_key and settings.azure_openai_deployment)}")
    
    # Initialize query history storage
    if settings.query_history_enabled:
        query_history = get_query_history_service()
        initialized = await query_history.initialize()
        if initialized:
            logger.info("Query history storage initialized")
        else:
            logger.warning("Query history storage failed to initialize")


@app.on_event("shutdown")
async def shutdown():
    """Cleanup on shutdown."""
    logger.info("Oracle Service shutting down...")


# Root endpoint for basic connectivity check
@app.get("/")
async def root():
    """Root endpoint."""
    return {"service": "oracle", "version": "0.1.0"}
