"""Health check endpoint for Oracle Service."""

from fastapi import APIRouter
import logging
import os

from src.models.response import HealthCheck, HealthStatus
from src.settings import settings

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


def check_neo4j() -> str:
    """Check Neo4j connectivity using the shared connection pool."""
    try:
        from src.services.keyword_retriever import get_repo
        repo = get_repo()
        # Use the existing cached connection to run a simple check
        result = repo.client.execute_query("RETURN 1 AS check")
        return "ok" if result else "error"
    except Exception as e:
        logger.warning(f"Neo4j health check failed: {e}")
        return f"error: {str(e)[:50]}"


def check_llm() -> str:
    """Check LLM (Azure OpenAI) connectivity."""
    if not settings.azure_openai_api_key or not settings.azure_openai_endpoint:
        return "not_configured"
    try:
        from openai import AzureOpenAI
        client = AzureOpenAI(
            api_key=settings.azure_openai_api_key,
            api_version=settings.azure_openai_api_version,
            azure_endpoint=settings.azure_openai_endpoint,
        )
        # Just verify client creation - don't make an actual API call
        return "ok"
    except Exception as e:
        logger.warning(f"LLM health check failed: {e}")
        return f"error: {str(e)[:50]}"


@router.get("/health", response_model=HealthCheck)
async def health_check() -> HealthCheck:
    """
    Health check endpoint for Oracle Service.
    
    Returns overall status and individual component checks.
    """
    checks = {}
    
    # Check Neo4j
    checks["neo4j"] = check_neo4j()
    
    # Check LLM
    checks["llm"] = check_llm()
    
    # Determine overall status
    errors = [k for k, v in checks.items() if v.startswith("error")]
    not_configured = [k for k, v in checks.items() if v == "not_configured"]
    
    if errors:
        status = HealthStatus.UNHEALTHY
    elif not_configured:
        status = HealthStatus.DEGRADED
    else:
        status = HealthStatus.HEALTHY
    
    return HealthCheck(
        status=status,
        checks=checks,
        version="0.1.0"
    )
