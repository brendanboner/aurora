"""Runtime configuration for the Content Creator Service."""
from __future__ import annotations

from functools import lru_cache
from typing import Dict, List, Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Typed settings loaded from environment variables."""

    model_config = SettingsConfigDict(env_file_encoding="utf-8", extra="allow")

    app_name: str = "content_creator_service"
    environment: str = Field(default="local", description="Deployment environment label")
    
    # Logging
    log_level: str = Field(default="INFO", description="Logging level (DEBUG, INFO, WARNING, ERROR)")

    # Postgres
    pg_dsn: Optional[str] = Field(default=None, description="Optional full DSN for Postgres")
    postgres_host: str = "postgres"
    postgres_port: int = 5432
    postgres_user: str = "aurora"
    postgres_password: str = "aurora_password"
    postgres_db: str = "aurora"
    pg_pool_min: int = 1
    pg_pool_max: int = 10

    # Neo4j (read-only access for knowledge context)
    neo4j_uri: str = "bolt://neo4j:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = "neo4j_password"
    neo4j_database: str = "neo4j"

    # RabbitMQ (optional event triggers)
    rabbitmq_host: str = "rabbitmq"
    rabbitmq_port: int = 5672
    rabbitmq_user: str = "user"
    rabbitmq_password: str = "password"
    rabbitmq_queue: str = "scraped_content"

    # Azure OpenAI / LLM
    azure_openai_endpoint: Optional[str] = None
    azure_openai_api_key: Optional[str] = None
    azure_openai_api_version: str = "2024-10-21"
    azure_openai_deployment: Optional[str] = None
    llm_temperature: float = 0.8  # Changed from 0.1 to 0.8 for creative variation
    llm_max_tokens: int = 1200

    # Feed defaults
    default_feed_page_size: int = 20
    max_feed_page_size: int = 100

    # Scheduler
    scheduler_poll_interval_seconds: int = 60
    scheduler_digest_hour_utc: int = 12
    per_event_cooldown_seconds: int = 900

    # Content Quality & Diversity Settings
    diversity_similarity_threshold: float = Field(
        default=0.7,
        description="Jaccard similarity threshold for filtering similar articles (0.0-1.0). "
                    "Higher values = stricter filtering (more duplicates removed)",
        ge=0.0,
        le=1.0,
    )
    min_relevance_score_default: float = Field(
        default=0.2,
        description="Default minimum relevance score for article selection (0.0-1.0). "
                    "Can be overridden by agent discovery_tolerance",
        ge=0.0,
        le=1.0,
    )
    max_topics_per_article: int = Field(
        default=20,
        description="Maximum number of topics per article. Articles with more are filtered as generic aggregations",
        ge=1,
    )
    max_articles_per_domain: int = Field(
        default=2,
        description="Maximum number of articles from the same domain to include in a single post",
        ge=1,
    )
    temporal_window_days_default: int = Field(
        default=90,
        description="Default temporal window in days for article selection. "
                    "Can be overridden by agent cadence_window_days",
        ge=1,
        le=365,
    )

    def pg_connect_kwargs(self) -> Dict[str, str | int]:
        """Return keyword arguments for psycopg2 pool creation."""
        if self.pg_dsn:
            return {"dsn": self.pg_dsn}
        return {
            "host": self.postgres_host,
            "port": self.postgres_port,
            "user": self.postgres_user,
            "password": self.postgres_password,
            "dbname": self.postgres_db,
        }


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return cached Settings instance."""
    return Settings()
