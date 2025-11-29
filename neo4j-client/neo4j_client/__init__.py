"""
Neo4j Client Library

A shared library for interacting with the Aurora Neo4j Knowledge Graph.
"""

from .client import Neo4jClient
from .repository import GraphRepository
from .deduplicator import NodeDeduplicator
from .models import (
    Node,
    Resource,
    Topic,
    Organization,
    DataSource,
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
    DataSourceBelongsToOrganization,
    TopicEncompasses,
    TopicSubtopicOf,
    ResourceUploadedByPerson,
    ResourceMentionsEvent
)

__version__ = "0.1.0"

__all__ = [
    # Client
    "Neo4jClient",
    "GraphRepository",
    "NodeDeduplicator",
    # Models
    "Node",
    "Resource",
    "Topic",
    "Organization",
    "DataSource",
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
    "DataSourceBelongsToOrganization",
    "TopicEncompasses",
    "TopicSubtopicOf",
    "ResourceUploadedByPerson",
    "ResourceMentionsEvent",
]
