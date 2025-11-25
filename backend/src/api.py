from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Any, Dict, List, Optional, cast
from datetime import datetime
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)

from src.services.query_engine import run_query
from src.services import postgres
from src.services import graph_service
from src.routes import admin

app = FastAPI(title="Aurora Backend API")

# Include admin routes
app.include_router(admin.router)

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
    created_at: datetime
    updated_at: datetime


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


# ========== Health Check ==========

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "aurora-backend"}


# ========== Query Endpoint ==========

@app.post("/query", response_model=QueryResponse)
async def query(req: QueryRequest) -> QueryResponse:
    """Process a natural language query."""
    try:
        result = run_query(req.user_id, req.question)
        return QueryResponse(
            answer=result["answer"],
            filters=result["filters"],
            documents=[Document(**d) for d in result["documents"]],
        )
    except HTTPException:
        raise
    except Exception as e:
        # Provide a structured error while preserving CORS headers.
        raise HTTPException(status_code=500, detail=f"Query failed: {e}")


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
        prefs_dict = cast(Dict[str, Any], prefs)
        return UserPreferences(**prefs_dict)
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
        result_dict = cast(Dict[str, Any], result)
        return UserPreferences(**result_dict)
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


# ========== Document Upload Endpoint ==========

@app.post("/upload", response_model=UploadResponse)
async def upload_document(doc: DocumentUpload):
    """
    Upload a document to the processing queue.
    Publishes document to RabbitMQ for processing by the digester.
    """
    import pika
    import os
    import json
    from datetime import datetime
    
    try:
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
