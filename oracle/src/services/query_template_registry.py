"""Query template registry for fast Cypher retrieval.

Maps route IDs to parameterized Cypher queries with schemas
and post-processing logic.

IMPORTANT: Date Handling
All temporal queries MUST use robust date fallback since publish_date is often NULL.

Use this pattern in Cypher expressions (WITH/RETURN):
    CASE WHEN r.publish_date IS NOT NULL AND NOT r.publish_date IN ['', 'unknown'] THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at) WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime() END as effective_date

This must be a single expression, not a block. Cypher does not support SQL-style CASE blocks.


This ensures Resources with NULL publish_date still appear in temporal queries
using their ingestion timestamp (created_at) or scrape timestamp (scraped_at).
"""

import logging
import re
from typing import Dict, List, Any, Optional, Callable
from datetime import datetime, date

from src.models.route_plan import RouteId, RoutePlan
from src.settings import settings

logger = logging.getLogger(__name__)


class QueryTemplate:
    """
    A Cypher query template with parameters and post-processing.
    """
    
    def __init__(
        self,
        route_id: RouteId,
        cypher: str,
        description: str,
        param_schema: Dict[str, str],
        post_process: Optional[Callable] = None
    ):
        """
        Initialize query template.
        
        Args:
            route_id: Route identifier
            cypher: Parameterized Cypher query
            description: Human-readable description
            param_schema: Parameter names and types
            post_process: Optional function to transform results
        """
        self.route_id = route_id
        self.cypher = cypher
        self.description = description
        self.param_schema = param_schema
        self.post_process = post_process or (lambda x: x)
    
    def build_params(self, plan: RoutePlan) -> Dict[str, Any]:
        """
        Build Cypher parameters from route plan.
        
        Args:
            plan: Route plan with filters and preferences
            
        Returns:
            Dictionary of Cypher parameters
        """
        params = {}
        
        # Date parameters - always provide them (as None if not set) for Cypher NULL checks
        params["start_date"] = plan.start_date.isoformat() if plan.start_date else None
        params["end_date"] = plan.end_date.isoformat() if plan.end_date else None
        params["relative_days"] = plan.relative_days if plan.relative_days else None
        
        # Entity parameters - always provide them (as empty list if not set) for Cypher
        params["workgroups"] = plan.workgroups if plan.workgroups else []
        params["topics"] = plan.topics if plan.topics else []
        params["organizations"] = plan.organizations if plan.organizations else []
        params["people"] = plan.people if plan.people else []
        params["category"] = plan.category if hasattr(plan, 'category') and plan.category else None
        params["exclude_meetings"] = plan.exclude_meetings if hasattr(plan, 'exclude_meetings') and plan.exclude_meetings is not None else None
        params["content_types"] = []  # Content type filter (e.g., ['decision', 'action'])
        # User source membership filters — populated by fast_engine from user preferences
        params["excluded_datasources"] = plan.excluded_datasources if plan.excluded_datasources else []
        params["preferred_datasources"] = plan.preferred_datasources if plan.preferred_datasources else []

        expanded_topics = list(params["topics"])
        for topic in params["topics"]:
            topic_lower = topic.lower()
            if topic_lower == "ieee 802.11" and "802.11" not in expanded_topics:
                expanded_topics.append("802.11")
            # Always include singular/plural variants for any router-supplied topic
            if topic_lower.endswith("s") and len(topic_lower) > 3 and not topic_lower.endswith("ss"):
                singular = topic[:-1]
                if singular not in expanded_topics:
                    expanded_topics.append(singular)
            elif not topic_lower.endswith("s"):
                plural = topic + "s"
                if plural not in expanded_topics:
                    expanded_topics.append(plural)
        params["topics"] = expanded_topics
        
        # For DOCUMENTS_BY_TOPIC, if no topics were extracted, try to extract from "what is X" query
        if hasattr(plan, 'route_id'):
            route_id_val = plan.route_id.value if hasattr(plan.route_id, 'value') else plan.route_id
            # For RECENT_PUBLICATIONS with no explicit date range, use 365-day lookback
            # so "latest press release" finds the actual most recent even if months old
            if route_id_val == "recent_publications" and params["relative_days"] is None:
                params["relative_days"] = 365
            # For RECENT_PUBLICATIONS, when a category filter is already set (e.g. "press release"),
            # the org filter over-restricts (requires MENTIONS/PUBLISHED_BY relationships that
            # many resources lack). Clear it so the category filter alone narrows the results.
            if route_id_val == "recent_publications" and params.get("category"):
                params["organizations"] = []
            if route_id_val == "documents_by_topic" and not params["topics"] and plan.raw_query:
                query_lower = plan.raw_query.lower().strip()
                extracted_term = None
                
                # Event-related queries: extract event name
                # "who spoke at [EVENT]" or "what was discussed at [EVENT]"
                event_patterns = [
                    r'who\s+(?:spoke|presented|talked)\s+at\s+(?:the\s+)?(.+?)(?:\s+\d{4})?$',
                    r'what\s+(?:was|is)\s+(?:discussed|covered|presented|talked about|shown|shared)\s+at\s+(?:the\s+)?(.+?)(?:\s+\d{4})?$',
                    r'what\s+(?:happened|occurred|took place)\s+at\s+(?:the\s+)?(.+?)(?:\s+\d{4})?$',
                    r'(?:speakers?|presenters?)\s+at\s+(?:the\s+)?(.+?)(?:\s+\d{4})?$',
                ]
                
                for pattern in event_patterns:
                    match = re.search(pattern, query_lower, re.IGNORECASE)
                    if match:
                        extracted_term = match.group(1).strip()
                        logger.info(f"Extracted event name from query: '{extracted_term}'")
                        break
                
                # Definition queries: "what is X"
                if not extracted_term:
                    if query_lower.startswith("what is "):
                        extracted_term = plan.raw_query[8:].strip().rstrip("?")
                    elif query_lower.startswith("what's "):
                        extracted_term = plan.raw_query[7:].strip().rstrip("?")
                    elif query_lower.startswith("what are "):
                        extracted_term = plan.raw_query[9:].strip().rstrip("?")
                    elif "tell me about " in query_lower:
                        extracted_term = plan.raw_query.split("tell me about ", 1)[1].strip().rstrip("?")
                    elif "explain " in query_lower:
                        extracted_term = plan.raw_query.split("explain ", 1)[1].strip().rstrip("?")
                
                if extracted_term:
                    # Remove leading articles
                    extracted_lower = extracted_term.lower()
                    if extracted_lower.startswith("a "):
                        extracted_term = extracted_term[2:].strip()
                    elif extracted_lower.startswith("an "):
                        extracted_term = extracted_term[3:].strip()
                    elif extracted_lower.startswith("the "):
                        extracted_term = extracted_term[4:].strip()
                    
                    # Truncate at the first conjunction / question word so that
                    # "sticky clients and why are they a problem in Wi-Fi" → "sticky clients".
                    conjunction_cut = re.search(
                        r'\s+(?:and|or|but|why|how|when|where|which|who)\b',
                        extracted_term, re.IGNORECASE
                    )
                    if conjunction_cut:
                        extracted_term = extracted_term[:conjunction_cut.start()].strip()
                    
                    # Strip trailing punctuation
                    extracted_term = re.sub(r'[.,;:!?]+$', '', extracted_term).strip()
                    
                    # Build topic list — include both the extracted form and a
                    # singular/plural variant so Neo4j topic-node matching is resilient
                    # to minor phrasing differences (e.g. "sticky clients" ↔ "sticky client").
                    topic_variants = [extracted_term]
                    term_lower = extracted_term.lower()
                    # Add singular if ends in 's' and singular is a meaningful word
                    if term_lower.endswith("s") and len(term_lower) > 3 and not term_lower.endswith("ss"):
                        singular = extracted_term[:-1]
                        if singular.lower() not in term_lower[:-1]:  # avoid duplication
                            topic_variants.append(singular)
                    # Add plural if doesn't end in 's'
                    elif not term_lower.endswith("s"):
                        plural = extracted_term + "s"
                        topic_variants.append(plural)
                    
                    params["topics"] = topic_variants
                    logger.info(f"Extracted topic variants from query: {topic_variants}")
            
            # For PERSON_AT_EVENT, extract event name and person from query
            if route_id_val == "person_at_event" and plan.raw_query:
                query_lower = plan.raw_query.lower().strip()
                
                # Patterns: "what did [PERSON] discuss at [EVENT]", "[PERSON]'s talk at [EVENT]"
                person_event_patterns = [
                    r'what (did|does)\s+(.+?)\s+(discuss|say|present|talk about|cover|announce)\s+at\s+(?:the\s+)?(.+?)(?:\s+\d{4})?$',
                    r'(.+?)(?:\'s|s)\s+(?:presentation|talk|keynote|session|discussion)\s+at\s+(?:the\s+)?(.+?)(?:\s+\d{4})?$',
                    r'did\s+(.+?)\s+(speak|present|talk)\s+at\s+(?:the\s+)?(.+?)(?:\s+\d{4})?$',
                ]
                
                for pattern in person_event_patterns:
                    match = re.search(pattern, query_lower, re.IGNORECASE)
                    if match:
                        groups = match.groups()
                        # Extract person (first capture that's not a verb)
                        person_name = None
                        event_name = None
                        
                        if len(groups) >= 4 and pattern.startswith(r'what'):
                            # Pattern 1: "what did [PERSON] [VERB] at [EVENT]"
                            person_name = groups[1].strip()
                            event_name = groups[3].strip()
                        elif "'s" in pattern or "s)" in pattern:
                            # Pattern 2: "[PERSON]'s [TYPE] at [EVENT]"
                            person_name = groups[0].strip()
                            event_name = groups[1].strip()
                        elif len(groups) >= 3:
                            # Pattern 3: "did [PERSON] [VERB] at [EVENT]"
                            person_name = groups[0].strip()
                            event_name = groups[2].strip()
                        
                        if person_name and event_name:
                            params["people"] = [person_name]
                            params["event_name"] = event_name
                            logger.info(f"Extracted person '{person_name}' and event '{event_name}' from query")
                            break
        
        # IETF route-specific parameter extraction
        _IETF_WG_ACRONYMS = [
            "quic", "bgp", "ospf", "tls", "http", "dns", "ipv6", "mpls",
            "bfd", "isis", "netconf", "yang", "pcep", "rsvp", "ldp", "pim",
            "vxlan", "evpn", "srv6",
        ]
        if hasattr(plan, 'route_id'):
            route_id_val = plan.route_id.value if hasattr(plan.route_id, 'value') else plan.route_id

            if route_id_val == "ietf_wg_updates" and plan.raw_query:
                query_lower = plan.raw_query.lower()
                matched_wgs = [acr for acr in _IETF_WG_ACRONYMS if re.search(r'\b' + acr + r'\b', query_lower)]
                params["wg_datasource_ids"] = [f"ietf_wg_{acr}" for acr in matched_wgs]
                from datetime import date, timedelta
                params["lookback_date"] = (date.today() - timedelta(days=90)).isoformat()

            elif route_id_val == "ietf_meeting_agenda" and plan.raw_query:
                query_lower = plan.raw_query.lower()
                m = re.search(r'ietf\s*(\d{2,3})', query_lower)
                if m:
                    meeting_num = m.group(1)
                    params["meeting_number"] = meeting_num
                    params["meeting_number_str"] = f"IETF {meeting_num}"
                else:
                    params["meeting_number"] = ""
                    params["meeting_number_str"] = ""
                # Also extract any WG acronyms for optional filtering
                matched_wgs = [acr for acr in _IETF_WG_ACRONYMS if re.search(r'\b' + acr + r'\b', query_lower)]
                params["wg_acronyms"] = matched_wgs

        # Content exclusion (for agent deduplication)
        # Extract from raw_query if it contains exclusion markers
        if plan.raw_query and "exclude_ids:" in plan.raw_query:
            try:
                # Parse exclusion IDs from query
                exclude_part = plan.raw_query.split("exclude_ids:")[1].split()[0]
                params["exclude_ids"] = exclude_part.strip("[]").split(",")
            except:
                params["exclude_ids"] = []
        else:
            params["exclude_ids"] = []
        
        # For GENERIC_SEARCH, extract key terms from query for full-text matching
        if hasattr(plan, 'route_id'):
            route_id_val = plan.route_id.value if hasattr(plan.route_id, 'value') else plan.route_id
            if route_id_val == "generic_search" and plan.raw_query:
                # Extract key terms from definition-style queries
                # "what is X" -> "X", "tell me about X" -> "X"
                query_lower = plan.raw_query.lower().strip()
                extracted_term = None
                
                if query_lower.startswith("what is "):
                    extracted_term = plan.raw_query[8:].strip().rstrip("?")
                elif query_lower.startswith("what's "):
                    extracted_term = plan.raw_query[7:].strip().rstrip("?")
                elif query_lower.startswith("what are "):
                    extracted_term = plan.raw_query[9:].strip().rstrip("?")
                elif "tell me about " in query_lower:
                    extracted_term = plan.raw_query.split("tell me about ", 1)[1].strip().rstrip("?")
                elif "explain " in query_lower:
                    extracted_term = plan.raw_query.split("explain ", 1)[1].strip().rstrip("?")
                else:
                    extracted_term = plan.raw_query.strip()
                
                # Remove leading articles (a, an, the) for better matching
                if extracted_term:
                    extracted_lower = extracted_term.lower()
                    if extracted_lower.startswith("a "):
                        extracted_term = extracted_term[2:].strip()
                    elif extracted_lower.startswith("an "):
                        extracted_term = extracted_term[3:].strip()
                    elif extracted_lower.startswith("the "):
                        extracted_term = extracted_term[4:].strip()
                    
                    # Strip trailing punctuation (but keep hyphens and underscores in middle)
                    # This handles "sticky client?" -> "sticky client"
                    extracted_term = re.sub(r'[.,;:!?]+$', '', extracted_term).strip()
                
                params["query_text"] = extracted_term if extracted_term else None
            else:
                params["query_text"] = None
        else:
            params["query_text"] = None
        
        # Limits - use smaller limit for definition queries to prioritize quality over quantity
        if hasattr(plan, 'route_id'):
            route_id_val = plan.route_id.value if hasattr(plan.route_id, 'value') else plan.route_id
            if route_id_val == "documents_by_topic":
                # For definition queries, 20 high-quality documents is better than 100 mediocre ones
                params["limit"] = 20
            else:
                params["limit"] = settings.fast_template_max_nodes
        else:
            params["limit"] = settings.fast_template_max_nodes
        
        return params
    
    def execute_post_process(self, results: List[Dict]) -> List[Dict]:
        """Execute post-processing function on results."""
        try:
            return self.post_process(results)
        except Exception as e:
            logger.error(f"Post-processing failed: {e}", exc_info=True)
            return results


