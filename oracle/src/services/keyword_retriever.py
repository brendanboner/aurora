"""Keyword Retriever - Neo4j keyword-based document retrieval for Oracle Service."""

from dataclasses import dataclass
import logging
import os
from typing import Any, Optional

from neo4j_client.client import Neo4jClient
from neo4j_client.repository import GraphRepository

from src.models.response import Document, QueryIntent
from src.settings import settings

logger = logging.getLogger(__name__)

# Global repository cache
_repo: Optional[GraphRepository] = None


@dataclass
class RetrievalResult:
    """Result of document retrieval."""
    documents: list[Document]
    total_candidates: int


def get_repo() -> GraphRepository:
    """Get a connected GraphRepository with host fallbacks."""
    global _repo
    
    if _repo is not None:
        return _repo
    
    # Use Neo4j settings from environment
    env_uri = settings.neo4j_uri
    candidates = []
    
    if env_uri:
        candidates.append(env_uri)
    
    # Add common service DNS names as fallbacks
    for host in ["bolt://neo4j:7687", "bolt://aurora-neo4j:7687", "bolt://localhost:7687"]:
        if host not in candidates:
            candidates.append(host)
    
    last_error = None
    for uri in candidates:
        try:
            client = Neo4jClient(
                uri=uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database=settings.neo4j_database
            )
            client.connect()
            _repo = GraphRepository(client)
            logger.info(f"Connected to Neo4j via {uri}")
            return _repo
        except Exception as e:
            last_error = e
            logger.warning(f"Neo4j connection attempt failed for {uri}: {e}")
            continue
    
    # All attempts failed
    fallback_uri = candidates[0] if candidates else "bolt://localhost:7687"
    logger.error(f"All Neo4j connection attempts failed; using fallback URI {fallback_uri}. Last error: {last_error}")
    client = Neo4jClient(
        uri=fallback_uri,
        user=settings.neo4j_user,
        password=settings.neo4j_password,
        database=settings.neo4j_database
    )
    _repo = GraphRepository(client)
    return _repo


def _convert_datetime(value: Any) -> Optional[str]:
    """Convert Neo4j DateTime to ISO string."""
    if value is None:
        return None
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return str(value)


