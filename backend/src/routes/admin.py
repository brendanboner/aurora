"""Admin routes for monitoring services."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any, Literal
from datetime import datetime
import pika
import os
import redis
import json
import subprocess
import logging
import time
import asyncio
from neo4j_client.client import Neo4jClient
from src.services import postgres, graph_service

router = APIRouter(prefix="/admin", tags=["Admin"])
logger = logging.getLogger(__name__)


class QueueResource(BaseModel):
    """Resource in the queue."""
    title: str
    url: str
    category: str
    publish_date: Optional[str]
    scraped_at: float
    position: int  # Position in queue


class ProcessingResource(BaseModel):
    """Resource currently being processed."""
    title: str
    url: str
    category: str
    status: str  # "retrieving", "extracting", "normalizing", "inserting", "completed", "failed"
    stage: str
    started_at: str
    updated_at: str
    error: Optional[str] = None
    datasource_id: Optional[str] = None
    publish_date: Optional[str] = None
    uploaded_by: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None


class QueueStatus(BaseModel):
    """RabbitMQ queue status."""
    queue_name: str
    message_count: int  # Total messages (ready + unacked)
    messages_ready: int  # Messages waiting to be consumed
    messages_unacked: int  # Messages currently being processed
    consumer_count: int
    resources: List[QueueResource]


class ServiceHealth(BaseModel):
    """Docker container health status."""
    container_name: str
    status: str  # "healthy", "unhealthy", "starting", "stopped", "not_found"
    health_status: Optional[str] = None  # Docker health check status


class ProcessingStatus(BaseModel):
    """Current processing status."""
    retriever_active: bool
    digester_active: bool
    retriever_health: ServiceHealth
    digester_health: ServiceHealth
    retriever_instances: Dict[str, int] = {"active": 0, "total": 1}  # active/total instances
    digester_instances: Dict[str, int] = {"active": 0, "total": 1}  # active/total instances
    retriever_current: Optional[ProcessingResource] = None
    digester_current: Optional[ProcessingResource] = None
    recent_completed: List[ProcessingResource]
    recent_failed: List[ProcessingResource]


class BatchProgress(BaseModel):
    """Ingestion batch progress information."""
    batch_id: str
    datasource_id: str
    status: str  # "scraping", "scraped", "digesting", "completed", "failed"
    items_scraped: int
    items_digested: int
    started_at: Optional[str] = None
    updated_at: Optional[str] = None
    progress_percent: float


class AdminDashboard(BaseModel):
    """Complete admin dashboard data."""
    queue_status: QueueStatus
    processing_status: ProcessingStatus
    active_batches: List[BatchProgress]
    timestamp: str


def get_rabbitmq_connection():
    """Get RabbitMQ connection."""
    host = os.getenv("RABBITMQ_HOST", "localhost")
    port = int(os.getenv("RABBITMQ_PORT", "5672"))
    user = os.getenv("RABBITMQ_USER", "guest")
    password = os.getenv("RABBITMQ_PASSWORD", "guest")
    
    credentials = pika.PlainCredentials(user, password)
    parameters = pika.ConnectionParameters(
        host=host, 
        port=port, 
        credentials=credentials,
        blocked_connection_timeout=10,
        socket_timeout=10,
        connection_attempts=1
    )
    return pika.BlockingConnection(parameters)


def get_redis_connection():
    """Get Redis connection for process status tracking."""
    host = os.getenv("REDIS_HOST", "localhost")
    port = int(os.getenv("REDIS_PORT", "6379"))
    return redis.Redis(host=host, port=port, decode_responses=True)


def get_docker_container_health(container_name: str) -> ServiceHealth:
    """
    Get Docker container health status using docker inspect.
    
    Args:
        container_name: Name of the Docker container
        
    Returns:
        ServiceHealth object with container status
    """
    try:
        # Run docker inspect to get container status
        result = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}|{{.State.Health.Status}}", container_name],
            capture_output=True,
            text=True,
            timeout=5
        )
        
        if result.returncode == 0:
            output = result.stdout.strip()
            parts = output.split("|")
            status = parts[0]
            health_status = parts[1] if len(parts) > 1 and parts[1] != "<no value>" else None
            
            # Map Docker status to our status
            if status == "running":
                if health_status == "healthy":
                    return ServiceHealth(container_name=container_name, status="healthy", health_status=health_status)
                elif health_status == "unhealthy":
                    return ServiceHealth(container_name=container_name, status="unhealthy", health_status=health_status)
                elif health_status == "starting":
                    return ServiceHealth(container_name=container_name, status="starting", health_status=health_status)
                else:
                    # No health check configured, but container is running
                    return ServiceHealth(container_name=container_name, status="healthy", health_status="no healthcheck")
            else:
                return ServiceHealth(container_name=container_name, status="stopped", health_status=None)
        else:
            # Container not found
            return ServiceHealth(container_name=container_name, status="not_found", health_status=None)
            
    except subprocess.TimeoutExpired:
        logger.warning(f"Docker inspect timeout for {container_name}")
        return ServiceHealth(container_name=container_name, status="unknown", health_status="timeout")
    except FileNotFoundError:
        # Docker CLI not available - assume healthy if heartbeat is recent
        logger.debug("Docker command not found - using heartbeat-based status")
        return ServiceHealth(container_name=container_name, status="healthy", health_status="heartbeat_based")
    except Exception as e:
        logger.error(f"Error checking Docker health for {container_name}: {e}")
        return ServiceHealth(container_name=container_name, status="unknown", health_status=str(e))


@router.get("/queue-status", response_model=QueueStatus)
async def get_queue_status():
    """
    Get current RabbitMQ queue status including pending resources.
    """
    try:
        queue_name = os.getenv("RABBITMQ_QUEUE", "document_processing")
        
        try:
            connection = get_rabbitmq_connection()
            channel = connection.channel()
        except Exception as e:
            # RabbitMQ not available - return empty status
            return QueueStatus(
                queue_name=queue_name,
                message_count=0,
                messages_ready=0,
                messages_unacked=0,
                consumer_count=0,
                resources=[]
            )
        
        # Get queue information
        try:
            queue = channel.queue_declare(queue=queue_name, durable=True, passive=True)
            messages_ready = queue.method.message_count  # Only ready messages
            consumer_count = queue.method.consumer_count
            messages_unacked = 0  # Will try to get from Management API
            
            # Try to get more detailed stats via Management HTTP API
            try:
                import requests
                mgmt_host = os.getenv("RABBITMQ_HOST", "rabbitmq")
                mgmt_port = 15672  # Management API port
                mgmt_user = os.getenv("RABBITMQ_USER", "guest")
                mgmt_password = os.getenv("RABBITMQ_PASSWORD", "guest")
                
                response = requests.get(
                    f"http://{mgmt_host}:{mgmt_port}/api/queues/%2F/{queue_name}",
                    auth=(mgmt_user, mgmt_password),
                    timeout=2
                )
                
                if response.status_code == 200:
                    queue_details = response.json()
                    messages_ready = queue_details.get("messages_ready", 0)
                    messages_unacked = queue_details.get("messages_unacknowledged", 0)
                    message_count = messages_ready + messages_unacked
                    consumer_count = queue_details.get("consumers", 0)
                    logger.debug(f"Got queue stats from Management API: ready={messages_ready}, unacked={messages_unacked}")
                else:
                    logger.warning(f"Management API returned status {response.status_code}")
                    message_count = messages_ready
                    messages_unacked = 0
            except ImportError:
                logger.warning("requests library not installed, cannot query Management API")
                message_count = messages_ready
                messages_unacked = 0
            except Exception as mgmt_error:
                logger.warning(f"RabbitMQ Management API not available: {mgmt_error}")
                # Try using rabbitmqctl as fallback
                try:
                    result = subprocess.run(
                        ["docker", "exec", "aurora-rabbitmq", "rabbitmqctl", "list_queues", 
                         "name", "messages_ready", "messages_unacknowledged"],
                        capture_output=True,
                        text=True,
                        timeout=5
                    )
                    if result.returncode == 0:
                        for line in result.stdout.split('\n'):
                            parts = line.split()
                            if len(parts) >= 3 and parts[0] == queue_name:
                                messages_ready = int(parts[1])
                                messages_unacked = int(parts[2])
                                message_count = messages_ready + messages_unacked
                                logger.debug(f"Got queue stats from rabbitmqctl: ready={messages_ready}, unacked={messages_unacked}")
                                break
                    else:
                        message_count = messages_ready
                        messages_unacked = 0
                except Exception as ctl_error:
                    logger.debug(f"rabbitmqctl fallback failed: {ctl_error}")
                    message_count = messages_ready
                    messages_unacked = 0
                
        except Exception:
            # Queue doesn't exist yet
            message_count = 0
            messages_ready = 0
            messages_unacked = 0
            consumer_count = 0
        
        # Peek at messages in queue (non-destructive) and deduplicate by URL
        resources = []
        if message_count > 0:
            try:
                peeked_tags = []
                seen_urls = set()
                position = 1
                
                for _ in range(message_count):
                    method_frame, header_frame, body = channel.basic_get(queue=queue_name, auto_ack=False)
                    
                    if not method_frame:
                        break
                    
                    try:
                        message = json.loads(body)
                        
                        # Extract data from nested structure (resource_data or event_data)
                        resource_data = message.get("resource_data", {})
                        event_data = message.get("event_data", {})
                        
                        # Get fields from appropriate nested object
                        title = resource_data.get("title") or event_data.get("name") or "Unknown"
                        url = resource_data.get("url") or event_data.get("url") or ""
                        category = resource_data.get("category") or ("event" if event_data else "unknown")
                        publish_date = resource_data.get("publish_date")
                        scraped_at = message.get("scraped_at", 0)
                        
                        # Only add if we haven't seen this URL yet
                        if url and url not in seen_urls:
                            resources.append(QueueResource(
                                title=title,
                                url=url,
                                category=category,
                                publish_date=publish_date,
                                scraped_at=scraped_at,
                                position=position
                            ))
                            seen_urls.add(url)
                            position += 1
                        
                        peeked_tags.append(method_frame.delivery_tag)
                        
                        # Stop if we have enough unique resources
                        if len(resources) >= 50:
                            break
                        
                    except json.JSONDecodeError:
                        peeked_tags.append(method_frame.delivery_tag)
                
                # Re-queue all peeked messages in original order to maintain queue order
                for tag in peeked_tags:
                    channel.basic_nack(delivery_tag=tag, requeue=True)
                    
            except Exception as e:
                logger.warning(f"Error peeking at queue messages: {e}")
                # Try to nack any messages we got
                try:
                    for tag in peeked_tags:
                        channel.basic_nack(delivery_tag=tag, requeue=True)
                except:
                    pass
        
        try:
            connection.close()
        except Exception:
            pass
        
        return QueueStatus(
            queue_name=queue_name,
            message_count=message_count,
            messages_ready=messages_ready,
            messages_unacked=messages_unacked,
            consumer_count=consumer_count,
            resources=resources
        )
        
    except Exception as e:
        logger.error(f"Failed to get queue status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve queue status")


@router.get("/processing-status", response_model=ProcessingStatus)
async def get_processing_status():
    """
    Get current processing status from retriever and digester services.
    Uses Redis to track current processing state and Docker to check health.
    """
    try:
        # Get Docker health status
        retriever_health = get_docker_container_health("aurora-retriever")
        digester_health = get_docker_container_health("aurora-digester")
        
        try:
            r = get_redis_connection()
            
            # Get current processing info
            retriever_current = r.get("retriever:current")
            digester_current = r.get("digester:current")
            
            # Get recent completed (last 10)
            recent_completed_raw = r.lrange("processing:completed", 0, 9)
            recent_completed = [
                ProcessingResource(**json.loads(item)) 
                for item in recent_completed_raw
            ]
            
            # Get recent failed (last 10)
            recent_failed_raw = r.lrange("processing:failed", 0, 9)
            recent_failed = [
                ProcessingResource(**json.loads(item)) 
                for item in recent_failed_raw
            ]
            
            # Check if services are active (updated in last 60 seconds)
            retriever_heartbeat = r.get("retriever:heartbeat")
            digester_heartbeat = r.get("digester:heartbeat")
            
            now = datetime.now().timestamp()
            retriever_active = (
                retriever_heartbeat is not None and 
                (now - float(retriever_heartbeat)) < 60
            )
            digester_active = (
                digester_heartbeat is not None and 
                (now - float(digester_heartbeat)) < 60
            )
            
            return ProcessingStatus(
                retriever_active=retriever_active,
                digester_active=digester_active,
                retriever_health=retriever_health,
                digester_health=digester_health,
                retriever_instances={"active": 1 if retriever_active else 0, "total": 1},
                digester_instances={"active": 1 if digester_active else 0, "total": 1},
                retriever_current=ProcessingResource(**json.loads(retriever_current)) if retriever_current else None,
                digester_current=ProcessingResource(**json.loads(digester_current)) if digester_current else None,
                recent_completed=recent_completed,
                recent_failed=recent_failed
            )
            
        except redis.ConnectionError:
            logger.warning("Redis not available - returning minimal status with Docker health only")
            # Redis not available - return minimal status with Docker health
            return ProcessingStatus(
                retriever_active=False,
                digester_active=False,
                retriever_health=retriever_health,
                digester_health=digester_health,
                retriever_instances={"active": 0, "total": 1},
                digester_instances={"active": 0, "total": 1},
                retriever_current=None,
                digester_current=None,
                recent_completed=[],
                recent_failed=[]
            )
            
    except Exception as e:
        logger.error(f"Failed to get processing status: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve processing status")


@router.get("/dashboard", response_model=AdminDashboard)
async def get_admin_dashboard():
    """
    Get complete admin dashboard data combining queue and processing status.
    """
    try:
        queue_status = await get_queue_status()
        processing_status = await get_processing_status()
        active_batches = await get_active_batches()
        
        return AdminDashboard(
            queue_status=queue_status,
            processing_status=processing_status,
            active_batches=active_batches,
            timestamp=datetime.now().isoformat()
        )
        
    except Exception as e:
        logger.error(f"Failed to get dashboard data: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to load monitoring dashboard")


@router.get("/active-batches", response_model=List[BatchProgress])
async def get_active_batches():
    """
    Get currently active ingestion batches from Neo4j.
    """
    try:
        # Get Neo4j connection details from environment
        uri = os.getenv("NEO4J_URI", "bolt://neo4j:7687")
        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD", "password")
        database = os.getenv("NEO4J_DATABASE", "neo4j")
        
        # Create client and connect
        neo4j_client = Neo4jClient(uri=uri, user=user, password=password, database=database)
        neo4j_client.connect()
        
        # Query for batches that are not completed or failed
        query = """
        MATCH (b:IngestionBatch)
        WHERE b.status IN ['retrieving', 'digesting']
        RETURN b.batch_id AS batch_id,
               b.datasource_id AS datasource_id,
               b.status AS status,
               b.items_scraped AS items_scraped,
               b.items_digested AS items_digested,
               b.scrape_started_at AS started_at,
               b.digest_completed_at AS updated_at
        ORDER BY b.scrape_started_at DESC
        LIMIT 10
        """
        
        results = neo4j_client.execute_query(query)
        
        batches = []
        for record in results:
            items_scraped = record.get("items_scraped", 0)
            items_digested = record.get("items_digested", 0)
            progress_percent = (items_digested / items_scraped * 100) if items_scraped > 0 else 0
            
            # Convert datetime objects to ISO strings if present
            started_at = record.get("started_at")
            updated_at = record.get("updated_at")
            
            if started_at and hasattr(started_at, 'isoformat'):
                started_at = started_at.isoformat()
            elif started_at:
                started_at = str(started_at)
                
            if updated_at and hasattr(updated_at, 'isoformat'):
                updated_at = updated_at.isoformat()
            elif updated_at:
                updated_at = str(updated_at)
            
            batches.append(BatchProgress(
                batch_id=record["batch_id"],
                datasource_id=record["datasource_id"],
                status=record["status"],
                items_scraped=items_scraped,
                items_digested=items_digested,
                started_at=started_at,
                updated_at=updated_at,
                progress_percent=round(progress_percent, 1)
            ))
        
        # Close connection
        neo4j_client.close()
        
        return batches
        
    except Exception as e:
        logger.error(f"Failed to get active batches: {e}", exc_info=True)
        # Return empty list instead of error to not break dashboard
        return []


@router.delete("/clear-completed")
async def clear_completed():
    """
    Clear the recently completed list.
    """
    try:
        r = get_redis_connection()
        r.delete("processing:completed")
        return {"status": "success", "message": "Recently completed list cleared"}
    except redis.ConnectionError:
        raise HTTPException(status_code=503, detail="Redis not available")
    except Exception as e:
        logger.error(f"Failed to clear completed list: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to clear completed list")


@router.delete("/clear-failed")
async def clear_failed():
    """
    Clear the recently failed list.
    """
    try:
        r = get_redis_connection()
        r.delete("processing:failed")
        return {"status": "success", "message": "Recently failed list cleared"}
    except redis.ConnectionError:
        raise HTTPException(status_code=503, detail="Redis not available")
    except Exception as e:
        logger.error(f"Failed to clear failed list: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to clear failed list")


@router.delete("/purge-queue")
async def purge_queue():
    """
    Purge all messages from the RabbitMQ queue.
    WARNING: This will delete all pending documents in the queue!
    """
    try:
        queue_name = os.getenv("RABBITMQ_QUEUE", "document_processing")
        
        try:
            connection = get_rabbitmq_connection()
            channel = connection.channel()
            
            # Purge the queue
            purged = channel.queue_purge(queue=queue_name)
            message_count = purged.method.message_count
            
            connection.close()
            
            logger.info(f"Purged {message_count} messages from queue {queue_name}")
            return {
                "status": "success", 
                "message": f"Purged {message_count} messages from queue",
                "queue_name": queue_name,
                "messages_purged": message_count
            }
            
        except Exception as e:
            logger.error(f"Failed to purge queue: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to purge queue: {str(e)}")
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to connect to RabbitMQ: {e}")
        raise HTTPException(status_code=503, detail=f"RabbitMQ not available: {str(e)}")


@router.delete("/purge-digester")
async def purge_digester(also_purge_queue: bool = False):
    """
    Signal the digester service to stop processing further documents and optionally purge the queue.
    This sets a Redis flag that the digester checks before processing each message.
    When the flag is detected the digester will ack any prefetched messages without processing and
    stop its consumer loop.

    Args:
        also_purge_queue: If True, purge the RabbitMQ queue after setting the stop flag.
    """
    try:
        # Set stop flag in Redis
        try:
            r = get_redis_connection()
            r.setex("digester:stop", 300, "1")  # expire in 5 minutes as safety
        except Exception as e:
            logger.error(f"Failed to set digester stop flag: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to set digester stop flag: {str(e)}")

        purged_info = None
        if also_purge_queue:
            # Re-use purge logic
            queue_name = os.getenv("RABBITMQ_QUEUE", "document_processing")
            try:
                connection = get_rabbitmq_connection()
                channel = connection.channel()
                purged = channel.queue_purge(queue=queue_name)
                message_count = purged.method.message_count
                connection.close()
                purged_info = {
                    "queue_name": queue_name,
                    "messages_purged": message_count
                }
                logger.info(f"Purged {message_count} messages from queue {queue_name} as part of digester purge")
            except Exception as e:
                logger.error(f"Failed to purge queue during digester purge: {e}")
                raise HTTPException(status_code=500, detail=f"Digester stop set but failed to purge queue: {str(e)}")

        response = {
            "status": "success",
            "message": "Digester stop signal set",
            "also_purged_queue": also_purge_queue
        }
        if purged_info:
            response.update(purged_info)
        return response
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Unexpected error purging digester: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to purge digester: {str(e)}")


# ========== System Configuration Endpoints ==========

class SystemConfigurationResponse(BaseModel):
    """System configuration model for API responses."""
    model_config = {"from_attributes": True}
    
    datasource_id: str
    name: str
    scraper_type: Optional[str] = None
    resource_url: Optional[str] = None
    scrape_schedule: Optional[str] = None  # Cron expression
    run_on_startup: bool = False
    check_content_hash: bool
    publish_weight: float = Field(..., ge=0.0, le=1.0)
    update_weight: float = Field(..., ge=0.0, le=1.0)
    event_weight: float = Field(..., ge=0.0, le=1.0)
    temporal_extraction_days: int = Field(default=90, ge=1)
    scraper_delay: Optional[float] = Field(default=0.5, ge=0.0, le=10.0)
    max_resources: Optional[int] = Field(default=150, ge=-1)
    max_redirects: Optional[int] = Field(default=10, ge=0, le=50)
    folders: Optional[List[str]] = Field(default=None, description="Folder paths for hierarchical scrapers (e.g., WFA Causeway)")
    discovery_mode: str = Field(default="incremental", description="Discovery mode: 'incremental' or 'date_based'")
    consecutive_duplicates_limit: int = Field(default=5, ge=0, description="Stop after this many consecutive duplicate URLs (incremental mode)")
    full_refresh_schedule: Optional[str] = Field(default=None, description="Cron expression for full refresh (incremental mode only)")
    ingestion_lookback_value: int = Field(default=12, ge=1, description="Global ingestion lookback amount for automated scraper ingestion")
    ingestion_lookback_unit: Literal["days", "weeks", "months", "years"] = Field(default="months", description="Global ingestion lookback unit for automated scraper ingestion")
    last_scraped_at: Optional[str] = None  # ISO format string from Neo4j
    created_at: Optional[str] = None  # ISO format string from Neo4j
    updated_at: Optional[str] = None  # ISO format string from Neo4j


class SystemConfigurationCreate(BaseModel):
    """Model for creating system configuration."""
    datasource_id: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    scraper_type: Optional[str] = Field(default=None, max_length=100, description="Scraper class to use (e.g., 'wfa', 'wfa_causeway')")
    resource_url: Optional[str] = Field(default=None, max_length=500, description="URL path to scrape")
    scrape_schedule: Optional[str] = Field(default=None, max_length=100, description="Cron expression (e.g., '0 2 * * *' for 2 AM daily)")
    run_on_startup: bool = Field(default=False, description="Run immediately when retriever starts")
    check_content_hash: bool = True
    publish_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    update_weight: float = Field(default=0.8, ge=0.0, le=1.0)
    event_weight: float = Field(default=0.9, ge=0.0, le=1.0)
    temporal_extraction_days: int = Field(default=90, ge=1)
    scraper_delay: float = Field(default=0.5, ge=0.0, le=10.0, description="Delay between requests in seconds")
    max_resources: int = Field(default=150, ge=-1, description="Max resources per scrape run (-1 = unlimited)")
    max_redirects: int = Field(default=10, ge=0, le=50, description="Max redirects to follow (0 = no redirects)")
    folders: Optional[List[str]] = Field(default=None, description="Folder paths for hierarchical scrapers (e.g., WFA Causeway)")
    discovery_mode: str = Field(default="incremental", description="Discovery mode: 'incremental' or 'date_based'")
    consecutive_duplicates_limit: int = Field(default=5, ge=0, description="Stop after this many consecutive duplicate URLs (incremental mode)")
    full_refresh_schedule: Optional[str] = Field(default=None, max_length=100, description="Cron expression for full refresh (incremental mode only)")
    ingestion_lookback_value: int = Field(default=12, ge=1, description="Global ingestion lookback amount for automated scraper ingestion")
    ingestion_lookback_unit: Literal["days", "weeks", "months", "years"] = Field(default="months", description="Global ingestion lookback unit for automated scraper ingestion")



class SystemConfigurationUpdate(BaseModel):
    """Model for updating system configuration."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    scraper_type: Optional[str] = Field(None, max_length=100, description="Scraper class to use (e.g., 'wfa', 'wfa_causeway')")
    resource_url: Optional[str] = Field(None, max_length=500, description="URL path to scrape")
    scrape_schedule: Optional[str] = Field(None, max_length=100, description="Cron expression (e.g., '0 2 * * *' for 2 AM daily)")
    run_on_startup: Optional[bool] = Field(None, description="Run immediately when retriever starts")
    check_content_hash: Optional[bool] = None
    publish_weight: Optional[float] = Field(None, ge=0.0, le=1.0)
    update_weight: Optional[float] = Field(None, ge=0.0, le=1.0)
    event_weight: Optional[float] = Field(None, ge=0.0, le=1.0)
    temporal_extraction_days: Optional[int] = Field(None, ge=1)
    scraper_delay: Optional[float] = Field(None, ge=0.0, le=10.0, description="Delay between requests in seconds")
    max_resources: Optional[int] = Field(None, ge=-1, description="Max resources per scrape run (-1 = unlimited)")
    max_redirects: Optional[int] = Field(None, ge=0, le=50, description="Max redirects to follow (0 = no redirects)")
    folders: Optional[List[str]] = Field(None, description="Folder paths for hierarchical scrapers (e.g., WFA Causeway)")
    discovery_mode: Optional[str] = Field(None, description="Discovery mode: 'incremental' or 'date_based'")
    consecutive_duplicates_limit: Optional[int] = Field(None, ge=0, description="Stop after this many consecutive duplicate URLs (incremental mode)")
    full_refresh_schedule: Optional[str] = Field(None, max_length=100, description="Cron expression for full refresh (incremental mode only)")
    ingestion_lookback_value: Optional[int] = Field(None, ge=1, description="Global ingestion lookback amount for automated scraper ingestion")
    ingestion_lookback_unit: Optional[Literal["days", "weeks", "months", "years"]] = Field(None, description="Global ingestion lookback unit for automated scraper ingestion")



