"""
Service for deduplicating nodes before insertion into the knowledge graph.

This service provides flexible duplicate detection for both batch processing
and individual node checking:

1. Batch Processing: Use `deduplicate_nodes()` to process multiple nodes at once
   (used by the Digester service)

2. Individual Checking: Use `find_duplicate()` or convenience methods like
   `check_topic_duplicate()` to check single nodes (useful for Curator, API, etc.)

The service queries the graph using vector similarity search and additional
scoring features (name, aliases, email) to identify duplicates with configurable
confidence thresholds. For uncertain cases, it can optionally use an LLM for review.
"""

from typing import Dict, Any, List, Optional, Tuple
import logging
import json
import os
import re
from .models import Node, Relationship
from .repository import GraphRepository


logger = logging.getLogger(__name__)


class NodeDeduplicator:
    """
    Service for deduplicating nodes (topics, people, organizations) before insertion.
    
    This service handles the deduplication process without modifying the graph.
    It queries the graph to find potential duplicates, scores them using various
    similarity metrics, and optionally uses an LLM for uncertain cases.
    """
    
    def __init__(self, client, logger_instance: Optional[logging.Logger] = None):
        """
        Initialize deduplicator.
        
        Args:
            client: Neo4jClient instance for querying the graph
            logger_instance: Optional logger instance
        """
        self.client = client
        self.logger = logger_instance or logger
        
        # Initialize repository for graph operations
        self.repository = GraphRepository(client, logger_instance)
        
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

    def find_duplicate(
        self,
        node: Node,
        node_label: str,
        k_neighbors: int = 5,
        similarity_threshold: float = 0.85,
        llm_review_threshold: float = 0.6
    ) -> Optional[Dict[str, Any]]:
        """
        Find a duplicate for a single node.
        
        This is a public method that can be used by any service to check if a node
        already exists in the graph.
        
        Args:
            node: Node model instance to check for duplicates
            node_label: Label of the node type (e.g., "Topic", "Person", "Organization")
            k_neighbors: Number of nearest neighbors to check
            similarity_threshold: Minimum similarity score for automatic duplicate
            llm_review_threshold: Minimum similarity score to trigger LLM review
            
        Returns:
            Dictionary with duplicate information if found:
            {
                "existing_node": {...},
                "existing_id": "id_value",
                "similarity_score": 0.92,
                "action": "auto_merge" | "llm_confirmed_merge"
            }
            Or None if no duplicate found.
        """
        node_id = getattr(node, node.id_field)
        
        # Check if node exists by ID using repository
        existing_node = self.repository.get_node(node)
        
        if existing_node:
            # Node exists by ID - exact match
            self.logger.info(f"{node_label} with ID {node_id} already exists")
            return {
                "is_duplicate": True,
                "existing_node": existing_node,
                "existing_id": existing_node.get(node.id_field),
                "similarity_score": 1.0,
                "action": "exact_id_match"
            }
        
        # Find similar nodes using vector similarity
        similar_nodes = self._find_similar_nodes(node, node_label, k_neighbors)
        self.logger.info(f"Similar nodes for {node_label} '{getattr(node, 'name', node_id)}': {len(similar_nodes)} found")
        
        if not similar_nodes:
            # No similar nodes found
            return None
        
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
        
        # Return result - either duplicate info or best match for debugging
        if is_duplicate:
            return {
                "is_duplicate": True,
                "existing_node": best_match,
                "existing_id": best_match.get(node.id_field),
                "similarity_score": best_score,
                "action": action
            }
        else:
            # Not a duplicate, but return best match info for debugging
            return {
                "is_duplicate": False,
                "existing_node": best_match,
                "existing_id": best_match.get(node.id_field),
                "similarity_score": best_score,
                "action": "new_node"
            }

    def check_topic_duplicate(
        self,
        topic: Node,
        k_neighbors: int = 5,
        similarity_threshold: float = 0.85,
        llm_review_threshold: float = 0.6
    ) -> Optional[Dict[str, Any]]:
        """
        Convenience method to check for duplicate topics.
        
        Args:
            topic: Topic node to check
            k_neighbors: Number of nearest neighbors to check
            similarity_threshold: Minimum similarity score for automatic duplicate
            llm_review_threshold: Minimum similarity score to trigger LLM review
            
        Returns:
            Duplicate information if found, None otherwise
        """
        return self.find_duplicate(
            topic,
            "Topic",
            k_neighbors=k_neighbors,
            similarity_threshold=similarity_threshold,
            llm_review_threshold=llm_review_threshold
        )
    
    def check_person_duplicate(
        self,
        person: Node,
        k_neighbors: int = 5,
        similarity_threshold: float = 0.85,
        llm_review_threshold: float = 0.6
    ) -> Optional[Dict[str, Any]]:
        """
        Convenience method to check for duplicate people.
        
        Args:
            person: Person node to check
            k_neighbors: Number of nearest neighbors to check
            similarity_threshold: Minimum similarity score for automatic duplicate
            llm_review_threshold: Minimum similarity score to trigger LLM review
            
        Returns:
            Duplicate information if found, None otherwise
        """
        return self.find_duplicate(
            person,
            "Person",
            k_neighbors=k_neighbors,
            similarity_threshold=similarity_threshold,
            llm_review_threshold=llm_review_threshold
        )
    
    def check_organization_duplicate(
        self,
        organization: Node,
        k_neighbors: int = 5,
        similarity_threshold: float = 0.85,
        llm_review_threshold: float = 0.6
    ) -> Optional[Dict[str, Any]]:
        """
        Convenience method to check for duplicate organizations.
        
        Args:
            organization: Organization node to check
            k_neighbors: Number of nearest neighbors to check
            similarity_threshold: Minimum similarity score for automatic duplicate
            llm_review_threshold: Minimum similarity score to trigger LLM review
            
        Returns:
            Duplicate information if found, None otherwise
        """
        return self.find_duplicate(
            organization,
            "Organization",
            k_neighbors=k_neighbors,
            similarity_threshold=similarity_threshold,
            llm_review_threshold=llm_review_threshold
        )

    def deduplicate_nodes(
        self, 
        nodes_dict: Dict[str, Any],
        k_neighbors: int = 5,
        similarity_threshold: float = 0.85,
        llm_review_threshold: float = 0.6
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
            llm_review_threshold: Minimum similarity score to trigger LLM review (default: 0.6)
            
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
            
            # Use the public find_duplicate method
            duplicate_info = self.find_duplicate(
                node,
                node_label,
                k_neighbors=k_neighbors,
                similarity_threshold=similarity_threshold,
                llm_review_threshold=llm_review_threshold
            )
            
            if duplicate_info and duplicate_info.get("is_duplicate"):
                # Found a duplicate (either exact ID match or similarity match)
                # Map the ID and track as duplicate - don't insert again
                existing_id = duplicate_info["existing_id"]
                id_mappings[node_id] = existing_id
                
                # Merge aliases from duplicate node into existing node
                self._merge_aliases(
                    node, 
                    duplicate_info["existing_node"], 
                    node_label
                )
                
                duplicates_info.append({
                    "new_node": node,
                    "new_id": node_id,
                    "existing_node": duplicate_info["existing_node"],
                    "existing_id": existing_id,
                    "similarity_score": duplicate_info["similarity_score"],
                    "action": duplicate_info["action"]
                })
                
                self.logger.info(
                    f"Duplicate {node_label} found: '{getattr(node, 'name', node_id)}' "
                    f"matches existing '{duplicate_info['existing_node'].get('name')}' "
                    f"(action: {duplicate_info['action']}, score: {duplicate_info['similarity_score']:.3f})"
                )
                # Don't add to deduplicated list - we'll use the existing node
            else:
                # Not a duplicate - add as new node
                # Store deduplication metadata for debugging (shows closest match considered)
                if duplicate_info:
                    node.deduplication_best_match_id = duplicate_info["existing_id"]
                    node.deduplication_best_match_name = duplicate_info["existing_node"].get("name")
                    node.deduplication_score = duplicate_info["similarity_score"]
                
                deduplicated.append(node)
        
        return deduplicated, duplicates_info, id_mappings
    
    def _merge_aliases(
        self,
        duplicate_node: Node,
        existing_node: Dict[str, Any],
        node_label: str
    ) -> None:
        """
        Merge aliases from duplicate node into existing node in the database.
        
        This enriches the existing node with alternative names from duplicates,
        improving future duplicate detection.
        
        Args:
            duplicate_node: The duplicate node being merged
            existing_node: The existing node in the database
            node_label: Type of node (Topic, Person, Organization)
        """
        # Only merge aliases for node types that have aliases
        if node_label not in ["Topic", "Organization"]:
            return
        
        # Get existing aliases from database node
        existing_aliases = set(existing_node.get('aliases', []))
        
        # Get new aliases from duplicate node
        new_aliases = set(getattr(duplicate_node, 'aliases', []))
        
        # Add the duplicate node's name to aliases (this is key!)
        duplicate_name = getattr(duplicate_node, 'name', '')
        if duplicate_name:
            new_aliases.add(duplicate_name)
        
        # Union the aliases
        merged_aliases = existing_aliases | new_aliases
        
        # Remove the existing node's main name from aliases if present
        existing_name = existing_node.get('name', '')
        if existing_name in merged_aliases:
            merged_aliases.discard(existing_name)
        
        # Check if there are new aliases to add
        new_aliases_to_add = merged_aliases - existing_aliases
        
        if new_aliases_to_add:
            # Update the node in the database
            id_field = duplicate_node.id_field
            existing_id = existing_node.get(id_field)
            
            # Convert back to list for Neo4j
            merged_aliases_list = sorted(list(merged_aliases))
            
            query = f"""
            MATCH (n:{node_label} {{{id_field}: $id_value}})
            SET n.aliases = $aliases, n.last_updated = datetime()
            RETURN n
            """
            
            try:
                self.client.execute_write(query, {
                    "id_value": existing_id,
                    "aliases": merged_aliases_list
                })
                
                self.logger.info(
                    f"Merged aliases for {node_label} '{existing_name}': "
                    f"added {len(new_aliases_to_add)} new aliases: {sorted(list(new_aliases_to_add))}"
                )
            except Exception as e:
                self.logger.error(f"Failed to merge aliases for {node_label} {existing_id}: {e}")
        else:
            self.logger.debug(f"No new aliases to merge for {node_label} '{existing_name}'")
    
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
        - Vector similarity (from search results) - 50% weight
        - Name/label similarity (includes aliases) - 30% weight
        - Email match (for People only) - 20% weight if available
        
        Note: Name similarity now compares all labels (name + aliases) for both nodes,
        so we don't need a separate alias overlap calculation.
        
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
            # Extract node - handle both raw dict and Cypher node wrapper
            raw_node = item.get('node', {})
            # If it's a Cypher result with 'n' wrapper, extract it
            existing_node = raw_node if not isinstance(raw_node, dict) or 'n' not in raw_node else raw_node.get('n', {})
            vector_score = item.get('score', 0.0)

            self.logger.info(f"Scoring potential duplicate: existing_node='{existing_node.get('name', 'N/A')}', vector_score={vector_score:.3f}")

            # Start with vector similarity score (50% weight)
            total_score = vector_score * 0.5
            
            # Calculate name similarity (already includes aliases comparison)
            name_score = self._calculate_name_similarity(new_node, existing_node, node_label)
            
            # Add name score and email score if applicable
            if node_label == "Person":
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
                # For Topics and Organizations, name similarity already includes aliases
                # Give full 50% weight to name similarity
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
        Calculate name similarity between two nodes by comparing all labels (name + aliases).
        
        For each pair of labels, we check:
        1. Exact match (case-insensitive)
        2. Jaccard similarity (token-based)
        
        Returns the maximum score found across all label pairs.
        
        Returns:
            Similarity score between 0.0 and 1.0
        """
        # Build labels list for new node (name + aliases)
        new_labels = []
        new_name = getattr(new_node, 'name', '').strip()
        if new_name:
            new_labels.append(new_name)
        new_aliases = getattr(new_node, 'aliases', [])
        new_labels.extend([a.strip() for a in new_aliases if a.strip()])
        
        # Build labels list for existing node (name + aliases)
        existing_labels = []
        existing_name = existing_node.get('name', '').strip()
        if existing_name:
            existing_labels.append(existing_name)
        existing_aliases = existing_node.get('aliases', [])
        existing_labels.extend([a.strip() for a in existing_aliases if a.strip()])
        
        # If either node has no labels, return 0
        if not new_labels or not existing_labels:
            return 0.0
        
        max_score = 0.0
        
        # Compare every label from new_labels to every label in existing_labels
        for new_label in new_labels:
            for existing_label in existing_labels:
                # Check for exact match (case-insensitive)
                if new_label.lower() == existing_label.lower():
                    return 1.0  # Perfect match - return immediately
                
                # Calculate Jaccard similarity (token-based)
                # Tokenize: lowercase, split on whitespace and punctuation
                new_tokens = set(re.findall(r'\w+', new_label.lower()))
                existing_tokens = set(re.findall(r'\w+', existing_label.lower()))
                
                if new_tokens and existing_tokens:
                    intersection = len(new_tokens & existing_tokens)
                    union = len(new_tokens | existing_tokens)
                    jaccard_score = intersection / union if union > 0 else 0.0
                    
                    # Track maximum score
                    max_score = max(max_score, jaccard_score)
        
        return max_score
    
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
            self.logger.error(f"LLM duplicate check failed: {e}", exc_info=True)
            return False
