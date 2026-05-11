"""Node and Relationship models for Neo4j knowledge graph."""

from typing import Dict, Any, List, Optional, ClassVar
from datetime import datetime
import logging
import os
from pydantic import BaseModel, Field, ConfigDict, model_validator
import re
import hashlib

# Configure module logger - will inherit from parent if configured, otherwise use basic config
logger = logging.getLogger(__name__)

# Only set up basic config if no handlers are configured (i.e., if this is imported standalone)
if not logging.getLogger().handlers:
    # Configure only the neo4j_client logger hierarchy, not the root
    neo4j_client_logger = logging.getLogger('neo4j_client')
    neo4j_client_logger.setLevel(logging.INFO)
    handler = logging.StreamHandler()
    handler.setFormatter(logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    ))
    neo4j_client_logger.addHandler(handler)
    
    # Suppress verbose neo4j driver logs
    logging.getLogger('neo4j').setLevel(logging.WARNING)

# Embedding model configuration
EMBEDDING_MODEL = os.getenv('EMBEDDING_MODEL', 'text-embedding-3-small')  # Azure OpenAI embedding model

# Lazy initialization for OpenAI client
_openai_client = None

def get_embedding_model():
    """
    Get the Azure OpenAI client for embeddings.
    
    Environment variables:
    - EMBEDDING_MODEL: Model name (default: 'text-embedding-3-small')
    - AZURE_OPENAI_API_KEY: Required
    - AZURE_OPENAI_ENDPOINT: Required
    - AZURE_OPENAI_API_VERSION: Optional (default: '2024-08-01-preview')
    """
    global _openai_client
    
    if _openai_client is None:
        try:
            from openai import AzureOpenAI
            
            api_key = os.getenv('AZURE_OPENAI_API_KEY')
            endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
            api_version = os.getenv('AZURE_OPENAI_API_VERSION', '2024-08-01-preview')
            
            if not api_key:
                raise ValueError("AZURE_OPENAI_API_KEY environment variable is required for Azure OpenAI embeddings")
            if not endpoint:
                raise ValueError("AZURE_OPENAI_ENDPOINT environment variable is required for Azure OpenAI embeddings")
            
            _openai_client = AzureOpenAI(
                api_key=api_key,
                api_version=api_version,
                azure_endpoint=endpoint
            )
            logger.info(f"Initialized Azure OpenAI client for embeddings with model: {EMBEDDING_MODEL}")
        except ImportError:
            raise ImportError("openai package is required for Azure OpenAI embeddings. Install with: pip install openai")
    return _openai_client


