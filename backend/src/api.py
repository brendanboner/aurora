from fastapi import FastAPI, HTTPException, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, cast
from datetime import datetime
import logging
from pathlib import Path
import pika
import os
import json
import time
import httpx as _httpx

# Import auth middleware
from common.auth_middleware import get_user_context, require_user_context, require_role

# Import OpenTelemetry instrumentation
from common.telemetry import init_telemetry, instrument_fastapi

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

from src.services.query_engine import run_query
from src.services import postgres
from src.services import graph_service
from src.services.news_service import get_news_service
from src.routes import admin
from src.routes import events
from src.routes import feedback
from src.routes import documents

# Initialize OpenTelemetry
tracer, meter = init_telemetry(
    service_name="aurora-backend",
    service_version="1.0.0"
)

app = FastAPI(title="Aurora Backend API")

# Instrument FastAPI with OpenTelemetry
instrument_fastapi(app)


# Run database schema on startup to apply any migrations
@app.on_event("startup")
async def apply_schema():
    """Apply database schema (includes migration logic for existing databases)."""
    try:
        logger.info("Applying database schema...")
        schema_file = Path(__file__).parent.parent / "db_schema.sql"
        
        if schema_file.exists():
            with open(schema_file, 'r') as f:
                schema_sql = f.read()
            
            conn = postgres.get_conn()
            with conn.cursor() as cur:
                cur.execute(schema_sql)
            logger.info("✓ Database schema applied successfully")
        else:
            logger.warning(f"Schema file not found: {schema_file}")
    except Exception as e:
        logger.error(f"Error applying schema: {e}")
        # Don't fail startup - database may already be configured

# Include admin routes (router already has /admin prefix, accessed via nginx /api/ proxy)
app.include_router(admin.router, prefix="")

# Include events routes
app.include_router(events.router, prefix="")

# Include feedback routes
app.include_router(feedback.router, prefix="")

# Include documents routes
app.include_router(documents.router, prefix="")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],  # React dev server
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ========== Models ==========

class QueryRequest(BaseModel):
    user_id: str  # Changed from int to str for Cognito UUID
    question: str
    conversation_id: Optional[int] = None  # Optional: if provided, adds to existing conversation


class Document(BaseModel):
    title: str | None = None
    url: str | None = None
    publish_date: str | None = None
    summary: str | None = None
    topics: List[str] = []
    organisations: List[str] = []
    
    class Config:
        # Allow extra fields from query engine
        extra = "allow"


class QueryResponse(BaseModel):
    answer: str
    filters: Dict[str, Any]
    documents: List[Document]
    conversation_id: int  # Return the conversation ID for subsequent messages
    message_id: int  # ID of the assistant's message


class UserCreate(BaseModel):
    user_id: str  # Cognito UUID (required for manual user creation)
    email: str
    display_name: str


class UserResponse(BaseModel):
    id: str  # Changed from int to str for Cognito UUID
    email: str
    display_name: str | None
    created_at: datetime
    updated_at: datetime
    synced_to_graph: bool = False  # Whether user exists in Neo4j graph


class UserPreferences(BaseModel):
    topics: List[str] = []
    organisations: List[str] = []
    people: List[str] = []
    sources: List[str] = []
    domains: List[str] = []
    notify_email: bool = True
    notify_digest: bool = True


class GraphStatistics(BaseModel):
    resources: int
    topics: int
    organisations: int
    people: int
    events: int
    datasources: int
    relationships: int


class DocumentUpload(BaseModel):
    title: str
    url: str
    category: str
    content: str
    publish_date: Optional[str] = None
    datasource_id: str = "local_upload"
    uploaded_by: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None
    binary_content: Optional[str] = None  # base64-encoded binary content for caching


class UploadResponse(BaseModel):
    status: str
    message: str
    url: str


class NewsRequest(BaseModel):
    user_id: str  # Cognito UUID
    time_range: str = "1month"
    force_refresh: bool = False


