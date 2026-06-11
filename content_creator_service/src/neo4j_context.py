"""Helpers for retrieving contextual knowledge from Neo4j."""
from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any, Dict, List

from neo4j_client import Neo4jClient

from .settings import get_settings

logger = logging.getLogger(__name__)


class Neo4jContextGateway:
    """Read-only facade used by CreatorAgents to assemble context."""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
        )
        self._settings = settings

    def fetch_recent_events(
        self,
        topics: List[str],
        organisations: List[str],
        limit: int = 15,
        window_days: Optional[int] = None,
        min_relevance_score: Optional[float] = None,
        excluded_datasources: Optional[List[str]] = None,
        preferred_datasources: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Return recent events/resources filtered by topics or organisations.
        
        Implements relevance scoring to prioritize articles where query topics are central:
        - Topic specificity: fewer total topics = more focused content (40% weight)
        - Query topic match rate: proportion of query topics matched (30% weight)
        - Recency: newer content scores higher (20% weight)
        - Title match: query topics in title indicate primary focus (10% weight)
        
        Filters out:
        - Resources older than window_days (default from settings)
        - Resources with relevance score below min_relevance_score (default from settings)
        - Resources with excessive topic relationships (>max_topics_per_article from settings)
        """
        topics = [topic for topic in topics if topic]
        organisations = [org for org in organisations if org]
        if not topics and not organisations:
            return []
        
        # Use settings defaults if not provided
        if window_days is None:
            window_days = self._settings.temporal_window_days_default
        if min_relevance_score is None:
            min_relevance_score = self._settings.min_relevance_score_default
        
        max_topics = self._settings.max_topics_per_article
        
        logger.info(
            "Fetching events for topics=%s organisations=%s (limit=%s, window=%dd, min_score=%.2f, max_topics=%d)",
            topics,
            organisations,
            limit,
            window_days,
            min_relevance_score,
            max_topics,
        )
        query = """
        MATCH (r:Resource)
        WHERE (
            ($has_topics AND EXISTS {
                MATCH (r)-[:RELATES_TO]->(topic:Topic)
                WHERE toLower(topic.name) IN [x IN $topics | toLower(x)]
            }) OR
            ($has_orgs AND EXISTS {
                MATCH (r)-[:MENTIONS]->(org:Organization)
                WHERE toLower(org.name) IN [x IN $organisations | toLower(x)]
            })
        )
        // Temporal filter: use publish_date when valid, fall back to created_at.
        // Regex-guard datetime() so a malformed publish_date (e.g. Python
        // str(datetime) with a space separator) does not blow up the whole query.
        WITH r,
            CASE
              WHEN r.publish_date IS NOT NULL AND NOT r.publish_date IN ['', 'unknown']
                   AND toString(r.publish_date) =~ '^\\d{4}-\\d{2}-\\d{2}[T ]\\d{2}:\\d{2}:\\d{2}.*'
                THEN datetime(replace(toString(r.publish_date), ' ', 'T'))
              WHEN r.created_at IS NOT NULL THEN r.created_at
              ELSE datetime('1970-01-01')
            END AS effective_date
        WHERE effective_date >= datetime() - duration({days: $window_days})
          AND effective_date <= datetime('2100-12-31T23:59:59Z')
          AND effective_date >= datetime('2000-01-01')
        // Exclude datasources the user has ignored
        AND ($excluded_datasources IS NULL OR size($excluded_datasources) = 0
             OR NOT r.datasource_id IN $excluded_datasources)

        // Collect all topics and orgs for scoring
        OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
        OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)

        WITH r, effective_date,
             collect(DISTINCT t.name) AS all_topics,
             collect(DISTINCT o.name) AS all_organisations

        // Filter out generic content aggregators (configurable max_topics)
        WHERE size(all_topics) <= $max_topics

        // Calculate relevance score components
        WITH r, effective_date, all_topics, all_organisations,
             // Topic specificity score: fewer topics = more focused (inverse normalized)
             CASE 
                WHEN size(all_topics) = 0 THEN 0.0
                WHEN size(all_topics) <= 3 THEN 1.0
                WHEN size(all_topics) <= 6 THEN 0.7
                WHEN size(all_topics) <= 10 THEN 0.4
                ELSE 0.2
             END AS specificity_score,
             
             // Query match rate: how many query topics are matched
             CASE 
                WHEN $has_topics THEN
                    toFloat(size([topic IN all_topics WHERE toLower(topic) IN [x IN $topics | toLower(x)]])) / 
                    toFloat(size($topics))
                ELSE 1.0
             END AS match_rate_score,
             
             // Recency score: exponential decay (14 days half-life — was 30 days).
             // Shorter half-life ensures last-week's WBA workgroup docs outrank older
             // evergreen case studies (e.g. Hamina Wireless) that have high specificity.
             // Reuse the validated effective_date so a malformed publish_date
             // can't crash duration.between() here either.
             exp(-duration.between(effective_date, datetime()).days / 14.0) AS recency_score,

             // Title match bonus: query topics in title indicate primary focus
             CASE
                WHEN $has_topics THEN
                    toFloat(size([topic IN $topics WHERE toLower(r.title) CONTAINS toLower(topic)])) /
                    toFloat(size($topics))
                ELSE 0.0
             END AS title_match_score

        // Weighted relevance score — recency raised from 0.2 → 0.35 so fresh content
        // beats old high-specificity documents in the fallback Neo4j path.
        WITH r, effective_date, all_topics, all_organisations,
             (specificity_score * 0.3 +
              match_rate_score * 0.25 +
              recency_score * 0.35 +
              title_match_score * 0.1) AS relevance_score
        
        // Filter by minimum relevance threshold
        WHERE relevance_score >= $min_relevance_score
        
        RETURN r.title AS title,
               r.summary AS summary,
               r.publish_date AS start_date,
               r.publish_date AS end_date,
               r.url AS url,
               r.datasource_id AS datasource_id,
               COALESCE(r.importance, 'normal') AS importance,
               COALESCE(r.last_updated, r.publish_date) AS last_updated,
               all_topics AS topics,
               all_organisations AS organisations,
               relevance_score
        
        // Sort by relevance score (primary) and recency (secondary)
        ORDER BY relevance_score DESC, 
                 COALESCE(r.last_updated, r.publish_date, datetime()) DESC
        LIMIT $limit
        """
        params = {
            "topics": topics,
            "organisations": organisations,
            "has_topics": bool(topics),
            "has_orgs": bool(organisations),
            "limit": limit,
            "window_days": window_days,
            "min_relevance_score": min_relevance_score,
            "max_topics": max_topics,
            "excluded_datasources": excluded_datasources or [],
        }
        results = self._client.execute_query(query, params)
        
        # Log results for debugging
        logger.info("Neo4j events query returned %d records", len(results))
        if results:
            relevance_scores = [r.get('relevance_score', 0) for r in results if r.get('relevance_score')]
            if relevance_scores:
                logger.info("Relevance scores: min=%.3f, max=%.3f, avg=%.3f", 
                           min(relevance_scores), max(relevance_scores), 
                           sum(relevance_scores) / len(relevance_scores))
            # Log first few results
            for i, r in enumerate(results[:3]):
                logger.debug("  Result %d: title='%s', score=%.3f, topics=%d", 
                            i+1, (r.get('title') or 'No title')[:50],
                            r.get('relevance_score', 0), len(r.get('topics', [])))
        else:
            logger.warning("No events found matching filters: topics=%s, orgs=%s, window=%dd",
                          topics, organisations, window_days)
        
        # Log relevance scores for monitoring
        if results:
            scores = [r.get("relevance_score", 0) for r in results]
            logger.debug(
                "Fetched %d events with relevance scores: min=%.2f, max=%.2f, avg=%.2f",
                len(results),
                min(scores),
                max(scores),
                sum(scores) / len(scores),
            )
        
        return results

    def fetch_recent_documents(
        self, 
        organisations: List[str], 
        limit: int = 20,
        window_days: Optional[int] = None,
        min_relevance_score: Optional[float] = None,
        excluded_datasources: Optional[List[str]] = None,
        preferred_datasources: Optional[List[str]] = None,
        topics: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Fetch recent documents mentioning specific organisations or topics.
        
        Accepts topics as a fallback when organisations list is empty.
        Applies similar relevance scoring as fetch_recent_events:
        - Organization specificity: fewer orgs = more focused (50% weight)
        - Recency: newer content scores higher (30% weight)
        - Title match: org names in title indicate primary focus (20% weight)
        """
        topics = [t for t in (topics or []) if t]
        organisations = [o for o in organisations if o]
        if not organisations and not topics:
            return []
        
        # Use settings defaults if not provided
        if window_days is None:
            window_days = self._settings.temporal_window_days_default
        if min_relevance_score is None:
            min_relevance_score = self._settings.min_relevance_score_default
        
        # For documents, use the max topics setting (for logging purposes)
        max_topics = self._settings.max_topics_per_article
        max_orgs = max_topics // 2
        
        logger.info(
            "Fetching documents for organisations=%s topics=%s (limit=%s, window=%dd, min_score=%.2f, max_topics=%d)",
            organisations,
            topics,
            limit,
            window_days,
            min_relevance_score,
            max_topics,
        )
        
        query = """
        MATCH (r:Resource)
        WHERE (
            ($has_orgs AND EXISTS {
                MATCH (r)-[:MENTIONS]->(o:Organization)
                WHERE toLower(o.name) IN [x IN $orgs | toLower(x)]
            }) OR
            ($has_topics AND EXISTS {
                MATCH (r)-[:RELATES_TO]->(t:Topic)
                WHERE toLower(t.name) IN [x IN $topics | toLower(x)]
            })
        )
        // Temporal filter: use publish_date when valid, fall back to created_at.
        // Regex-guard datetime() so a malformed publish_date (e.g. Python
        // str(datetime) with a space separator) does not blow up the whole query.
        WITH r,
            CASE
              WHEN r.publish_date IS NOT NULL AND NOT r.publish_date IN ['', 'unknown']
                   AND toString(r.publish_date) =~ '^\\d{4}-\\d{2}-\\d{2}[T ]\\d{2}:\\d{2}:\\d{2}.*'
                THEN datetime(replace(toString(r.publish_date), ' ', 'T'))
              WHEN r.created_at IS NOT NULL THEN r.created_at
              ELSE datetime('1970-01-01')
            END AS effective_date
        WHERE effective_date >= datetime() - duration({days: $window_days})
          AND effective_date <= datetime('2100-12-31T23:59:59Z')
          AND effective_date >= datetime('2000-01-01')
        // Exclude datasources the user has ignored
        AND ($excluded_datasources IS NULL OR size($excluded_datasources) = 0
             OR NOT r.datasource_id IN $excluded_datasources)

        // Collect orgs and topics for scoring
        OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
        WITH r, effective_date, collect(DISTINCT o.name) AS all_organisations
        
        // Filter out generic aggregators (configurable max_orgs) only when org-scoped
        WHERE $has_orgs = false OR size(all_organisations) <= $max_orgs
        
        // Calculate relevance score
        WITH r, effective_date, all_organisations,
             // Organization specificity: fewer orgs = more focused
             CASE
                WHEN size(all_organisations) = 0 THEN 0.5
                WHEN size(all_organisations) <= 2 THEN 1.0
                WHEN size(all_organisations) <= 4 THEN 0.7
                WHEN size(all_organisations) <= 6 THEN 0.4
                ELSE 0.2
             END AS specificity_score,
             
             // Recency score: 14-day half-life (was 30 days) so last-week's workgroup
             // updates rank above month-old case studies in the document fallback path.
             exp(-duration.between(effective_date, datetime()).days / 14.0) AS recency_score,

             // Title match bonus
             CASE
               WHEN $has_orgs AND size($orgs) > 0
                 THEN toFloat(size([org IN $orgs WHERE toLower(r.title) CONTAINS toLower(org)])) /
                      toFloat(size($orgs))
               WHEN $has_topics AND size($topics) > 0
                 THEN toFloat(size([t IN $topics WHERE toLower(r.title) CONTAINS toLower(t)])) /
                      toFloat(size($topics))
               ELSE 0.0
             END AS title_match_score

        // Recency raised from 0.3 → 0.45; specificity cut from 0.5 → 0.35 so fresh
        // workgroup docs beat older evergreen content in document queries.
        WITH r, effective_date, all_organisations,
             (specificity_score * 0.35 +
              recency_score * 0.45 +
              title_match_score * 0.2) AS relevance_score
        
        WHERE relevance_score >= $min_relevance_score
        
        RETURN r.title AS title,
               r.summary AS summary,
               r.url AS url,
               coalesce(r.publish_date, toString(effective_date)) AS publish_date,
               r.datasource_id AS datasource_id,
               all_organisations AS organisations,
               relevance_score
        
        ORDER BY relevance_score DESC, effective_date DESC
        LIMIT $limit
        """
        
        params = {
            "orgs": organisations,
            "topics": topics,
            "has_orgs": bool(organisations),
            "has_topics": bool(topics),
            "limit": limit,
            "window_days": window_days,
            "min_relevance_score": min_relevance_score,
            "max_orgs": max_orgs,
            "excluded_datasources": excluded_datasources or [],
        }
        
        results = self._client.execute_query(query, params)
        
        # Log results for debugging
        logger.info("Neo4j documents query returned %d records", len(results))
        if results:
            relevance_scores = [r.get('relevance_score', 0) for r in results if r.get('relevance_score')]
            if relevance_scores:
                logger.info("Document relevance scores: min=%.3f, max=%.3f, avg=%.3f", 
                           min(relevance_scores), max(relevance_scores), 
                           sum(relevance_scores) / len(relevance_scores))
        else:
            logger.warning("No documents found matching filters: orgs=%s, topics=%s, window=%dd",
                          organisations, topics, window_days)
        
        # Log relevance scores
        if results:
            scores = [r.get("relevance_score", 0) for r in results]
            logger.debug(
                "Fetched %d documents with relevance scores: min=%.2f, max=%.2f, avg=%.2f",
                len(results),
                min(scores),
                max(scores),
                sum(scores) / len(scores),
            )
        
        return results

    def fetch_recent_and_upcoming(
        self,
        topics: List[str],
        organisations: List[str],
        window_days: int = 30,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Fetch resources within a time window (past and future).
        Useful for agents with regular cadences to find both recent context and upcoming events.
        """
        topics = [topic for topic in topics if topic]
        organisations = [org for org in organisations if org]
        if not topics and not organisations:
            return []

        logger.debug(
            "Fetching events within %d-day window for topics=%s organisations=%s",
            window_days,
            topics,
            organisations,
        )
        # Regex-guard datetime() so a malformed publish_date (e.g. Python
        # str(datetime) with a space separator) doesn't blow up the query and
        # take out every CreatorAgent run.
        query = """
        MATCH (r:Resource)
        WHERE (
            ($has_topics AND EXISTS {
                MATCH (r)-[:RELATES_TO]->(topic:Topic)
                WHERE toLower(topic.name) IN [x IN $topics | toLower(x)]
            }) OR
            ($has_orgs AND EXISTS {
                MATCH (r)-[:MENTIONS]->(org:Organization)
                WHERE toLower(org.name) IN [x IN $organisations | toLower(x)]
            })
        )
        AND r.publish_date IS NOT NULL
        AND NOT r.publish_date IN ['', 'unknown']
        AND toString(r.publish_date) =~ '^\\d{4}-\\d{2}-\\d{2}[T ]\\d{2}:\\d{2}:\\d{2}.*'
        WITH r, datetime(replace(toString(r.publish_date), ' ', 'T')) AS effective_date
        WHERE effective_date >= datetime() - duration({days: $window_days})
          AND effective_date <= datetime('2100-12-31T23:59:59Z')
          AND effective_date >= datetime('2000-01-01')
        OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
        OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
        WITH r, effective_date, collect(DISTINCT t.name) AS topics, collect(DISTINCT o.name) AS organisations
        RETURN r.title AS title,
               r.summary AS summary,
               r.publish_date AS start_date,
               r.publish_date AS end_date,
               r.url AS url,
               COALESCE(r.importance, 'normal') AS importance,
               COALESCE(r.last_updated, r.publish_date) AS last_updated,
               topics,
               organisations
        ORDER BY effective_date DESC
        LIMIT $limit
        """
        params = {
            "topics": topics,
            "organisations": organisations,
            "window_days": window_days,
            "has_topics": bool(topics),
            "has_orgs": bool(organisations),
            "limit": limit,
        }
        return self._client.execute_query(query, params)

    def fetch_adjacent_topics(
        self,
        topics: List[str],
        organisations: List[str],
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Discover adjacent/related topics when primary topics have no matches.
        Useful for exploratory content generation.
        """
        if not topics:
            return []

        logger.debug(
            "Fetching adjacent topics related to: %s (orgs: %s)",
            topics,
            organisations,
        )
        query = """
        MATCH (primary_topic:Topic)
        WHERE toLower(primary_topic.name) IN [x IN $topics | toLower(x)]
        MATCH (primary_topic)<-[:RELATES_TO]-(r:Resource)-[:RELATES_TO]->(adjacent_topic:Topic)
        WHERE NOT toLower(adjacent_topic.name) IN [x IN $topics | toLower(x)]
        OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
        WHERE o IS NULL OR toLower(o.name) IN [x IN $organisations | toLower(x)]
        WITH r, adjacent_topic, collect(DISTINCT o.name) AS organisations
        RETURN r.title AS title,
               r.summary AS summary,
               r.publish_date AS start_date,
               r.publish_date AS end_date,
               r.url AS url,
               COALESCE(r.importance, 'normal') AS importance,
               COALESCE(r.last_updated, r.publish_date) AS last_updated,
               [adjacent_topic.name] AS topics,
               organisations
        ORDER BY COALESCE(r.last_updated, r.publish_date, datetime()) DESC
        LIMIT $limit
        """
        params = {
            "topics": topics,
            "organisations": organisations,
            "limit": limit,
        }
        return self._client.execute_query(query, params)


@lru_cache(maxsize=1)
def get_context_gateway() -> Neo4jContextGateway:
    return Neo4jContextGateway()