class Node(BaseModel):
    """Base class for graph nodes."""

    node_label: str # e.g. "Topic"
    id_field: str # e.g. "topic_id"

    embedding: List[float] = Field( 
        default_factory=list,
        description="Embedding vector for the topic"
    )

    # Optional deduplication metadata fields (set during deduplication process)
    deduplication_best_match_id: Optional[str] = Field(
        default=None,
        description="ID of the closest matching node found during deduplication"
    )
    deduplication_best_match_name: Optional[str] = Field(
        default=None,
        description="Name of the closest matching node found during deduplication"
    )
    deduplication_score: Optional[float] = Field(
        default=None,
        description="Similarity score with the best match (0.0-1.0)"
    )

    TRUNCATE: ClassVar[Dict[str, int]] = {}
    NORMALIZE: ClassVar[Dict[str, str]] = {}  # field_name -> case


    # Build Node embedding
    @model_validator(mode='after')
    def set_embedding(self):
        self.embedding = self.build_embedding()
        return self

    @model_validator(mode="before")
    @classmethod
    def _normalize_strings(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize string fields based on NORMALIZE configuration."""
        if not isinstance(data, dict):
            return data
        
        normalize_config = getattr(cls, "NORMALIZE", {})
        if not normalize_config:
            return data
            
        for field_name, case in normalize_config.items():
            value = data.get(field_name)
            if value is None:
                continue
            
            # Handle lists
            if isinstance(value, list):
                normalized_list = []
                for item in value:
                    if item is not None:
                        normalized_list.append(normalize_string(item, case))
                data[field_name] = normalized_list
            else:
                # Handle single strings
                data[field_name] = normalize_string(value, case)
        
        return data
    
    @model_validator(mode="before")
    @classmethod
    def _truncate_strings(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Truncate string fields based on TRUNCATE configuration."""
        if not isinstance(data, dict):
            return data
        
        truncate_config = getattr(cls, "TRUNCATE", {})
        if not truncate_config:
            return data
            
        for field_name, max_len in truncate_config.items():
            value = data.get(field_name)
            if isinstance(value, str) and len(value) > max_len:
                data[field_name] = value[:max_len]
                logger.warning(f"Truncated field '{field_name}' to max length {max_len}")

        return data
    
    model_config = ConfigDict(
        # Allow extra fields for flexibility (like **kwargs)
        extra="ignore",
        # Use arbitrary types (for datetime, etc.)
        arbitrary_types_allowed=True
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert node to dictionary for Neo4j.
        Excludes None values and converts datetime to ISO format.
        """
        data = self.model_dump(exclude=["node_label", "id_field"], exclude_none=True)
        # Convert datetime fields to ISO string for Neo4j
        datetime_fields = [
            'scraped_at', 'publish_date', 'content_changed_at', 
            'start_date', 'end_date', 'scrape_started_at', 'scrape_completed_at', 
            'digest_completed_at'
        ]
        for field in datetime_fields:
            if field in data and data[field] is not None and isinstance(data[field], datetime):
                data[field] = data[field].isoformat()
        return data

    def get_embedding_fields(self) -> List[str]:
        """
        Returns a list of field names to include in the embedding text.
        Subclasses should override to specify relevant fields.
        """
        # By default, include all string fields
        return [name for name, field in self.__fields__.items()
                if field.annotation == str]

    def get_embedding_text(self) -> str:
        """
        Returns a string suitable for generating embeddings, combining relevant fields.
        """
        parts = []
        for field_name in self.get_embedding_fields():
            value = getattr(self, field_name, None)
            if value:
                if isinstance(value, list):
                    parts.extend([str(v) for v in value if v])
                else:
                    parts.append(str(value))
        return " | ".join(parts)

    def build_embedding(self) -> List[float]:
        """
        Generate embedding vector for the node using Azure OpenAI.
        """
        embedding_text = self.get_embedding_text()
        logger.debug(f"Generating embedding for text: {embedding_text}")
        
        # Use OpenAI embeddings
        client = get_embedding_model()
        try:
            response = client.embeddings.create(
                input=embedding_text,
                model=EMBEDDING_MODEL,
            )
            embedding_vector = response.data[0].embedding
            logger.debug(f"Generated OpenAI embedding with {len(embedding_vector)} dimensions")
            return embedding_vector
        except Exception as e:
            logger.error(f"Failed to generate OpenAI embedding: {e}")
            raise


class Relationship(BaseModel):
    """Base class for graph relationships."""
    
    model_config = ConfigDict(
        extra="ignore",
        arbitrary_types_allowed=True
    )
    
    # Class-level metadata - override these in subclasses
    # These should be set in each subclass to define relationship structure
    source_node_label: str  # e.g., "Resource"
    source_id_field: str    # e.g., "url_hash"
    target_node_label: str  # e.g., "Topic"
    target_id_field: str    # e.g., "topic_id"
    relationship_label: str  # e.g., "RELATES_TO"
    
    # Instance-level data - required on instantiation
    source_id: str # e.g. the actual source node's id value
    target_id: str # e.g. the actual target node's id value

    TRUNCATE: ClassVar[Dict[str, int]] = {}
    NORMALIZE: ClassVar[Dict[str, str]] = {}  # field_name -> case


    def to_dict(self) -> Dict[str, Any]:
        """
        Convert relationship to dictionary for Neo4j.
        Excludes None values and metadata fields.
        Only includes instance data (source_id, target_id, and relationship-specific fields).
        """
        data = self.model_dump(exclude={"source_id", "target_id", "source_node_label", "source_id_field", "target_node_label", "target_id_field", "relationship_label"}, exclude_none=True)
        return data

    @model_validator(mode="before")
    @classmethod
    def _normalize_strings(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Normalize string fields based on NORMALIZE configuration."""
        if not isinstance(data, dict):
            return data
        
        normalize_config = getattr(cls, "NORMALIZE", {})
        if not normalize_config:
            return data
            
        for field_name, case in normalize_config.items():
            value = data.get(field_name)
            if value is None:
                continue
            
            # Handle lists
            if isinstance(value, list):
                normalized_list = []
                for item in value:
                    if item is not None:
                        normalized_list.append(normalize_string(item, case))
                data[field_name] = normalized_list
            else:
                # Handle single strings
                data[field_name] = normalize_string(value, case)
        
        return data
    
    @model_validator(mode="before")
    @classmethod
    def _truncate_strings(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        """Truncate string fields based on TRUNCATE configuration."""
        if not isinstance(data, dict):
            return data
        
        truncate_config = getattr(cls, "TRUNCATE", {})
        if not truncate_config:
            return data
            
        for field_name, max_len in truncate_config.items():
            value = data.get(field_name)
            if isinstance(value, str) and len(value) > max_len:
                data[field_name] = value[:max_len]
                logger.warning(f"Truncated field '{field_name}' to max length {max_len}")

        return data


class DataSource(Node):
    """DataSource node - represents a data source with full scraping configuration."""

    node_label: str = "DataSource"
    id_field: str = "datasource_id"
    
    # Core Identity
    datasource_id: str = Field(
        default="",
        description="Unique identifier for the data source (auto-generated from name if not provided)"
    )
    
    name: str = Field(
        ...,
        description="Name of the data source"
    )

    display_name: Optional[str] = Field(
        None,
        description="Human-readable display name shown in the UI (falls back to name if not set)"
    )

    area_acronym: Optional[str] = Field(
        None,
        description="IETF area acronym (e.g., 'wit', 'int', 'sec') — used to group IETF WG datasources in the UI"
    )

    area_name: Optional[str] = Field(
        None,
        description="IETF area full name (e.g., 'Web and Internet Transport') — used as section header in UI"
    )
    
    source_type: str = Field(
        ...,
        description="Type of data source (e.g., 'api', 'webpage', 'sharepoint', 'rss', 'database', 'scraped_webpage', 'authenticated_portal')"
    )
    
    fetch_url: Optional[str] = Field(
        None,
        description="URL to fetch data from (optional)"
    )
    
    has_events: bool = Field(
        default=False,
        description="Whether this datasource contains events (calendar, conference listings, etc.)"
    )
    
    # Scraper Configuration
    scraper_type: Optional[str] = Field(
        None,
        description="Scraper class to use (e.g., 'wfa', 'wfa_causeway'). NULL = manual only"
    )
    
    resource_url: Optional[str] = Field(
        None,
        description="URL path to scrape (e.g., '/resource-center', '/wg/WiFi7MTG/document')"
    )
    
    # Scheduling
    scrape_schedule: Optional[str] = Field(
        None,
        description="Cron expression for scheduling (e.g., '0 2 * * *' = 2 AM daily). NULL = manual only"
    )
    
    run_on_startup: bool = Field(
        default=False,
        description="Run immediately when retriever starts"
    )
    
    full_refresh_schedule: Optional[str] = Field(
        None,
        description="Cron expression for content update checks (e.g., weekly full scan)"
    )
    
    last_scraped_at: Optional[datetime] = Field(
        None,
        description="Timestamp of last successful scrape"
    )
    
    # Content Processing
    check_content_hash: bool = Field(
        default=True,
        description="Whether to check content hash for deduplication"
    )
    
    # Scoring Weights
    publish_weight: float = Field(
        default=1.0,
        description="Weight for newly published documents"
    )
    
    update_weight: float = Field(
        default=0.8,
        description="Weight for updated documents"
    )
    
    event_weight: float = Field(
        default=0.9,
        description="Weight for events"
    )
    
    temporal_extraction_days: Optional[int] = Field(
        default=90,
        description="Days threshold for extracting events from documents"
    )
    
    # Scraper Behavior Settings
    scraper_delay: float = Field(
        default=0.5,
        description="Delay between requests in seconds"
    )
    
    max_resources: int = Field(
        default=150,
        description="Max resources to scrape per run (-1 = unlimited)"
    )
    
    max_redirects: int = Field(
        default=10,
        description="Max redirects to follow when resolving URLs"
    )
    
    discovery_mode: Optional[str] = Field(
        default='incremental',
        description="Discovery strategy: 'date_based' (Causeway) or 'incremental' (WFA public). None for non-scraped sources."
    )
    
    consecutive_duplicates_limit: int = Field(
        default=5,
        description="For incremental mode: stop after N consecutive duplicates"
    )
    
    # Causeway-specific (hierarchical scrapers)
    folders: Optional[List[str]] = Field(
        None,
        description="Folder paths for hierarchical scrapers (e.g., Causeway working groups)"
    )
    
    NORMALIZE = {
        "name": "title",
        "source_type": "lower",
        "fetch_url": "lower",
        "scraper_type": "lower",
        "discovery_mode": "lower"
    }
    
    @model_validator(mode='after')
    def validate_id(self):
        if (not self.datasource_id) and self.name:
            self.datasource_id = slugify(self.name)
        return self


class IngestionBatch(Node):
    """
    IngestionBatch node - tracks the lifecycle of a scrape→digest pipeline.
    
    Each time the retriever scrapes a datasource, it creates an IngestionBatch.
    The batch tracks progress through scraping, digesting, and completion.
    This enables the curator to know when all items have been digested
    before running event reconciliation.
    """
    
    node_label: str = "IngestionBatch"
    id_field: str = "batch_id"
    
    batch_id: str = Field(
        ...,
        description="UUID uniquely identifying this batch"
    )
    
    datasource_id: str = Field(
        ...,
        description="ID of the datasource this batch belongs to (denormalized for fast queries)"
    )
    
    status: str = Field(
        default="scraping",
        description="Batch status: 'scraping', 'digesting', 'completed', 'failed'"
    )
    
    scrape_started_at: Optional[datetime] = Field(
        default=None,
        description="When the retriever started scraping"
    )
    
    scrape_completed_at: Optional[datetime] = Field(
        default=None,
        description="When the retriever finished scraping"
    )
    
    digest_completed_at: Optional[datetime] = Field(
        default=None,
        description="When the digester finished processing all items"
    )
    
    items_scraped: int = Field(
        default=0,
        description="Number of items sent to the queue by retriever"
    )
    
    items_digested: int = Field(
        default=0,
        description="Number of items processed by digester"
    )
    
    events_count: int = Field(
        default=0,
        description="Number of events ingested in this batch"
    )
    
    resources_count: int = Field(
        default=0,
        description="Number of resources ingested in this batch"
    )
    
    error_message: Optional[str] = Field(
        default=None,
        description="Error message if batch failed"
    )
    
    reconciled_at: Optional[datetime] = Field(
        default=None,
        description="When event reconciliation was run for this batch (null if not yet reconciled)"
    )
    
    NORMALIZE = {
        "status": "lower"
    }
    
    def build_embedding(self) -> List[float]:
        """IngestionBatch doesn't need embeddings."""
        return []


class Resource(Node):
    """Resource node - represents a document/resource."""

    node_label: str = "Resource"
    id_field: str = "url_hash"

    # Unique identifier for the resource
    url_hash: str = Field(
        default="",
        description="SHA256 hash of the URL - serves as unique identifier (auto-generated)"
    )

    url: str = Field(
        ...,
        description="URL where the resource can be accessed"
    )
    
    title: str = Field(
        ...,
        max_length=500,
        description="Title of the resource"
    )

    summary: str = Field(
        default="",
        description="Brief summary or abstract of the resource"
    )
    
    content_hash: str = Field(
        ...,
        description="SHA256 hash of the actual content to detect changes"
    )
    
    doc_type: str = Field(
        ...,
        description="Document type (e.g., 'pdf', 'docx', 'html', 'txt')"
    )
    
    category: str = Field(
        ...,
        description="Resource category (e.g., 'blog', 'press release', 'paper', 'whitepaper', 'article')"
    )

    scraped_at: datetime = Field(
        ...,
        description="Timestamp when the resource metadata was last scraped"
    )

    importance: Optional[float] = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="How important or urgent the document is (0.0-1.0)"
    )

    datasource_id: str = Field(
        ...,
        description="Unique identifier for the data source (e.g., 'api', 'webpage', 'sharepoint', 'rss', 'database')"
    )

    workgroup_id: Optional[str] = Field(
        default=None,
        description="IETF WG acronym (e.g., 'quic', 'http', 'bgp') for IETF Datatracker resources; NULL for all other sources"
    )

    batch_id: Optional[str] = Field(
        default=None,
        description="ID of the ingestion batch this resource was ingested in"
    )

    importance_explanation: Optional[str] = Field(
        ...,
        description="Brief explanation of the importance score"
    )
    
    extreme_impact: Optional[str] = Field(
        None,
        description="Impact and outcomes on Extreme Networks company, products, services, clients"
    )
    
    publish_date: Optional[datetime] = Field(
        None,
        description="Publication date of the resource (ISO 8601 datetime)"
    )
    
    content_changed_at: Optional[datetime] = Field(
        None,
        description="Timestamp when the resource content was last changed (based on content_hash)"
    )
    
    language: str = Field(
        default="en",
        description="ISO 639-1 language code (e.g., 'en', 'es', 'fr', 'de')"
    )
    
    access_notes: Optional[str] = Field(
        None,
        description="Notes about access barriers (e.g., 'requires login', 'paywall', 'registration required')"
    )
    
    # S3 Storage fields (for user uploads - null for scraped resources)
    s3_bucket: Optional[str] = Field(
        None,
        description="S3 bucket name where the original file is stored"
    )
    
    s3_key: Optional[str] = Field(
        None,
        description="S3 object key path for generating presigned download URLs"
    )

    # Temporal confidence — set by digester based on publish_date availability.
    # "high": publish_date was present and parsed successfully.
    # "low":  publish_date was absent/unparseable; effective date is estimated.
    # Recency queries deprioritise "low" confidence resources.
    temporal_confidence: str = Field(
        default="high",
        description="Confidence in the resource's publish date ('high' or 'low')"
    )

    # Archival flag — set by curator for content older than the configured threshold.
    # Archived resources are excluded from all oracle queries by default.
    archived: bool = Field(
        default=False,
        description="True if the resource has been archived due to age"
    )

    TRUNCATE = {
        "title": 500
    }  

    NORMALIZE = {
        "title": "title",
        "summary": "sentence",
        "doc_type": "lower",
        "category": "lower",
        "importance_explanation": "sentence",
        "extreme_impact": "sentence",
        "access_notes": "sentence"
    }

    # Generate url_hash after initialization
    @model_validator(mode='after')
    def generate_url_hash(self):
        url_str = str(self.url)
        self.url_hash = hashlib.sha256(url_str.encode('utf-8')).hexdigest()
        return self

    def get_embedding_fields(self) -> List[str]:
        # Specify fields relevant for Topic embeddings
        return ["title", "summary"]


class Topic(Node):
    """
    Topic node - represents a subject or topic in the knowledge graph.
    
    Topics represent areas of knowledge, technical concepts, or subject matter.
    They can be organized hierarchically through SUBTOPIC_OF relationships.
    
    The topic_id is automatically generated from the name if not provided.
    """

    node_label: str = "Topic"    
    id_field: str = "topic_id"

    # Unique identifier for the topic
    topic_id: str = Field(
        default="",
        description="Unique slugified identifier generated from name (e.g., 'wi-fi-6e', 'network-security')"
    )
    
    name: str = Field(
        ...,
        description="Human-readable topic name (e.g., 'Wi-Fi 6E', 'Network Security')"
    )
    
    classification: str = Field(
        ...,
        description="Topic classification (e.g., 'standard', 'certification', 'regulation', 'framework', 'technology', etc.)"
    )
    
    identifier: Optional[str] = Field(
        None,
        description="Canonical identifier for the topic (e.g., 'IEEE 802.11be', 'ISO/IEC 27001')"
    )
    
    issuer: Optional[str] = Field(
        None,
        description="Organization that issues/maintains this topic (e.g., 'ISO', 'Wi-Fi Alliance', 'NIST')"
    )
    
    aliases: List[str] = Field(
        default_factory=list,
        description="Alternative names or synonyms for this topic (e.g., ['802.11ax', 'High Efficiency Wireless'])"
    )
    
    created_by: str = Field(
        default="unknown",
        description="Service that created this topic (e.g., 'digester', 'curator', 'manual', 'api')"
    )
    
    # Curation tracking - used to avoid repeatedly processing stubborn topics
    curation_attempts: int = Field(
        default=0,
        description="Number of times this topic has been processed by the curator without being organized"
    )
    
    last_curated_at: Optional[str] = Field(
        None,
        description="ISO timestamp of last curation attempt (e.g., '2026-01-28T10:30:00Z')"
    )
    
    # Deduplication metadata (populated during deduplication process)
    deduplication_best_match_id: Optional[str] = Field(
        None,
        description="ID of the best matching existing node found during deduplication (if any)"
    )
    
    deduplication_best_match_name: Optional[str] = Field(
        None,
        description="Name of the best matching existing node found during deduplication (if any)"
    )
    
    deduplication_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Similarity score of the best match (0.0-1.0)"
    )

    NORMALIZE = {
        "name": "lower",
        "classification": "lower",
        "identifier": "lower",
        "issuer": "lower",
        "aliases": "lower"
    }

    # Build slugified topic_id from name if not provided
    @model_validator(mode='after')
    def validate_id(self):
        if (not self.topic_id) and self.name:
            self.topic_id = slugify(self.name)
        return self

    def get_embedding_fields(self) -> List[str]:
        # Specify fields relevant for Topic embeddings
        return ["name", "identifier", "aliases"]


class Organization(Node):
    """Organization node - represents an organization."""

    node_label: str = "Organization"
    id_field: str = "org_id"
    
    # Unique identifier for the organization
    org_id: str = Field(
        default="",
        description="Unique identifier for the organization (auto-generated from name if not provided)"
    )
    
    name: str = Field(
        ...,
        description="Name of the organization"
    )

    org_type: str = Field(
        ...,
        description="Organization type (e.g., 'standards body', 'consortium', 'vendor', 'non-profit', 'academic')"
    )
    
    aliases: List[str] = Field(
        default_factory=list,
        description="Alternative names for this organization"
    )
    
    homepage_url: Optional[str] = Field(
        None,
        description="Organization's homepage URL"
    )
    
    # Deduplication metadata (populated during deduplication process)
    deduplication_best_match_id: Optional[str] = Field(
        None,
        description="ID of the best matching existing node found during deduplication (if any)"
    )
    
    deduplication_best_match_name: Optional[str] = Field(
        None,
        description="Name of the best matching existing node found during deduplication (if any)"
    )
    
    deduplication_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Similarity score of the best match (0.0-1.0)"
    )
    
    NORMALIZE = {
        "name": "title",
        "org_type": "lower",
        "aliases": "title",
        "homepage_url": "lower"
    }
    
    @model_validator(mode='after')
    def validate_id(self):
        if (not self.org_id) and self.name:
            self.org_id = slugify(self.name)
        return self

    def get_embedding_fields(self) -> List[str]:
        # Specify fields relevant for Organization embeddings
        return ["name", "org_type", "aliases"]