class NewsResponse(BaseModel):
    headline: str
    summary: str
    sections: List[Dict[str, Any]]
    highlights: List[str]
    time_range: str
    document_count: int
    generated_at: str
    
    class Config:
        # Allow extra fields from LLM response
        extra = "allow"


class ConversationResponse(BaseModel):
    id: int
    user_id: str
    title: Optional[str]
    created_at: datetime
    updated_at: datetime


class MessageResponse(BaseModel):
    id: int
    conversation_id: int
    user_id: str
    role: str
    content: str
    metadata: Optional[Dict[str, Any]]
    created_at: datetime


class ConversationDetailResponse(BaseModel):
    conversation: ConversationResponse
    messages: List[MessageResponse]


# ========== Health Check ==========

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "aurora-backend"}


# ========== Internal Endpoints (called by other services) ==========

class UserSyncRequest(BaseModel):
    """Request model for user sync."""
    user_id: str
    email: str
    display_name: Optional[str] = None
    given_name: Optional[str] = None  # First name
    family_name: Optional[str] = None  # Last name


@app.post("/internal/sync-user")
async def sync_user_internal(req: UserSyncRequest):
    """
    Internal endpoint for syncing users to Postgres and Neo4j.
    Called by the auth service on user login.
    
    This endpoint:
    1. Creates user in Postgres if doesn't exist
    2. Syncs user to Neo4j with smart deduplication
    3. Updates existing Person nodes with user_uuid
    
    Note: This is an internal endpoint, typically accessed only by the auth service
    within the Docker network. It doesn't require user authentication headers since
    it's called during the login process before user context is established.
    """
    try:
        logger.info(f"Internal user sync: {req.user_id} ({req.email})")
        
        # Create/update user in Postgres and sync to Neo4j
        user = postgres.get_or_create_user(
            req.user_id, 
            req.email, 
            req.display_name,
            req.given_name,
            req.family_name
        )
        
        logger.info(f"User sync completed: {req.user_id}")
        
        return {
            "success": True,
            "user_id": user["id"],
            "email": user["email"],
            "display_name": user["display_name"]
        }
    except Exception as e:
        logger.error(f"Failed to sync user {req.user_id}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"User sync failed: {str(e)}"
        )


# ========== Query Endpoint ==========

