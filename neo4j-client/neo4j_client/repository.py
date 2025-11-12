"""Repository for managing knowledge graph operations."""

from typing import Dict, Any, List, Optional, Tuple
import logging
import json
from pathlib import Path
from .client import Neo4jClient
from .models import *


logger = logging.getLogger(__name__)


class GraphRepository:
    """Repository for managing knowledge graph operations."""
    
    def __init__(self, client: Neo4jClient, logger_instance: Optional[logging.Logger] = None):
        """
        Initialize repository.
        
        Args:
            client: Neo4jClient instance
            logger_instance: Optional logger instance
        """
        self.client = client
        self.logger = logger_instance or logger

    def initialize_base_data(self):
        """
        Initialize base organizations and data sources from the local initial_data.json file.
        Creates organizations, data sources, and their relationships.
        """
        json_path = Path(__file__).parent / "initial_data.json"
        if not json_path.exists():
            self.logger.warning(f"Initial data file not found: {json_path}")
            return
        
        with open(json_path, "r") as f:
            data = json.load(f)
        
        orgs = data.get("organizations", [])
        data_sources = data.get("data_sources", [])
        
        # Create organizations
        for org_dict in orgs:
            org = Organization(**org_dict)
            self.create_organization(org)
        
        # Create data sources and link to organizations
        for ds_dict in data_sources:
            ds = DataSource(**ds_dict)
            org_id = ds_dict.get("org_id")
            
            # Create the data source
            self.create_datasource(ds)
            
            # Link data source to organization if org_id is provided
            if org_id:
                belongs_to_rel = DataSourceBelongsTo()
                self.link_datasource_to_organization(ds.source_id, org_id, belongs_to_rel)
        
        self.logger.info("Base data initialization complete")
    
    
    # ========== Resource Operations ==========
    
    def create_resource(self, resource: Resource) -> Optional[Dict[str, Any]]:
        """
        Create or update a Resource node.
        Explicitly sets required fields and dynamically handles optional ones.
        
        Args:
            resource: Resource model instance
        Returns:
            Created/updated resource node data
        """
        resource_data = resource.to_dict()
        
        # Extract optional fields that may or may not be present
        optional_fields = {
            k: v for k, v in resource_data.items() 
            if k in ['publish_date', 'access_notes', 'resource_vector', 'last_updated']
        }
        
        query = """
        MERGE (r:Resource {url: $url})
        ON CREATE SET 
            r.url_hash = $url_hash,
            r.url = $url,
            r.content_hash = $content_hash,
            r.title = $title,
            r.doc_type = $doc_type,
            r.category = $category,
            r.summary = $summary,
            r.scraped_at = $scraped_at,
            r.language = $language,
            r += $optional_fields,
            r.created_at = datetime()
        ON MATCH SET
            r.url_hash = $url_hash,
            r.url = $url,
            r.content_hash = $content_hash,
            r.title = $title,
            r.doc_type = $doc_type,
            r.category = $category,
            r.summary = $summary,
            r.scraped_at = $scraped_at,
            r.language = $language,
            r += $optional_fields,
            r.last_updated = datetime()
        RETURN r
        """

        result = self.client.execute_write(query, {
            "url": resource.url,
            "url_hash": resource.url_hash,
            "content_hash": resource.content_hash,
            "title": resource.title,
            "doc_type": resource.doc_type,
            "category": resource.category,
            "summary": resource.summary,
            "scraped_at": resource.scraped_at.isoformat() if isinstance(resource.scraped_at, datetime) else resource.scraped_at,
            "language": resource.language,
            "optional_fields": optional_fields
        })
        self.logger.info(f"Created/updated Resource: {resource.title}")
        return result[0] if result else None
    
    def get_resource(self, url: str) -> Optional[Dict[str, Any]]:
        """Get a resource by URL."""
        query = "MATCH (r:Resource {url: $url}) RETURN r"
        result = self.client.execute_query(query, {"url": url})
        return result[0] if result else None
    
    def list_resources(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List resources with optional limit."""
        query = "MATCH (r:Resource) RETURN r LIMIT $limit"
        return self.client.execute_query(query, {"limit": limit})
    
    # ========== Topic Operations ==========
    
    def create_topic(self, topic: Topic) -> Optional[Dict[str, Any]]:
        """
        Create or get a Topic node.
        Explicitly sets required fields and dynamically handles optional ones.
        
        Args:
            topic: Topic model instance
        Returns:
            Created/updated topic node data
        """
        topic_data = topic.to_dict()
        
        # Extract optional fields that may or may not be present
        optional_fields = {
            k: v for k, v in topic_data.items() 
            if k in ['topic_vector']
        }
        
        query = """
        MERGE (t:Topic {topic_id: $topic_id})
        ON CREATE SET 
            t.name = $name,
            t.aliases = $aliases,
            t += $optional_fields,
            t.created_at = datetime()
        ON MATCH SET
            t.name = $name,
            t.aliases = $aliases,
            t += $optional_fields,
            t.last_updated = datetime()
        RETURN t
        """
        result = self.client.execute_write(query, {
            "topic_id": topic.topic_id,
            "name": topic.name,
            "aliases": topic.aliases,
            "optional_fields": optional_fields
        })
        return result[0] if result else None
    
    def link_topic_to_parent(self, child_topic_id: str, parent_topic_id: str, relationship: TopicSubtopicOf):
        """
        Create SUBTOPIC_OF relationship between two topics (child -> parent).
        Args:
            child_topic_id: ID of the child topic
            parent_topic_id: ID of the parent topic
            relationship: TopicSubtopicOf relationship model with properties
        """
        rel_props = relationship.to_dict()
        query = """
        MATCH (child:Topic {topic_id: $child_topic_id})
        MATCH (parent:Topic {topic_id: $parent_topic_id})
        MERGE (child)-[rel:SUBTOPIC_OF]->(parent)
        SET rel += $properties
        RETURN rel
        """
        self.client.execute_write(query, {
            "child_topic_id": child_topic_id,
            "parent_topic_id": parent_topic_id,
            "properties": rel_props
        })
    
    def get_topic_hierarchy(self, topic_id: str) -> List[Dict[str, Any]]:
        """
        Get the full hierarchy chain from a topic to its root parent.
        
        Args:
            topic_id: ID of the starting topic
            
        Returns:
            List of topics from child to root parent
        """
        query = """
        MATCH path = (t:Topic {topic_id: $topic_id})-[:SUBTOPIC_OF*0..]->(parent:Topic)
        RETURN nodes(path) as hierarchy
        ORDER BY length(path) DESC
        LIMIT 1
        """
        result = self.client.execute_query(query, {"topic_id": topic_id})
        return result[0].get('hierarchy', []) if result else []
    
    def get_topic_subtopics(self, topic_id: str, max_depth: int = 1) -> List[Dict[str, Any]]:
        """
        Get all subtopics of a topic up to a certain depth.
        
        Args:
            topic_id: ID of the parent topic
            max_depth: Maximum depth to traverse (1 = direct children only)
            
        Returns:
            List of subtopic nodes
        """
        query = f"""
        MATCH (parent:Topic {{topic_id: $topic_id}})<-[:SUBTOPIC_OF*1..{max_depth}]-(subtopic:Topic)
        RETURN subtopic
        """
        return self.client.execute_query(query, {"topic_id": topic_id})
    
    def list_topics(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List all topics."""
        query = "MATCH (t:Topic) RETURN t LIMIT $limit"
        return self.client.execute_query(query, {"limit": limit})
    
    # ========== Standard Operations ==========
    
    def create_standard(self, standard: Standard) -> Optional[Dict[str, Any]]:
        """
        Create or get a Standard node.
        Explicitly sets required fields (no optional fields for Standard).
        
        Args:
            standard: Standard model instance
            
        Returns:
            Created/updated standard node data
        """
        query = """
        MERGE (s:Standard {standard_id: $standard_id})
        ON CREATE SET 
            s.identifier = $identifier,
            s.name = $name,
            s.aliases = $aliases,
            s.created_at = datetime()
        ON MATCH SET
            s.identifier = $identifier,
            s.name = $name,
            s.aliases = $aliases,
            s.last_updated = datetime()
        RETURN s
        """
        result = self.client.execute_write(query, {
            "standard_id": standard.standard_id,
            "identifier": standard.identifier,
            "name": standard.name,
            "aliases": standard.aliases
        })
        return result[0] if result else None
    
    def create_standard_edition(self, edition: StandardEdition) -> Optional[Dict[str, Any]]:
        """
        Create or get a Standard Edition node.
        Explicitly sets required fields and dynamically handles optional ones.
        
        Args:
            edition: StandardEdition model instance
            
        Returns:
            Created/updated standard edition node data
        """
        edition_data = edition.to_dict()
        
        # Extract optional fields that may or may not be present
        optional_fields = {
            k: v for k, v in edition_data.items() 
            if k in ['status', 'published_at', 'url']
        }
        
        query = """
        MERGE (se:StandardEdition {edition_id: $edition_id})
        ON CREATE SET 
            se.identifier = $identifier,
            se.name = $name,
            se.version = $version,
            se += $optional_fields,
            se.created_at = datetime()
        ON MATCH SET
            se.identifier = $identifier,
            se.name = $name,
            se.version = $version,
            se += $optional_fields,
            se.last_updated = datetime()
        RETURN se
        """
        result = self.client.execute_write(query, {
            "edition_id": edition.edition_id,
            "identifier": edition.identifier,
            "name": edition.name,
            "version": edition.version,
            "optional_fields": optional_fields
        })
        return result[0] if result else None
    
    def list_standards(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List all standards."""
        query = "MATCH (s:Standard) RETURN s LIMIT $limit"
        return self.client.execute_query(query, {"limit": limit})
    
    # ========== Organization Operations ==========
    
    def create_organization(self, org: Organization) -> Optional[Dict[str, Any]]:
        """
        Create or update an Organization node.
        Explicitly sets required fields and dynamically handles optional ones.
        
        Args:
            org: Organization model instance
            
        Returns:
            Created/updated organization node data
        """
        org_data = org.to_dict()
        
        # Extract optional fields that may or may not be present
        optional_fields = {
            k: v for k, v in org_data.items() 
            if k in ['homepage_url']
        }
        
        query = """
        MERGE (o:Organization {org_id: $org_id})
        ON CREATE SET 
            o.name = $name,
            o.type = $type,
            o += $optional_fields,
            o.created_at = datetime()
        ON MATCH SET
            o.name = $name,
            o.type = $type,
            o += $optional_fields,
            o.last_updated = datetime()
        RETURN o
        """
        result = self.client.execute_write(query, {
            "org_id": org.org_id,
            "name": org.name,
            "type": org.type,
            "optional_fields": optional_fields
        })
        self.logger.info(f"Created/updated Organization: {org.name}")
        return result[0] if result else None
    
    def get_organization(self, org_id: str) -> Optional[Dict[str, Any]]:
        """Get an organization by org_id."""
        query = "MATCH (o:Organization {org_id: $org_id}) RETURN o"
        result = self.client.execute_query(query, {"org_id": org_id})
        return result[0] if result else None
    
    def list_organizations(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List all organizations."""
        query = "MATCH (o:Organization) RETURN o LIMIT $limit"
        return self.client.execute_query(query, {"limit": limit})
    
    # ========== DataSource Operations ==========
    
    def create_datasource(self, datasource: DataSource) -> Optional[Dict[str, Any]]:
        """
        Create or update a DataSource node.
        Explicitly sets required fields and dynamically handles optional ones.
        
        Args:
            datasource: DataSource model instance
            
        Returns:
            Created/updated datasource node data
        """
        datasource_data = datasource.to_dict()
        
        # Extract optional fields that may or may not be present
        optional_fields = {
            k: v for k, v in datasource_data.items() 
            if k in ['fetch_url']
        }
        
        query = """
        MERGE (ds:DataSource {source_id: $source_id})
        ON CREATE SET 
            ds.name = $name,
            ds.source_type = $source_type,
            ds += $optional_fields,
            ds.created_at = datetime()
        ON MATCH SET
            ds.name = $name,
            ds.source_type = $source_type,
            ds += $optional_fields,
            ds.last_updated = datetime()
        RETURN ds
        """
        result = self.client.execute_write(query, {
            "source_id": datasource.source_id,
            "name": datasource.name,
            "source_type": datasource.source_type,
            "optional_fields": optional_fields
        })
        self.logger.info(f"Created/updated DataSource: {datasource.name}")
        return result[0] if result else None
    
    def get_datasource(self, source_id: str) -> Optional[Dict[str, Any]]:
        """Get a data source by source_id."""
        query = "MATCH (ds:DataSource {source_id: $source_id}) RETURN ds"
        result = self.client.execute_query(query, {"source_id": source_id})
        return result[0] if result else None
    
    def list_datasources(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List all data sources."""
        query = "MATCH (ds:DataSource) RETURN ds LIMIT $limit"
        return self.client.execute_query(query, {"limit": limit})
    
    # ========== Relationship Operations ==========

    def link_datasource_to_organization(self, source_id: str, org_id: str, relationship: DataSourceBelongsTo):
        """
        Create BELONGS_TO relationship between DataSource and Organization.
        
        Args:
            source_id: ID of the data source
            org_id: ID of the organization
            relationship: DataSourceBelongsTo relationship model with properties
        """
        rel_props = relationship.to_dict()
        query = """
        MATCH (ds:DataSource {source_id: $source_id})
        MATCH (o:Organization {org_id: $org_id})
        MERGE (ds)-[rel:BELONGS_TO]->(o)
        SET rel += $properties
        RETURN rel
        """
        self.client.execute_write(query, {
            "source_id": source_id,
            "org_id": org_id,
            "properties": rel_props
        })
        self.logger.info(f"Linked DataSource '{source_id}' to Organization '{org_id}'")
    
    def link_resource_to_topic(self, resource_url: str, topic_id: str, relationship: ResourceRelatesToTopic):
        """
        Create RELATES_TO relationship between Resource and Topic.
        Args:
            resource_url: URL of the resource
            topic_id: ID of the topic (slugified identifier)
            relationship: ResourceRelatesToTopic relationship model with properties
        """
        rel_props = relationship.to_dict()
        query = """
        MATCH (r:Resource {url: $resource_url})
        MATCH (t:Topic {topic_id: $topic_id})
        MERGE (r)-[rel:RELATES_TO]->(t)
        SET rel += $properties
        RETURN rel
        """
        self.client.execute_write(query, {
            "resource_url": resource_url,
            "topic_id": topic_id,
            "properties": rel_props
        })
    
    def link_resource_to_standard(self, resource_url: str, standard_id: str, relationship: ResourceReferencesStandard):
        """
        Create REFERENCES_STANDARD relationship between Resource and Standard.
        Args:
            resource_url: URL of the resource
            standard_id: ID of the standard (standard_id field)
            relationship: ResourceReferencesStandard relationship model with properties
        """
        rel_props = relationship.to_dict()
        query = """
        MATCH (r:Resource {url: $resource_url})
        MATCH (s:Standard {standard_id: $standard_id})
        MERGE (r)-[rel:REFERENCES_STANDARD]->(s)
        SET rel += $properties
        RETURN rel
        """
        self.client.execute_write(query, {
            "resource_url": resource_url,
            "standard_id": standard_id,
            "properties": rel_props
        })
    
    def link_resource_to_standard_edition(self, resource_url: str, edition_id: str, relationship: ResourceReferencesEdition):
        """
        Create REFERENCES_EDITION relationship between Resource and Standard Edition.
        Args:
            resource_url: URL of the resource
            edition_id: ID of the standard edition (edition_id field)
            relationship: ResourceReferencesEdition relationship model with properties
        """
        rel_props = relationship.to_dict()
        query = """
        MATCH (r:Resource {url: $resource_url})
        MATCH (se:StandardEdition {edition_id: $edition_id})
        MERGE (r)-[rel:REFERENCES_EDITION]->(se)
        SET rel += $properties
        RETURN rel
        """
        self.client.execute_write(query, {
            "resource_url": resource_url,
            "edition_id": edition_id,
            "properties": rel_props
        })
    
    def link_standard_edition_to_standard(self, edition_name: str, standard_name: str, relationship: EditionVersionOf):
        """
        Create VERSION_OF relationship between Standard Edition and Standard.
        Args:
            edition_name: Name of the standard edition
            standard_name: Name of the standard
            relationship: EditionVersionOf relationship model with properties
        """
        rel_props = relationship.to_dict()
        query = """
        MATCH (se:StandardEdition {name: $edition_name})
        MATCH (s:Standard {name: $standard_name})
        MERGE (se)-[rel:VERSION_OF]->(s)
        SET rel += $properties
        RETURN rel
        """
        self.client.execute_write(query, {
            "edition_name": edition_name,
            "standard_name": standard_name,
            "properties": rel_props
        })
    
    def link_resource_to_datasource(self, resource_url: str, datasource_id: str, relationship: ResourceIngestedFrom):
        """
        Create INGESTED_FROM relationship between Resource and DataSource.
        Args:
            resource_url: URL of the resource
            datasource_id: ID of the data source (source_id field)
            relationship: ResourceIngestedFrom relationship model with properties
        """
        rel_props = relationship.to_dict()
        query = """
        MATCH (r:Resource {url: $resource_url})
        MATCH (ds:DataSource {source_id: $datasource_id})
        MERGE (r)-[rel:INGESTED_FROM]->(ds)
        SET rel += $properties
        RETURN rel
        """
        self.client.execute_write(query, {
            "resource_url": resource_url,
            "datasource_id": datasource_id,
            "properties": rel_props
        })
    
    # ========== Bulk Insert Operations ==========
    
    def insert_entities(
        self,
        resource: Resource,
        topics: Optional[List[Tuple[Topic, ResourceRelatesToTopic]]] = None,
        standards: Optional[List[Tuple[Standard, ResourceReferencesStandard]]] = None,
        standard_editions: Optional[List[Tuple[StandardEdition, ResourceReferencesEdition]]] = None,
        datasource_id: Optional[str] = None
    ):
        """
        Insert all entities and relationships into the graph.
        This is a type-safe method for bulk inserting a complete set of entities.
        Creates relationships with confidence and relevance scores from metadata.
        
        Args:
            resource: Resource model instance
            topics: List of tuples (Topic model, ResourceRelatesToTopic relationship)
            standards: List of tuples (Standard model, ResourceReferencesStandard relationship)
            standard_editions: List of tuples (StandardEdition model, ResourceReferencesEdition relationship)
            datasource_id: ID of the data source (optional)
        """
        # Create Resource node
        self.create_resource(resource)
        
        # Link to DataSource if provided
        if datasource_id:
            try:
                source_rel = ResourceIngestedFrom()
                self.link_resource_to_datasource(resource.url, datasource_id, source_rel)
                self.logger.info(f"Linked resource to data source: {datasource_id}")
            except Exception as e:
                self.logger.warning(f"Could not link to data source {datasource_id}: {e}")
        
        # Create and link Topics with scores
        if topics:
            for topic, rel in topics:
                self.create_topic(topic)
                self.link_resource_to_topic(resource.url, topic.topic_id, rel)
            self.logger.info(f"Linked {len(topics)} topics to resource with scores")
        
        # Create and link Standards with confidence
        if standards:
            for standard, rel in standards:
                self.create_standard(standard)
                self.link_resource_to_standard(resource.url, standard.standard_id, rel)
            self.logger.info(f"Linked {len(standards)} standards to resource with confidence")
        
        # Create and link Standard Editions with confidence
        if standard_editions:
            for edition, rel in standard_editions:
                self.create_standard_edition(edition)
                self.link_resource_to_standard_edition(resource.url, edition.edition_id, rel)
            self.logger.info(f"Linked {len(standard_editions)} standard editions to resource with confidence")
    
    # ========== Query Operations ==========
    
    def get_resource_with_relationships(self, url: str) -> Optional[Dict[str, Any]]:
        """
        Get a resource with all its relationships.
        
        Returns:
            Dictionary with resource and related entities
        """
        query = """
        MATCH (r:Resource {url: $url})
        OPTIONAL MATCH (r)-[:COVERS_TOPIC]->(t:Topic)
        OPTIONAL MATCH (r)-[:REFERENCES_STANDARD]->(s:Standard)
        OPTIONAL MATCH (r)-[:REFERENCES_EDITION]->(se:StandardEdition)
        OPTIONAL MATCH (r)-[:FROM_SOURCE]->(ds:DataSource)
        RETURN r, 
               collect(DISTINCT t) as topics,
               collect(DISTINCT s) as standards,
               collect(DISTINCT se) as standard_editions,
               collect(DISTINCT ds) as data_sources
        """
        result = self.client.execute_query(query, {"url": url})
        return result[0] if result else None
    
    def search_resources_by_topic(self, topic_name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Find all resources covering a specific topic."""
        query = """
        MATCH (r:Resource)-[:COVERS_TOPIC]->(t:Topic {name: $topic_name})
        RETURN r
        LIMIT $limit
        """
        return self.client.execute_query(query, {"topic_name": topic_name, "limit": limit})
    
    def search_resources_by_standard(self, standard_name: str, limit: int = 100) -> List[Dict[str, Any]]:
        """Find all resources referencing a specific standard."""
        query = """
        MATCH (r:Resource)-[:REFERENCES_STANDARD]->(s:Standard {name: $standard_name})
        RETURN r
        LIMIT $limit
        """
        return self.client.execute_query(query, {"standard_name": standard_name, "limit": limit})
