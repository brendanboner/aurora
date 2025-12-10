"""
Mock Neo4j Client and GraphRepository for testing.

Provides in-memory implementations that mimic the neo4j_client interfaces
without requiring an actual Neo4j database connection.
"""

from typing import Any, Dict, List, Optional, Type
from datetime import datetime
import logging


class MockNeo4jClient:
    """
    Mock Neo4j client that stores data in memory.
    
    Implements the same interface as neo4j_client.Neo4jClient.
    """
    
    def __init__(
        self,
        uri: str = "bolt://localhost:7687",
        user: str = "neo4j",
        password: str = "password",
        database: str = "neo4j",
        logger_instance: Optional[logging.Logger] = None
    ):
        self.uri = uri
        self.user = user
        self.password = password
        self.database = database
        self.logger = logger_instance or logging.getLogger(__name__)
        
        # In-memory storage
        self._nodes: Dict[str, Dict[str, Any]] = {}  # label:id -> node data
        self._relationships: List[Dict[str, Any]] = []
        self._connected = False
        
        # Track query history for assertions
        self.query_history: List[Dict[str, Any]] = []
    
    def connect(self):
        """Simulate connection."""
        self._connected = True
        self.logger.debug("MockNeo4jClient connected")
    
    def close(self):
        """Simulate disconnection."""
        self._connected = False
        self.logger.debug("MockNeo4jClient closed")
    
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._connected
    
    def execute_query(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Execute a Cypher query (simulated).
        
        This mock implementation handles common query patterns.
        For complex queries, you may need to extend this.
        """
        parameters = parameters or {}
        
        # Record the query
        self.query_history.append({
            "query": query,
            "parameters": parameters,
            "timestamp": datetime.now()
        })
        
        # Handle common query patterns
        query_lower = query.lower()
        
        # Count queries
        if "return count" in query_lower:
            return [{"count": len(self._nodes)}]
        
        # Match all nodes of a type
        if "match (n:" in query_lower or "match (t:" in query_lower:
            label = self._extract_label(query)
            if label:
                matching = [
                    node for key, node in self._nodes.items()
                    if key.startswith(f"{label}:")
                ]
                return matching
        
        # Default: return empty result
        return []
    
    def execute_write(
        self,
        query: str,
        parameters: Optional[Dict[str, Any]] = None
    ) -> Any:
        """Execute a write query (simulated)."""
        parameters = parameters or {}
        self.query_history.append({
            "query": query,
            "parameters": parameters,
            "timestamp": datetime.now(),
            "type": "write"
        })
        return None
    
    def _extract_label(self, query: str) -> Optional[str]:
        """Extract node label from a MATCH query."""
        import re
        match = re.search(r'MATCH\s*\([a-z]+:(\w+)', query, re.IGNORECASE)
        if match:
            return match.group(1)
        return None
    
    # Test helper methods
    def add_node(self, label: str, node_id: str, data: Dict[str, Any]):
        """Add a node to the mock database."""
        key = f"{label}:{node_id}"
        self._nodes[key] = {**data, "_label": label, "_id": node_id}
    
    def add_relationship(
        self,
        source_label: str,
        source_id: str,
        rel_type: str,
        target_label: str,
        target_id: str,
        properties: Optional[Dict[str, Any]] = None
    ):
        """Add a relationship to the mock database."""
        self._relationships.append({
            "source_label": source_label,
            "source_id": source_id,
            "type": rel_type,
            "target_label": target_label,
            "target_id": target_id,
            "properties": properties or {}
        })
    
    def get_node(self, label: str, node_id: str) -> Optional[Dict[str, Any]]:
        """Get a node by label and ID."""
        key = f"{label}:{node_id}"
        return self._nodes.get(key)
    
    def get_all_nodes(self, label: str) -> List[Dict[str, Any]]:
        """Get all nodes of a given label."""
        return [
            node for key, node in self._nodes.items()
            if key.startswith(f"{label}:")
        ]
    
    def clear(self):
        """Clear all data."""
        self._nodes.clear()
        self._relationships.clear()
        self.query_history.clear()


class MockGraphRepository:
    """
    Mock GraphRepository for testing.
    
    Implements the same interface as neo4j_client.GraphRepository.
    """
    
    def __init__(
        self,
        client: MockNeo4jClient,
        logger_instance: Optional[logging.Logger] = None
    ):
        self.client = client
        self.logger = logger_instance or logging.getLogger(__name__)
        
        # Track operations for assertions
        self.created_nodes: List[Any] = []
        self.created_relationships: List[Any] = []
    
    def get_all_nodes(self, node_class: Type) -> List[Dict[str, Any]]:
        """
        Get all nodes of a given type.
        
        Args:
            node_class: The node model class (e.g., Topic, Event)
            
        Returns:
            List of node dictionaries
        """
        label = getattr(node_class, "node_label", node_class.__name__)
        return self.client.get_all_nodes(label)
    
    def create_node(self, node: Any) -> Dict[str, Any]:
        """
        Create a node in the database.
        
        Args:
            node: Node model instance
            
        Returns:
            Created node data
        """
        self.created_nodes.append(node)
        
        label = getattr(node, "node_label", node.__class__.__name__)
        id_field = getattr(node, "id_field", "id")
        node_id = getattr(node, id_field, "unknown")
        
        data = node.to_dict() if hasattr(node, "to_dict") else {}
        self.client.add_node(label, node_id, data)
        
        return data
    
    def create_relationship(self, relationship: Any) -> Dict[str, Any]:
        """
        Create a relationship in the database.
        
        Args:
            relationship: Relationship model instance
            
        Returns:
            Created relationship data
        """
        self.created_relationships.append(relationship)
        
        self.client.add_relationship(
            source_label=relationship.source_node_label,
            source_id=relationship.source_id,
            rel_type=relationship.relationship_label,
            target_label=relationship.target_node_label,
            target_id=relationship.target_id,
            properties=relationship.to_dict() if hasattr(relationship, "to_dict") else {}
        )
        
        return relationship.to_dict() if hasattr(relationship, "to_dict") else {}
    
    def node_exists(self, node_class: Type, node_id: str) -> bool:
        """Check if a node exists."""
        label = getattr(node_class, "node_label", node_class.__name__)
        return self.client.get_node(label, node_id) is not None
    
    def clear(self):
        """Clear all tracked operations."""
        self.created_nodes.clear()
        self.created_relationships.clear()
        self.client.clear()
