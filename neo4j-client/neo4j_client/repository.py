"""Repository for managing knowledge graph operations."""

from typing import Dict, Any, List, Optional, Tuple
import logging
import json
import os
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
            "Organization": {}  # org_id -> existing_org_id
        }
        
        result = {
            "nodes": {
                "resource": nodes.get("resource"),
                "topics": [],
                "people": [],
                "organizations": []
            },
            "relationships": [],
            "duplicates_found": {
                "topics": [],
                "people": [],
                "organizations": []
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
        

        self.logger.info(f"ID MAPPINGS: {id_mappings}")


        # Update relationships to point to existing nodes
        remapped_relationships = self._remap_relationships(relationships, id_mappings)

        self.logger.info(f"Deduplication complete. Found {len(result['duplicates_found']['topics'])} duplicate topics, {len(result['duplicates_found']['people'])} duplicate people, and {len(result['duplicates_found']['organizations'])} duplicate organizations.")
        
        # Return same structure as input, with duplicates removed and relationships updated
        return {
            "nodes": {
                "resource": result["nodes"]["resource"],
                "topics": result["nodes"]["topics"],
                "people": result["nodes"]["people"],
                "organizations": result["nodes"]["organizations"]
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
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent Resource nodes with optional filters on topics, organisations, and people.

        Dates should be ISO-8601 strings (YYYY-MM-DD). We'll prefer publish_date if present,
        otherwise fall back to scraped_at.

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
            "limit": limit,
        }

        # Safe date handling: Some publish_date values are non-ISO (e.g. 'November 6, 2025').
        # Neo4j date() rejects those. We extract an ISO candidate only if it matches YYYY-MM-DD.
        # Otherwise we treat publish_date as unusable for date comparisons and rely on scraped_at.
        query = """
        WITH
            $topics        AS topics_param,
            $organisations AS orgs_param,
            $people        AS people_param,
            $start         AS start_param,
            $end           AS end_param,
            $limit         AS limit_param

        MATCH (r:Resource)

        WITH r,
             (CASE WHEN r.publish_date =~ '\\d{4}-\\d{2}-\\d{2}' THEN r.publish_date ELSE NULL END) AS publish_date_iso,
             topics_param, orgs_param, people_param, start_param, end_param, limit_param

        OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
        OPTIONAL MATCH (r)-[:MENTIONS]->(p:Person)
        OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
        OPTIONAL MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)

        WITH r,
             publish_date_iso,
             collect(DISTINCT t)  AS topics,
             collect(DISTINCT p)  AS people,
             collect(DISTINCT o)  AS orgs,
             collect(DISTINCT ds) AS datasources,
             topics_param,
             orgs_param,
             people_param,
             start_param,
             end_param,
             limit_param

        WHERE
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
            AND (
                size(topics_param) = 0 OR any(tp IN topics WHERE toLower(tp.name) IN [x IN topics_param | toLower(x)] OR tp.topic_id IN topics_param)
            )
            AND (
                size(orgs_param) = 0 OR any(org IN orgs WHERE toLower(org.name) IN [x IN orgs_param | toLower(x)] OR org.org_id IN orgs_param)
            )
            AND (
                size(people_param) = 0 OR any(pr IN people WHERE toLower(pr.name) IN [x IN people_param | toLower(x)] OR pr.person_id IN people_param)
            )

        WITH r, publish_date_iso, topics, people, orgs, datasources
        ORDER BY coalesce(
                CASE WHEN publish_date_iso IS NOT NULL THEN date(publish_date_iso) ELSE NULL END,
                date(datetime(r.scraped_at))
            ) DESC

        LIMIT $limit

        RETURN
            r           AS resource,
            topics      AS topics,
            people      AS people,
            orgs        AS organisations,
            datasources AS datasources
        """

        return self.client.execute_query(query, params)