@router.get("/system-configuration", response_model=List[SystemConfigurationResponse])
async def get_all_system_configurations():
    """
    Get all system configurations from Neo4j DataSource nodes.
    """
    try:
        configs = graph_service.get_all_datasource_configurations()
        return configs
    except Exception as e:
        logger.error(f"Failed to get system configurations: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get system configurations: {str(e)}")


@router.get("/system-configuration/{datasource_id}", response_model=SystemConfigurationResponse)
async def get_system_configuration(datasource_id: str):
    """
    Get system configuration for a specific datasource from Neo4j.
    """
    try:
        config = graph_service.get_datasource_configuration(datasource_id)
        if not config:
            raise HTTPException(status_code=404, detail=f"Configuration for datasource '{datasource_id}' not found")
        return config
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get system configuration: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get system configuration: {str(e)}")


@router.post("/system-configuration", response_model=SystemConfigurationResponse, status_code=201)
async def create_system_configuration(config: SystemConfigurationCreate):
    """
    Create or update system configuration for a datasource in Neo4j.
    """
    try:
        result = graph_service.upsert_datasource_configuration(
            datasource_id=config.datasource_id,
            name=config.name,
            scraper_type=config.scraper_type,
            resource_url=config.resource_url,
            scrape_schedule=config.scrape_schedule,
            run_on_startup=config.run_on_startup,
            check_content_hash=config.check_content_hash,
            publish_weight=config.publish_weight,
            update_weight=config.update_weight,
            event_weight=config.event_weight,
            temporal_extraction_days=config.temporal_extraction_days,
            scraper_delay=config.scraper_delay,
            max_resources=config.max_resources,
            max_redirects=config.max_redirects,
            folders=config.folders,
            discovery_mode=config.discovery_mode,
            consecutive_duplicates_limit=config.consecutive_duplicates_limit,
            full_refresh_schedule=config.full_refresh_schedule,
            ingestion_lookback_value=config.ingestion_lookback_value,
            ingestion_lookback_unit=config.ingestion_lookback_unit
        )
        return result
    except Exception as e:
        logger.error(f"Failed to create system configuration: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create system configuration: {str(e)}")