@app.post("/query", response_model=QueryResponse)
@require_user_context
async def query(req: QueryRequest, user: Optional[dict] = Depends(get_user_context)) -> QueryResponse:
    """
    Process a natural language query.
    Requires authentication - only authenticated users can query.
    Auto-creates user if first query.
    """
    # Create a span for the entire orchestration pipeline
    with tracer.start_as_current_span("orchestrator.query_pipeline") as span:
        pipeline_start = time.time()
        
        try:
            logger.info(f"Query from user {user['email']} (role: {user['role']}): {req.question}")
            
            # Ensure user_id from request matches authenticated user (security check)
            if req.user_id != user["user_id"]:
                raise HTTPException(status_code=403, detail="User ID mismatch")
            
            # User must exist from login sync
            user_data = postgres.get_user_by_id(req.user_id)
            if not user_data:
                logger.error(f"User {req.user_id} not found - login sync failed")
                raise HTTPException(status_code=500, detail="User not synced - please log out and log back in")
            
            # Create or get conversation
            conversation_id = req.conversation_id
            if conversation_id:
                # Verify conversation belongs to user
                conversation = postgres.get_conversation(conversation_id)
                if not conversation or conversation["user_id"] != req.user_id:
                    raise HTTPException(status_code=403, detail="Invalid conversation ID")
            else:
                # Create new conversation
                conversation = postgres.create_conversation(req.user_id)
                conversation_id = conversation["id"]
                logger.info(f"Created new conversation {conversation_id} for user {req.user_id}")
            
            # Save user's question to database
            user_message = postgres.save_message(
                conversation_id=conversation_id,
                user_id=req.user_id,
                role="user",
                content=req.question,
                metadata=None
            )
            logger.info(f"Saved user message {user_message['id']} to conversation {conversation_id}")
            
            # Run the query
            result = run_query(req.user_id, req.question)
            
            # Save assistant's response to database
            assistant_metadata = {
                "filters": result["filters"],
                "documents": result["documents"]
            }
            assistant_message = postgres.save_message(
                conversation_id=conversation_id,
                user_id=req.user_id,
                role="assistant",
                content=result["answer"],
                metadata=assistant_metadata
            )
            logger.info(f"Saved assistant message {assistant_message['id']} to conversation {conversation_id}")
            
            # Auto-generate conversation title from first user message if not set
            if not conversation.get("title"):
                # Use first 50 chars of question as title
                title = req.question[:50] + ("..." if len(req.question) > 50 else "")
                postgres.update_conversation_title(conversation_id, title)
                logger.info(f"Set conversation {conversation_id} title to: {title}")
            
            # Record total pipeline duration
            pipeline_duration_ms = (time.time() - pipeline_start) * 1000
            span.set_attribute("orchestrator.pipeline.total_ms", pipeline_duration_ms)
            span.set_attribute("user.id", req.user_id)
            span.set_attribute("conversation.id", conversation_id)
            
            # Record metric
            pipeline_counter = meter.create_counter(
                name="orchestrator.pipeline.count",
                description="Number of query pipeline executions",
                unit="1"
            )
            pipeline_counter.add(1, {"user.id": req.user_id})
            
            pipeline_histogram = meter.create_histogram(
                name="orchestrator.pipeline.duration_ms",
                description="Query pipeline duration in milliseconds",
                unit="ms"
            )
            pipeline_histogram.record(pipeline_duration_ms, {"user.id": req.user_id})
            
            return QueryResponse(
                answer=result["answer"],
                filters=result["filters"],
                documents=[Document(**d) for d in result["documents"]],
                conversation_id=conversation_id,
                message_id=assistant_message["id"]
            )
        except HTTPException:
            raise
        except Exception as e:
            # Provide a structured error while preserving CORS headers.
            raise HTTPException(status_code=500, detail=f"Query failed: {e}")


# ========== User Management Endpoints ==========

@app.post("/users", response_model=UserResponse)
@require_role(["admin", "superadmin"])
async def create_user(user_data: UserCreate, user: Optional[dict] = Depends(get_user_context)):
    """
    Create a new user manually.
    Requires admin or superadmin role.
    
    NOTE: With Cognito auth, users are typically auto-created on first login.
    This endpoint is mainly for testing or special administrative cases.
    """
    try:
        logger.info(f"Manual user creation by {user['email']} (role: {user['role']})")
        # Check if user already exists
        existing = postgres.get_user_by_id(user_data.user_id)
        if existing:
            raise HTTPException(status_code=400, detail="User with this ID already exists")
        
        existing_email = postgres.get_user_by_email(user_data.email)
        if existing_email:
            raise HTTPException(status_code=400, detail="User with this email already exists")
        
        result = postgres.create_user(user_data.user_id, user_data.email, user_data.display_name)
        return UserResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/users", response_model=List[UserResponse])
@require_role(["admin", "superadmin"])
async def get_users(user: Optional[dict] = Depends(get_user_context)):
    """
    Get all users.
    Requires admin or superadmin role.
    """
    try:
        users = postgres.get_all_users()
        return [UserResponse(**u) for u in users]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/users/{user_id}", response_model=UserResponse)
