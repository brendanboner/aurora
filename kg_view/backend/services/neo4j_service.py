"""
Neo4j Service for Knowledge Graph Visualizer
Provides graph data access using the neo4j-client library
"""
import os
import sys
from typing import Dict, List, Optional, Any
from datetime import datetime

# Add neo4j-client to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../neo4j-client'))

from neo4j_client import Neo4jClient, GraphRepository
from neo4j.exceptions import Neo4jError


class Neo4jService:
    """Service for interacting with Neo4j knowledge graph"""
    
    def __init__(self):
        self.client = None
        self.repo = None
        self._initialize_client()
    
    def _initialize_client(self):
        """Initialize Neo4j client with environment variables"""
        uri = os.getenv('NEO4J_URI', 'bolt://localhost:7687')
        user = os.getenv('NEO4J_USER', 'neo4j')
        password = os.getenv('NEO4J_PASSWORD', 'password')
        database = os.getenv('NEO4J_DATABASE', 'neo4j')
        
        self.client = Neo4jClient(uri=uri, user=user, password=password, database=database)
        self.client.connect()
        self.repo = GraphRepository(self.client)
    
    def get_graph_stats(self) -> Dict[str, Any]:
        """Get statistics about the graph structure"""
        query = """
        CALL apoc.meta.stats() YIELD labels, relTypesCount
        RETURN labels, relTypesCount
        """
        
        # Fallback query without APOC
        fallback_query = """
        MATCH (n)
        WITH labels(n) as nodeLabels, count(*) as count
        UNWIND nodeLabels as label
        WITH label, sum(count) as totalCount
        WITH collect({label: label, count: totalCount}) as nodeCounts
        MATCH ()-[r]->()
        WITH nodeCounts, type(r) as relType, count(*) as relCount
        WITH nodeCounts, collect({type: relType, count: relCount}) as relCounts
        RETURN nodeCounts, relCounts
        """
        
        try:
            # Try APOC first for performance
            result = self.client.execute_query(query)
            if result:
                return {
                    'nodes': result[0].get('labels', {}),
                    'relationships': result[0].get('relTypesCount', 0),
                    'timestamp': datetime.now().isoformat()
                }
        except Neo4jError:
            pass
        
        # Use fallback
        result = self.client.execute_query(fallback_query)
        if result:
            node_counts = {item['label']: item['count'] for item in result[0].get('nodeCounts', [])}
            rel_counts = {item['type']: item['count'] for item in result[0].get('relCounts', [])}
            total_rels = sum(rel_counts.values())
            
            return {
                'nodes': node_counts,
                'relationships': total_rels,
                'relationship_types': rel_counts,
                'timestamp': datetime.now().isoformat()
            }
        
        return {'nodes': {}, 'relationships': 0, 'timestamp': datetime.now().isoformat()}
    
    def execute_cypher(self, query: str, parameters: Optional[Dict] = None, timeout: int = 10) -> List[Dict]:
        """
        Execute a Cypher query with timeout and read-only mode
        
        Args:
            query: Cypher query string
            parameters: Query parameters
            timeout: Query timeout in seconds
            
        Returns:
            List of result records as dictionaries
        """
        # Add timeout to query
        escaped_query = query.replace("'", "\\'")
        query_with_timeout = f"CALL apoc.cypher.runTimeboxed('{escaped_query}', {{}}, {timeout * 1000}) YIELD value RETURN value"
        
        try:
            # Try with APOC timeout
            results = self.client.execute_query(query_with_timeout, parameters or {})
            return [dict(record['value']) for record in results]
        except Neo4jError:
            # Fallback without APOC
            results = self.client.execute_query(query, parameters or {})
            return [dict(record) for record in results]
    
    def get_graph_data(
        self, 
        limit: int = 1000, 
        node_types: Optional[List[str]] = None,
        skip: int = 0,
        importance_threshold: float = 0.0,
        curated_only: bool = False
    ) -> Dict[str, Any]:
        """
        Get graph nodes and relationships for visualization with importance-based filtering
        
        Args:
            limit: Maximum number of nodes to return
            node_types: Filter by node types (e.g., ['Topic', 'Organization'])
            skip: Number of nodes to skip (for pagination)
            importance_threshold: Minimum importance score (0-1) for nodes to include
            curated_only: If True, only return curated/important nodes (high quality content)
            
        Returns:
            Dictionary with nodes and links arrays plus metadata
        """
        # Build node filter
        node_filter = ""
        if node_types:
            labels = " OR ".join([f"n:{label}" for label in node_types])
            node_filter = f"WHERE {labels}"
        
        # Add importance threshold filter
        importance_filter = f"AND COALESCE(n.importance, 0) >= {importance_threshold}" if importance_threshold > 0 else ""
        
        query = f"""
        MATCH (n)
        {node_filter}
        {importance_filter}
        WITH n
        ORDER BY n.importance DESC, n.name ASC, elementId(n) ASC
        SKIP $skip
        LIMIT $limit
        MATCH (n)-[r]->(m)
        WHERE elementId(m) >= elementId(n)
        RETURN 
            collect(DISTINCT {{
                id: elementId(n),
                label: labels(n)[0],
                name: COALESCE(n.name, n.title, n.topic_id, n.org_id, n.person_id, n.source_id),
                importance: COALESCE(n.importance, 0),
                tier: COALESCE(n.tier, 2),
                properties: properties(n)
            }}) + 
            collect(DISTINCT {{
                id: elementId(m),
                label: labels(m)[0],
                name: COALESCE(m.name, m.title, m.topic_id, m.org_id, m.person_id, m.source_id),
                importance: COALESCE(m.importance, 0),
                tier: COALESCE(m.tier, 2),
                properties: properties(m)
            }}) as nodes,
            collect({{
                source: elementId(n),
                target: elementId(m),
                type: type(r),
                properties: properties(r)
            }}) as links
        """
        
        results = self.client.execute_query(query, {'skip': skip, 'limit': limit})
        
        if results:
            # Deduplicate nodes
            nodes_dict = {}
            for node in results[0].get('nodes', []):
                node_id = node['id']
                if node_id not in nodes_dict:
                    nodes_dict[node_id] = node
            
            return {
                'nodes': list(nodes_dict.values()),
                'links': results[0].get('links', []),
                'total_returned': len(nodes_dict),
                'importance_threshold': importance_threshold,
                'curated_only': curated_only
            }
        
        return {'nodes': [], 'links': [], 'total_returned': 0, 'importance_threshold': importance_threshold, 'curated_only': curated_only}
    
    def get_topics_autocomplete(self, search: str = "", limit: int = 50, curated_only: bool = False) -> List[Dict[str, str]]:
        """
        Get topics for autocomplete with search filter and tier-aware results
        
        Args:
            search: Search string to filter topics
            limit: Maximum results to return
            curated_only: If True, only return tier 0-1 (top-level curated) topics
            
        Returns:
            List of topics with id, name, type, and tier information
        """
        tier_filter = "AND (t.tier <= 1 OR t.tier IS NULL)" if curated_only else ""
        query = f"""
        MATCH (t:Topic)
        WHERE (toLower(t.name) CONTAINS toLower($search)
           OR toLower(t.identifier) CONTAINS toLower($search)
           OR any(alias IN t.aliases WHERE toLower(alias) CONTAINS toLower($search)))
        {tier_filter}
        RETURN t.topic_id as id, t.name as name, 'topic' as type, t.classification as classification,
               COALESCE(t.tier, 2) as tier, COALESCE(t.importance, 0) as importance,
               CASE 
                   WHEN toLower(t.name) = toLower($search) THEN 0
                   WHEN toLower(t.name) STARTS WITH toLower($search) THEN 1
                   WHEN any(alias IN t.aliases WHERE toLower(alias) = toLower($search)) THEN 0
                   WHEN any(alias IN t.aliases WHERE toLower(alias) STARTS WITH toLower($search)) THEN 1
                   ELSE 2
               END as rank
        ORDER BY rank, COALESCE(t.importance, 0) DESC, t.name
        LIMIT $limit
        """
        
        results = self.client.execute_query(query, {'search': search, 'limit': limit})
        return [dict(record) for record in results]
    
    def get_organizations_autocomplete(self, search: str = "", limit: int = 50) -> List[Dict[str, str]]:
        """Get organizations for autocomplete"""
        query = """
        MATCH (o:Organization)
        WHERE toLower(o.name) CONTAINS toLower($search)
           OR any(alias IN o.aliases WHERE toLower(alias) CONTAINS toLower($search))
        RETURN o.org_id as id, o.name as name, 'organization' as type, o.org_type as classification,
               CASE 
                   WHEN toLower(o.name) = toLower($search) THEN 0
                   WHEN toLower(o.name) STARTS WITH toLower($search) THEN 1
                   WHEN any(alias IN o.aliases WHERE toLower(alias) = toLower($search)) THEN 0
                   WHEN any(alias IN o.aliases WHERE toLower(alias) STARTS WITH toLower($search)) THEN 1
                   ELSE 2
               END as rank
        ORDER BY rank, o.name
        LIMIT $limit
        """
        
        results = self.client.execute_query(query, {'search': search, 'limit': limit})
        return [dict(record) for record in results]
    
    def get_people_autocomplete(self, search: str = "", limit: int = 50) -> List[Dict[str, str]]:
        """Get people for autocomplete"""
        query = """
        MATCH (p:Person)
        WHERE toLower(p.name) CONTAINS toLower($search)
           OR toLower(p.email) CONTAINS toLower($search)
        RETURN p.person_id as id, p.name as name, 'person' as type, p.email as email
        ORDER BY p.name
        LIMIT $limit
        """
        
        results = self.client.execute_query(query, {'search': search, 'limit': limit})
        return [dict(record) for record in results]
    
    def get_events_autocomplete(self, search: str = "", limit: int = 50) -> List[Dict[str, str]]:
        """Get events for autocomplete"""
        query = """
        MATCH (e:Event)
        WHERE toLower(e.name) CONTAINS toLower($search)
           OR toLower(e.description) CONTAINS toLower($search)
           OR toLower(e.event_type) CONTAINS toLower($search)
        RETURN e.url as id, e.name as name, 'event' as type, e.event_type as classification, e.start_date as start_date
        ORDER BY e.start_date DESC, e.name
        LIMIT $limit
        """
        
        results = self.client.execute_query(query, {'search': search, 'limit': limit})
        return [dict(record) for record in results]
    
    def get_node_neighborhood(
        self, 
        node_id: str,  # Changed to str to support elementId format
        hops: int = 2,
        limit: int = 100,
        load_child_topics: bool = False
    ) -> Dict[str, Any]:
        """
        Get neighborhood of a node up to k hops away, with optional child topic loading
        
        Args:
            node_id: Neo4j elementId string (format: '4:uuid:internal_id')
            hops: Number of hops to traverse
            limit: Maximum nodes to return
            load_child_topics: If True and node is a topic, also load child topics via ENCOMPASSES
            
        Returns:
            Dictionary with nodes and links
        """
        query = f"""
        MATCH path = (start)-[*1..{hops}]-(connected)
        WHERE elementId(start) = $node_id
        WITH start, connected, relationships(path) as rels
        LIMIT $limit
        RETURN 
            collect(DISTINCT {{
                id: elementId(start),
                label: labels(start)[0],
                name: COALESCE(start.name, start.title, start.topic_id, start.org_id),
                importance: COALESCE(start.importance, 0),
                tier: COALESCE(start.tier, 2),
                properties: properties(start)
            }}) +
            collect(DISTINCT {{
                id: elementId(connected),
                label: labels(connected)[0],
                name: COALESCE(connected.name, connected.title, connected.topic_id, connected.org_id),
                importance: COALESCE(connected.importance, 0),
                tier: COALESCE(connected.tier, 2),
                properties: properties(connected)
            }}) as nodes,
            [rel IN rels | {{
                source: elementId(startNode(rel)),
                target: elementId(endNode(rel)),
                type: type(rel),
                properties: properties(rel)
            }}] as links
        """
        
        results = self.client.execute_query(query, {'node_id': node_id, 'limit': limit})
        
        if results:
            # Flatten links array
            all_links = []
            for result in results:
                all_links.extend(result.get('links', []))
            
            # Deduplicate nodes
            nodes_dict = {}
            for result in results:
                for node in result.get('nodes', []):
                    node_id = node['id']
                    if node_id not in nodes_dict:
                        nodes_dict[node_id] = node
            
            return {
                'nodes': list(nodes_dict.values()),
                'links': all_links
            }
        
        return {'nodes': [], 'links': []}
    
    def search_nodes(self, search_text: str, limit: int = 100) -> List[Dict[str, Any]]:
        """
        Full-text search across all node types
        
        Args:
            search_text: Text to search for
            limit: Maximum results
            
        Returns:
            List of matching nodes
        """
        query = """
        MATCH (n)
        WHERE toLower(n.name) CONTAINS toLower($search)
           OR toLower(n.title) CONTAINS toLower($search)
           OR toLower(n.summary) CONTAINS toLower($search)
           OR any(alias IN COALESCE(n.aliases, []) WHERE toLower(alias) CONTAINS toLower($search))
        RETURN 
            elementId(n) as id,
            labels(n)[0] as label,
            COALESCE(n.name, n.title, n.topic_id, n.org_id) as name,
            properties(n) as properties
        ORDER BY 
            CASE 
                WHEN toLower(n.name) = toLower($search) THEN 0
                WHEN toLower(n.title) = toLower($search) THEN 0
                WHEN toLower(n.name) STARTS WITH toLower($search) THEN 1
                WHEN toLower(n.title) STARTS WITH toLower($search) THEN 1
                ELSE 2
            END,
            n.importance DESC,
            name ASC
        LIMIT $limit
        """
        
        results = self.client.execute_query(query, {'search': search_text, 'limit': limit})
        return [dict(record) for record in results]
    
    def get_entity_subgraph(
        self,
        entity_ids: List[str],
        hops: int = 3,
        limit: int = 500
    ) -> Dict[str, Any]:
        """
        Get subgraph connecting multiple entities
        
        Args:
            entity_ids: List of entity identifiers (topic_id, org_id, person_id, etc.)
            hops: Maximum path length between entities
            limit: Maximum nodes to return
            
        Returns:
            Dictionary with nodes and links connecting the entities
        """
        if not entity_ids:
            return {'nodes': [], 'links': []}
        
        # Simpler approach: find entities and get their neighborhoods
        query = f"""
        MATCH (entity)
        WHERE entity.topic_id IN $entity_ids
           OR entity.org_id IN $entity_ids
           OR entity.person_id IN $entity_ids
           OR entity.name IN $entity_ids
        
        // Get all paths between these entities within hop limit
        MATCH path = (entity)-[*1..{hops}]-(connected)
        WHERE connected.topic_id IN $entity_ids
           OR connected.org_id IN $entity_ids
           OR connected.person_id IN $entity_ids
           OR connected.name IN $entity_ids
        
        WITH collect(path) as paths
        LIMIT {limit}
        
        // Extract unique nodes and relationships
        UNWIND paths as p
        UNWIND nodes(p) as node
        WITH collect(DISTINCT {{
            id: elementId(node),
            label: labels(node)[0],
            name: COALESCE(node.name, node.title, node.topic_id, node.org_id, node.person_id),
            properties: properties(node)
        }}) as allNodes, paths
        
        UNWIND paths as p2
        UNWIND relationships(p2) as rel
        WITH allNodes, collect(DISTINCT {{
            source: elementId(startNode(rel)),
            target: elementId(endNode(rel)),
            type: type(rel),
            properties: properties(rel)
        }}) as allLinks
        
        RETURN allNodes as nodes, allLinks as links
        """
        
        results = self.client.execute_query(query, {
            'entity_ids': entity_ids
        })
        
        if results and len(results) > 0:
            return {
                'nodes': results[0].get('nodes', []),
                'links': results[0].get('links', [])
            }
        
        return {'nodes': [], 'links': []}
    
    def close(self):
        """Close the Neo4j connection"""
        if self.client:
            self.client.close()
