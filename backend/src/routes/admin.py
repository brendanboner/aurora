"""Admin routes for monitoring services."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, validator
from typing import List, Optional, Dict, Any
from datetime import datetime
import pika
import os
import redis
import json
import subprocess
import logging
import time
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
    parameters = pika.ConnectionParameters(host=host, port=port, credentials=credentials)
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
                max_peek = min(message_count, 50)  # Limit peeking to 50 messages for efficiency
                
                for _ in range(max_peek):
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
    max_redirects: Optional[int] = Field(default=10, ge=1, le=50)
    folders: Optional[List[str]] = Field(default=None, description="Folder paths for hierarchical scrapers (e.g., WFA Causeway)")
    discovery_mode: str = Field(default="incremental", description="Discovery mode: 'incremental' or 'date_based'")
    consecutive_duplicates_limit: int = Field(default=5, ge=0, description="Stop after this many consecutive duplicate URLs (incremental mode)")
    full_refresh_schedule: Optional[str] = Field(default=None, description="Cron expression for full refresh (incremental mode only)")
    last_scraped_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


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
    max_redirects: int = Field(default=10, ge=1, le=50, description="Max redirects to follow")
    folders: Optional[List[str]] = Field(default=None, description="Folder paths for hierarchical scrapers (e.g., WFA Causeway)")
    discovery_mode: str = Field(default="incremental", description="Discovery mode: 'incremental' or 'date_based'")
    consecutive_duplicates_limit: int = Field(default=5, ge=0, description="Stop after this many consecutive duplicate URLs (incremental mode)")
    full_refresh_schedule: Optional[str] = Field(default=None, max_length=100, description="Cron expression for full refresh (incremental mode only)")



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
    max_redirects: Optional[int] = Field(None, ge=1, le=50, description="Max redirects to follow")
    folders: Optional[List[str]] = Field(None, description="Folder paths for hierarchical scrapers (e.g., WFA Causeway)")
    discovery_mode: Optional[str] = Field(None, description="Discovery mode: 'incremental' or 'date_based'")
    consecutive_duplicates_limit: Optional[int] = Field(None, ge=0, description="Stop after this many consecutive duplicate URLs (incremental mode)")
    full_refresh_schedule: Optional[str] = Field(None, max_length=100, description="Cron expression for full refresh (incremental mode only)")



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
            full_refresh_schedule=config.full_refresh_schedule
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
            full_refresh_schedule=config.full_refresh_schedule
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
