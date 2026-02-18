"""
Feed streaming endpoint for Server-Sent Events (SSE)
Provides real-time feed updates for Teams Tab integration
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from typing import AsyncGenerator, Optional
import asyncio
import json
import logging
from datetime import datetime
from common.auth_middleware import get_user_context, UserContext

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/feed", tags=["feed"])


@router.get("/stream")
async def stream_feed(
    user: UserContext = Depends(get_user_context),
) -> StreamingResponse:
    """
    Server-Sent Events endpoint for real-time feed updates.
    
    Client connects and receives feed updates as they occur.
    This endpoint streams:
    - feed_update: New posts, comments, likes from Creator Agent
    - notification: Toast notifications for users
    - chat_message: Auto-injected system messages from feed updates
    
    Example:
        const eventSource = new EventSource('/api/feed/stream', {
            withCredentials: true
        });
        eventSource.addEventListener('feed_update', (event) => {
            const data = JSON.parse(event.data);
            console.log('Feed update:', data);
        });
    """

    async def event_generator() -> AsyncGenerator[str, None]:
        """Generate SSE events for the client."""
        
        try:
            logger.info(f"[SSE] User {user.user_id} connected to feed stream")
            
            # Send initial connection confirmation
            yield f"event: connected\n"
            yield f"data: {json.dumps({'timestamp': datetime.utcnow().isoformat()})}\n\n"
            
            # Main event loop: stream updates to client
            # In production, this would listen to a message queue (RabbitMQ, etc.)
            # For now, we implement a polling loop that checks for new feed items
            
            last_check = datetime.utcnow()
            consecutive_empty = 0
            max_consecutive_empty = 30  # Disconnect after 5 minutes of no data
            
            while True:
                try:
                    # Poll for new feed items (every 5 seconds)
                    # In production, use RabbitMQ listener instead
                    await asyncio.sleep(5)
                    
                    # TODO: Replace with actual feed service call
                    # For now, this is a placeholder that demonstrates the flow
                    feed_items = await get_new_feed_items(user.user_id, last_check)
                    
                    if feed_items:
                        consecutive_empty = 0
                        for item in feed_items:
                            # Convert feed item to SSE event
                            yield f"event: feed_update\n"
                            yield f"data: {json.dumps(item)}\n\n"
                            last_check = datetime.utcnow()
                    else:
                        consecutive_empty += 1
                        if consecutive_empty >= max_consecutive_empty:
                            logger.info(f"[SSE] User {user.user_id} idle timeout, closing connection")
                            break
                        
                        # Send heartbeat to keep connection alive
                        yield f"event: heartbeat\n"
                        yield f"data: {{}}\n\n"
                        
                except asyncio.CancelledError:
                    logger.info(f"[SSE] User {user.user_id} connection cancelled")
                    break
                except Exception as e:
                    logger.error(f"[SSE] Error in feed stream for user {user.user_id}: {e}")
                    yield f"event: error\n"
                    yield f"data: {json.dumps({'error': str(e)})}\n\n"
                    break
                    
        except Exception as e:
            logger.error(f"[SSE] Fatal error in event generator: {e}")
        finally:
            logger.info(f"[SSE] User {user.user_id} disconnected from feed stream")

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


async def get_new_feed_items(user_id: str, since: datetime) -> list:
    """
    Fetch new feed items for a user since the last check.
    
    PRODUCTION IMPLEMENTATION:
    This should:
    1. Query your feed service (Content Creator Service endpoint)
    2. Filter items created/updated since 'since' timestamp
    3. Return items the user hasn't seen
    4. Consider using a message queue (RabbitMQ) instead for true real-time push
    
    For now, returns empty list (implement based on your feed service).
    """
    
    try:
        # TODO: Call content_creator_service or feed endpoint
        # Example:
        # response = await httpx.AsyncClient().get(
        #     f"{CONTENT_CREATOR_SERVICE_URL}/feed/timeline",
        #     params={"user_id": user_id, "since": since.isoformat()},
        #     timeout=5.0
        # )
        # if response.status_code == 200:
        #     return response.json().get("items", [])
        
        # Placeholder: no items for now
        return []
        
    except Exception as e:
        logger.error(f"Failed to fetch feed items for user {user_id}: {e}")
        return []


@router.get("/timeline")
async def get_feed_timeline(
    limit: int = 20,
    offset: int = 0,
    user: UserContext = Depends(get_user_context),
):
    """
    Get personalized feed timeline for the user.
    
    Returns recent posts from creators the user follows, ordered by recency.
    
    Query Parameters:
        limit: Number of items to return (default 20, max 100)
        offset: Number of items to skip for pagination (default 0)
    
    Returns:
        {
            "items": [
                {
                    "id": "post-123",
                    "author": "Creator Name",
                    "authorId": "user-456",
                    "content": "Post content...",
                    "timestamp": "2024-01-15T10:30:00Z",
                    "likes": 42,
                    "comments": 5,
                    "liked": false
                }
            ],
            "total": 156,
            "hasMore": true
        }
    """
    
    # Validate pagination params
    limit = min(limit, 100)
    offset = max(offset, 0)
    
    try:
        # TODO: Call content_creator_service to get feed
        # Example implementation:
        # feed_service = get_feed_service()
        # items = await feed_service.get_timeline(
        #     user_id=user.user_id,
        #     limit=limit,
        #     offset=offset
        # )
        
        # Placeholder response
        return {
            "items": [],
            "total": 0,
            "hasMore": False
        }
        
    except Exception as e:
        logger.error(f"Failed to get feed timeline for user {user.user_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to load feed")
