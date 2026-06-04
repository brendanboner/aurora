"""Oracle Service settings loaded from environment variables."""

from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    # Neo4j Configuration
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "your_neo4j_password_here"
    neo4j_database: str = "neo4j"
    
    # PostgreSQL Configuration (for user preferences)
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "aurora"
    postgres_password: str = "aurora_password"
    postgres_db: str = "aurora"
    
    # Azure OpenAI Configuration
    azure_openai_api_key: str = ""
    azure_openai_endpoint: str = ""
    azure_openai_api_version: str = "2024-08-01-preview"
    azure_openai_deployment: str = ""  # GPT deployment name
    azure_openai_embedding_deployment: str = "text-embedding-3-small"
    
    # LLM Settings
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.1
    llm_rate_limit_retries: int = 3
    
    # Intent Classification
    intent_confidence_threshold: float = 0.7
    
    # Entity Resolution Settings
    entity_resolution_enabled: bool = True  # Resolve entities against graph
    entity_resolution_min_similarity: float = 0.75  # Min similarity for fuzzy match
    
    # Retrieval Settings
    default_max_documents: int = 20
    max_documents_limit: int = 100
    min_relevance_score: float = 0.5
    retrieval_pool_multiplier: int = 3  # Fetch 3x documents for better re-ranking
    
    # Vector Search Settings (Phase 2)
    vector_search_enabled: bool = True
    vector_min_score: float = 0.7  # Minimum cosine similarity score
    vector_top_k: int = 50  # Candidates to retrieve from vector search
    embedding_dimensions: int = 1536  # text-embedding-3-small dimensions
    
    # Hybrid Search Settings (Phase 2)
    hybrid_search_enabled: bool = True
    rrf_k: int = 60  # RRF constant (higher = more equal weighting)
    keyword_weight: float = 1.0  # Weight for keyword results in fusion
    vector_weight: float = 1.0  # Weight for vector results in fusion
    recency_boost_enabled: bool = True
    recency_boost_days: int = 30  # Boost documents from last N days
    recency_boost_factor: float = 1.2  # Multiplier for recent documents
    
    # Graph Search Settings (Phase 3)
    graph_search_enabled: bool = True
    graph_weight: float = 0.8  # Weight for graph results in fusion (slightly lower than keyword/vector)
    
    # Response Generation
    max_answer_tokens: int = 1024
    
    # Timeouts (seconds)
    llm_timeout: float = 30.0
    llm_enhance_timeout: float = 60.0  # Longer timeout for enhanced answers (more context)
    neo4j_timeout: float = 10.0
    
    # Logging
    log_level: str = "INFO"
    
    # OpenTelemetry
    otel_enabled: bool = True
    otel_endpoint: str = "http://otel-collector:4317"
    otel_sample_rate: float = 1.0
    
    # Phase 4: Caching (Redis)
    cache_enabled: bool = True
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_password: str = ""
    redis_db: int = 0
    cache_query_ttl: int = 300  # 5 minutes for full query responses
    cache_embedding_ttl: int = 3600  # 1 hour for embeddings
    cache_graph_ttl: int = 900  # 15 minutes for graph context
    cache_document_ttl: int = 1800  # 30 minutes for documents
    
    # Phase 4: Parallel Retrieval
    parallel_retrieval_enabled: bool = True
    retrieval_timeout: float = 10.0  # Timeout for each retriever
    
    # Phase 4: Confidence Scoring
    confidence_scoring_enabled: bool = True
    confidence_low_threshold: float = 0.4
    confidence_high_threshold: float = 0.75
    
    # Phase 4: Query Suggestions
    suggestions_enabled: bool = True
    suggestions_min_results: int = 3  # Show suggestions if fewer results
    suggestions_min_relevance: float = 0.5  # Show suggestions if lower relevance
    suggestions_max_count: int = 3  # Maximum suggestions to return
    
    # Phase 4: Ranking Explainability
    explainability_enabled: bool = True
    
    # Phase 5: Enhanced Answers (Full Content)
    enhance_enabled: bool = True
    enhance_chunk_size: int = 500  # Target tokens per chunk
    enhance_chunk_overlap: int = 50  # Tokens of overlap between chunks
    enhance_max_chunks: int = 15  # Maximum chunks to use for answer
    enhance_max_context_tokens: int = 7500  # Maximum tokens for LLM context
    enhance_min_relevance_score: float = 0.5  # Minimum chunk relevance
    enhance_max_quotes: int = 5  # Maximum direct quotes to extract
    content_cache_ttl: int = 3600  # 1 hour cache for fetched content
    retriever_service_url: str = "http://retriever:8000"  # Retriever service URL
    
    # Phase 6: Analytics & Tracking
    analytics_enabled: bool = True  # Enable analytics metrics collection
    analytics_logging_enabled: bool = True  # Enable structured logging for Loki
    feedback_enabled: bool = True  # Enable user feedback endpoint
    metrics_prefix: str = "oracle"  # Prefix for Prometheus metrics
    
    # Phase 6: Query History Storage
    query_history_enabled: bool = True  # Store raw request/response data
    query_history_retention_days: int = 30  # How long to keep history
    query_history_max_response_size: int = 50000  # Max chars to store per response
    
    # Pipeline selection (was A/B test, now a simple admin switch).
    # "auto"     = fast pipeline with downstream baseline fallback (default)
    # "baseline" = force baseline for every request — used for clean-signal
    #              evaluation runs and as a safety lever if fast misbehaves
    oracle_pipeline_mode: str = "auto"

    # Master fast-pipeline kill switch — kept for backward compatibility but
    # the same effect can be achieved by setting oracle_pipeline_mode=baseline.
    # When False, every request uses baseline regardless of the mode setting.
    fast_pipeline_enabled: bool = True

    # DEPRECATED — A/B-test rollout and shadow-mode knobs are no longer used
    # (the SHA-bucketing produced a third "unspecified" pipeline bucket in
    # oracle_query_history that confused eval metrics). Left in place so old
    # .env files don't fail to load; the values are ignored.
    fast_pipeline_rollout_percentage: int = 100
    fast_pipeline_shadow_mode: bool = False
    
    # Fast Pipeline: Routing
    fast_router_confidence_threshold: float = 0.6  # Min confidence to use local router (else LLM fallback)
    fast_router_llm_fallback_enabled: bool = True  # Enable LLM router as fallback
    fast_router_max_entities: int = 10  # Max entities to resolve per query
    
    # Fast Pipeline: Cypher Templates
    fast_template_max_nodes: int = 100  # Max nodes returned per template query
    fast_template_timeout: float = 5.0  # Timeout for template execution (seconds)
    fast_template_version: str = "1.0.15"  # hard future-date filter + Postgres-timestamp coercion in RECENT_CONTENT + DATASOURCE_LATEST
    
    # Fast Pipeline: Rollups (PostgreSQL)
    fast_rollup_enabled: bool = True  # Enable rollup generation and retrieval
    fast_rollup_generation_enabled: bool = True  # Enable nightly rollup generation job
    fast_rollup_generation_cron: str = "0 2 * * *"  # 2 AM daily; scheduler currently uses only the hour component
    fast_rollup_daily_lookback: int = 14  # Generate daily rollups for last N days
    fast_rollup_weekly_lookback: int = 4  # Generate weekly rollups for last N weeks
    fast_rollup_monthly_lookback: int = 3  # Generate monthly rollups for last N months
    fast_rollup_prewarm_on_ingest: bool = True  # Invalidate/rebuild rollups on document ingest
    
    # Fast Pipeline: Caching
    fast_cache_plan_ttl: int = 86400  # 24 hours - route plan cache
    fast_cache_result_ttl: int = 3600  # 1 hour - retrieval result cache
    fast_cache_answer_ttl: int = 3600  # 1 hour - final answer cache
    fast_cache_prewarm_enabled: bool = True  # Enable cache prewarming
    fast_cache_prewarm_mode: str = "autonomous"  # "provided" or "autonomous"
    fast_cache_prewarm_patterns_file: str = "/app/config/prewarm_patterns.json"
    
    # Fast Pipeline: Deep Dive
    fast_deep_dive_enabled: bool = True  # Enable deep dive retrieval
    fast_deep_dive_trigger_threshold: float = 0.7  # Trigger deep dive if confidence < threshold
    fast_deep_dive_max_snippets: int = 10  # Max document snippets to retrieve
    fast_deep_dive_token_budget: int = 7500  # Max tokens for deep dive context
    
    # Fast Pipeline: Fallback & Safety
    fast_fallback_to_baseline: bool = True  # Fall back to baseline on error
    fast_confidence_threshold: float = 0.6  # Min confidence to return fast result
    fast_operation_timeout: float = 30.0  # Max total time for fast pipeline (seconds)
    
    # Rate Limiting: YouTube Transcript API
    youtube_transcript_max_requests: int = 60  # Max transcript requests per time window
    youtube_transcript_time_window: int = 3600  # Time window in seconds (1 hour)
    
    # Rate Limiting: RabbitMQ Publishing
    rabbitmq_max_requests: int = 20  # Max RabbitMQ publish operations per time window
    rabbitmq_time_window: int = 10  # Time window in seconds (10 seconds)
    
    # YouTube Proxy Configuration (optional)
    # Use a proxy to bypass YouTube IP blocking for cloud providers (AWS, GCP, Azure)
    # Format: http://username:password@proxy.example.com:3128 or http://proxy.example.com:3128
    # Leave empty to disable proxy usage
    youtube_proxy_http: str = ""  # HTTP proxy URL
    youtube_proxy_https: str = ""  # HTTPS proxy URL
    
    @property
    def postgres_dsn(self) -> str:
        """Generate PostgreSQL connection string."""
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"


settings = Settings()
