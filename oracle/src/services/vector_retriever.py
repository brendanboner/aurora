"""Vector Retriever - Semantic search using Neo4j vector indexes for Oracle Service.

This module implements vector-based document retrieval using embeddings stored in Neo4j.
It enables semantic similarity search to find conceptually related documents even when
the exact keywords don't match (handles typos, synonyms, conceptual variations).

Phase 2 of Oracle Service implementation.
"""

from dataclasses import dataclass
import logging
from typing import Any, Optional
from datetime import datetime, timedelta

from src.models.response import Document, QueryIntent
from src.services.keyword_retriever import get_repo, _convert_datetime
from src.services.llm_client import generate_embedding
from src.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class VectorSearchResult:
    """Result of vector search operation."""
    documents: list[Document]
    total_candidates: int
    query_embedding_generated: bool


class VectorRetriever:
    """Retrieves documents using vector similarity search in Neo4j."""
    
    async def retrieve(
        self,
        query: str,
        filters: dict,
        intent: QueryIntent,
        max_results: int = 50,
        min_score: float = None,
    ) -> VectorSearchResult:
        """
        Retrieve documents using semantic similarity search.
        
        Args:
            query: User's natural language query
            filters: Parsed filters (used for post-filtering)
            intent: Classified query intent
            max_results: Maximum documents to return
            min_score: Minimum cosine similarity score (default from settings)
            
        Returns:
            VectorSearchResult with documents and metadata
        """
        min_score = min_score or settings.vector_min_score
        
        try:
            # Step 1: Generate embedding for the query
            logger.info(f"Generating embedding for query: {query[:100]}...")
            query_embedding = await generate_embedding(query)
            
            if not query_embedding:
                logger.warning("Failed to generate query embedding")
                return VectorSearchResult(
                    documents=[],
                    total_candidates=0,
                    query_embedding_generated=False
                )
            
            # Step 2: Execute vector search in Neo4j
            repo = get_repo()
            documents = await self._execute_vector_search(
                repo=repo,
                embedding=query_embedding,
                max_results=max_results,
                min_score=min_score,
                filters=filters,
            )
            
            logger.info(f"Vector search returned {len(documents)} documents")
            
            return VectorSearchResult(
                documents=documents,
                total_candidates=len(documents),
                query_embedding_generated=True
            )
            
        except Exception as e:
            logger.error(f"Vector retrieval failed: {e}")
            return VectorSearchResult(
                documents=[],
                total_candidates=0,
                query_embedding_generated=False
            )
    
    async def _execute_vector_search(
        self,
        repo,
        embedding: list[float],
        max_results: int,
        min_score: float,
        filters: dict,
    ) -> list[Document]:
        """
        Execute vector similarity search in Neo4j.
        
        Uses Neo4j's native vector index for cosine similarity search.
        """
        try:
            # Build datasource filter for Cypher query
            datasource_ids = filters.get("datasource_ids") or []
            datasource_filter = ""
            params = {
                "query_embedding": embedding,
                "top_k": max_results * 3,  # Fetch extra for post-filtering
                "min_score": min_score,
                "limit": max_results,
            }
            
            if datasource_ids:
                datasource_filter = " AND ds.datasource_id IN $datasource_ids"
                params["datasource_ids"] = datasource_ids
            
            # Build the Cypher query for vector search
            # The vector index query returns (node, score) tuples
            cypher = f"""
            CALL db.index.vector.queryNodes('resource_embedding_index', $top_k, $query_embedding)
            YIELD node AS r, score
            WHERE score >= $min_score
            
            // Join with datasource for filtering (required match when filtering)
            MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
            WHERE true {datasource_filter}
            
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
            WITH r, score, 
                 collect(DISTINCT t.name) AS topics, 
                 collect(DISTINCT o.name) AS organizations,
                 ds.name AS datasource_name,
                 ds.datasource_id AS datasource_id
            RETURN r, score, topics, organizations, datasource_name, datasource_id
            ORDER BY score DESC
            LIMIT $limit
            """
            
            # Execute the query using Neo4jClient's execute_query method
            client = repo.client
            results = client.execute_query(cypher, params)
            
            documents = []
            for record in results:
                resource = record.get("r", {})
                score = record.get("score", 0.0)
                topics = record.get("topics") or []
                organizations = record.get("organizations") or []
                datasource_name = record.get("datasource_name")
                datasource_id = record.get("datasource_id")
                
                # Extract properties from Neo4j node (already a dict from execute_query)
                props = resource if isinstance(resource, dict) else {}
                
                # Apply date filters if specified
                if not self._passes_date_filter(props, filters):
                    continue
                
                doc = Document(
                    url=props.get("url", ""),
                    title=props.get("title"),
                    summary=props.get("summary"),
                    publish_date=_convert_datetime(props.get("publish_date")),
                    source=datasource_name or props.get("datasource_id"),
                    category=props.get("category"),
                    datasource_id=datasource_id or props.get("datasource_id"),
                    topics=[t for t in topics if t],
                    organizations=[o for o in organizations if o],
                    relevance_score=float(score),
                    match_reasons=[f"Semantic similarity: {score:.2f}"]
                )
                documents.append(doc)
            
            # Note: datasource filtering is now done in Cypher query for efficiency
            
            return documents
                
        except Exception as e:
            logger.error(f"Vector search query failed: {e}")
            # Check if it's an index-related error
            if "index" in str(e).lower():
                logger.warning(
                    "Vector index may not exist. Run recreate_vector_indexes.py to create indexes."
                )
            raise
    
    def _passes_date_filter(self, props: dict, filters: dict) -> bool:
        """Check if document passes date filters."""
        start_date = filters.get("start_date")
        end_date = filters.get("end_date")
        
        if not start_date and not end_date:
            return True
        
        publish_date = props.get("publish_date")
        if not publish_date:
            return True  # Allow documents without dates
        
        # Parse publish_date if it's a string
        if isinstance(publish_date, str):
            try:
                publish_date = datetime.fromisoformat(publish_date.replace("Z", "+00:00"))
            except ValueError:
                return True
        
        # Handle Neo4j DateTime objects
        if hasattr(publish_date, 'to_native'):
            publish_date = publish_date.to_native()
        
        # Normalize to date for comparison
        if hasattr(publish_date, 'date'):
            publish_date = publish_date.date()
        
        if start_date:
            if isinstance(start_date, str):
                start_date = datetime.fromisoformat(start_date).date()
            elif hasattr(start_date, 'date'):
                start_date = start_date.date()
            if publish_date < start_date:
                return False
        
        if end_date:
            if isinstance(end_date, str):
                end_date = datetime.fromisoformat(end_date).date()
            elif hasattr(end_date, 'date'):
                end_date = end_date.date()
            if publish_date > end_date:
                return False
        
        return True


