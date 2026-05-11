"""
FastAPI endpoints for the Curator service.

Provides health checks, status monitoring, and manual job triggers.
"""
import asyncio
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from pydantic import BaseModel

from services.topic_organizer import TopicOrganizer
from services.event_reconciler import EventReconciler
from utils.logger import setup_logger
from common.auth_middleware import get_user_context, require_role
from neo4j_client import Neo4jClient, GraphRepository
from neo4j_client.models import Topic
from settings import settings

# Import OpenTelemetry instrumentation
try:
    from common.telemetry import init_telemetry, instrument_fastapi
    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False

logger = setup_logger(__name__)

# Initialize OpenTelemetry
if OTEL_AVAILABLE:
    tracer, meter = init_telemetry(
        service_name="aurora-curator",
        service_version="1.0.0"
    )
else:
    tracer, meter = None, None


class JobStatus(BaseModel):
    """Status of a scheduled job."""
    name: str
    is_running: bool
    last_run: Optional[datetime] = None
    next_run: Optional[datetime] = None
    last_error: Optional[str] = None


class ServiceStatus(BaseModel):
    """Overall service status."""
    status: str
    uptime_seconds: float
    jobs: list[JobStatus]


class TriggerResponse(BaseModel):
    """Response for manual trigger endpoints."""
    success: bool
    message: str
    job_id: Optional[str] = None


# Create FastAPI app
app = FastAPI(
    title="Curator Service",
    description="Event reconciliation and topic organization service",
    version="1.0.0",
)

# Instrument FastAPI with OpenTelemetry
if OTEL_AVAILABLE:
    instrument_fastapi(app)

# Global state - will be set by curator.py
_scheduler = None
_start_time: Optional[datetime] = None
_job_state: dict = {
    "topic_organization": {
        "is_running": False,
        "last_run": None,
        "last_error": None,
    },
    "event_reconciliation": {
        "is_running": False,
        "last_run": None,
        "last_error": None,
    },
}


def set_scheduler(scheduler):
    """Set the APScheduler instance for status queries."""
    global _scheduler
    _scheduler = scheduler


def set_start_time(start_time: datetime):
    """Set the service start time."""
    global _start_time
    _start_time = start_time


def update_job_state(job_name: str, **kwargs):
    """Update the state of a job."""
    if job_name in _job_state:
        _job_state[job_name].update(kwargs)


class TopicStats(BaseModel):
    """Topic organization statistics."""
    total_topics: int
    unorganized_topics: int
    organized_topics: int
    curation_threshold: int
    curation_mode: str  # "full" or "incremental"


@app.get("/health")
async def health_check():
    """Simple health check endpoint."""
    return {"status": "healthy"}


@app.get("/topics/stats", response_model=TopicStats)
@require_role(["admin", "superadmin"])
async def get_topic_stats(user: Optional[dict] = Depends(get_user_context)):
    """
    Get topic organization statistics.
    
    Returns counts of total, organized, and unorganized topics,
    along with current curation mode.
    
    Requires admin or superadmin role.
    """
    logger.info(f"Topic stats requested by {user['email']} (role: {user['role']})")
    
    neo4j_client = None
    try:
        # Connect to Neo4j
        neo4j_client = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
            logger_instance=logger
        )
        neo4j_client.connect()
        repo = GraphRepository(neo4j_client, logger_instance=logger)
        
        # Get counts
        total_topics = repo.count_nodes(Topic)
        unorganized_topics = len(repo.get_unorganized_topics())
        organized_topics = total_topics - unorganized_topics
        
        # Determine curation mode
        threshold = settings.incremental_curation_threshold
        curation_mode = "incremental" if total_topics > threshold else "full"
        
        return TopicStats(
            total_topics=total_topics,
            unorganized_topics=unorganized_topics,
            organized_topics=organized_topics,
            curation_threshold=threshold,
            curation_mode=curation_mode
        )
    except Exception as e:
        logger.error(f"Error getting topic stats: {e}")
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        if neo4j_client:
            neo4j_client.close()


@app.get("/status", response_model=ServiceStatus)
async def get_status(user: Optional[dict] = Depends(get_user_context)):
    """
    Get detailed service status including job information.
    
    Can be called by authenticated users OR internal services.
    If user context is present, log the access for monitoring.
    """
    if user:
        logger.info(f"Status check by user {user['email']} (role: {user['role']})")
    else:
        logger.debug("Status check by internal service")
    
    if _start_time is None:
        uptime = 0.0
    else:
        uptime = (datetime.now() - _start_time).total_seconds()
    
    jobs = []
    for job_name, state in _job_state.items():
        next_run = None
        if _scheduler:
            job = _scheduler.get_job(job_name)
            if job and job.next_run_time:
                next_run = job.next_run_time
        
        jobs.append(JobStatus(
            name=job_name,
            is_running=state["is_running"],
            last_run=state["last_run"],
            next_run=next_run,
            last_error=state["last_error"],
        ))
    
    return ServiceStatus(
        status="running",
        uptime_seconds=uptime,
        jobs=jobs,
    )


