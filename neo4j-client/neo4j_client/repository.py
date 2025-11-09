"""Repository for managing knowledge graph operations."""

from typing import Dict, Any, List, Optional
import logging
from .client import Neo4jClient


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
    
    # ========== Resource Operations ==========
    
    def create_resource(self, resource_data: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Create or update a Resource node.
        
        Args:
            resource_data: Resource data dictionary with keys: url, title, resource_type, 
                          summary, source, publish_date, timestamp, key_technologies,
                          industry_sectors, use_cases
            
        Returns:
            Created/updated resource node data
        """
        query = """
        MERGE (r:Resource {url: $url})
        ON CREATE SET 
            r.title = $title,
            r.resource_type = $resource_type,
            r.summary = $summary,
            r.source = $source,
            r.publish_date = $publish_date,
            r.timestamp = $timestamp,
            r.key_technologies = $key_technologies,
            r.industry_sectors = $industry_sectors,
            r.use_cases = $use_cases,
            r.created_at = datetime()
        ON MATCH SET
            r.title = $title,
            r.resource_type = $resource_type,
            r.summary = $summary,
            r.source = $source,
            r.publish_date = $publish_date,
            r.timestamp = $timestamp,
            r.key_technologies = $key_technologies,
            r.industry_sectors = $industry_sectors,
            r.use_cases = $use_cases,
            r.updated_at = datetime()
        RETURN r
        """
        
        result = self.client.execute_write(query, resource_data)
        self.logger.info(f"Created/updated Resource: {resource_data.get('title', 'Unknown')}")
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
    
    def create_topic(self, topic_name: str) -> Optional[Dict[str, Any]]:
        """Create or get a Topic node."""
        query = """
        MERGE (t:Topic {name: $name})
        ON CREATE SET t.created_at = datetime()
        RETURN t
        """
        result = self.client.execute_write(query, {"name": topic_name})
        return result[0] if result else None
    
    def list_topics(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List all topics."""
        query = "MATCH (t:Topic) RETURN t LIMIT $limit"
        return self.client.execute_query(query, {"limit": limit})
    
    # ========== Standard Operations ==========
    
    def create_standard(self, standard_name: str, **properties) -> Optional[Dict[str, Any]]:
        """Create or get a Standard node."""
        query = """
        MERGE (s:Standard {name: $name})
        ON CREATE SET s.created_at = datetime()
        RETURN s
        """
        result = self.client.execute_write(query, {"name": standard_name})
        return result[0] if result else None
    
    def create_standard_edition(self, edition_name: str, version: str = "", **properties) -> Optional[Dict[str, Any]]:
        """Create or get a Standard Edition node."""
        query = """
        MERGE (se:StandardEdition {name: $name})
        ON CREATE SET 
            se.version = $version,
            se.created_at = datetime()
        RETURN se
        """
        result = self.client.execute_write(query, {"name": edition_name, "version": version})
        return result[0] if result else None
    
    def list_standards(self, limit: int = 100) -> List[Dict[str, Any]]:
        """List all standards."""
        query = "MATCH (s:Standard) RETURN s LIMIT $limit"
        return self.client.execute_query(query, {"limit": limit})
    
    # ========== Organization Operations ==========
    
    def create_organization(self, name: str, description: str = "") -> Optional[Dict[str, Any]]:
        """Create or update an Organization node."""
        query = """
        MERGE (o:Organization {name: $name})
        ON CREATE SET 
            o.description = $description,
            o.created_at = datetime()
        ON MATCH SET
            o.description = $description
        RETURN o
        """
        result = self.client.execute_write(query, {"name": name, "description": description})
        return result[0] if result else None
    
    # ========== Relationship Operations ==========
    
    def link_resource_to_topic(self, resource_url: str, topic_name: str):
        """Create COVERS_TOPIC relationship between Resource and Topic."""
        query = """
        MATCH (r:Resource {url: $resource_url})
        MATCH (t:Topic {name: $topic_name})
        MERGE (r)-[:COVERS_TOPIC]->(t)
        """
        self.client.execute_write(query, {"resource_url": resource_url, "topic_name": topic_name})
    
    def link_resource_to_standard(self, resource_url: str, standard_name: str):
        """Create REFERENCES_STANDARD relationship between Resource and Standard."""
        query = """
        MATCH (r:Resource {url: $resource_url})
        MATCH (s:Standard {name: $standard_name})
        MERGE (r)-[:REFERENCES_STANDARD]->(s)
        """
        self.client.execute_write(query, {"resource_url": resource_url, "standard_name": standard_name})
    
    def link_resource_to_standard_edition(self, resource_url: str, edition_name: str):
        """Create REFERENCES_EDITION relationship between Resource and Standard Edition."""
        query = """
        MATCH (r:Resource {url: $resource_url})
        MATCH (se:StandardEdition {name: $edition_name})
        MERGE (r)-[:REFERENCES_EDITION]->(se)
        """
        self.client.execute_write(query, {"resource_url": resource_url, "edition_name": edition_name})
    
    def link_standard_edition_to_standard(self, edition_name: str, standard_name: str):
        """Create VERSION_OF relationship between Standard Edition and Standard."""
        query = """
        MATCH (se:StandardEdition {name: $edition_name})
        MATCH (s:Standard {name: $standard_name})
        MERGE (se)-[:VERSION_OF]->(s)
        """
        self.client.execute_write(query, {"edition_name": edition_name, "standard_name": standard_name})
    
    def link_resource_to_datasource(self, resource_url: str, datasource_name: str):
        """Create FROM_SOURCE relationship between Resource and DataSource."""
        query = """
        MATCH (r:Resource {url: $resource_url})
        MATCH (ds:DataSource {name: $datasource_name})
        MERGE (r)-[:FROM_SOURCE]->(ds)
        """
        self.client.execute_write(query, {"resource_url": resource_url, "datasource_name": datasource_name})
    
    # ========== Bulk Insert Operations ==========
    
    def insert_entities(self, entities: Dict[str, Any]):
        """
        Insert all entities and relationships into the graph.
        
        This is a convenience method for bulk inserting a complete set of entities.
        
        Args:
            entities: Dictionary containing:
                - resource: Dict with resource data
                - topics: List of dicts with topic data
                - standards: List of dicts with standard data
                - standard_editions: List of dicts with standard edition data
        """
        # Create Resource node
        resource_data = entities["resource"]
        self.create_resource(resource_data)
        resource_url = resource_data["url"]
        
        # Create and link Topics
        for topic_data in entities.get("topics", []):
            self.create_topic(topic_data["name"])
            self.link_resource_to_topic(resource_url, topic_data["name"])
        
        self.logger.info(f"Linked {len(entities.get('topics', []))} topics to resource")
        
        # Create and link Standards
        for standard_data in entities.get("standards", []):
            self.create_standard(standard_data["name"])
            self.link_resource_to_standard(resource_url, standard_data["name"])
        
        self.logger.info(f"Linked {len(entities.get('standards', []))} standards to resource")
        
        # Create and link Standard Editions
        for edition_data in entities.get("standard_editions", []):
            self.create_standard_edition(edition_data["name"], edition_data.get("version", ""))
            self.link_resource_to_standard_edition(resource_url, edition_data["name"])
            
            # Try to link edition to parent standard if we can infer it
            edition_name = edition_data["name"]
            for standard_data in entities.get("standards", []):
                standard_name = standard_data["name"]
                # Simple heuristic: if standard name is in edition name, link them
                if standard_name.lower() in edition_name.lower():
                    self.link_standard_edition_to_standard(edition_name, standard_name)
        
        self.logger.info(f"Linked {len(entities.get('standard_editions', []))} standard editions to resource")
        
        # Link to DataSource based on source field
        source = resource_data.get("source", "").lower().replace(" ", "-")
        if source:
            try:
                self.link_resource_to_datasource(resource_url, source)
                self.logger.info(f"Linked resource to data source: {source}")
            except Exception as e:
                self.logger.warning(f"Could not link to data source {source}: {e}")
    
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
