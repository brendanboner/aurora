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
    
    # RabbitMQ Threading Configuration
    rabbitmq_max_workers: int = 4  # Number of worker threads (0 = single-threaded)
    rabbitmq_heartbeat: int = 180  # Heartbeat interval in seconds (3 minutes)
    
    @property
    def rabbitmq_prefetch_count(self) -> int:
        """Calculate prefetch count based on max_workers."""
        return max(1, self.rabbitmq_max_workers * 2)
    
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
