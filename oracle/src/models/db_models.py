"""PostgreSQL database models for fast pipeline rollups."""

from sqlalchemy import (
    Column, String, Integer, Float, DateTime, Text, JSON, Boolean,
    Index, UniqueConstraint, create_engine, text
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.dialects.postgresql import UUID, ARRAY
from datetime import datetime
import uuid

Base = declarative_base()


class Rollup(Base):
    """
    Pre-computed rollup summaries for common query patterns.
    
    Stores daily and weekly summaries for workgroups to enable
    fast retrieval without full pipeline execution.
    """
    __tablename__ = "rollups"
    
    # Primary key
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Rollup identification
    rollup_type = Column(String(20), nullable=False)  # 'day' or 'week'
    start_date = Column(DateTime, nullable=False)
    end_date = Column(DateTime, nullable=False)
    workgroup_id = Column(String(255), nullable=True)  # Null for global rollups
    workgroup_name = Column(String(255), nullable=True)
    
    # Content
    summary = Column(Text, nullable=False)  # Brief summary
    key_events = Column(ARRAY(String), default=[])  # Event IDs
    key_decisions = Column(JSON, default=[])  # Decision summaries
    top_topics = Column(ARRAY(String), default=[])  # Topic names
    links = Column(JSON, default=[])  # URLs to source documents
    
    # Metadata
    event_count = Column(Integer, default=0)
    document_count = Column(Integer, default=0)
    
    # Generation metadata
    generated_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    generation_method = Column(String(50), default="autonomous")  # 'autonomous' or 'on_demand'
    template_version = Column(String(20), default="1.0.0")
    
    # Cache control
    expires_at = Column(DateTime, nullable=True)  # Optional explicit expiration
    invalidated = Column(Boolean, default=False)  # Mark for regeneration
    
    # Indexes for fast lookup
    __table_args__ = (
        Index('idx_rollup_lookup', 'rollup_type', 'start_date', 'workgroup_id'),
        Index('idx_rollup_workgroup', 'workgroup_id', 'rollup_type'),
        Index('idx_rollup_date_range', 'start_date', 'end_date'),
        Index('idx_rollup_generated', 'generated_at'),
        UniqueConstraint('rollup_type', 'start_date', 'workgroup_id', name='uq_rollup_period_workgroup'),
    )


class CacheEntry(Base):
    """
    Fast pipeline cache entries.
    
    Stores plan, result, and answer caches with TTL and versioning.
    """
    __tablename__ = "fast_cache"
    
    # Primary key
    cache_key = Column(String(64), primary_key=True)  # SHA256 hash
    cache_type = Column(String(20), nullable=False)  # 'plan', 'result', or 'answer'
    
    # Cache content
    content = Column(JSON, nullable=False)
    
    # Metadata
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    hits = Column(Integer, default=0)
    last_hit_at = Column(DateTime, nullable=True)
    
    # Versioning
    template_version = Column(String(20), default="1.0.0")
    
    # Indexes
    __table_args__ = (
        Index('idx_cache_type_expires', 'cache_type', 'expires_at'),
        Index('idx_cache_expires', 'expires_at'),
    )


class BenchmarkQuery(Base):
    """
    Benchmark queries for A/B testing and prewarming.
    
    Admin-provided or autonomously identified query patterns
    for performance evaluation and cache prewarming.
    """
    __tablename__ = "benchmark_queries"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Query definition
    query_text = Column(Text, nullable=False)
    query_pattern = Column(String(255), nullable=True)  # Pattern name
    category = Column(String(100), nullable=True)  # 'recap', 'decision', 'topic', etc.
    
    # Expected results (for quality evaluation)
    expected_intent = Column(String(50), nullable=True)
    expected_entities = Column(JSON, default={})
    
    # Metadata
    source = Column(String(50), default="manual")  # 'manual' or 'autonomous'
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    frequency_score = Column(Float, default=0.0)  # For autonomous queries
    
    # Flags
    enabled = Column(Boolean, default=True)
    prewarm = Column(Boolean, default=True)  # Include in prewarming
    
    __table_args__ = (
        Index('idx_benchmark_enabled', 'enabled'),
        Index('idx_benchmark_prewarm', 'prewarm'),
        Index('idx_benchmark_frequency', 'frequency_score'),
    )


class BenchmarkResult(Base):
    """
    Results from benchmark query execution.
    
    Stores comparison data between baseline and fast pipelines
    for A/B testing evaluation.
    """
    __tablename__ = "benchmark_results"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    
    # Reference to benchmark query
    query_id = Column(UUID(as_uuid=True), nullable=False)
    query_text = Column(Text, nullable=False)
    
    # Execution metadata
    pipeline = Column(String(20), nullable=False)  # 'baseline' or 'fast'
    executed_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    
    # Performance metrics
    total_latency_ms = Column(Integer, nullable=False)
    routing_latency_ms = Column(Integer, nullable=True)
    db_latency_ms = Column(Integer, nullable=True)
    llm_latency_ms = Column(Integer, nullable=True)
    
    # Cache metrics
    cache_hit = Column(Boolean, default=False)
    cache_type = Column(String(20), nullable=True)  # Which cache was hit
    
    # Quality metrics
    document_count = Column(Integer, default=0)
    citation_count = Column(Integer, default=0)
    answer_length = Column(Integer, default=0)
    confidence_score = Column(Float, nullable=True)
    
    # Results
    answer_text = Column(Text, nullable=True)
    documents = Column(JSON, default=[])
    
    # Comparison
    baseline_result_id = Column(UUID(as_uuid=True), nullable=True)  # Link to baseline run
    
    __table_args__ = (
        Index('idx_benchmark_result_query', 'query_id'),
        Index('idx_benchmark_result_pipeline', 'pipeline'),
        Index('idx_benchmark_result_executed', 'executed_at'),
    )


def init_db(database_url: str):
    """
    Initialize database schema.
    
    Creates all tables if they don't exist (idempotent).
    
    Args:
        database_url: PostgreSQL connection string
        
    Returns:
        SQLAlchemy engine
    """
    import logging
    logger = logging.getLogger(__name__)
    
    try:
        engine = create_engine(database_url, echo=False)
        
        # Test connection
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        
        # Create tables (CREATE TABLE IF NOT EXISTS)
        Base.metadata.create_all(engine)
        
        logger.info("Database schema initialized successfully")
        return engine
        
    except Exception as e:
        logger.error(f"Failed to initialize database schema: {e}")
        raise


def get_session(database_url: str):
    """
    Get a database session.
    
    Args:
        database_url: PostgreSQL connection string
        
    Returns:
        SQLAlchemy session
    """
    engine = create_engine(database_url)
    Session = sessionmaker(bind=engine)
    return Session()