class Person(Node):
    """Person node - represents an individual."""

    node_label: str = "Person"
    id_field: str = "person_id"
    
    # Unique identifier for the person
    person_id: str = Field(
        default="",
        description="Unique identifier for the person (auto-generated from name if not provided)"
    )
    
    name: str = Field(
        ...,
        description="Name of the person"
    )
    
    email: Optional[str] = Field(
        None,
        description="Email address of the person"
    )
    
    user_uuid: Optional[str] = Field(
        None,
        description="UUID from Postgres users table (if this person is a registered user)"
    )
    
    # Deduplication metadata (populated during deduplication process)
    deduplication_best_match_id: Optional[str] = Field(
        None,
        description="ID of the best matching existing node found during deduplication (if any)"
    )
    
    deduplication_best_match_name: Optional[str] = Field(
        None,
        description="Name of the best matching existing node found during deduplication (if any)"
    )
    
    deduplication_score: Optional[float] = Field(
        None,
        ge=0.0,
        le=1.0,
        description="Similarity score of the best match (0.0-1.0)"
    )
    
    NORMALIZE = {
        "name": "title",
        "email": "lower"
    }
    
    @model_validator(mode='after')
    def validate_id(self):
        if (not self.person_id) and self.name:
            self.person_id = slugify(self.name)
        return self

    def get_embedding_fields(self) -> List[str]:
        # Specify fields relevant for Person embeddings
        return ["name", "email"]