@router.patch("/system-configuration/{datasource_id}", response_model=SystemConfigurationResponse)
async def update_system_configuration(datasource_id: str, config: SystemConfigurationUpdate):
    """
    Update system configuration for a datasource in Neo4j.
    Only updates provided fields, leaving others unchanged.
    """
    try:
        # Check if configuration exists
        existing = graph_service.get_datasource_configuration(datasource_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Configuration for datasource '{datasource_id}' not found")
        
        result = graph_service.upsert_datasource_configuration(
            datasource_id=datasource_id,
            name=config.name,
            scraper_type=config.scraper_type,
            resource_url=config.resource_url,
            scrape_schedule=config.scrape_schedule,
            run_on_startup=config.run_on_startup,
            check_content_hash=config.check_content_hash,
            publish_weight=config.publish_weight,
            update_weight=config.update_weight,
            event_weight=config.event_weight,
            temporal_extraction_days=config.temporal_extraction_days,
            scraper_delay=config.scraper_delay,
            max_resources=config.max_resources,
            max_redirects=config.max_redirects,
            folders=config.folders,
            discovery_mode=config.discovery_mode,
            consecutive_duplicates_limit=config.consecutive_duplicates_limit,
            full_refresh_schedule=config.full_refresh_schedule,
            ingestion_lookback_value=config.ingestion_lookback_value,
            ingestion_lookback_unit=config.ingestion_lookback_unit
        )
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to update system configuration: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to update system configuration: {str(e)}")


@router.delete("/system-configuration/{datasource_id}")
async def delete_system_configuration(datasource_id: str):
    """
    Delete system configuration for a datasource from Neo4j.
    """
    try:
        # Check if configuration exists
        existing = graph_service.get_datasource_configuration(datasource_id)
        if not existing:
            raise HTTPException(status_code=404, detail=f"Configuration for datasource '{datasource_id}' not found")
        
        success = graph_service.delete_datasource_configuration(datasource_id)
        if not success:
            raise HTTPException(status_code=500, detail="Failed to delete configuration")
        
        return {"status": "success", "message": f"Configuration for datasource '{datasource_id}' deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete system configuration: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete system configuration: {str(e)}")


# ========== Chat Analytics Endpoints ==========

class ConversationWithUserResponse(BaseModel):
    """Conversation with user details for admin view."""
    id: int
    user_id: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    email: str
    display_name: Optional[str]
    message_count: int


class ConversationDetailWithUserResponse(BaseModel):
    """Conversation detail with user info for admin view."""
    id: int
    user_id: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime
    email: str
    display_name: Optional[str]


class MessageResponse(BaseModel):
    """Chat message."""
    id: int
    conversation_id: int
    user_id: str
    role: str
    content: str
    metadata: Optional[Dict[str, Any]]
    created_at: datetime


class ChatStatisticsResponse(BaseModel):
    """Chat statistics for admin dashboard."""
    total_conversations: int
    unique_users: int
    total_messages: int
    user_messages: int
    assistant_messages: int
    avg_messages_per_conversation: float
    recent_conversations: int


@router.get("/conversations", response_model=List[ConversationWithUserResponse])
async def get_all_conversations_admin(limit: int = 100, user_id: Optional[str] = None):
    """
    Get all conversations for admin view.
    Includes user email and message count.
    Optionally filter by user_id.
    """
    try:
        conversations = postgres.get_all_conversations_admin(limit=limit, user_id=user_id)
        return [ConversationWithUserResponse(**conv) for conv in conversations]
    except Exception as e:
        logger.error(f"Error fetching conversations for admin: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/conversations/{conversation_id}")
async def get_conversation_detail_admin(conversation_id: int):
    """
    Get conversation details with all messages for admin view.
    Includes user information.
    """
    try:
        conversation = postgres.get_conversation_with_user_admin(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        messages = postgres.get_conversation_messages(conversation_id)
        
        return {
            "conversation": ConversationDetailWithUserResponse(**conversation),
            "messages": [MessageResponse(**msg) for msg in messages]
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching conversation {conversation_id} for admin: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/chat-statistics", response_model=ChatStatisticsResponse)
async def get_chat_statistics():
    """
    Get overall chat statistics for admin dashboard.
    """
    try:
        stats = postgres.get_chat_statistics()
        return ChatStatisticsResponse(**stats)
    except Exception as e:
        logger.error(f"Error fetching chat statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/users/{user_id}/sync")
async def sync_user_to_graph(user_id: str):
    """
    Sync a user from Postgres to Neo4j as a Person node.
    Uses the same deduplication logic as the login process to avoid creating duplicates.
    
    Args:
        user_id: UUID of the user to sync
        
    Returns:
        Success message with sync details
    """
    
    try:
        # Get user from Postgres
        user = postgres.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        logger.info(f"Syncing user {user_id} ({user['email']}) to Neo4j graph")
        
        # Use the same sync logic as login (handles deduplication)
        try:
            postgres._ensure_user_in_neo4j(
                user_uuid=user['id'],
                email=user['email'],
                full_name=user['display_name'] or user['email']
            )
            logger.info(f"_ensure_user_in_neo4j completed for user {user_id}")
        except Exception as sync_error:
            logger.error(f"Error in _ensure_user_in_neo4j for user {user_id}: {sync_error}", exc_info=True)
            raise HTTPException(status_code=500, detail=f"Failed to sync user to Neo4j: {str(sync_error)}")
        
        # Give Neo4j a moment to ensure transaction is committed
        time.sleep(0.5)
        
        # Check if user now exists in graph
        synced = graph_service.check_user_in_graph(user['id'])
        logger.info(f"User {user_id} sync status check: synced={synced}")
        
        if not synced:
            logger.warning(f"User {user_id} sync completed but user not found in graph - checking Neo4j connection")
            # Additional diagnostic query to check if any Person nodes exist
            try:
                repo = graph_service.get_repo()
                check_query = "MATCH (p:Person) WHERE p.user_uuid = $user_uuid OR p.email = $email RETURN p LIMIT 1"
                results = repo.client.execute_query(check_query, {"user_uuid": user['id'], "email": user['email']})
                if results:
                    person = dict(results[0]['p'])
                    logger.warning(f"Found Person node but not by user_uuid: {person}")
                    return {
                        "success": True,
                        "message": f"User {user['email']} found in graph but user_uuid may need updating",
                        "synced_to_graph": False,
                        "debug_info": {"found_person": person}
                    }
            except Exception as debug_error:
                logger.error(f"Debug query failed: {debug_error}")
        
        return {
            "success": True,
            "message": f"User {user['email']} synced to graph using deduplication logic",
            "synced_to_graph": synced
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error syncing user {user_id} to graph: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# ========== Dead Letter Queue (DLQ) Endpoints ==========

class DLQMessage(BaseModel):
    """Dead letter queue message."""
    message_id: int  # Position in queue for identification
    title: str
    url: str
    category: str
    error: str
    error_timestamp: str
    batch_id: Optional[str] = None
    datasource_id: Optional[str] = None
    message_type: Optional[str] = None  # "resource" or "event"
    original_scraped_at: Optional[str] = None
    is_duplicate: bool = False  # True if this URL appears multiple times in DLQ
    duplicate_count: int = 1  # How many times this URL appears


class DLQDuplicateGroup(BaseModel):
    """Group of duplicate messages with the same URL."""
    url: str
    title: str
    count: int
    message_ids: List[int]  # All message IDs for this URL
    newest_message_id: int  # The one to keep (most recent error_timestamp)
    oldest_error_timestamp: str
    newest_error_timestamp: str


class DLQFilterOptions(BaseModel):
    """Available filter options for DLQ."""
    error_types: List[str]
    batch_ids: List[str]
    datasource_ids: List[str]


class DLQStatus(BaseModel):
    """DLQ status response."""
    queue_name: str
    message_count: int
    messages: List[DLQMessage]
    filter_options: DLQFilterOptions
    duplicate_count: int = 0  # Number of URLs that have duplicates
    duplicate_message_count: int = 0  # Total extra messages that are duplicates
    duplicates: List[DLQDuplicateGroup] = []  # Grouped duplicate info
    inspected_count: int = 0
    truncated: bool = False


class DLQRetryRequest(BaseModel):
    """Request to retry specific DLQ messages."""
    message_ids: List[int]


class DLQRetryResponse(BaseModel):
    """Response after retrying DLQ messages."""
    success: bool
    retried_count: int
    failed_count: int
    message: str


class DLQDedupeResponse(BaseModel):
    """Response after deduplicating DLQ."""
    success: bool
    duplicates_removed: int
    unique_messages_kept: int
    message: str


@router.get("/dlq-messages", response_model=DLQStatus)
async def get_dlq_messages(
    error_filter: Optional[str] = None,
    batch_id: Optional[str] = None,
    datasource_id: Optional[str] = None,
    limit: int = 100
):
    """
    Get messages from the Dead Letter Queue with optional filtering.
    
    Args:
        error_filter: Filter by error message (case-insensitive partial match)
        batch_id: Filter by batch ID
        datasource_id: Filter by datasource ID
        limit: Maximum messages to return (default 100)
    """
    # Run blocking RabbitMQ operations in a thread to avoid blocking the event loop
    return await asyncio.to_thread(
        _get_dlq_messages_sync,
        error_filter,
        batch_id,
        datasource_id,
        limit
    )


def _get_dlq_messages_sync(
    error_filter: Optional[str] = None,
    batch_id: Optional[str] = None,
    datasource_id: Optional[str] = None,
    limit: int = 100
) -> DLQStatus:
    """Synchronous implementation of get_dlq_messages."""
    dlq_name = f"{os.getenv('RABBITMQ_QUEUE', 'document_processing')}-dlq"
    empty_filter_options = DLQFilterOptions(error_types=[], batch_ids=[], datasource_ids=[])
    peek_limit = max(limit * 10, 500)
    
    try:
        try:
            connection = get_rabbitmq_connection()
            channel = connection.channel()
        except Exception as e:
            logger.warning(f"RabbitMQ not available for DLQ: {e}")
            return DLQStatus(
                queue_name=dlq_name,
                message_count=0,
                messages=[],
                filter_options=empty_filter_options
            )
        
        # Declare the DLQ queue (check if exists with passive=True first)
        try:
            # First try passive=True to just check if queue exists
            queue = channel.queue_declare(queue=dlq_name, durable=True, passive=True)
            total_messages = queue.method.message_count
        except Exception as e:
            # Queue doesn't exist - try to create it (might fail with read-only user)
            logger.info(f"DLQ queue {dlq_name} not found, attempting to create: {e}")
            try:
                # Need to recreate channel after failed passive declare
                connection.close()
                connection = get_rabbitmq_connection()
                channel = connection.channel()
                queue = channel.queue_declare(queue=dlq_name, durable=True, passive=False)
                total_messages = queue.method.message_count
            except Exception as create_err:
                logger.warning(f"Could not create DLQ queue {dlq_name}: {create_err}")
                try:
                    connection.close()
                except Exception:
                    pass
                return DLQStatus(
                    queue_name=dlq_name,
                    message_count=0,
                    messages=[],
                    filter_options=empty_filter_options
                )
        
        logger.info(f"DLQ queue {dlq_name} has {total_messages} messages")
        
        # Fetch a bounded sample from the DLQ so large queues remain inspectable.
        all_messages_data = []
        peeked_tags = []
        position = 0
        
        # Sets to collect unique filter values
        error_types_set = set()
        batch_ids_set = set()
        datasource_ids_set = set()
        
        inspected_target = min(total_messages, peek_limit)
        logger.info(f"Peeking at up to {inspected_target} messages from DLQ (total={total_messages})")
        for _ in range(inspected_target):
            method_frame, header_frame, body = channel.basic_get(queue=dlq_name, auto_ack=False)
            
            if not method_frame:
                break
            
            peeked_tags.append(method_frame.delivery_tag)
            position += 1
            
            try:
                message = json.loads(body)
                
                # Extract message data
                resource_data = message.get("resource_data", {})
                event_data = message.get("event_data", {})
                
                title = resource_data.get("title") or event_data.get("name") or "Unknown"
                url = resource_data.get("url") or event_data.get("url") or ""
                category = resource_data.get("category") or event_data.get("type") or "unknown"
                error = message.get("dlq_error", "Unknown error")
                error_timestamp = message.get("dlq_timestamp", "")
                msg_batch_id = message.get("batch_id")
                msg_datasource_id = message.get("datasource_id")
                message_type = message.get("message_type", "resource")
                scraped_at = resource_data.get("scraped_at") or event_data.get("scraped_at")
                
                # Collect filter options from ALL messages (before filtering)
                # Extract error type (first part of error message, up to colon or first 50 chars)
                error_type = error.split(':')[0].strip() if ':' in error else error[:50].strip()
                if error_type:
                    error_types_set.add(error_type)
                if msg_batch_id:
                    batch_ids_set.add(msg_batch_id)
                if msg_datasource_id:
                    datasource_ids_set.add(msg_datasource_id)
                
                # Convert scraped_at timestamp if present
                original_scraped_at = None
                if scraped_at:
                    try:
                        if isinstance(scraped_at, (int, float)):
                            original_scraped_at = datetime.fromtimestamp(scraped_at).isoformat()
                        else:
                            original_scraped_at = str(scraped_at)
                    except Exception:
                        original_scraped_at = str(scraped_at)
                
                # Store message data for filtering
                all_messages_data.append({
                    "message_id": position,
                    "title": title,
                    "url": url,
                    "category": category,
                    "error": error,
                    "error_type": error_type,
                    "error_timestamp": error_timestamp,
                    "batch_id": msg_batch_id,
                    "datasource_id": msg_datasource_id,
                    "message_type": message_type,
                    "original_scraped_at": original_scraped_at
                })
                    
            except Exception as e:
                logger.warning(f"Error parsing DLQ message: {e}")
                continue
        
        logger.info(f"Peeked {len(all_messages_data)} messages, re-queuing {len(peeked_tags)} tags")
        
        # Re-queue all peeked messages
        for tag in peeked_tags:
            channel.basic_nack(delivery_tag=tag, requeue=True)
        
        logger.info("Re-queued all messages, closing connection")
        
        try:
            connection.close()
        except Exception:
            pass
        
        logger.info("Connection closed, processing duplicates")
        # Detect duplicates by URL (normalize URL for comparison)
        def normalize_url(url: str) -> str:
            """Normalize URL for duplicate detection."""
            if not url:
                return ""
            # Remove trailing slashes
            url = url.rstrip('/')
            # Remove common tracking parameters
            from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
            try:
                parsed = urlparse(url)
                # Remove tracking params
                params = parse_qs(parsed.query)
                # Remove common tracking params
                for track_param in ['utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term', 'ref', 'source']:
                    params.pop(track_param, None)
                # Rebuild query string
                new_query = urlencode(params, doseq=True)
                normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', new_query, ''))
                return normalized.lower()
            except Exception:
                return url.lower()
        
        # Track messages by URL for duplicate detection
        url_to_messages: Dict[str, List[Dict]] = {}
        
        for msg_data in all_messages_data:
            url = msg_data["url"]
            
            if url:
                normalized_url = normalize_url(url)
                if normalized_url not in url_to_messages:
                    url_to_messages[normalized_url] = []
                url_to_messages[normalized_url].append(msg_data)
        
        # Build duplicate groups and mark messages
        duplicates = []
        url_duplicate_count = {}  # normalized_url -> count for marking messages
        
        # Process URL-based duplicates
        for url, msgs in url_to_messages.items():
            if len(msgs) > 1:
                url_duplicate_count[url] = len(msgs)
                # Sort by error_timestamp to find newest
                sorted_msgs = sorted(msgs, key=lambda m: m["error_timestamp"] or "", reverse=True)
                newest = sorted_msgs[0]
                oldest = sorted_msgs[-1]
                
                duplicates.append(DLQDuplicateGroup(
                    url=url,
                    title=newest["title"],
                    count=len(msgs),
                    message_ids=[m["message_id"] for m in msgs],
                    newest_message_id=newest["message_id"],
                    oldest_error_timestamp=oldest["error_timestamp"] or "",
                    newest_error_timestamp=newest["error_timestamp"] or ""
                ))
        
        # Sort duplicates by count descending
        duplicates.sort(key=lambda d: d.count, reverse=True)
        
        # Calculate duplicate stats
        duplicate_count = len(duplicates)
        duplicate_message_count = sum(d.count - 1 for d in duplicates)  # Extra messages beyond the first
        
        # Now apply filters to get the result set
        filtered_messages = []
        for msg_data in all_messages_data:
            # Apply filters
            if error_filter and error_filter.lower() not in msg_data["error"].lower():
                continue
            if batch_id and msg_data["batch_id"] != batch_id:
                continue
            if datasource_id and msg_data["datasource_id"] != datasource_id:
                continue
            
            # Mark duplicates (use normalized URL for comparison)
            url = msg_data["url"]
            normalized_url = normalize_url(url) if url else ""
            
            # Check if duplicate by URL
            is_duplicate = normalized_url in url_duplicate_count
            dup_count = url_duplicate_count.get(normalized_url, 1)
            
            filtered_messages.append(DLQMessage(
                message_id=msg_data["message_id"],
                title=msg_data["title"],
                url=msg_data["url"],
                category=msg_data["category"],
                error=msg_data["error"],
                error_timestamp=msg_data["error_timestamp"],
                batch_id=msg_data["batch_id"],
                datasource_id=msg_data["datasource_id"],
                message_type=msg_data["message_type"],
                original_scraped_at=msg_data["original_scraped_at"],
                is_duplicate=is_duplicate,
                duplicate_count=dup_count
            ))
            
            if len(filtered_messages) >= limit:
                break
        
        # Build filter options
        filter_options = DLQFilterOptions(
            error_types=sorted(list(error_types_set)),
            batch_ids=sorted(list(batch_ids_set)),
            datasource_ids=sorted(list(datasource_ids_set))
        )
        
        return DLQStatus(
            queue_name=dlq_name,
            message_count=total_messages,
            messages=filtered_messages,
            filter_options=filter_options,
            duplicate_count=duplicate_count,
            duplicate_message_count=duplicate_message_count,
            duplicates=duplicates,
            inspected_count=len(all_messages_data),
            truncated=total_messages > len(all_messages_data)
        )
        
    except Exception as e:
        logger.error(f"Failed to get DLQ messages: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to get DLQ messages: {str(e)}")


@router.post("/dlq-retry", response_model=DLQRetryResponse)
async def retry_dlq_messages(request: DLQRetryRequest):
    """
    Retry specific messages from the DLQ by re-queuing them to the main queue.
    
    Messages are identified by their position (message_id) in the DLQ.
    The selected messages are removed from DLQ and added back to the main processing queue.
    """
    dlq_name = f"{os.getenv('RABBITMQ_QUEUE', 'document_processing')}-dlq"
    main_queue = os.getenv("RABBITMQ_QUEUE", "document_processing")
    
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()
        
        # Ensure main queue exists
        channel.queue_declare(queue=main_queue, durable=True)
        
        # Track results
        retried = 0
        failed = 0
        
        # We need to consume messages and only ack the ones we want to retry
        # This is tricky because RabbitMQ doesn't support random access
        # We'll consume all messages, retry selected ones, and requeue the rest
        
        messages_to_requeue = []
        messages_to_retry = []
        position = 0
        
        # First, consume all messages from DLQ
        while True:
            method_frame, header_frame, body = channel.basic_get(queue=dlq_name, auto_ack=True)
            if not method_frame:
                break
            
            position += 1
            
            try:
                message = json.loads(body)
                
                if position in request.message_ids:
                    # Remove DLQ metadata before retrying
                    message.pop("dlq_error", None)
                    message.pop("dlq_timestamp", None)
                    # Reset delivery attempts for fresh retry
                    message["delivery_attempts"] = 0
                    # Clear batch_id to prevent double-counting in batch progress
                    # (the original batch already counted this item when it went to DLQ)
                    message.pop("batch_id", None)
                    messages_to_retry.append(message)
                else:
                    messages_to_requeue.append(body)
            except Exception as e:
                logger.warning(f"Error processing DLQ message for retry: {e}")
                messages_to_requeue.append(body)
                failed += 1
        
        # Requeue non-selected messages back to DLQ
        for body in messages_to_requeue:
            channel.basic_publish(
                exchange='',
                routing_key=dlq_name,
                body=body,
                properties=pika.BasicProperties(delivery_mode=2)
            )
        
        # Publish selected messages to main queue for retry
        for message in messages_to_retry:
            try:
                channel.basic_publish(
                    exchange='',
                    routing_key=main_queue,
                    body=json.dumps(message),
                    properties=pika.BasicProperties(delivery_mode=2)
                )
                retried += 1
            except Exception as e:
                logger.error(f"Failed to retry message: {e}")
                # Put back in DLQ
                message["dlq_error"] = f"Retry failed: {str(e)}"
                message["dlq_timestamp"] = datetime.now().isoformat()
                channel.basic_publish(
                    exchange='',
                    routing_key=dlq_name,
                    body=json.dumps(message),
                    properties=pika.BasicProperties(delivery_mode=2)
                )
                failed += 1
        
        connection.close()
        
        logger.info(f"DLQ retry: {retried} messages retried, {failed} failed")
        
        return DLQRetryResponse(
            success=True,
            retried_count=retried,
            failed_count=failed,
            message=f"Retried {retried} messages, {failed} failed"
        )
        
    except Exception as e:
        logger.error(f"Failed to retry DLQ messages: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retry messages: {str(e)}")


@router.post("/dlq-retry-all", response_model=DLQRetryResponse)
async def retry_all_dlq_messages():
    """
    Retry ALL messages from the DLQ by re-queuing them to the main processing queue.
    
    WARNING: This will retry all failed messages. Use with caution.
    """
    dlq_name = f"{os.getenv('RABBITMQ_QUEUE', 'document_processing')}-dlq"
    main_queue = os.getenv("RABBITMQ_QUEUE", "document_processing")
    
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()
        
        # Ensure queues exist
        channel.queue_declare(queue=main_queue, durable=True)
        dlq_queue = channel.queue_declare(queue=dlq_name, durable=True, passive=False)
        total_messages = dlq_queue.method.message_count
        
        retried = 0
        failed = 0
        
        # Consume all messages from DLQ and republish to main queue
        while True:
            method_frame, header_frame, body = channel.basic_get(queue=dlq_name, auto_ack=True)
            if not method_frame:
                break
            
            try:
                message = json.loads(body)
                
                # Remove DLQ metadata
                message.pop("dlq_error", None)
                message.pop("dlq_timestamp", None)
                # Reset delivery attempts
                message["delivery_attempts"] = 0
                # Clear batch_id to prevent double-counting in batch progress
                # (the original batch already counted this item when it went to DLQ)
                message.pop("batch_id", None)
                
                channel.basic_publish(
                    exchange='',
                    routing_key=main_queue,
                    body=json.dumps(message),
                    properties=pika.BasicProperties(delivery_mode=2)
                )
                retried += 1
                
            except Exception as e:
                logger.error(f"Failed to retry DLQ message: {e}")
                # Put back in DLQ
                channel.basic_publish(
                    exchange='',
                    routing_key=dlq_name,
                    body=body,
                    properties=pika.BasicProperties(delivery_mode=2)
                )
                failed += 1
        
        connection.close()
        
        logger.info(f"DLQ retry all: {retried} messages retried out of {total_messages}, {failed} failed")
        
        return DLQRetryResponse(
            success=True,
            retried_count=retried,
            failed_count=failed,
            message=f"Retried {retried} of {total_messages} messages, {failed} failed"
        )
        
    except Exception as e:
        logger.error(f"Failed to retry all DLQ messages: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to retry all messages: {str(e)}")


@router.delete("/dlq-purge")
async def purge_dlq():
    """
    Purge ALL messages from the Dead Letter Queue.
    
    WARNING: This permanently deletes all failed messages!
    """
    dlq_name = f"{os.getenv('RABBITMQ_QUEUE', 'document_processing')}-dlq"
    
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()
        
        try:
            purged = channel.queue_purge(queue=dlq_name)
            message_count = purged.method.message_count
        except Exception:
            # Queue doesn't exist
            message_count = 0
        
        connection.close()
        
        logger.info(f"Purged {message_count} messages from DLQ {dlq_name}")
        
        return {
            "status": "success",
            "message": f"Purged {message_count} messages from Dead Letter Queue",
            "queue_name": dlq_name,
            "messages_purged": message_count
        }
        
    except Exception as e:
        logger.error(f"Failed to purge DLQ: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to purge DLQ: {str(e)}")


@router.post("/dlq-dedupe", response_model=DLQDedupeResponse)
async def dedupe_dlq():
    """
    Remove duplicate messages from the DLQ, keeping only the most recent message for each URL.
    
    This is useful when the same document fails multiple times (e.g., scraper picks it up
    again because it's not in the DB yet).
    """
    dlq_name = f"{os.getenv('RABBITMQ_QUEUE', 'document_processing')}-dlq"
    
    try:
        connection = get_rabbitmq_connection()
        channel = connection.channel()
        
        # Consume all messages from DLQ
        all_messages = []
        while True:
            method_frame, header_frame, body = channel.basic_get(queue=dlq_name, auto_ack=True)
            if not method_frame:
                break
            
            try:
                message = json.loads(body)
                resource_data = message.get("resource_data", {})
                event_data = message.get("event_data", {})
                url = resource_data.get("url") or event_data.get("url") or ""
                error_timestamp = message.get("dlq_timestamp", "")
                
                all_messages.append({
                    "body": body,
                    "message": message,
                    "url": url,
                    "error_timestamp": error_timestamp
                })
            except Exception as e:
                # Keep unparseable messages
                all_messages.append({
                    "body": body,
                    "message": None,
                    "url": "",
                    "error_timestamp": ""
                })
        
        # Group by URL
        url_to_messages: Dict[str, List[Dict]] = {}
        messages_without_url = []
        
        for msg in all_messages:
            url = msg["url"]
            if url:
                if url not in url_to_messages:
                    url_to_messages[url] = []
                url_to_messages[url].append(msg)
            else:
                messages_without_url.append(msg)
        
        # For each URL group, keep only the newest message
        messages_to_keep = []
        duplicates_removed = 0
        
        for url, msgs in url_to_messages.items():
            if len(msgs) > 1:
                # Sort by error_timestamp descending (newest first)
                sorted_msgs = sorted(msgs, key=lambda m: m["error_timestamp"] or "", reverse=True)
                messages_to_keep.append(sorted_msgs[0])  # Keep newest
                duplicates_removed += len(sorted_msgs) - 1
            else:
                messages_to_keep.append(msgs[0])
        
        # Add messages without URL (can't dedupe these)
        messages_to_keep.extend(messages_without_url)
        
        # Re-publish kept messages back to DLQ
        for msg in messages_to_keep:
            channel.basic_publish(
                exchange='',
                routing_key=dlq_name,
                body=msg["body"],
                properties=pika.BasicProperties(delivery_mode=2)
            )
        
        connection.close()
        
        logger.info(f"DLQ dedupe: removed {duplicates_removed} duplicates, kept {len(messages_to_keep)} unique messages")
        
        return DLQDedupeResponse(
            success=True,
            duplicates_removed=duplicates_removed,
            unique_messages_kept=len(messages_to_keep),
            message=f"Removed {duplicates_removed} duplicate messages, kept {len(messages_to_keep)} unique messages"
        )
        
    except Exception as e:
        logger.error(f"Failed to dedupe DLQ: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to dedupe DLQ: {str(e)}")


# ---------------------------------------------------------------------------
# Data-quality admin controls (T10-T12)
# ---------------------------------------------------------------------------

DATA_QUALITY_FIELDS = {
    "ingestion_lookback_days": {"type": int, "min": 30, "max": 730, "default": 365},
    "oracle_max_content_age_days": {"type": int, "min": 30, "max": 730, "default": 365},
    "creator_temporal_window_days": {"type": int, "min": 7, "max": 365, "default": 90},
    "creator_min_relevance_score": {"type": float, "min": 0.0, "max": 1.0, "default": 0.25},
    "initial_backfill_max_months": {"type": int, "min": 1, "max": 36, "default": 12},
}


class DataQualitySettings(BaseModel):
    ingestion_lookback_days: int = Field(365, ge=30, le=730,
        description="Max age of content accepted by the digester (days).")
    oracle_max_content_age_days: int = Field(365, ge=30, le=730,
        description="Oracle Cypher recency cap for temporal queries (days).")
    creator_temporal_window_days: int = Field(90, ge=7, le=365,
        description="Content creator fetch window (days).")
    creator_min_relevance_score: float = Field(0.25, ge=0.0, le=1.0,
        description="Minimum relevance score for content creator articles.")
    initial_backfill_max_months: int = Field(12, ge=1, le=36,
        description="Max months of history ingested on first scrape.")


def _get_neo4j_client() -> Neo4jClient:
    return Neo4jClient(
        uri=os.environ["NEO4J_URI"],
        user=os.environ["NEO4J_USER"],
        password=os.environ["NEO4J_PASSWORD"],
        database=os.environ.get("NEO4J_DATABASE", "neo4j"),
    )


def _get_redis_client():
    return redis.Redis(
        host=os.environ.get("REDIS_HOST", "redis"),
        port=int(os.environ.get("REDIS_PORT", 6379)),
        decode_responses=True,
    )


def _flush_fast_cache(r) -> int:
    """Flush all fast-pipeline Redis caches and return the number deleted."""
    keys = r.keys("fast:*")
    if keys:
        return r.delete(*keys)
    return 0


@router.get("/data-quality", response_model=DataQualitySettings, tags=["Data Quality"])
async def get_data_quality_settings():
    """Return the current data-quality runtime parameters from Neo4j."""
    client = _get_neo4j_client()
    try:
        result = client.run_query(
            """
            MATCH (ds:DataSource {datasource_id: 'default'})
            RETURN ds
            """,
            {},
        )
        node = result[0]["ds"] if result else {}
        settings = {}
        for field, meta in DATA_QUALITY_FIELDS.items():
            raw = node.get(field)
            if raw is None:
                settings[field] = meta["default"]
            else:
                try:
                    settings[field] = meta["type"](raw)
                except (ValueError, TypeError):
                    settings[field] = meta["default"]
        return DataQualitySettings(**settings)
    except Exception as e:
        logger.error("Failed to read data-quality settings: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Neo4j error: {e}")
    finally:
        client.close()


@router.put("/data-quality", response_model=DataQualitySettings, tags=["Data Quality"])
async def update_data_quality_settings(settings: DataQualitySettings):
    """Update data-quality runtime parameters in Neo4j and flush fast caches."""
    client = _get_neo4j_client()
    try:
        props = settings.model_dump()
        client.run_query(
            """
            MERGE (ds:DataSource {datasource_id: 'default'})
            SET ds += $props
            """,
            {"props": props},
        )
        # Flush fast pipeline cache so new settings take effect immediately
        try:
            r = _get_redis_client()
            flushed = _flush_fast_cache(r)
            logger.info("Flushed %d fast-cache keys after data-quality update", flushed)
        except Exception as re:
            logger.warning("Redis flush failed (non-fatal): %s", re)

        return settings
    except Exception as e:
        logger.error("Failed to update data-quality settings: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Neo4j error: {e}")
    finally:
        client.close()


class FreshnessAuditRow(BaseModel):
    datasource_id: Optional[str]
    name: Optional[str]
    total: int
    oldest: Optional[str]
    newest: Optional[str]
    recent_90d: int
    recent_30d: int
    temporal_confidence_low: int


class FreshnessAuditResponse(BaseModel):
    generated_at: str
    rows: List[FreshnessAuditRow]


@router.get("/freshness-audit", response_model=FreshnessAuditResponse, tags=["Data Quality"])
async def freshness_audit():
    """Return per-datasource content age distribution for operator review.

    Helps identify which sources are delivering stale content so operators
    can adjust scraper schedules or trigger archive-stale cleanup.
    """
    client = _get_neo4j_client()
    try:
        results = client.run_query(
            """
            MATCH (r:Resource)
            OPTIONAL MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
            WITH ds,
                 r.publish_date AS pd,
                 coalesce(r.temporal_confidence, 'high') AS tc
            RETURN
                ds.datasource_id AS datasource_id,
                ds.name AS name,
                count(r) AS total,
                min(CASE WHEN pd IS NOT NULL AND pd <> '' THEN pd END) AS oldest,
                max(CASE WHEN pd IS NOT NULL AND pd <> '' THEN pd END) AS newest,
                count(CASE WHEN pd IS NOT NULL AND pd <> ''
                      AND datetime(pd) >= datetime() - duration({days: 90}) THEN 1 END) AS recent_90d,
                count(CASE WHEN pd IS NOT NULL AND pd <> ''
                      AND datetime(pd) >= datetime() - duration({days: 30}) THEN 1 END) AS recent_30d,
                count(CASE WHEN tc = 'low' THEN 1 END) AS temporal_confidence_low
            ORDER BY newest DESC
            """,
            {},
        )
        rows = [
            FreshnessAuditRow(
                datasource_id=row.get("datasource_id"),
                name=row.get("name"),
                total=row.get("total", 0),
                oldest=row.get("oldest"),
                newest=row.get("newest"),
                recent_90d=row.get("recent_90d", 0),
                recent_30d=row.get("recent_30d", 0),
                temporal_confidence_low=row.get("temporal_confidence_low", 0),
            )
            for row in results
        ]
        return FreshnessAuditResponse(
            generated_at=datetime.utcnow().isoformat(),
            rows=rows,
        )
    except Exception as e:
        logger.error("Freshness audit failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=f"Neo4j error: {e}")
    finally:
        client.close()
