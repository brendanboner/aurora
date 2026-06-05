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
        WITH n, COUNT {{ (n)--() }} as degree
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
                properties: properties(n),
                degree: degree
            }}) + 
            collect(DISTINCT {{
                id: elementId(m),
                label: labels(m)[0],
                name: COALESCE(m.name, m.title, m.topic_id, m.org_id, m.person_id, m.source_id),
                importance: COALESCE(m.importance, 0),
                tier: COALESCE(m.tier, 2),
                properties: properties(m),
                degree: COUNT {{ (m)--() }}
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
    
    def get_balanced_graph_data(
        self,
        total_limit: int = 1000,
        importance_threshold: float = 0.0
    ) -> Dict[str, Any]:
        """
        Get graph data with balanced sampling across all node types to ensure diversity
        
        Args:
            total_limit: Total maximum number of nodes to return
            importance_threshold: Minimum importance score (0-1) for nodes to include
            
        Returns:
            Dictionary with nodes and links arrays with balanced representation
        """
        # Define node types and their target proportions
        # This ensures we get a diverse view of the graph
        node_type_config = {
            'Resource': 0.35,      # 35% - Documents, articles, specs
            'Topic': 0.20,         # 20% - Reduced from 14k to prevent dominance
            'Event': 0.15,         # 15% - Conferences, webinars
            'Organization': 0.15,  # 15% - Companies, standards bodies
            'Person': 0.15,        # 15% - Authors, experts
        }
        
        all_nodes = []
        node_ids = set()
        
        # Get stats to understand actual distribution
        stats = self.get_graph_stats()
        node_counts = stats.get('nodes', {})
        
        # Calculate limits for each type based on proportions
        for node_type, proportion in node_type_config.items():
            type_limit = int(total_limit * proportion)
            actual_count = node_counts.get(node_type, 0)
            
            # If type has fewer nodes than limit, use actual count
            if actual_count > 0 and actual_count < type_limit:
                type_limit = actual_count
            
            if type_limit > 0:
                # Query for this specific node type
                importance_filter = f"AND COALESCE(n.importance, 0) >= {importance_threshold}" if importance_threshold > 0 else ""
                
                query = f"""
                MATCH (n:{node_type})
                WHERE 1=1
                {importance_filter}
                WITH n, COUNT {{ (n)--() }} as degree
                ORDER BY n.importance DESC, n.name ASC, elementId(n) ASC
                LIMIT $limit
                RETURN 
                    elementId(n) as id,
                    labels(n)[0] as label,
                    COALESCE(n.name, n.title, n.topic_id, n.org_id, n.person_id, n.source_id) as name,
                    COALESCE(n.importance, 0) as importance,
                    COALESCE(n.tier, 2) as tier,
                    properties(n) as properties,
                    degree
                """
                
                try:
                    results = self.client.execute_query(query, {'limit': type_limit})
                    for record in results:
                        node_id = record['id']
                        if node_id not in node_ids:
                            all_nodes.append({
                                'id': node_id,
                                'label': record['label'],
                                'name': record['name'],
                                'importance': record['importance'],
                                'tier': record['tier'],
                                'properties': record['properties'],
                                'degree': record['degree']
                            })
                            node_ids.add(node_id)
                except Exception as e:
                    print(f"Warning: Failed to fetch {node_type} nodes: {e}")
        
        # Now get relationships between the selected nodes
        if all_nodes:
            # Build a query to get all relationships between our selected nodes
            links_query = """
            MATCH (n)-[r]->(m)
            WHERE elementId(n) IN $node_ids AND elementId(m) IN $node_ids
            RETURN 
                elementId(n) as source,
                elementId(m) as target,
                type(r) as type,
                properties(r) as properties
            LIMIT 5000
            """
            
            try:
                links_results = self.client.execute_query(links_query, {'node_ids': list(node_ids)})
                links = [
                    {
                        'source': record['source'],
                        'target': record['target'],
                        'type': record['type'],
                        'properties': record['properties']
                    }
                    for record in links_results
                ]
            except Exception as e:
                print(f"Warning: Failed to fetch links: {e}")
                links = []
        else:
            links = []
        
        # Calculate node type distribution for metadata
        type_distribution = {}
        for node in all_nodes:
            label = node['label']
            type_distribution[label] = type_distribution.get(label, 0) + 1
        
        return {
            'nodes': all_nodes,
            'links': links,
            'total_returned': len(all_nodes),
            'importance_threshold': importance_threshold,
            'balanced': True,
            'type_distribution': type_distribution,
            'target_distribution': node_type_config
        }
    
    def get_connected_graph_data(
        self,
        total_limit: int = 2000,
        importance_threshold: float = 0.0
    ) -> Dict[str, Any]:
        """
        Get graph data prioritizing well-connected nodes (hubs) while maintaining type diversity.
        This creates a more interconnected view showing the actual connection patterns in the graph.
        
        Args:
            total_limit: Total maximum number of nodes to return
            importance_threshold: Minimum importance score (0-1) for nodes to include
            
        Returns:
            Dictionary with nodes and links arrays emphasizing connectivity
        """
        # Node types and their proportions (same as balanced query for consistency)
        node_type_config = {
            'Resource': 0.35,      # 35% - Documents, articles, specs
            'Topic': 0.20,         # 20% - Topics
            'Event': 0.15,         # 15% - Conferences, webinars
            'Organization': 0.15,  # 15% - Companies, standards bodies
            'Person': 0.15,        # 15% - Authors, experts
        }
        
        all_nodes = []
        node_ids = set()
        
        # Get stats
        stats = self.get_graph_stats()
        node_counts = stats.get('nodes', {})
        
        # For each type, get the most connected nodes (hubs)
        for node_type, proportion in node_type_config.items():
            type_limit = int(total_limit * proportion)
            actual_count = node_counts.get(node_type, 0)
            
            if actual_count > 0 and actual_count < type_limit:
                type_limit = actual_count
            
            if type_limit > 0:
                # Query prioritizes nodes by connection degree (how many relationships they have)
                importance_filter = f"AND COALESCE(n.importance, 0) >= {importance_threshold}" if importance_threshold > 0 else ""
                
                # Get well-connected nodes of this type
                # Neo4j 5.x requires COUNT {pattern} instead of size(pattern)
                query = f"""
                MATCH (n:{node_type})
                WHERE 1=1
                {importance_filter}
                WITH n, COUNT {{ (n)--() }} as degree
                WHERE degree > 0
                ORDER BY degree DESC, n.importance DESC, n.name ASC
                LIMIT $limit
                RETURN 
                    elementId(n) as id,
                    labels(n)[0] as label,
                    COALESCE(n.name, n.title, n.topic_id, n.org_id, n.person_id, n.source_id) as name,
                    COALESCE(n.importance, 0) as importance,
                    COALESCE(n.tier, 2) as tier,
                    properties(n) as properties,
                    degree
                """
                
                try:
                    results = self.client.execute_query(query, {'limit': type_limit})
                    for record in results:
                        node_id = record['id']
                        if node_id not in node_ids:
                            all_nodes.append({
                                'id': node_id,
                                'label': record['label'],
                                'name': record['name'],
                                'importance': record['importance'],
                                'tier': record['tier'],
                                'properties': record['properties'],
                                'degree': record['degree']  # Include degree for debugging
                            })
                            node_ids.add(node_id)
                except Exception as e:
                    print(f"Warning: Failed to fetch {node_type} nodes: {e}")
        
        # Now get ALL relationships between our selected nodes
        # This is the key difference - we ensure high connectivity
        if all_nodes:
            links_query = """
            MATCH (n)-[r]->(m)
            WHERE elementId(n) IN $node_ids AND elementId(m) IN $node_ids
            RETURN 
                elementId(n) as source,
                elementId(m) as target,
                type(r) as type,
                properties(r) as properties
            LIMIT 10000
            """
            
            try:
                links_results = self.client.execute_query(links_query, {'node_ids': list(node_ids)})
                links = [
                    {
                        'source': record['source'],
                        'target': record['target'],
                        'type': record['type'],
                        'properties': record['properties']
                    }
                    for record in links_results
                ]
            except Exception as e:
                print(f"Warning: Failed to fetch links: {e}")
                links = []
        else:
            links = []
        
        # Calculate type distribution
        type_distribution = {}
        for node in all_nodes:
            label = node['label']
            type_distribution[label] = type_distribution.get(label, 0) + 1
        
        # Calculate connectivity metrics
        avg_degree = sum(node.get('degree', 0) for node in all_nodes) / len(all_nodes) if all_nodes else 0
        
        return {
            'nodes': all_nodes,
            'links': links,
            'total_returned': len(all_nodes),
            'total_links': len(links),
            'importance_threshold': importance_threshold,
            'connected': True,
            'avg_degree': avg_degree,
            'type_distribution': type_distribution,
            'target_distribution': node_type_config
        }
    
    def get_recent_connected_graph_data(
        self,
        seed_resource_count: int = 80,
        days_back: int = 120,
        node_budget: int = 500,
    ) -> Dict[str, Any]:
        """
        Default-view graph: seed with the N most-recent Resources (importance-
        weighted), expand 1-hop to their Topics/Orgs/People/Events, then pull
        all edges among the resulting node set.

        Produces a *clustered, interlinked* view of what the system has
        ingested recently, rather than a random-sampled "galaxy" of mostly
        disconnected nodes. ~80 seed resources + their direct neighbours
        typically yields 300-500 nodes with strong inter-connectivity.

        Args:
            seed_resource_count: How many recent Resources to seed with
            days_back: Recency cutoff (only Resources newer than this)
            node_budget: Hard cap on total nodes returned (after dedup)
        """
        # 1) Seed: most-recent Resources with valid publish_date
        seed_query = """
        WITH datetime() - duration({days: $days_back}) AS cutoff
        MATCH (r:Resource)
        WHERE r.publish_date IS NOT NULL
          AND r.publish_date =~ '20[0-9]{2}-[01][0-9]-[0-3][0-9].*'
          AND datetime(replace(toString(r.publish_date), ' ', 'T')) >= cutoff
          AND datetime(replace(toString(r.publish_date), ' ', 'T')) <= datetime()
        WITH r, COALESCE(r.importance, 0) AS imp
        ORDER BY imp DESC, r.publish_date DESC
        LIMIT $seed_resource_count
        RETURN elementId(r) AS id
        """
        try:
            seed_rows = self.client.execute_query(seed_query, {
                'days_back': days_back,
                'seed_resource_count': seed_resource_count,
            })
        except Exception as e:
            print(f"recent_connected: seed query failed: {e}")
            return {'nodes': [], 'links': [], 'total_returned': 0, 'total_links': 0}

        seed_ids = [row['id'] for row in seed_rows]
        if not seed_ids:
            return {'nodes': [], 'links': [], 'total_returned': 0, 'total_links': 0}

        # 2) Expand 1-hop to neighbours, prioritising high-degree connectors.
        # We let neighbours of any type through so the cluster shows the full
        # web around recent work (topics, orgs, people, events).
        expand_query = """
        MATCH (r:Resource) WHERE elementId(r) IN $seed_ids
        MATCH (r)-[]-(n)
        WHERE n:Topic OR n:Organization OR n:Person OR n:Event OR n:Resource OR n:DataSource
        WITH DISTINCT n, COUNT { (n)--() } AS degree
        ORDER BY degree DESC
        LIMIT $neighbour_limit
        RETURN elementId(n) AS id,
               labels(n)[0]   AS label,
               COALESCE(n.name, n.title, n.topic_id, n.org_id, n.person_id, n.source_id) AS name,
               COALESCE(n.importance, 0) AS importance,
               COALESCE(n.tier, 2) AS tier,
               properties(n)  AS properties,
               degree
        """
        # Reserve room for seeds in the budget — neighbours fill the rest
        neighbour_limit = max(0, node_budget - len(seed_ids))
        try:
            neighbour_rows = self.client.execute_query(expand_query, {
                'seed_ids': seed_ids,
                'neighbour_limit': neighbour_limit,
            })
        except Exception as e:
            print(f"recent_connected: expand query failed: {e}")
            neighbour_rows = []

        # 3) Also fetch the seed nodes' own properties so they appear in the output
        seed_props_query = """
        MATCH (r:Resource) WHERE elementId(r) IN $seed_ids
        WITH r, COUNT { (r)--() } AS degree
        RETURN elementId(r) AS id,
               labels(r)[0]  AS label,
               COALESCE(r.name, r.title, r.topic_id, r.org_id, r.person_id, r.source_id) AS name,
               COALESCE(r.importance, 0) AS importance,
               COALESCE(r.tier, 2) AS tier,
               properties(r) AS properties,
               degree
        """
        try:
            seed_prop_rows = self.client.execute_query(seed_props_query, {'seed_ids': seed_ids})
        except Exception as e:
            print(f"recent_connected: seed props query failed: {e}")
            seed_prop_rows = []

        # Merge seeds + neighbours, dedupe on id
        all_nodes_by_id: Dict[str, Dict[str, Any]] = {}
        for row in list(seed_prop_rows) + list(neighbour_rows):
            nid = row['id']
            if nid not in all_nodes_by_id:
                all_nodes_by_id[nid] = {
                    'id': nid,
                    'label': row['label'],
                    'name': row['name'],
                    'importance': row['importance'],
                    'tier': row['tier'],
                    'properties': row['properties'],
                    'degree': row['degree'],
                }
        all_nodes = list(all_nodes_by_id.values())
        node_id_set = set(all_nodes_by_id.keys())

        # 4) All edges among the final node set
        links: List[Dict[str, Any]] = []
        if node_id_set:
            links_query = """
            MATCH (n)-[rel]->(m)
            WHERE elementId(n) IN $node_ids AND elementId(m) IN $node_ids
            RETURN elementId(n) AS source,
                   elementId(m) AS target,
                   type(rel)    AS type,
                   properties(rel) AS properties
            LIMIT 10000
            """
            try:
                link_rows = self.client.execute_query(links_query, {'node_ids': list(node_id_set)})
                links = [
                    {
                        'source': r['source'],
                        'target': r['target'],
                        'type':   r['type'],
                        'properties': r['properties'],
                    }
                    for r in link_rows
                ]
            except Exception as e:
                print(f"recent_connected: links query failed: {e}")

        # Type distribution + connectivity metric
        type_distribution: Dict[str, int] = {}
        for n in all_nodes:
            type_distribution[n['label']] = type_distribution.get(n['label'], 0) + 1
        avg_degree = sum(n.get('degree', 0) for n in all_nodes) / len(all_nodes) if all_nodes else 0

        return {
            'nodes': all_nodes,
            'links': links,
            'total_returned': len(all_nodes),
            'total_links': len(links),
            'seed_resource_count': len(seed_ids),
            'days_back': days_back,
            'avg_degree': avg_degree,
            'type_distribution': type_distribution,
            'view': 'recent_connected',
        }

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