class Event(Node):
    """
    Event node - represents a scheduled event, meeting, conference, or deadline.
    
    Events are temporal entities extracted from documents that have specific dates.
    They can represent future events (conferences, meetings, deadlines) or past events
    (historical meetings, completed conferences).
    
    The event_id is generated from the URL (preferred) or falls back to name+date slug.
    URL-based IDs are more stable as events may be renamed or rescheduled.
    """

    node_label: str = "Event"
    id_field: str = "url_hash"
    
    # Unique identifier - SHA256 hash of URL (same pattern as Resource)
    url_hash: str = Field(
        default="",
        description="SHA256 hash of the event URL - serves as unique identifier (auto-generated)"
    )
    
    name: str = Field(
        ...,
        description="Human-readable event name (e.g., 'Wi-Fi Alliance Congress 2025', 'IEEE 802.11 Working Group Meeting')"
    )
    
    event_type: str = Field(
        ...,
        description="Type of event (e.g., 'conference', 'meeting', 'webinar', 'deadline', 'workshop', 'seminar', 'summit')"
    )
    
    start_date: Optional[datetime] = Field(
        None,
        description="Start date and time of the event (ISO 8601 format)"
    )
    
    end_date: Optional[datetime] = Field(
        None,
        description="End date and time of the event (ISO 8601 format, for multi-day events)"
    )
    
    location: Optional[str] = Field(
        default=None,
        description="Location of the event (e.g., 'Dubai, UAE', 'Virtual', 'San Francisco, CA')"
    )
    
    timezone: Optional[str] = Field(
        None,
        description="Timezone of the event (e.g., 'UTC', 'America/New_York', 'Europe/London')"
    )
    
    description: str = Field(
        default="",
        description="Description of the event (scraped from source)"
    )
    
    url: str = Field(
        ...,
        description="URL for event registration or more information (required for stable ID generation)"
    )
    
    status: str = Field(
        default="scheduled",
        description="Event status: 'scheduled', 'cancelled', 'rescheduled', 'completed', 'unconfirmed'"
    )

    datasource_id: str = Field(
        ...,
        description="Unique identifier for the data source this event was ingested from"
    )
    
    batch_id: Optional[str] = Field(
        default=None,
        description="ID of the ingestion batch this event was ingested in"
    )
    
    scraped_at: Optional[datetime] = Field(
        default=None,
        description="When this event was last scraped from the source (ISO 8601 format)"
    )

    NORMALIZE = {
        "name": "title",
        "event_type": "lower",
        "location": "title",
        "status": "lower"
    }
    
    # Generate url_hash from URL (same pattern as Resource)
    @model_validator(mode='after')
    def generate_url_hash(self):
        if not self.url_hash:
            self.url_hash = hashlib.sha256(self.url.encode('utf-8')).hexdigest()
        return self

    def get_embedding_fields(self) -> List[str]:
        # Include dates for temporal differentiation (e.g., "Wi-Fi Congress 2025" vs "2026")
        return ["name", "event_type", "location", "start_date", "end_date"]

