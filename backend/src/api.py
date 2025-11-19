from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from src.services.query_engine import run_query
from src.services import postgres
from src.services import graph_service

app = FastAPI(title="Aurora Backend API")

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
    user_id: int
    question: str


class Document(BaseModel):
    title: str | None = None
    url: str | None = None
    publish_date: str | None = None
    summary: str | None = None
    topics: List[str] = []
    organisations: List[str] = []


class QueryResponse(BaseModel):
    answer: str
    filters: Dict[str, Any]
    documents: List[Document]


class UserCreate(BaseModel):
    email: str
    display_name: str


class UserResponse(BaseModel):
    id: int
    email: str
    display_name: str | None
    created_at: str
    updated_at: str


class UserPreferences(BaseModel):
    topics: List[str] = []
    organisations: List[str] = []
    people: List[str] = []
    sources: List[str] = []
    notify_email: bool = True
    notify_digest: bool = True


class GraphStatistics(BaseModel):
    resources: int
    topics: int
    organisations: int
    people: int
    datasources: int


# ========== Health Check ==========

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "aurora-backend"}


# ========== Query Endpoint ==========

@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    """Process a natural language query."""
    result = run_query(req.user_id, req.question)
    return QueryResponse(
        answer=result["answer"],
        filters=result["filters"],
        documents=[Document(**d) for d in result["documents"]],
    )


# ========== User Management Endpoints ==========

@app.post("/users", response_model=UserResponse)
async def create_user(user: UserCreate):
    """Create a new user."""
    try:
        # Check if user already exists
        existing = postgres.get_user_by_email(user.email)
        if existing:
            raise HTTPException(status_code=400, detail="User with this email already exists")
        
        result = postgres.create_user(user.email, user.display_name)
        return UserResponse(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/users", response_model=List[UserResponse])
async def get_users():
    """Get all users."""
    try:
        users = postgres.get_all_users()
        return [UserResponse(**u) for u in users]
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/users/{user_id}", response_model=UserResponse)
async def get_user(user_id: int):
    """Get a specific user."""
    try:
        user = postgres.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return UserResponse(**user)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/users/email/{email}", response_model=UserResponse)
async def get_user_by_email(email: str):
    """Get a user by email."""
    try:
        user = postgres.get_user_by_email(email)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        return UserResponse(**user)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/users/{user_id}")
async def delete_user(user_id: int):
    """Delete a user."""
    try:
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
async def get_preferences(user_id: int):
    """Get user preferences."""
    try:
        # Verify user exists
        user = postgres.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        prefs = postgres.get_user_preferences(user_id)
        return UserPreferences(**prefs)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.put("/users/{user_id}/preferences", response_model=UserPreferences)
async def update_preferences(user_id: int, preferences: UserPreferences):
    """Update user preferences."""
    try:
        # Verify user exists
        user = postgres.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        result = postgres.upsert_user_preferences(
            user_id=user_id,
            topics=preferences.topics,
            organisations=preferences.organisations,
            people=preferences.people,
            sources=preferences.sources,
            notify_email=preferences.notify_email,
            notify_digest=preferences.notify_digest
        )
        return UserPreferences(**result)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ========== Knowledge Graph Endpoints ==========

@app.get("/graph/topics")
async def get_topics(limit: int = 1000):
    """Get all topics from the knowledge graph."""
    try:
        topics = graph_service.get_all_topics(limit)
        return {"topics": topics, "count": len(topics)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/organisations")
async def get_organisations(limit: int = 1000):
    """Get all organisations from the knowledge graph."""
    try:
        orgs = graph_service.get_all_organisations(limit)
        return {"organisations": orgs, "count": len(orgs)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/graph/people")
async def get_people(limit: int = 1000):
    """Get all people from the knowledge graph."""
    try:
        people = graph_service.get_all_people(limit)
        return {"people": people, "count": len(people)}
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
