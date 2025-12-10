from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    # Neo4j Configuration
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"
    
    # Azure OpenAI Configuration
    azure_openai_api_key: str
    azure_openai_endpoint: str
    azure_openai_api_version: str = "2024-08-01-preview"
    azure_openai_deployment: str  # Your deployment name
    llm_max_tokens: int = 4096
    llm_temperature: float = 0.1
    
    # RabbitMQ Configuration (for queue monitoring)
    rabbitmq_host: str = "rabbitmq"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "user"
    rabbitmq_password: str = "password"
    rabbitmq_queue: str = "scraped_content"
    
    # Redis Configuration (for monitoring digester state)
    redis_host: str = "redis"
    redis_port: int = 6379
    
    # Clustering Configuration
    cluster_min_size: int = 3
    cluster_max_size: int = 10
    cluster_distance_threshold: float = 0.5
    cluster_overlap_neighbors: int = 3  # Number of nearest external topics to add to each cluster (0 = no overlap)
    
    # Hierarchy Analysis Configuration
    max_topics_per_llm_call: int = 20
    hierarchy_confidence_threshold: float = 0.7
    enable_cross_cluster_analysis: bool = True  # Analyze cluster representatives for cross-cluster relationships
    
    # Wait Configuration
    wait_for_digester: bool = True  # Whether to wait for digester to complete
    queue_empty_wait_seconds: int = 30  # How long queue must be empty before proceeding
    max_wait_minutes: int = 60  # Maximum time to wait for digester
    
    # Scheduler Configuration
    # Topic organization: threshold-based (recommended) or cron-based (fallback)
    # When threshold is enabled, organization triggers when X new topics are created
    # When threshold is disabled, falls back to cron schedule
    topic_threshold_enabled: bool = True  # Use threshold-based triggering (recommended)
    topic_threshold_count: int = 50  # Number of new topics to trigger organization
    topic_threshold_check_interval_seconds: int = 60  # How often to check for new topics
    
    # Cron schedule (only used when topic_threshold_enabled=False)
    topic_organization_cron: str = "0 6 * * *"  # Cron expression: minute hour day month day_of_week
    
    # Event reconciliation checks for pending scrape completions on an interval
    # Only does work when there are scrape:complete:* signals in Redis
    event_reconciliation_check_interval_seconds: int = 60
    event_reconciliation_enabled: bool = True
    
    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000  # Internal container port (external port configured in docker-compose)
    
    # Logging
    log_level: str = "INFO"


settings = Settings()
