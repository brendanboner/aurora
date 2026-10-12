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
    
    # PostgreSQL Configuration (for user data, preferences, event attendance)
    # Note: Datasource configuration has been migrated to Neo4j
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
    # Datasource-specific schedules are stored in Neo4j DataSource nodes
    scheduler_poll_interval: int = 60  # Check every 60 seconds
    
    # WFA Causeway Authentication
    wfa_causeway_username: str = ""
    wfa_causeway_password: str = ""
    
    # WBA Authentication (public wballiance.com — WordPress login)
    wba_username: str = ""
    wba_password: str = ""

    # WBA Extranet Authentication (extranet.wballiance.com — Higher Logic portal)
    wba_extranet_username: str = ""
    wba_extranet_password: str = ""
    wba_extranet_base_url: str = "https://extranet.wballiance.com"
    # Cookie-based auth (when login form has reCAPTCHA):
    # Paste cookie values from browser DevTools (Application → Cookies)
    # after logging in to https://extranet.wballiance.com manually.
    # HLLogin is the persistent "remember me" token (expires after ~7 days).
    # The server auto-generates a new session (HLTC / ASP.NET_SessionId)
    # when it sees a valid HLLogin cookie, so only HLLogin is needed.
    wba_extranet_hllogin: str = ""   # Primary: persistent login token (HLLogin cookie)
    wba_extranet_hltc: str = ""      # Legacy: session auth token (HLTC cookie, if set)
    wba_extranet_session_id: str = ""  # Optional: ASP.NET_SessionId cookie
    # IAM Key-based auth (preferred for automated access — no reCAPTCHA):
    # Obtain the HLIAMKey from the WBA admin portal under:
    #   Settings → Integrations → API Settings → IAM Key
    # Used with HLIAMKey + HLPassword + HLUserLogin headers for the
    # /higherlogic/external/api/v2.0/ REST API endpoints.
    wba_extranet_iam_key: str = ""
    # Set to True (or WBA_EXTRANET_SKIP_BODY_DOWNLOAD=true) to skip document
    # body downloads. Useful for local dev where you just want to prove the
    # metadata pipeline works; production should leave this False.
    wba_extranet_skip_body_download: bool = False

    # Event Sanitization Configuration
    sanitize_events: bool = True  # Enable/disable sensitive info sanitization
    sanitization_replacement_text: str = "[Meeting access details removed for privacy. Please view the source link for access details.]"
    
    # AWS S3 Configuration for document uploads
    aws_region: str = "us-east-1"
    s3_document_bucket: str = "aurora-document-uploads"
    max_upload_size_mb: int = 50
    
    # Application Environment
    # 'dev' = development mode (scheduled scrapes disabled, manual only)
    # 'prod' = production mode (scheduled scrapes enabled)
    app_env: str = "prod"


settings = Settings()
