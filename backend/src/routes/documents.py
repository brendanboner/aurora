"""Documents API routes for user uploads."""

from fastapi import APIRouter, HTTPException, Header, Query
from typing import Optional, List
from pydantic import BaseModel
import logging

from ..services import documents_service

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["documents"])


class DocumentResponse(BaseModel):
    """Response model for a document."""
    url_hash: str
    title: str
    url: str
    category: str
    doc_type: Optional[str] = None
    s3_key: Optional[str] = None
    s3_bucket: Optional[str] = None
    uploaded_at: Optional[str] = None
    uploaded_by: Optional[str] = None


class DocumentUpdateRequest(BaseModel):
    """Request model for updating a document."""
    title: Optional[str] = None
    category: Optional[str] = None
    related_events: Optional[List[str]] = None  # List of event url_hashes


class DocumentDownloadResponse(BaseModel):
    """Response model for document download URL."""
    download_url: str
    expires_in: int


@router.get("/user-uploads")
async def get_user_uploads(
    x_user_id: str = Header(...),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0)
):
    """
    Get documents uploaded by the current user.
    
    Requires authentication (X-User-Id header).
    
    Returns list of documents the user has uploaded.
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        documents = documents_service.get_user_uploads(
            user_uuid=x_user_id,
            limit=limit,
            offset=offset
        )
        return {
            "documents": documents,
            "count": len(documents),
            "limit": limit,
            "offset": offset
        }
    except Exception as e:
        logger.error(f"Error getting user uploads: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve user uploads")


@router.get("/categories")
async def get_document_categories():
    """
    Get available document categories for user uploads.
    
    Returns list of predefined categories with descriptions.
    """
    try:
        categories = documents_service.get_document_categories()
        return {"categories": categories}
    except Exception as e:
        logger.error(f"Error getting document categories: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve categories")


@router.get("/{url_hash}/download")
async def get_document_download_url(
    url_hash: str,
    x_user_id: str = Header(...)
):
    """
    Get a presigned S3 URL for document download.
    
    Only accessible to authenticated Aurora users.
    The URL expires after 1 hour.
    
    Args:
        url_hash: The document's url_hash (unique identifier)
    
    Returns:
        Presigned download URL and expiration time
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        result = documents_service.get_document_download_url(url_hash)
        
        if not result:
            raise HTTPException(status_code=404, detail="Document not found or not available for download")
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting download URL for {url_hash}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to generate download URL")


@router.get("/{url_hash}")
async def get_document(
    url_hash: str,
    x_user_id: Optional[str] = Header(None)
):
    """
    Get document details by URL hash.
    
    Args:
        url_hash: The document's url_hash (unique identifier)
    
    Returns:
        Document details including title, category, and upload info
    """
    try:
        document = documents_service.get_document_by_id(url_hash)
        
        if not document:
            raise HTTPException(status_code=404, detail="Document not found")
        
        return document
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting document {url_hash}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve document")


@router.patch("/{url_hash}")
async def update_document(
    url_hash: str,
    request: DocumentUpdateRequest,
    x_user_id: str = Header(...)
):
    """
    Update a document's metadata.
    
    Only the owner can update their documents.
    
    Args:
        url_hash: The document's url_hash
        request: Update fields (title, category)
    
    Returns:
        Updated document details
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        result = documents_service.update_document(
            url_hash=url_hash,
            user_uuid=x_user_id,
            title=request.title,
            category=request.category,
            related_events=request.related_events
        )
        
        if not result:
            raise HTTPException(
                status_code=404, 
                detail="Document not found or you don't have permission to update it"
            )
        
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating document {url_hash}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to update document")


@router.delete("/{url_hash}")
async def delete_document(
    url_hash: str,
    x_user_id: str = Header(...)
):
    """
    Delete a document.
    
    Only the owner can delete their documents.
    
    Args:
        url_hash: The document's url_hash
    
    Returns:
        Success message
    """
    if not x_user_id:
        raise HTTPException(status_code=401, detail="Authentication required")
    
    try:
        success = documents_service.delete_document(
            url_hash=url_hash,
            user_uuid=x_user_id
        )
        
        if not success:
            raise HTTPException(
                status_code=404, 
                detail="Document not found or you don't have permission to delete it"
            )
        
        return {"message": "Document deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting document {url_hash}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to delete document")


@router.get("/{url_hash}/events")
async def get_document_events(
    url_hash: str,
    x_user_id: Optional[str] = Header(None)
):
    """
    Get events related to a document.
    
    Args:
        url_hash: The document's url_hash
    
    Returns:
        List of related events
    """
    try:
        events = documents_service.get_document_events(url_hash)
        return {"events": events}
    except Exception as e:
        logger.error(f"Error getting events for document {url_hash}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Failed to retrieve document events")