@app.post("/trigger/topics", response_model=TriggerResponse)
@require_role(["admin", "superadmin"])
async def trigger_topic_organization(background_tasks: BackgroundTasks, user: Optional[dict] = Depends(get_user_context)):
    """
    Manually trigger topic organization job.
    Requires admin or superadmin role.
    """
    logger.info(f"Manual topic organization triggered by {user['email']} (role: {user['role']})")
    
    if _job_state["topic_organization"]["is_running"]:
        raise HTTPException(
            status_code=409,
            detail="Topic organization is already running"
        )
    
    async def run_job():
        update_job_state("topic_organization", is_running=True)
        try:
            organizer = TopicOrganizer(logger_instance=logger)
            await asyncio.to_thread(organizer.run)
            update_job_state(
                "topic_organization",
                is_running=False,
                last_run=datetime.now(),
                last_error=None,
            )
            logger.info("Manual topic organization completed successfully")
        except Exception as e:
            update_job_state(
                "topic_organization",
                is_running=False,
                last_error=str(e),
            )
            logger.error(f"Manual topic organization failed: {e}")
    
    background_tasks.add_task(run_job)
    
    return TriggerResponse(
        success=True,
        message="Topic organization job triggered",
        job_id="topic_organization",
    )


@app.post("/trigger/reconcile", response_model=TriggerResponse)
@require_role(["admin", "superadmin"])
async def trigger_event_reconciliation(background_tasks: BackgroundTasks, user: Optional[dict] = Depends(get_user_context)):
    """
    Manually trigger event reconciliation job.
    Requires admin or superadmin role.
    """
    logger.info(f"Manual event reconciliation triggered by {user['email']} (role: {user['role']})")
    
    if _job_state["event_reconciliation"]["is_running"]:
        raise HTTPException(
            status_code=409,
            detail="Event reconciliation is already running"
        )
    
    async def run_job():
        update_job_state("event_reconciliation", is_running=True)
        reconciler = None
        try:
            reconciler = EventReconciler(logger_instance=logger)
            await asyncio.to_thread(reconciler.run)
            update_job_state(
                "event_reconciliation",
                is_running=False,
                last_run=datetime.now(),
                last_error=None,
            )
            logger.info("Manual event reconciliation completed successfully")
        except Exception as e:
            update_job_state(
                "event_reconciliation",
                is_running=False,
                last_error=str(e),
            )
            logger.error(f"Manual event reconciliation failed: {e}")
        finally:
            # Ensure cleanup of resources
            if reconciler:
                reconciler.close()
    
    background_tasks.add_task(run_job)
    
    return TriggerResponse(
        success=True,
        message="Event reconciliation job triggered",
        job_id="event_reconciliation",
    )


# NOTE: Removed /trigger/reconcile/{datasource_id} endpoint
# Manual datasource-specific reconciliation is dangerous because it requires
# a valid scrape_started_at timestamp. Using current time would mark ALL events
# as unconfirmed since they were all last_updated before "now".
# 
# The /trigger/reconcile endpoint is safe - it only processes pending Redis
# signals from actual scrapes, which have valid timestamps.


# ---------------------------------------------------------------------------
# Archive stale content (T14)
# ---------------------------------------------------------------------------

class ArchiveStaleRequest(BaseModel):
    max_age_months: int = 24
    dry_run: bool = False


class ArchiveStaleResponse(BaseModel):
    success: bool
    archived: int
    dry_run: bool
    message: str


@app.post("/curator/archive-stale", response_model=ArchiveStaleResponse, tags=["Data Quality"])
async def archive_stale_resources(
    request: ArchiveStaleRequest,
    user: Optional[dict] = Depends(require_role("admin")),
):
    """Mark Resource nodes older than max_age_months as archived=true.

    Archived resources are filtered out of all oracle recency queries.
    Only resources with a confirmed publish_date and temporal_confidence='high'
    are eligible — undated content is left alone so nothing is hidden silently.

    Use dry_run=true to preview the count without making changes.
    """
    client = Neo4jClient(
        uri=settings.neo4j_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        database=settings.neo4j_database,
    )
    try:
        if request.dry_run:
            result = client.run_query(
                """
                MATCH (r:Resource)
                WHERE r.publish_date IS NOT NULL
                  AND r.publish_date <> ''
                  AND coalesce(r.archived, false) = false
                  AND coalesce(r.temporal_confidence, 'high') = 'high'
                  AND datetime(r.publish_date) < datetime() - duration({months: $months})
                RETURN count(r) AS total
                """,
                {"months": request.max_age_months},
            )
            total = result[0]["total"] if result else 0
            return ArchiveStaleResponse(
                success=True,
                archived=total,
                dry_run=True,
                message=f"dry_run: {total} resources would be archived (older than {request.max_age_months} months).",
            )

        result = client.run_query(
            """
            MATCH (r:Resource)
            WHERE r.publish_date IS NOT NULL
              AND r.publish_date <> ''
              AND coalesce(r.archived, false) = false
              AND coalesce(r.temporal_confidence, 'high') = 'high'
              AND datetime(r.publish_date) < datetime() - duration({months: $months})
            SET r.archived = true
            RETURN count(r) AS total
            """,
            {"months": request.max_age_months},
        )
        total = result[0]["total"] if result else 0
        logger.info("archive-stale: archived %d resources older than %d months", total, request.max_age_months)
        return ArchiveStaleResponse(
            success=True,
            archived=total,
            dry_run=False,
            message=f"Archived {total} resources older than {request.max_age_months} months.",
        )
    except Exception as e:
        logger.error("archive-stale failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Archive stale failed: {e}")
    finally:
        client.close()