# TODO

class Team(Node):
    """Team node - represents a team or group."""
    
    name: str
    description: str = ""


class Project(Node):
    """Project node - represents a project."""
    
    name: str
    description: str = ""
    status: str = ""


class Skill(Node):
    """Skill node - represents a skill or competency."""
    
    name: str
    category: str = ""


class Report(Node):
    """Report node - represents a report."""
    
    title: str
    report_type: str
    summary: str = ""


class Insight(Node):
    """Insight node - represents an insight or finding."""
    
    content: str
    source: str = ""
    confidence: Optional[float] = None


class Digest(Node):
    """Digest node - represents a content digest."""
    
    title: str
    summary: str
    period: str = ""


class Tag(Node):
    """Tag node - represents a tag or label."""
    
    name: str
    category: str = ""


# ========== Relationship Models ==========

class IngestionBatchBelongsToDataSource(Relationship):
    """Relationship: IngestionBatch belongs to a DataSource."""
    
    source_node_label: str = "IngestionBatch"
    source_id_field: str = "batch_id"
    target_node_label: str = "DataSource"
    target_id_field: str = "datasource_id"
    relationship_label: str = "BELONGS_TO"


class ResourceIngestedInBatch(Relationship):
    """Resource - ingested in -> IngestionBatch
    
    Tracks which batch a resource was ingested in.
    Enables queries like "find all resources from batch X".
    """
    source_node_label: str = "Resource"
    source_id_field: str = "url_hash"
    target_node_label: str = "IngestionBatch"
    target_id_field: str = "batch_id"
    relationship_label: str = "INGESTED_IN"


