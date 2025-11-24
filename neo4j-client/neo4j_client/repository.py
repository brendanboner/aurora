"""Repository for managing knowledge graph operations."""

from typing import Dict, Any, List, Optional, Tuple
import logging
import json
import os
from pathlib import Path
from datetime import datetime
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
        
        # Initialize Azure OpenAI client for LLM duplicate checking
        # Only initialize if environment variables are present
        self.llm_client = None
        try:
            api_key = os.getenv('AZURE_OPENAI_API_KEY')
            endpoint = os.getenv('AZURE_OPENAI_ENDPOINT')
            api_version = os.getenv('AZURE_OPENAI_API_VERSION', '2024-08-01-preview')
            deployment = os.getenv('AZURE_OPENAI_DEPLOYMENT')
            
            if api_key and endpoint and deployment:
                from openai import AzureOpenAI
                self.llm_client = AzureOpenAI(
                    api_key=api_key,
                    api_version=api_version,
                    azure_endpoint=endpoint
                )
                self.llm_deployment = deployment
                self.logger.info(f"Initialized Azure OpenAI client for duplicate checking with deployment: {deployment}")
            else:
                self.logger.warning("Azure OpenAI credentials not found. LLM duplicate checking will be disabled.")
        except ImportError:
            self.logger.warning("openai package not installed. LLM duplicate checking will be disabled.")
        except Exception as e:
            self.logger.warning(f"Failed to initialize Azure OpenAI client: {e}. LLM duplicate checking will be disabled.")

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
        - Preserves first_seen_at on creation
        
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
                   n.title as old_title,
                   n.first_seen_at as first_seen_at
            """
            existing = self.client.execute_read(fetch_query, {"id_value": node_data[id_field]})
            
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
                
                # Preserve first_seen_at
                if old_data.get('first_seen_at'):
                    node_data['first_seen_at'] = old_data.get('first_seen_at')

        # Prepare query and parameters
        if label == "Resource":
            # For Resources, use special handling to preserve first_seen_at
            query = f"""
            MERGE (n:{label} {{{id_field}: $id_value}})
            ON CREATE SET n += $properties, n.created_at = datetime(), n.first_seen_at = datetime()
            ON MATCH SET n += $properties, n.last_updated = datetime()
            RETURN n
            """
        else:
            # For other nodes, use standard query
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
        
        return result[0] if result else None


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
    
    # ========== Deduplication Operations ==========
    
    def deduplicate_nodes(
        self, 
        nodes_dict: Dict[str, Any],
        k_neighbors: int = 5,
        similarity_threshold: float = 0.85,
        llm_review_threshold: float = 0.65
    ) -> Dict[str, Any]:
        """
        Deduplicate nodes (topics, people, organizations) before insertion.
        
        Process:
        1. Check if node exists by ID (Neo4j MERGE handles this)
        2. Find k nearest neighbors using vector similarity
        3. Score potential duplicates using additional features
        4. Handle duplicates based on score:
           - Above similarity_threshold: Automatic duplicate
           - Between llm_review_threshold and similarity_threshold: Send to LLM for review
           - Below llm_review_threshold: New node
        5. Update relationships to point to existing nodes when duplicates found
        6. Return deduplicated nodes with updated relationships
        
        Args:
            nodes_dict: Dictionary with structure:
                {
                    "nodes": {
                        "resource": resource_model,
                        "topics": [topic_models],
                        "people": [person_models],
                        "organizations": [org_models]
                    },
                    "relationships": [relationship_models]
                }
            k_neighbors: Number of nearest neighbors to check
            similarity_threshold: Minimum similarity score for automatic duplicate (default: 0.85)
            llm_review_threshold: Minimum similarity score to trigger LLM review (default: 0.65)
            
        Returns:
            Dictionary with deduplicated nodes, updated relationships, and merge information
        """

        nodes = nodes_dict.get("nodes", {})
        relationships = nodes_dict.get("relationships", [])
        
        # Track ID mappings: new_id -> existing_id for duplicates
        id_mappings = {
            "Topic": {},      # topic_id -> existing_topic_id
            "Person": {},     # person_id -> existing_person_id
            "Organization": {},  # org_id -> existing_org_id
            "Event": {}       # event_id -> existing_event_id
        }
        
        result = {
            "nodes": {
                "resource": nodes.get("resource"),
                "topics": [],
                "people": [],
                "organizations": [],
                "events": []
            },
            "relationships": [],
            "duplicates_found": {
                "topics": [],
                "people": [],
                "organizations": [],
                "events": []
            }
        }
        
        # Deduplicate topics
        if nodes.get("topics"):
            result["nodes"]["topics"], result["duplicates_found"]["topics"], topic_mappings = \
                self._deduplicate_node_list(
                    nodes["topics"], 
                    "Topic", 
                    k_neighbors, 
                    similarity_threshold,
                    llm_review_threshold
                )
            id_mappings["Topic"] = topic_mappings
        
        # Deduplicate people
        if nodes.get("people"):
            result["nodes"]["people"], result["duplicates_found"]["people"], person_mappings = \
                self._deduplicate_node_list(
                    nodes["people"], 
                    "Person", 
                    k_neighbors, 
                    similarity_threshold,
                    llm_review_threshold
                )
            id_mappings["Person"] = person_mappings
        
        # Deduplicate organizations
        if nodes.get("organizations"):
            result["nodes"]["organizations"], result["duplicates_found"]["organizations"], org_mappings = \
                self._deduplicate_node_list(
                    nodes["organizations"], 
                    "Organization", 
                    k_neighbors, 
                    similarity_threshold,
                    llm_review_threshold
                )
            id_mappings["Organization"] = org_mappings
        
        # Deduplicate events
        if nodes.get("events"):
            result["nodes"]["events"], result["duplicates_found"]["events"], event_mappings = \
                self._deduplicate_node_list(
                    nodes["events"], 
                    "Event", 
                    k_neighbors, 
                    similarity_threshold,
                    llm_review_threshold
                )
            id_mappings["Event"] = event_mappings
        

        self.logger.info(f"ID MAPPINGS: {id_mappings}")


        # Update relationships to point to existing nodes
        remapped_relationships = self._remap_relationships(relationships, id_mappings)

        self.logger.info(f"Deduplication complete. Found {len(result['duplicates_found']['topics'])} duplicate topics, {len(result['duplicates_found']['people'])} duplicate people, {len(result['duplicates_found']['organizations'])} duplicate organizations, and {len(result['duplicates_found']['events'])} duplicate events.")
        
        # Return same structure as input, with duplicates removed and relationships updated
        return {
            "nodes": {
                "resource": result["nodes"]["resource"],
                "topics": result["nodes"]["topics"],
                "people": result["nodes"]["people"],
                "organizations": result["nodes"]["organizations"],
                "events": result["nodes"]["events"]
            },
            "relationships": remapped_relationships
        }
    
    def insert_entities(
        self,
        entities_dict: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Insert deduplicated nodes and relationships into the graph.
        
        This function takes the output from deduplicate_nodes() and creates/updates
        all nodes and relationships in Neo4j. Nodes are inserted first, then relationships.
        
        Args:
            entities_dict: Dictionary with structure (output from deduplicate_nodes):
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
            
            # Insert event nodes
            if nodes.get("events"):
                self.logger.info(f"Inserting {len(nodes['events'])} event nodes...")
                for event in nodes["events"]:
                    self.create_node(event)
                    stats["nodes_created"]["events"] += 1
            
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
                f"{stats['nodes_created']['organizations']} organizations, "
                f"{stats['nodes_created']['events']} events. "
                f"Relationships: {stats['relationships_created']}"
            )
            
        except Exception as e:
            self.logger.error(f"Failed to insert entities: {e}", exc_info=True)
            stats["success"] = False
            raise
        
        return stats
    
    def _deduplicate_node_list(
        self, 
        nodes: List[Node], 
        node_label: str,
        k_neighbors: int,
        similarity_threshold: float,
        llm_review_threshold: float
    ) -> Tuple[List[Node], List[Dict[str, Any]], Dict[str, str]]:
        """
        Deduplicate a list of nodes of the same type.
        
        Args:
            nodes: List of node models to deduplicate
            node_label: Label of the node type (e.g., "Topic", "Person")
            k_neighbors: Number of nearest neighbors to check
            similarity_threshold: Minimum similarity score for automatic duplicate
            llm_review_threshold: Minimum similarity score to trigger LLM review
            
        Returns:
            Tuple of (deduplicated_nodes, duplicates_info, id_mappings)
            where:
            - deduplicated_nodes: nodes that passed deduplication
            - duplicates_info: confirmed duplicates (score >= similarity_threshold or LLM confirmed)
            - id_mappings: dict of {new_id: existing_id} for confirmed duplicates
        """
        deduplicated = []
        duplicates_info = []
        id_mappings = {}  # new_id -> existing_id
        
        for node in nodes:
            node_id = getattr(node, node.id_field)
            
            # Check if node exists by ID
            existing_node = self._get_node_by_id(node, node_label)
            
            if existing_node:
                # Node exists by ID - this is handled by MERGE, but we log it
                self.logger.info(f"{node_label} with ID {node_id} already exists")
                deduplicated.append(node)
                continue
            
            # Find similar nodes using vector similarity
            similar_nodes = self._find_similar_nodes(node, node_label, k_neighbors)
            self.logger.info(f"Similar nodes for {node_label} '{getattr(node, 'name', node_id)}': {len(similar_nodes)} found")
            
            if not similar_nodes:
                # No similar nodes found, keep as new
                deduplicated.append(node)
                continue
            
            # Score potential duplicates
            best_match, best_score = self._score_duplicates(node, similar_nodes, node_label)
            self.logger.info(f"Best match for {node_label} '{getattr(node, 'name', node_id)}': {best_match.get('name', 'N/A')} with score {best_score:.3f}")
            
            is_duplicate = False
            action = ""
            
            if best_score >= similarity_threshold:
                # HIGH CONFIDENCE: Automatic duplicate
                is_duplicate = True
                action = "auto_merge"
                self.logger.info(
                    f"AUTOMATIC DUPLICATE found for {node_label}: "
                    f"new='{getattr(node, 'name', node_id)}' (id={node_id}) "
                    f"existing='{best_match.get('name', best_match.get(node.id_field))}' (id={best_match.get(node.id_field)}) "
                    f"(score={best_score:.3f})"
                )
                
            elif best_score >= llm_review_threshold:
                # MEDIUM CONFIDENCE: Use LLM to decide
                self.logger.info(
                    f"LLM REVIEW for {node_label}: "
                    f"new='{getattr(node, 'name', node_id)}' (id={node_id}) "
                    f"existing='{best_match.get('name', best_match.get(node.id_field))}' (id={best_match.get(node.id_field)}) "
                    f"(score={best_score:.3f})"
                )
                
                # Call LLM to make the decision
                is_duplicate = self._llm_check_duplicate(node, best_match, node_label)
                action = "llm_confirmed_merge" if is_duplicate else "llm_rejected_merge"
                
                if is_duplicate:
                    self.logger.info(
                        f"LLM CONFIRMED DUPLICATE for {node_label}: "
                        f"new='{getattr(node, 'name', node_id)}' -> existing='{best_match.get('name', best_match.get(node.id_field))}'"
                    )
                else:
                    self.logger.info(
                        f"LLM REJECTED DUPLICATE for {node_label}: "
                        f"treating '{getattr(node, 'name', node_id)}' as new node"
                    )
            else:
                # LOW CONFIDENCE: Treat as new node
                self.logger.info(
                    f"NEW NODE: {node_label} '{getattr(node, 'name', node_id)}' "
                    f"(best match score {best_score:.3f} below threshold {llm_review_threshold:.3f})"
                )
            
            # Handle the duplicate decision
            if is_duplicate:
                existing_id = best_match.get(node.id_field)
                id_mappings[node_id] = existing_id
                
                duplicates_info.append({
                    "new_node": node,
                    "new_id": node_id,
                    "existing_node": best_match,
                    "existing_id": existing_id,
                    "similarity_score": best_score,
                    "action": action
                })
                # Don't add to deduplicated list - we'll use the existing node
            else:
                # Not a duplicate - add as new node
                deduplicated.append(node)
        
        return deduplicated, duplicates_info, id_mappings
    
    def _get_node_by_id(self, node: Node, node_label: str) -> Optional[Dict[str, Any]]:
        """
        Check if a node exists in the graph by its ID field.
        
        Args:
            node: Node model instance
            node_label: Label of the node type
            
        Returns:
            Existing node data or None
        """
        id_field = node.id_field
        id_value = getattr(node, id_field)
        
        query = f"MATCH (n:{node_label} {{{id_field}: $id_value}}) RETURN n"
        result = self.client.execute_query(query, {"id_value": id_value})
        
        return result[0] if result else None
    
    def _find_similar_nodes(
        self, 
        node: Node, 
        node_label: str, 
        k: int
    ) -> List[Dict[str, Any]]:
        """
        Find k most similar nodes using vector similarity search.
        
        Args:
            node: Node model instance with embedding
            node_label: Label of the node type
            k: Number of neighbors to return
            
        Returns:
            List of similar nodes with similarity scores
        """
        if not node.embedding:
            self.logger.warning(f"Node has no embedding, cannot find similar nodes")
            return []
        
        # Use Neo4j vector index for similarity search
        query = f"""
        CALL db.index.vector.queryNodes('{node_label.lower()}_embedding_index', $k, $embedding)
        YIELD node, score
        RETURN node, score
        ORDER BY score DESC
        """
        
        try:
            results = self.client.execute_query(query, {
                "k": k,
                "embedding": node.embedding
            })
            return results
        except Exception as e:
            self.logger.warning(f"Vector similarity search failed: {e}")
            return []
    
    def _score_duplicates(
        self, 
        new_node: Node, 
        similar_nodes: List[Dict[str, Any]],
        node_label: str
    ) -> Tuple[Optional[Dict[str, Any]], float]:
        """
        Score potential duplicates using multiple features.
        
        Scoring considers:
        - Vector similarity (from search results) - 50% base weight
        - Name/identifier exact match or similarity - 30% base weight
        - Aliases overlap (for Topics and Organizations) - 20% weight if available
        - Email match (for People) - 20% weight if available
        
        When type-specific features aren't available, their weight is redistributed to name similarity.
        
        Args:
            new_node: New node to check
            similar_nodes: List of similar nodes from vector search
            node_label: Type of node being compared
            
        Returns:
            Tuple of (best_matching_node, best_score)
        """
        if not similar_nodes:
            return None, 0.0
        
        best_match = None
        best_score = 0.0
        
        for item in similar_nodes:
            existing_node = item.get('node', {})
            vector_score = item.get('score', 0.0)
            
            # Start with vector similarity score
            total_score = vector_score * 0.5  # 50% weight
            
            # Calculate name similarity
            name_score = self._calculate_name_similarity(new_node, existing_node, node_label)
            
            # Add type-specific features and adjust weights
            if node_label == "Topic" or node_label == "Organization":
                # Check if aliases are available
                has_aliases = (
                    len(getattr(new_node, 'aliases', [])) > 0 or 
                    len(existing_node.get('aliases', [])) > 0
                )
                
                if has_aliases:
                    # Use base weights: name 30%, aliases 20%
                    alias_score = self._calculate_alias_overlap(new_node, existing_node)
                    total_score += name_score * 0.3
                    total_score += alias_score * 0.2
                else:
                    # No aliases, give all 50% to name similarity
                    total_score += name_score * 0.5
            
            elif node_label == "Person":
                # Check if email is available
                has_email = (
                    getattr(new_node, 'email', None) is not None and
                    existing_node.get('email') is not None
                )
                
                if has_email:
                    # Use base weights: name 30%, email 20%
                    email_score = self._calculate_email_match(new_node, existing_node)
                    total_score += name_score * 0.3
                    total_score += email_score * 0.2
                else:
                    # No email, give all 50% to name similarity
                    total_score += name_score * 0.5
            else:
                # Default: just use name similarity
                total_score += name_score * 0.5
            
            if total_score > best_score:
                best_score = total_score
                best_match = existing_node
        
        return best_match, best_score
    
    def _calculate_name_similarity(
        self, 
        new_node: Node, 
        existing_node: Dict[str, Any],
        node_label: str
    ) -> float:
        """
        Calculate name similarity between two nodes.
        
        Returns:
            Similarity score between 0.0 and 1.0
        """
        new_name = getattr(new_node, 'name', '').lower().strip()
        existing_name = existing_node.get('name', '').lower().strip()
        
        if not new_name or not existing_name:
            return 0.0
        
        # Exact match
        if new_name == existing_name:
            return 1.0
        
        # Simple token-based similarity
        new_tokens = set(new_name.split())
        existing_tokens = set(existing_name.split())
        
        if not new_tokens or not existing_tokens:
            return 0.0
        
        intersection = len(new_tokens & existing_tokens)
        union = len(new_tokens | existing_tokens)
        
        return intersection / union if union > 0 else 0.0
    
    def _calculate_alias_overlap(
        self, 
        new_node: Node, 
        existing_node: Dict[str, Any]
    ) -> float:
        """
        Calculate overlap between aliases of two nodes.
        
        Returns:
            Overlap score between 0.0 and 1.0
        """
        new_aliases = set(a.lower().strip() for a in getattr(new_node, 'aliases', []))
        existing_aliases = set(a.lower().strip() for a in existing_node.get('aliases', []))
        
        # Also include the main name in aliases
        if hasattr(new_node, 'name'):
            new_aliases.add(getattr(new_node, 'name').lower().strip())
        if 'name' in existing_node:
            existing_aliases.add(existing_node['name'].lower().strip())
        
        if not new_aliases or not existing_aliases:
            return 0.0
        
        intersection = len(new_aliases & existing_aliases)
        union = len(new_aliases | existing_aliases)
        
        return intersection / union if union > 0 else 0.0
    
    def _calculate_email_match(
        self, 
        new_node: Node, 
        existing_node: Dict[str, Any]
    ) -> float:
        """
        Calculate email match between two Person nodes.
        
        Returns:
            1.0 for exact match, 0.0 otherwise
        """
        new_email = getattr(new_node, 'email', '').lower().strip()
        existing_email = existing_node.get('email', '').lower().strip()
        
        if not new_email or not existing_email:
            return 0.0
        
        return 1.0 if new_email == existing_email else 0.0
    
    def _remap_relationships(
        self, 
        relationships: List[Relationship],
        id_mappings: Dict[str, Dict[str, str]]
    ) -> List[Relationship]:
        """
        Remap relationships to point to existing nodes when duplicates are found.
        
        Args:
            relationships: List of relationship models
            id_mappings: Nested dict with structure:
                {
                    "Topic": {new_topic_id: existing_topic_id, ...},
                    "Person": {new_person_id: existing_person_id, ...},
                    "Organization": {new_org_id: existing_org_id, ...}
                }
                
        Returns:
            List of relationships with remapped source_id and target_id
        """
        remapped_relationships = []
        
        for rel in relationships:
            # Check if source needs remapping
            source_label = rel.source_node_label
            source_id = rel.source_id
            
            if source_label in id_mappings and source_id in id_mappings[source_label]:
                old_source_id = source_id
                new_source_id = id_mappings[source_label][source_id]
                rel.source_id = new_source_id
                self.logger.info(
                    f"Remapped {rel.relationship_label} source: "
                    f"{source_label}({old_source_id}) -> {source_label}({new_source_id})"
                )
            
            # Check if target needs remapping
            target_label = rel.target_node_label
            target_id = rel.target_id
            
            if target_label in id_mappings and target_id in id_mappings[target_label]:
                old_target_id = target_id
                new_target_id = id_mappings[target_label][target_id]
                rel.target_id = new_target_id
                self.logger.info(
                    f"Remapped {rel.relationship_label} target: "
                    f"{target_label}({old_target_id}) -> {target_label}({new_target_id})"
                )
            
            remapped_relationships.append(rel)
        
        return remapped_relationships

    def _llm_check_duplicate(
        self,
        new_node: Node,
        existing_node: Dict[str, Any],
        node_label: str
    ) -> bool:
        """
        Use LLM to determine if two nodes are duplicates when confidence is uncertain.
        
        Args:
            new_node: New node being considered
            existing_node: Existing node from the database
            node_label: Type of node (Topic, Person, Organization)
            
        Returns:
            True if nodes are duplicates, False otherwise
        """
        # Check if LLM client is available
        if not self.llm_client:
            self.logger.warning(
                f"LLM client not available. Cannot perform LLM duplicate check for {node_label}. "
                "Defaulting to treating nodes as different."
            )
            return False
        
        self.logger.info(f"Performing LLM duplicate check for {node_label}")
        
        # Prepare comparison data
        new_data = {
            "name": getattr(new_node, 'name', ''),
            "aliases": getattr(new_node, 'aliases', []),
        }
        
        existing_data = {
            "name": existing_node.get('name', ''),
            "aliases": existing_node.get('aliases', []),
        }
        
        # Add type-specific fields
        if node_label == "Topic":
            new_data.update({
                "classification": getattr(new_node, 'classification', ''),
                "identifier": getattr(new_node, 'identifier', ''),
                "issuer": getattr(new_node, 'issuer', '')
            })
            existing_data.update({
                "classification": existing_node.get('classification', ''),
                "identifier": existing_node.get('identifier', ''),
                "issuer": existing_node.get('issuer', '')
            })
        elif node_label == "Person":
            new_data["email"] = getattr(new_node, 'email', '')
            existing_data["email"] = existing_node.get('email', '')
        elif node_label == "Organization":
            new_data["org_type"] = getattr(new_node, 'org_type', '')
            existing_data["org_type"] = existing_node.get('org_type', '')
        
        prompt = f"""
            
            You are a data deduplication expert. Determine if these two {node_label} entries refer to the same entity.

            New Entry:
            {json.dumps(new_data, indent=2)}

            Existing Entry:
            {json.dumps(existing_data, indent=2)}

            Consider:
            - Name variations and abbreviations
            - Aliases and alternative names
            - Context-specific identifiers
            - Common naming patterns in this domain
            - A difference in classification, identifier, issuer, org_type, email does not explicitly mean they are different entities if other details align closely. These are just context clues.

            Respond with ONLY 'YES' if they are the same entity, or 'NO' if they are different entities.
            
            """
        
        try:
            response = self.llm_client.chat.completions.create(
                model=self.llm_deployment,
                messages=[
                    {
                        "role": "system", 
                        "content": "You are a data deduplication expert. Respond with only 'YES' or 'NO'."
                    },
                    {
                        "role": "user", 
                        "content": prompt
                    }
                ],
                temperature=0,  # Use deterministic output
                max_tokens=10   # Only need a single word response
            )
            
            answer = response.choices[0].message.content.strip().upper()
            is_duplicate = answer == "YES"
            
            self.logger.info(
                f"LLM response for {node_label} duplicate check: {answer} "
                f"(new='{new_data.get('name')}', existing='{existing_data.get('name')}')"
            )
            
            return is_duplicate
            
        except Exception as e:
            self.logger.error(
                f"LLM duplicate check failed for {node_label}: {e}. "
                "Defaulting to treating nodes as different."
            )
            return False

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
        from datetime import date as date_module
        
        # Default to today if no start_date provided
        if not start_date:
            start_date = date_module.today().isoformat()
        
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
        
        // Find resources that mention this event
        OPTIONAL MATCH (r:Resource)-[:MENTIONS_EVENT]->(e)
        
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
        from datetime import date as date_module
        
        # Default to today if no end_date provided
        if not end_date:
            end_date = date_module.today().isoformat()
        
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
        
        // Find resources that mention this event
        OPTIONAL MATCH (r:Resource)-[:MENTIONS_EVENT]->(e)
        
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
        from datetime import datetime, timedelta
        
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
             collect(DISTINCT ds {.source_id, .name}) AS datasources,
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
            r.first_seen_at AS first_seen_at,
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
        from datetime import datetime
        
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
             collect(DISTINCT ds {.source_id, .name}) AS datasources,
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
            r.first_seen_at AS first_seen_at,
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
        from datetime import datetime
        
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
