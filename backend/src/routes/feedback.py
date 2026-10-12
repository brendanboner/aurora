"""User feedback routes."""

from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime
import logging

from common.auth_middleware import get_user_context, require_user_context, require_role
from src.services import postgres

router = APIRouter(prefix="/feedback", tags=["Feedback"])
logger = logging.getLogger(__name__)


# ========== Request/Response Models ==========

class FeedbackSubmit(BaseModel):
    """Model for submitting feedback."""
    feedback_text: str = Field(..., min_length=1, max_length=5000, description="Feedback content")
    category: str = Field(..., description="Category: 'feedback', 'bug', 'accessibility', or 'styling'")
    
    class Config:
        json_schema_extra = {
            "example": {
                "feedback_text": "The search feature would be more useful with filters.",
                "category": "feedback"
            }
        }


class FeedbackStatusUpdate(BaseModel):
    """Model for updating feedback status (admin only)."""
    status: str = Field(..., description="Status: 'open', 'closed', 'in_progress', or 'paused'")
    priority: Optional[str] = Field(None, description="Priority: 'low', 'medium', 'high', or 'urgent'")
    
    class Config:
        json_schema_extra = {
            "example": {
                "status": "in_progress",
                "priority": "high"
            }
        }


class FeedbackResponse(BaseModel):
    """Feedback record response."""
    id: int
    user_id: str
    feedback_text: str
    category: str
    status: str
    priority: Optional[str]
    submitted_at: datetime
    updated_at: datetime
    user_email: Optional[str] = None
    user_display_name: Optional[str] = None


class FeedbackStatistics(BaseModel):
    """Feedback statistics for admin dashboard."""
    total_feedback: int
    unique_users: int
    open_count: int
    in_progress_count: int
    paused_count: int
    closed_count: int
    bug_count: int
    accessibility_count: int
    styling_count: int
    general_feedback_count: int
    urgent_count: int
    high_count: int
    recent_submissions: int


# ========== User Endpoints ==========

@router.post("/submit", response_model=FeedbackResponse)
@require_user_context
async def submit_feedback(
    feedback: FeedbackSubmit,
    user: Optional[dict] = Depends(get_user_context)
):
    """
    Submit new feedback.
    Requires authentication.
    """
    try:
        # Validate category
        valid_categories = ['feedback', 'bug', 'accessibility', 'styling']
        if feedback.category not in valid_categories:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}"
            )
        
        logger.info(f"New {feedback.category} submission from user {user['email']}")
        
        result = postgres.create_feedback(
            user_id=user['user_id'],
            feedback_text=feedback.feedback_text,
            category=feedback.category
        )
        
        return FeedbackResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Failed to submit feedback: {str(e)}")


@router.get("/my-feedback", response_model=List[FeedbackResponse])
@require_user_context
async def get_my_feedback(
    limit: int = 50,
    user: Optional[dict] = Depends(get_user_context)
):
    """
    Get all feedback submitted by the current user.
    Requires authentication.
    """
    try:
        feedback_list = postgres.get_user_feedback(user_id=user['user_id'], limit=limit)
        return [FeedbackResponse(**f) for f in feedback_list]
    except Exception as e:
        logger.error(f"Error fetching user feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve feedback")


# ========== Admin Endpoints ==========

@router.get("/all", response_model=List[FeedbackResponse])
@require_role(["admin", "superadmin"])
async def get_all_feedback(
    status: Optional[str] = None,
    category: Optional[str] = None,
    priority: Optional[str] = None,
    limit: int = 100,
    offset: int = 0,
    user: Optional[dict] = Depends(get_user_context)
):
    """
    Get all feedback submissions with optional filters.
    Requires admin or superadmin role.
    """
    try:
        # Validate filters if provided
        if status:
            valid_statuses = ['open', 'closed', 'in_progress', 'paused']
            if status not in valid_statuses:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
                )
        
        if category:
            valid_categories = ['feedback', 'bug', 'accessibility', 'styling']
            if category not in valid_categories:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid category. Must be one of: {', '.join(valid_categories)}"
                )
        
        if priority:
            valid_priorities = ['low', 'medium', 'high', 'urgent']
            if priority not in valid_priorities:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid priority. Must be one of: {', '.join(valid_priorities)}"
                )
        
        logger.info(f"Admin {user['email']} fetching feedback (status={status}, category={category}, priority={priority})")
        
        feedback_list = postgres.get_all_feedback(
            status=status,
            category=category,
            priority=priority,
            limit=limit,
            offset=offset
        )
        
        return [FeedbackResponse(**f) for f in feedback_list]
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching all feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve feedback")


@router.get("/statistics", response_model=FeedbackStatistics)
@require_role(["admin", "superadmin"])
async def get_feedback_statistics(
    user: Optional[dict] = Depends(get_user_context)
):
    """
    Get feedback statistics for admin dashboard.
    Requires admin or superadmin role.
    """
    try:
        stats = postgres.get_feedback_statistics()
        return FeedbackStatistics(**stats)
    except Exception as e:
        logger.error(f"Error fetching feedback statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve statistics")


@router.get("/{feedback_id}", response_model=FeedbackResponse)
@require_role(["admin", "superadmin"])
async def get_feedback_by_id(
    feedback_id: int,
    user: Optional[dict] = Depends(get_user_context)
):
    """
    Get a specific feedback submission by ID.
    Requires admin or superadmin role.
    """
    try:
        feedback = postgres.get_feedback_by_id(feedback_id)
        
        if not feedback:
            raise HTTPException(status_code=404, detail="Feedback not found")
        
        return FeedbackResponse(**feedback)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching feedback {feedback_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve feedback")


@router.patch("/{feedback_id}", response_model=FeedbackResponse)
@require_role(["admin", "superadmin"])
async def update_feedback(
    feedback_id: int,
    update: FeedbackStatusUpdate,
    user: Optional[dict] = Depends(get_user_context)
):
    """
    Update feedback status and/or priority.
    Requires admin or superadmin role.
    """
    try:
        # Validate status
        valid_statuses = ['open', 'closed', 'in_progress', 'paused']
        if update.status not in valid_statuses:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid status. Must be one of: {', '.join(valid_statuses)}"
            )
        
        # Validate priority if provided
        if update.priority:
            valid_priorities = ['low', 'medium', 'high', 'urgent']
            if update.priority not in valid_priorities:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid priority. Must be one of: {', '.join(valid_priorities)}"
                )
        
        logger.info(f"Admin {user['email']} updating feedback {feedback_id}: status={update.status}, priority={update.priority}")
        
        result = postgres.update_feedback_status(
            feedback_id=feedback_id,
            status=update.status,
            priority=update.priority
        )
        
        if not result:
            raise HTTPException(status_code=404, detail="Feedback not found")
        
        return FeedbackResponse(**result)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating feedback {feedback_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update feedback")


@router.delete("/{feedback_id}")
@require_role(["superadmin"])
async def delete_feedback(
    feedback_id: int,
    user: Optional[dict] = Depends(get_user_context)
):
    """
    Delete a feedback submission.
    Requires superadmin role.
    """
    try:
        logger.warning(f"Superadmin {user['email']} deleting feedback {feedback_id}")
        
        rows_deleted = postgres.delete_feedback(feedback_id)
        
        if rows_deleted == 0:
            raise HTTPException(status_code=404, detail="Feedback not found")
        
        return {"status": "success", "message": f"Feedback {feedback_id} deleted"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting feedback {feedback_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete feedback")