class EventIngestedInBatch(Relationship):
    """Event - ingested in -> IngestionBatch
    
    Tracks which batch an event was ingested in.
    Enables queries like "find all events from batch X".
    """
    source_node_label: str = "Event"
    source_id_field: str = "url_hash"
    target_node_label: str = "IngestionBatch"
    target_id_field: str = "batch_id"
    relationship_label: str = "INGESTED_IN"


class ResourceRelatesToTopic(Relationship):
    """Resource - relates to -> Topic"""
    source_node_label: str = "Resource"
    source_id_field: str = "url_hash"
    target_node_label: str = "Topic"
    target_id_field: str = "topic_id"
    relationship_label: str = "RELATES_TO"
    
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")
    relevance: float = Field(..., ge=0.0, le=1.0, description="Relevance score (0.0-1.0)")
    evidence: str = Field(..., description="Direct quote from content supporting this relationship")
    stance: str = Field(
        ..., 
        description="Stance of the resource toward the topic",
        pattern="^(descriptive|supportive|critical|concerned|directive|mixed|speculative)$"
    )
    stance_score: float = Field(..., ge=0.0, le=1.0, description="Stance score (0 to 1.0)")

    TRUNCATE = {
        "evidence": 240
    }   

    NORMALIZE = {
        "evidence": "sentence",
        "stance": "lower"
    }

