"""YouTube video ingestion endpoint for Oracle Service."""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from typing import Optional
import logging
import hashlib
import json
from datetime import datetime

from common.auth_middleware import get_user_context, require_user_context
from src.services.youtube_service import YouTubeService
from src.settings import settings

router = APIRouter(tags=["ingest"])
logger = logging.getLogger(__name__)


class YouTubeIngestRequest(BaseModel):
    """Request model for YouTube video ingestion."""
    url: str = Field(..., description="YouTube video URL")
    user_id: Optional[str] = Field(default=None, description="User who added the video")
    force_redigest: bool = Field(default=False, description="Force re-ingestion of existing video")


class YouTubeIngestResponse(BaseModel):
    """Response model for YouTube video ingestion."""
    success: bool
    video_id: str
    title: str
    has_transcript: bool
    duration_seconds: int
    segments_created: int
    message: str
    already_exists: Optional[bool] = Field(default=False, description="Whether video already existed")
    existing_video_title: Optional[str] = Field(default=None, description="Title of existing video")


@router.post("/ingest/youtube", response_model=YouTubeIngestResponse)
@require_user_context
async def ingest_youtube_video(
    request: YouTubeIngestRequest,
    user: Optional[dict] = Depends(get_user_context)
) -> YouTubeIngestResponse:
    """
    Ingest a YouTube video into the knowledge base.
    
    This endpoint:
    1. Validates the YouTube URL
    2. Fetches video metadata and transcript
    3. For long videos with agendas, creates segments
    4. Publishes to RabbitMQ for processing by digester
    5. Returns success status with video info
    """
    try:
        youtube_service = YouTubeService()
        
        # Validate and extract video ID
        video_id = youtube_service.extract_video_id(request.url)
        if not video_id:
            raise HTTPException(
                status_code=400,
                detail={
                    "error": "INVALID_URL",
                    "message": "Could not extract video ID from URL. Please provide a valid YouTube URL.",
                }
            )
        
        logger.info(f"Processing YouTube video: {video_id} (requested by {user.get('email', 'unknown')})")
        
        # Check if video already exists in Neo4j
        try:
            from neo4j_client.client import Neo4jClient
            from neo4j_client.repository import GraphRepository
            
            neo4j_client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password
            )
            repo = GraphRepository(neo4j_client)
            
            # Check for existing video by URL pattern (contains video_id)
            # YouTube URLs contain the video ID, so we can search for resources with this ID in the URL
            query = """
            MATCH (r:Resource)
            WHERE r.url CONTAINS $video_id
            RETURN r.title as title, r.url as url
            LIMIT 1
            """
            result = neo4j_client.execute_query(query, {"video_id": video_id})
            
            if result and len(result) > 0 and not request.force_redigest:
                existing_title = result[0].get('title', 'Unknown Video')
                logger.info(f"Video {video_id} already exists in database: {existing_title}")
                raise HTTPException(
                    status_code=409,
                    detail={
                        "error": "VIDEO_EXISTS",
                        "message": f"This video has already been processed: {existing_title}",
                        "video_id": video_id,
                        "existing_title": existing_title,
                    }
                )
        except HTTPException:
            raise
        except Exception as e:
            # If Neo4j check fails, log but continue (don't block ingestion)
            logger.warning(f"Could not check for duplicate video: {e}")
        
        # Process video: get metadata, transcript, and segments
        try:
            logger.info(f"Calling youtube_service.process_video for {request.url}")
            metadata, transcript, segments = await youtube_service.process_video(
                request.url,
                segment_long_videos=True,
                long_video_threshold=1800  # 30 minutes
            )
            logger.info(f"Successfully processed video: {metadata.title}")
        except ValueError as e:
            logger.error(f"ValueError processing video {video_id}: {e}")
            raise HTTPException(
                status_code=404,
                detail={
                    "error": "VIDEO_NOT_FOUND",
                    "message": str(e),
                }
            )
        except Exception as e:
            logger.error(f"Unexpected error processing video {video_id}: {e}", exc_info=True)
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "PROCESSING_ERROR",
                    "message": f"Failed to process video: {str(e)}",
                }
            )
        
        # Check if transcript is available
        if not transcript:
            logger.warning(f"No transcript available for video {video_id}")
            raise HTTPException(
                status_code=422,
                detail={
                    "error": "NO_TRANSCRIPT",
                    "message": f"This video does not have transcripts available. "
                               f"Please ensure the video has English captions enabled.",
                }
            )
        
        # Prepare message for RabbitMQ
        # Import here to avoid circular dependencies
        try:
            from rabbitmq_client import RabbitMQProducer
            import os
        except ImportError:
            logger.error("RabbitMQ client not available")
            raise HTTPException(
                status_code=503,
                detail={
                    "error": "SERVICE_UNAVAILABLE",
                    "message": "Message queue is not available",
                }
            )
        
        # Get RabbitMQ config from environment
        rabbitmq_config = {
            "host": os.getenv("RABBITMQ_HOST", "aurora-rabbitmq"),
            "port": int(os.getenv("RABBITMQ_PORT", "5672")),
            "user": os.getenv("RABBITMQ_USER", "user"),
            "password": os.getenv("RABBITMQ_PASSWORD", "password"),
            "queue": "scraped_content",
        }
        
        # Create URL hash
        url_hash = hashlib.sha256(metadata.url.encode()).hexdigest()
        
        # Prepare content (transcript with timestamps)
        content = transcript.formatted_with_timestamps
        
        # If we have segments, publish each segment separately
        messages_published = 0
        
        # Use context manager for RabbitMQ connection
        with RabbitMQProducer(**rabbitmq_config, logger_instance=logger) as producer:
            if segments:
                logger.info(f"Creating {len(segments)} segments for video {video_id}")
                
                # Publish parent video first
                parent_message = {
                    "message_type": "resource",
                    "datasource_id": "youtube",
                    "scraped_at": datetime.utcnow().isoformat(),
                    "uploaded_by": user.get('email') if user else None,
                    "resource_data": {
                        "url": metadata.url,
                        "url_hash": url_hash,
                        "title": metadata.title,
                        "content": content,
                        "category": "video",
                        "doc_type": "video",
                        "publish_date": metadata.publish_date or datetime.utcnow().isoformat(),
                        "metadata": {
                            "video_id": metadata.video_id,
                            "channel_name": metadata.channel_name,
                            "channel_id": metadata.channel_id,
                            "duration_seconds": metadata.duration_seconds,
                            "thumbnail_url": metadata.thumbnail_url,
                            "has_transcript": True,
                            "transcript_language": metadata.transcript_language,
                            "has_segments": True,
                            "total_segments": len(segments),
                        }
                    }
                }
                
                producer.publish(parent_message)
                messages_published += 1
                
                # Publish each segment
                for segment in segments:
                    segment_url = f"{metadata.url}&t={segment.timestamp_start}s"
                    segment_url_hash = hashlib.sha256(segment_url.encode()).hexdigest()
                    
                    segment_message = {
                        "message_type": "resource",
                        "datasource_id": "youtube",
                        "scraped_at": datetime.utcnow().isoformat(),
                        "uploaded_by": user.get('email') if user else None,
                        "resource_data": {
                            "url": segment_url,
                            "url_hash": segment_url_hash,
                            "title": f"{metadata.title} - {segment.title}",
                            "content": segment.transcript,
                            "category": "video",
                            "doc_type": "video",
                            "publish_date": metadata.publish_date or datetime.utcnow().isoformat(),
                            "metadata": {
                                "video_id": metadata.video_id,
                                "channel_name": metadata.channel_name,
                                "duration_seconds": metadata.duration_seconds,
                                "thumbnail_url": metadata.thumbnail_url,
                                "has_transcript": True,
                                "transcript_language": metadata.transcript_language,
                                "is_segment": True,
                                "segment_number": segment.segment_number,
                                "total_segments": segment.total_segments,
                                "timestamp_start": segment.timestamp_start,
                                "timestamp_end": segment.timestamp_end,
                                "parent_url": metadata.url,
                                "parent_url_hash": url_hash,
                            }
                        }
                    }
                    
                    producer.publish(segment_message)
                    messages_published += 1
            
            else:
                # Single video (no segments)
                message = {
                    "message_type": "resource",
                    "datasource_id": "youtube",
                    "scraped_at": datetime.utcnow().isoformat(),
                    "uploaded_by": user.get('email') if user else None,
                    "resource_data": {
                        "url": metadata.url,
                        "url_hash": url_hash,
                        "title": metadata.title,
                        "content": content,
                        "category": "video",
                        "doc_type": "video",
                        "publish_date": metadata.publish_date or datetime.utcnow().isoformat(),
                        "metadata": {
                            "video_id": metadata.video_id,
                            "channel_name": metadata.channel_name,
                            "channel_id": metadata.channel_id,
                            "duration_seconds": metadata.duration_seconds,
                            "thumbnail_url": metadata.thumbnail_url,
                            "has_transcript": True,
                            "transcript_language": metadata.transcript_language,
                            "has_segments": False,
                        }
                    }
                }
                
                producer.publish(message)
                messages_published = 1
        
        logger.info(f"Published {messages_published} messages for video {video_id}")
        
        return YouTubeIngestResponse(
            success=True,
            video_id=video_id,
            title=metadata.title,
            has_transcript=True,
            duration_seconds=metadata.duration_seconds,
            segments_created=len(segments),
            message=f"Video '{metadata.title}' queued for processing. " +
                   (f"{len(segments)} segments created." if segments else "")
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"YouTube ingestion failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "INTERNAL_ERROR",
                "message": f"Failed to process video: {str(e)}",
            }
        )
