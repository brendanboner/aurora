"""Content generation orchestration for CreatorAgents."""
from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from ..llm_client import get_llm_client
from ..models.agent import CreatorAgent
from ..models.post import PostSource
from ..neo4j_context import get_context_gateway
from ..settings import get_settings
from .oracle_client import OracleAgentClient
from .prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


class GenerationService:
    def __init__(self) -> None:
        self._context = get_context_gateway()
        self._settings = get_settings()
        self._prompt_builder = PromptBuilder()
        self._oracle_client = OracleAgentClient()
        self._use_oracle = getattr(self._settings, 'use_oracle_for_discovery', True)

    def build_prompt(self, agent: CreatorAgent, context_payload: Dict[str, Any]) -> Dict[str, str]:
        """Legacy method for backward compatibility. Use PromptBuilder instead."""
        system_prompt = self._prompt_builder.build_system_prompt(agent)
        user_prompt = self._prompt_builder.build_user_prompt(
            agent,
            context_payload.get("events", []),
            context_payload.get("documents", []),
        )
        return {"system": system_prompt, "user": user_prompt}

    def generate_post_payload(
        self,
        agent: CreatorAgent,
        topics: Optional[List[str]] = None,
        organisations: Optional[List[str]] = None,
        perspective: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Generate a post with full context including agent history and user feedback.
        
        Now uses Oracle service for content discovery with:
        - Pre-computed rollups for performance
        - Automatic deduplication via used content tracking
        - Relevance scoring optimized for agents
        - Cadence-based routing (daily/weekly/monthly)
        """
        topic_scope = topics or agent.expertise_topics
        organisation_scope = organisations or agent.expertise_organisations

        # Determine time window from agent's cadence or use system default
        cadence_days = agent.cadence_window_days if agent.cadence_window_days else self._settings.temporal_window_days_default
        
        # Fetch previously used content IDs for deduplication
        used_content_ids = self._fetch_used_content_ids(agent.id, lookback_days=cadence_days * 2)
        
        # Try Oracle-based discovery first
        if self._use_oracle:
            try:
                logger.info(
                    "Using Oracle discovery for agent %s: topics=%s, orgs=%s, cadence=%d days, excluding %d IDs",
                    agent.name,
                    topic_scope,
                    organisation_scope,
                    cadence_days,
                    len(used_content_ids),
                )
                
                # Call Oracle async method from sync context
                oracle_result = asyncio.run(
                    self._oracle_client.discover_content(
                        agent_id=agent.id,
                        agent_name=agent.name,
                        topics=topic_scope,
                        organizations=organisation_scope,
                        cadence_days=cadence_days,
                        last_content_ids=used_content_ids,
                        perspective=perspective,
                        limit=30,
                    )
                )
                
                logger.info(
                    "Oracle discovery for agent %s: route=%s, items=%d, rollup=%s, excluded=%d",
                    agent.name,
                    oracle_result.get("route_used"),
                    len(oracle_result.get("content_items", [])),
                    oracle_result.get("rollup_used"),
                    oracle_result.get("excluded_count", 0),
                )
                
                # Transform Oracle content items to events/documents format
                events, documents = self._transform_oracle_content(oracle_result.get("content_items", []))
                
            except Exception as e:
                logger.warning("Oracle discovery failed for agent %s: %s - falling back to Neo4j", agent.name, e)
                # Fall through to Neo4j fallback
                events, documents = self._fetch_from_neo4j(
                    agent,
                    topic_scope,
                    organisation_scope,
                    cadence_days,
                )
        else:
            # Direct Neo4j access (legacy path)
            events, documents = self._fetch_from_neo4j(
                agent,
                topic_scope,
                organisation_scope,
                cadence_days,
            )

        if not events and not documents:
            logger.info("No context available for agent %s (topics: %s, orgs: %s, window: %d days)", 
                       agent.name, topic_scope, organisation_scope, window_days)
            return None

        # Apply diversity filtering to prevent duplicate coverage
        events_before_diversity = len(events)
        documents_before_diversity = len(documents)
        events = self._apply_diversity_filter(events, max_items=8)
        documents = self._apply_diversity_filter(documents, max_items=8)
        logger.info("After diversity filtering: %d events (was %d), %d documents (was %d) for agent %s", 
                   len(events), events_before_diversity, len(documents), documents_before_diversity, agent.name)
        
        # Note: Relevance filtering already done in Neo4j query, no need to re-filter
        # This ensures we don't over-filter and lose valid content
        
        if not events and not documents:
            logger.info("No high-quality context available for agent %s after filtering", agent.name)
            return None

        # Fetch agent's recent posts for deduplication
        recent_posts = self._fetch_agent_recent_posts(agent.id, limit=5)
        
        # Fetch recent posts from ALL agents for cross-agent deduplication
        all_agents_posts = self._fetch_all_recent_posts(exclude_agent_id=agent.id, limit=10)

        # Fetch user reactions to recent posts for preference signals
        user_reactions = self._aggregate_user_reactions(recent_posts)

        # Build rich prompt with all context
        system_prompt = self._prompt_builder.build_system_prompt(agent)
        user_prompt = self._prompt_builder.build_user_prompt(
            agent,
            events=events,
            documents=documents,
            recent_posts=recent_posts,
            user_reactions=user_reactions,
            all_agents_recent_posts=all_agents_posts,
        )

        # Determine temperature (agent override or system default)
        temperature = agent.llm_temperature_override if agent.llm_temperature_override is not None else None

        # Call LLM with enriched prompt and temperature
        logger.info("Calling LLM for agent %s with temperature=%s", agent.name, temperature)
        llm_client = get_llm_client()
        llm_response = llm_client.generate(system_prompt, user_prompt, temperature_override=temperature)

        if not llm_response:
            logger.warning("LLM generation failed for agent %s - check LLM service connectivity", agent.name)
            return None
            
        logger.info("LLM response for agent %s: keys=%s", agent.name, list(llm_response.keys()) if llm_response else "None")

        # Coerce sources from LLM response or fallback to context
        sources = self._coerce_sources(llm_response.get("sources"), events, documents)

        return {
            "title": llm_response.get("title", "Untitled update"),
            "summary": llm_response.get("summary"),
            "body": llm_response.get("body"),
            "tags": llm_response.get("tags", topic_scope),
            "visibility": llm_response.get("visibility", "public"),
            "importance": llm_response.get("importance", agent.importance_threshold),
            "content_length": llm_response.get("content_length", agent.content_length_preference),
            "sources": sources,
        }

    def _fetch_agent_recent_posts(self, agent_id: int, limit: int = 5) -> List[Dict[str, Any]]:
        """Fetch agent's recent posts for deduplication context."""
        try:
            from .. import db
            
            rows = db.fetch_all(
                """
                SELECT id, title, body, created_at
                FROM post
                WHERE agent_id = %s
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (agent_id, limit),
            )

            return [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "body": row["body"][:200] if row["body"] else "",  # Truncate for prompt context
                    "created_at": row["created_at"],
                }
                for row in rows
            ]
        except Exception as e:
            logger.warning("Failed to fetch recent posts for agent %d: %s", agent_id, e)
            return []
    
    def _fetch_used_content_ids(self, agent_id: int, lookback_days: int = 30) -> List[str]:
        """Extract content IDs from agent's recent posts for deduplication."""
        try:
            from .. import db
            
            # Get source_identifiers from post_source for this agent's recent posts
            rows = db.fetch_all(
                """
                SELECT DISTINCT ps.source_identifier
                FROM post_source ps
                JOIN post p ON p.id = ps.post_id
                WHERE p.agent_id = %s
                  AND p.created_at >= NOW() - INTERVAL '%s days'
                  AND ps.source_identifier IS NOT NULL
                ORDER BY ps.source_identifier
                """,
                (agent_id, lookback_days),
            )
            
            content_ids = [row["source_identifier"] for row in rows]
            logger.info(
                "Agent %d has used %d content IDs in last %d days",
                agent_id,
                len(content_ids),
                lookback_days,
            )
            return content_ids
            
        except Exception as e:
            logger.warning("Failed to fetch used content IDs for agent %d: %s", agent_id, e)
            return []
    
    def _apply_diversity_filter(
        self, 
        articles: List[Dict[str, Any]], 
        max_items: int = 8,
        similarity_threshold: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """
        Filter articles to prevent duplicates and ensure diversity.
        
        Removes articles that are too similar based on:
        - Exact URL match (same source)
        - Title similarity (Jaccard similarity > threshold)
        - Same domain within short time window
        
        Returns up to max_items diverse articles, preserving relevance score order.
        """
        if not articles:
            return []
        
        # Use configured threshold if not provided
        if similarity_threshold is None:
            similarity_threshold = self._settings.diversity_similarity_threshold
        
        # Get max articles per domain from settings
        max_per_domain = self._settings.max_articles_per_domain
        
        def get_domain(url: str) -> str:
            """Extract domain from URL."""
            if not url:
                return ""
            try:
                from urllib.parse import urlparse
                parsed = urlparse(url)
                return parsed.netloc.lower()
            except:
                return ""
        
        def title_similarity(title1: str, title2: str) -> float:
            """Calculate Jaccard similarity between two titles."""
            if not title1 or not title2:
                return 0.0
            
            # Normalize and tokenize
            tokens1 = set(title1.lower().split())
            tokens2 = set(title2.lower().split())
            
            if not tokens1 or not tokens2:
                return 0.0
            
            # Jaccard similarity: intersection / union
            intersection = len(tokens1 & tokens2)
            union = len(tokens1 | tokens2)
            
            return intersection / union if union > 0 else 0.0
        
        diverse_articles = []
        seen_urls = set()
        seen_domains_recent = {}  # domain -> most recent timestamp
        
        for article in articles:
            url = article.get("url", "")
            title = article.get("title", "")
            domain = get_domain(url)
            
            # Skip exact URL duplicates
            if url and url in seen_urls:
                logger.debug("Skipping duplicate URL: %s", title)
                continue
            
            # Check title similarity with already selected articles
            too_similar = False
            for selected in diverse_articles:
                selected_title = selected.get("title", "")
                similarity = title_similarity(title, selected_title)
                if similarity >= similarity_threshold:
                    logger.debug(
                        "Skipping similar article (%.2f): '%s' vs '%s'",
                        similarity,
                        title[:50],
                        selected_title[:50],
                    )
                    too_similar = True
                    break
            
            if too_similar:
                continue
            
            # Limit articles from same domain in short time window
            if domain and domain in seen_domains_recent:
                # Allow multiple from same domain if spaced apart or very different
                # Use configurable max_per_domain setting
                domain_count = sum(1 for a in diverse_articles if get_domain(a.get("url", "")) == domain)
                if domain_count >= max_per_domain:
                    logger.debug("Skipping article from over-represented domain: %s", domain)
                    continue
            
            # Add to diverse set
            diverse_articles.append(article)
            if url:
                seen_urls.add(url)
            if domain:
                seen_domains_recent[domain] = article.get("publish_date")
            
            # Stop when we have enough
            if len(diverse_articles) >= max_items:
                break
        
        logger.debug(
            "Diversity filter: %d -> %d articles (removed %d duplicates/similar)",
            len(articles),
            len(diverse_articles),
            len(articles) - len(diverse_articles),
        )
        
        return diverse_articles
    
    def _fetch_all_recent_posts(self, exclude_agent_id: int, limit: int = 10) -> List[Dict[str, Any]]:
        """Fetch recent posts from all agents (excluding current) for cross-agent deduplication."""
        try:
            from .. import db
            
            rows = db.fetch_all(
                """
                SELECT p.id, p.title, p.body, p.created_at, ca.name as agent_name
                FROM post p
                JOIN creator_agent ca ON p.agent_id = ca.id
                WHERE p.agent_id != %s
                ORDER BY p.created_at DESC
                LIMIT %s
                """,
                (exclude_agent_id, limit),
            )

            return [
                {
                    "id": row["id"],
                    "title": row["title"],
                    "body": row["body"][:200] if row["body"] else "",  # Truncate for prompt context
                    "created_at": row["created_at"],
                    "agent_name": row["agent_name"],
                }
                for row in rows
            ]
        except Exception as e:
            logger.warning("Failed to fetch all recent posts: %s", e)
            return []
    
    def _transform_oracle_content(self, content_items: List[Dict[str, Any]]) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        \"\"\"
        Transform Oracle content items into events and documents format.
        
        Oracle returns unified content with:
        - id, title, summary, publish_date, url, category
        - topics, organizations, events, people
        - relevance_score
        
        We split into events (has events array) and documents (publications/decisions).
        \"\"\"
        events = []
        documents = []
        
        for item in content_items:
            # Check if this is event-related content
            has_events = item.get("events") and len(item.get("events", [])) > 0
            
            # Base structure
            transformed = {
                "id": item.get("id"),
                "title": item.get("title"),
                "summary": item.get("summary", ""),
                "url": item.get("url"),
                "publish_date": item.get("publish_date"),
                "topics": item.get("topics", []),
                "organizations": item.get("organizations", []),
                "relevance_score": item.get("relevance_score", 0.0),
                "category": item.get("category"),
            }
            
            if has_events:
                # Event-related content
                transformed["events"] = item.get("events", [])
                transformed["people"] = item.get("people", [])
                events.append(transformed)
            else:
                # Document content (publications, decisions, etc.)
                transformed["authors"] = item.get("people", [])  # People as authors
                documents.append(transformed)
        
        logger.info(
            "Transformed Oracle content: %d events, %d documents from %d items",
            len(events),
            len(documents),
            len(content_items),
        )
        
        return events, documents
    
    def _fetch_from_neo4j(
        self,
        agent: CreatorAgent,
        topics: List[str],
        organisations: List[str],
        window_days: int,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        \"\"\"
        Fallback to direct Neo4j queries (legacy path).
        
        Used when Oracle service is unavailable or disabled.
        \"\"\"
        # Minimum relevance score based on agent tolerance
        min_relevance = 0.5 - (agent.discovery_tolerance * 0.3)
        
        logger.info(
            "Using Neo4j fallback for agent %s: topics=%s, orgs=%s, window=%d days",
            agent.name,
            topics,
            organisations,
            window_days,
        )
        
        # Fetch events
        events = self._context.fetch_recent_events(
            topics,
            organisations,
            limit=30,
            window_days=window_days,
            min_relevance_score=min_relevance,
        )
        
        # Fetch documents
        documents = self._context.fetch_recent_documents(
            organisations,
            limit=30,
            window_days=window_days,
            min_relevance_score=min_relevance,
        )
        
        logger.info(
            "Neo4j fallback results: %d events, %d documents",
            len(events),
            len(documents),
        )
        
        return events, documents

    def _aggregate_user_reactions(self, recent_posts: List[Dict[str, Any]]) -> Optional[Dict[str, int]]:
        """Aggregate like/dislike counts from recent posts."""
        try:
            from .. import db

            post_ids = [p.get("id") for p in recent_posts]

            if not post_ids:
                return None

            # Create placeholders for IN clause
            placeholders = ",".join(["%s"] * len(post_ids))
            query = f"""
                SELECT reaction_type
                FROM user_post_reaction
                WHERE post_id IN ({placeholders})
            """
            
            rows = db.fetch_all(query, tuple(post_ids))

            reaction_counts = {"like": 0, "dislike": 0}
            for row in rows:
                reaction = row.get("reaction_type")
                if reaction in reaction_counts:
                    reaction_counts[reaction] += 1

            return reaction_counts if sum(reaction_counts.values()) > 0 else None
        except Exception as e:
            logger.warning("Failed to aggregate user reactions: %s", e)
            return None

    def _coerce_sources(
        self,
        raw_sources: Optional[List[Dict[str, Any]]],
        events: List[Dict[str, Any]],
        documents: List[Dict[str, Any]],
    ) -> List[PostSource]:
        \"\"\"
        Extract sources from LLM response or context.
        
        Now uses content 'id' as source_identifier for proper deduplication tracking.
        \"\"\"
        sources: List[PostSource] = []
        if raw_sources:
            for raw in raw_sources:
                try:
                    sources.append(PostSource(**raw))
                except ValidationError:
                    logger.warning("Discarded invalid LLM source payload: %s", raw)
        if sources:
            return sources

        # Extract from events - use 'id' as identifier for tracking
        for event in events:
            content_id = event.get("id")
            url = event.get("url")
            title = event.get("title")
            if content_id or url:
                sources.append(
                    PostSource(
                        source_kind="event",
                        source_identifier=content_id or url,  # Prefer ID for tracking
                        url=url,
                        title=title,
                    )
                )
            if len(sources) >= 5:  # Increase limit to capture more sources
                break
        if sources:
            return sources

        # Extract from documents - use 'id' as identifier for tracking
        for doc in documents:
            content_id = doc.get("id")
            url = doc.get("url")
            title = doc.get("title")
            if content_id or url:
                sources.append(
                    PostSource(
                        source_kind="document",
                        source_identifier=content_id or url,  # Prefer ID for tracking
                        url=url,
                        title=title,
                    )
                )
            if len(sources) >= 5:  # Increase limit to capture more sources
                break
        return sources
