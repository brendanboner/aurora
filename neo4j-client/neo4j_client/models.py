"""Node and Relationship models for Neo4j knowledge graph."""

from typing import Dict, Any, List, Optional, ClassVar
from datetime import datetime
import logging
from pydantic import BaseModel, Field, ConfigDict, model_validator
import re
import hashlib
try:
    from sentence_transformers import SentenceTransformer
except ImportError:  # Optional dependency
    SentenceTransformer = None  # type: ignore
    logging.getLogger(__name__).warning(
        "sentence_transformers not installed; embeddings generation disabled."
    )

logger = logging.getLogger(__name__)

# Lazy initialization for SentenceTransformer embedding model
_embedding_model = None
def get_embedding_model():
    """Return (and lazily initialize) the embedding model, if available.

    If sentence_transformers is not installed we return None and downstream
    embedding code will gracefully skip embedding generation.
    """
    global _embedding_model
    if SentenceTransformer is None:
        return None
    if _embedding_model is None:
        _embedding_model = SentenceTransformer('sentence-transformers/all-mpnet-base-v2')
    return _embedding_model


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


    # Build Node embedding
    @model_validator(mode='after')
    def set_embedding(self):
        self.embedding = self.build_embedding()
        return self

    @model_validator(mode="before")
    @classmethod
    def _truncate_strings(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        caps = getattr(cls, "TRUNCATE", {})
        if not caps or not isinstance(data, dict):
            return data

        for name, max_len in caps.items():
            value = data.get(name)
            if isinstance(value, str) and len(value) > max_len:
                data[name] = value[:max_len]
                logger.warning(f"Truncated field '{name}' to max length {max_len}")

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
        data = self.model_dump(exclude=["node_label", "id_field", "datasource_id"])
        # Convert datetime fields to ISO string for Neo4j
        datetime_fields = ['created_at', 'scraped_at', 'publish_date', 'content_changed_at', 'first_seen_at', 'start_date', 'end_date']
        for field in datetime_fields:
            if field in data and data[field] is not None and isinstance(data[field], datetime):
                data[field] = data[field].isoformat()
        return data

    def get_embedding_fields(self) -> List[str]:
        """
        Returns a list of field names to include in the embedding text.
        Subclasses should override to specify relevant fields.
        """
        # By default, include all string fields except 'created_at'
        return [name for name, field in self.__fields__.items()
                if field.annotation == str and name != "created_at"]

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
        """Generate embedding vector for the node if embedding model available.

        Returns empty list when embeddings are disabled (missing dependency) or
        when there is no meaningful text to embed.
        """
        embedding_text = self.get_embedding_text().strip()
        if not embedding_text:
            return []
        embedding_model = get_embedding_model()
        if embedding_model is None:
            return []
        try:
            logger.info(f"Generating embedding for text: {embedding_text}")
            embedding_vector = embedding_model.encode(
                embedding_text,
                convert_to_numpy=True,
                normalize_embeddings=True
            ).tolist()
            return embedding_vector
        except Exception as e:
            logger.warning(f"Failed to generate embedding: {e}; returning empty list")
            return []


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


    def to_dict(self) -> Dict[str, Any]:
        """
        Convert relationship to dictionary for Neo4j.
        Excludes None values, metadata fields, and converts datetime to ISO format.
        Only includes instance data (source_id, target_id, and relationship-specific fields).
        """
        data = self.model_dump(exclude={"source_id", "target_id", "source_node_label", "source_id_field", "target_node_label", "target_id_field", "relationship_label"})
        # Convert datetime to ISO string for Neo4j
        if 'created_at' in data and isinstance(data['created_at'], datetime):
            data['created_at'] = data['created_at'].isoformat()
        return data

    @model_validator(mode="before")
    @classmethod
    def _truncate_strings(cls, data: Dict[str, Any]) -> Dict[str, Any]:
        caps = getattr(cls, "TRUNCATE", {})
        if not caps or not isinstance(data, dict):
            return data

        for name, max_len in caps.items():
            value = data.get(name)
            if isinstance(value, str) and len(value) > max_len:
                data[name] = value[:max_len]
                logger.warning(f"Truncated field '{name}' to max length {max_len}")

        return data


class DataSource(Node):
    """DataSource node - represents a data source."""

    node_label: str = "DataSource"
    id_field: str = "source_id"
    
    # Unique identifier for the data source
    source_id: str = Field(
        default="",
        description="Unique identifier for the data source (auto-generated from name if not provided)"
    )
    
    name: str = Field(
        ...,
        description="Name of the data source"
    )
    
    source_type: str = Field(
        ...,
        description="Type of data source (e.g., 'api', 'webpage', 'sharepoint', 'rss', 'database')"
    )
    
    fetch_url: Optional[str] = Field(
        None,
        description="URL to fetch data from (optional)"
    )
    
    @model_validator(mode='after')
    def validate_id(self):
        if (not self.source_id) and self.name:
            self.source_id = slugify(self.name)
        return self

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
        description="Timestamp when the resource metadata was last updated"
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
    
    first_seen_at: Optional[datetime] = Field(
        None,
        description="Timestamp when the resource was first created in the knowledge graph"
    )
    
    language: str = Field(
        default="en",
        description="ISO 639-1 language code (e.g., 'en', 'es', 'fr', 'de')"
    )
    
    access_notes: Optional[str] = Field(
        None,
        description="Notes about access barriers (e.g., 'requires login', 'paywall', 'registration required')"
    )

    TRUNCATE = {
        "title": 500
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
    
    @model_validator(mode='after')
    def validate_id(self):
        if (not self.person_id) and self.name:
            self.person_id = slugify(self.name)
        return self

    def get_embedding_fields(self) -> List[str]:
        # Specify fields relevant for Person embeddings
        return ["name", "email"]

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


class Event(Node):
    """
    Event node - represents a scheduled event, meeting, conference, or deadline.
    
    Events are temporal entities extracted from documents that have specific dates.
    They can represent future events (conferences, meetings, deadlines) or past events
    (historical meetings, completed conferences).
    
    The event_id is automatically generated from the name if not provided.
    """

    node_label: str = "Event"
    id_field: str = "event_id"
    
    # Unique identifier for the event
    event_id: str = Field(
        default="",
        description="Unique slugified identifier generated from name (e.g., 'wfa-congress-2025', 'ieee-meeting-dec-2025')"
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
    
    location: str = Field(
        default="",
        description="Location of the event (e.g., 'Dubai, UAE', 'Virtual', 'San Francisco, CA')"
    )
    
    timezone: Optional[str] = Field(
        None,
        description="Timezone of the event (e.g., 'UTC', 'America/New_York', 'Europe/London')"
    )
    
    description: str = Field(
        default="",
        description="Brief description of the event"
    )
    
    url: Optional[str] = Field(
        None,
        description="URL for event registration or more information"
    )
    
    # Build slugified event_id from name if not provided
    @model_validator(mode='after')
    def validate_id(self):
        if (not self.event_id) and self.name:
            self.event_id = slugify(self.name)
        return self

    def get_embedding_fields(self) -> List[str]:
        # Specify fields relevant for Event embeddings
        return ["name", "event_type", "location", "description"]


# ========== Relationship Models ==========

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

class ResourceIngestedFromDataSource(Relationship):
    """Resource - ingested from -> DataSource"""
    source_node_label: str = "Resource"
    source_id_field: str = "url"
    target_node_label: str = "DataSource"
    target_id_field: str = "source_id"
    relationship_label: str = "INGESTED_FROM"

class DataSourceBelongsToOrganization(Relationship):
    """DataSource - belongs to -> Organization"""
    source_node_label: str = "DataSource"
    source_id_field: str = "source_id"
    target_node_label: str = "Organization"
    target_id_field: str = "org_id"
    relationship_label: str = "BELONGS_TO"

class TopicSubtopicOf(Relationship):
    """Topic - subtopic of -> Topic"""
    source_node_label: str = "Topic"
    source_id_field: str = "topic_id"
    target_node_label: str = "Topic"
    target_id_field: str = "topic_id"
    relationship_label: str = "SUBTOPIC_OF"

class ResourceUploadedByPerson(Relationship):
    """Resource - uploaded by -> Person"""
    source_node_label: str = "Resource"
    source_id_field: str = "url_hash"
    target_node_label: str = "Person"
    target_id_field: str = "person_id"
    relationship_label: str = "UPLOADED_BY"
    
    uploaded_at: Optional[str] = Field(None, description="Timestamp when uploaded")

class ResourceMentionsEvent(Relationship):
    """Resource - mentions -> Event"""
    source_node_label: str = "Resource"
    source_id_field: str = "url_hash"
    target_node_label: str = "Event"
    target_id_field: str = "event_id"
    relationship_label: str = "MENTIONS_EVENT"
    
    confidence: float = Field(..., ge=0.0, le=1.0, description="Confidence score (0.0-1.0)")
    evidence: str = Field(..., description="Direct quote from content mentioning this event")
    
    TRUNCATE = {
        "evidence": 240
    }


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