class ResourceMentionsPerson(Relationship):
    """Resource - mentions -> Person"""
    source_node_label: str = "Resource"
    source_id_field: str = "url_hash"
    target_node_label: str = "Person"
    target_id_field: str = "person_id"
    relationship_label: str = "MENTIONS"
    
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")
    role: Optional[str] = Field(None, description="Role of the person in the context")
    evidence: str = Field(..., description="Direct quote from content mentioning this person")

    TRUNCATE = {
        "evidence": 240
    }  

    NORMALIZE = {
        "evidence": "sentence",
        "role": "sentence"
    }

class ResourceMentionsOrganization(Relationship):
    """Resource - mentions -> Organization"""
    source_node_label: str = "Resource"
    source_id_field: str = "url_hash"
    target_node_label: str = "Organization"
    target_id_field: str = "org_id"
    relationship_label: str = "MENTIONS"
    
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")
    evidence: str = Field(..., description="Direct quote from content mentioning this organization")

    TRUNCATE = {
        "evidence": 240
    }  

    NORMALIZE = {
        "evidence": "sentence"
    }

class PersonAffiliatedWithOrganization(Relationship):
    """Person - affiliated with -> Organization"""
    source_node_label: str = "Person"
    source_id_field: str = "person_id"
    target_node_label: str = "Organization"
    target_id_field: str = "org_id"
    relationship_label: str = "AFFILIATED_WITH"
    
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")
    role: Optional[str] = Field(None, description="Role or position of the person in the organization")
    evidence: str = Field(..., description="Direct quote from content supporting this affiliation")

    TRUNCATE = {
        "evidence": 240
    }  

    NORMALIZE = {
        "evidence": "sentence",
        "role": "sentence"
    }

class PersonConnectedToTopic(Relationship):
    """Person - connected to -> Topic"""
    source_node_label: str = "Person"
    source_id_field: str = "person_id"
    target_node_label: str = "Topic"
    target_id_field: str = "topic_id"
    relationship_label: str = "CONNECTED_TO"
    
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")
    affiliation: Optional[str] = Field(None, description="Nature of the connection or affiliation")
    evidence: str = Field(..., description="Direct quote from content supporting this connection")

    TRUNCATE = {
        "evidence": 240
    }  

    NORMALIZE = {
        "evidence": "sentence",
        "affiliation": "sentence"
    }

class OrganizationAssociatedWithTopic(Relationship):
    """Organization - associated with -> Topic"""
    source_node_label: str = "Organization"
    source_id_field: str = "org_id"
    target_node_label: str = "Topic"
    target_id_field: str = "topic_id"
    relationship_label: str = "ASSOCIATED_WITH"
    
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")
    affiliation: Optional[str] = Field(None, description="Nature of the association or affiliation")
    evidence: str = Field(..., description="Direct quote from content supporting this association")

    TRUNCATE = {
        "evidence": 240
    }  

    NORMALIZE = {
        "evidence": "sentence",
        "affiliation": "sentence"
    }

class ResourceIngestedFromDataSource(Relationship):
    """Resource - ingested from -> DataSource"""
    source_node_label: str = "Resource"
    source_id_field: str = "url_hash"
    target_node_label: str = "DataSource"
    target_id_field: str = "datasource_id"
    relationship_label: str = "INGESTED_FROM"

class EventIngestedFromDataSource(Relationship):
    """Event - ingested from -> DataSource"""
    source_node_label: str = "Event"
    source_id_field: str = "url_hash"
    target_node_label: str = "DataSource"
    target_id_field: str = "datasource_id"
    relationship_label: str = "INGESTED_FROM"


class EventSupersedes(Relationship):
    """Event - supersedes -> Event
    
    Indicates that the source event supersedes (replaces) the target event.
    This is used when an event is rescheduled to a new URL or renamed.
    The target event should be marked with status='rescheduled'.
    
    Example:
        New URL event (supersedes) -> Old URL event (status='rescheduled')
    """
    source_node_label: str = "Event"
    source_id_field: str = "url_hash"
    target_node_label: str = "Event"
    target_id_field: str = "url_hash"
    relationship_label: str = "SUPERSEDES"
    
    similarity_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Embedding similarity score between the two events (0.0-1.0)"
    )
    reason: str = Field(
        default="",
        description="Explanation of why this event supersedes the other (e.g., 'URL changed', 'Rescheduled')"
    )