async def search_similar_topics(
    query: str,
    max_results: int = 10,
    min_score: float = 0.7,
) -> list[dict]:
    """
    Search for topics similar to the query using vector search.
    
    Useful for finding related topics when user's terminology doesn't
    exactly match the knowledge graph.
    
    Args:
        query: Search query
        max_results: Maximum topics to return
        min_score: Minimum similarity score
        
    Returns:
        List of dicts with topic name, description, and similarity score
    """
    try:
        query_embedding = await generate_embedding(query)
        if not query_embedding:
            return []
        
        repo = get_repo()
        client = repo.client
        
        cypher = """
        CALL db.index.vector.queryNodes('topic_embedding_index', $top_k, $query_embedding)
        YIELD node AS t, score
        WHERE score >= $min_score
        RETURN t.name AS name, t.description AS description, score
        ORDER BY score DESC
        LIMIT $limit
        """
        
        results = client.execute_query(
            cypher,
            {
                "query_embedding": query_embedding,
                "top_k": max_results * 2,
                "min_score": min_score,
                "limit": max_results,
            }
        )
        
        topics = []
        for record in results:
            topics.append({
                "name": record["name"],
                "description": record.get("description"),
                "score": record["score"],
            })
        
        return topics
            
    except Exception as e:
        logger.error(f"Topic similarity search failed: {e}")
        return []


async def search_similar_organizations(
    query: str,
    max_results: int = 10,
    min_score: float = 0.7,
) -> list[dict]:
    """
    Search for organizations similar to the query using vector search.
    
    Useful for finding organizations when user's input has typos or
    uses different naming conventions.
    
    Args:
        query: Search query
        max_results: Maximum organizations to return
        min_score: Minimum similarity score
        
    Returns:
        List of dicts with org name, description, and similarity score
    """
    try:
        query_embedding = await generate_embedding(query)
        if not query_embedding:
            return []
        
        repo = get_repo()
        client = repo.client
        
        cypher = """
        CALL db.index.vector.queryNodes('organization_embedding_index', $top_k, $query_embedding)
        YIELD node AS o, score
        WHERE score >= $min_score
        RETURN o.name AS name, o.description AS description, score
        ORDER BY score DESC
        LIMIT $limit
        """
        
        results = client.execute_query(
            cypher,
            {
                "query_embedding": query_embedding,
                "top_k": max_results * 2,
                "min_score": min_score,
                "limit": max_results,
            }
        )
        
        orgs = []
        for record in results:
            orgs.append({
                "name": record["name"],
                "description": record.get("description"),
                "score": record["score"],
            })
        
        return orgs
            
    except Exception as e:
        logger.error(f"Organization similarity search failed: {e}")
        return []
