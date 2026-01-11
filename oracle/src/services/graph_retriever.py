"""Graph Retriever - Graph-native queries for Oracle Service.

This module implements graph-based document retrieval using Neo4j's graph structure
for relationship-aware queries, multi-hop traversals, and temporal pattern detection.

Phase 3 of Oracle Service implementation.

Query patterns implemented:
1. Organization hierarchy traversal - Find resources from org and related orgs
2. People-topic relationships - Find people working on topics
3. Topic relationship discovery - Find related topics via co-occurrence
4. Temporal trend analysis - Detect trending topics over time
5. Cross-organization collaboration - Find orgs collaborating on topics
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
import logging
from typing import Any, Optional

from src.models.response import Document, QueryIntent
from src.services.keyword_retriever import get_repo, _convert_datetime
from src.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class GraphSearchResult:
    """Result of graph-based retrieval."""
    documents: list[Document]
    total_candidates: int
    query_pattern: str
    graph_data: Optional[dict] = None  # Additional graph data (trends, people, etc.)


@dataclass
class TrendingTopic:
    """A trending topic with growth metrics."""
    name: str
    current_count: int
    previous_count: int
    growth_rate: float
    growth_percentage: float


@dataclass
class PersonTopicConnection:
    """A person connected to a topic."""
    name: str
    affiliations: list[str]
    contribution_count: int
    latest_activity: Optional[str]


@dataclass
class OrgCollaboration:
    """Collaboration between two organizations."""
    org1: str
    org2: str
    collaboration_count: int
    shared_topics: list[str]


class GraphRetriever:
    """Retrieves documents using graph traversal patterns in Neo4j."""
    
    def __init__(self):
        """Initialize the graph retriever."""
        self.patterns = {
            QueryIntent.ENTITY_FOCUSED: self._org_hierarchy_search,
            QueryIntent.RELATIONSHIP_QUERY: self._people_topic_search,
            QueryIntent.TREND_ANALYSIS: self._trend_analysis_search,
            QueryIntent.COMPARATIVE: self._cross_org_collaboration_search,
            QueryIntent.TOPIC_DISCOVERY: self._topic_relationship_search,
        }
    
    async def retrieve(
        self,
        query: str,
        filters: dict,
        intent: QueryIntent,
        max_results: int = 50,
    ) -> GraphSearchResult:
        """
        Retrieve documents using graph-native queries.
        
        Selects the appropriate query pattern based on intent and executes
        graph traversal to find related documents.
        
        Args:
            query: User's natural language query
            filters: Parsed filters (topics, orgs, dates, etc.)
            intent: Classified query intent
            max_results: Maximum documents to return
            
        Returns:
            GraphSearchResult with documents and graph metadata
        """
        try:
            # Select query pattern based on intent
            pattern_fn = self.patterns.get(intent)
            
            if pattern_fn is None:
                logger.info(f"No graph pattern for intent {intent.value}, using topic relationship")
                pattern_fn = self._topic_relationship_search
            
            # Execute the pattern
            result = await pattern_fn(
                query=query,
                filters=filters,
                max_results=max_results,
            )
            
            logger.info(f"Graph retrieval ({result.query_pattern}) returned {len(result.documents)} documents")
            
            return result
            
        except Exception as e:
            logger.error(f"Graph retrieval failed: {e}")
            return GraphSearchResult(
                documents=[],
                total_candidates=0,
                query_pattern="error",
                graph_data={"error": str(e)},
            )
    
    async def _org_hierarchy_search(
        self,
        query: str,
        filters: dict,
        max_results: int,
    ) -> GraphSearchResult:
        """
        Pattern 1: Organization Hierarchy Traversal
        
        Find resources from specified organizations AND their related orgs
        (parent, child, affiliated organizations).
        
        Use case: "What did IEEE 802.11 task group announce?"
        """
        orgs = filters.get("organizations") or []
        start_date = filters.get("start_date")
        end_date = filters.get("end_date")
        datasource_ids = filters.get("datasource_ids") or []
        
        if not orgs:
            # Fall back to topic relationship search if no orgs specified
            return await self._topic_relationship_search(query, filters, max_results)
        
        try:
            repo = get_repo()
            
            # Build dynamic date filter
            date_filter = ""
            params: dict[str, Any] = {
                "orgs": orgs,
                "limit": max_results,
            }
            
            if start_date:
                date_filter += " AND r.publish_date >= date($start_date)"
                params["start_date"] = start_date
            if end_date:
                date_filter += " AND r.publish_date <= date($end_date)"
                params["end_date"] = end_date
            
            # Build datasource filter for Cypher query
            datasource_filter = ""
            if datasource_ids:
                datasource_filter = " AND ds.datasource_id IN $datasource_ids"
                params["datasource_ids"] = datasource_ids
            
            # Cypher query: Find org and traverse to related orgs, get their resources
            cypher = f"""
            // Find target organizations
            MATCH (target:Organization)
            WHERE target.name IN $orgs
               OR any(alias IN target.aliases WHERE alias IN $orgs)
            
            // Traverse to parent/child/affiliated organizations (1-2 hops)
            OPTIONAL MATCH (target)-[:PARENT_OF|CHILD_OF|AFFILIATED_WITH*1..2]-(related:Organization)
            
            WITH collect(DISTINCT target) + collect(DISTINCT related) AS allOrgs
            
            // Get resources mentioning any of these organizations
            UNWIND allOrgs AS org
            MATCH (org)<-[:MENTIONS]-(r:Resource)
            WHERE r.url IS NOT NULL {date_filter}
            
            // Join with datasource for filtering
            MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
            WHERE true {datasource_filter}
            
            // Collect topics for context
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            
            WITH r, collect(DISTINCT org.name) AS orgs, collect(DISTINCT t.name) AS topics,
                 ds.name AS datasource_name,
                 ds.datasource_id AS datasource_id
            
            RETURN r AS resource,
                   orgs AS organizations,
                   topics,
                   datasource_name,
                   datasource_id,
                   1.0 AS relevance
            ORDER BY r.publish_date DESC
            LIMIT $limit
            """
            
            documents = self._execute_query_and_convert(repo, cypher, params, "org_hierarchy", filters)
            
            return GraphSearchResult(
                documents=documents,
                total_candidates=len(documents),
                query_pattern="org_hierarchy",
                graph_data={"searched_orgs": orgs},
            )
            
        except Exception as e:
            logger.error(f"Org hierarchy search failed: {e}")
            return GraphSearchResult(
                documents=[],
                total_candidates=0,
                query_pattern="org_hierarchy",
                graph_data={"error": str(e)},
            )
    
    async def _people_topic_search(
        self,
        query: str,
        filters: dict,
        max_results: int,
    ) -> GraphSearchResult:
        """
        Pattern 2: People-Topic Relationships
        
        Find people working on specific topics and their resources.
        
        Use case: "Who is working on Wi-Fi 7?" or "What topics are people from Qualcomm working on?"
        """
        topics = filters.get("topics") or []
        orgs = filters.get("organizations") or []
        datasource_ids = filters.get("datasource_ids") or []
        
        try:
            repo = get_repo()
            params: dict[str, Any] = {"limit": max_results}
            
            # Build datasource filter for Cypher query
            datasource_filter = ""
            if datasource_ids:
                datasource_filter = " AND ds.datasource_id IN $datasource_ids"
                params["datasource_ids"] = datasource_ids
            
            if topics:
                # Find people working on specific topics
                cypher = f"""
                // Find topics
                MATCH (t:Topic)
                WHERE t.name IN $topics
                   OR any(alias IN t.aliases WHERE alias IN $topics)
                
                // Find resources about this topic that mention people
                MATCH (r:Resource)-[:RELATES_TO]->(t)
                MATCH (r)-[:MENTIONS]->(p:Person)
                
                // Join with datasource for filtering
                MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
                WHERE true {datasource_filter}
                
                // Get organizational affiliations
                OPTIONAL MATCH (p)-[:AFFILIATED_WITH]->(org:Organization)
                
                WITH p, ds,
                     collect(DISTINCT org.name) AS affiliations,
                     collect(DISTINCT r) AS resources,
                     max(r.publish_date) AS latest_activity
                
                // Return resources with person context
                UNWIND resources AS r
                
                OPTIONAL MATCH (r)-[:RELATES_TO]->(topic:Topic)
                OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
                
                WITH r, 
                     collect(DISTINCT topic.name) AS topics,
                     collect(DISTINCT o.name) AS orgs,
                     collect(DISTINCT p.name) AS people,
                     ds.name AS datasource_name,
                     ds.datasource_id AS datasource_id
                
                RETURN r AS resource,
                       topics,
                       orgs AS organizations,
                       people,
                       datasource_name,
                       datasource_id,
                       1.0 AS relevance
                ORDER BY r.publish_date DESC
                LIMIT $limit
                """
                params["topics"] = topics
                
            elif orgs:
                # Find what topics people from specific orgs work on
                cypher = f"""
                // Find people affiliated with orgs
                MATCH (p:Person)-[:AFFILIATED_WITH]->(org:Organization)
                WHERE org.name IN $orgs
                   OR any(alias IN org.aliases WHERE alias IN $orgs)
                
                // Find resources mentioning these people
                MATCH (r:Resource)-[:MENTIONS]->(p)
                
                // Join with datasource for filtering
                MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
                WHERE true {datasource_filter}
                
                // Get topics
                OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
                OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
                
                WITH r,
                     collect(DISTINCT t.name) AS topics,
                     collect(DISTINCT o.name) AS orgs,
                     collect(DISTINCT p.name) AS people,
                     ds.name AS datasource_name,
                     ds.datasource_id AS datasource_id
                
                RETURN r AS resource,
                       topics,
                       orgs AS organizations,
                       people,
                       datasource_name,
                       datasource_id,
                       1.0 AS relevance
                ORDER BY r.publish_date DESC
                LIMIT $limit
                """
                params["orgs"] = orgs
            else:
                # General people search - find active contributors
                cypher = f"""
                // Find people with most recent contributions
                MATCH (r:Resource)-[:MENTIONS]->(p:Person)
                WHERE r.publish_date IS NOT NULL
                
                // Join with datasource for filtering
                MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
                WHERE true {datasource_filter}
                
                WITH p, ds, count(r) AS contributions, max(r.publish_date) AS latest
                ORDER BY latest DESC, contributions DESC
                LIMIT 20
                
                // Get their resources
                MATCH (r:Resource)-[:MENTIONS]->(p)
                MATCH (r)-[:INGESTED_FROM]->(ds2:DataSource)
                WHERE ds2.datasource_id = ds.datasource_id
                
                OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
                OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
                
                WITH r,
                     collect(DISTINCT t.name) AS topics,
                     collect(DISTINCT o.name) AS orgs,
                     collect(DISTINCT p.name) AS people,
                     ds.name AS datasource_name,
                     ds.datasource_id AS datasource_id
                
                RETURN r AS resource,
                       topics,
                       orgs AS organizations,
                       people,
                       datasource_name,
                       datasource_id,
                       1.0 AS relevance
                ORDER BY r.publish_date DESC
                LIMIT $limit
                """
            
            documents = self._execute_query_and_convert(repo, cypher, params, "people_topic", filters)
            
            # Extract people data for graph context
            people_data = self._extract_people_data(repo, topics, orgs)
            
            return GraphSearchResult(
                documents=documents,
                total_candidates=len(documents),
                query_pattern="people_topic",
                graph_data={"people": people_data},
            )
            
        except Exception as e:
            logger.error(f"People-topic search failed: {e}")
            return GraphSearchResult(
                documents=[],
                total_candidates=0,
                query_pattern="people_topic",
                graph_data={"error": str(e)},
            )
    
    async def _topic_relationship_search(
        self,
        query: str,
        filters: dict,
        max_results: int,
    ) -> GraphSearchResult:
        """
        Pattern 3: Topic Relationship Discovery
        
        Find topics related to specified topics via co-occurrence in documents.
        
        Use case: "What topics are related to MLO?"
        """
        topics = filters.get("topics") or []
        start_date = filters.get("start_date")
        end_date = filters.get("end_date")
        datasource_ids = filters.get("datasource_ids") or []
        
        try:
            repo = get_repo()
            params: dict[str, Any] = {"limit": max_results}
            
            # Build date filter
            date_filter = ""
            if start_date:
                date_filter += " AND r.publish_date >= date($start_date)"
                params["start_date"] = start_date
            if end_date:
                date_filter += " AND r.publish_date <= date($end_date)"
                params["end_date"] = end_date
            
            # Build datasource filter for Cypher query
            datasource_filter = ""
            if datasource_ids:
                datasource_filter = " AND ds.datasource_id IN $datasource_ids"
                params["datasource_ids"] = datasource_ids
            
            if topics:
                # Find resources about these topics and related topics
                cypher = f"""
                // Find target topics
                MATCH (t:Topic)
                WHERE t.name IN $topics
                   OR any(alias IN t.aliases WHERE alias IN $topics)
                
                // Find resources about these topics
                MATCH (r:Resource)-[:RELATES_TO]->(t)
                WHERE r.url IS NOT NULL {date_filter}
                
                // Join with datasource for filtering
                MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
                WHERE true {datasource_filter}
                
                // Find other topics these resources relate to
                OPTIONAL MATCH (r)-[:RELATES_TO]->(related:Topic)
                OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
                
                WITH r,
                     collect(DISTINCT related.name) AS topics,
                     collect(DISTINCT o.name) AS orgs,
                     ds.name AS datasource_name,
                     ds.datasource_id AS datasource_id
                
                RETURN r AS resource,
                       topics,
                       orgs AS organizations,
                       datasource_name,
                       datasource_id,
                       1.0 AS relevance
                ORDER BY r.publish_date DESC
                LIMIT $limit
                """
                params["topics"] = topics
            else:
                # General topic discovery - find resources with most topic connections
                cypher = f"""
                MATCH (r:Resource)-[:RELATES_TO]->(t:Topic)
                WHERE r.url IS NOT NULL {date_filter}
                
                // Join with datasource for filtering
                MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
                WHERE true {datasource_filter}
                
                WITH r, ds, count(DISTINCT t) AS topic_count
                WHERE topic_count >= 2
                
                MATCH (r)-[:RELATES_TO]->(t:Topic)
                OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
                
                WITH r,
                     collect(DISTINCT t.name) AS topics,
                     collect(DISTINCT o.name) AS orgs,
                     ds.name AS datasource_name,
                     ds.datasource_id AS datasource_id,
                     topic_count
                
                RETURN r AS resource,
                       topics,
                       orgs AS organizations,
                       datasource_name,
                       datasource_id,
                       toFloat(topic_count) / 10.0 AS relevance
                ORDER BY topic_count DESC, r.publish_date DESC
                LIMIT $limit
                """
            
            documents = self._execute_query_and_convert(repo, cypher, params, "topic_relationship", filters)
            
            # Get related topics for context
            related_topics = self._find_related_topics(repo, topics) if topics else []
            
            # Get organization contributions for these topics
            org_contributions = self._get_topic_org_breakdown(repo, topics) if topics else []
            
            return GraphSearchResult(
                documents=documents,
                total_candidates=len(documents),
                query_pattern="topic_relationship",
                graph_data={
                    "related_topics": related_topics,
                    "org_contributions": org_contributions,
                },
            )
            
        except Exception as e:
            logger.error(f"Topic relationship search failed: {e}")
            return GraphSearchResult(
                documents=[],
                total_candidates=0,
                query_pattern="topic_relationship",
                graph_data={"error": str(e)},
            )
    
    async def _trend_analysis_search(
        self,
        query: str,
        filters: dict,
        max_results: int,
    ) -> GraphSearchResult:
        """
        Pattern 4: Temporal Trend Analysis
        
        Detect trending topics based on growth in document count over time.
        
        Use case: "What topics are trending this month?"
        """
        # Default to last 30 days for current period, previous 30 for comparison
        end_date = filters.get("end_date") or datetime.now().strftime("%Y-%m-%d")
        start_date = filters.get("start_date") or (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        datasource_ids = filters.get("datasource_ids") or []
        
        # Calculate previous period for comparison
        try:
            if isinstance(start_date, str):
                start_dt = datetime.strptime(start_date, "%Y-%m-%d")
            else:
                start_dt = start_date
            if isinstance(end_date, str):
                end_dt = datetime.strptime(end_date, "%Y-%m-%d")
            else:
                end_dt = end_date
            
            period_days = (end_dt - start_dt).days or 30
            prev_start = (start_dt - timedelta(days=period_days)).strftime("%Y-%m-%d")
            prev_end = start_dt.strftime("%Y-%m-%d")
        except (ValueError, TypeError):
            prev_start = (datetime.now() - timedelta(days=60)).strftime("%Y-%m-%d")
            prev_end = (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d")
        
        try:
            repo = get_repo()
            
            # Build datasource filter for Cypher query
            datasource_filter = ""
            if datasource_ids:
                datasource_filter = """
                MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
                WHERE ds.datasource_id IN $datasource_ids
                WITH r, t
                """
            
            # First, find trending topics
            trend_cypher = f"""
            // Get resources in current period
            MATCH (r:Resource)-[:RELATES_TO]->(t:Topic)
            WHERE r.publish_date >= date($start_date)
              AND r.publish_date <= date($end_date)
            
            {datasource_filter}
            
            WITH t, count(r) AS current_count
            
            // Get resources in previous period
            OPTIONAL MATCH (r_prev:Resource)-[:RELATES_TO]->(t)
            WHERE r_prev.publish_date >= date($prev_start)
              AND r_prev.publish_date < date($start_date)
            
            WITH t, current_count, count(r_prev) AS previous_count
            
            // Calculate growth rate
            WITH t, current_count, previous_count,
                 CASE WHEN previous_count > 0
                      THEN toFloat(current_count - previous_count) / previous_count
                      ELSE CASE WHEN current_count > 0 THEN 1.0 ELSE 0.0 END
                 END AS growth_rate
            
            WHERE current_count >= 2
            
            RETURN t.name AS topic,
                   current_count,
                   previous_count,
                   growth_rate,
                   round(growth_rate * 100) AS growth_percentage
            ORDER BY growth_rate DESC, current_count DESC
            LIMIT 10
            """
            
            params: dict[str, Any] = {
                "start_date": start_date,
                "end_date": end_date,
                "prev_start": prev_start,
            }
            if datasource_ids:
                params["datasource_ids"] = datasource_ids
            
            # Get trending topics using execute_query
            trending_topics: list[TrendingTopic] = []
            client = repo.client
            results = client.execute_query(trend_cypher, params)
            for record in results:
                trending_topics.append(TrendingTopic(
                    name=record["topic"],
                    current_count=record["current_count"],
                    previous_count=record["previous_count"],
                    growth_rate=record["growth_rate"],
                    growth_percentage=record.get("growth_percentage") or 0,
                ))
            
            # Build datasource filter for document query
            doc_datasource_filter = ""
            if datasource_ids:
                doc_datasource_filter = " AND ds.datasource_id IN $datasource_ids"
            
            # Get documents from trending topics
            if trending_topics:
                trending_topic_names = [t.name for t in trending_topics[:5]]
                doc_cypher = f"""
                MATCH (r:Resource)-[:RELATES_TO]->(t:Topic)
                WHERE t.name IN $topics
                  AND r.publish_date >= date($start_date)
                  AND r.url IS NOT NULL
                
                // Join with datasource for filtering
                MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
                WHERE true {doc_datasource_filter}
                
                OPTIONAL MATCH (r)-[:RELATES_TO]->(all_t:Topic)
                OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
                
                WITH r,
                     collect(DISTINCT all_t.name) AS topics,
                     collect(DISTINCT o.name) AS orgs,
                     ds.name AS datasource_name,
                     ds.datasource_id AS datasource_id
                
                RETURN r AS resource,
                       topics,
                       orgs AS organizations,
                       datasource_name,
                       datasource_id,
                       1.0 AS relevance
                ORDER BY r.publish_date DESC
                LIMIT $limit
                """
                
                doc_params: dict[str, Any] = {
                    "topics": trending_topic_names,
                    "start_date": start_date,
                    "limit": max_results,
                }
                if datasource_ids:
                    doc_params["datasource_ids"] = datasource_ids
                
                documents = self._execute_query_and_convert(repo, doc_cypher, doc_params, "trend_analysis", filters)
            else:
                documents = []
                trending_topic_names = []
            
            # Get org contributions for trending topics
            org_contributions = self._get_topic_org_breakdown(repo, trending_topic_names) if trending_topic_names else []
            
            return GraphSearchResult(
                documents=documents,
                total_candidates=len(documents),
                query_pattern="trend_analysis",
                graph_data={
                    "trending_topics": [
                        {
                            "name": t.name,
                            "current_count": t.current_count,
                            "previous_count": t.previous_count,
                            "growth_percentage": t.growth_percentage,
                        }
                        for t in trending_topics
                    ],
                    "period": {"start": start_date, "end": end_date},
                    "org_contributions": org_contributions,
                },
            )
            
        except Exception as e:
            logger.error(f"Trend analysis search failed: {e}")
            return GraphSearchResult(
                documents=[],
                total_candidates=0,
                query_pattern="trend_analysis",
                graph_data={"error": str(e)},
            )
    
    async def _cross_org_collaboration_search(
        self,
        query: str,
        filters: dict,
        max_results: int,
    ) -> GraphSearchResult:
        """
        Pattern 5: Cross-Organization Collaboration
        
        Find organizations collaborating on topics (mentioned together in documents).
        
        Use case: "Which organizations are collaborating on 6 GHz spectrum?"
        """
        topics = filters.get("topics") or []
        datasource_ids = filters.get("datasource_ids") or []
        
        try:
            repo = get_repo()
            params: dict[str, Any] = {"limit": max_results}
            
            # Build topic filter
            topic_filter = ""
            if topics:
                topic_filter = """
                MATCH (r)-[:RELATES_TO]->(t:Topic)
                WHERE t.name IN $topics
                   OR any(alias IN t.aliases WHERE alias IN $topics)
                WITH r
                """
                params["topics"] = topics
            
            # Build datasource filter for Cypher query
            datasource_filter = ""
            if datasource_ids:
                datasource_filter = " AND ds.datasource_id IN $datasource_ids"
                params["datasource_ids"] = datasource_ids
            
            # Find resources mentioning multiple organizations
            collab_cypher = f"""
            // Start with resources
            MATCH (r:Resource)-[:MENTIONS]->(o:Organization)
            WHERE r.url IS NOT NULL
            
            {topic_filter}
            
            // Join with datasource for filtering
            MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
            WHERE true {datasource_filter}
            
            // Find resources mentioning multiple orgs (collaboration signal)
            WITH r, ds, collect(DISTINCT o) AS orgs
            WHERE size(orgs) >= 2
            
            // Get topics for these resources
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            
            WITH r,
                 [org IN orgs | org.name] AS org_names,
                 collect(DISTINCT t.name) AS topics,
                 ds.name AS datasource_name,
                 ds.datasource_id AS datasource_id
            
            RETURN r AS resource,
                   topics,
                   org_names AS organizations,
                   datasource_name,
                   datasource_id,
                   toFloat(size(org_names)) / 5.0 AS relevance
            ORDER BY size(org_names) DESC, r.publish_date DESC
            LIMIT $limit
            """
            
            documents = self._execute_query_and_convert(repo, collab_cypher, params, "cross_org_collaboration", filters)
            
            # Get collaboration pairs
            collaborations = self._find_org_collaborations(repo, topics) if topics else []
            
            # Get org contributions (mentions/involvement)
            org_contributions = self._get_topic_org_breakdown(repo, topics) if topics else []
            
            return GraphSearchResult(
                documents=documents,
                total_candidates=len(documents),
                query_pattern="cross_org_collaboration",
                graph_data={
                    "collaborations": collaborations,
                    "org_contributions": org_contributions,
                },
            )
            
        except Exception as e:
            logger.error(f"Cross-org collaboration search failed: {e}")
            return GraphSearchResult(
                documents=[],
                total_candidates=0,
                query_pattern="cross_org_collaboration",
                graph_data={"error": str(e)},
            )
    
    def _execute_query_and_convert(
        self,
        repo,
        cypher: str,
        params: dict,
        pattern_name: str,
        filters: dict = None,
    ) -> list[Document]:
        """Execute a Cypher query and convert results to Documents."""
        documents = []
        filters = filters or {}
        
        try:
            client = repo.client
            results = client.execute_query(cypher, params)
            
            for record in results:
                resource = record.get("resource", {})
                topics = record.get("topics") or []
                orgs = record.get("organizations") or []
                relevance = record.get("relevance", 0.8)
                datasource_id = record.get("datasource_id")
                datasource_name = record.get("datasource_name")
                
                # Extract properties from Neo4j node (already a dict from execute_query)
                props = resource if isinstance(resource, dict) else {}
                
                # Create Document - use datasource_name if available, fall back to datasource_id
                doc = Document(
                    url=props.get("url", ""),
                    title=props.get("title", ""),
                    summary=props.get("summary", ""),
                    publish_date=_convert_datetime(props.get("publish_date")),
                    source=datasource_name or datasource_id or props.get("datasource_id", ""),
                    category=props.get("category", ""),
                    datasource_id=datasource_id or props.get("datasource_id", ""),
                    topics=[t for t in topics if t],
                    organizations=[o for o in orgs if o],
                    relevance_score=min(float(relevance), 1.0),
                    match_reasons=[f"Graph traversal ({pattern_name})"],
                )
                
                if doc.url:
                    documents.append(doc)
            
            # Apply datasource filter if specified
            datasource_ids = filters.get("datasource_ids") or []
            if datasource_ids:
                documents = [d for d in documents if d.datasource_id in datasource_ids]
                logger.info(f"Filtered graph results to {len(documents)} documents from datasources: {datasource_ids}")
                        
        except Exception as e:
            logger.error(f"Query execution failed for {pattern_name}: {e}")
        
        return documents
    
    def _extract_people_data(
        self,
        repo,
        topics: list[str],
        orgs: list[str],
    ) -> list[dict]:
        """Extract people data for graph context."""
        people_data = []
        
        try:
            if topics:
                cypher = """
                MATCH (t:Topic)
                WHERE t.name IN $topics
                
                MATCH (r:Resource)-[:RELATES_TO]->(t)
                MATCH (r)-[:MENTIONS]->(p:Person)
                
                OPTIONAL MATCH (p)-[:AFFILIATED_WITH]->(org:Organization)
                
                WITH p,
                     collect(DISTINCT org.name) AS affiliations,
                     count(DISTINCT r) AS contributions,
                     max(r.publish_date) AS latest
                
                RETURN p.name AS name,
                       affiliations,
                       contributions,
                       latest
                ORDER BY contributions DESC
                LIMIT 10
                """
                params = {"topics": topics}
            elif orgs:
                cypher = """
                MATCH (p:Person)-[:AFFILIATED_WITH]->(org:Organization)
                WHERE org.name IN $orgs
                
                MATCH (r:Resource)-[:MENTIONS]->(p)
                
                WITH p,
                     collect(DISTINCT org.name) AS affiliations,
                     count(DISTINCT r) AS contributions,
                     max(r.publish_date) AS latest
                
                RETURN p.name AS name,
                       affiliations,
                       contributions,
                       latest
                ORDER BY contributions DESC
                LIMIT 10
                """
                params = {"orgs": orgs}
            else:
                return []
            
            client = repo.client
            results = client.execute_query(cypher, params)
            for record in results:
                people_data.append({
                    "name": record["name"],
                    "affiliations": record.get("affiliations") or [],
                    "contributions": record["contributions"],
                    "latest_activity": _convert_datetime(record.get("latest")),
                })
                    
        except Exception as e:
            logger.warning(f"Failed to extract people data: {e}")
        
        return people_data
    
    def _find_related_topics(self, repo, topics: list[str]) -> list[dict]:
        """Find topics related to specified topics via co-occurrence."""
        related = []
        
        try:
            cypher = """
            MATCH (t:Topic)
            WHERE t.name IN $topics
            
            MATCH (t)<-[:RELATES_TO]-(r:Resource)-[:RELATES_TO]->(related:Topic)
            WHERE NOT related.name IN $topics
            
            WITH related, count(r) AS co_occurrence
            ORDER BY co_occurrence DESC
            LIMIT 10
            
            RETURN related.name AS name,
                   related.description AS description,
                   co_occurrence
            """
            
            client = repo.client
            results = client.execute_query(cypher, {"topics": topics})
            for record in results:
                related.append({
                    "name": record["name"],
                    "description": record.get("description"),
                    "co_occurrence": record["co_occurrence"],
                })
                    
        except Exception as e:
            logger.warning(f"Failed to find related topics: {e}")
        
        return related
    
    def _find_org_collaborations(self, repo, topics: list[str]) -> list[dict]:
        """Find organization collaboration pairs."""
        collaborations = []
        
        try:
            cypher = """
            // Find resources about the topics
            MATCH (r:Resource)-[:RELATES_TO]->(t:Topic)
            WHERE t.name IN $topics
            
            // Find organizations mentioned in these resources
            MATCH (r)-[:MENTIONS]->(o:Organization)
            
            // Find resources mentioning multiple orgs
            WITH r, collect(DISTINCT o) AS orgs, collect(DISTINCT t.name) AS topics
            WHERE size(orgs) >= 2
            
            // Expand org pairs
            UNWIND orgs AS org1
            UNWIND orgs AS org2
            WITH org1, org2, topics, r
            WHERE id(org1) < id(org2)
            
            // Count collaborations
            WITH org1.name AS org1_name,
                 org2.name AS org2_name,
                 count(DISTINCT r) AS collaboration_count,
                 collect(DISTINCT topics) AS shared_topics
            
            // Flatten shared_topics
            WITH org1_name, org2_name, collaboration_count,
                 reduce(s = [], t IN shared_topics | s + t) AS flat_topics
            
            RETURN org1_name,
                   org2_name,
                   collaboration_count,
                   flat_topics[0..5] AS shared_topics
            ORDER BY collaboration_count DESC
            LIMIT 10
            """
            
            client = repo.client
            results = client.execute_query(cypher, {"topics": topics})
            for record in results:
                collaborations.append({
                    "org1": record["org1_name"],
                    "org2": record["org2_name"],
                    "collaboration_count": record["collaboration_count"],
                    "shared_topics": record.get("shared_topics") or [],
                })
                    
        except Exception as e:
            logger.warning(f"Failed to find org collaborations: {e}")
        
        return collaborations
    
    def _get_org_contributions(
        self,
        repo,
        topics: list[str] = None,
        start_date: str = None,
        limit: int = 10,
    ) -> list[dict]:
        """
        Get organizations ranked by their contribution/mention count.
        
        Returns organizations with:
        - mention_count: How many resources mention them
        - topic_count: How many distinct topics they're associated with
        - latest_activity: Most recent resource mentioning them
        
        Args:
            repo: Graph repository
            topics: Optional filter to specific topics
            start_date: Optional date filter
            limit: Max organizations to return
            
        Returns:
            List of org contribution data sorted by mention count
        """
        org_contributions = []
        
        try:
            # Build optional filters
            topic_filter = ""
            date_filter = ""
            params: dict[str, Any] = {"limit": limit}
            
            if topics:
                topic_filter = """
                MATCH (r)-[:RELATES_TO]->(t:Topic)
                WHERE t.name IN $topics
                WITH r, o
                """
                params["topics"] = topics
            
            if start_date:
                date_filter = "AND r.publish_date >= date($start_date)"
                params["start_date"] = start_date
            
            cypher = f"""
            // Find organizations mentioned in resources
            MATCH (r:Resource)-[:MENTIONS]->(o:Organization)
            WHERE r.url IS NOT NULL {date_filter}
            
            {topic_filter}
            
            // Get topics associated with each org's resources
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            
            WITH o,
                 count(DISTINCT r) AS mention_count,
                 count(DISTINCT t) AS topic_count,
                 max(r.publish_date) AS latest_activity,
                 collect(DISTINCT t.name)[0..5] AS top_topics
            
            RETURN o.name AS name,
                   o.description AS description,
                   mention_count,
                   topic_count,
                   latest_activity,
                   top_topics
            ORDER BY mention_count DESC, topic_count DESC
            LIMIT $limit
            """
            
            client = repo.client
            results = client.execute_query(cypher, params)
            
            for record in results:
                org_contributions.append({
                    "name": record["name"],
                    "description": record.get("description"),
                    "mention_count": record["mention_count"],
                    "topic_count": record["topic_count"],
                    "latest_activity": _convert_datetime(record.get("latest_activity")),
                    "top_topics": record.get("top_topics") or [],
                })
                
        except Exception as e:
            logger.warning(f"Failed to get org contributions: {e}")
        
        return org_contributions
    
    def _get_topic_org_breakdown(
        self,
        repo,
        topics: list[str],
        limit: int = 10,
    ) -> list[dict]:
        """
        Get organizations contributing to specific topics with counts.
        
        For a given topic, shows which organizations are most active.
        
        Args:
            repo: Graph repository
            topics: Topics to analyze
            limit: Max organizations per topic
            
        Returns:
            List of {topic, organizations: [{name, count}]}
        """
        breakdown = []
        
        if not topics:
            return breakdown
        
        try:
            cypher = """
            // For each topic, find orgs and their contribution counts
            MATCH (t:Topic)
            WHERE t.name IN $topics
            
            MATCH (r:Resource)-[:RELATES_TO]->(t)
            MATCH (r)-[:MENTIONS]->(o:Organization)
            
            WITH t.name AS topic,
                 o.name AS org_name,
                 count(DISTINCT r) AS contribution_count
            
            ORDER BY topic, contribution_count DESC
            
            WITH topic, collect({name: org_name, count: contribution_count})[0..$limit] AS orgs
            
            RETURN topic, orgs
            """
            
            client = repo.client
            results = client.execute_query(cypher, {"topics": topics, "limit": limit})
            
            for record in results:
                breakdown.append({
                    "topic": record["topic"],
                    "organizations": record.get("orgs") or [],
                })
                
        except Exception as e:
            logger.warning(f"Failed to get topic-org breakdown: {e}")
        
        return breakdown


# Convenience function for simple usage
async def graph_search(
    query: str,
    filters: dict = None,
    intent: QueryIntent = QueryIntent.TOPIC_DISCOVERY,
    max_results: int = 50,
) -> GraphSearchResult:
    """
    Convenience function for graph-based search.
    
    Args:
        query: Search query
        filters: Optional filters
        intent: Query intent
        max_results: Maximum results
        
    Returns:
        GraphSearchResult with documents and graph data
    """
    retriever = GraphRetriever()
    return await retriever.retrieve(
        query=query,
        filters=filters or {},
        intent=intent,
        max_results=max_results,
    )
