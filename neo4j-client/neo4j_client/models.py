"""Node and Relationship models for Neo4j knowledge graph."""

from typing import Dict, Any, List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, ConfigDict, model_validator
import re
import hashlib


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
    
    created_at: datetime = Field(default_factory=datetime.now)
    
    model_config = ConfigDict(
        # Allow extra fields for flexibility (like **kwargs)
        extra="allow",
        # Use arbitrary types (for datetime, etc.)
        arbitrary_types_allowed=True
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert node to dictionary for Neo4j.
        Excludes None values and converts datetime to ISO format.
        """
        data = self.model_dump(exclude_none=True)
        # Convert datetime to ISO string for Neo4j
        if 'created_at' in data and isinstance(data['created_at'], datetime):
            data['created_at'] = data['created_at'].isoformat()
        return data


class Relationship(BaseModel):
    """Base class for graph relationships."""
    
    created_at: datetime = Field(default_factory=datetime.now)
    
    model_config = ConfigDict(
        extra="allow",
        arbitrary_types_allowed=True
    )
    
    def to_dict(self) -> Dict[str, Any]:
        """
        Convert relationship to dictionary for Neo4j.
        Excludes None values and converts datetime to ISO format.
        """
        data = self.model_dump(exclude_none=True)
        # Convert datetime to ISO string for Neo4j
        if 'created_at' in data and isinstance(data['created_at'], datetime):
            data['created_at'] = data['created_at'].isoformat()
        return data


class Resource(Node):
    """Resource node - represents a document/resource."""

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
    
    publish_date: Optional[str] = Field(
        None,
        description="Publication date of the resource"
    )

    scraped_at: datetime = Field(
        ...,
        description="Timestamp when the resource metadata was last updated"
    )
    
    language: str = Field(
        default="en",
        description="ISO 639-1 language code (e.g., 'en', 'es', 'fr', 'de')"
    )
    
    summary: str = Field(
        default="",
        description="Brief summary or abstract of the resource"
    )
    
    access_notes: Optional[str] = Field(
        None,
        description="Notes about access barriers (e.g., 'requires login', 'paywall', 'registration required')"
    )
    
    resource_vector: Optional[List[float]] = Field(
        None,
        description="Semantic embedding vector for similarity matching and recommendations"
    )

    @model_validator(mode='after')
    def generate_url_hash(self):
        url_str = str(self.url)
        self.url_hash = hashlib.sha256(url_str.encode('utf-8')).hexdigest()
        return self


class Topic(Node):
    """
    Topic node - represents a subject or topic in the knowledge graph.
    
    Topics represent areas of knowledge, technical concepts, or subject matter.
    They can be organized hierarchically through SUBTOPIC_OF relationships.
    
    The topic_id is automatically generated from the name if not provided.
    """

    topic_id: str = Field(
        default="",
        description="Unique slugified identifier generated from name (e.g., 'wi-fi-6e', 'network-security')"
    )
    
    name: str = Field(
        ...,
        description="Human-readable topic name (e.g., 'Wi-Fi 6E', 'Network Security')"
    )
    
    aliases: List[str] = Field(
        default_factory=list,
        description="Alternative names or synonyms for this topic (e.g., ['802.11ax', 'High Efficiency Wireless'])"
    )
    
    topic_vector: Optional[List[float]] = Field(
        None,
        description="Semantic embedding vector for similarity matching and recommendations"
    )
    
    @model_validator(mode='after')
    def validate_id(self):
        if (not self.topic_id) and self.name:
            self.topic_id = slugify(self.name)
        return self


class Organization(Node):
    """Organization node - represents an organization."""
    
    org_id: str = Field(
        default="",
        description="Unique identifier for the organization (auto-generated from name if not provided)"
    )
    
    name: str = Field(
        ...,
        description="Name of the organization"
    )
    
    type: str = Field(
        ...,
        description="Organization type (e.g., 'standards body', 'consortium', 'vendor', 'non-profit', 'academic')"
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


class DataSource(Node):
    """DataSource node - represents a data source."""
    
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


class Standard(Node):
    """Standard node - represents a technical standard."""
    
    standard_id: str = Field(
        default="",
        description="Unique identifier for the standard (auto-generated from identifier if not provided)"
    )
    
    identifier: str = Field(
        ...,
        description="Canonical external ID for the standard (e.g., 'IEEE 802.11ax', 'RFC 9000')"
    )
    
    name: str = Field(
        ...,
        description="Human-readable name of the standard"
    )
    
    aliases: List[str] = Field(
        default_factory=list,
        description="Alternative names or identifiers for this standard (e.g., ['Wi-Fi 6', '802.11ax'])"
    )
    
    @model_validator(mode='after')
    def validate_id(self):
        if (not self.standard_id) and self.name:
            self.standard_id = slugify(self.name)
        return self


class StandardEdition(Node):
    """Standard Edition node - represents a specific version of a standard."""
    
    edition_id: str = Field(
        default="",
        description="Unique identifier for the edition (auto-generated from identifier and version if not provided)"
    )

    name: str = Field(
        ...,
        description="Human-readable name of the standard"
    )
    
    identifier: str = Field(
        ...,
        description="Base identifier of the standard (e.g., 'IEEE 802.11ax', 'RFC 9000')"
    )
    
    version: str = Field(
        ...,
        description="Version of this edition (e.g., '2021', '2023', 'rev1')"
    )
    
    status: Optional[str] = Field(
        None,
        description="Status of this edition (e.g., 'current', 'deprecated', 'draft', 'obsolete')"
    )
    
    published_at: Optional[str] = Field(
        None,
        description="Publication date of this edition"
    )
    
    url: Optional[str] = Field(
        None,
        description="URL to the official document for this edition"
    )
    
    @model_validator(mode='after')
    def validate_id(self):
        if (not self.edition_id) and self.name:
            self.edition_id = slugify(self.name)
        return self


# To be reworked

class Person(Node):
    """Person node - represents an individual."""
    
    name: str
    email: str = ""
    title: str = ""


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
    """Event node - represents a general event."""
    
    name: str
    event_type: str
    date: str = ""
    location: str = ""


# ========== Relationship Models ==========

class ResourceRelatesToTopic(Relationship):
    """Resource - relates to -> Topic"""
    relevance_score: Optional[float] = Field(None, ge=0.0, le=1.0)
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)

class ResourceIngestedFrom(Relationship):
    """Resource - ingested_from -> DataSource"""
    pass

class ResourceReferencesStandard(Relationship):
    """Resource - references standard -> Standard"""
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)

class ResourceReferencesEdition(Relationship):
    """Resource - references edition -> StandardEdition"""
    confidence: Optional[float] = Field(None, ge=0.0, le=1.0)

class TopicSubtopicOf(Relationship):
    """Topic - subtopic of -> Topic"""
    pass

class DataSourceBelongsTo(Relationship):
    """DataSource - belongs to -> Organization"""
    pass

class EditionVersionOf(Relationship):
    """StandardEdition - version of -> Standard"""
    pass

class EditionSupersedes(Relationship):
    """StandardEdition - supersedes -> StandardEdition"""
    pass
