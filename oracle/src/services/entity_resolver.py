"""Entity Resolver - Resolve entity mentions against the knowledge graph.

This module resolves candidate entity names extracted from queries against
actual nodes in the Neo4j knowledge graph. It handles:
- Exact matches (fast path)
- Fuzzy/vector similarity matches (handles typos, aliases, variations)

Phase 2 enhancement for Oracle Service.
"""

import logging
from dataclasses import dataclass
from typing import Optional

from src.services.keyword_retriever import get_repo
from src.services.llm_client import generate_embedding
from src.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class ResolvedEntity:
    """An entity resolved against the graph."""
    original: str  # What user/LLM said
    resolved: str  # Actual graph node name
    entity_type: str  # "topic", "organization", "person"
    confidence: float  # Match confidence (1.0 for exact, lower for fuzzy)
    node_id: Optional[str] = None  # Graph node ID if available


@dataclass
class EntityResolutionResult:
    """Result of entity resolution."""
    topics: list[ResolvedEntity]
    organizations: list[ResolvedEntity]
    people: list[ResolvedEntity]
    unresolved: list[str]  # Entities that couldn't be matched


class EntityResolver:
    """Resolves entity mentions against the knowledge graph."""
    
    def __init__(self, min_similarity: float = 0.75):
        """
        Initialize the entity resolver.
        
        Args:
            min_similarity: Minimum similarity score for fuzzy matches
        """
        self.min_similarity = min_similarity
    
    async def resolve(
        self,
        topics: list[str],
        organizations: list[str],
        people: list[str],
    ) -> EntityResolutionResult:
        """
        Resolve candidate entities against the knowledge graph.
        
        Args:
            topics: Candidate topic names from query
            organizations: Candidate organization names from query
            people: Candidate person names from query
            
        Returns:
            EntityResolutionResult with resolved entities
        """
        resolved_topics = []
        resolved_orgs = []
        resolved_people = []
        unresolved = []
        
        # Resolve topics
        for topic in topics:
            result = await self._resolve_entity(topic, "topic")
            if result:
                resolved_topics.append(result)
            else:
                unresolved.append(topic)
        
        # Resolve organizations
        for org in organizations:
            result = await self._resolve_entity(org, "organization")
            if result:
                resolved_orgs.append(result)
            else:
                unresolved.append(org)
        
        # Resolve people
        for person in people:
            result = await self._resolve_entity(person, "person")
            if result:
                resolved_people.append(result)
            else:
                unresolved.append(person)
        
        if unresolved:
            logger.info(f"Could not resolve entities: {unresolved}")
        
        return EntityResolutionResult(
            topics=resolved_topics,
            organizations=resolved_orgs,
            people=resolved_people,
            unresolved=unresolved,
        )
    
    async def _resolve_entity(
        self,
        candidate: str,
        entity_type: str,
    ) -> Optional[ResolvedEntity]:
        """
        Resolve a single entity candidate against the graph.
        
        Strategy:
        1. Try exact match (case-insensitive)
        2. Try alias match
        3. Try vector similarity match
        """
        if not candidate or not candidate.strip():
            return None
        
        candidate = candidate.strip()
        
        # Step 1: Try exact match
        exact_match = await self._exact_match(candidate, entity_type)
        if exact_match:
            logger.debug(f"Exact match for '{candidate}': {exact_match.resolved}")
            return exact_match
        
        # Step 2: Try vector similarity match
        if settings.vector_search_enabled:
            vector_match = await self._vector_match(candidate, entity_type)
            if vector_match:
                logger.debug(f"Vector match for '{candidate}': {vector_match.resolved} (score: {vector_match.confidence:.2f})")
                return vector_match
        
        # No match found - return the original as-is (let retrieval handle it)
        logger.debug(f"No graph match for '{candidate}', using as-is")
        return ResolvedEntity(
            original=candidate,
            resolved=candidate,  # Use original
            entity_type=entity_type,
            confidence=0.5,  # Low confidence - not validated
        )
    
    async def _exact_match(
        self,
        candidate: str,
        entity_type: str,
    ) -> Optional[ResolvedEntity]:
        """Try to find an exact match (case-insensitive) or alias match."""
        try:
            repo = get_repo()
            client = repo.client
            
            label = self._get_label(entity_type)
            name_field = self._get_name_field(entity_type)
            id_field = self._get_id_field(entity_type)
            
            # Query for exact match on name or aliases
            cypher = f"""
            MATCH (n:{label})
            WHERE toLower(n.{name_field}) = toLower($candidate)
               OR toLower($candidate) IN [alias IN coalesce(n.aliases, []) | toLower(alias)]
            RETURN n.{name_field} AS name, n.{id_field} AS node_id
            LIMIT 1
            """
            
            results = client.execute_query(cypher, {"candidate": candidate})
            
            if results:
                record = results[0]
                return ResolvedEntity(
                    original=candidate,
                    resolved=record["name"],
                    entity_type=entity_type,
                    confidence=1.0,
                    node_id=record.get("node_id"),
                )
            
            return None
            
        except Exception as e:
            logger.warning(f"Exact match query failed for '{candidate}': {e}")
            return None
    
    async def _vector_match(
        self,
        candidate: str,
        entity_type: str,
    ) -> Optional[ResolvedEntity]:
        """Try to find a match using vector similarity."""
        try:
            # Generate embedding for the candidate
            embedding = await generate_embedding(candidate)
            if not embedding:
                return None
            
            repo = get_repo()
            client = repo.client
            
            label = self._get_label(entity_type)
            index_name = self._get_vector_index(entity_type)
            name_field = self._get_name_field(entity_type)
            id_field = self._get_id_field(entity_type)
            
            # Query vector index
            cypher = f"""
            CALL db.index.vector.queryNodes('{index_name}', 5, $embedding)
            YIELD node AS n, score
            WHERE score >= $min_score
            RETURN n.{name_field} AS name, n.{id_field} AS node_id, score
            ORDER BY score DESC
            LIMIT 1
            """
            
            results = client.execute_query(
                cypher,
                {
                    "embedding": embedding,
                    "min_score": self.min_similarity,
                }
            )
            
            if results:
                record = results[0]
                return ResolvedEntity(
                    original=candidate,
                    resolved=record["name"],
                    entity_type=entity_type,
                    confidence=float(record["score"]),
                    node_id=record.get("node_id"),
                )
            
            return None
            
        except Exception as e:
            logger.warning(f"Vector match query failed for '{candidate}': {e}")
            return None
    
    def _get_label(self, entity_type: str) -> str:
        """Get Neo4j node label for entity type."""
        return {
            "topic": "Topic",
            "organization": "Organization",
            "person": "Person",
        }.get(entity_type, "Topic")
    
    def _get_name_field(self, entity_type: str) -> str:
        """Get the name field for entity type."""
        return "name"  # All entity types use 'name'
    
    def _get_id_field(self, entity_type: str) -> str:
        """Get the ID field for entity type."""
        return {
            "topic": "topic_id",
            "organization": "org_id",
            "person": "person_id",
        }.get(entity_type, "id")
    
    def _get_vector_index(self, entity_type: str) -> str:
        """Get the vector index name for entity type."""
        return {
            "topic": "topic_embedding_index",
            "organization": "organization_embedding_index",
            "person": "person_embedding_index",
        }.get(entity_type, "topic_embedding_index")


# Convenience function
async def resolve_entities(
    topics: list[str] = None,
    organizations: list[str] = None,
    people: list[str] = None,
) -> EntityResolutionResult:
    """
    Convenience function to resolve entities.
    
    Args:
        topics: Candidate topic names
        organizations: Candidate organization names
        people: Candidate person names
        
    Returns:
        EntityResolutionResult with resolved entities
    """
    resolver = EntityResolver()
    return await resolver.resolve(
        topics=topics or [],
        organizations=organizations or [],
        people=people or [],
    )
