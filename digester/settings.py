from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Literal


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""
    
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False
    )
    
    # RabbitMQ Configuration
    rabbitmq_host: str = "aurora-rabbitmq"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "user"
    rabbitmq_password: str = "password"
    rabbitmq_queue: str = "scraped_content"
    
    # Redis Configuration
    redis_host: str = "redis"
    redis_port: int = 6379
    
    # RabbitMQ Async Configuration
    rabbitmq_max_concurrent: int = 10  # Max concurrent message processing (async semaphore)
    rabbitmq_message_timeout: float = 1200.0  # Message timeout in seconds (20 minutes)
    rabbitmq_heartbeat: int = 60  # Heartbeat interval in seconds (60s recommended for async)
    
    @property
    def rabbitmq_prefetch_count(self) -> int:
        """Calculate prefetch count based on max_concurrent."""
        return max(1, self.rabbitmq_max_concurrent * 2)
    
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
    llm_rate_limit_retries: int = 3  # Max retries when hitting rate limits
    
    # LLM Rate Limiting (Proactive)
    llm_rate_limit_enabled: bool = True  # Enable proactive rate limiting
    llm_max_requests_per_minute: int = 60  # RPM quota (requests per minute)
    llm_max_tokens_per_minute: int = 10000  # TPM quota (tokens per minute)
    
    # Content Chunking
    max_chunk_size: int = 8000
    chunk_overlap: int = 500
    
    # Event Association
    event_disambiguation_confidence_threshold: float = 0.6  # Minimum confidence for LLM event disambiguation
    
    # Message Retry Configuration
    max_message_retries: int = 3  # Max times to requeue a message before sending to DLQ
    
    # Logging
    log_level: str = "INFO"


settings = Settings()
