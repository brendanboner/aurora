"""Content generation orchestration for CreatorAgents."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from pydantic import ValidationError

from ..llm_client import get_llm_client
from ..models.agent import CreatorAgent
from ..models.post import PostSource
from ..neo4j_context import get_context_gateway
from ..settings import get_settings
from .oracle_client import OracleAgentClient
from .post_service import PostService
from .prompt_builder import PromptBuilder

logger = logging.getLogger(__name__)


class GenerationService:
    def __init__(self) -> None:
        self._context = get_context_gateway()
        self._settings = get_settings()
        self._prompt_builder = PromptBuilder()
        self._oracle_client = OracleAgentClient()
        self._post_service = PostService()
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
                       agent.name, topic_scope, organisation_scope, cadence_days)
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
        """
        Transform Oracle content items into events and documents format.
        
        Oracle returns unified content with:
        - id, title, summary, publish_date, url, category
        - topics, organizations, events, people
        - relevance_score
        
        We split into events (has events array) and documents (publications/decisions).
        """
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
        """
        Fallback to direct Neo4j queries (legacy path).
        
        Used when Oracle service is unavailable or disabled.
        """
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
        """
        Extract sources from LLM response or context.
        
        Now uses content 'id' as source_identifier for proper deduplication tracking.
        """
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

    def _get_user_agent_discovery_window_days(self, cadence: str) -> int:
        cadence_windows = {
            "daily": 7,
            "daily-digest": 7,
            "weekly": 21,
            "weekly-digest": 21,
            "important-only": 45,
            "monthly": 90,
        }
        return cadence_windows.get(cadence, 14)

    def _normalize_context_records(self, records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        normalized: List[Dict[str, Any]] = []
        for record in records:
            publish_date = (
                record.get("publish_date")
                or record.get("start_date")
                or record.get("end_date")
                or record.get("last_updated")
            )
            normalized.append(
                {
                    "id": record.get("id") or record.get("url") or record.get("title"),
                    "title": record.get("title"),
                    "summary": record.get("summary", ""),
                    "url": record.get("url"),
                    "publish_date": publish_date,
                    "topics": record.get("topics", []),
                    "organizations": record.get("organizations") or record.get("organisations", []),
                    "relevance_score": record.get("relevance_score", 0.0),
                    "category": record.get("category"),
                }
            )
        return normalized

    def _parse_context_datetime(self, value: Any) -> Optional[datetime]:
        if value is None:
            return None
        if isinstance(value, datetime):
            normalized = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
            return normalized.astimezone(timezone.utc)
        if isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                normalized = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
                return normalized.astimezone(timezone.utc)
            except ValueError:
                return None
        return None

    def _summarize_context_freshness(
        self,
        events: List[Dict[str, Any]],
        documents: List[Dict[str, Any]],
        *,
        freshness_window_days: int,
        discovery_source: str,
        adjacent_topics_used: bool = False,
        fallback_reason: Optional[str] = None,
    ) -> Dict[str, Any]:
        timestamps = [
            self._parse_context_datetime(item.get("publish_date"))
            for item in [*events, *documents]
        ]
        timestamps = [timestamp for timestamp in timestamps if timestamp is not None]
        latest_timestamp = max(timestamps) if timestamps else None
        latest_age_days = None
        latest_publish_date = None
        stale_context = False
        if latest_timestamp is not None:
            latest_timestamp = (
                latest_timestamp.astimezone(timezone.utc)
                if latest_timestamp.tzinfo
                else latest_timestamp.replace(tzinfo=timezone.utc)
            )
            latest_age_days = max((datetime.now(timezone.utc) - latest_timestamp).days, 0)
            latest_publish_date = latest_timestamp.date().isoformat()
            stale_context = latest_age_days > freshness_window_days

        return {
            "discovery_source": discovery_source,
            "freshness_window_days": freshness_window_days,
            "latest_age_days": latest_age_days,
            "latest_publish_date": latest_publish_date,
            "stale_context": stale_context,
            "adjacent_topics_used": adjacent_topics_used,
            "fallback_reason": fallback_reason,
        }

    def _fetch_user_agent_context_from_neo4j(
        self,
        *,
        topics: List[str],
        organizations: List[str],
        base_window_days: int,
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
        fallback_reason = "Oracle discovery unavailable or returned no relevant content."
        candidate_windows = []
        for window in (
            max(base_window_days, 7),
            max(base_window_days * 4, 30),
            max(self._settings.temporal_window_days_default, 180),
        ):
            if window not in candidate_windows:
                candidate_windows.append(window)

        for index, window_days in enumerate(candidate_windows):
            min_relevance = max(0.08, self._settings.min_relevance_score_default - (index * 0.05))
            events = self._normalize_context_records(
                self._context.fetch_recent_events(
                    topics,
                    organizations,
                    limit=20,
                    window_days=window_days,
                    min_relevance_score=min_relevance,
                )
            )
            documents = self._normalize_context_records(
                self._context.fetch_recent_documents(
                    organizations,
                    limit=20,
                    window_days=window_days,
                    min_relevance_score=min_relevance,
                )
            )

            adjacent_topics_used = False
            if not events and topics:
                adjacent_topics_used = True
                events = self._normalize_context_records(
                    self._context.fetch_adjacent_topics(
                        topics=topics,
                        organisations=organizations,
                        limit=10,
                    )
                )

            if events or documents:
                meta = self._summarize_context_freshness(
                    events,
                    documents,
                    freshness_window_days=base_window_days,
                    discovery_source=f"neo4j-fallback-{window_days}d",
                    adjacent_topics_used=adjacent_topics_used,
                    fallback_reason=fallback_reason,
                )
                return events, documents, meta

        return [], [], self._summarize_context_freshness(
            [],
            [],
            freshness_window_days=base_window_days,
            discovery_source="neo4j-fallback-empty",
            fallback_reason=fallback_reason,
        )

    def _discover_user_agent_context(
        self,
        *,
        agent_id: int,
        agent_name: str,
        topics: List[str],
        organizations: List[str],
        cadence_days: int,
        used_content_ids: List[str],
    ) -> tuple[List[Dict[str, Any]], List[Dict[str, Any]], Dict[str, Any]]:
        if self._use_oracle:
            try:
                logger.info(
                    "Oracle discovery for user agent %s: topics=%s, orgs=%s, cadence=%d days",
                    agent_name,
                    topics,
                    organizations,
                    cadence_days,
                )
                oracle_result = asyncio.run(
                    self._oracle_client.discover_content(
                        agent_id=agent_id,
                        agent_name=agent_name,
                        topics=topics,
                        organizations=organizations,
                        cadence_days=cadence_days,
                        last_content_ids=used_content_ids,
                        limit=20,
                    )
                )
                events, documents = self._transform_oracle_content(oracle_result.get("content_items", []))
                if events or documents:
                    return events, documents, self._summarize_context_freshness(
                        events,
                        documents,
                        freshness_window_days=cadence_days,
                        discovery_source=f"oracle:{oracle_result.get('route_used', 'discover')}",
                    )
                logger.info(
                    "Oracle returned no direct matches for personal agent %s; trying knowledge graph fallback",
                    agent_name,
                )
            except Exception as exc:
                logger.warning(
                    "Oracle discovery failed for user agent %s: %s; trying knowledge graph fallback",
                    agent_name,
                    exc,
                )

        return self._fetch_user_agent_context_from_neo4j(
            topics=topics,
            organizations=organizations,
            base_window_days=cadence_days,
        )
    
    def generate_for_user_agent(self, user_agent_dict: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """
        Generate content for a personal user agent.
        Similar to generate_post_payload but handles user-specific agents with feedback history.
        """
        agent_id = user_agent_dict['id']
        user_id = user_agent_dict['user_id']
        agent_name = user_agent_dict['name']
        persona = user_agent_dict.get('persona')
        topics = user_agent_dict.get('expertise_topics', [])
        organizations = user_agent_dict.get('expertise_organisations', [])
        tone_style = user_agent_dict.get('tone_style', 'analytical')
        feedback_history = user_agent_dict.get('feedback_history', [])
        cadence = user_agent_dict.get('cadence', 'daily')
        
        # Determine time window from cadence
        cadence_days = self._get_user_agent_discovery_window_days(cadence)
        
        # Fetch previously used content IDs
        used_content_ids = self._fetch_used_content_ids_for_user_agent(agent_id, lookback_days=cadence_days * 2)
        
        events, documents, context_meta = self._discover_user_agent_context(
            agent_id=agent_id,
            agent_name=agent_name,
            topics=topics,
            organizations=organizations,
            cadence_days=cadence_days,
            used_content_ids=used_content_ids,
        )
        
        if not events and not documents:
            logger.info("No relevant context found for user agent %s", agent_name)
            return None
        
        # Apply diversity filtering
        events = self._apply_diversity_filter(events, max_items=6)
        documents = self._apply_diversity_filter(documents, max_items=6)
        
        if not events and not documents:
            logger.info("No diverse context remained for user agent %s after filtering", agent_name)
            return None

        recent_posts = self._fetch_recent_posts_for_user_agent(agent_id, user_id, limit=4)
        
        # Build prompt with user agent context and feedback history
        system_prompt = self._build_user_agent_system_prompt(
            agent_name,
            persona,
            tone_style,
            feedback_history,
            recent_posts=recent_posts,
            context_meta=context_meta,
        )
        user_prompt = self._build_user_agent_user_prompt(
            events,
            documents,
            topics,
            organizations,
            recent_posts=recent_posts,
            context_meta=context_meta,
        )
        
        # Generate content
        logger.info("Generating content for user agent %s", agent_name)
        llm_client = get_llm_client()
        llm_response = llm_client.generate(system_prompt, user_prompt, temperature_override=0.7)
        
        if not llm_response:
            logger.warning("LLM generation failed for user agent %s", agent_name)
            return None

        if self._is_duplicate_user_agent_update(llm_response, recent_posts):
            logger.info(
                "Skipping duplicate-style update for user agent %s because it overlaps a recent post",
                agent_name,
            )
            return None
        
        # Create post with user_id and agent_type
        sources = self._coerce_sources(llm_response.get("sources"), events, documents)
        
        post_id = self._post_service.create_post(
            agent_id=agent_id,
            user_id=user_id,
            agent_type='personal',
            title=llm_response.get("title", "Untitled update"),
            summary=llm_response.get("summary"),
            body=llm_response.get("body"),
            tags=llm_response.get("tags", topics),
            visibility='private',
            importance=llm_response.get("importance", 'normal'),
            content_length=llm_response.get("content_length", 'medium'),
            sources=sources,
        )

        from .. import db

        # Update agent's last_generated_at
        db.execute(
            """
            UPDATE user_agent
            SET last_run_at = NOW(),
                last_generated_at = NOW()
            WHERE id = %s
            """,
            (agent_id,)
        )
        
        logger.info("Generated post %s for user agent %s", post_id, agent_name)
        
        return {
            "post_id": post_id,
            "post": {
                "title": llm_response.get("title"),
                "summary": llm_response.get("summary"),
                "body": llm_response.get("body")
            }
        }
    
    def _fetch_used_content_ids_for_user_agent(self, agent_id: int, lookback_days: int = 30) -> List[str]:
        """Fetch content IDs already used by this user agent."""
        from .. import db
        
        rows = db.fetch_all(
            """
            SELECT DISTINCT ps.source_identifier
            FROM post p
            JOIN post_source ps ON p.id = ps.post_id
            WHERE p.agent_type = 'personal'
              AND p.agent_id = %s
              AND p.created_at > NOW() - (%s * INTERVAL '1 day')
              AND ps.source_identifier IS NOT NULL
            """,
            (agent_id, lookback_days),
        )
        
        return [row["source_identifier"] for row in rows if row.get("source_identifier")]

    def _fetch_recent_posts_for_user_agent(
        self,
        agent_id: int,
        user_id: str,
        limit: int = 4,
    ) -> List[Dict[str, Any]]:
        """Fetch recent personal-agent posts to avoid repeating the same update."""
        from .. import db

        rows = db.fetch_all(
            """
            SELECT id, title, body, created_at
            FROM post
            WHERE agent_type = 'personal'
              AND agent_id = %s
              AND user_id = %s
            ORDER BY created_at DESC
            LIMIT %s
            """,
            (agent_id, user_id, limit),
        )

        return [
            {
                "id": row["id"],
                "title": row["title"],
                "body": (row["body"] or "")[:240],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def _text_similarity(self, left: str, right: str) -> float:
        if not left or not right:
            return 0.0

        left_tokens = set(left.lower().split())
        right_tokens = set(right.lower().split())
        if not left_tokens or not right_tokens:
            return 0.0

        overlap = len(left_tokens & right_tokens)
        union = len(left_tokens | right_tokens)
        return overlap / union if union else 0.0

    def _is_duplicate_user_agent_update(
        self,
        llm_response: Dict[str, Any],
        recent_posts: List[Dict[str, Any]],
    ) -> bool:
        """Prevent near-duplicate personal updates when the same news would be repeated."""
        if not recent_posts:
            return False

        candidate_title = (llm_response.get("title") or "").strip()
        candidate_body = (llm_response.get("body") or "").strip()
        candidate_summary = (llm_response.get("summary") or "").strip()
        candidate_text = " ".join(part for part in [candidate_title, candidate_summary, candidate_body[:280]] if part)

        for recent_post in recent_posts:
            recent_title = (recent_post.get("title") or "").strip()
            recent_body = (recent_post.get("body") or "").strip()
            recent_text = " ".join(part for part in [recent_title, recent_body] if part)

            title_similarity = self._text_similarity(candidate_title, recent_title)
            body_similarity = self._text_similarity(candidate_text, recent_text)

            if title_similarity >= 0.75 or body_similarity >= 0.72:
                return True

        return False
    
    def _build_user_agent_system_prompt(
        self,
        agent_name: str,
        persona: Optional[str],
        tone_style: str,
        feedback_history: List[Dict],
        recent_posts: Optional[List[Dict[str, Any]]] = None,
        context_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build system prompt for user agent with feedback context."""
        base_prompt = f"""You are {agent_name}, a personal AI content curator.

Your role: {persona or 'Monitor relevant developments and provide concise, actionable updates.'}

Tone: {tone_style}

Output a JSON object with:
- title: Engaging headline (max 100 chars)
- summary: 2-3 sentence overview
- body: Detailed analysis in markdown (200-400 words)
- tags: Array of relevant topic tags
- sources: Array of objects with {{kind, id, url, confidence}}
- importance: 'low', 'normal', or 'high'
- content_length: 'short', 'medium', or 'long'

        Focus on insights relevant to your project scope."""

        if recent_posts:
            base_prompt += (
                "\n\nDeduplication guidance:\n"
                "- You have already published recent updates for this project.\n"
                "- Do not repeat the same headline, same lead example, or same core takeaway.\n"
                "- Only publish if you can provide a materially different development, implication, or state-of-play synthesis."
            )

        if context_meta:
            if context_meta.get("stale_context"):
                latest_publish_date = context_meta.get("latest_publish_date") or "the latest archived material available"
                latest_age_days = context_meta.get("latest_age_days")
                staleness = (
                    f"The newest relevant source is from {latest_publish_date}"
                    if latest_age_days is None
                    else f"The newest relevant source is from {latest_publish_date} ({latest_age_days} days ago)"
                )
                base_prompt += (
                    "\n\nImportant freshness guidance:\n"
                    f"- No highly relevant material was found inside the last {context_meta.get('freshness_window_days')} days.\n"
                    f"- Use the archived but still relevant signals below to produce a status update.\n"
                    f"- Explicitly say that there has not been meaningful new discussion in the recent window and anchor the reader with the latest known signal. {staleness}.\n"
                    "- Do not pretend content is fresh.\n"
                    "- Summarize the 2-4 most pertinent historical signals, explain why they still matter, and cite them."
                )
            else:
                base_prompt += (
                    "\n\nFreshness guidance:\n"
                    f"- Relevant material was found within the last {context_meta.get('freshness_window_days')} days.\n"
                    "- Prioritize the most important current developments and mention recency where helpful."
                )

            if context_meta.get("adjacent_topics_used"):
                base_prompt += (
                    "\n- Some context comes from adjacent topics because direct matches were sparse. "
                    "Be explicit when you are extrapolating from closely related discussions."
                )

        # Add learned preferences from feedback
        if feedback_history:
            recent_feedback = [f for f in feedback_history[-5:] if f.get('applied_changes')]
            if recent_feedback:
                feedback_context = "\n\nLearned preferences from feedback:\n"
                for entry in recent_feedback:
                    feedback_context += f"- {entry.get('applied_changes')}\n"
                base_prompt += feedback_context
        
        return base_prompt
    
    def _build_user_agent_user_prompt(
        self,
        events: List[Dict],
        documents: List[Dict],
        topics: List[str],
        organizations: List[str],
        recent_posts: Optional[List[Dict[str, Any]]] = None,
        context_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Build user prompt for user agent content generation."""
        prompt = f"""Generate a content update based on the following:\n\n"""
        
        if topics:
            prompt += f"**Focus Topics**: {', '.join(topics[:10])}\n\n"
        
        if organizations:
            prompt += f"**Relevant Organizations**: {', '.join(organizations[:5])}\n\n"

        if context_meta:
            freshness_window_days = context_meta.get("freshness_window_days")
            latest_publish_date = context_meta.get("latest_publish_date")
            latest_age_days = context_meta.get("latest_age_days")
            prompt += f"**Discovery Source**: {context_meta.get('discovery_source')}\n"
            if context_meta.get("fallback_reason"):
                prompt += f"**Fallback Note**: {context_meta.get('fallback_reason')}\n"
            if context_meta.get("stale_context"):
                prompt += (
                    f"**Freshness Summary**: No highly relevant material was found in the last {freshness_window_days} days. "
                    f"The latest relevant signal is from {latest_publish_date or 'an earlier period'}"
                )
                if latest_age_days is not None:
                    prompt += f" ({latest_age_days} days ago)"
                prompt += ". Build a helpful state-of-play update rather than pretending there is breaking news.\n\n"
            else:
                prompt += f"**Freshness Summary**: Relevant material exists within the last {freshness_window_days} days.\n\n"

        if recent_posts:
            prompt += "**Your Recent Updates (avoid repeating these same angles)**:\n"
            for index, recent_post in enumerate(recent_posts[:4], 1):
                created_at = recent_post.get("created_at") or "unknown date"
                prompt += (
                    f"{index}. [{created_at}] {recent_post.get('title', 'Untitled')} - "
                    f"{recent_post.get('body', '')[:160]}\n"
                )
            prompt += (
                "\nYour new update must advance the story with a new angle, a different implication, "
                "or a clearly stated state-of-play summary instead of repeating the same news.\n\n"
            )
        
        if events:
            prompt += f"**Recent Events** ({len(events)}):\n"
            for i, event in enumerate(events[:8], 1):
                publish_date = event.get("publish_date") or "unknown date"
                url = event.get("url") or "no URL"
                prompt += (
                    f"{i}. [{publish_date}] {event.get('title')} - {event.get('summary', '')[:180]}\n"
                    f"   URL: {url}\n"
                )
            prompt += "\n"
        
        if documents:
            prompt += f"**Publications & Resources** ({len(documents)}):\n"
            for i, doc in enumerate(documents[:8], 1):
                publish_date = doc.get("publish_date") or "unknown date"
                url = doc.get("url") or "no URL"
                prompt += (
                    f"{i}. [{publish_date}] {doc.get('title')} - {doc.get('summary', '')[:180]}\n"
                    f"   URL: {url}\n"
                )
            prompt += "\n"
        
        prompt += (
            "Synthesize this information into a valuable update for the project. "
            "If the newest relevant source is older than the freshness window, explicitly say there has been no recent discussion and explain what the latest known relevant signals were."
        )
        
        return prompt
