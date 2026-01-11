"""Context Builder - Graph context assembly for Oracle Service.

Phase 1: Basic context from document aggregation.
Phase 3 enhancement: Rich context from graph retriever results.
"""

from dataclasses import dataclass
import logging
from typing import Optional
from collections import Counter

from src.models.response import Document, GraphContext, RelatedEntity
from src.services.keyword_retriever import get_repo
from src.settings import settings

logger = logging.getLogger(__name__)


class ContextBuilder:
    """Builds graph context around retrieved documents."""
    
    async def build(
        self,
        documents: list[Document],
        graph_data: Optional[dict] = None,
    ) -> GraphContext:
        """
        Build graph context from retrieved documents and optional graph retriever data.
        
        Extracts:
        - Central topics (most frequent across documents)
        - Key organizations
        - Key people
        - Related entities
        - Temporal patterns
        - Trending topics (from graph retriever)
        - Collaboration data (from graph retriever)
        
        Args:
            documents: List of retrieved documents
            graph_data: Optional additional context from graph retriever
            
        Returns:
            GraphContext with assembled information
        """
        if not documents:
            return GraphContext()
        
        try:
            # Aggregate topics across documents
            topic_counter = Counter()
            org_counter = Counter()
            
            for doc in documents:
                for topic in doc.topics:
                    topic_counter[topic] += 1
                for org in doc.organizations:
                    org_counter[org] += 1
            
            # Get most common topics and orgs
            central_topics = [t for t, _ in topic_counter.most_common(5)]
            key_organizations = [o for o, _ in org_counter.most_common(5)]
            
            # Try to get additional context from graph
            related_entities = await self._get_related_entities(central_topics, key_organizations)
            
            # Enhance with graph retriever data if available
            if graph_data:
                related_entities = self._enhance_with_graph_data(related_entities, graph_data)
            
            # Analyze temporal patterns
            temporal_patterns = self._analyze_temporal_patterns(documents, graph_data)
            
            # Try to extract people from graph (or use graph_data if available)
            key_people = await self._get_key_people(documents, graph_data)
            
            return GraphContext(
                central_topics=central_topics,
                key_organizations=key_organizations,
                key_people=key_people,
                related_entities=related_entities,
                temporal_patterns=temporal_patterns
            )
            
        except Exception as e:
            logger.warning(f"Failed to build full graph context: {e}")
            # Return basic context from documents only
            topic_counter = Counter()
            org_counter = Counter()
            
            for doc in documents:
                for topic in doc.topics:
                    topic_counter[topic] += 1
                for org in doc.organizations:
                    org_counter[org] += 1
            
            return GraphContext(
                central_topics=[t for t, _ in topic_counter.most_common(5)],
                key_organizations=[o for o, _ in org_counter.most_common(5)],
                key_people=[],
                related_entities=[],
                temporal_patterns=None
            )
    
    def _enhance_with_graph_data(
        self,
        related_entities: list[RelatedEntity],
        graph_data: dict,
    ) -> list[RelatedEntity]:
        """Enhance related entities with graph retriever data."""
        enhanced = list(related_entities)
        
        # Add related topics from graph retriever
        if "related_topics" in graph_data:
            for topic in graph_data["related_topics"]:
                if isinstance(topic, dict) and topic.get("name"):
                    # Check if already present
                    if not any(e.name == topic["name"] for e in enhanced):
                        enhanced.append(RelatedEntity(
                            name=topic["name"],
                            type="topic",
                            relevance=min(topic.get("co_occurrence", 1) / 10.0, 1.0)
                        ))
        
        # Add trending topics from graph retriever
        if "trending_topics" in graph_data:
            for topic in graph_data["trending_topics"]:
                if isinstance(topic, dict) and topic.get("name"):
                    # Check if already present
                    existing = next((e for e in enhanced if e.name == topic["name"]), None)
                    if existing:
                        # Boost relevance for trending topics
                        existing.relevance = min(existing.relevance * 1.5, 1.0)
                    else:
                        # Calculate relevance based on growth
                        growth = topic.get("growth_percentage", 0)
                        relevance = min(0.5 + (growth / 200.0), 1.0)  # Max 1.0
                        enhanced.append(RelatedEntity(
                            name=topic["name"],
                            type="trending_topic",
                            relevance=relevance
                        ))
        
        # Add collaboration data as related organizations
        if "collaborations" in graph_data:
            for collab in graph_data["collaborations"]:
                if isinstance(collab, dict):
                    for org_key in ["org1", "org2"]:
                        org_name = collab.get(org_key)
                        if org_name and not any(e.name == org_name for e in enhanced):
                            enhanced.append(RelatedEntity(
                                name=org_name,
                                type="collaborating_org",
                                relevance=min(collab.get("collaboration_count", 1) / 5.0, 1.0)
                            ))
        
        # Add organization contributions (mentions/involvement rankings)
        if "org_contributions" in graph_data:
            for item in graph_data["org_contributions"]:
                if isinstance(item, dict):
                    # Handle topic-org breakdown format: {topic, organizations: [{name, count}]}
                    if "organizations" in item:
                        for org in item.get("organizations", []):
                            if isinstance(org, dict) and org.get("name"):
                                org_name = org["name"]
                                if not any(e.name == org_name for e in enhanced):
                                    # Use count as relevance indicator
                                    count = org.get("count", 1)
                                    relevance = min(count / 10.0, 1.0)
                                    enhanced.append(RelatedEntity(
                                        name=org_name,
                                        type="contributing_org",
                                        relevance=relevance
                                    ))
                    # Handle flat org format: {name, mention_count, ...}
                    elif item.get("name"):
                        org_name = item["name"]
                        existing = next((e for e in enhanced if e.name == org_name and e.type in ["organization", "collaborating_org"]), None)
                        if existing:
                            # Boost relevance based on mention count
                            mention_count = item.get("mention_count", 0)
                            existing.relevance = min(existing.relevance + (mention_count / 50.0), 1.0)
                        else:
                            # Calculate relevance from mention count
                            mention_count = item.get("mention_count", 1)
                            relevance = min(mention_count / 20.0, 1.0)
                            enhanced.append(RelatedEntity(
                                name=org_name,
                                type="contributing_org",
                                relevance=relevance
                            ))
        
        # Limit total and sort by relevance
        enhanced.sort(key=lambda e: e.relevance, reverse=True)
        return enhanced[:15]  # Limit to top 15
    
    async def _get_related_entities(
        self,
        topics: list[str],
        organizations: list[str]
    ) -> list[RelatedEntity]:
        """Get entities related to the central topics and orgs."""
        related = []
        
        if not topics and not organizations:
            return related
        
        try:
            repo = get_repo()
            
            # Query for related topics
            if topics:
                query = """
                MATCH (t:Topic)
                WHERE t.name IN $topics
                MATCH (t)<-[:RELATES_TO]-(r:Resource)-[:RELATES_TO]->(related:Topic)
                WHERE NOT related.name IN $topics
                WITH related, count(r) AS co_occurrence
                ORDER BY co_occurrence DESC
                LIMIT 5
                RETURN related.name AS name, 'topic' AS type, co_occurrence
                """
                
                results = repo.client.execute_query(query, {"topics": topics})
                
                for row in results:
                    if row.get("name"):
                        related.append(RelatedEntity(
                            name=row["name"],
                            type="topic",
                            relevance=min(row.get("co_occurrence", 1) / 10.0, 1.0)
                        ))
            
            # Query for related organizations
            if organizations:
                query = """
                MATCH (o:Organization)
                WHERE o.name IN $orgs
                MATCH (o)<-[:MENTIONS]-(r:Resource)-[:MENTIONS]->(related:Organization)
                WHERE NOT related.name IN $orgs
                WITH related, count(r) AS co_occurrence
                ORDER BY co_occurrence DESC
                LIMIT 5
                RETURN related.name AS name, 'organization' AS type, co_occurrence
                """
                
                results = repo.client.execute_query(query, {"orgs": organizations})
                
                for row in results:
                    if row.get("name"):
                        related.append(RelatedEntity(
                            name=row["name"],
                            type="organization",
                            relevance=min(row.get("co_occurrence", 1) / 10.0, 1.0)
                        ))
            
        except Exception as e:
            logger.warning(f"Failed to get related entities from graph: {e}")
        
        return related[:10]  # Limit total related entities
    
    async def _get_key_people(
        self,
        documents: list[Document],
        graph_data: Optional[dict] = None,
    ) -> list[str]:
        """Extract key people mentioned in documents or from graph data."""
        people = []
        
        # First check if graph_data has people info
        if graph_data and "people" in graph_data:
            for person in graph_data["people"]:
                if isinstance(person, dict) and person.get("name"):
                    people.append(person["name"])
            if people:
                return people[:5]  # Return top 5
        
        # Otherwise query the graph
        try:
            repo = get_repo()
            
            # Get URLs of documents
            urls = [doc.url for doc in documents if doc.url]
            
            if urls:
                query = """
                MATCH (r:Resource)
                WHERE r.url IN $urls
                MATCH (r)-[:MENTIONS]->(p:Person)
                WITH p, count(r) AS mentions
                ORDER BY mentions DESC
                LIMIT 5
                RETURN p.name AS name
                """
                
                results = repo.client.execute_query(query, {"urls": urls})
                
                for row in results:
                    if row.get("name"):
                        people.append(row["name"])
                        
        except Exception as e:
            logger.warning(f"Failed to get key people from graph: {e}")
        
        return people
    
    def _analyze_temporal_patterns(
        self,
        documents: list[Document],
        graph_data: Optional[dict] = None,
    ) -> Optional[str]:
        """Analyze temporal patterns in the documents."""
        # Check for trending topic info from graph retriever
        if graph_data and "trending_topics" in graph_data:
            trending = graph_data["trending_topics"]
            if trending and len(trending) > 0:
                top_trend = trending[0]
                if isinstance(top_trend, dict):
                    growth = top_trend.get("growth_percentage", 0)
                    name = top_trend.get("name", "unknown")
                    if growth > 50:
                        return f"Strong growth in '{name}' (+{growth}% vs previous period)"
                    elif growth > 0:
                        return f"Growing interest in '{name}' (+{growth}% vs previous period)"
        
        # Check for period info
        if graph_data and "period" in graph_data:
            period = graph_data["period"]
            if isinstance(period, dict):
                start = period.get("start", "")
                end = period.get("end", "")
                if start and end:
                    return f"Analysis period: {start} to {end}"
        
        if not documents:
            return None
        
        # Get documents with dates
        dated_docs = [d for d in documents if d.publish_date]
        
        if not dated_docs:
            return "No temporal information available"
        
        # Parse dates and analyze
        try:
            from datetime import datetime
            
            dates = []
            for doc in dated_docs:
                try:
                    # Handle various date formats
                    date_str = doc.publish_date
                    if 'T' in date_str:
                        date_str = date_str.split('T')[0]
                    date = datetime.strptime(date_str[:10], '%Y-%m-%d')
                    dates.append(date)
                except (ValueError, TypeError):
                    continue
            
            if not dates:
                return "Unable to parse document dates"
            
            dates.sort()
            
            # Calculate date range
            earliest = dates[0]
            latest = dates[-1]
            range_days = (latest - earliest).days
            
            # Count documents by month
            month_counts = Counter()
            for d in dates:
                month_key = d.strftime('%Y-%m')
                month_counts[month_key] += 1
            
            # Generate pattern description
            if range_days <= 7:
                pattern = f"All {len(dated_docs)} documents from the past week"
            elif range_days <= 30:
                pattern = f"Documents span {range_days} days ({len(dated_docs)} total)"
            elif range_days <= 90:
                most_active = month_counts.most_common(1)[0]
                pattern = f"Most activity in {most_active[0]} ({most_active[1]} documents)"
            else:
                pattern = f"Documents span {range_days // 30} months from {earliest.strftime('%B %Y')} to {latest.strftime('%B %Y')}"
            
            return pattern
            
        except Exception as e:
            logger.warning(f"Failed to analyze temporal patterns: {e}")
            return None
