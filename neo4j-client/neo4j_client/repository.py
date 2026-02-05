"""Repository for managing knowledge graph operations."""

from typing import Dict, Any, List, Optional
import logging
import json
from pathlib import Path
from datetime import datetime, date, timedelta
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
        Initialize base organizations, data sources, and common topics from initial_data.json.
        Creates organizations, data sources, topics, and their relationships.
        """
        self.logger.info("Initializing base data (organizations, data sources, and topics)...")
        
        json_path = Path(__file__).parent / "initial_data.json"
        if not json_path.exists():
            self.logger.warning(f"Initial data file not found: {json_path}")
            return
        
        with open(json_path, "r") as f:
            data = json.load(f)
        
        orgs = data.get("organizations", [])
        data_sources = data.get("data_sources", [])
        topics = data.get("topics", [])
        
        # Create organizations
        for org_dict in orgs:
            org = Organization(**org_dict)
            self.create_node(org)
        
        # Create data sources and link to organizations
        for ds_dict in data_sources:
            ds = DataSource(**ds_dict)
            org_id = ds_dict.get("org_id")
            
            # Create the data source
            self.create_node(ds)
            
            # Link data source to organization if org_id is provided
            if org_id:
                ds_to_org_rel = DataSourceBelongsToOrganization(source_id=ds.datasource_id, target_id=org_id)
                self.create_relationship(ds_to_org_rel)
        
        # Create common topics with aliases
        for topic_dict in topics:
            topic = Topic(**topic_dict)
            self.create_node(topic)
        
        self.logger.info(f"Base data initialization complete ({len(orgs)} organizations, {len(data_sources)} data sources, {len(topics)} topics)")

    def _log_document_change(
        self,
        url_hash: str,
        old_content_hash: Optional[str],
        new_content_hash: str,
        old_publish_date: Optional[datetime],
        new_publish_date: Optional[datetime],
        old_title: Optional[str],
        new_title: str,
        changed_fields: List[str]
    ) -> bool:
        """
        Log document changes to PostgreSQL document_change_log table.
        
        Args:
            url_hash: Unique identifier for the document
            old_content_hash: Previous content hash
            new_content_hash: New content hash
            old_publish_date: Previous publish date
            new_publish_date: New publish date
            old_title: Previous title
            new_title: New title
            changed_fields: List of field names that changed
            
        Returns:
            True if logged successfully, False otherwise
        """
        try:
            import psycopg2
            import psycopg2.extras
            
            pg_dsn = os.getenv(
                "PG_DSN",
                "postgresql://aurora:aurora_password@localhost:5432/aurora"
            )
            
            conn = psycopg2.connect(pg_dsn)
            conn.autocommit = True
            
            with conn.cursor() as cur:
                query = """
                INSERT INTO document_change_log (
                    url_hash,
                    old_content_hash,
                    new_content_hash,
                    old_publish_date,
                    new_publish_date,
                    old_title,
                    new_title,
                    changed_fields
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """
                
                # Convert datetime to ISO strings for PostgreSQL
                old_pub_str = old_publish_date.isoformat() if old_publish_date else None
                new_pub_str = new_publish_date.isoformat() if new_publish_date else None
                
                cur.execute(query, (
                    url_hash,
                    old_content_hash,
                    new_content_hash,
                    old_pub_str,
                    new_pub_str,
                    old_title,
                    new_title,
                    json.dumps(changed_fields)
                ))
            
            conn.close()
            self.logger.info(f"Logged document change for {url_hash}: {changed_fields}")
            return True
            
        except Exception as e:
            self.logger.warning(f"Failed to log document change: {e}")
            return False

    def create_node(self, node: Node) -> Optional[Dict[str, Any]]:
        """
        General method to create or update any node type in Neo4j.
        Uses the class name as the label and the first string field as the unique identifier.
        Subclasses can override get_node_label and get_id_field for custom behavior.
        
        Special handling for Resource nodes:
        - Automatically creates INGESTED_FROM relationship to the DataSource
        - Detects content changes and logs them to PostgreSQL
        - Sets content_changed_at when content_hash differs
        
        Args:
            node: Node model instance
        Returns:
            Created/updated node data
        """
        node_data = node.to_dict()
        # Determine label and id field
        label = node.node_label
        id_field = node.id_field

        # Special handling for Resource nodes - detect changes
        if label == "Resource":
            # First, fetch existing node to compare
            fetch_query = f"""
            MATCH (n:{label} {{{id_field}: $id_value}})
            RETURN n.content_hash as old_content_hash,
                   n.publish_date as old_publish_date,
                   n.title as old_title
            """
            existing = self.client.execute_query(fetch_query, {"id_value": node_data[id_field]})
            
            if existing:
                # Node exists - check for changes
                old_data = existing[0]
                changed_fields = []
                
                # Check content_hash
                if old_data.get('old_content_hash') != node_data.get('content_hash'):
                    changed_fields.append('content_hash')
                
                # Check publish_date
                old_pub = old_data.get('old_publish_date')
                new_pub = node_data.get('publish_date')
                if old_pub != new_pub:
                    changed_fields.append('publish_date')
                
                # Check title
                if old_data.get('old_title') != node_data.get('title'):
                    changed_fields.append('title')
                
                # If changes detected, log them and set content_changed_at
                if changed_fields:
                    self._log_document_change(
                        url_hash=node_data[id_field],
                        old_content_hash=old_data.get('old_content_hash'),
                        new_content_hash=node_data.get('content_hash'),
                        old_publish_date=old_data.get('old_publish_date'),
                        new_publish_date=new_pub,
                        old_title=old_data.get('old_title'),
                        new_title=node_data.get('title'),
                        changed_fields=changed_fields
                    )
                    # Set content_changed_at to current time
                    node_data['content_changed_at'] = datetime.now().isoformat()

        # Prepare query and parameters
        # Set both created_at and last_updated on create, only last_updated on match
        # Special handling for Topic nodes: merge aliases instead of replacing them
        if label == "Topic":
            query = f"""
            MERGE (n:{label} {{{id_field}: $id_value}})
            ON CREATE SET n += $properties, n.created_at = datetime(), n.last_updated = datetime()
            ON MATCH SET 
                n.name = $properties.name,
                n.classification = $properties.classification,
                n.description = coalesce($properties.description, n.description),
                n.identifier = coalesce($properties.identifier, n.identifier),
                n.issuer = coalesce($properties.issuer, n.issuer),
                n.created_by = coalesce(n.created_by, $properties.created_by),
                n.aliases = CASE 
                    WHEN $properties.aliases IS NOT NULL AND size($properties.aliases) > 0 
                    THEN [alias IN (coalesce(n.aliases, []) + $properties.aliases) | toLower(alias)] 
                    ELSE coalesce(n.aliases, [])
                END,
                n.last_updated = datetime()
            WITH n
            // Deduplicate aliases (case-insensitive)
            WITH n, [alias IN n.aliases | toLower(alias)] as lower_aliases
            WITH n, reduce(unique = [], alias IN lower_aliases | 
                CASE WHEN NOT toLower(alias) IN [x IN unique | toLower(x)] 
                THEN unique + [alias] 
                ELSE unique 
                END
            ) as deduped_aliases
            SET n.aliases = deduped_aliases
            RETURN n
            """
        else:
            query = f"""
            MERGE (n:{label} {{{id_field}: $id_value}})
            ON CREATE SET n += $properties, n.created_at = datetime(), n.last_updated = datetime()
            ON MATCH SET n += $properties, n.last_updated = datetime()
            RETURN n
            """
        
        params = {
            "id_value": node_data[id_field],
            "properties": node_data
        }
        result = self.client.execute_write(query, params)
        self.logger.debug(f"Created/updated {label}: {node_data.get(id_field)}")
        
        # For Resource nodes, automatically create the INGESTED_FROM relationship
        if label == "Resource" and hasattr(node, 'datasource_id'):
            datasource_id = getattr(node, 'datasource_id')
            if datasource_id:
                try:
                    ingested_rel = ResourceIngestedFromDataSource(
                        source_id=node.url_hash,
                        target_id=datasource_id
                    )
                    self.create_relationship(ingested_rel)
                except Exception as e:
                    self.logger.warning(f"Failed to create INGESTED_FROM relationship for Resource: {e}")
            
            # Also create INGESTED_IN relationship to batch if batch_id present
            batch_id = getattr(node, 'batch_id', None)
            if batch_id:
                try:
                    batch_rel = ResourceIngestedInBatch(
                        source_id=node.url_hash,
                        target_id=batch_id
                    )
                    self.create_relationship(batch_rel)
                except Exception as e:
                    self.logger.warning(f"Failed to create INGESTED_IN relationship for Resource: {e}")
        
        # For Event nodes, automatically create the INGESTED_FROM relationship
        if label == "Event" and hasattr(node, 'datasource_id'):
            datasource_id = getattr(node, 'datasource_id')
            if datasource_id:
                try:
                    ingested_rel = EventIngestedFromDataSource(
                        source_id=node.url_hash,
                        target_id=datasource_id
                    )
                    self.create_relationship(ingested_rel)
                except Exception as e:
                    self.logger.warning(f"Failed to create INGESTED_FROM relationship for Event: {e}")
            
            # Also create INGESTED_IN relationship to batch if batch_id present
            batch_id = getattr(node, 'batch_id', None)
            if batch_id:
                try:
                    batch_rel = EventIngestedInBatch(
                        source_id=node.url_hash,
                        target_id=batch_id
                    )
                    self.create_relationship(batch_rel)
                except Exception as e:
                    self.logger.warning(f"Failed to create INGESTED_IN relationship for Event: {e}")
        
        # Extract the node properties from the result (same as get_node)
        if result:
            return result[0].get("n", {})
        return None

    def get_node(self, node: Node) -> Optional[Dict[str, Any]]:
        """
        General method to retrieve any node type from Neo4j by its ID.
        Uses the node model's metadata to determine label and ID field.
        
        Args:
            node: Node model instance with the ID field populated
                  (e.g., Topic(topic_id="ai"), Person(person_id="john-doe"))
            
        Returns:
            Node data as dictionary, or None if not found
            
        Example:
            # Get a topic by ID
            topic_node = Topic(topic_id="artificial-intelligence", name="", classification="")
            topic_data = repo.get_node(topic_node)
            if topic_data:
                print(topic_data["name"])
            
            # Get a person by ID
            person_node = Person(person_id="jane-smith", name="")
            person_data = repo.get_node(person_node)
        """
        label = node.node_label
        id_field = node.id_field
        id_value = getattr(node, id_field)
        
        query = f"""
        MATCH (n:{label} {{{id_field}: $id_value}})
        RETURN n
        """
        
        result = self.client.execute_query(query, {"id_value": id_value})
        
        if result:
            # Neo4j returns the node object, extract its properties
            node_data = result[0].get("n", {})
            self.logger.debug(f"Retrieved {label} with {id_field}='{id_value}'")
            return node_data
        else:
            self.logger.debug(f"{label} with {id_field}='{id_value}' not found")
            return None

    def delete_node(self, node: Node) -> bool:
        """
        General method to delete any node type from Neo4j by its ID.
        Uses the node model's metadata to determine label and ID field.
        
        WARNING: This will also delete all relationships connected to this node.
        Neo4j requires detaching relationships before deleting a node.
        
        Args:
            node: Node model instance with the ID field populated
                  (e.g., Topic(topic_id="ai"), Person(person_id="john-doe"))
            
        Returns:
            True if node was deleted, False if node was not found
            
        Example:
            # Delete a topic by ID
            topic_node = Topic(topic_id="outdated-topic", name="", classification="")
            deleted = repo.delete_node(topic_node)
            if deleted:
                print("Topic deleted successfully")
            
            # Delete a person by ID
            person_node = Person(person_id="jane-smith", name="")
            repo.delete_node(person_node)
        """
        label = node.node_label
        id_field = node.id_field
        id_value = getattr(node, id_field)
        
        query = f"""
        MATCH (n:{label} {{{id_field}: $id_value}})
        DETACH DELETE n
        RETURN count(n) as deleted_count
        """
        
        result = self.client.execute_write(query, {"id_value": id_value})
        deleted = result[0].get("deleted_count", 0) if result else 0
        
        if deleted > 0:
            self.logger.debug(f"Deleted {label} with {id_field}='{id_value}' and all its relationships")
            return True
        else:
            self.logger.warning(f"{label} with {id_field}='{id_value}' not found, nothing deleted")
            return False

    def create_relationship(self, relationship: Relationship):
        """
        Generic method to create any relationship between two nodes.
        Uses metadata from the relationship class to automatically determine
        node labels, ID fields, and relationship type.
        
        The source_id and target_id in the relationship should contain the actual
        unique identifier values for matching the nodes (e.g., url for Resource,
        topic_id for Topic, org_id for Organization, person_id for Person, etc.).
        
        Args:
            relationship: Any Relationship model instance (contains source_id, target_id, and metadata)
            
        Example:
            rel = ResourceRelatesToTopic(
                source_id=resource.url,  # matches Resource.url
                target_id=topic.topic_id,  # matches Topic.topic_id
                confidence=0.95,
                relevance=0.85,
                evidence="Direct quote from the document",
                stance="supportive",
                stance_score=0.7
            )
            repo.create_relationship(rel)
            
            rel = PersonAffiliatedWithOrganization(
                source_id=person.person_id,  # matches Person.person_id
                target_id=org.org_id,  # matches Organization.org_id
                confidence=0.95,
                role="Chief Technology Officer",
                evidence="Jane Smith serves as CTO at..."
            )
            repo.create_relationship(rel)
        """
        rel_props = relationship.to_dict()
        
        query = f"""
        MATCH (source:{relationship.source_node_label} {{{relationship.source_id_field}: $source_id}})
        MATCH (target:{relationship.target_node_label} {{{relationship.target_id_field}: $target_id}})
        MERGE (source)-[rel:{relationship.relationship_label}]->(target)
        ON CREATE SET rel += $properties, rel.created_at = datetime()
        ON MATCH SET rel += $properties, rel.last_updated = datetime()
        RETURN rel
        """
        
        result = self.client.execute_write(query, {
            "source_id": relationship.source_id,
            "target_id": relationship.target_id,
            "properties": rel_props
        })
        
        if not result:
            # Relationship wasn't created - check which node is missing
            self.logger.warning(
                f"Could not create {relationship.relationship_label} relationship: "
                f"source {relationship.source_node_label}('{relationship.source_id}') or "
                f"target {relationship.target_node_label}('{relationship.target_id}') not found"
            )
        else:
            self.logger.debug(
                f"Created {relationship.relationship_label} relationship from "
                f"{relationship.source_node_label}('{relationship.source_id}') to "
                f"{relationship.target_node_label}('{relationship.target_id}')"
            )
    
    def delete_relationship(self, relationship: Relationship) -> bool:
        """
        Delete a specific relationship between two nodes.
        
        Uses metadata from the relationship class to automatically determine
        node labels, ID fields, and relationship type - mirrors create_relationship().
        
        Args:
            relationship: Any Relationship model instance (same as create_relationship)
            
        Returns:
            True if relationship was deleted, False otherwise
            
        Example:
            # Delete a topic hierarchy relationship
            rel = TopicEncompasses(
                source_id="software",
                target_id="web_development",
                reasoning="",  # Not needed for deletion
                confidence=0.0  # Not needed for deletion
            )
            self.delete_relationship(rel)
        """
        query = f"""
        MATCH (source:{relationship.source_node_label} {{{relationship.source_id_field}: $source_id}})
              -[rel:{relationship.relationship_label}]->
              (target:{relationship.target_node_label} {{{relationship.target_id_field}: $target_id}})
        DELETE rel
        RETURN count(rel) as deleted_count
        """
        
        params = {
            "source_id": relationship.source_id,
            "target_id": relationship.target_id
        }
        
        result = self.client.execute_write(query, params)
        deleted = result[0].get("deleted_count", 0) if result else 0
        
        if deleted > 0:
            self.logger.debug(
                f"Deleted {relationship.relationship_label} relationship: "
                f"{relationship.source_node_label}('{relationship.source_id}') -> "
                f"{relationship.target_node_label}('{relationship.target_id}')"
            )
            return True
        else:
            self.logger.warning(
                f"No {relationship.relationship_label} relationship found to delete: "
                f"{relationship.source_node_label}('{relationship.source_id}') -> "
                f"{relationship.target_node_label}('{relationship.target_id}')"
            )
            return False
    
    def get_relationship(self, relationship: Relationship) -> Optional[Dict[str, Any]]:
        """
        Retrieve a specific relationship between two nodes.
        
        Uses metadata from the relationship class to automatically determine
        node labels, ID fields, and relationship type - mirrors create_relationship().
        
        Args:
            relationship: Any Relationship model instance (same as create_relationship)
            
        Returns:
            Relationship data as dictionary, or None if not found
            
        Example:
            # Check if a topic hierarchy relationship exists
            rel = TopicEncompasses(
                source_id="software",
                target_id="web_development",
                reasoning="",  # Not needed for retrieval
                confidence=0.0  # Not needed for retrieval
            )
            rel_data = repo.get_relationship(rel)
            if rel_data:
                print(f"Confidence: {rel_data.get('confidence')}")
        """
        query = f"""
        MATCH (source:{relationship.source_node_label} {{{relationship.source_id_field}: $source_id}})
              -[rel:{relationship.relationship_label}]->
              (target:{relationship.target_node_label} {{{relationship.target_id_field}: $target_id}})
        RETURN rel
        """
        
        params = {
            "source_id": relationship.source_id,
            "target_id": relationship.target_id
        }
        
        result = self.client.execute_query(query, params)
        
        if result:
            rel_data = result[0].get("rel", {})
            self.logger.debug(
                f"Retrieved {relationship.relationship_label} relationship: "
                f"{relationship.source_node_label}('{relationship.source_id}') -> "
                f"{relationship.target_node_label}('{relationship.target_id}')"
            )
            return rel_data
        else:
            self.logger.debug(
                f"{relationship.relationship_label} relationship not found: "
                f"{relationship.source_node_label}('{relationship.source_id}') -> "
                f"{relationship.target_node_label}('{relationship.target_id}')"
            )
            return None
    
    def insert_entities(
        self,
        entities_dict: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Insert deduplicated nodes and relationships into the graph.
        
        This function takes the output from NodeDeduplicator.deduplicate_nodes() and creates/updates
        all nodes and relationships in Neo4j. Nodes are inserted first, then relationships.
        
        Args:
            entities_dict: Dictionary with structure (output from NodeDeduplicator.deduplicate_nodes):
                {
                    "nodes": {
                        "resource": resource_model,
                        "topics": [topic_models],
                        "people": [person_models],
                        "organizations": [org_models]
                    },
                    "relationships": [relationship_models]
                }
                
        Returns:
            Dictionary with insertion statistics:
                {
                    "nodes_created": {
                        "resource": 1,
                        "topics": 5,
                        "people": 3,
                        "organizations": 2
                    },
                    "relationships_created": 15,
                    "success": True
                }
        """
        nodes = entities_dict.get("nodes", {})
        relationships = entities_dict.get("relationships", [])
        
        stats = {
            "nodes_created": {
                "resource": 0,
                "topics": 0,
                "people": 0,
                "organizations": 0,
                "events": 0
            },
            "relationships_created": 0,
            "success": False
        }
        
        try:
            # Insert resource node
            if nodes.get("resource"):
                self.logger.debug(f"Inserting resource node...")
                self.create_node(nodes["resource"])
                stats["nodes_created"]["resource"] = 1
            
            # Insert topic nodes
            if nodes.get("topics"):
                self.logger.debug(f"Inserting {len(nodes['topics'])} topic nodes...")
                for topic in nodes["topics"]:
                    self.create_node(topic)
                    stats["nodes_created"]["topics"] += 1
            
            # Insert person nodes
            if nodes.get("people"):
                self.logger.debug(f"Inserting {len(nodes['people'])} person nodes...")
                for person in nodes["people"]:
                    self.create_node(person)
                    stats["nodes_created"]["people"] += 1
            
            # Insert organization nodes
            if nodes.get("organizations"):
                self.logger.debug(f"Inserting {len(nodes['organizations'])} organization nodes...")
                for org in nodes["organizations"]:
                    self.create_node(org)
                    stats["nodes_created"]["organizations"] += 1
            
            # Insert event nodes
            if nodes.get("events"):
                self.logger.debug(f"Inserting {len(nodes['events'])} event nodes...")
                for event in nodes["events"]:
                    self.create_node(event)
                    stats["nodes_created"]["events"] += 1
            
            # Insert relationships
            if relationships:
                self.logger.debug(f"Inserting {len(relationships)} relationships...")
                for rel in relationships:
                    self.create_relationship(rel)
                    stats["relationships_created"] += 1
            
            stats["success"] = True
            
            self.logger.info(
                f"Entity insertion complete. "
                f"Nodes: {stats['nodes_created']['resource']} resource, "
                f"{stats['nodes_created']['topics']} topics, "
                f"{stats['nodes_created']['people']} people, "
                f"{stats['nodes_created']['organizations']} organizations, "
                f"{stats['nodes_created']['events']} events. "
                f"Relationships: {stats['relationships_created']}"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to insert entities: {e}", exc_info=True)
            stats["success"] = False
            raise
        
        return stats
    
    # ========== Node Retrieval Operations ==========
    
    def get_all_nodes(self, node_type: type[Node]) -> List[Dict[str, Any]]:
        """
        General method to retrieve all nodes of a specific type from the knowledge graph.
        
        Uses the node class metadata to determine label and fields to return.
        Returns all properties of the nodes.
        
        Args:
            node_type: The Node class type (e.g., Topic, Person, Organization)
            
        Returns:
            List of node dictionaries with all their properties
            
        Example:
            # Get all topics
            topics = repo.get_all_nodes(Topic)
            for topic in topics:
                print(topic['name'])
            
            # Get all people
            people = repo.get_all_nodes(Person)
            
            # Get all organizations
            orgs = repo.get_all_nodes(Organization)
        """
        # Access class attributes directly from the class (not an instance)
        # Use __dict__ to get class attributes or model_fields for Pydantic v2
        label = node_type.model_fields['node_label'].default
        id_field = node_type.model_fields['id_field'].default
        
        query = f"""
        MATCH (n:{label})
        RETURN n
        ORDER BY n.{id_field}
        """
        
        results = self.client.execute_query(query)
        
        # Extract node properties from results
        nodes = [result.get("n", {}) for result in results]
        
        self.logger.info(f"Retrieved {len(nodes)} {label} nodes from knowledge graph")
        return nodes

    def count_nodes(self, node_type: type[Node]) -> int:
        """
        Count the total number of nodes of a specific type.
        
        More efficient than get_all_nodes when you only need the count.
        
        Args:
            node_type: The Node class type (e.g., Topic, Person, Organization)
            
        Returns:
            Total count of nodes of the specified type
            
        Example:
            topic_count = repo.count_nodes(Topic)
            print(f"Total topics: {topic_count}")
        """
        label = node_type.model_fields['node_label'].default
        
        query = f"""
        MATCH (n:{label})
        RETURN count(n) as count
        """
        
        results = self.client.execute_query(query)
        count = results[0].get("count", 0) if results else 0
        
        self.logger.debug(f"Counted {count} {label} nodes")
        return count

    def get_unorganized_topics(self) -> List[Dict[str, Any]]:
        """
        Retrieve topics that have no hierarchical relationships.
        
        Returns topics that are NOT involved in any ENCOMPASSES or SUBTOPIC_OF
        relationships (neither as source nor target). These are "orphan" topics
        that haven't been organized into the hierarchy yet.
        
        This is useful for incremental curation - only processing new topics
        instead of re-processing the entire knowledge graph.
        
        Returns:
            List of topic dictionaries without hierarchy relationships
            
        Example:
            unorganized = repo.get_unorganized_topics()
            print(f"Found {len(unorganized)} topics needing organization")
        """
        query = """
        MATCH (t:Topic)
        WHERE NOT (t)-[:ENCOMPASSES]-() 
          AND NOT (t)-[:SUBTOPIC_OF]-()
        RETURN t
        ORDER BY t.topic_id
        """
        
        results = self.client.execute_query(query)
        topics = [result.get("t", {}) for result in results]
        
        self.logger.info(f"Retrieved {len(topics)} unorganized topics (no hierarchy relationships)")
        return topics

    def get_events_by_datasource_and_date(
        self,
        datasource_id: str,
        target_date: str
    ) -> List[Dict[str, Any]]:
        """
        Retrieve events from a specific datasource that match a given date.
        
        An event matches if:
        - For single-day events (end_date is null): start_date equals target_date
        - For multi-day events: target_date falls within start_date to end_date range
        
        Args:
            datasource_id: The datasource_id to filter events by (e.g., "wfa_causeway_htf")
            target_date: The date to match in ISO format (YYYY-MM-DD)
            
        Returns:
            List of event dictionaries with all their properties
        """
        query = """
        MATCH (e:Event)
        WHERE e.datasource_id = $datasource_id
          AND date(datetime(e.start_date)) <= date($target_date)
          AND (e.end_date IS NULL OR date(datetime(e.end_date)) >= date($target_date))
        RETURN e
        ORDER BY e.start_date
        """
        
        results = self.client.execute_query(query, {
            "datasource_id": datasource_id,
            "target_date": target_date
        })
        
        events = [result.get("e", {}) for result in results]
        
        self.logger.debug(
            f"Found {len(events)} events for datasource '{datasource_id}' "
            f"matching date '{target_date}'"
        )
        return events

    def update_node_aliases(
        self,
        node_label: str,
        id_field: str,
        node_id: str,
        aliases: List[str]
    ) -> None:
        """
        Update the aliases field of a node in the graph.
        
        This is used during deduplication to merge aliases from duplicate nodes
        into the existing node.
        
        Args:
            node_label: Label of the node type (e.g., "Topic", "Person", "Organization")
            id_field: ID field name (e.g., "topic_id", "person_id", "org_id")
            node_id: The ID value of the node to update
            aliases: Complete list of aliases to set on the node
        """
        query = f"""
        MATCH (n:{node_label} {{{id_field}: $node_id}})
        SET n.aliases = $aliases,
            n.last_updated = datetime()
        RETURN n
        """
        
        self.client.execute_write(query, {
            "node_id": node_id,
            "aliases": aliases
        })
        
        self.logger.info(
            f"Updated aliases for {node_label} {id_field}='{node_id}': {len(aliases)} aliases"
        )

    def would_create_cycle(
        self, 
        source_topic_id: str, 
        target_topic_id: str
    ) -> bool:
        """
        Check if adding an ENCOMPASSES relationship would create a cycle in the hierarchy.
        
        A cycle would occur if there's already a path from target to source through
        ENCOMPASSES relationships. This ensures the hierarchy remains a DAG (Directed Acyclic Graph).
        
        Example of what we're preventing:
        - A ENCOMPASSES B (already exists)
        - B ENCOMPASSES C (already exists)
        - Adding C ENCOMPASSES A would create: A → B → C → A (cycle!)
        
        Args:
            source_topic_id: The topic that would encompass (broader topic)
            target_topic_id: The topic that would be encompassed (narrower topic)
            
        Returns:
            True if adding this relationship would create a cycle, False otherwise
        """
        # Check if there's already a path from target to source via ENCOMPASSES
        # If such a path exists, adding source->target would create a cycle
        # Use OPTIONAL MATCH to avoid warnings when ENCOMPASSES relationship type doesn't exist yet
        query = """
        OPTIONAL MATCH path = (target:Topic {topic_id: $target_id})
                              -[:ENCOMPASSES*]->(source:Topic {topic_id: $source_id})
        RETURN path IS NOT NULL as has_path
        LIMIT 1
        """
        
        params = {
            "source_id": source_topic_id,
            "target_id": target_topic_id
        }
        
        results = self.client.execute_query(query, params)
        
        if results and results[0].get("has_path"):
            self.logger.warning(
                f"Cycle detected: Path exists from {target_topic_id} to {source_topic_id}. "
                f"Cannot add reverse relationship."
            )
            return True
        
        return False

    def check_relationship_redundancy(
        self, 
        source_topic_id: str, 
        target_topic_id: str
    ) -> Dict[str, Any]:
        """
        Check if adding an ENCOMPASSES relationship would be redundant or conflicting.
        
        A relationship is redundant if it can be inferred from existing relationships.
        This implements comprehensive transitive reduction by checking three cases:
        
        Case 1 (Forward transitivity): A→B→C exists, trying to add A→C
        - Clearly redundant - just skip creation
        
        Case 2 (Sibling inference): A→B and A→C exist, trying to add B→C
        - Needs LLM resolution to determine if B→C creates proper hierarchy
          or if they are truly siblings
        
        Case 3 (Common child inference): A→C and B→C exist, trying to add A→B
        - Needs LLM resolution to determine if A→B creates proper hierarchy
          or if they are truly siblings
        
        Args:
            source_topic_id: The topic that would encompass (broader topic)
            target_topic_id: The topic that would be encompassed (narrower topic)
            
        Returns:
            Dict with keys:
                - is_redundant (bool): Whether the relationship is redundant
                - case_type (str): 'none', 'transitive', 'common_parent', 'common_child'
                - needs_llm_resolution (bool): Whether LLM should resolve this
                - topics_for_resolution (List[str]): Topic IDs to analyze [A, B, C]
                - existing_relationships (List[Dict]): Existing parent-child relationships
                - proposed_relationship (Dict): The proposed new relationship
                - conflict_description (str): Human-readable description
                - common_node_id (str|None): ID of common parent or child node
        """
        
        # Case 1: Check if there's already an indirect path from source to target
        # (Classic transitivity: A→B→C exists, trying to add A→C)
        # Use OPTIONAL MATCH to avoid warnings when ENCOMPASSES relationship type doesn't exist yet
        query_case1 = """
        OPTIONAL MATCH path = (source:Topic {topic_id: $source_id})
                              -[:ENCOMPASSES*2..]->(target:Topic {topic_id: $target_id})
        RETURN path IS NOT NULL as has_path
        LIMIT 1
        """
        
        params = {
            "source_id": source_topic_id,
            "target_id": target_topic_id
        }
        
        results = self.client.execute_query(query_case1, params)
        
        if results and results[0].get("has_path"):
            self.logger.info(
                f"Redundant relationship (Case 1): Indirect path exists from {source_topic_id} "
                f"to {target_topic_id}. Direct relationship not needed."
            )
            return {
                "is_redundant": True,
                "case_type": "transitive",
                "needs_llm_resolution": False,
                "topics_for_resolution": [],
                "existing_relationships": [],
                "proposed_relationship": {"parent": source_topic_id, "child": target_topic_id},
                "conflict_description": (
                    f"Transitive redundancy: An indirect path already exists from "
                    f"{source_topic_id} to {target_topic_id}"
                ),
                "common_node_id": None
            }
        
        # Case 2: Check if source and target share a common parent
        # (A→B and A→C exist, trying to add B→C suggests B and C are siblings)
        # Use OPTIONAL MATCH with a single pattern to require BOTH relationships exist
        # The pattern (parent)-[:ENCOMPASSES]->(source) and (parent)-[:ENCOMPASSES]->(target)
        # ensures we only match when both source and target have the same parent
        #
        # TODO: This only finds ONE common parent due to LIMIT 1. If source and target have
        # multiple common parents (e.g., B has parents A,F,G and C has parents K,T,A,F),
        # we only detect and resolve the conflict for one parent (A). After LLM resolves
        # A→B, A→C, the sibling relationship through F would still exist, potentially
        # allowing a redundant B→C relationship to be created. To fully handle this,
        # we'd need to collect ALL common parents and resolve conflicts for each.
        query_case2 = """
        OPTIONAL MATCH (parent:Topic)-[:ENCOMPASSES]->(source:Topic {topic_id: $source_id})
        WHERE EXISTS { (parent)-[:ENCOMPASSES]->(target:Topic {topic_id: $target_id}) }
        RETURN parent.topic_id AS common_parent
        LIMIT 1
        """
        
        results = self.client.execute_query(query_case2, params)
        
        if results and results[0].get("common_parent"):
            common_parent = results[0].get("common_parent")
            self.logger.info(
                f"Redundant relationship (Case 2): {source_topic_id} and {target_topic_id} "
                f"share common parent {common_parent}. Needs LLM resolution."
            )
            return {
                "is_redundant": True,
                "case_type": "common_parent",
                "needs_llm_resolution": True,
                "topics_for_resolution": [common_parent, source_topic_id, target_topic_id],
                "existing_relationships": [
                    {"parent": common_parent, "child": source_topic_id},
                    {"parent": common_parent, "child": target_topic_id}
                ],
                "proposed_relationship": {"parent": source_topic_id, "child": target_topic_id},
                "conflict_description": (
                    f"{source_topic_id} and {target_topic_id} share common parent {common_parent}. "
                    f"Proposed {source_topic_id}→{target_topic_id} needs validation."
                ),
                "common_node_id": common_parent
            }
        
        # Case 3: Check if source and target both encompass a common child
        # (A→C and B→C exist, trying to add A→B suggests A and B are siblings)
        # Use OPTIONAL MATCH with a single pattern to require BOTH relationships exist
        # The pattern (source)-[:ENCOMPASSES]->(child)<-[:ENCOMPASSES]-(target) ensures
        # we only match when both source and target have ENCOMPASSES to the same child
        #
        # TODO: Same limitation as Case 2 - only finds ONE common child due to LIMIT 1.
        # If source and target both encompass multiple common children, we only detect
        # and resolve the conflict for one. The sibling relationship through other
        # common children could still allow redundant relationships to be created.
        query_case3 = """
        OPTIONAL MATCH (source:Topic {topic_id: $source_id})-[:ENCOMPASSES]->(child:Topic)<-[:ENCOMPASSES]-(target:Topic {topic_id: $target_id})
        RETURN child.topic_id AS common_child
        LIMIT 1
        """
        
        results = self.client.execute_query(query_case3, params)
        
        if results and results[0].get("common_child"):
            common_child = results[0].get("common_child")
            self.logger.info(
                f"Redundant relationship (Case 3): {source_topic_id} and {target_topic_id} "
                f"both encompass common child {common_child}. Needs LLM resolution."
            )
            return {
                "is_redundant": True,
                "case_type": "common_child",
                "needs_llm_resolution": True,
                "topics_for_resolution": [source_topic_id, target_topic_id, common_child],
                "existing_relationships": [
                    {"parent": source_topic_id, "child": common_child},
                    {"parent": target_topic_id, "child": common_child}
                ],
                "proposed_relationship": {"parent": source_topic_id, "child": target_topic_id},
                "conflict_description": (
                    f"{source_topic_id} and {target_topic_id} both encompass {common_child}. "
                    f"Proposed {source_topic_id}→{target_topic_id} needs validation."
                ),
                "common_node_id": common_child
            }
        
        # No redundancy detected
        return {
            "is_redundant": False,
            "case_type": "none",
            "needs_llm_resolution": False,
            "topics_for_resolution": [],
            "existing_relationships": [],
            "proposed_relationship": {"parent": source_topic_id, "child": target_topic_id},
            "conflict_description": "",
            "common_node_id": None
        }


    # ========== Query Operations for LLM frontend ==========

    def get_recent_resources(
        self,
        start: Optional[str] = None,
        end: Optional[str] = None,
        topics: Optional[List[str]] = None,
        organisations: Optional[List[str]] = None,
        people: Optional[List[str]] = None,
        category: Optional[str] = None,
        doc_type: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent Resource nodes with optional filters on topics, organisations, people, category, and doc_type.

        Dates should be ISO-8601 strings (YYYY-MM-DD). We'll prefer publish_date if present,
        otherwise fall back to scraped_at.
        
        The query now supports:
        - Relevance-based ranking combining recency and filter match quality
        - Matching by name, aliases, or identifiers for topics
        - Matching by name or aliases for organisations
        - Category filtering (e.g., 'press release', 'whitepaper', 'blog', 'article', 'podcast', 'newsletter')
        - Doc type filtering (e.g., 'pdf', 'html', 'video', 'docx')
        - Topic classification and identifier matching for standards (e.g., '802.11ax', 'Wi-Fi 6', '6 GHz')
        - More flexible matching that treats filters as relevance signals
        - Returns most relevant and recent documents based on proximity to requested entities

        Returns a list of dicts:
            {
              "resource": { ... Resource properties ... },
              "topics": [ {topic props}, ... ],
              "people": [ {person props}, ... ],
              "organisations": [ {org props}, ... ],
              "datasources": [ {ds props}, ... ]
            }
        """
        topics = topics or []
        organisations = organisations or []
        people = people or []

        params = {
            "start": start,
            "end": end,
            "topics": topics,
            "organisations": organisations,
            "people": people,
            "category": category,
            "doc_type": doc_type,
            "limit": limit,
        }

        # Enhanced query with better relevance ranking and alias matching
        # Safe date handling: Some publish_date values are non-ISO (e.g. 'November 6, 2025').
        # Neo4j date() rejects those. We extract an ISO candidate only if it matches YYYY-MM-DD.
        # Otherwise we treat publish_date as unusable for date comparisons and rely on scraped_at.
        query = """
        WITH
            $topics        AS topics_param,
            $organisations AS orgs_param,
            $people        AS people_param,
            $category      AS category_param,
            $doc_type      AS doc_type_param,
            $start         AS start_param,
            $end           AS end_param,
            $limit         AS limit_param

        MATCH (r:Resource)

        WITH r,
             (CASE WHEN r.publish_date =~ '\\d{4}-\\d{2}-\\d{2}.*' THEN substring(r.publish_date, 0, 10) ELSE NULL END) AS publish_date_iso,
             topics_param, orgs_param, people_param, category_param, doc_type_param, start_param, end_param, limit_param

        // Collect related entities
        OPTIONAL MATCH (r)-[rt:RELATES_TO]->(t:Topic)
        OPTIONAL MATCH (r)-[mp:MENTIONS]->(p:Person)
        OPTIONAL MATCH (r)-[mo:MENTIONS]->(o:Organization)
        OPTIONAL MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)

        WITH r,
             publish_date_iso,
             collect(DISTINCT t)  AS topics,
             collect(DISTINCT rt) AS topic_rels,
             collect(DISTINCT p)  AS people,
             collect(DISTINCT o)  AS orgs,
             collect(DISTINCT ds) AS datasources,
             topics_param,
             orgs_param,
             people_param,
             category_param,
             doc_type_param,
             start_param,
             end_param,
             limit_param
        
        // For each person, collect their organizational affiliations
        UNWIND CASE WHEN size(people) > 0 THEN people ELSE [null] END AS person
        OPTIONAL MATCH (person)-[aff:AFFILIATED_WITH]->(affOrg:Organization)
        WITH r, publish_date_iso, topics, topic_rels, people, orgs, datasources,
             topics_param, orgs_param, people_param, category_param, doc_type_param,
             start_param, end_param, limit_param,
             person,
             collect(DISTINCT {organization: affOrg.name, role: aff.role}) AS person_affiliations
        
        WITH r, publish_date_iso, topics, topic_rels, people, orgs, datasources,
             topics_param, orgs_param, people_param, category_param, doc_type_param,
             start_param, end_param, limit_param,
             collect(CASE WHEN person IS NOT NULL THEN {
                 person: person,
                 affiliations: person_affiliations
             } ELSE null END) AS people_with_affiliations_raw
        
        WITH r, publish_date_iso, topics, topic_rels, people, orgs, datasources,
             topics_param, orgs_param, people_param, category_param, doc_type_param,
             start_param, end_param, limit_param,
             [x IN people_with_affiliations_raw WHERE x IS NOT NULL] AS people_with_affiliations

        // Apply date, category, and doc_type filters
        WHERE
            // Category filter (if specified, must match exactly - case insensitive)
            (category_param IS NULL OR toLower(r.category) = toLower(category_param))
            AND
            // Doc type filter (if specified, must match exactly - case insensitive)
            (doc_type_param IS NULL OR toLower(r.doc_type) = toLower(doc_type_param))
            AND
            // Date validation: exclude invalid future dates (beyond year 2100)
            (
                publish_date_iso IS NULL OR date(publish_date_iso) <= date('2100-12-31')
            )
            AND
            // Date filters
            (
                start_param IS NULL
                OR (
                    publish_date_iso IS NOT NULL AND date(publish_date_iso) >= date(start_param)
                )
                OR (
                    publish_date_iso IS NULL AND r.scraped_at IS NOT NULL AND datetime(r.scraped_at) >= datetime(start_param)
                )
            )
            AND (
                end_param IS NULL
                OR (
                    publish_date_iso IS NOT NULL AND date(publish_date_iso) <= date(end_param)
                )
                OR (
                    publish_date_iso IS NULL AND r.scraped_at IS NOT NULL AND datetime(r.scraped_at) <= datetime(end_param)
                )
            )

        // Calculate relevance scores with per-term scoring for better precision
        WITH r, publish_date_iso, topics, topic_rels, people, orgs, datasources,
             people_with_affiliations,
             topics_param, orgs_param, people_param, limit_param,
             
             // Topic match score: check name, aliases, and identifiers in Topic nodes
             CASE 
                WHEN size(topics_param) = 0 THEN 1.0
                ELSE 
                    toFloat(size([tp IN topics WHERE 
                        toLower(tp.name) IN [x IN topics_param | toLower(x)] OR
                        tp.topic_id IN topics_param OR
                        any(alias IN tp.aliases WHERE toLower(alias) IN [x IN topics_param | toLower(x)]) OR
                        (tp.identifier IS NOT NULL AND toLower(tp.identifier) IN [x IN topics_param | toLower(x)])
                    ])) / size(topics_param)
             END AS topic_match_score,
             
             // Count how many distinct query terms matched in document text (completeness metric)
             CASE
                WHEN size(topics_param) = 0 THEN 0
                ELSE
                    size([keyword IN topics_param WHERE
                        toLower(coalesce(r.title, '')) CONTAINS toLower(keyword) OR
                        toLower(coalesce(r.summary, '')) CONTAINS toLower(keyword) OR
                        toLower(coalesce(r.url, '')) CONTAINS toLower(keyword)
                    ])
             END AS matched_term_count,
             
             // Simple per-term match tracking for weighted scoring
             [keyword IN topics_param WHERE
                 toLower(coalesce(r.title, '')) CONTAINS toLower(keyword) OR
                 toLower(coalesce(r.summary, '')) CONTAINS toLower(keyword) OR
                 toLower(coalesce(r.url, '')) CONTAINS toLower(keyword)
             ] AS matched_keywords
        
        WITH r, publish_date_iso, topics, topic_rels, people, orgs, datasources,
             people_with_affiliations,
             topics_param, orgs_param, people_param, limit_param,
             topic_match_score, matched_term_count, matched_keywords,
             
             // Text match score: equal weight per matched term (completeness-based)
             CASE
                WHEN size(topics_param) = 0 THEN 0.0
                ELSE toFloat(matched_term_count) / size(topics_param)
             END AS text_match_score,
             
             // Organization match score: check name and aliases
             CASE
                WHEN size(orgs_param) = 0 THEN 1.0
                ELSE
                    toFloat(size([org IN orgs WHERE 
                        toLower(org.name) IN [x IN orgs_param | toLower(x)] OR
                        org.org_id IN orgs_param OR
                        any(alias IN org.aliases WHERE toLower(alias) IN [x IN orgs_param | toLower(x)])
                    ])) / size(orgs_param)
             END AS org_match_score,
             
             // People match score: check name (partial match with CONTAINS), email
             CASE
                WHEN size(people_param) = 0 THEN 1.0
                ELSE
                    toFloat(size([pr IN people WHERE 
                        any(search_term IN people_param WHERE toLower(pr.name) CONTAINS toLower(search_term)) OR
                        pr.person_id IN people_param OR
                        (pr.email IS NOT NULL AND any(search_term IN people_param WHERE toLower(pr.email) CONTAINS toLower(search_term)))
                    ])) / size(people_param)
             END AS people_match_score,
             
             // Relationship quality score from confidence values
             CASE
                WHEN size(topic_rels) = 0 THEN 0.0
                ELSE reduce(s = 0.0, rel IN topic_rels | s + coalesce(rel.confidence, 0.5)) / size(topic_rels)
             END AS avg_topic_confidence

        // Apply entity filters - require match in EITHER graph relationships OR document text
        WHERE
            (size(topics_param) = 0 OR topic_match_score > 0.0 OR text_match_score > 0.0)
            AND (size(orgs_param) = 0 OR org_match_score > 0.0)
            AND (size(people_param) = 0 OR people_match_score > 0.0)

        // Calculate combined relevance score with strong completeness emphasis
        WITH r, publish_date_iso, topics, people, orgs, datasources,
             people_with_affiliations,
             topic_match_score, text_match_score, org_match_score, people_match_score, avg_topic_confidence, matched_term_count,
             // Completeness bonus: HEAVILY favor documents matching ALL query terms
             // 10x multiplier if ALL terms matched, 2x if 75%+, 1x otherwise
             // This ensures "wi-fi" + "congress" ranks much higher than just "wi-fi"
             CASE
                WHEN size(topics_param) > 0 AND matched_term_count = size(topics_param) THEN 10.0
                WHEN size(topics_param) > 0 AND toFloat(matched_term_count) / size(topics_param) >= 0.75 THEN 2.0
                ELSE 1.0
             END AS completeness_bonus,
             // Base relevance: 30% text match, 25% topic match (graph), 20% org match, 15% people match, 10% relationship quality
             (text_match_score * 0.3 + topic_match_score * 0.25 + org_match_score * 0.2 + people_match_score * 0.15 + avg_topic_confidence * 0.1) AS base_relevance,
             
             // Recency score: more recent documents get higher scores
             CASE
                WHEN publish_date_iso IS NOT NULL THEN 
                    1.0 / (1.0 + duration.between(date(publish_date_iso), date()).days / 365.0)
                WHEN r.scraped_at IS NOT NULL THEN
                    1.0 / (1.0 + duration.between(datetime(r.scraped_at), datetime()).days / 365.0)
                ELSE 0.1
             END AS recency_score

        // Final ranking: apply completeness bonus to base relevance, then blend with recency
        // 80% relevance (with completeness bonus), 20% recency
        WITH r, publish_date_iso, topics, people, orgs, datasources, matched_term_count,
             people_with_affiliations,
             (base_relevance * completeness_bonus * 0.8 + recency_score * 0.2) AS final_score
        
        ORDER BY final_score DESC, matched_term_count DESC,
                 coalesce(
                    CASE WHEN publish_date_iso IS NOT NULL THEN date(publish_date_iso) ELSE NULL END,
                    date(datetime(r.scraped_at))
                 ) DESC

        // Limit to requested number of documents
        LIMIT $limit
        
        RETURN
            r           AS resource,
            topics      AS topics,
            people      AS people,
            people_with_affiliations AS people_details,
            orgs        AS organisations,
            datasources AS datasources
        """

        return self.client.execute_query(query, params)
    
    def get_upcoming_events(
        self,
        start_date: Optional[str] = None,
        topics: Optional[List[str]] = None,
        organisations: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Fetch upcoming Event nodes with optional filters.
        
        Args:
            start_date: ISO-8601 date string (YYYY-MM-DD). Defaults to today if not provided.
            topics: List of topic names/identifiers to filter by (events associated via resources)
            organisations: List of organization names to filter by (events mentioned by org resources)
            limit: Maximum number of events to return (default: 20)
            
        Returns:
            List of dicts containing event data with associated resources:
            {
              "event": { ... Event properties ... },
              "resources": [ {resource props}, ... ],
              "topics": [ {topic props}, ... ],
              "organisations": [ {org props}, ... ]
            }
        """
        # Default to today if no start_date provided
        if not start_date:
            start_date = date.today().isoformat()
        
        topics = topics or []
        organisations = organisations or []
        
        params = {
            "start_date": start_date,
            "topics": topics,
            "organisations": organisations,
            "limit": limit
        }
        
        query = """
        WITH
            $topics        AS topics_param,
            $organisations AS orgs_param,
            $start_date    AS start_param,
            $limit         AS limit_param
        
        // Match events that haven't ended yet (future or ongoing)
        MATCH (e:Event)
        WHERE
            // Event hasn't ended yet (use start_date if no end_date)
            (
                (e.end_date IS NOT NULL AND datetime(e.end_date) >= datetime(start_param))
                OR
                (e.end_date IS NULL AND e.start_date IS NOT NULL AND datetime(e.start_date) >= datetime(start_param))
            )
        
        // Find resources that relate to this event
        OPTIONAL MATCH (r:Resource)-[:RELATES_TO]->(e)
        
        // Find topics and organizations related to those resources
        OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
        OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
        
        WITH e, r,
             collect(DISTINCT t) AS topics,
             collect(DISTINCT o) AS orgs,
             topics_param, orgs_param
        
        // Apply topic and organization filters if specified
        WHERE
            (size(topics_param) = 0 OR any(tp IN topics_param WHERE 
                any(topic IN topics WHERE 
                    toLower(topic.name) = toLower(tp) OR
                    topic.topic_id = tp OR
                    any(alias IN topic.aliases WHERE toLower(alias) = toLower(tp))
                )
            ))
            AND
            (size(orgs_param) = 0 OR any(op IN orgs_param WHERE
                any(org IN orgs WHERE
                    toLower(org.name) = toLower(op) OR
                    org.org_id = op OR
                    any(alias IN org.aliases WHERE toLower(alias) = toLower(op))
                )
            ))
        
        // Collect all resources per event
        WITH e,
             collect(DISTINCT r) AS resources,
             collect(DISTINCT topics) AS all_topics,
             collect(DISTINCT orgs) AS all_orgs
        
        // Flatten nested lists and calculate urgency score
        WITH e, resources,
             reduce(flat = [], topics IN all_topics | flat + topics) AS flat_topics,
             reduce(flat = [], orgs IN all_orgs | flat + orgs) AS flat_orgs,
             // Urgency score: events closer to today rank higher
             CASE
                WHEN e.start_date IS NOT NULL THEN
                    1.0 / (1.0 + duration.between(datetime($start_date), datetime(e.start_date)).days / 30.0)
                ELSE 0.1
             END AS urgency_score
        
        ORDER BY urgency_score DESC, e.start_date ASC
        LIMIT $limit
        
        RETURN
            e AS event,
            resources AS resources,
            flat_topics AS topics,
            flat_orgs AS organisations
        """
        
        return self.client.execute_query(query, params)
    
    def get_past_events(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        topics: Optional[List[str]] = None,
        organisations: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Fetch past Event nodes with optional filters.
        
        Args:
            start_date: ISO-8601 date string (YYYY-MM-DD) for earliest event date
            end_date: ISO-8601 date string (YYYY-MM-DD). Defaults to today if not provided.
            topics: List of topic names/identifiers to filter by
            organisations: List of organization names to filter by
            limit: Maximum number of events to return (default: 20)
            
        Returns:
            List of dicts containing event data with associated resources
        """
        # Default to today if no end_date provided
        if not end_date:
            end_date = date.today().isoformat()
        
        topics = topics or []
        organisations = organisations or []
        
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "topics": topics,
            "organisations": organisations,
            "limit": limit
        }
        
        query = """
        WITH
            $topics        AS topics_param,
            $organisations AS orgs_param,
            $start_date    AS start_param,
            $end_date      AS end_param,
            $limit         AS limit_param
        
        // Match events that have ended
        MATCH (e:Event)
        WHERE
            // Event has ended (use start_date if no end_date)
            (
                (e.end_date IS NOT NULL AND datetime(e.end_date) < datetime(end_param))
                OR
                (e.end_date IS NULL AND e.start_date IS NOT NULL AND datetime(e.start_date) < datetime(end_param))
            )
            AND
            // Apply start_date filter if provided
            (
                start_param IS NULL
                OR
                (e.start_date IS NOT NULL AND datetime(e.start_date) >= datetime(start_param))
            )
        
        // Find resources that relate to this event
        OPTIONAL MATCH (r:Resource)-[:RELATES_TO]->(e)
        
        // Find topics and organizations related to those resources
        OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
        OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
        
        WITH e, r,
             collect(DISTINCT t) AS topics,
             collect(DISTINCT o) AS orgs,
             topics_param, orgs_param
        
        // Apply topic and organization filters if specified
        WHERE
            (size(topics_param) = 0 OR any(tp IN topics_param WHERE 
                any(topic IN topics WHERE 
                    toLower(topic.name) = toLower(tp) OR
                    topic.topic_id = tp OR
                    any(alias IN topic.aliases WHERE toLower(alias) = toLower(tp))
                )
            ))
            AND
            (size(orgs_param) = 0 OR any(op IN orgs_param WHERE
                any(org IN orgs WHERE
                    toLower(org.name) = toLower(op) OR
                    org.org_id = op OR
                    any(alias IN org.aliases WHERE toLower(alias) = toLower(op))
                )
            ))
        
        // Collect all resources per event
        WITH e,
             collect(DISTINCT r) AS resources,
             collect(DISTINCT topics) AS all_topics,
             collect(DISTINCT orgs) AS all_orgs
        
        // Flatten nested lists
        WITH e, resources,
             reduce(flat = [], topics IN all_topics | flat + topics) AS flat_topics,
             reduce(flat = [], orgs IN all_orgs | flat + orgs) AS flat_orgs
        
        ORDER BY e.start_date DESC
        LIMIT $limit
        
        RETURN
            e AS event,
            resources AS resources,
            flat_topics AS topics,
            flat_orgs AS organisations
        """
        
        return self.client.execute_query(query, params)
    
    def query_recently_updated_documents(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        topics: Optional[List[str]] = None,
        organisations: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Fetch Resource nodes that were recently updated (content changed).
        
        Args:
            start_date: ISO-8601 date string - start of date range (default: 7 days ago)
            end_date: ISO-8601 date string - end of date range (default: today)
            topics: List of topic names/identifiers to filter by
            organisations: List of organization names to filter by
            limit: Maximum number of documents to return
            
        Returns:
            List of dicts containing document data with update_recency_score
        """
        # Default to last 7 days if not provided
        if not start_date:
            start_date = (datetime.now() - timedelta(days=7)).date().isoformat()
        if not end_date:
            end_date = datetime.now().date().isoformat()
        
        topics = topics or []
        organisations = organisations or []
        
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "topics": topics,
            "organisations": organisations,
            "limit": limit
        }
        
        query = """
        WITH
            $topics        AS topics_param,
            $organisations AS orgs_param,
            $start_date    AS start_param,
            $end_date      AS end_param,
            $limit         AS limit_param
        
        MATCH (r:Resource)
        WHERE
            r.content_changed_at IS NOT NULL
            AND datetime(r.content_changed_at) >= datetime(start_param)
            AND datetime(r.content_changed_at) <= datetime(end_param)
        
        OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
        OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
        OPTIONAL MATCH (r)-[:UPLOADED_BY]->(p:Person)
        OPTIONAL MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
        
        WITH r, t, o, p, ds, topics_param, orgs_param
        WHERE
            (size(topics_param) = 0 OR t.name IN topics_param OR t.topic_id IN topics_param)
            AND
            (size(orgs_param) = 0 OR o.name IN orgs_param OR o.org_id IN orgs_param)
        
        WITH r,
             collect(DISTINCT t {.topic_id, .name, .classification}) AS topics,
             collect(DISTINCT o {.org_id, .name, .org_type}) AS orgs,
             collect(DISTINCT p {.person_id, .name, .email}) AS people,
             collect(DISTINCT ds {.datasource_id, .name}) AS datasources,
             CASE
                 WHEN r.content_changed_at IS NOT NULL THEN
                     1.0 / (1.0 + duration.between(datetime(r.content_changed_at), datetime()).days / 30.0)
                 ELSE 0.1
             END AS update_recency_score
        
        ORDER BY update_recency_score DESC, r.content_changed_at DESC
        LIMIT limit_param
        
        RETURN
            r.url_hash     AS url_hash,
            r.url          AS url,
            r.title        AS title,
            r.summary      AS summary,
            r.category     AS category,
            r.doc_type     AS doc_type,
            r.publish_date AS publish_date,
            r.scraped_at   AS scraped_at,
            r.content_changed_at AS content_changed_at,
            r.created_at   AS created_at,
            r.importance   AS importance,
            update_recency_score AS update_recency_score,
            topics         AS topics,
            people         AS people,
            orgs           AS organisations,
            datasources    AS datasources
        """
        
        return self.client.execute_query(query, params)
    
    def query_documents_by_publish_date(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        topics: Optional[List[str]] = None,
        organisations: Optional[List[str]] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Fetch Resource nodes by publication date.
        
        Args:
            start_date: ISO-8601 date string - start of date range
            end_date: ISO-8601 date string - end of date range (default: today)
            topics: List of topic names/identifiers to filter by
            organisations: List of organization names to filter by
            limit: Maximum number of documents to return
            
        Returns:
            List of dicts containing document data with publish_recency_score
        """
        if not end_date:
            end_date = datetime.now().date().isoformat()
        
        topics = topics or []
        organisations = organisations or []
        
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "topics": topics,
            "organisations": organisations,
            "limit": limit
        }
        
        query = """
        WITH
            $topics        AS topics_param,
            $organisations AS orgs_param,
            $start_date    AS start_param,
            $end_date      AS end_param,
            $limit         AS limit_param
        
        MATCH (r:Resource)
        WHERE
            r.publish_date IS NOT NULL
            AND (start_param IS NULL OR datetime(r.publish_date) >= datetime(start_param))
            AND datetime(r.publish_date) <= datetime(end_param)
        
        OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
        OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
        OPTIONAL MATCH (r)-[:UPLOADED_BY]->(p:Person)
        OPTIONAL MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
        
        WITH r, t, o, p, ds, topics_param, orgs_param
        WHERE
            (size(topics_param) = 0 OR t.name IN topics_param OR t.topic_id IN topics_param)
            AND
            (size(orgs_param) = 0 OR o.name IN orgs_param OR o.org_id IN orgs_param)
        
        WITH r,
             collect(DISTINCT t {.topic_id, .name, .classification}) AS topics,
             collect(DISTINCT o {.org_id, .name, .org_type}) AS orgs,
             collect(DISTINCT p {.person_id, .name, .email}) AS people,
             collect(DISTINCT ds {.datasource_id, .name}) AS datasources,
             CASE
                 WHEN r.publish_date IS NOT NULL THEN
                     1.0 / (1.0 + duration.between(datetime(r.publish_date), datetime()).days / 365.0)
                 ELSE 0.1
             END AS publish_recency_score
        
        ORDER BY publish_recency_score DESC, r.publish_date DESC
        LIMIT limit_param
        
        RETURN
            r.url_hash     AS url_hash,
            r.url          AS url,
            r.title        AS title,
            r.summary      AS summary,
            r.category     AS category,
            r.doc_type     AS doc_type,
            r.publish_date AS publish_date,
            r.scraped_at   AS scraped_at,
            r.content_changed_at AS content_changed_at,
            r.created_at   AS created_at,
            r.importance   AS importance,
            publish_recency_score AS publish_recency_score,
            topics         AS topics,
            people         AS people,
            orgs           AS organisations,
            datasources    AS datasources
        """
        
        return self.client.execute_query(query, params)
    
    def query_temporal_mixed(
        self,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        topics: Optional[List[str]] = None,
        organisations: Optional[List[str]] = None,
        publish_weight: float = 1.0,
        update_weight: float = 0.8,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """
        Fetch both newly published and recently updated documents.
        
        Args:
            start_date: ISO-8601 date string - start of date range
            end_date: ISO-8601 date string - end of date range (default: today)
            topics: List of topic names/identifiers to filter by
            organisations: List of organization names to filter by
            publish_weight: Weight for newly published documents (default: 1.0)
            update_weight: Weight for updated documents (default: 0.8)
            limit: Maximum total documents to return
            
        Returns:
            Dict with documents, published_count, updated_count, total_count
        """
        if not end_date:
            end_date = datetime.now().date().isoformat()
        
        # Query both published and updated documents
        published = self.query_documents_by_publish_date(start_date, end_date, topics, organisations, limit)
        updated = self.query_recently_updated_documents(start_date, end_date, topics, organisations, limit)
        
        # Apply weights and combine
        for doc in published:
            doc['temporal_type'] = 'published'
            doc['weighted_score'] = doc.get('publish_recency_score', 0.5) * publish_weight
        
        for doc in updated:
            doc['temporal_type'] = 'updated'
            doc['weighted_score'] = doc.get('update_recency_score', 0.5) * update_weight
        
        # Merge and deduplicate by url_hash (keep higher score)
        doc_map = {}
        for doc in published + updated:
            url_hash = doc['url_hash']
            if url_hash not in doc_map or doc['weighted_score'] > doc_map[url_hash]['weighted_score']:
                doc_map[url_hash] = doc
        
        # Sort by weighted score
        combined = sorted(doc_map.values(), key=lambda x: x['weighted_score'], reverse=True)[:limit]
        
        published_count = sum(1 for doc in combined if doc['temporal_type'] == 'published')
        updated_count = sum(1 for doc in combined if doc['temporal_type'] == 'updated')
        
        return {
            "documents": combined,
            "published_count": published_count,
            "updated_count": updated_count,
            "total_count": len(combined)
        }

    # =========================================================================
    # Ingestion Batch Methods
    # =========================================================================
    
    def update_batch_status(
        self,
        batch_id: str,
        status: str,
        **kwargs
    ) -> bool:
        """
        Update the status and optional fields of an ingestion batch.
        
        Args:
            batch_id: The batch UUID
            status: New status:
                - 'retrieving': Retriever actively scraping (digester may also be processing)
                - 'digesting': Retriever finished, digester still processing remaining items
                - 'completed': All items digested successfully
                - 'failed': Batch encountered errors
            **kwargs: Additional fields to update (e.g., scrape_completed_at, items_scraped)
            
        Returns:
            True if updated successfully
        """
        # Build SET clause dynamically
        set_parts = ["b.status = $status"]
        params = {"batch_id": batch_id, "status": status}
        
        # Handle datetime fields
        datetime_fields = ['scrape_started_at', 'scrape_completed_at', 'digest_completed_at']
        for key, value in kwargs.items():
            if value is not None:
                if key in datetime_fields:
                    if isinstance(value, datetime):
                        set_parts.append(f"b.{key} = datetime($_{key})")
                        params[f"_{key}"] = value.isoformat()
                    else:
                        set_parts.append(f"b.{key} = datetime($_{key})")
                        params[f"_{key}"] = value
                else:
                    set_parts.append(f"b.{key} = $_{key}")
                    params[f"_{key}"] = value
        
        query = f"""
        MATCH (b:IngestionBatch {{batch_id: $batch_id}})
        SET {', '.join(set_parts)}
        RETURN b.batch_id
        """
        
        try:
            results = self.client.execute_write(query, params)
            if results:
                self.logger.debug(f"Updated batch {batch_id} to status={status}")
                return True
            return False
        except Exception as e:
            self.logger.error(f"Failed to update batch status: {e}")
            return False
    
    def increment_batch_digested(
        self,
        batch_id: str,
        events_delta: int = 0,
        resources_delta: int = 0
    ) -> Optional[Dict[str, int]]:
        """
        Atomically increment the items_digested counter and type counts.
        
        Args:
            batch_id: The batch UUID
            events_delta: Number of events to add to count
            resources_delta: Number of resources to add to count
            
        Returns:
            Dict with current counts and status, or None on error
        """
        query = """
        MATCH (b:IngestionBatch {batch_id: $batch_id})
        SET b.items_digested = coalesce(b.items_digested, 0) + $delta,
            b.events_count = coalesce(b.events_count, 0) + $events_delta,
            b.resources_count = coalesce(b.resources_count, 0) + $resources_delta
        RETURN b.items_digested as items_digested,
               b.items_scraped as items_scraped,
               b.events_count as events_count,
               b.resources_count as resources_count,
               b.status as status
        """
        
        delta = events_delta + resources_delta
        try:
            results = self.client.execute_write(query, {
                "batch_id": batch_id,
                "delta": delta,
                "events_delta": events_delta,
                "resources_delta": resources_delta
            })
            if results:
                return dict(results[0])
            return None
        except Exception as e:
            self.logger.error(f"Failed to increment batch counter: {e}")
            return None
    
    def increment_batch_scraped(
        self,
        batch_id: str,
        delta: int = 1
    ) -> Optional[int]:
        """
        Atomically increment the items_scraped counter.
        
        Called by the retriever each time an item is published to the queue.
        
        Args:
            batch_id: The batch UUID
            delta: Number of items to add (default 1)
            
        Returns:
            New items_scraped count, or None on error
        """
        query = """
        MATCH (b:IngestionBatch {batch_id: $batch_id})
        SET b.items_scraped = coalesce(b.items_scraped, 0) + $delta
        RETURN b.items_scraped as items_scraped
        """
        
        try:
            results = self.client.execute_write(query, {
                "batch_id": batch_id,
                "delta": delta
            })
            if results:
                return results[0]["items_scraped"]
            return None
        except Exception as e:
            self.logger.error(f"Failed to increment batch scraped counter: {e}")
            return None
    
    def get_batches_by_status(
        self,
        status: Optional[List[str]] = None,
        datasource_id: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Get ingestion batches filtered by status and/or datasource.
        
        Args:
            status: List of statuses to filter by (e.g., ['completed'], ['retrieving', 'digesting'])
                   If None, returns all batches.
            datasource_id: Optional filter by datasource
            
        Returns:
            List of batch data dicts, ordered by scrape_started_at DESC
        """
        conditions = []
        params = {}
        
        if status:
            conditions.append("b.status IN $status")
            params["status"] = status
        
        if datasource_id:
            conditions.append("b.datasource_id = $datasource_id")
            params["datasource_id"] = datasource_id
        
        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        
        query = f"""
        MATCH (b:IngestionBatch)
        {where_clause}
        RETURN b
        ORDER BY b.scrape_started_at DESC
        """
        
        results = self.client.execute_query(query, params)
        return [dict(r["b"]) for r in results]

    # ========================================================================
    # DataSource Configuration Methods (for ConfigManager)
    # ========================================================================
    
    def get_datasource_config(self, datasource_id: str) -> Optional[Dict[str, Any]]:
        """
        Get configuration for a specific datasource.
        
        Args:
            datasource_id: Identifier for the datasource (e.g., 'wfa_resource_page')
            
        Returns:
            Configuration dict with all DataSource node properties, or None if not found
        """
        query = """
        MATCH (ds:DataSource {datasource_id: $datasource_id})
        RETURN ds
        """
        
        results = self.client.execute_query(query, {"datasource_id": datasource_id})
        if results:
            return dict(results[0]["ds"])
        return None
    
    def get_all_datasources_with_scraper(self) -> List[Dict[str, Any]]:
        """
        Get all datasources that have a scraper_type configured.
        
        Returns:
            List of datasource configurations with scraper_type set
        """
        query = """
        MATCH (ds:DataSource)
        WHERE ds.scraper_type IS NOT NULL
        RETURN ds
        ORDER BY ds.scraper_type, ds.datasource_id
        """
        
        results = self.client.execute_query(query)
        return [dict(r["ds"]) for r in results]
    
    def get_startup_datasources(self) -> List[Dict[str, Any]]:
        """
        Get datasources that should run on retriever startup.
        
        Returns:
            List of datasource configurations where run_on_startup=true
        """
        query = """
        MATCH (ds:DataSource)
        WHERE ds.scraper_type IS NOT NULL
          AND ds.run_on_startup = true
        RETURN ds
        ORDER BY ds.scraper_type, ds.datasource_id
        """
        
        results = self.client.execute_query(query)
        return [dict(r["ds"]) for r in results]
    
    def get_scheduled_datasources(self) -> List[Dict[str, Any]]:
        """
        Get all datasources with a scrape_schedule configured.
        
        Returns:
            List of datasource configurations with scrape_schedule set
        """
        query = """
        MATCH (ds:DataSource)
        WHERE ds.scraper_type IS NOT NULL
          AND ds.scrape_schedule IS NOT NULL
        RETURN ds
        ORDER BY ds.scraper_type, ds.datasource_id
        """
        
        results = self.client.execute_query(query)
        return [dict(r["ds"]) for r in results]
    
    def get_full_refresh_datasources(self) -> List[Dict[str, Any]]:
        """
        Get all datasources with a full_refresh_schedule configured.
        
        Returns:
            List of datasource configurations with full_refresh_schedule set
        """
        query = """
        MATCH (ds:DataSource)
        WHERE ds.scraper_type IS NOT NULL
          AND ds.full_refresh_schedule IS NOT NULL
        RETURN ds
        ORDER BY ds.scraper_type, ds.datasource_id
        """
        
        results = self.client.execute_query(query)
        return [dict(r["ds"]) for r in results]
    
    def update_datasource_last_scraped(self, datasource_id: str, timestamp: Optional[datetime] = None):
        """
        Update the last_scraped_at timestamp for a datasource.
        
        Args:
            datasource_id: Identifier for the datasource
            timestamp: Timestamp to set (defaults to current time)
        """
        if timestamp is None:
            timestamp = datetime.now()
        
        query = """
        MATCH (ds:DataSource {datasource_id: $datasource_id})
        SET ds.last_scraped_at = $timestamp
        RETURN ds.datasource_id
        """
        
        try:
            results = self.client.execute_write(query, {
                "datasource_id": datasource_id,
                "timestamp": timestamp
            })
            if results:
                self.logger.info(f"Updated last_scraped_at for {datasource_id}")
            else:
                self.logger.warning(f"Datasource {datasource_id} not found - skipping timestamp update")
        except Exception as e:
            self.logger.error(f"Error updating last_scraped for {datasource_id}: {e}")