class KeywordRetriever:
    """Retrieves documents using keyword-based Neo4j queries."""
    
    async def retrieve(
        self,
        query: str,
        filters: dict,
        intent: QueryIntent,
        max_results: int = 20
    ) -> RetrievalResult:
        """
        Retrieve documents matching the query and filters.
        
        Args:
            query: Original user query (for keyword extraction)
            filters: Parsed filters (topics, orgs, dates, etc.)
            intent: Classified query intent
            max_results: Maximum documents to return
            
        Returns:
            RetrievalResult with documents and metadata
        """
        try:
            repo = get_repo()
            
            # Build filter parameters
            topics = filters.get("topics") or []
            organizations = filters.get("organizations") or []
            people = filters.get("people") or []
            start_date = filters.get("start_date")
            end_date = filters.get("end_date")
            category = filters.get("category")
            keywords = filters.get("keywords") or []
            datasource_ids = filters.get("datasource_ids") or []
            
            logger.info(f"Retrieving documents: topics={topics}, orgs={organizations}, dates={start_date}-{end_date}, datasources={datasource_ids}")
            
            # When filtering by datasource, fetch more documents to ensure we have enough after filtering
            pool_multiplier = settings.retrieval_pool_multiplier
            if datasource_ids:
                pool_multiplier = pool_multiplier * 3  # Fetch 3x more when datasource filtering
            
            # Use the repository's get_recent_resources method
            rows = repo.get_recent_resources(
                start=start_date,
                end=end_date,
                topics=topics,
                organisations=organizations,
                people=people,
                category=category,
                doc_type=None,
                limit=max_results * pool_multiplier  # Fetch more for better re-ranking
            )
            
            # Convert to Document models
            documents = []
            for row in rows:
                # Handle different response formats from the repository
                if isinstance(row, dict):
                    resource = row.get("r") or row.get("resource") or row
                else:
                    resource = row
                
                # Extract resource properties
                if hasattr(resource, '__getitem__'):
                    # Dict-like access
                    props = resource
                elif hasattr(resource, '_properties'):
                    # Neo4j Node object
                    props = resource._properties
                else:
                    props = {}
                
                # Extract topics and organizations from row
                doc_topics = []
                doc_orgs = []
                doc_source = None
                doc_datasource_id = None
                
                if isinstance(row, dict):
                    if "topics" in row:
                        doc_topics = [t.get("name") if isinstance(t, dict) else str(t) for t in row["topics"]]
                    if "organisations" in row or "organizations" in row:
                        orgs_data = row.get("organisations") or row.get("organizations") or []
                        doc_orgs = [o.get("name") if isinstance(o, dict) else str(o) for o in orgs_data]
                    # Extract datasource name and id
                    if "datasources" in row and row["datasources"]:
                        ds_list = row["datasources"]
                        if ds_list and len(ds_list) > 0:
                            ds = ds_list[0]
                            if isinstance(ds, dict):
                                doc_source = ds.get("name") or ds.get("datasource_id")
                                doc_datasource_id = ds.get("datasource_id")
                            elif hasattr(ds, '_properties'):
                                doc_source = ds._properties.get("name") or ds._properties.get("datasource_id")
                                doc_datasource_id = ds._properties.get("datasource_id")
                
                doc = Document(
                    url=props.get("url", ""),
                    title=props.get("title"),
                    summary=props.get("summary"),
                    publish_date=_convert_datetime(props.get("publish_date")),
                    source=doc_source or props.get("datasource_id"),
                    category=props.get("category"),
                    datasource_id=doc_datasource_id or props.get("datasource_id"),
                    topics=doc_topics,
                    organizations=doc_orgs,
                    relevance_score=self._calculate_relevance(props, filters, keywords),
                    match_reasons=self._get_match_reasons(props, filters)
                )
                documents.append(doc)
            
            # Filter by datasource_ids if specified
            if datasource_ids:
                documents = [d for d in documents if d.datasource_id in datasource_ids]
                logger.info(f"Filtered to {len(documents)} documents from specified datasources: {datasource_ids}")
            
            # Sort by relevance and limit
            documents.sort(key=lambda d: d.relevance_score, reverse=True)
            documents = documents[:max_results]
            
            logger.info(f"Retrieved {len(documents)} documents from {len(rows)} candidates")
            
            return RetrievalResult(
                documents=documents,
                total_candidates=len(rows)
            )
            
        except Exception as e:
            logger.error(f"Document retrieval failed: {e}")
            # Return empty result rather than failing
            return RetrievalResult(
                documents=[],
                total_candidates=0
            )
    
    def _calculate_relevance(
        self,
        props: dict,
        filters: dict,
        keywords: list[str]
    ) -> float:
        """
        Calculate a relevance score for a document.
        
        Enhanced scoring for video segments with event + entity co-occurrence.
        """
        score = 0.5  # Base score
        
        title = (props.get("title") or "").lower()
        summary = (props.get("summary") or "").lower()
        category = props.get("category", "").lower()
        
        # Track matches for co-occurrence bonus
        has_event_match = False
        has_org_match = False
        has_person_match = False
        
        # Boost for event matches (NEW - highest priority for video queries)
        events = filters.get("events") or []
        for event in events:
            event_lower = event.lower()
            if event_lower in title:
                score += 0.5  # Strong boost for event in title
                has_event_match = True
            elif event_lower in summary:
                score += 0.3  # Moderate boost for event in summary
                has_event_match = True
        
        # Boost for topic matches
        for topic in (filters.get("topics") or []):
            if topic.lower() in title:
                score += 0.15
            elif topic.lower() in summary:
                score += 0.1
        
        # Boost for organization matches
        for org in (filters.get("organizations") or []):
            org_lower = org.lower()
            if org_lower in title:
                score += 0.5  # Increased from 0.1
                has_org_match = True
            elif org_lower in summary:
                score += 0.3  # Increased from 0.05
                has_org_match = True
        
        # Boost for people matches
        for person in (filters.get("people") or []):
            person_lower = person.lower()
            if person_lower in title:
                score += 0.4  # Increased from 0.0
                has_person_match = True
            elif person_lower in summary:
                score += 0.2  # Increased from 0.0
                has_person_match = True
        
        # Boost for keyword matches
        for keyword in keywords:
            if keyword.lower() in title:
                score += 0.05
            elif keyword.lower() in summary:
                score += 0.02
        
        # Co-occurrence bonus: When multiple query entities match same document
        # This prevents cross-video contamination
        co_occurrence_count = sum([has_event_match, has_org_match, has_person_match])
        if co_occurrence_count >= 2:
            score += 0.3 * co_occurrence_count  # 0.6 for all three, 0.3 for two
            logger.debug(f"Co-occurrence bonus (+{0.3 * co_occurrence_count}): event={has_event_match}, org={has_org_match}, person={has_person_match}")
        
        # Video segment bonus: prefer specific segments over parent videos
        if category == "video" and "segment" in title.lower():
            score += 0.1
        
        # Cap at 1.0
        return min(score, 1.0)
    
    def _get_match_reasons(self, props: dict, filters: dict) -> list[str]:
        """Generate human-readable match reasons."""
        reasons = []
        
        title = (props.get("title") or "").lower()
        summary = (props.get("summary") or "").lower()
        
        # Event matches (highest priority)
        for event in (filters.get("events") or []):
            if event.lower() in title or event.lower() in summary:
                reasons.append(f"Event: {event}")
        
        for topic in (filters.get("topics") or []):
            if topic.lower() in title or topic.lower() in summary:
                reasons.append(f"Topic: {topic}")
        
        for org in (filters.get("organizations") or []):
            if org.lower() in title or org.lower() in summary:
                reasons.append(f"Organization: {org}")
        
        for person in (filters.get("people") or []):
            if person.lower() in title or person.lower() in summary:
                reasons.append(f"Person: {person}")
        
        if not reasons:
            reasons.append("Matched by recency")
        
        return reasons[:3]  # Limit reasons
