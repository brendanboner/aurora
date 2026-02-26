"""
Neo4j Client Library

A shared library for interacting with the Aurora Neo4j Knowledge Graph.
"""

from .client import Neo4jClient
from .repository import GraphRepository
from .deduplicator import NodeDeduplicator
from .migrations import Migrations
from .models import (
    Node,
    Resource,
    Topic,
    Organization,
    DataSource,
    IngestionBatch,
    Person,
    Team,
    Project,
    Skill,
    Report,
    Insight,
    Digest,
    Tag,
    Event,
    ResourceRelatesToTopic,
    ResourceMentionsPerson,
    ResourceMentionsOrganization,
    PersonAffiliatedWithOrganization,
    PersonConnectedToTopic,
    OrganizationAssociatedWithTopic,
    ResourceIngestedFromDataSource,
    EventIngestedFromDataSource,
    EventSupersedes,
    DataSourceBelongsToOrganization,
    IngestionBatchBelongsToDataSource,
    ResourceIngestedInBatch,
    EventIngestedInBatch,
    TopicEncompasses,
    TopicSubtopicOf,
    ResourceUploadedByPerson,
    ResourceRelatesToEvent
)

__version__ = "0.1.0"

__all__ = [
    # Client
    "Neo4jClient",
    "GraphRepository",
    "NodeDeduplicator",
    "Migrations",
    # Models
    "Node",
    "Resource",
    "Topic",
    "Organization",
    "DataSource",
    "IngestionBatch",
    "Person",
    "Team",
    "Project",
    "Skill",
    "Report",
    "Insight",
    "Digest",
    "Tag",
    "Event",
    "ResourceRelatesToTopic",
    "ResourceMentionsPerson",
    "ResourceMentionsOrganization",
    "PersonAffiliatedWithOrganization",
    "PersonConnectedToTopic",
    "OrganizationAssociatedWithTopic",
    "ResourceIngestedFromDataSource",
    "EventIngestedFromDataSource",
    "EventSupersedes",
    "DataSourceBelongsToOrganization",
    "IngestionBatchBelongsToDataSource",
    "ResourceIngestedInBatch",
    "EventIngestedInBatch",
    "TopicEncompasses",
    "TopicSubtopicOf",
    "ResourceUploadedByPerson",
    "ResourceRelatesToEvent",
]
