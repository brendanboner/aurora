"""
Neo4j Client Library

A shared library for interacting with the Aurora Neo4j Knowledge Graph.
"""

from .client import Neo4jClient
from .repository import GraphRepository
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
    TopicSubtopicOf,
)

__version__ = "0.1.0"

__all__ = [
    # Client
    "Neo4jClient",
    "GraphRepository",
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
    "TopicSubtopicOf",
]
