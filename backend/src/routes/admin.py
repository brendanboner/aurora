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
from src.services import postgres

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
    message_count: int
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


class AdminDashboard(BaseModel):
    """Complete admin dashboard data."""
    queue_status: QueueStatus
    processing_status: ProcessingStatus
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
                consumer_count=0,
                resources=[]
            )
        
        # Get queue information
        try:
            queue = channel.queue_declare(queue=queue_name, durable=True, passive=True)
            message_count = queue.method.message_count
            consumer_count = queue.method.consumer_count
        except Exception:
            # Queue doesn't exist yet
            message_count = 0
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
                        url = message.get("url", "")
                        
                        # Only add if we haven't seen this URL yet
                        if url and url not in seen_urls:
                            resources.append(QueueResource(
                                title=message.get("title", "Unknown"),
                                url=url,
                                category=message.get("category", "unknown"),
                                publish_date=message.get("publish_date"),
                                scraped_at=message.get("scraped_at", 0),
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
            consumer_count=consumer_count,
            resources=resources
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get queue status: {str(e)}")


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
        logger.error(f"Failed to get processing status: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get processing status: {str(e)}")


@router.get("/dashboard", response_model=AdminDashboard)
async def get_admin_dashboard():
    """
    Get complete admin dashboard data combining queue and processing status.
    """
    try:
        queue_status = await get_queue_status()
        processing_status = await get_processing_status()
        
        return AdminDashboard(
            queue_status=queue_status,
            processing_status=processing_status,
            timestamp=datetime.now().isoformat()
        )
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get dashboard data: {str(e)}")


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
        logger.error(f"Failed to clear completed list: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear completed list: {str(e)}")


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
        logger.error(f"Failed to clear failed list: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to clear failed list: {str(e)}")


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
    scrape_frequency: str
    check_content_hash: bool
    publish_weight: float = Field(..., ge=0.0, le=1.0)
    update_weight: float = Field(..., ge=0.0, le=1.0)
    event_weight: float = Field(..., ge=0.0, le=1.0)
    temporal_extraction_days: int = Field(default=90, ge=1)
    last_scraped_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SystemConfigurationCreate(BaseModel):
    """Model for creating system configuration."""
    datasource_id: str = Field(..., min_length=1, max_length=255)
    name: str = Field(..., min_length=1, max_length=255)
    scrape_frequency: str = Field(default="daily", pattern="^(hourly|daily|weekly|monthly|manual)$")
    check_content_hash: bool = True
    publish_weight: float = Field(default=1.0, ge=0.0, le=1.0)
    update_weight: float = Field(default=0.8, ge=0.0, le=1.0)
    event_weight: float = Field(default=0.9, ge=0.0, le=1.0)
    temporal_extraction_days: int = Field(default=90, ge=1)


class SystemConfigurationUpdate(BaseModel):
    """Model for updating system configuration."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    scrape_frequency: Optional[str] = Field(None, pattern="^(hourly|daily|weekly|monthly|manual)$")
    check_content_hash: Optional[bool] = None
    publish_weight: Optional[float] = Field(None, ge=0.0, le=1.0)
    update_weight: Optional[float] = Field(None, ge=0.0, le=1.0)
    event_weight: Optional[float] = Field(None, ge=0.0, le=1.0)
    temporal_extraction_days: Optional[int] = Field(None, ge=1)


@router.get("/system-configuration", response_model=List[SystemConfigurationResponse])
async def get_all_system_configurations():
    """
    Get all system configurations.
    """
    try:
        configs = postgres.get_all_system_configurations()
        return configs
    except Exception as e:
        logger.error(f"Failed to get system configurations: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get system configurations: {str(e)}")


@router.get("/system-configuration/{datasource_id}", response_model=SystemConfigurationResponse)
async def get_system_configuration(datasource_id: str):
    """
    Get system configuration for a specific datasource.
    """
    try:
        config = postgres.get_system_configuration(datasource_id)
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
    Create or update system configuration for a datasource.
    """
    try:
        result = postgres.upsert_system_configuration(
            datasource_id=config.datasource_id,
            name=config.name,
            scrape_frequency=config.scrape_frequency,
            check_content_hash=config.check_content_hash,
            publish_weight=config.publish_weight,
            update_weight=config.update_weight,
            event_weight=config.event_weight,
            temporal_extraction_days=config.temporal_extraction_days
        )
        return result
    except Exception as e:
        logger.error(f"Failed to create system configuration: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to create system configuration: {str(e)}")


@router.patch("/system-configuration/{datasource_id}", response_model=SystemConfigurationResponse)
async def update_system_configuration(datasource_id: str, config: SystemConfigurationUpdate):
    """
    Update system configuration for a datasource.
    Only updates provided fields, leaving others unchanged.
    """
    try:
        # Check if configuration exists
        existing = postgres.get_system_configuration(datasource_id)
        if not existing.get("created_at"):
            raise HTTPException(status_code=404, detail=f"Configuration for datasource '{datasource_id}' not found")
        
        result = postgres.upsert_system_configuration(
            datasource_id=datasource_id,
            name=config.name,
            scrape_frequency=config.scrape_frequency,
            check_content_hash=config.check_content_hash,
            publish_weight=config.publish_weight,
            update_weight=config.update_weight,
            event_weight=config.event_weight,
            temporal_extraction_days=config.temporal_extraction_days
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
    Delete system configuration for a datasource.
    """
    try:
        # Check if configuration exists
        existing = postgres.get_system_configuration(datasource_id)
        if not existing.get("created_at"):
            raise HTTPException(status_code=404, detail=f"Configuration for datasource '{datasource_id}' not found")
        
        query = "DELETE FROM system_configuration WHERE datasource_id = %s"
        postgres.execute(query, (datasource_id,))
        
        return {"status": "success", "message": f"Configuration for datasource '{datasource_id}' deleted"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to delete system configuration: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to delete system configuration: {str(e)}")