class QueryTemplateRegistry:
    """
    Registry of Cypher query templates for fast retrieval.
    
    Maps route IDs to parameterized Cypher queries that return
    thin results optimized for fast execution.
    """
    
    def __init__(self):
        """Initialize the registry with predefined templates."""
        self.templates: Dict[RouteId, QueryTemplate] = {}
        self._register_templates()
        logger.info(f"Initialized QueryTemplateRegistry with {len(self.templates)} templates")
    
    def get_template(self, route_id: RouteId) -> Optional[QueryTemplate]:
        """Get template for a route ID."""
        return self.templates.get(route_id)
    
    def _register_templates(self):
        """Register all query templates."""
        
        # ========================================
        # UNIFIED TEMPLATES (New Architecture)
        # ========================================
        
        # RECENT_CONTENT - Unified temporal query with smart fallback
        # Replaces: WORKGROUP_RECENT_UPDATES, RECENT_PUBLICATIONS, DOCUMENTS_BY_DATE
        self.templates[RouteId.RECENT_CONTENT] = QueryTemplate(
            route_id=RouteId.RECENT_CONTENT,
            description="Get recent content with smart time window expansion",
            param_schema={
                "relative_days": "int (default: 14, expands to 56, 180 if empty)",
                "workgroups": "list[str] (datasource_ids or names)",
                "topics": "list[str] (topic names)",
                "organizations": "list[str] (org names or ids)",
                "content_types": "list[str] (categories: decision, action, etc)",
                "limit": "int"
            },
              cypher="""
              // Calculate expanding time windows
              WITH coalesce($relative_days, 14) as requested_days,
                  CASE
                      WHEN $limit <= 6 THEN 1
                      WHEN $limit <= 12 THEN 2
                      ELSE 3
                  END as items_per_group,
                  CASE
                      WHEN $limit <= 4 THEN $limit
                      WHEN $limit <= 10 THEN 5
                      ELSE 6
                  END as group_limit
              WITH requested_days, items_per_group, group_limit,
                  datetime() - duration({days: requested_days}) as primary_threshold,
                  datetime() - duration({days: 56}) as fallback_threshold,
                  datetime() - duration({days: 180}) as max_threshold

              // Get resources with robust date fallback: publish_date -> created_at -> scraped_at
              MATCH (r:Resource)
              WITH r, primary_threshold, fallback_threshold, max_threshold, items_per_group, group_limit, requested_days,
                   CASE WHEN r.publish_date IS NOT NULL AND NOT r.publish_date IN ['', 'unknown'] THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at) WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime() END as effective_date
              WHERE effective_date >= max_threshold

              // Filter by organization (WFA, WBA, etc.) - this ensures "Wi-Fi Alliance updates" only returns WFA sources
              WITH r, effective_date, primary_threshold, fallback_threshold, items_per_group, group_limit, requested_days
              WHERE ($organizations IS NULL OR size($organizations) = 0
                OR EXISTS {
                    MATCH (r)-[:MENTIONS|PUBLISHED_BY]->(org:Organization)
                    WHERE org.name IN $organizations
                }
                OR EXISTS {
                    MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)-[:OPERATED_BY]->(org:Organization)
                    WHERE org.name IN $organizations
                })
               // Filter by specific workgroups if requested
               AND ($workgroups IS NULL OR size($workgroups) = 0
                 OR EXISTS {
                     MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
                     WHERE ds.datasource_id IN $workgroups OR ds.name IN $workgroups
                 })
               // Filter by topic if requested
                AND ($topics IS NULL OR size($topics) = 0
                   OR EXISTS {
                       MATCH (r)-[:RELATES_TO]->(t:Topic)
                       WHERE t.name IN $topics
                          OR t.topic_id IN $topics
                          OR ANY(alias IN coalesce(t.aliases, []) WHERE alias IN $topics)
                          OR ANY(requested IN $topics WHERE
                              toLower(t.name) CONTAINS toLower(requested)
                              OR toLower(t.topic_id) CONTAINS toLower(requested)
                              OR ANY(alias IN coalesce(t.aliases, []) WHERE
                                  toLower(alias) CONTAINS toLower(requested)
                              )
                          )
                   })

                // Categorize by time window using effective date
                WITH r, effective_date, items_per_group, group_limit, requested_days, primary_threshold, fallback_threshold,
                     CASE
                         WHEN $topics IS NULL OR size($topics) = 0 THEN 0
                         WHEN any(topic IN $topics WHERE toLower(coalesce(r.title, '')) CONTAINS toLower(topic)) THEN 4
                         WHEN any(topic IN $topics WHERE toLower(coalesce(r.summary, '')) CONTAINS toLower(topic)) THEN 2
                         ELSE 0
                     END as topic_term_bonus,
                     CASE
                         WHEN coalesce(trim(r.title), '') = '' OR toLower(trim(r.title)) = 'untitled' THEN -3
                         ELSE 0
                     END as title_quality_bonus,
                     CASE WHEN effective_date >= primary_threshold THEN 'primary' WHEN effective_date >= fallback_threshold THEN 'fallback'
                         ELSE 'max' END as time_bucket

              WITH collect(CASE WHEN time_bucket = 'primary' THEN {resource: r, effective_date: effective_date, score: topic_term_bonus + title_quality_bonus} ELSE null END) as primary_docs,
                   collect(CASE WHEN time_bucket = 'fallback' THEN {resource: r, effective_date: effective_date, score: topic_term_bonus + title_quality_bonus} ELSE null END) as fallback_docs,
                   collect(CASE WHEN time_bucket = 'max' THEN {resource: r, effective_date: effective_date, score: topic_term_bonus + title_quality_bonus} ELSE null END) as max_docs,
                   items_per_group, group_limit, requested_days

               // Use first non-empty bucket
               WITH CASE WHEN size([d IN primary_docs WHERE d IS NOT NULL]) > 0 THEN [d IN primary_docs WHERE d IS NOT NULL] WHEN size([d IN fallback_docs WHERE d IS NOT NULL]) > 0 THEN [d IN fallback_docs WHERE d IS NOT NULL] ELSE [d IN max_docs WHERE d IS NOT NULL] END as final_docs,
                    CASE WHEN size([d IN primary_docs WHERE d IS NOT NULL]) > 0 THEN requested_days WHEN size([d IN fallback_docs WHERE d IS NOT NULL]) > 0 THEN 56 ELSE 180 END as actual_window_days,
                    items_per_group,
                    group_limit

              UNWIND final_docs as ranked_doc

              WITH ranked_doc.resource as r,
                   ranked_doc.effective_date as effective_date,
                   ranked_doc.score as relevance_bonus,
                   actual_window_days, items_per_group, group_limit

              // Get datasource for grouping
              OPTIONAL MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
            
              // Get events mentioned in these documents
            OPTIONAL MATCH (r)-[:MENTIONS]->(e:Event)
            
              // Get topics
             OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)

             WITH r, effective_date, relevance_bonus, actual_window_days, items_per_group, group_limit, ds, e, t
             ORDER BY relevance_bonus DESC, effective_date DESC
             
             // Group by datasource
              WITH coalesce(ds.datasource_id, 'unknown') as workgroup_id,
                  coalesce(ds.name, 'Unknown Source') as workgroup_name,
                  actual_window_days,
                  items_per_group,
                  group_limit,
                  collect(DISTINCT e) as all_events,
                  collect(DISTINCT {resource: r, effective_date: effective_date, relevance_bonus: relevance_bonus}) as all_docs_with_dates,
                  collect(DISTINCT t.name)[..5] as top_topics
            
            // Skip empty groups
            WHERE size(all_docs_with_dates) > 0 OR size(all_events) > 0
            
            // Calculate last update date using effective dates
             WITH workgroup_id, workgroup_name, actual_window_days, items_per_group, group_limit,
                  all_events, all_docs_with_dates, top_topics,
                  CASE WHEN size(all_docs_with_dates) > 0 THEN reduce(latest = datetime('1970-01-01'), doc IN all_docs_with_dates | CASE WHEN doc.effective_date > latest THEN doc.effective_date ELSE latest END) ELSE null END as last_update_date
             
             WITH
                workgroup_id,
                workgroup_name,
                actual_window_days,
                top_topics,
                last_update_date,
                [event IN all_events[..items_per_group] | {
                    type: 'event',
                    id: event.url_hash,
                    title: event.name,
                    startTime: event.start_date,
                    url: event.url
                }] as recent_events,
                [doc IN all_docs_with_dates[..items_per_group] | {
                    type: 'document',
                    id: doc.resource.url_hash,
                    title: doc.resource.title,
                    summary: doc.resource.summary,
                    publishDate: toString(doc.effective_date),
                    url: doc.resource.url,
                    category: doc.resource.category
                }] as recent_documents,
                group_limit
            ORDER BY last_update_date DESC
            WITH collect({
                workgroup_id: workgroup_id,
                workgroup_name: workgroup_name,
                time_window_used: actual_window_days,
                last_content_date: toString(last_update_date),
                top_topics: top_topics,
                recent_events: recent_events,
                recent_documents: recent_documents
            }) as grouped_results,
            group_limit
            WITH grouped_results[..group_limit] as limited_results
            UNWIND limited_results as result
            RETURN
                result.workgroup_id as workgroup_id,
                result.workgroup_name as workgroup_name,
                result.time_window_used as time_window_used,
                result.last_content_date as last_content_date,
                result.top_topics as top_topics,
                result.recent_events as recent_events,
                result.recent_documents as recent_documents
            """
        )
        
        # ========================================
        # LEGACY TEMPLATES (To be deprecated)
        # ========================================
        
        # WORKGROUP_WEEKLY_RECAP - fetch weekly summary from DataSource (workgroups)
        self.templates[RouteId.WORKGROUP_WEEKLY_RECAP] = QueryTemplate(
            route_id=RouteId.WORKGROUP_WEEKLY_RECAP,
            description="Get weekly recap for workgroups (DataSource nodes)",
            param_schema={
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "workgroups": "list[str]",
                "limit": "int"
            },
            cypher="""
            // Match DataSource nodes (workgroups) - validate WFA Causeway workgroups only
            MATCH (ds:DataSource)
            WHERE ds.scraper_type = 'wfa_causeway' 
              AND ds.resource_url CONTAINS '/wg/'
              AND ($workgroups IS NULL OR size($workgroups) = 0 OR ds.datasource_id IN $workgroups OR ds.name IN $workgroups)
            
            // Find resources from these datasources in the date range
            MATCH (ds)<-[:INGESTED_FROM]-(r:Resource)
            WITH ds, r
            WITH ds, r,
                CASE WHEN r.publish_date IS NOT NULL AND NOT r.publish_date IN ['', 'unknown'] THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at) WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime('1970-01-01') END as effective_date
            WHERE ($start_date IS NULL OR effective_date >= datetime($start_date))
              AND ($end_date IS NULL OR effective_date <= datetime($end_date))
            
            // Get topics for each resource
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            
            // Collect topics per resource
            WITH r, ds, collect(DISTINCT t.name)[..5] as topics, effective_date
            
            // Sort by date (most recent first)
            ORDER BY effective_date DESC
            
            // Return individual documents
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                r.category as type,
                topics,
                [] as organizations
            LIMIT $limit
            """
        )
        
        # WORKGROUP_DAILY_RECAP - fetch daily summary from DataSource (workgroups)
        self.templates[RouteId.WORKGROUP_DAILY_RECAP] = QueryTemplate(
            route_id=RouteId.WORKGROUP_DAILY_RECAP,
            description="Get daily recap for workgroups (DataSource nodes)",
            param_schema={
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "workgroups": "list[str]",
                "limit": "int"
            },
            cypher="""
            // Match DataSource nodes (workgroups) - validate WFA Causeway workgroups only
            MATCH (ds:DataSource)
            WHERE ds.scraper_type = 'wfa_causeway' 
              AND ds.resource_url CONTAINS '/wg/'
              AND ($workgroups IS NULL OR size($workgroups) = 0 OR ds.datasource_id IN $workgroups OR ds.name IN $workgroups)
            
            // Find resources from these datasources in the date range
            MATCH (ds)<-[:INGESTED_FROM]-(r:Resource)
            WITH ds, r,
                CASE WHEN r.publish_date IS NOT NULL AND NOT r.publish_date IN ['', 'unknown'] THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at) WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime('1970-01-01') END as effective_date
            WHERE ($start_date IS NULL OR effective_date >= datetime($start_date))
              AND ($end_date IS NULL OR effective_date <= datetime($end_date))
            
            // Get topics for each resource
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            
            // Collect topics per resource
            WITH r, ds, collect(DISTINCT t.name)[..5] as topics, effective_date
            
            // Sort by date (most recent first)
            ORDER BY effective_date DESC
            
            // Return individual documents
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                r.category as type,
                topics,
                [] as organizations
            LIMIT $limit
            """
        )
        
        # WORKGROUP_RECENT_UPDATES - recent documents and events
        self.templates[RouteId.WORKGROUP_RECENT_UPDATES] = QueryTemplate(
            route_id=RouteId.WORKGROUP_RECENT_UPDATES,
            description="Get recent updates (recently published/updated docs + any events they mention)",
            param_schema={
                "workgroups": "list[str]",
                "topics": "list[str]",
                "relative_days": "int",
                "limit": "int"
            },
            cypher="""
            // Calculate date threshold for document updates (not event dates)
            WITH datetime() - duration({days: coalesce($relative_days, 14)}) as doc_threshold,
                 toInteger($limit / 2.0) as half_limit
            
            // Get recently PUBLISHED/UPDATED documents (use date fallback for NULL publish_date)
            MATCH (r:Resource)
              WITH r, doc_threshold, half_limit
              WITH r, doc_threshold, half_limit,
                  CASE WHEN r.publish_date IS NOT NULL AND NOT r.publish_date IN ['', 'unknown'] THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at) WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime() END as effective_date
            WHERE effective_date >= doc_threshold
            
            // Filter by datasource (workgroup) via INGESTED_FROM relationship
            WITH r, doc_threshold, half_limit
            WHERE $workgroups IS NULL OR size($workgroups) = 0
               OR EXISTS {
                   MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
                   WHERE ds.datasource_id IN $workgroups
               }
            
            // Get the datasource for grouping
            OPTIONAL MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
            
            // Get events mentioned in these recent documents
            OPTIONAL MATCH (r)-[:MENTIONS]->(e:Event)
            
            // Get topics for scoring (don't filter by them - user preferences shouldn't limit results)
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            
            // Group by datasource and collect results
            WITH coalesce(ds.datasource_id, 'unknown') as workgroup_id,
                 coalesce(ds.name, 'Unknown') as workgroup_name,
                 half_limit,
                 collect(DISTINCT e) as all_events,
                 collect(DISTINCT r) as all_docs
            
            // Skip empty groups
            WHERE size(all_docs) > 0 OR size(all_events) > 0
            
            RETURN 
                workgroup_id,
                workgroup_name,
                [event IN all_events[..half_limit] | {
                    type: 'event',
                    id: event.url_hash,
                    title: event.name,
                    startTime: event.start_date,
                    url: event.url
                }] as recent_events,
                [doc IN all_docs[..half_limit] | {
                    type: 'document',
                    id: doc.url_hash,
                    title: doc.title,
                    summary: doc.summary,
                    publishDate: doc.publish_date,
                    url: doc.url
                }] as recent_documents
            LIMIT $limit
            """
        )
        
        # DECISIONS_IN_RANGE - decisions made in time range
        self.templates[RouteId.DECISIONS_IN_RANGE] = QueryTemplate(
            route_id=RouteId.DECISIONS_IN_RANGE,
            description="Get decisions made in date range",
            param_schema={
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "workgroups": "list[str]",
                "limit": "int"
            },
            cypher="""
            MATCH (r:Resource)
              WITH r,
                  CASE WHEN r.publish_date IS NOT NULL THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at) WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime() END as effective_date
            WHERE toLower(r.category) = 'decision'
              AND ($start_date IS NULL OR effective_date >= datetime($start_date))
              AND ($end_date IS NULL OR effective_date <= datetime($end_date))
            
            // Optional workgroup filter
            WITH r
            WHERE ($workgroups IS NULL OR size($workgroups) = 0
                   OR EXISTS {
                       MATCH (r)-[:MENTIONS]->(o:Organization)
                       WHERE o.name IN $workgroups OR o.org_id IN $workgroups
                   })
            
            // Get related topics and organizations
            OPTIONAL MATCH (r)-[rt:RELATES_TO]->(t:Topic)
            WHERE rt.relevance >= 0.5
            
            OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
            
            WITH r, 
                 collect(DISTINCT t.name)[..5] as topics,
                 collect(DISTINCT o.name)[..3] as organizations
            ORDER BY r.publish_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                topics,
                organizations
            LIMIT $limit
            """
        )
        
        # ACTION_ITEMS_OPEN - open action items
        self.templates[RouteId.ACTION_ITEMS_OPEN] = QueryTemplate(
            route_id=RouteId.ACTION_ITEMS_OPEN,
            description="Get open action items",
            param_schema={
                "workgroups": "list[str]",
                "limit": "int"
            },
            cypher="""
            MATCH (r:Resource)
            WHERE toLower(r.category) IN ['action', 'task', 'todo']
              AND (r.status IS NULL OR toLower(r.status) IN ['open', 'pending', 'in progress'])
            
            // Optional workgroup filter
            WITH r
            WHERE ($workgroups IS NULL OR size($workgroups) = 0
                   OR EXISTS {
                       MATCH (r)-[:MENTIONS]->(o:Organization)
                       WHERE o.name IN $workgroups OR o.org_id IN $workgroups
                   })
            
            OPTIONAL MATCH (r)-[:MENTIONS]->(p:Person)
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            
            WITH r,
                 collect(DISTINCT p.name)[..3] as assignees,
                 collect(DISTINCT t.name)[..5] as topics
            ORDER BY r.publish_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                assignees,
                topics
            LIMIT $limit
            """
        )
        
        # TOPICS_TREND - trending topics
        self.templates[RouteId.TOPICS_TREND] = QueryTemplate(
            route_id=RouteId.TOPICS_TREND,
            description="Get trending topics in time range",
            param_schema={
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "topics": "list[str]",
                "limit": "int"
            },
            cypher="""
            // Get resources in date range - don't filter by user topic preferences
            // User preferences should boost, not limit results (user might discover new topics)
            MATCH (r:Resource)-[rt:RELATES_TO]->(t:Topic)
            WITH r, rt, t,
                 CASE WHEN r.publish_date IS NOT NULL THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at) WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime() END as effective_date
            WHERE ($start_date IS NULL OR effective_date >= datetime($start_date))
              AND ($end_date IS NULL OR effective_date <= datetime($end_date))
              AND rt.relevance >= 0.5
            
            // Count mentions per topic
            WITH t, 
                 count(DISTINCT r) as mention_count, 
                 collect(DISTINCT r)[..10] as resources,
                 // Boost score if topic matches user preferences (for ranking, not filtering)
                 CASE WHEN $topics IS NOT NULL AND size($topics) > 0 AND t.name IN $topics THEN 1.5 ELSE 1.0 END as preference_boost
            ORDER BY mention_count * preference_boost DESC
            
            RETURN 
                t.topic_id as topic_id,
                t.name as topic_name,
                mention_count,
                [res IN resources | {
                    id: res.url_hash,
                    title: res.title,
                    date: res.publish_date,
                    url: res.url
                }] as sample_documents
            LIMIT $limit
            """
        )
        
        # WHO_SAID_WHAT - find mentions by people
        self.templates[RouteId.WHO_SAID_WHAT] = QueryTemplate(
            route_id=RouteId.WHO_SAID_WHAT,
            description="Find who mentioned specific topics",
            param_schema={
                "topics": "list[str]",
                "people": "list[str]",
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "limit": "int"
            },
            cypher="""
            MATCH (r:Resource)-[:MENTIONS]->(p:Person)
            WITH r, p,
                 CASE WHEN r.publish_date IS NOT NULL THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at)
                      WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime() END as effective_date
            WHERE ($people IS NULL OR size($people) = 0 OR p.name IN $people)
              AND ($start_date IS NULL OR effective_date >= datetime($start_date))
              AND ($end_date IS NULL OR effective_date <= datetime($end_date))
            
            // Optional topic filter
            WITH r, p
            WHERE ($topics IS NULL OR size($topics) = 0
                   OR EXISTS {
                       MATCH (r)-[:RELATES_TO]->(t:Topic)
                       WHERE any(topic IN $topics WHERE toLower(t.name) = toLower(topic))
                   })
            
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            
            WITH p, r, collect(DISTINCT t.name)[..5] as topics
            ORDER BY r.publish_date DESC
            
            RETURN 
                p.person_id as person_id,
                p.name as person_name,
                r.url_hash as document_id,
                r.title as document_title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                topics
            LIMIT $limit
            """
        )
        
        # MEETING_BY_TITLE - search for meetings
        self.templates[RouteId.MEETING_BY_TITLE] = QueryTemplate(
            route_id=RouteId.MEETING_BY_TITLE,
            description="Find meetings by title keywords",
            param_schema={
                "topics": "list[str]",
                "workgroups": "list[str]",
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "limit": "int"
            },
            cypher="""
            MATCH (e:Event)
            WHERE ($start_date IS NULL OR datetime(e.startTime) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(e.startTime) <= datetime($end_date))
            
            // Optional workgroup filter
            WITH e
            WHERE ($workgroups IS NULL OR size($workgroups) = 0
                   OR EXISTS {
                       MATCH (e)-[:BELONGS_TO]->(wg:Workgroup)
                       WHERE wg.id IN $workgroups OR wg.name IN $workgroups
                   })
            
            // Optional topic filter (via related documents)
            WITH e
            WHERE ($topics IS NULL OR size($topics) = 0
                   OR EXISTS {
                       MATCH (e)<-[:RELATES_TO]-(r:Resource)-[:RELATES_TO]->(t:Topic)
                       WHERE any(topic IN $topics WHERE toLower(t.name) = toLower(topic))
                   })
            
            OPTIONAL MATCH (e)-[:BELONGS_TO]->(wg:Workgroup)
            OPTIONAL MATCH (e)<-[:RELATES_TO]-(r:Resource)
            
            WITH e, wg, collect(DISTINCT r)[..5] as docs
            ORDER BY e.startTime DESC
            
            RETURN 
                e.id as event_id,
                e.name as title,
                e.startTime as start_time,
                e.endTime as end_time,
                e.description as description,
                e.url as url,
                wg.name as workgroup,
                [doc IN docs | {
                    id: doc.url_hash,
                    title: doc.title,
                    url: doc.url
                }] as related_documents
            LIMIT $limit
            """
        )
        
        # MEETING_ATTENDEES - find who attended/participated in meetings
        self.templates[RouteId.MEETING_ATTENDEES] = QueryTemplate(
            route_id=RouteId.MEETING_ATTENDEES,
            description="Find people who attended or participated in meetings",
            param_schema={
                "people": "list[str]",
                "topics": "list[str]",
                "workgroups": "list[str]",
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "limit": "int"
            },
            cypher="""
            // Find meeting/event documents
            MATCH (r:Resource)
            WHERE toLower(r.category) IN ['meeting', 'minutes', 'agenda', 'session']
              AND ($start_date IS NULL OR r.publish_date >= $start_date)
              AND ($end_date IS NULL OR r.publish_date <= $end_date)
            
            // Filter by workgroup if specified
            WITH r
            WHERE ($workgroups IS NULL OR size($workgroups) = 0
                   OR EXISTS {
                       MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
                       WHERE ds.datasource_id IN $workgroups OR ds.name IN $workgroups
                   })
            
            // Get people mentioned in these meeting documents
            OPTIONAL MATCH (r)-[:MENTIONS]->(p:Person)
            WHERE ($people IS NULL OR size($people) = 0
                   OR any(name IN $people WHERE toLower(p.name) CONTAINS toLower(name)))
            
            // Get topics to help filter relevance
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            WHERE ($topics IS NULL OR size($topics) = 0
                   OR any(topic IN $topics WHERE toLower(t.name) CONTAINS toLower(topic)))
            
            WITH r, p, collect(DISTINCT t.name)[0..5] as topics
            ORDER BY r.publish_date DESC
            
            RETURN 
                r.url_hash as document_id,
                r.title as meeting_title,
                r.publish_date as date,
                r.url as url,
                r.summary as summary,
                collect(DISTINCT p.name)[0..20] as attendees,
                topics
            LIMIT $limit
            """
        )
        
        # UPCOMING_EVENTS - future events
        self.templates[RouteId.UPCOMING_EVENTS] = QueryTemplate(
            route_id=RouteId.UPCOMING_EVENTS,
            description="Get upcoming events (excluding meetings when conferences are requested)",
            param_schema={
                "workgroups": "list[str]",
                "topics": "list[str]",
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "exclude_meetings": "bool (true for conference queries)",
                "limit": "int"
            },
            cypher="""
            // Find Event nodes: upcoming events OR recent past events (last 30 days)
            // This ensures results even when no future events are scheduled
            MATCH (e:Event)
            WHERE datetime(e.start_date) >= datetime() - duration({days: 30})
              AND ($start_date IS NULL OR datetime(e.start_date) >= datetime($start_date))
              // Extend "this quarter" to 90 days ahead
              AND ($end_date IS NULL OR datetime(e.start_date) <= datetime($end_date))
              // Exclude meetings if conferences specifically requested
              AND ($exclude_meetings IS NULL OR $exclude_meetings = false OR NOT toLower(coalesce(e.event_type, '')) IN ['meeting', 'workgroup meeting', 'task group meeting'])
            
            // Optional workgroup filter (only apply if workgroups specified)
            WITH e
            WHERE ($workgroups IS NULL OR size($workgroups) = 0
                   OR EXISTS {
                       MATCH (e)<-[:MENTIONS]-(r:Resource)-[:INGESTED_FROM]->(ds:DataSource)
                       WHERE ds.datasource_id IN $workgroups
                   })
            
            // Optional topic filter (topics mentioned in event or related documents)
            WITH e
            WHERE ($topics IS NULL OR size($topics) = 0
                   OR EXISTS {
                       MATCH (e)-[:RELATES_TO]->(t:Topic)
                       WHERE any(topic IN $topics WHERE toLower(t.name) = toLower(topic) OR any(alias IN t.aliases WHERE toLower(alias) = toLower(topic)))
                   }
                   OR EXISTS {
                       // Check if recent documents mention both the event and the topic
                       MATCH (r:Resource)-[:MENTIONS]->(e)
                       MATCH (r)-[:RELATES_TO]->(t:Topic)
                       WHERE any(topic IN $topics WHERE toLower(t.name) = toLower(topic) OR any(alias IN t.aliases WHERE toLower(alias) = toLower(topic)))
                   })
            
            OPTIONAL MATCH (e)-[:RELATES_TO]->(t:Topic)
            
            WITH e,
                 collect(DISTINCT t.name)[..5] as topics
            ORDER BY e.start_date ASC
            
            RETURN 
                e.url_hash as event_id,
                e.name as title,
                e.start_date as start_time,
                e.end_date as end_time,
                e.location as location,
                e.url as url,
                e.event_type as event_type,
                null as workgroup,
                topics
            LIMIT $limit
            """
        )
        
        # PAST_EVENTS - recent past events
        self.templates[RouteId.PAST_EVENTS] = QueryTemplate(
            route_id=RouteId.PAST_EVENTS,
            description="Get past events (defaults to last 30 days if no date range specified)",
            param_schema={
                "workgroups": "list[str]",
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "relative_days": "int",
                "limit": "int"
            },
            cypher="""
            // Default to last 30 days if no date range specified
            WITH CASE WHEN $start_date IS NULL THEN datetime() - duration({days: coalesce($relative_days, 30)})
                      ELSE datetime($start_date) END as threshold_start,
                 CASE WHEN $end_date IS NULL THEN datetime()
                      ELSE datetime($end_date) END as threshold_end
            
            MATCH (e:Event)
            WHERE datetime(e.startTime) >= threshold_start
              AND datetime(e.startTime) <= threshold_end
              AND ($workgroups IS NULL OR size($workgroups) = 0
                   OR EXISTS {
                       MATCH (e)-[:BELONGS_TO]->(wg:Workgroup)
                       WHERE wg.id IN $workgroups OR wg.name IN $workgroups
                   })
            
            OPTIONAL MATCH (e)-[:BELONGS_TO]->(wg:Workgroup)
            
            WITH e, wg
            ORDER BY e.startTime DESC
            
            RETURN 
                e.id as event_id,
                e.name as title,
                e.startTime as start_time,
                e.endTime as end_time,
                e.url as url,
                wg.name as workgroup
            LIMIT $limit
            """
        )
        
        # RECENT_DECISIONS - most recent decisions
        self.templates[RouteId.RECENT_DECISIONS] = QueryTemplate(
            route_id=RouteId.RECENT_DECISIONS,
            description="Get most recent decisions",
            param_schema={
                "relative_days": "int",
                "limit": "int"
            },
            cypher="""
            WITH datetime() - duration({days: coalesce($relative_days, 30)}) as threshold
            
            MATCH (r:Resource)
            WITH r, threshold,
                 CASE WHEN r.publish_date IS NOT NULL THEN datetime(r.publish_date)
                      WHEN r.created_at IS NOT NULL THEN datetime(r.created_at)
                      WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime() END as effective_date
            WHERE toLower(r.category) = 'decision'
              AND effective_date >= threshold
            
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            WHERE t.relevance >= 0.5
            
            OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
            
            WITH r, 
                 collect(DISTINCT t.name)[..5] as topics,
                 collect(DISTINCT o.name)[..3] as organizations
            ORDER BY r.publish_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                topics,
                organizations
            LIMIT $limit
            """
        )
        
        # DECISIONS_BY_TOPIC - decisions related to specific topics
        self.templates[RouteId.DECISIONS_BY_TOPIC] = QueryTemplate(
            route_id=RouteId.DECISIONS_BY_TOPIC,
            description="Get decisions by topic",
            param_schema={
                "topics": "list[str]",
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "limit": "int"
            },
            cypher="""
            MATCH (r:Resource)-[rt:RELATES_TO]->(t:Topic)
            WHERE toLower(r.category) = 'decision'
              AND rt.relevance >= 0.5
              AND t.name IN $topics
              AND ($start_date IS NULL OR datetime(r.publish_date) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(r.publish_date) <= datetime($end_date))
            
            OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
            
            WITH r, t,
                 collect(DISTINCT o.name)[..3] as organizations
            ORDER BY r.publish_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                t.name as primary_topic,
                organizations
            LIMIT $limit
            """
        )
        
        # ACTION_ITEMS_BY_PERSON - action items assigned to person
        self.templates[RouteId.ACTION_ITEMS_BY_PERSON] = QueryTemplate(
            route_id=RouteId.ACTION_ITEMS_BY_PERSON,
            description="Get action items by person",
            param_schema={
                "people": "list[str]",
                "limit": "int"
            },
            cypher="""
            MATCH (r:Resource)-[:MENTIONS]->(p:Person)
            WHERE toLower(r.category) IN ['action', 'task', 'todo']
              AND (r.status IS NULL OR toLower(r.status) IN ['open', 'pending', 'in progress'])
              AND p.name IN $people
            
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            
            WITH r, p,
                 collect(DISTINCT t.name)[..5] as topics
            ORDER BY r.publish_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                p.name as assignee,
                topics
            LIMIT $limit
            """
        )
        
        # DOCUMENTS_BY_TOPIC - documents on specific topics with KG-based relevance scoring
        # Supports both exact Topic node matching AND fuzzy text search fallback
        self.templates[RouteId.DOCUMENTS_BY_TOPIC] = QueryTemplate(
            route_id=RouteId.DOCUMENTS_BY_TOPIC,
            description="Get documents by topic with intelligent KG-based scoring",
            param_schema={
                "topics": "list[str]",
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "limit": "int"
            },
            cypher="""
            // Try exact Topic match first (case-insensitive for topic names)
            CALL {
                MATCH (r:Resource)-[rt:RELATES_TO]->(t:Topic)
                WHERE any(topic IN $topics WHERE toLower(t.name) = toLower(topic))
                  AND rt.relevance >= 0.5
                
                // Date fallback with validation - handle NULL publish_date
                WITH r, t, rt.relevance as base_relevance, rt.stance as stance,
                     CASE WHEN r.publish_date IS NOT NULL AND NOT r.publish_date IN ['', 'unknown'] THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at) WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime() END as effective_date
                
                RETURN r, effective_date, base_relevance, stance, t.name as topic_name, 'exact' as match_type
                
                UNION
                
                // Fallback: fuzzy text search in title/summary if no exact topic matches
                // For event queries (long topic strings), require full phrase match in title
                // For short topics, allow partial matches
                MATCH (r:Resource)
                WHERE (
                    // For event names (>10 chars), require presence in title for high relevance
                    // For short topics, allow title or summary matches
                    any(topic IN $topics WHERE 
                        (size(topic) > 10 AND toLower(r.title) CONTAINS toLower(topic)) OR
                        (size(topic) <= 10 AND (
                            toLower(r.title) CONTAINS toLower(topic) OR 
                            toLower(coalesce(r.summary, '')) CONTAINS toLower(topic)
                        ))
                    )
                )
                
                // Date fallback - handle NULL publish_date
                WITH r,
                     CASE WHEN r.publish_date IS NOT NULL AND NOT r.publish_date IN ['', 'unknown'] THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at) WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime() END as effective_date
                
                // Get the first matching topic for metadata and calculate match quality
                WITH r, effective_date,
                     head([topic IN $topics WHERE 
                         toLower(r.title) CONTAINS toLower(topic) OR 
                         toLower(coalesce(r.summary, '')) CONTAINS toLower(topic)
                     ]) as topic_name,
                     // Give higher base relevance if event name (long topic) appears in title
                     CASE WHEN any(topic IN $topics WHERE size(topic) > 10 AND toLower(r.title) CONTAINS toLower(topic)) THEN 0.7
                          WHEN any(topic IN $topics WHERE toLower(r.title) CONTAINS toLower(topic)) THEN 0.5
                          ELSE 0.3
                     END as fuzzy_relevance
                
                RETURN r, effective_date, fuzzy_relevance as base_relevance, 'mixed' as stance, topic_name, 'fuzzy' as match_type
            }
            
            WITH r, effective_date, base_relevance, stance, topic_name, match_type
            
            WHERE ($start_date IS NULL OR effective_date >= datetime($start_date))
              AND ($end_date IS NULL OR effective_date <= datetime($end_date))
              // Exclude documents with invalid future dates
              AND effective_date.year <= 2030
            
            // Count total topics for this resource (specificity calculation)
            WITH DISTINCT r, effective_date, base_relevance, stance, topic_name, match_type
            MATCH (r)-[:RELATES_TO]->(all_topics:Topic)
            WITH r, effective_date, base_relevance, stance, topic_name, match_type, count(DISTINCT all_topics) as topic_count
            
            // Calculate specificity score (fewer topics = more focused)
            WITH r, effective_date, base_relevance, stance, topic_name, match_type, topic_count,
                 CASE WHEN topic_count = 1 THEN 1.0 WHEN topic_count = 2 THEN 0.9 WHEN topic_count <= 5 THEN 0.7 ELSE 0.5 END as specificity_score
            
            // Calculate stance boost (descriptive documents explain topics better)
            WITH r, effective_date, base_relevance, stance, topic_name, match_type, topic_count, specificity_score,
                 CASE toLower(stance)
                   WHEN 'descriptive' THEN 1.5    // Boost explanatory/definitional content
                   WHEN 'supportive' THEN 1.2     // Advocacy content
                   WHEN 'directive' THEN 1.1      // Instructional content
                   WHEN 'speculative' THEN 0.9    // Forward-looking content
                   WHEN 'critical' THEN 0.8       // Critical analysis
                   WHEN 'concerned' THEN 0.8      // Concern-focused
                   ELSE 1.0                        // Mixed or neutral
                 END as stance_boost
            
            // Calculate title match boost
            // Apply a strong boost whenever ANY topic longer than 10 chars appears in the
            // document title — this surfaces focused documents (e.g. "Sticky Client Scenarios")
            // even when multiple topics are present (e.g. ["sticky clients", "wi-fi"]).
            WITH r, effective_date, base_relevance, stance, topic_name, match_type, topic_count, specificity_score, stance_boost,
                 CASE 
                   WHEN any(topic IN $topics WHERE size(topic) > 10 AND toLower(r.title) CONTAINS toLower(topic)) THEN 2.0
                   WHEN size($topics) = 1 AND toLower(r.title) CONTAINS toLower($topics[0]) THEN 1.5
                   ELSE 1.0
                 END as title_match_boost
            
            // Calculate content type boost
            WITH r, effective_date, base_relevance, stance, topic_name, match_type, topic_count, specificity_score, stance_boost, title_match_boost,
                 CASE r.category
                   WHEN 'whitepaper' THEN 1.5     // Increased from 1.3 for definition queries
                   WHEN 'specification' THEN 1.4  // Increased from 1.2
                   WHEN 'standard' THEN 1.4       // Increased from 1.2
                   WHEN 'technical_report' THEN 1.2  // Increased from 1.1
                   WHEN 'press release' THEN 1.1  // Press releases often introduce/explain
                   WHEN 'video' THEN 1.5          // Boost video content for events
                   WHEN 'blog' THEN 1.0
                   WHEN 'news' THEN 0.9
                   WHEN 'draft' THEN 0.9          // Decreased from 1.0
                   WHEN 'presentation' THEN 0.7   // Decreased from 0.8
                   WHEN 'meeting_minutes' THEN 0.3  // Decreased from 0.5
                   WHEN 'email' THEN 0.2          // Decreased from 0.4
                   ELSE 0.8
                 END as content_type_boost
            
            // Recency score (less important for definitional queries)
            WITH r, effective_date, base_relevance, stance, topic_name, match_type, topic_count, specificity_score, stance_boost, content_type_boost, title_match_boost,
                 CASE WHEN effective_date >= datetime() - duration({days: 180}) THEN 1.2 WHEN effective_date >= datetime() - duration({days: 365}) THEN 1.1 WHEN effective_date >= datetime() - duration({days: 730}) THEN 1.0 ELSE 0.9 END as recency_score
            
            // Apply match type penalty (fuzzy matches rank slightly lower)
            WITH r, effective_date, base_relevance, stance, topic_name, match_type, topic_count, specificity_score, stance_boost, content_type_boost, recency_score, title_match_boost,
                 CASE match_type
                   WHEN 'exact' THEN 1.0
                   WHEN 'fuzzy' THEN 0.8
                   ELSE 0.7
                 END as match_type_penalty
            
            // Calculate final KG relevance score (increased weight for title match and content_type)
            WITH r, effective_date, stance, topic_name, topic_count, match_type, base_relevance, match_type_penalty, specificity_score, stance_boost, content_type_boost, title_match_boost, recency_score,
                 (base_relevance * 0.25 * match_type_penalty +
                  specificity_score * 0.15 +
                  stance_boost * 0.2 +
                  content_type_boost * 0.15 +
                  title_match_boost * 0.2 +
                  recency_score * 0.05
                 ) as kg_score
            
            // Normalize kg_score to 0-1 range for consistency
            WITH r, effective_date, topic_name, topic_count, match_type, kg_score,
                 kg_score / 2.0 as normalized_kg_score
            
            // Extract segment number or URL timestamp for secondary sorting of video series
            WITH r, effective_date, topic_name, topic_count, match_type, normalized_kg_score,
                 CASE 
                   WHEN r.category = 'video' AND r.url CONTAINS 't=' THEN 
                     toInteger(replace(split(split(r.url, 't=')[1], '&')[0], 's', ''))
                   WHEN r.title =~ '.*Segment \\d+.*' THEN 
                     toInteger(replace(replace(split(r.title, 'Segment ')[1], '(', ''), ' ', ''))
                   ELSE 999999
                 END as segment_order
            
            ORDER BY normalized_kg_score DESC, segment_order ASC, effective_date DESC
            
            // Get additional metadata: datasource, topics, organizations
            OPTIONAL MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
            OPTIONAL MATCH (r)-[:RELATES_TO]->(all_topics:Topic)
            OPTIONAL MATCH (r)-[:MENTIONS]->(org:Organization)
            
            WITH r, effective_date, topic_name, topic_count, match_type, normalized_kg_score,
                 ds.datasource_id as datasource_id,
                 collect(DISTINCT all_topics.name) as all_topic_names,
                 collect(DISTINCT org.name) as org_names
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                toString(effective_date) as date,
                r.url as url,
                r.category as category,
                datasource_id,
                all_topic_names as topics,
                org_names as organizations,
                topic_name as matched_topic,
                round(normalized_kg_score * 100) / 100.0 as relevance_score,
                topic_count as topic_breadth,
                match_type
            LIMIT $limit
            """
        )
        
        # RECENT_PUBLICATIONS - recent documents/publications
        self.templates[RouteId.RECENT_PUBLICATIONS] = QueryTemplate(
            route_id=RouteId.RECENT_PUBLICATIONS,
            description="Get recent publications",
            param_schema={
                "relative_days": "int",
                "workgroups": "list[str]",
                "organizations": "list[str]",
                "topics": "list[str]",
                "category": "str",
                "limit": "int"
            },
            cypher="""
            WITH datetime() - duration({days: coalesce($relative_days, 14)}) as threshold
            
            MATCH (r:Resource)
            WITH r, threshold
            WITH r, threshold,
                 CASE WHEN r.publish_date IS NOT NULL AND NOT r.publish_date IN ['', 'unknown'] THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at) WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime() END as effective_date
            WHERE effective_date >= threshold
              AND effective_date <= datetime()
              AND ($workgroups IS NULL OR size($workgroups) = 0
                    OR EXISTS {
                        MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
                        WHERE ds.datasource_id IN $workgroups OR ds.name IN $workgroups
                    })
              AND ($organizations IS NULL OR size($organizations) = 0
                    OR EXISTS {
                        MATCH (r)-[:MENTIONS|PUBLISHED_BY]->(o:Organization)
                        WHERE o.name IN $organizations OR o.org_id IN $organizations
                    }
                    OR EXISTS {
                        MATCH (r)-[:INGESTED_FROM]->(:DataSource)-[:OPERATED_BY]->(o:Organization)
                        WHERE o.name IN $organizations OR o.org_id IN $organizations
                    })
              AND ($topics IS NULL OR size($topics) = 0
                    OR EXISTS {
                        MATCH (r)-[:RELATES_TO]->(t:Topic)
                        WHERE t.name IN $topics
                           OR t.topic_id IN $topics
                           OR ANY(alias IN coalesce(t.aliases, []) WHERE alias IN $topics)
                           OR ANY(requested IN $topics WHERE
                               toLower(t.name) CONTAINS toLower(requested)
                               OR toLower(t.topic_id) CONTAINS toLower(requested)
                               OR ANY(alias IN coalesce(t.aliases, []) WHERE
                                   toLower(alias) CONTAINS toLower(requested)
                               )
                           )
                    }
                    OR any(topic IN $topics WHERE
                        toLower(coalesce(r.title, '')) CONTAINS toLower(topic)
                        OR toLower(coalesce(r.summary, '')) CONTAINS toLower(topic)
                    ))
              AND ($category IS NULL OR toLower(r.category) = toLower($category))
            
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            OPTIONAL MATCH (r)-[:MENTIONS|PUBLISHED_BY]->(o:Organization)
            
            WITH r, effective_date,
                 collect(DISTINCT t.name)[..5] as topics,
                 collect(DISTINCT o.name)[..3] as organizations,
                 CASE
                     WHEN $topics IS NULL OR size($topics) = 0 THEN 0
                     WHEN any(topic IN $topics WHERE toLower(coalesce(r.title, '')) CONTAINS toLower(topic)) THEN 4
                     WHEN any(topic IN $topics WHERE toLower(coalesce(r.summary, '')) CONTAINS toLower(topic)) THEN 2
                     ELSE 0
                 END as topic_term_bonus
            ORDER BY topic_term_bonus DESC, effective_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                toString(effective_date) as date,
                r.url as url,
                r.category as type,
                topics,
                organizations
            LIMIT $limit
            """
        )
        
        # PERSON_ACTIVITY - activity/contributions by person
        self.templates[RouteId.PERSON_ACTIVITY] = QueryTemplate(
            route_id=RouteId.PERSON_ACTIVITY,
            description="Get person activity",
            param_schema={
                "people": "list[str]",
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "limit": "int"
            },
            cypher="""
            MATCH (p:Person)<-[:MENTIONS]-(r:Resource)
            WHERE p.name IN $people
              AND ($start_date IS NULL OR datetime(r.publish_date) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(r.publish_date) <= datetime($end_date))
            
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            
            WITH p, r,
                 collect(DISTINCT t.name)[..5] as topics
            ORDER BY r.publish_date DESC
            
            RETURN 
                p.person_id as person_id,
                p.name as person_name,
                p.title as person_title,
                r.url_hash as document_id,
                r.title as document_title,
                r.publish_date as date,
                r.url as url,
                topics
            LIMIT $limit
            """
        )
        
        # PERSON_AT_EVENT - what did a person discuss/present at a specific event
        self.templates[RouteId.PERSON_AT_EVENT] = QueryTemplate(
            route_id=RouteId.PERSON_AT_EVENT,
            description="Get person's contributions at a specific event",
            param_schema={
                "people": "list[str]",
                "event_name": "str",
                "limit": "int"
            },
            cypher="""
            // Find resources matching the event name and mentioning the person
            MATCH (r:Resource)-[:MENTIONS]->(p:Person)
            WHERE toLower(r.title) CONTAINS toLower($event_name)
              AND any(person IN $people WHERE toLower(p.name) CONTAINS toLower(person) OR toLower(person) CONTAINS toLower(p.name))
            
            // Date fallback with validation
            WITH r, p,
                 CASE WHEN r.publish_date IS NOT NULL AND NOT r.publish_date IN ['', 'unknown'] THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at) WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime() END as effective_date
            
            // Extract segment number or URL timestamp for secondary sorting of video series
            WITH r, p, effective_date,
                 CASE 
                   WHEN r.category = 'video' AND r.url CONTAINS 't=' THEN 
                     toInteger(replace(split(split(r.url, 't=')[1], '&')[0], 's', ''))
                   WHEN r.title =~ '.*Segment \\d+.*' THEN 
                     toInteger(replace(replace(split(r.title, 'Segment ')[1], '(', ''), ' ', ''))
                   ELSE 999999
                 END as segment_order
            
            // Get topics and other metadata
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            OPTIONAL MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
            OPTIONAL MATCH (r)-[:MENTIONS]->(org:Organization)
            
            WITH r, p, effective_date, segment_order,
                 ds.datasource_id as datasource_id,
                 collect(DISTINCT t.name)[..10] as topic_names,
                 collect(DISTINCT org.name)[..5] as org_names
            
            ORDER BY segment_order ASC, effective_date DESC
            
            RETURN 
                r.url_hash as document_id,
                r.title as title,
                coalesce(r.summary, '') as summary,
                r.url as url,
                effective_date as publish_date,
                r.category as category,
                datasource_id,
                topic_names as topics,
                org_names as organizations,
                collect(DISTINCT p.name) as mentioned_people,
                1.0 as relevance_score
            LIMIT $limit
            """
        )
        
        # TOPIC_TIMELINE - topic evolution over time
        self.templates[RouteId.TOPIC_TIMELINE] = QueryTemplate(
            route_id=RouteId.TOPIC_TIMELINE,
            description="Get topic timeline",
            param_schema={
                "topics": "list[str]",
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "limit": "int"
            },
            cypher="""
            MATCH (r:Resource)-[rt:RELATES_TO]->(t:Topic)
            WHERE any(topic IN $topics WHERE toLower(t.name) = toLower(topic))
              AND rt.relevance >= 0.5
              AND ($start_date IS NULL OR datetime(r.publish_date) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(r.publish_date) <= datetime($end_date))
            
            WITH t, r
            ORDER BY r.publish_date ASC
            
            WITH t.name as topic_name,
                 collect({
                     date: r.publish_date,
                     title: r.title,
                     url: r.url,
                     id: r.url_hash
                 }) as timeline
            
            RETURN 
                topic_name,
                timeline[..$limit] as events
            """
        )
        
        # RELATED_TOPICS - find related topics
        self.templates[RouteId.RELATED_TOPICS] = QueryTemplate(
            route_id=RouteId.RELATED_TOPICS,
            description="Get related topics",
            param_schema={
                "topics": "list[str]",
                "limit": "int"
            },
            cypher="""
            MATCH (t:Topic)
            WHERE any(topic IN $topics WHERE toLower(t.name) = toLower(topic) OR any(alias IN t.aliases WHERE toLower(alias) = toLower(topic)))
            
            // Find topics that co-occur in documents
            MATCH (t)<-[rt1:RELATES_TO]-(r:Resource)-[rt2:RELATES_TO]->(related:Topic)
            WHERE related <> t
              AND rt1.relevance >= 0.5
              AND rt2.relevance >= 0.5
            
            WITH related, count(DISTINCT r) as co_occurrence
            ORDER BY co_occurrence DESC
            
            RETURN 
                related.topic_id as topic_id,
                related.name as topic_name,
                co_occurrence as strength
            LIMIT $limit
            """
        )
        
        # WORKGROUP_MONTHLY_SUMMARY - monthly summary from DataSource (workgroups)
        self.templates[RouteId.WORKGROUP_MONTHLY_SUMMARY] = QueryTemplate(
            route_id=RouteId.WORKGROUP_MONTHLY_SUMMARY,
            description="Get monthly summary for workgroups (DataSource nodes)",
            param_schema={
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "workgroups": "list[str]",
                "limit": "int"
            },
            cypher="""
            // Match DataSource nodes (workgroups) - validate WFA Causeway workgroups only
            MATCH (ds:DataSource)
            WHERE ds.scraper_type = 'wfa_causeway' 
              AND ds.resource_url CONTAINS '/wg/'
              AND ($workgroups IS NULL OR size($workgroups) = 0 OR ds.datasource_id IN $workgroups OR ds.name IN $workgroups)
            
            // Find resources from these datasources in the date range
            MATCH (ds)<-[:INGESTED_FROM]-(r:Resource)
            WITH ds, r,
                CASE WHEN r.publish_date IS NOT NULL AND NOT r.publish_date IN ['', 'unknown'] THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at) WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime('1970-01-01') END as effective_date
            WHERE ($start_date IS NULL OR effective_date >= datetime($start_date))
              AND ($end_date IS NULL OR effective_date <= datetime($end_date))
            
            // Get topics for each resource
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            
            // Collect topics per resource
            WITH r, ds, collect(DISTINCT t.name)[..5] as topics, effective_date
            
            // Sort by date (most recent first)
            ORDER BY effective_date DESC
            
            // Return individual documents
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                r.category as type,
                topics,
                [] as organizations
            LIMIT $limit
            """
        )
        
        # ORGANIZATION_ACTIVITY - organization activity summary
        self.templates[RouteId.ORGANIZATION_ACTIVITY] = QueryTemplate(
            route_id=RouteId.ORGANIZATION_ACTIVITY,
            description="Get organization activity - prioritizes public content unless workgroup specified",
            param_schema={
                "organizations": "list[str]",
                "workgroups": "list[str]",
                "topics": "list[str]",
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "limit": "int"
            },
            cypher="""
            MATCH (o:Organization)
            WHERE o.name IN $organizations OR o.org_id IN $organizations
            
            MATCH (o)<-[:MENTIONS]-(r:Resource)
            WITH o, r,
                 CASE WHEN r.publish_date IS NOT NULL THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at) WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime() END as effective_date
            WHERE ($start_date IS NULL OR effective_date >= datetime($start_date))
              AND ($end_date IS NULL OR effective_date <= datetime($end_date))
            
            // Get datasource to determine priority
            OPTIONAL MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
            
            // Calculate priority: 
            // - If workgroups specified: workgroup content = 3, public = 2, other workgroups = 1
            // - If no workgroups: public = 3, workgroup = 1
            WITH o, r, effective_date, ds,
                 CASE 
                     WHEN $workgroups IS NOT NULL AND size($workgroups) > 0 THEN
                         CASE 
                             WHEN ds.datasource_id IN $workgroups THEN 3
                             WHEN ds.datasource_id IN ['wfa_resource_page', 'wba_resource_page'] THEN 2
                             ELSE 1
                         END
                     ELSE
                         CASE 
                             WHEN ds.datasource_id IN ['wfa_resource_page', 'wba_resource_page'] THEN 3
                             WHEN ds.scraper_type = 'wfa_causeway' THEN 1
                             ELSE 2
                         END
                 END as source_priority
            
            // Get topic + org associations for scoring and response
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            OPTIONAL MATCH (r)-[:MENTIONS]->(mentioned_org:Organization)
            
            WITH o, r, effective_date, source_priority,
                 collect(DISTINCT t.name)[..5] as topics,
                 collect(DISTINCT mentioned_org.name)[0..3] as orgs,
                 // Topic preference bonus: if personalization topics provided, boost docs that match them
                 // This PREFERS relevant topics but doesn't filter them out
                 CASE 
                     WHEN $topics IS NULL OR size($topics) = 0 THEN 0
                     ELSE reduce(bonus = 0, topic IN $topics | 
                         bonus + CASE 
                             WHEN toLower(r.title) CONTAINS toLower(topic) THEN 20
                             WHEN r.summary IS NOT NULL AND toLower(r.summary) CONTAINS toLower(topic) THEN 10
                             WHEN EXISTS {
                                 MATCH (r)-[:RELATES_TO]->(related_topic:Topic)
                                 WHERE toLower(related_topic.name) = toLower(topic) 
                                    OR any(alias IN related_topic.aliases WHERE toLower(alias) = toLower(topic))
                             } THEN 15
                             ELSE 0
                         END
                     )
                 END as topic_preference_score
            
            // Order by topic preference (personalization), then priority, then date
            ORDER BY topic_preference_score DESC, source_priority DESC, effective_date DESC
            
            RETURN 
                o.org_id as org_id,
                o.name as org_name,
                collect({
                    id: r.url_hash,
                    title: r.title,
                    date: toString(effective_date),
                    url: r.url,
                    topics: topics,
                    organizations: orgs,
                    priority: source_priority,
                    topic_score: topic_preference_score
                })[..$limit] as recent_activity
            """
        )
        
        # AGENT_CONTENT_DISCOVERY - specialized route for creator agents
        # Combines recent updates with deduplication and relevance scoring
        self.templates[RouteId.AGENT_CONTENT_DISCOVERY] = QueryTemplate(
            route_id=RouteId.AGENT_CONTENT_DISCOVERY,
            description="Discover content for creator agents with deduplication",
            param_schema={
                "topics": "list[str]",
                "organizations": "list[str]",
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "exclude_ids": "list[str]",
                "limit": "int"
            },
            cypher="""
            // Calculate date threshold
            WITH datetime() - duration({days: coalesce($relative_days, 7)}) as doc_threshold
            
            // Match resources by topics or organizations
            MATCH (r:Resource)
            WITH r, doc_threshold,
                 CASE WHEN r.publish_date IS NOT NULL THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at) WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime() END as effective_date
            WHERE effective_date >= doc_threshold
              AND ($start_date IS NULL OR effective_date >= datetime($start_date))
              AND ($end_date IS NULL OR effective_date <= datetime($end_date))
              // Exclude previously used content
              AND NOT r.url_hash IN $exclude_ids
            
            // Filter by topics or organizations
            WITH r, doc_threshold
            WHERE (
                ($topics IS NOT NULL AND size($topics) > 0 AND EXISTS {
                    MATCH (r)-[:RELATES_TO]->(t:Topic)
                    WHERE any(topic IN $topics WHERE toLower(t.name) = toLower(topic))
                }) OR
                ($organizations IS NOT NULL AND size($organizations) > 0 AND EXISTS {
                    MATCH (r)-[:MENTIONS]->(o:Organization)
                    WHERE o.name IN $organizations OR o.org_id IN $organizations
                })
            )
            
            // Get related entities for context
            OPTIONAL MATCH (r)-[rt:RELATES_TO]->(t:Topic)
            WHERE rt.relevance >= 0.5
            
            OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
            OPTIONAL MATCH (r)-[:MENTIONS]->(e:Event)
            OPTIONAL MATCH (r)-[:MENTIONS]->(p:Person)
            
            // Calculate relevance score for agent content
            WITH r,
                 collect(DISTINCT t.name)[..5] as topics,
                 collect(DISTINCT o.name)[..3] as organizations,
                 collect(DISTINCT e.name)[..2] as events,
                 collect(DISTINCT p.name)[..3] as people,
                 // Topic specificity: fewer topics = more focused
                 CASE WHEN size(collect(DISTINCT t)) = 0 THEN 0.5 WHEN size(collect(DISTINCT t)) <= 3 THEN 1.0 WHEN size(collect(DISTINCT t)) <= 6 THEN 0.8 ELSE 0.6 END as specificity_score,
                 // Recency: exponential decay with 7-day half-life
                 CASE WHEN r.publish_date IS NULL THEN 0.5
                    ELSE exp(-duration.between(datetime(r.publish_date), datetime()).days / 7.0)
                 END as recency_score,
                 // Importance boost
                 CASE toLower(r.importance) WHEN 'high' THEN 1.2 WHEN 'critical' THEN 1.5 ELSE 1.0 END as importance_multiplier
            
            // Combined relevance score
            WITH r, topics, organizations, events, people,
                 (specificity_score * 0.6 + recency_score * 0.4) * importance_multiplier as relevance_score
            
            ORDER BY relevance_score DESC, r.publish_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as publish_date,
                r.last_updated as last_updated,
                r.url as url,
                r.category as category,
                r.importance as importance,
                topics,
                organizations,
                events,
                people,
                relevance_score
            LIMIT $limit
            """
        )
        
        # TOPIC_COMPARISON - compare two topics/standards side-by-side
        self.templates[RouteId.TOPIC_COMPARISON] = QueryTemplate(
            route_id=RouteId.TOPIC_COMPARISON,
            description="Compare two topics or standards side-by-side",
            param_schema={
                "topics": "list[str] (expects 2+ topics)",
                "start_date": "str (ISO date)",
                "limit": "int"
            },
            cypher="""
            // Find the topics to compare
            MATCH (t:Topic)
            WHERE any(topic IN $topics WHERE toLower(t.name) = toLower(topic) OR t.topic_id = topic OR any(alias IN coalesce(t.aliases, []) WHERE toLower(alias) = toLower(topic)))
            
            WITH collect(t) as topics_to_compare
            WHERE size(topics_to_compare) >= 2
            WITH topics_to_compare,
                 CASE
                     WHEN size(topics_to_compare) = 0 THEN 1
                     ELSE toInteger(ceil(toFloat($limit) / size(topics_to_compare)))
                 END as sample_limit
            
            // Get resources for each topic
            UNWIND topics_to_compare as topic
            MATCH (r:Resource)-[rt:RELATES_TO]->(topic)
            WHERE rt.relevance >= 0.5
              AND ($start_date IS NULL OR datetime(r.publish_date) >= datetime($start_date))
            
            // Collect organizations and key attributes
            OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
            
            // Drop topics_to_compare from scope before aggregation to avoid implicit grouping error
            WITH topic, r, o, sample_limit
            
            WITH topic, sample_limit,
                 count(DISTINCT r) as resource_count,
                 collect(DISTINCT r.publish_date)[0..5] as recent_dates,
                 collect(DISTINCT o.name)[0..10] as related_orgs,
                 collect(DISTINCT {
                     id: r.url_hash,
                     title: r.title,
                     date: r.publish_date,
                     url: r.url,
                     summary: r.summary
                 })[0..sample_limit] as sample_resources
            
            RETURN 
                topic.name as topic_name,
                topic.topic_id as topic_id,
                topic.description as description,
                topic.classification as classification,
                resource_count,
                recent_dates,
                related_orgs,
                sample_resources
            ORDER BY resource_count DESC
            """
        )
        
        # STATUS_CHECK - current status of topic/standard
        self.templates[RouteId.STATUS_CHECK] = QueryTemplate(
            route_id=RouteId.STATUS_CHECK,
            description="Get current status of a topic or standard",
            param_schema={
                "topics": "list[str]",
                "limit": "int"
            },
            cypher="""
            // Find resources with status keywords
            MATCH (t:Topic)
            WHERE ($topics IS NULL OR size($topics) = 0 OR t.name IN $topics OR t.topic_id IN $topics OR ANY(alias IN t.aliases WHERE alias IN $topics))
            
            MATCH (r:Resource)-[:RELATES_TO]->(t)
            WHERE r.title =~ '(?i).*(status|progress|update|approved|final|draft|ratified|published|released|version).*'
            
            OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
            
            WITH r, t,
                 collect(DISTINCT o.name)[0..3] as orgs
            ORDER BY r.publish_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                r.category as type,
                t.name as topic,
                orgs as organizations
            LIMIT $limit
            """
        )
        
        # TECHNICAL_EXPLANATION - how does X work, architecture, design
        self.templates[RouteId.TECHNICAL_EXPLANATION] = QueryTemplate(
            route_id=RouteId.TECHNICAL_EXPLANATION,
            description="Get technical documentation and explanations",
            param_schema={
                "topics": "list[str]",
                "limit": "int"
            },
            cypher="""
            MATCH (t:Topic)
            WHERE ($topics IS NULL OR size($topics) = 0 OR t.name IN $topics OR t.topic_id IN $topics OR ANY(alias IN t.aliases WHERE alias IN $topics))

            MATCH (r:Resource)-[:RELATES_TO]->(t)
            WHERE (r.category IN ['specification', 'whitepaper', 'technical_guide', 'standard']
                   OR r.title =~ '(?i).*(architecture|design|implementation|guide|specification|technical|mechanism|structure).*')
              AND r.publish_date IS NOT NULL
            
            OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
            
            WITH r, t,
                 collect(DISTINCT o.name)[0..3] as orgs
            ORDER BY r.publish_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                r.category as type,
                t.name as topic,
                orgs as organizations
            LIMIT $limit
            """
        )
        
        # ADOPTION_STATUS - who supports/uses X
        self.templates[RouteId.ADOPTION_STATUS] = QueryTemplate(
            route_id=RouteId.ADOPTION_STATUS,
            description="Find organizations that support or use a technology",
            param_schema={
                "topics": "list[str]",
                "limit": "int"
            },
            cypher="""
            MATCH (t:Topic)
            WHERE ($topics IS NULL OR size($topics) = 0 OR t.name IN $topics OR t.topic_id IN $topics OR ANY(alias IN t.aliases WHERE alias IN $topics))

            // Find resources about this topic mentioning adoption
            MATCH (r:Resource)-[:RELATES_TO]->(t)
            MATCH (r)-[:MENTIONS]->(o:Organization)
            WHERE r.title =~ '(?i).*(adopt|deploy|support|implement|launch|announce|using|enable).*'
            
            // Count mentions per organization
            WITH o, t,
                 count(DISTINCT r) as mention_count,
                 collect(DISTINCT {
                     id: r.url_hash,
                     title: r.title,
                     date: r.publish_date,
                     url: r.url
                 })[0..5] as supporting_resources
            ORDER BY mention_count DESC
            
            RETURN 
                o.name as organization,
                o.org_id as org_id,
                o.org_type as org_type,
                mention_count,
                supporting_resources
            LIMIT $limit
            """
        )
        
        # PERSON_PROFILE - who is [Person Name]
        self.templates[RouteId.PERSON_PROFILE] = QueryTemplate(
            route_id=RouteId.PERSON_PROFILE,
            description="Get profile information for a person",
            param_schema={
                "people": "list[str]",
                "limit": "int"
            },
            cypher="""
            // Find the person
            MATCH (p:Person)
            WHERE ($people IS NULL OR size($people) = 0 OR p.name IN $people OR p.person_id IN $people)
            
            // Get their affiliations
            OPTIONAL MATCH (p)-[aff:AFFILIATED_WITH]->(o:Organization)
            
            // Get topics they're connected to
            OPTIONAL MATCH (p)-[:CONNECTED_TO]->(t:Topic)
            
            // Get recent resources mentioning them - sort BEFORE aggregation
            OPTIONAL MATCH (r:Resource)-[:MENTIONS]->(p)
            WHERE r.publish_date IS NOT NULL
            
            // Sort while r is still in scope, then aggregate
            WITH p, o, aff, t, r
            ORDER BY r.publish_date DESC
            
            WITH p, o, aff,
                 collect(DISTINCT t.name)[0..10] as topics,
                 collect(DISTINCT {
                     id: r.url_hash,
                     title: r.title,
                     date: r.publish_date,
                     url: r.url
                 })[0..10] as recent_resources
            
            RETURN 
                p.name as name,
                p.person_id as person_id,
                p.email as email,
                collect(DISTINCT {name: o.name, role: aff.role})[0..5] as affiliations,
                topics,
                recent_resources
            LIMIT $limit
            """
        )
        
        # ORGANIZATION_REPRESENTATIVES - who represents X at Y
        self.templates[RouteId.ORGANIZATION_REPRESENTATIVES] = QueryTemplate(
            route_id=RouteId.ORGANIZATION_REPRESENTATIVES,
            description="Find people representing an organization at meetings/events",
            param_schema={
                "organizations": "list[str]",
                "topics": "list[str]",
                "limit": "int"
            },
            cypher="""
            // Find the organization
            MATCH (org:Organization)
            WHERE org.name IN $organizations OR org.org_id IN $organizations
            
            // Find people affiliated with this org
            MATCH (p:Person)-[aff:AFFILIATED_WITH]->(org)
            
            // If topics specified, filter by topic connections
            OPTIONAL MATCH (p)-[:CONNECTED_TO]->(t:Topic)
            WHERE $topics IS NULL OR size($topics) = 0 OR t.name IN $topics OR ANY(alias IN t.aliases WHERE alias IN $topics)
            
            // Get recent resources/events they're mentioned in
            OPTIONAL MATCH (r:Resource)-[:MENTIONS]->(p)
            WHERE r.publish_date IS NOT NULL
            
            WITH p, org, aff,
                 count(DISTINCT r) as activity_count,
                 collect(DISTINCT t.name)[0..5] as topics,
                 collect(DISTINCT {
                     id: r.url_hash,
                     title: r.title,
                     date: r.publish_date,
                     url: r.url
                 })[0..5] as recent_activity
            ORDER BY activity_count DESC
            
            RETURN 
                p.name as name,
                p.email as email,
                aff.role as role,
                org.name as organization,
                topics,
                activity_count,
                recent_activity
            LIMIT $limit
            """
        )
        
        # LEARNING_RESOURCES - tutorials, guides, getting started
        self.templates[RouteId.LEARNING_RESOURCES] = QueryTemplate(
            route_id=RouteId.LEARNING_RESOURCES,
            description="Find educational resources and tutorials",
            param_schema={
                "topics": "list[str]",
                "limit": "int"
            },
            cypher="""
            MATCH (t:Topic)
            WHERE ($topics IS NULL OR size($topics) = 0 OR t.name IN $topics OR t.topic_id IN $topics OR ANY(alias IN t.aliases WHERE alias IN $topics))
            
            MATCH (r:Resource)-[:RELATES_TO]->(t)
            WHERE (r.category IN ['tutorial', 'guide', 'training', 'documentation']
                   OR r.title =~ '(?i).*(intro|tutorial|guide|learn|beginner|getting started|how to|step by step).*')
            
            OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
            
            WITH r, t,
                 collect(DISTINCT o.name)[0..3] as orgs
            ORDER BY r.publish_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                r.category as type,
                t.name as topic,
                orgs as organizations
            LIMIT $limit
            """
        )
        
        # VENDOR_PRODUCTS - company-specific product queries
        self.templates[RouteId.VENDOR_PRODUCTS] = QueryTemplate(
            route_id=RouteId.VENDOR_PRODUCTS,
            description="Find vendor-specific products and implementations",
            param_schema={
                "organizations": "list[str]",
                "topics": "list[str]",
                "limit": "int"
            },
            cypher="""
            // Find resources that mention both the organization and topic
            MATCH (o:Organization)
            WHERE o.name IN $organizations OR o.org_id IN $organizations
            
            MATCH (r:Resource)-[:MENTIONS]->(o)
            WHERE r.title =~ '(?i).*(product|chip|chipset|solution|platform|system|device|equipment|implementation).*'
            
            // Filter by topics if specified
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            WHERE $topics IS NULL OR size($topics) = 0 OR t.name IN $topics OR ANY(alias IN t.aliases WHERE alias IN $topics)
            
            WITH r, o,
                 collect(DISTINCT t.name)[0..5] as topics
            WHERE size(topics) > 0 OR ($topics IS NULL OR size($topics) = 0)
            ORDER BY r.publish_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                r.category as type,
                o.name as organization,
                topics
            LIMIT $limit
            """
        )
        
        # ISSUE_TRACKING - problems, bugs, limitations
        self.templates[RouteId.ISSUE_TRACKING] = QueryTemplate(
            route_id=RouteId.ISSUE_TRACKING,
            description="Find issues and problems with a technology",
            param_schema={
                "topics": "list[str]",
                "limit": "int"
            },
            cypher="""
            MATCH (t:Topic)
            WHERE ($topics IS NULL OR size($topics) = 0 OR t.name IN $topics OR t.topic_id IN $topics OR ANY(alias IN t.aliases WHERE alias IN $topics))
            
            // Find resources with critical/concerned stance or issue keywords
            MATCH (r:Resource)-[rt:RELATES_TO]->(t)
            WHERE (rt.stance IN ['critical', 'concerned']
                   OR r.title =~ '(?i).*(issue|problem|bug|limitation|challenge|concern|vulnerability|flaw|weakness).*')
            
            OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
            
            WITH r, t, rt,
                 collect(DISTINCT o.name)[0..3] as orgs
            ORDER BY r.publish_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                r.category as type,
                t.name as topic,
                rt.stance as stance,
                orgs as organizations
            LIMIT $limit
            """
        )
        
        # REGULATORY_INFO - regulations, compliance, certification
        self.templates[RouteId.REGULATORY_INFO] = QueryTemplate(
            route_id=RouteId.REGULATORY_INFO,
            description="Find regulatory and compliance information",
            param_schema={
                "topics": "list[str]",
                "limit": "int"
            },
            cypher="""
            MATCH (t:Topic)
            WHERE ($topics IS NULL OR size($topics) = 0 OR t.name IN $topics OR t.topic_id IN $topics OR ANY(alias IN t.aliases WHERE alias IN $topics))
            
            MATCH (r:Resource)-[:RELATES_TO]->(t)
            WHERE r.title =~ '(?i).*(regulation|compliance|certification|requirement|rule|legal|mandate|policy|standard).*'
            
            // Prefer documents from regulatory bodies
            OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
            WHERE o.org_type IN ['government', 'regulatory', 'standards body']
            
            WITH r, t,
                 collect(DISTINCT o.name)[0..3] as regulatory_orgs,
                 CASE WHEN size(collect(DISTINCT o)) > 0 THEN 1.5 ELSE 1.0 END as boost
            ORDER BY boost DESC, r.publish_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                r.category as type,
                t.name as topic,
                regulatory_orgs as organizations
            LIMIT $limit
            """
        )
        
        # IETF_WG_UPDATES - recent content from IETF working group datasources
        self.templates[RouteId.IETF_WG_UPDATES] = QueryTemplate(
            route_id=RouteId.IETF_WG_UPDATES,
            description="Get recent IETF working group updates, drafts, and RFCs",
            param_schema={
                "excluded_datasources": "list[str]",
                "wg_datasource_ids": "list[str] (specific WG datasource IDs, e.g. ietf_wg_quic)",
                "lookback_date": "str (ISO date string, e.g. '2025-12-20')",
            },
            cypher="""
MATCH (r:Resource)-[:INGESTED_FROM]->(ds:DataSource)
WHERE ds.source_type = 'ietf_wg'
  AND (size($excluded_datasources) = 0 OR NOT r.datasource_id IN $excluded_datasources)
  AND r.publish_date >= $lookback_date
  AND (
    size($wg_datasource_ids) = 0
    OR r.datasource_id IN $wg_datasource_ids
  )
WITH r, ds
ORDER BY r.publish_date DESC
LIMIT 20
OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
RETURN r.url AS url,
       r.title AS title,
       r.summary AS summary,
       r.publish_date AS publish_date,
       r.category AS category,
       r.datasource_id AS datasource_id,
       ds.display_name AS source_name,
       ds.area_name AS area_name,
       collect(DISTINCT t.name)[0..5] AS topics
"""
        )

        # IETF_MEETING_AGENDA - events and materials for a specific IETF meeting number
        self.templates[RouteId.IETF_MEETING_AGENDA] = QueryTemplate(
            route_id=RouteId.IETF_MEETING_AGENDA,
            description="Get agenda, sessions, and materials for an IETF meeting by number",
            param_schema={
                "excluded_datasources": "list[str]",
                "meeting_number": "str (numeric meeting number, e.g. '120')",
                "meeting_number_str": "str (formatted, e.g. 'IETF 120')",
            },
            cypher="""
MATCH (e:Event)
WHERE e.datasource_id STARTS WITH 'ietf_wg_'
  AND (size($excluded_datasources) = 0 OR NOT e.datasource_id IN $excluded_datasources)
  AND (
    $meeting_number = ''
    OR toLower(e.name) CONTAINS toLower($meeting_number_str)
    OR e.name CONTAINS $meeting_number_str
  )
WITH e
ORDER BY e.start_date DESC
LIMIT 10
OPTIONAL MATCH (e)<-[:RELATES_TO_EVENT]-(r:Resource)
RETURN e.name AS event_name,
       e.url AS event_url,
       e.start_date AS start_date,
       e.end_date AS end_date,
       e.datasource_id AS datasource_id,
       collect(DISTINCT {title: r.title, url: r.url, category: r.category})[0..10] AS materials
ORDER BY e.start_date DESC
"""
        )

        # GENERIC_SEARCH - fallback for unmatched queries with full-text + KG-based scoring
        self.templates[RouteId.GENERIC_SEARCH] = QueryTemplate(
            route_id=RouteId.GENERIC_SEARCH,
            description="Generic search with full-text matching and KG scoring",
            param_schema={
                "query_text": "str (optional - for full-text search)",
                "workgroups": "list[str]",
                "start_date": "str (ISO format, optional)",
                "end_date": "str (ISO format, optional)",
                "limit": "int"
            },
            cypher="""
            // Generic search with multiple matching strategies:
            // 1. Full-text search on query_text (title/summary)
            // 2. Topic-based search if topics provided
            // 3. Fallback to graph-based scoring
            MATCH (r:Resource)
            WHERE (($query_text IS NULL OR 
                    toLower(r.title) CONTAINS toLower($query_text) OR 
                    (r.summary IS NOT NULL AND toLower(r.summary) CONTAINS toLower($query_text))) OR
                   ($topics IS NOT NULL AND size($topics) > 0))
              AND ($topics IS NULL OR size($topics) = 0 OR
                   EXISTS {
                       MATCH (r)-[:RELATES_TO]->(t:Topic)
                       WHERE any(topic IN $topics WHERE toLower(t.name) = toLower(topic) OR any(alias IN t.aliases WHERE toLower(alias) = toLower(topic)))
                   } OR
                   any(topic IN $topics WHERE 
                       toLower(r.title) CONTAINS toLower(topic) OR 
                       toLower(coalesce(r.summary, '')) CONTAINS toLower(topic)
                   ))
            
            // Calculate effective date with robust fallback
            WITH r, CASE WHEN r.publish_date IS NOT NULL AND NOT r.publish_date IN ['', 'unknown'] THEN datetime(r.publish_date) WHEN r.created_at IS NOT NULL THEN datetime(r.created_at) WHEN r.scraped_at IS NOT NULL THEN datetime(r.scraped_at) ELSE datetime('1970-01-01') END as effective_date
            
            // Filter by date range if provided
            WITH r, effective_date
            WHERE $start_date IS NULL OR effective_date >= datetime($start_date)
            
            WITH r, effective_date
            WHERE $end_date IS NULL OR effective_date <= datetime($end_date)
            
            // Filter by datasource (workgroup) if specified
            WITH r, effective_date
            WHERE $workgroups IS NULL OR size($workgroups) = 0 
               OR EXISTS {
                   MATCH (r)-[:INGESTED_FROM]->(ds:DataSource)
                   WHERE ds.datasource_id IN $workgroups
               }
            
            // Get graph richness metrics
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
            OPTIONAL MATCH (r)-[:MENTIONS]->(p:Person)
            
            WITH r, effective_date,
                 count(DISTINCT t) as topic_count,
                 count(DISTINCT o) as org_count,
                 count(DISTINCT p) as person_count,
                 collect(DISTINCT t.name)[0..5] as topics,
                 collect(DISTINCT o.name)[0..3] as orgs,
                 // Text match bonus: higher if query_text found in title vs summary
                 // Bonus for definition/explanation content types
                 (CASE WHEN $query_text IS NULL THEN 0 WHEN toLower(r.title) CONTAINS toLower($query_text) THEN 15 WHEN r.summary IS NOT NULL AND toLower(r.summary) CONTAINS toLower($query_text) THEN 8 ELSE 0 END) + (CASE WHEN r.category IN ['specification', 'standard', 'whitepaper', 'technical_report'] THEN 5 ELSE 0 END) as text_match_score,
                 // Exact topic term match bonus: prioritize docs that mention the searched topic terms (e.g., "802.11ax" vs just Wi-Fi 6)
                 reduce(bonus = 0, topic IN $topics | bonus + CASE WHEN toLower(r.title) CONTAINS toLower(topic) THEN 20 WHEN r.summary IS NOT NULL AND toLower(r.summary) CONTAINS toLower(topic) THEN 10 ELSE 0 END) as topic_term_bonus
            
            // Hybrid scoring: text match + topic term match + graph connectivity + recency (with null-safe date handling)
            WITH r, effective_date, topic_count, org_count, person_count, topics, orgs, text_match_score, topic_term_bonus,
                 (topic_count * 2 + org_count + person_count) as graph_score,
                 CASE WHEN effective_date >= datetime() - duration({days: 180}) THEN 5 WHEN effective_date >= datetime() - duration({days: 365}) THEN 3 WHEN effective_date >= datetime() - duration({days: 730}) THEN 1 ELSE 0 END as recency_bonus
            
            // Score = exact topic term match + text relevance + graph richness + recency bonus
            WITH r, topics, orgs, text_match_score, topic_term_bonus, graph_score, recency_bonus, topic_term_bonus + text_match_score + (graph_score * 0.5) + recency_bonus as hybrid_score
            
            ORDER BY hybrid_score DESC, effective_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                r.category as type,
                topics,
                orgs as organizations
            LIMIT $limit
            """
        )
        
        logger.info(f"Registered {len(self.templates)} query templates")
