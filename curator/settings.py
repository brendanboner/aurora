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
    
    # Scheduling Configuration (for future use)
    curation_interval_hours: int = 24
    
    # Logging
    log_level: str = "INFO"


settings = Settings()
