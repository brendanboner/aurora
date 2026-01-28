"""Query template registry for fast Cypher retrieval.

Maps route IDs to parameterized Cypher queries with schemas
and post-processing logic.
"""

import logging
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
        if plan.relative_days:
            params["relative_days"] = plan.relative_days
        
        # Entity parameters
        if plan.workgroups:
            params["workgroups"] = plan.workgroups
        if plan.topics:
            params["topics"] = plan.topics
        if plan.organizations:
            params["organizations"] = plan.organizations
        if plan.people:
            params["people"] = plan.people
        
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
        
        # Limits
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
        
        # WORKGROUP_WEEKLY_RECAP - fetch weekly rollup
        self.templates[RouteId.WORKGROUP_WEEKLY_RECAP] = QueryTemplate(
            route_id=RouteId.WORKGROUP_WEEKLY_RECAP,
            description="Get weekly recap rollup for workgroup",
            param_schema={
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "workgroups": "list[str]",
                "limit": "int"
            },
            cypher="""
            // Match workgroups (by ID or name)
            MATCH (wg:WorkGroup)
            WHERE ($workgroups IS NULL OR size($workgroups) = 0 
                   OR wg.id IN $workgroups 
                   OR wg.name IN $workgroups)
            
            // Find weekly rollup in date range
            OPTIONAL MATCH (wg)-[:HAS_ROLLUP]->(r:Rollup)
            WHERE r.type = 'week'
              AND ($start_date IS NULL OR datetime(r.start) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(r.end) <= datetime($end_date))
            
            // If no rollup, get recent events instead
            OPTIONAL MATCH (wg)<-[:BELONGS_TO]-(e:Event)
            WHERE ($start_date IS NULL OR datetime(e.startTime) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(e.startTime) <= datetime($end_date))
            
            // Return rollup if available, else thin event data
            WITH wg, r, collect(DISTINCT e)[..$limit] as events
            
            RETURN 
                wg.id as workgroup_id,
                wg.name as workgroup_name,
                r.id as rollup_id,
                r.summary as rollup_summary,
                r.keyEvents as key_events,
                r.keyDecisions as key_decisions,
                r.topTopics as top_topics,
                r.links as links,
                r.start as rollup_start,
                r.end as rollup_end,
                CASE WHEN r IS NOT NULL THEN 'rollup' ELSE 'events' END as source_type,
                [event IN events | {
                    id: event.id,
                    title: event.name,
                    startTime: event.startTime,
                    endTime: event.endTime,
                    url: event.url
                }] as events
            LIMIT $limit
            """
        )
        
        # WORKGROUP_DAILY_RECAP - fetch daily rollup
        self.templates[RouteId.WORKGROUP_DAILY_RECAP] = QueryTemplate(
            route_id=RouteId.WORKGROUP_DAILY_RECAP,
            description="Get daily recap rollup for workgroup",
            param_schema={
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "workgroups": "list[str]",
                "limit": "int"
            },
            cypher="""
            MATCH (wg:WorkGroup)
            WHERE ($workgroups IS NULL OR size($workgroups) = 0 
                   OR wg.id IN $workgroups 
                   OR wg.name IN $workgroups)
            
            OPTIONAL MATCH (wg)-[:HAS_ROLLUP]->(r:Rollup)
            WHERE r.type = 'day'
              AND ($start_date IS NULL OR datetime(r.start) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(r.end) <= datetime($end_date))
            
            OPTIONAL MATCH (wg)<-[:BELONGS_TO]-(e:Event)
            WHERE ($start_date IS NULL OR datetime(e.startTime) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(e.startTime) <= datetime($end_date))
            
            WITH wg, r, collect(DISTINCT e)[..$limit] as events
            
            RETURN 
                wg.id as workgroup_id,
                wg.name as workgroup_name,
                r.id as rollup_id,
                r.summary as rollup_summary,
                r.keyEvents as key_events,
                r.keyDecisions as key_decisions,
                r.topTopics as top_topics,
                r.links as links,
                r.start as rollup_start,
                r.end as rollup_end,
                CASE WHEN r IS NOT NULL THEN 'rollup' ELSE 'events' END as source_type,
                [event IN events | {
                    id: event.id,
                    title: event.name,
                    startTime: event.startTime,
                    endTime: event.endTime,
                    url: event.url
                }] as events
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
            WITH datetime() - duration({days: coalesce($relative_days, 14)}) as doc_threshold
            
            // Match workgroups
            MATCH (wg:WorkGroup)
            WHERE ($workgroups IS NULL OR size($workgroups) = 0 
                   OR wg.id IN $workgroups 
                   OR wg.name IN $workgroups)
            
            // Get recently PUBLISHED/UPDATED documents (regardless of event dates mentioned)
            OPTIONAL MATCH (wg)<-[:MENTIONS]-(r:Resource)
            WHERE datetime(r.publish_date) >= doc_threshold
            
            // Get events mentioned in these recent documents (can be future or past events)
            OPTIONAL MATCH (r)-[:MENTIONS]->(e:Event)
            
            // Optional: filter by topics
            WITH wg, e, r, doc_threshold
            WHERE ($topics IS NULL OR size($topics) = 0 
                   OR EXISTS {
                       MATCH (r)-[:RELATES_TO]->(t:Topic)
                       WHERE t.name IN $topics
                   })
            
            WITH wg, 
                 collect(DISTINCT e)[..$limit/2] as events,
                 collect(DISTINCT r)[..$limit/2] as docs
            
            RETURN 
                wg.id as workgroup_id,
                wg.name as workgroup_name,
                [event IN events | {
                    type: 'event',
                    id: event.id,
                    title: event.name,
                    startTime: event.startTime,
                    url: event.url
                }] as recent_events,
                [doc IN docs | {
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
            WHERE toLower(r.category) = 'decision'
              AND ($start_date IS NULL OR datetime(r.publish_date) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(r.publish_date) <= datetime($end_date))
            
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
            // Get resources in date range
            MATCH (r:Resource)-[rt:RELATES_TO]->(t:Topic)
            WHERE ($start_date IS NULL OR datetime(r.publish_date) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(r.publish_date) <= datetime($end_date))
              AND rt.relevance >= 0.5
              AND ($topics IS NULL OR size($topics) = 0 OR t.name IN $topics)
            
            // Count mentions per topic
            WITH t, count(DISTINCT r) as mention_count, collect(DISTINCT r)[..10] as resources
            ORDER BY mention_count DESC
            
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
            WHERE ($people IS NULL OR size($people) = 0 OR p.name IN $people)
              AND ($start_date IS NULL OR datetime(r.publish_date) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(r.publish_date) <= datetime($end_date))
            
            // Optional topic filter
            WITH r, p
            WHERE ($topics IS NULL OR size($topics) = 0
                   OR EXISTS {
                       MATCH (r)-[:RELATES_TO]->(t:Topic)
                       WHERE t.name IN $topics
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
                       MATCH (e)-[:BELONGS_TO]->(wg:WorkGroup)
                       WHERE wg.id IN $workgroups OR wg.name IN $workgroups
                   })
            
            // Optional topic filter (via related documents)
            WITH e
            WHERE ($topics IS NULL OR size($topics) = 0
                   OR EXISTS {
                       MATCH (e)<-[:RELATES_TO]-(r:Resource)-[:RELATES_TO]->(t:Topic)
                       WHERE t.name IN $topics
                   })
            
            OPTIONAL MATCH (e)-[:BELONGS_TO]->(wg:WorkGroup)
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
        
        # UPCOMING_EVENTS - future events
        self.templates[RouteId.UPCOMING_EVENTS] = QueryTemplate(
            route_id=RouteId.UPCOMING_EVENTS,
            description="Get upcoming events (including those mentioned in recent documents)",
            param_schema={
                "workgroups": "list[str]",
                "topics": "list[str]",
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "limit": "int"
            },
            cypher="""
            // Find future events (Event nodes)
            MATCH (e:Event)
            WHERE datetime(e.startTime) >= datetime()
              AND ($start_date IS NULL OR datetime(e.startTime) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(e.startTime) <= datetime($end_date))
            
            // Optional workgroup filter
            WITH e
            WHERE ($workgroups IS NULL OR size($workgroups) = 0
                   OR EXISTS {
                       MATCH (e)-[:BELONGS_TO]->(wg:WorkGroup)
                       WHERE wg.id IN $workgroups OR wg.name IN $workgroups
                   })
            
            // Optional topic filter (topics mentioned in event or related documents)
            WITH e
            WHERE ($topics IS NULL OR size($topics) = 0
                   OR EXISTS {
                       // Check if event relates to topics directly
                       MATCH (e)-[:RELATES_TO]->(t:Topic)
                       WHERE t.name IN $topics
                   }
                   OR EXISTS {
                       // Check if recent documents mention both the event and the topic
                       MATCH (r:Resource)-[:MENTIONS]->(e)
                       MATCH (r)-[:RELATES_TO]->(t:Topic)
                       WHERE t.name IN $topics
                         AND datetime(r.publish_date) >= datetime() - duration({days: 180})
                   })
            
            OPTIONAL MATCH (e)-[:BELONGS_TO]->(wg:WorkGroup)
            OPTIONAL MATCH (e)-[:RELATES_TO]->(t:Topic)
            OPTIONAL MATCH (r:Resource)-[:MENTIONS]->(e)
            WHERE datetime(r.publish_date) >= datetime() - duration({days: 180})
            
            WITH e, wg,
                 collect(DISTINCT t.name)[..5] as topics,
                 collect(DISTINCT r.title)[..3] as mentioning_documents
            ORDER BY e.startTime ASC
            
            RETURN 
                e.id as event_id,
                e.name as title,
                e.startTime as start_time,
                e.endTime as end_time,
                e.location as location,
                e.url as url,
                wg.name as workgroup,
                topics,
                mentioning_documents
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
            WITH CASE 
                WHEN $start_date IS NULL 
                THEN datetime() - duration({days: coalesce($relative_days, 30)})
                ELSE datetime($start_date)
            END as threshold_start,
            CASE
                WHEN $end_date IS NULL
                THEN datetime()
                ELSE datetime($end_date)
            END as threshold_end
            
            MATCH (e:Event)
            WHERE datetime(e.startTime) >= threshold_start
              AND datetime(e.startTime) <= threshold_end
              AND ($workgroups IS NULL OR size($workgroups) = 0
                   OR EXISTS {
                       MATCH (e)-[:BELONGS_TO]->(wg:WorkGroup)
                       WHERE wg.id IN $workgroups OR wg.name IN $workgroups
                   })
            
            OPTIONAL MATCH (e)-[:BELONGS_TO]->(wg:WorkGroup)
            
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
            WHERE toLower(r.category) = 'decision'
              AND datetime(r.publish_date) >= threshold
            
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
            MATCH (r:Resource)-[rt:RELATES_TO]->(t:Topic)
            WHERE t.name IN $topics
              AND rt.relevance >= 0.5
              AND ($start_date IS NULL OR datetime(r.publish_date) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(r.publish_date) <= datetime($end_date))
            
            // Count total topics for this resource (specificity calculation)
            WITH r, t, rt.relevance as base_relevance
            MATCH (r)-[:RELATES_TO]->(all_topics:Topic)
            WITH r, t, base_relevance, count(DISTINCT all_topics) as topic_count
            
            // Calculate specificity score (fewer topics = more specific = higher score)
            WITH r, t, base_relevance, topic_count,
                 CASE 
                   WHEN topic_count = 1 THEN 1.0      // Highly specific
                   WHEN topic_count = 2 THEN 0.9      // Very focused
                   WHEN topic_count <= 5 THEN 0.7     // Focused
                   ELSE 0.5                           // Broad/general
                 END as specificity_score
            
            // Calculate content type boost (whitepapers > specs > meeting minutes)
            WITH r, t, base_relevance, topic_count, specificity_score,
                 CASE r.category
                   WHEN 'whitepaper' THEN 1.3         // Whitepapers are comprehensive
                   WHEN 'specification' THEN 1.2      // Specs are authoritative
                   WHEN 'technical_report' THEN 1.1   // Reports are detailed
                   WHEN 'standard' THEN 1.2           // Standards are definitive
                   WHEN 'draft' THEN 1.0              // Drafts are current
                   WHEN 'presentation' THEN 0.8       // Presentations are summaries
                   WHEN 'meeting_minutes' THEN 0.5    // Minutes are activity logs
                   WHEN 'email' THEN 0.4              // Emails are fragments
                   ELSE 0.8                           // Other content
                 END as content_type_boost
            
            // Calculate recency score (newer content gets boost for "what is" queries)
            WITH r, t, base_relevance, topic_count, specificity_score, content_type_boost,
                 CASE
                   WHEN r.publish_date IS NOT NULL AND datetime(r.publish_date) >= datetime() - duration({days: 180}) THEN 1.2  // Last 6 months
                   WHEN r.publish_date IS NOT NULL AND datetime(r.publish_date) >= datetime() - duration({days: 365}) THEN 1.1  // Last year
                   WHEN r.publish_date IS NOT NULL AND datetime(r.publish_date) >= datetime() - duration({days: 730}) THEN 1.0  // Last 2 years
                   ELSE 0.9                                                         // Older content or no date
                 END as recency_score
            
            // Calculate final KG relevance score
            WITH r, t, base_relevance, topic_count, specificity_score, content_type_boost, recency_score,
                 (base_relevance * 0.4 +              // Base semantic relevance (40%)
                  specificity_score * 0.3 +           // Topic specificity (30%)
                  content_type_boost * 0.2 +          // Content type quality (20%)
                  recency_score * 0.1                 // Recency factor (10%)
                 ) as kg_score
            
            // Normalize kg_score to 0-1 range for consistency
            WITH r, t, base_relevance, topic_count, kg_score,
                 kg_score / 2.0 as normalized_kg_score
            
            ORDER BY normalized_kg_score DESC, r.publish_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                r.category as type,
                t.name as topic,
                round(normalized_kg_score * 100) / 100.0 as relevance_score,
                topic_count as topic_breadth
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
                "limit": "int"
            },
            cypher="""
            WITH datetime() - duration({days: coalesce($relative_days, 14)}) as threshold
            
            MATCH (r:Resource)
            WHERE datetime(r.publish_date) >= threshold
              AND ($workgroups IS NULL OR size($workgroups) = 0
                   OR EXISTS {
                       MATCH (r)-[:MENTIONS]->(o:Organization)
                       WHERE o.name IN $workgroups OR o.org_id IN $workgroups
                   })
            
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            WHERE t.relevance >= 0.5
            
            WITH r,
                 collect(DISTINCT t.name)[..5] as topics
            ORDER BY r.publish_date DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                r.category as type,
                topics
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
            WHERE t.name IN $topics
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
            WHERE t.name IN $topics
            
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
        
        # WORKGROUP_MONTHLY_SUMMARY - monthly rollup
        self.templates[RouteId.WORKGROUP_MONTHLY_SUMMARY] = QueryTemplate(
            route_id=RouteId.WORKGROUP_MONTHLY_SUMMARY,
            description="Get monthly summary for workgroup",
            param_schema={
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "workgroups": "list[str]",
                "limit": "int"
            },
            cypher="""
            MATCH (wg:WorkGroup)
            WHERE ($workgroups IS NULL OR size($workgroups) = 0 
                   OR wg.id IN $workgroups 
                   OR wg.name IN $workgroups)
            
            // Try to find monthly rollup
            OPTIONAL MATCH (wg)-[:HAS_ROLLUP]->(r:Rollup)
            WHERE r.type = 'month'
              AND ($start_date IS NULL OR datetime(r.start) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(r.end) <= datetime($end_date))
            
            // If no rollup, aggregate from events
            OPTIONAL MATCH (wg)<-[:BELONGS_TO]-(e:Event)
            WHERE ($start_date IS NULL OR datetime(e.startTime) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(e.startTime) <= datetime($end_date))
            
            WITH wg, r, collect(DISTINCT e)[..$limit] as events
            
            RETURN 
                wg.id as workgroup_id,
                wg.name as workgroup_name,
                r.summary as rollup_summary,
                r.keyEvents as key_events,
                r.topTopics as top_topics,
                [event IN events | {
                    id: event.id,
                    title: event.name,
                    date: event.startTime
                }] as recent_events
            LIMIT $limit
            """
        )
        
        # ORGANIZATION_ACTIVITY - organization activity summary
        self.templates[RouteId.ORGANIZATION_ACTIVITY] = QueryTemplate(
            route_id=RouteId.ORGANIZATION_ACTIVITY,
            description="Get organization activity",
            param_schema={
                "organizations": "list[str]",
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "limit": "int"
            },
            cypher="""
            MATCH (o:Organization)
            WHERE o.name IN $organizations OR o.org_id IN $organizations
            
            MATCH (o)<-[:MENTIONS]-(r:Resource)
            WHERE ($start_date IS NULL OR datetime(r.publish_date) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(r.publish_date) <= datetime($end_date))
            
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            WHERE t.relevance >= 0.5
            
            WITH o, r,
                 collect(DISTINCT t.name)[..5] as topics
            ORDER BY r.publish_date DESC
            
            RETURN 
                o.org_id as org_id,
                o.name as org_name,
                collect({
                    id: r.url_hash,
                    title: r.title,
                    date: r.publish_date,
                    url: r.url,
                    topics: topics
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
            WHERE datetime(r.publish_date) >= doc_threshold
              AND ($start_date IS NULL OR datetime(r.publish_date) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(r.publish_date) <= datetime($end_date))
              // Exclude previously used content
              AND NOT r.url_hash IN $exclude_ids
            
            // Filter by topics or organizations
            WITH r, doc_threshold
            WHERE (
                ($topics IS NOT NULL AND size($topics) > 0 AND EXISTS {
                    MATCH (r)-[:RELATES_TO]->(t:Topic)
                    WHERE t.name IN $topics
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
                 CASE 
                    WHEN size(collect(DISTINCT t)) = 0 THEN 0.5
                    WHEN size(collect(DISTINCT t)) <= 3 THEN 1.0
                    WHEN size(collect(DISTINCT t)) <= 6 THEN 0.8
                    ELSE 0.6
                 END as specificity_score,
                 // Recency: exponential decay with 7-day half-life
                 CASE
                    WHEN r.publish_date IS NULL THEN 0.5
                    ELSE exp(-duration.between(datetime(r.publish_date), datetime()).days / 7.0)
                 END as recency_score,
                 // Importance boost
                 CASE toLower(r.importance)
                    WHEN 'high' THEN 1.2
                    WHEN 'critical' THEN 1.5
                    ELSE 1.0
                 END as importance_multiplier
            
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
            WHERE t.name IN $topics OR t.topic_id IN $topics
            
            WITH collect(t) as topics_to_compare
            WHERE size(topics_to_compare) >= 2
            
            // Get resources for each topic
            UNWIND topics_to_compare as topic
            MATCH (r:Resource)-[rt:RELATES_TO]->(topic)
            WHERE rt.relevance >= 0.5
              AND ($start_date IS NULL OR datetime(r.publish_date) >= datetime($start_date))
            
            // Collect organizations and key attributes
            OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
            
            WITH topic,
                 count(DISTINCT r) as resource_count,
                 collect(DISTINCT r.publish_date)[0..5] as recent_dates,
                 collect(DISTINCT o.name)[0..10] as related_orgs,
                 collect(DISTINCT {
                     id: r.url_hash,
                     title: r.title,
                     date: r.publish_date,
                     url: r.url,
                     summary: r.summary
                 })[0..($limit/size(topics_to_compare))] as sample_resources
            
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
            WHERE ($topics IS NULL OR size($topics) = 0 OR t.name IN $topics OR t.topic_id IN $topics)
            
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
            WHERE ($topics IS NULL OR size($topics) = 0 OR t.name IN $topics OR t.topic_id IN $topics)
            
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
            WHERE ($topics IS NULL OR size($topics) = 0 OR t.name IN $topics OR t.topic_id IN $topics)
            
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
            
            // Get recent resources mentioning them
            OPTIONAL MATCH (r:Resource)-[:MENTIONS]->(p)
            WHERE r.publish_date IS NOT NULL
            
            WITH p, o, 
                 collect(DISTINCT t.name)[0..10] as topics,
                 collect(DISTINCT {
                     id: r.url_hash,
                     title: r.title,
                     date: r.publish_date,
                     url: r.url
                 })[0..10] as recent_resources
            ORDER BY r.publish_date DESC
            
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
            WHERE $topics IS NULL OR size($topics) = 0 OR t.name IN $topics
            
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
            WHERE ($topics IS NULL OR size($topics) = 0 OR t.name IN $topics OR t.topic_id IN $topics)
            
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
            WHERE $topics IS NULL OR size($topics) = 0 OR t.name IN $topics
            
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
            WHERE ($topics IS NULL OR size($topics) = 0 OR t.name IN $topics OR t.topic_id IN $topics)
            
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
            WHERE ($topics IS NULL OR size($topics) = 0 OR t.name IN $topics OR t.topic_id IN $topics)
            
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
        
        # GENERIC_SEARCH - fallback for unmatched queries with KG-based hybrid scoring
        self.templates[RouteId.GENERIC_SEARCH] = QueryTemplate(
            route_id=RouteId.GENERIC_SEARCH,
            description="Generic search fallback using hybrid KG scoring",
            param_schema={
                "limit": "int"
            },
            cypher="""
            // Use KG structure for relevance even without specific entities
            // Find recently published resources with rich graph connections
            MATCH (r:Resource)
            WHERE r.publish_date IS NOT NULL
              AND r.summary IS NOT NULL
            
            // Get graph richness metrics
            OPTIONAL MATCH (r)-[:RELATES_TO]->(t:Topic)
            OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
            OPTIONAL MATCH (r)-[:MENTIONS]->(p:Person)
            
            WITH r,
                 count(DISTINCT t) as topic_count,
                 count(DISTINCT o) as org_count,
                 count(DISTINCT p) as person_count,
                 collect(DISTINCT t.name)[0..5] as topics,
                 collect(DISTINCT o.name)[0..3] as orgs
            
            // Hybrid scoring: recency + graph connectivity
            WITH r, topic_count, org_count, person_count, topics, orgs,
                 (topic_count * 2 + org_count + person_count) as graph_score,
                 duration.between(datetime(r.publish_date), datetime()).days as days_old
            
            // Score = graph richness - age penalty
            WITH r, topics, orgs, graph_score,
                 graph_score - (days_old / 30.0) as hybrid_score
            
            ORDER BY hybrid_score DESC, r.publish_date DESC
            
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