class DataSourceBelongsToOrganization(Relationship):
    """DataSource - belongs to -> Organization"""
    source_node_label: str = "DataSource"
    source_id_field: str = "datasource_id"
    target_node_label: str = "Organization"
    target_id_field: str = "org_id"
    relationship_label: str = "BELONGS_TO"



class TopicEncompasses(Relationship):
    """Topic - encompasses -> Topic (A encompasses B means A is a broader category that includes B)"""
    source_node_label: str = "Topic"
    source_id_field: str = "topic_id"
    target_node_label: str = "Topic"
    target_id_field: str = "topic_id"
    relationship_label: str = "ENCOMPASSES"

    reasoning: str = Field(..., description="Brief explanation of why source topic encompasses target topic")
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")

    NORMALIZE = {
        "reasoning": "sentence"
    }

class TopicSubtopicOf(Relationship):
    """Topic - subtopic of -> Topic (A is subtopic of B means A is a more specific topic within B)"""
    source_node_label: str = "Topic"
    source_id_field: str = "topic_id"
    target_node_label: str = "Topic"
    target_id_field: str = "topic_id"
    relationship_label: str = "SUBTOPIC_OF"

    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")

class ResourceUploadedByPerson(Relationship):
    """Resource - uploaded by -> Person"""
    source_node_label: str = "Resource"
    source_id_field: str = "url_hash"
    target_node_label: str = "Person"
    target_id_field: str = "person_id"
    relationship_label: str = "UPLOADED_BY"
    
    uploaded_at: Optional[str] = Field(None, description="Timestamp when uploaded")

class ResourceRelatesToEvent(Relationship):
    """Resource - relates to -> Event
    
    Represents any relationship between a resource and an event.
    Use confidence score to indicate relationship strength:
    - 0.8-1.0: Strong relationship (meeting minutes, presentations, materials FROM event)
    - 0.5-0.8: Medium relationship (announcements, descriptions ABOUT event)
    - 0.2-0.5: Weak relationship (casual mentions, references TO event)
    
    Optional context_type provides additional specificity when needed.
    """
    source_node_label: str = "Resource"
    source_id_field: str = "url_hash"
    target_node_label: str = "Event"
    target_id_field: str = "url_hash"
    relationship_label: str = "RELATES_TO"
    
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")
    evidence: str = Field(..., description="Direct quote from content relating to this event")
    context_type: Optional[str] = Field(
        None,
        description="Type of relationship: 'material' (from event), 'announcement' (about event), 'reference' (mentions event)"
    )
    
    TRUNCATE = {
        "evidence": 240
    }
    
    NORMALIZE = {
        "evidence": "sentence",
        "context_type": "lower"
    }


class PersonAttendingEvent(Relationship):
    """Person - attending -> Event
    
    Represents a user's intention to attend an event.
    Users can mark/unmark attendance and indicate if they're presenting.
    """
    source_node_label: str = "Person"
    source_id_field: str = "person_id"
    target_node_label: str = "Event"
    target_id_field: str = "url_hash"
    relationship_label: str = "ATTENDING"
    
    marked_at: datetime = Field(
        ...,
        description="Timestamp when user marked/updated their attendance"
    )
    
    is_presenting: bool = Field(
        default=False,
        description="Whether the person is presenting at this event"
    )


class VideoSegmentOf(Relationship):
    """Relationship between a video segment and its parent video."""
    _type: ClassVar[str] = "VIDEO_SEGMENT_OF"
    
    segment_number: int = Field(..., description="Segment number (1-indexed)")
    timestamp_start: int = Field(..., description="Start timestamp in seconds")
    timestamp_end: Optional[int] = Field(default=None, description="End timestamp in seconds, None for last segment")


def slugify(text: str) -> str:
    """
    Convert text to a URL-friendly slug.
    
    Examples:
        'Wi-Fi 6E' -> 'wi-fi-6e'
        'Network Security' -> 'network-security'
        '802.11ax' -> '802-11ax'
    """
    text = text.lower()
    text = re.sub(r'[^\w\s-]', '', text)  # Remove special chars except - and spaces
    text = re.sub(r'[-\s]+', '_', text)    # Replace spaces and multiple - with single _
    return text.strip('-')


def normalize_string(value: str, case: str = "lower") -> str:
    """
    Normalize a single string value.
    - Strips leading/trailing whitespace
    - Collapses multiple spaces
    - Normalizes case: 'upper', 'lower', 'title', 'sentence'
    - Returns empty string for None
    
    Args:
        value: The input value to normalize
        case: Case normalization ('upper', 'lower', 'title', 'sentence')
        
    Returns:
        Normalized string
    """
    if value is None:
        return ""
    
    if not isinstance(value, str):
        value = str(value)
    
    # Strip and collapse whitespace
    value = value.strip()
    value = " ".join(value.split())
    
    # Apply case normalization
    if case == "upper":
        value = value.upper()
    elif case == "lower":
        value = value.lower()
    elif case == "title":
        value = value.title()
    elif case == "sentence":
        if value:
            value = value[0].upper() + value[1:].lower()
    
    return value
