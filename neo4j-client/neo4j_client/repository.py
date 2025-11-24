"""Repository for managing knowledge graph operations."""

from typing import Dict, Any, List, Optional
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
            self.create_node(org)
        
        # Create data sources and link to organizations
        for ds_dict in data_sources:
            ds = DataSource(**ds_dict)
            org_id = ds_dict.get("org_id")
            
            # Create the data source
            self.create_node(ds)
            
            # Link data source to organization if org_id is provided
            if org_id:
                ds_to_org_rel = DataSourceBelongsToOrganization(source_id=ds.source_id, target_id=org_id)
                self.create_relationship(ds_to_org_rel)
        
        self.logger.info("Base data initialization complete")

    def create_node(self, node: Node) -> Optional[Dict[str, Any]]:
        """
        General method to create or update any node type in Neo4j.
        Uses the class name as the label and the first string field as the unique identifier.
        Subclasses can override get_node_label and get_id_field for custom behavior.
        
        Special handling for Resource nodes:
        - Automatically creates INGESTED_FROM relationship to the DataSource
        
        Args:
            node: Node model instance
        Returns:
            Created/updated node data
        """
        node_data = node.to_dict()
        # Determine label and id field
        label = node.node_label
        id_field = node.id_field

        # Prepare query and parameters
        query = f"""
        MERGE (n:{label} {{{id_field}: $id_value}})
        ON CREATE SET n += $properties, n.created_at = datetime()
        ON MATCH SET n += $properties, n.last_updated = datetime()
        RETURN n
        """
        params = {
            "id_value": node_data[id_field],
            "properties": node_data
        }
        result = self.client.execute_write(query, params)
        self.logger.info(f"Created/updated {label}: {node_data.get(id_field)}")
        
        # For Resource nodes, automatically create the INGESTED_FROM relationship
        if label == "Resource" and hasattr(node, 'datasource_id'):
            datasource_id = getattr(node, 'datasource_id')
            if datasource_id:
                try:
                    # Create the relationship using the url (not url_hash) as source_id
                    # because ResourceIngestedFromDataSource uses 'url' as source_id_field
                    ingested_rel = ResourceIngestedFromDataSource(
                        source_id=node.url,
                        target_id=datasource_id
                    )
                    self.create_relationship(ingested_rel)
                except Exception as e:
                    self.logger.warning(f"Failed to create INGESTED_FROM relationship for Resource: {e}")
        
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
            self.logger.info(f"Deleted {label} with {id_field}='{id_value}' and all its relationships")
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
        
        self.client.execute_write(query, {
            "source_id": relationship.source_id,
            "target_id": relationship.target_id,
            "properties": rel_props
        })
        self.logger.info(
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
            self.logger.info(
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
                "organizations": 0
            },
            "relationships_created": 0,
            "success": False
        }
        
        try:
            # Insert resource node
            if nodes.get("resource"):
                self.logger.info(f"Inserting resource node...")
                self.create_node(nodes["resource"])
                stats["nodes_created"]["resource"] = 1
            
            # Insert topic nodes
            if nodes.get("topics"):
                self.logger.info(f"Inserting {len(nodes['topics'])} topic nodes...")
                for topic in nodes["topics"]:
                    self.create_node(topic)
                    stats["nodes_created"]["topics"] += 1
            
            # Insert person nodes
            if nodes.get("people"):
                self.logger.info(f"Inserting {len(nodes['people'])} person nodes...")
                for person in nodes["people"]:
                    self.create_node(person)
                    stats["nodes_created"]["people"] += 1
            
            # Insert organization nodes
            if nodes.get("organizations"):
                self.logger.info(f"Inserting {len(nodes['organizations'])} organization nodes...")
                for org in nodes["organizations"]:
                    self.create_node(org)
                    stats["nodes_created"]["organizations"] += 1
            
            # Insert relationships
            if relationships:
                self.logger.info(f"Inserting {len(relationships)} relationships...")
                for rel in relationships:
                    self.create_relationship(rel)
                    stats["relationships_created"] += 1
            
            stats["success"] = True
            
            self.logger.info(
                f"Entity insertion complete. "
                f"Nodes: {stats['nodes_created']['resource']} resource, "
                f"{stats['nodes_created']['topics']} topics, "
                f"{stats['nodes_created']['people']} people, "
                f"{stats['nodes_created']['organizations']} organizations. "
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
        query = """
        MATCH path = (target:Topic {topic_id: $target_id})
                     -[:ENCOMPASSES*]->(source:Topic {topic_id: $source_id})
        RETURN path
        LIMIT 1
        """
        
        params = {
            "source_id": source_topic_id,
            "target_id": target_topic_id
        }
        
        results = self.client.execute_query(query, params)
        
        if results:
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
        query_case1 = """
        MATCH path = (source:Topic {topic_id: $source_id})
                     -[:ENCOMPASSES*2..]->(target:Topic {topic_id: $target_id})
        RETURN path
        LIMIT 1
        """
        
        params = {
            "source_id": source_topic_id,
            "target_id": target_topic_id
        }
        
        results = self.client.execute_query(query_case1, params)
        
        if results:
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
        query_case2 = """
        MATCH (parent:Topic)-[:ENCOMPASSES]->(source:Topic {topic_id: $source_id})
        MATCH (parent)-[:ENCOMPASSES]->(target:Topic {topic_id: $target_id})
        RETURN parent.topic_id AS common_parent
        LIMIT 1
        """
        
        results = self.client.execute_query(query_case2, params)
        
        if results:
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
        query_case3 = """
        MATCH (source:Topic {topic_id: $source_id})-[:ENCOMPASSES]->(child:Topic)
        MATCH (target:Topic {topic_id: $target_id})-[:ENCOMPASSES]->(child)
        RETURN child.topic_id AS common_child
        LIMIT 1
        """
        
        results = self.client.execute_query(query_case3, params)
        
        if results:
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
             (CASE WHEN r.publish_date =~ '\\d{4}-\\d{2}-\\d{2}' THEN r.publish_date ELSE NULL END) AS publish_date_iso,
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

        // Limit to top 3 documents for focused results (only show highly relevant matches)
        // Unless user explicitly requests more with a higher limit
        LIMIT CASE WHEN $limit < 3 THEN $limit ELSE 3 END        RETURN
            r           AS resource,
            topics      AS topics,
            people      AS people,
            people_with_affiliations AS people_details,
            orgs        AS organisations,
            datasources AS datasources
        """

        return self.client.execute_query(query, params)
