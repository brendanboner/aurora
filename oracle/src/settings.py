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
    
    # Production Neo4j Configuration (read-only access via SSH tunnel)
    # When use_prod_data=True, Oracle connects to prod Neo4j for queries
    use_prod_data: bool = False
    oracle_prod_neo4j_uri: str = "bolt://localhost:7688"
    oracle_prod_neo4j_user: str = "neo4j"
    oracle_prod_neo4j_password: str = ""
    oracle_prod_neo4j_database: str = "neo4j"
    
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
    
    @property
    def postgres_dsn(self) -> str:
        """Generate PostgreSQL connection string."""
        return f"postgresql://{self.postgres_user}:{self.postgres_password}@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
    
    @property
    def effective_neo4j_uri(self) -> str:
        """Get the Neo4j URI to use (prod or dev based on use_prod_data)."""
        if self.use_prod_data:
            return self.oracle_prod_neo4j_uri
        return self.neo4j_uri
    
    @property
    def effective_neo4j_user(self) -> str:
        """Get the Neo4j user to use (prod or dev based on use_prod_data)."""
        if self.use_prod_data:
            return self.oracle_prod_neo4j_user
        return self.neo4j_user
    
    @property
    def effective_neo4j_password(self) -> str:
        """Get the Neo4j password to use (prod or dev based on use_prod_data)."""
        if self.use_prod_data:
            return self.oracle_prod_neo4j_password
        return self.neo4j_password
    
    @property
    def effective_neo4j_database(self) -> str:
        """Get the Neo4j database to use (prod or dev based on use_prod_data)."""
        if self.use_prod_data:
            return self.oracle_prod_neo4j_database
        return self.neo4j_database


settings = Settings()
