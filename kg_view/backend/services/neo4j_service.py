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
        skip: int = 0
    ) -> Dict[str, Any]:
        """
        Get graph nodes and relationships for visualization
        
        Args:
            limit: Maximum number of nodes to return
            node_types: Filter by node types (e.g., ['Topic', 'Organization'])
            skip: Number of nodes to skip (for pagination)
            
        Returns:
            Dictionary with nodes and links arrays
        """
        # Build node filter
        node_filter = ""
        if node_types:
            labels = " OR ".join([f"n:{label}" for label in node_types])
            node_filter = f"WHERE {labels}"
        
        query = f"""
        MATCH (n)
        {node_filter}
        WITH n
        ORDER BY n.importance DESC, n.name ASC, id(n) ASC
        SKIP $skip
        LIMIT $limit
        MATCH (n)-[r]->(m)
        WHERE id(m) >= id(n)
        RETURN 
            collect(DISTINCT {{
                id: id(n),
                label: labels(n)[0],
                name: COALESCE(n.name, n.title, n.topic_id, n.org_id, n.person_id, n.source_id),
                properties: properties(n)
            }}) + 
            collect(DISTINCT {{
                id: id(m),
                label: labels(m)[0],
                name: COALESCE(m.name, m.title, m.topic_id, m.org_id, m.person_id, m.source_id),
                properties: properties(m)
            }}) as nodes,
            collect({{
                source: id(n),
                target: id(m),
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
                'total_returned': len(nodes_dict)
            }
        
        return {'nodes': [], 'links': [], 'total_returned': 0}
    
    def get_topics_autocomplete(self, search: str = "", limit: int = 50) -> List[Dict[str, str]]:
        """
        Get topics for autocomplete with search filter
        
        Args:
            search: Search string to filter topics
            limit: Maximum results to return
            
        Returns:
            List of topics with id, name, and type
        """
        query = """
        MATCH (t:Topic)
        WHERE toLower(t.name) CONTAINS toLower($search)
           OR toLower(t.identifier) CONTAINS toLower($search)
           OR any(alias IN t.aliases WHERE toLower(alias) CONTAINS toLower($search))
        RETURN t.topic_id as id, t.name as name, 'topic' as type, t.classification as classification,
               CASE 
                   WHEN toLower(t.name) = toLower($search) THEN 0
                   WHEN toLower(t.name) STARTS WITH toLower($search) THEN 1
                   WHEN any(alias IN t.aliases WHERE toLower(alias) = toLower($search)) THEN 0
                   WHEN any(alias IN t.aliases WHERE toLower(alias) STARTS WITH toLower($search)) THEN 1
                   ELSE 2
               END as rank
        ORDER BY rank, t.name
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
        node_id: int, 
        hops: int = 2,
        limit: int = 100
    ) -> Dict[str, Any]:
        """
        Get neighborhood of a node up to k hops away
        
        Args:
            node_id: Internal Neo4j node ID
            hops: Number of hops to traverse
            limit: Maximum nodes to return
            
        Returns:
            Dictionary with nodes and links
        """
        query = f"""
        MATCH path = (start)-[*1..{hops}]-(connected)
        WHERE id(start) = $node_id
        WITH start, connected, relationships(path) as rels
        LIMIT $limit
        RETURN 
            collect(DISTINCT {{
                id: id(start),
                label: labels(start)[0],
                name: COALESCE(start.name, start.title, start.topic_id, start.org_id),
                properties: properties(start)
            }}) +
            collect(DISTINCT {{
                id: id(connected),
                label: labels(connected)[0],
                name: COALESCE(connected.name, connected.title, connected.topic_id, connected.org_id),
                properties: properties(connected)
            }}) as nodes,
            [rel IN rels | {{
                source: id(startNode(rel)),
                target: id(endNode(rel)),
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
            id(n) as id,
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
            id: id(node),
            label: labels(node)[0],
            name: COALESCE(node.name, node.title, node.topic_id, node.org_id, node.person_id),
            properties: properties(node)
        }}) as allNodes, paths
        
        UNWIND paths as p2
        UNWIND relationships(p2) as rel
        WITH allNodes, collect(DISTINCT {{
            source: id(startNode(rel)),
            target: id(endNode(rel)),
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
