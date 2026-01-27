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
        
        # Date parameters
        if plan.start_date:
            params["start_date"] = plan.start_date.isoformat()
        if plan.end_date:
            params["end_date"] = plan.end_date.isoformat()
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
            description="Get recent updates (docs + events) for workgroup",
            param_schema={
                "workgroups": "list[str]",
                "topics": "list[str]",
                "relative_days": "int",
                "limit": "int"
            },
            cypher="""
            // Calculate date threshold
            WITH datetime() - duration({days: coalesce($relative_days, 7)}) as threshold
            
            // Match workgroups
            MATCH (wg:WorkGroup)
            WHERE ($workgroups IS NULL OR size($workgroups) = 0 
                   OR wg.id IN $workgroups 
                   OR wg.name IN $workgroups)
            
            // Get recent events
            OPTIONAL MATCH (wg)<-[:BELONGS_TO]-(e:Event)
            WHERE datetime(e.startTime) >= threshold
            
            // Get recent documents related to workgroup
            OPTIONAL MATCH (wg)<-[:MENTIONS]-(r:Resource)
            WHERE datetime(r.publish_date) >= threshold
            
            // Optional: filter by topics
            WITH wg, e, r, threshold
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
            description="Get upcoming events",
            param_schema={
                "workgroups": "list[str]",
                "start_date": "str (ISO date)",
                "limit": "int"
            },
            cypher="""
            MATCH (e:Event)
            WHERE datetime(e.startTime) >= datetime()
              AND ($workgroups IS NULL OR size($workgroups) = 0
                   OR EXISTS {
                       MATCH (e)-[:BELONGS_TO]->(wg:WorkGroup)
                       WHERE wg.id IN $workgroups OR wg.name IN $workgroups
                   })
              AND ($start_date IS NULL OR datetime(e.startTime) <= datetime($start_date))
            
            OPTIONAL MATCH (e)-[:BELONGS_TO]->(wg:WorkGroup)
            
            WITH e, wg
            ORDER BY e.startTime ASC
            
            RETURN 
                e.id as event_id,
                e.name as title,
                e.startTime as start_time,
                e.endTime as end_time,
                e.location as location,
                e.url as url,
                wg.name as workgroup
            LIMIT $limit
            """
        )
        
        # PAST_EVENTS - recent past events
        self.templates[RouteId.PAST_EVENTS] = QueryTemplate(
            route_id=RouteId.PAST_EVENTS,
            description="Get past events",
            param_schema={
                "workgroups": "list[str]",
                "start_date": "str (ISO date)",
                "end_date": "str (ISO date)",
                "limit": "int"
            },
            cypher="""
            MATCH (e:Event)
            WHERE datetime(e.startTime) < datetime()
              AND ($start_date IS NULL OR datetime(e.startTime) >= datetime($start_date))
              AND ($end_date IS NULL OR datetime(e.startTime) <= datetime($end_date))
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
        
        # DOCUMENTS_BY_TOPIC - documents on specific topics
        self.templates[RouteId.DOCUMENTS_BY_TOPIC] = QueryTemplate(
            route_id=RouteId.DOCUMENTS_BY_TOPIC,
            description="Get documents by topic",
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
            
            OPTIONAL MATCH (r)-[:MENTIONS]->(o:Organization)
            
            WITH r, t,
                 count(DISTINCT o) as org_mentions
            ORDER BY r.publish_date DESC, rt.relevance DESC
            
            RETURN 
                r.url_hash as id,
                r.title as title,
                r.summary as summary,
                r.publish_date as date,
                r.url as url,
                r.category as type,
                t.name as topic
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
        
        logger.info(f"Registered {len(self.templates)} query templates")
