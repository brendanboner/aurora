"""Events API routes."""

from fastapi import APIRouter, HTTPException, Header, Query
from typing import Optional
from pydantic import BaseModel
import logging

from ..services import events_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


class AttendanceRequest(BaseModel):
    """Request model for marking attendance."""
    attending: bool = True
    is_presenting: bool = False


@router.get("")
async def list_events(
    upcoming: Optional[bool] = Query(None, description="Filter by upcoming (true) or past (false) events"),
    datasource_id: Optional[str] = Query(None, description="Filter by datasource ID"),
    event_type: Optional[str] = Query(None, description="Filter by event type"),
    sort_by: str = Query("start_date", description="Sort by field (start_date, name, event_type)"),
    sort_order: str = Query("asc", description="Sort order (asc, desc)"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    x_user_id: Optional[str] = Header(None)
):
    """
    Get list of events with optional filtering and sorting.
    
    - **upcoming**: Filter upcoming (true) or past (false) events, or all (null)
    - **datasource_id**: Filter by datasource
    - **event_type**: Filter by event type (conference, meeting, webinar, etc.)
    - **sort_by**: Sort field (start_date, name, event_type)
    - **sort_order**: asc or desc
    """
    try:
        events = events_service.get_events(
            upcoming=upcoming,
            datasource_id=datasource_id,
            event_type=event_type,
            sort_by=sort_by,
            sort_order=sort_order,
            limit=limit,
            offset=offset
        )
        return {
            "events": events,
            "count": len(events),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        logger.error(f"Error listing events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve events")


@router.get("/{url_hash}")
async def get_event(
    url_hash: str,
    x_user_id: Optional[str] = Header(None)
):
    """
    Get a single event by URL hash.
    
    Returns event details including:
    - Event information
    - Attendance count
    - Presenter count
    - User's attendance status (if authenticated)
    """
    try:
        event = events_service.get_event_by_id(url_hash, user_id=x_user_id)
        
        if not event:
            raise HTTPException(status_code=404, detail="Event not found")
        
        return event
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting event {url_hash}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve event details")


@router.get("/{url_hash}/attendees")
async def get_event_attendees(
    url_hash: str,
    x_user_id: Optional[str] = Header(None)
):
    """
    Get list of people attending an event.
    
    Returns list of attendees with:
    - Name
    - Email (if available)
    - Whether they're presenting
    - When they marked attendance
    """
    try:
        attendees = events_service.get_event_attendees(url_hash)
        return {
            "attendees": attendees,
            "count": len(attendees)
        }
    except Exception as e:
        logger.error(f"Error getting attendees for event {url_hash}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve event attendees")


@router.post("/{url_hash}/attendance")
async def mark_event_attendance(
    url_hash: str,
    request: AttendanceRequest,
    x_user_id: str = Header(...)
):
    """
    Mark or update attendance for an event.
    
    Requires authentication (X-User-Id header).
    
    - **attending**: true to mark attendance, false to remove
    - **is_presenting**: whether user is presenting at the event
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        result = events_service.mark_attendance(
            user_uuid=x_user_id,
            url_hash=url_hash,
            is_presenting=request.is_presenting,
            attending=request.attending
        )
        
        if not result.get("success"):
            error = result.get("error", "Failed to update attendance")
            raise HTTPException(status_code=400, detail=error)
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error marking attendance for event {url_hash}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update attendance")


@router.get("/user/attending")
async def get_user_attending_events(
    upcoming_only: bool = Query(True, description="Only show upcoming events"),
    x_user_id: str = Header(...)
):
    """
    Get events that the authenticated user is attending.
    
    Requires authentication (X-User-Id header).
    
    - **upcoming_only**: If true, only return upcoming events
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        events = events_service.get_user_attending_events(
            user_uuid=x_user_id,
            upcoming_only=upcoming_only
        )
        return {
            "events": events,
            "count": len(events)
        }
    except Exception as e:
        logger.error(f"Error getting user attending events: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve user's events")


@router.get("/metadata/filters")
async def get_event_filters():
    """
    Get available filter values for events.
    
    Returns:
    - **event_types**: List of distinct event types
    - **datasources**: List of datasources with id and name
    """
    try:
        filters = events_service.get_event_filters()
        return filters
    except Exception as e:
        logger.error(f"Error getting event filters: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve filter options")