@require_user_context
async def get_user(user_id: str, user: Optional[dict] = Depends(get_user_context)):  # Changed from int to str
    """
    Get a specific user.
    Users can view their own profile, admins can view any profile.
    Auto-creates user if viewing own profile for the first time.
    """
    try:
        # Check if user is accessing their own profile or is admin
        if user_id != user["user_id"] and user["role"] not in ["admin", "superadmin"]:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # If viewing own profile, user must exist from login sync
        if user_id == user["user_id"]:
            user_data = postgres.get_user_by_id(user_id)
            if not user_data:
                logger.error(f"User {user_id} not found - login sync failed")
                raise HTTPException(status_code=500, detail="User not synced - please log out and log back in")
        else:
            # Admin viewing another user - don't auto-create
            user_data = postgres.get_user_by_id(user_id)
            if not user_data:
                raise HTTPException(status_code=404, detail="User not found")
        
        return UserResponse(**user_data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/users/email/{email}", response_model=UserResponse)
@require_user_context
async def get_user_by_email(email: str, user: Optional[dict] = Depends(get_user_context)):
    """
    Get a user by email.
    Users can view their own profile, admins can view any profile.
    Auto-creates user if viewing own profile for the first time.
    """
    try:
        # Check if user is accessing their own profile or is admin
        if email != user["email"] and user["role"] not in ["admin", "superadmin"]:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # If viewing own profile, user must exist from login sync
        if email == user["email"]:
            user_data = postgres.get_user_by_id(user["user_id"])
            if not user_data:
                logger.error(f"User {user['user_id']} not found - login sync failed")
                raise HTTPException(status_code=500, detail="User not synced - please log out and log back in")
        else:
            # Admin viewing another user - don't auto-create
            user_data = postgres.get_user_by_email(email)
            if not user_data:
                raise HTTPException(status_code=404, detail="User not found")
        
        return UserResponse(**user_data)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/users/{user_id}")
@require_role(["superadmin"])
async def delete_user(user_id: str, user: Optional[dict] = Depends(get_user_context)):  # Changed from int to str
    """
    Delete a user.
    Requires superadmin role.
    """
    try:
        logger.warning(f"User deletion by {user['email']} (superadmin): user_id={user_id}")
        rows = postgres.delete_user(user_id)
        if rows == 0:
            raise HTTPException(status_code=404, detail="User not found")
        return {"message": "User deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== User Preferences Endpoints ==========

@app.get("/users/{user_id}/preferences", response_model=UserPreferences)
@require_user_context
async def get_preferences(user_id: str, user: Optional[dict] = Depends(get_user_context)):  # Changed from int to str
    """
    Get user preferences.
    Users can only view their own preferences unless they're admin.
    Auto-creates user if they don't exist (first login scenario).
    """
    try:
        # Check authorization
        if user_id != user["user_id"] and user["role"] not in ["admin", "superadmin"]:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # User must exist from login sync
        user_data = postgres.get_user_by_id(user_id)
        if not user_data:
            logger.error(f"User {user_id} not found - login sync failed")
            raise HTTPException(status_code=500, detail="User not synced - please log out and log back in")
        
        prefs = postgres.get_user_preferences(user_id)
        prefs_dict = cast(Dict[str, Any], prefs)
        return UserPreferences(**prefs_dict)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/users/{user_id}/preferences", response_model=UserPreferences)
@require_user_context
async def update_preferences(user_id: str, preferences: UserPreferences, user: Optional[dict] = Depends(get_user_context)):  # Changed from int to str
    """
    Update user preferences.
    Users can only update their own preferences unless they're admin.
    Auto-creates user if they don't exist (first login scenario).
    """
    try:
        # Check authorization
        if user_id != user["user_id"] and user["role"] not in ["admin", "superadmin"]:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # User must exist from login sync
        user_data = postgres.get_user_by_id(user_id)
        if not user_data:
            logger.error(f"User {user_id} not found - login sync failed")
            raise HTTPException(status_code=500, detail="User not synced - please log out and log back in")
        
        result = postgres.upsert_user_preferences(
            user_id=user_id,
            topics=preferences.topics,
            organisations=preferences.organisations,
            people=preferences.people,
            sources=preferences.sources,
            domains=preferences.domains,
            notify_email=preferences.notify_email,
            notify_digest=preferences.notify_digest
        )
        result_dict = cast(Dict[str, Any], result)
        return UserPreferences(**result_dict)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== Datasource Listing Endpoint ==========

class DatasourceInfo(BaseModel):
    datasource_id: str
    name: str
    source_type: str
    category: str  # 'workgroup' or 'public'
    fetch_url: Optional[str] = None
    area_acronym: Optional[str] = None
    area_name: Optional[str] = None


@app.get("/datasources", response_model=List[DatasourceInfo])
@require_user_context
async def list_datasources(user: Optional[dict] = Depends(get_user_context)):
    """
    List all datasources available for user preference selection.
    Returns workgroups (authenticated_portal) and public sources (scraped_webpage),
    grouped by category. Used by the Workgroup Preferences UI.
    """
    try:
        datasources = graph_service.get_listable_datasources()
        return [DatasourceInfo(**ds) for ds in datasources]
    except Exception as e:
        logger.error(f"Error fetching listable datasources: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== User Source Membership Endpoints ==========

class SourceMembershipRequest(BaseModel):
    status: str  # 'joined' or 'ignored'


class SourceMembershipResponse(BaseModel):
    user_id: str
    datasource_id: str
    status: str


class UserSourceMembershipsResponse(BaseModel):
    joined: List[str]
    ignored: List[str]


@app.get("/users/{user_id}/source-memberships", response_model=UserSourceMembershipsResponse)
@require_user_context
async def get_source_memberships(user_id: str, user: Optional[dict] = Depends(get_user_context)):
    """Get all workgroup/source membership preferences for a user."""
    try:
        if user_id != user["user_id"] and user["role"] not in ["admin", "superadmin"]:
            raise HTTPException(status_code=403, detail="Access denied")
        memberships = postgres.get_user_source_memberships(user_id)
        return UserSourceMembershipsResponse(**memberships)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/users/{user_id}/source-memberships/{datasource_id}", response_model=SourceMembershipResponse)
@require_user_context
async def upsert_source_membership(
    user_id: str,
    datasource_id: str,
    body: SourceMembershipRequest,
    user: Optional[dict] = Depends(get_user_context),
):
    """
    Set a user's membership status for a datasource.
    status='joined' boosts results from this source.
    status='ignored' hard-excludes results from this source.
    Saves instantly on toggle.
    """
    try:
        if user_id != user["user_id"] and user["role"] not in ["admin", "superadmin"]:
            raise HTTPException(status_code=403, detail="Access denied")
        if body.status not in ("joined", "ignored"):
            raise HTTPException(status_code=422, detail="status must be 'joined' or 'ignored'")
        result = postgres.upsert_user_source_membership(user_id, datasource_id, body.status)
        return SourceMembershipResponse(
            user_id=result["user_id"],
            datasource_id=result["datasource_id"],
            status=result["status"],
        )
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/users/{user_id}/source-memberships/{datasource_id}", status_code=204)
@require_user_context
async def delete_source_membership(
    user_id: str,
    datasource_id: str,
    user: Optional[dict] = Depends(get_user_context),
):
    """
    Remove a user's membership preference for a datasource (reverts to default behaviour).
    """
    try:
        if user_id != user["user_id"] and user["role"] not in ["admin", "superadmin"]:
            raise HTTPException(status_code=403, detail="Access denied")
        postgres.delete_user_source_membership(user_id, datasource_id)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== IETF Datatracker Endpoints ==========

_DATATRACKER_API = "https://datatracker.ietf.org/api/v1"
_ietf_area_cache: Optional[dict] = None
_ietf_area_cache_ts: float = 0.0
_IETF_AREA_CACHE_TTL = 3600  # 1 hour


async def _get_datatracker(path: str, params: Optional[dict] = None) -> dict:
    url = f"{_DATATRACKER_API}{path}"
    async with _httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        return resp.json()


@app.get("/ietf/areas")
async def list_ietf_areas(user: Optional[dict] = Depends(get_user_context)):
    """Return active IETF areas from Datatracker (cached 1 hr)."""
    global _ietf_area_cache, _ietf_area_cache_ts
    import time
    if _ietf_area_cache and (time.time() - _ietf_area_cache_ts) < _IETF_AREA_CACHE_TTL:
        return _ietf_area_cache
    try:
        data = await _get_datatracker("/group/group/", {"type": "area", "state": "active", "limit": 50})
        areas = [
            {"acronym": g["acronym"], "name": g["name"]}
            for g in data.get("objects", [])
        ]
        _ietf_area_cache = {"areas": areas}
        _ietf_area_cache_ts = time.time()
        return _ietf_area_cache
    except Exception as e:
        logger.error(f"Error fetching IETF areas: {e}")
        raise HTTPException(status_code=502, detail=f"Datatracker API error: {e}")


@app.get("/ietf/areas/{acronym}/workgroups")
async def list_ietf_workgroups(acronym: str, user: Optional[dict] = Depends(get_user_context)):
    """Return active IETF working groups for the given area acronym."""
    try:
        data = await _get_datatracker(
            "/group/group/",
            {"type": "wg", "parent__acronym": acronym, "state": "active", "limit": 200}
        )
        wgs = [
            {"acronym": g["acronym"], "name": g["name"], "area": acronym}
            for g in data.get("objects", [])
        ]
        return {"area": acronym, "workgroups": wgs}
    except Exception as e:
        logger.error(f"Error fetching IETF workgroups for {acronym}: {e}")
        raise HTTPException(status_code=502, detail=f"Datatracker API error: {e}")


@app.get("/ietf/enabled-groups")
async def get_ietf_enabled_groups(user: Optional[dict] = Depends(get_user_context)):
    """Return the currently enabled IETF areas/WGs from the ietf_datatracker_api DataSource node."""
    try:
        config = graph_service.get_datasource_config("ietf_datatracker_api")
        folders = config.get("folders", []) if config else []
        return {"enabled_groups": folders}
    except Exception as e:
        logger.error(f"Error fetching IETF enabled groups: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class IETFApplyGroupsRequest(BaseModel):
    groups: List[str]  # e.g. ["area:wit", "area:int", "wg:quic"]


@app.post("/admin/ietf/apply-groups")
@require_role(["admin", "superadmin"])
async def apply_ietf_groups(
    request: IETFApplyGroupsRequest,
    user: Optional[dict] = Depends(get_user_context)
):
    """
    Update the enabled IETF groups (areas/WGs).
    Creates/activates ietf_wg_* DataSource nodes for newly added WGs,
    deactivates nodes for removed ones, and updates ietf_datatracker_api.folders.
    """
    try:
        result = await graph_service.apply_ietf_groups(request.groups)
        return result
    except Exception as e:
        logger.error(f"Error applying IETF groups: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== Chat History Endpoints ==========

@app.get("/conversations", response_model=List[ConversationResponse])
@require_user_context
async def get_conversations(user: Optional[dict] = Depends(get_user_context), limit: int = 50):
    """
    Get all conversations for the authenticated user.
    Returns conversations ordered by most recent.
    """
    try:
        conversations = postgres.get_user_conversations(user["user_id"], limit=limit)
        return [ConversationResponse(**conv) for conv in conversations]
    except Exception as e:
        logger.error(f"Error fetching conversations for user {user['user_id']}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/conversations/{conversation_id}", response_model=ConversationDetailResponse)
@require_user_context
async def get_conversation_detail(conversation_id: int, user: Optional[dict] = Depends(get_user_context)):
    """
    Get a specific conversation with all its messages.
    Users can only access their own conversations.
    """
    try:
        conversation = postgres.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Verify conversation belongs to user
        if conversation["user_id"] != user["user_id"]:
            raise HTTPException(status_code=403, detail="Access denied")
        
        messages = postgres.get_conversation_messages(conversation_id)
        
        return ConversationDetailResponse(
            conversation=ConversationResponse(**conversation),
            messages=[MessageResponse(**msg) for msg in messages]
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/conversations/{conversation_id}")
@require_user_context
async def delete_conversation_endpoint(conversation_id: int, user: Optional[dict] = Depends(get_user_context)):
    """
    Delete a conversation and all its messages.
    Users can only delete their own conversations.
    """
    try:
        conversation = postgres.get_conversation(conversation_id)
        if not conversation:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        # Verify conversation belongs to user
        if conversation["user_id"] != user["user_id"]:
            raise HTTPException(status_code=403, detail="Access denied")
        
        rows = postgres.delete_conversation(conversation_id)
        if rows == 0:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        logger.info(f"User {user['user_id']} deleted conversation {conversation_id}")
        return {"message": "Conversation deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting conversation {conversation_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ========== Knowledge Graph Endpoints ==========

@app.get("/graph/topics")
async def get_topics(limit: int = 100, offset: int = 0, search: str = "", sort_by: str = "alphabetical"):
    """Get all topics from the knowledge graph with pagination, search, and sorting.
    
    Args:
        limit: Maximum number of results to return
        offset: Number of results to skip
        search: Optional search term to filter by topic name
        sort_by: Sort order - 'alphabetical' (default) or 'popularity' (by relationship count)
    """
    try:
        return graph_service.get_all_topics(limit, offset, search, sort_by)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/topics/hierarchy")
async def get_topics_hierarchy(search: str = ""):
    """Get all topics in hierarchical tree structure using ENCOMPASSES relationships.
    
    Returns:
        roots: List of root topic IDs (topics with no parents)
        nodes: Dictionary mapping topic_id to topic data with children/parents
        total_topics: Total count of topics
    
    Args:
        search: Optional search term to filter by topic name
    """
    try:
        return graph_service.get_topics_hierarchy(search)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/organisations")
async def get_organisations(limit: int = 100, offset: int = 0, sort_by: str = "alphabetical", search: str = ""):
    """Get all organisations from the knowledge graph with pagination, sorting, and search.
    
    Args:
        limit: Maximum number of results to return
        offset: Number of results to skip
        sort_by: Sort order - 'alphabetical' (default) or 'popularity' (by relationship count)
        search: Optional search term to filter by organization name
    """
    try:
        return graph_service.get_all_organisations(limit, offset, sort_by, search)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/people")
async def get_people(limit: int = 100, offset: int = 0, sort_by: str = "alphabetical", search: str = ""):
    """Get all people from the knowledge graph with pagination, sorting, and search.
    
    Args:
        limit: Maximum number of results to return
        offset: Number of results to skip
        sort_by: Sort order - 'alphabetical' (default) or 'popularity' (by relationship count)
        search: Optional search term to filter by person name
    """
    try:
        return graph_service.get_all_people(limit, offset, sort_by, search)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/statistics", response_model=GraphStatistics)
async def get_statistics():
    """Get statistics about the knowledge graph."""
    try:
        stats = graph_service.get_graph_statistics()
        return GraphStatistics(**stats)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== Document Upload Endpoint ==========

@app.post("/upload", response_model=UploadResponse)
async def upload_document(doc: DocumentUpload, user: Optional[dict] = Depends(get_user_context)):
    """
    Upload a document to the processing queue.
    Publishes document to RabbitMQ for processing by the digester.
    
    Can be called by authenticated users OR by internal services.
    If user context is present, the uploader is tracked for audit purposes.
    """
    try:
        # Log who initiated the upload
        if user:
            logger.info(f"Document upload by user {user['email']} (role: {user['role']}): {doc.title}")
            # Set uploaded_by if not already set
            if not doc.uploaded_by:
                doc.uploaded_by = user["email"]
        else:
            logger.info(f"Document upload by service/system: {doc.title}")
        
        # Cache binary content in Redis if provided
        if doc.binary_content:
            import redis
            redis_host = os.getenv("REDIS_HOST", "localhost")
            redis_port = int(os.getenv("REDIS_PORT", "6379"))
            
            try:
                redis_client = redis.Redis(
                    host=redis_host,
                    port=redis_port,
                    decode_responses=False,  # Handle binary data
                    socket_connect_timeout=5
                )
                
                # Store binary content with URL as key (24 hour TTL)
                cache_key = f"binary_content:{doc.url}"
                redis_client.setex(cache_key, 86400, doc.binary_content.encode('ascii'))
                logging.info(f"Cached binary content for {doc.url}")
            except Exception as e:
                logging.warning(f"Failed to cache binary content: {e}")
        
        # Get RabbitMQ connection details
        host = os.getenv("RABBITMQ_HOST", "localhost")
        port = int(os.getenv("RABBITMQ_PORT", "5672"))
        user = os.getenv("RABBITMQ_USER", "user")
        password = os.getenv("RABBITMQ_PASSWORD", "password")
        # Use configured queue; default aligns with .env RABBITMQ_QUEUE=scraped_content
        queue = os.getenv("RABBITMQ_QUEUE", "scraped_content")
        
        # Prepare message (exclude binary_content from queue message)
        message = {
            "title": doc.title,
            "url": doc.url,
            "category": doc.category,
            "content": doc.content,
            "publish_date": doc.publish_date,
            "datasource_id": doc.datasource_id,
            "scraped_at": datetime.now().timestamp(),
        }
        
        # Add optional fields
        if doc.uploaded_by:
            message["uploaded_by"] = doc.uploaded_by
        if doc.metadata:
            message["metadata"] = doc.metadata
        
        # Connect to RabbitMQ and publish
        credentials = pika.PlainCredentials(user, password)
        parameters = pika.ConnectionParameters(host=host, port=port, credentials=credentials)
        connection = pika.BlockingConnection(parameters)
        channel = connection.channel()
        
        # Declare queue (idempotent)
        channel.queue_declare(queue=queue, durable=True)
        
        # Publish message
        channel.basic_publish(
            exchange='',
            routing_key=queue,
            body=json.dumps(message),
            properties=pika.BasicProperties(
                delivery_mode=2,  # Make message persistent
            )
        )
        
        connection.close()
        
        return UploadResponse(
            status="success",
            message=f"Document '{doc.title}' queued for processing",
            url=doc.url
        )
        
    except Exception as e:
        logging.error(f"Failed to upload document: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to upload document: {str(e)}")


# ========== News Endpoint ==========

@app.post("/news", response_model=NewsResponse)
@require_user_context
async def get_news(req: NewsRequest, user: Optional[dict] = Depends(get_user_context)):
    """
    Generate curated news content for a user based on their preferences.
    Returns a personalized news digest with sections, highlights, and related documents.
    Requires authentication. Auto-creates user if first request.
    """
    try:
        logger.info(f"News generation for user {user['email']}, time_range={req.time_range}")
        
        # Check authorization - users can only get their own news unless admin
        if str(req.user_id) != user["user_id"] and user["role"] not in ["admin", "superadmin"]:
            raise HTTPException(status_code=403, detail="Access denied")
        
        # User must exist from login sync
        user_data = postgres.get_user_by_id(req.user_id)
        if not user_data:
            logger.error(f"User {req.user_id} not found - login sync failed")
            raise HTTPException(status_code=500, detail="User not synced - please log out and log back in")
        
        # Get user preferences
        preferences = postgres.get_user_preferences(req.user_id)
        
        # Generate news content
        news_service = get_news_service()
        news_content = news_service.generate_news(
            user_id=req.user_id,
            user_preferences=preferences,
            time_range=req.time_range,
            force_refresh=req.force_refresh
        )
        
        return NewsResponse(**news_content)
        
    except HTTPException:
        raise
    except Exception as e:
        logging.error(f"Failed to generate news: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate news: {str(e)}")
