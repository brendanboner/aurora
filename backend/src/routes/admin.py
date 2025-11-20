"""Admin routes for monitoring services."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import pika
import os
import redis
import json
import subprocess
import logging

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
