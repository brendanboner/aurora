"""Admin routes for monitoring services."""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import List, Optional, Dict, Any
from datetime import datetime
import pika
import os
import redis
import json

router = APIRouter(prefix="/admin", tags=["Admin"])


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


class ProcessingStatus(BaseModel):
    """Current processing status."""
    retriever_active: bool
    digester_active: bool
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
        
        # Peek at messages in queue (non-destructive)
        resources = []
        if message_count > 0:
            try:
                method_frame, header_frame, body = channel.basic_get(queue=queue_name, auto_ack=False)
                position = 1
                
                while method_frame and position <= 50:  # Limit to first 50 messages
                    try:
                        message = json.loads(body)
                        resources.append(QueueResource(
                            title=message.get("title", "Unknown"),
                            url=message.get("url", ""),
                            category=message.get("category", "unknown"),
                            publish_date=message.get("publish_date"),
                            scraped_at=message.get("scraped_at", 0),
                            position=position
                        ))
                        
                        # Re-queue the message (we were just peeking)
                        channel.basic_nack(delivery_tag=method_frame.delivery_tag, requeue=True)
                        
                    except json.JSONDecodeError:
                        channel.basic_nack(delivery_tag=method_frame.delivery_tag, requeue=True)
                    
                    method_frame, header_frame, body = channel.basic_get(queue=queue_name, auto_ack=False)
                    position += 1
            except Exception:
                pass  # Ignore errors when peeking at messages
        
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
    Uses Redis to track current processing state.
    """
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
            retriever_current=ProcessingResource(**json.loads(retriever_current)) if retriever_current else None,
            digester_current=ProcessingResource(**json.loads(digester_current)) if digester_current else None,
            recent_completed=recent_completed,
            recent_failed=recent_failed
        )
        
    except redis.ConnectionError:
        # Redis not available - return minimal status
        return ProcessingStatus(
            retriever_active=False,
            digester_active=False,
            retriever_current=None,
            digester_current=None,
            recent_completed=[],
            recent_failed=[]
        )
    except Exception as e:
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
