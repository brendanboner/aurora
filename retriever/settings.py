from pydantic_settings import BaseSettings, SettingsConfigDict


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
    
    # Neo4j Configuration
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "password"
    neo4j_database: str = "neo4j"
    
    # PostgreSQL Configuration (for config_manager)
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "aurora"
    postgres_password: str = "aurora_password"
    postgres_db: str = "aurora"
    
    # Logging
    log_level: str = "INFO"
    
    # API Configuration
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    
    # Scheduler Configuration
    # Poll interval for checking cron schedules (in seconds)
    # Datasource-specific schedules are stored in the database
    scheduler_poll_interval: int = 60  # Check every 60 seconds
    
    # WFA Causeway Authentication
    wfa_causeway_username: str = ""
    wfa_causeway_password: str = ""


settings = Settings()
