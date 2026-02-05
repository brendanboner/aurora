"""Adapter to convert CreatorAgent to Oracle routing format.

Bridges creator agents with Oracle's fast engine for content discovery,
leveraging rollups, query templates, and personalization infrastructure.
"""

import logging
from typing import Optional, List, Tuple, Dict, Any
from datetime import date, timedelta

from src.models.route_plan import RoutePlan, RouteId, DetailLevel
from src.services.personalization import UserPreferences

logger = logging.getLogger(__name__)


class CreatorAgentPreferences:
    """Agent configuration that maps to UserPreferences."""
    
    def __init__(
        self,
        agent_id: str,
        agent_name: str,
        expertise_topics: List[str],
        expertise_organisations: List[str],
        cadence_days: Optional[int] = None,
        discovery_tolerance: float = 0.5,
        last_content_ids: Optional[List[str]] = None
    ):
        """
        Initialize agent preferences.
        
        Args:
            agent_id: Unique agent identifier
            agent_name: Display name for agent
            expertise_topics: Topics the agent focuses on
            expertise_organisations: Organizations the agent tracks
            cadence_days: Days between content generation (7=weekly, 1=daily, 30=monthly)
            discovery_tolerance: 0.0=strict focus, 1.0=exploratory (affects min relevance)
            last_content_ids: IDs of content used in last generation (for diversity)
        """
        self.agent_id = agent_id
        self.agent_name = agent_name
        self.expertise_topics = expertise_topics or []
        self.expertise_organisations = expertise_organisations or []
        self.cadence_days = cadence_days or 7
        self.discovery_tolerance = discovery_tolerance
        self.last_content_ids = last_content_ids or []
    
    def to_user_preferences(self) -> UserPreferences:
        """Convert to UserPreferences format for Oracle routing."""
        # Create a UserPreferences object using the agent as a "user"
        # This allows agents to leverage all personalization infrastructure
        prefs = UserPreferences.__new__(UserPreferences)
        prefs.user_id = f"agent:{self.agent_id}"
        prefs.topics = self.expertise_topics
        prefs.organisations = self.expertise_organisations
        prefs.people = []  # Agents typically don't track specific people
        return prefs


class AgentRouter:
    """Routes agent content requests to appropriate Oracle templates."""
    
    def __init__(self):
        """Initialize agent router."""
        logger.info("Initialized AgentRouter for creator agent integration")
    
    def route_for_agent(
        self,
        agent_prefs: CreatorAgentPreferences,
        perspective: Optional[str] = None
    ) -> Tuple[RouteId, RoutePlan, float]:
        """
        Determine optimal route and plan for agent content discovery.
        
        Args:
            agent_prefs: Agent preferences and configuration
            perspective: Optional angle/perspective for content ("news", "analysis", "trends", etc.)
            
        Returns:
            Tuple of (RouteId, RoutePlan, confidence)
        """
        # Determine route based on cadence
        route_id = self._select_route_by_cadence(agent_prefs.cadence_days, perspective)
        
        # Calculate date range based on cadence
        start_date, end_date, relative_days = self._calculate_date_range(
            agent_prefs.cadence_days,
            perspective
        )
        
        # Convert agent prefs to user preferences for routing
        user_prefs = agent_prefs.to_user_preferences()
        
        # Build route plan
        plan = RoutePlan(
            route_id=route_id,
            confidence=0.95,  # High confidence for agent-driven routing
            start_date=start_date,
            end_date=end_date,
            relative_days=relative_days,
            workgroups=agent_prefs.expertise_organisations,
            topics=agent_prefs.expertise_topics,
            organizations=agent_prefs.expertise_organisations,
            people=[],
            detail_level=DetailLevel.DETAILED,
            deep_dive=True,  # Agents need comprehensive context
            template_version="v1",
            routing_method="agent",
            raw_query=f"Agent {agent_prefs.agent_name} content discovery: {perspective or 'general'}"
        )
        
        logger.info(
            f"Routed agent {agent_prefs.agent_name} to {route_id.value}: "
            f"date_range={start_date} to {end_date}, "
            f"topics={len(agent_prefs.expertise_topics)}, "
            f"orgs={len(agent_prefs.expertise_organisations)}"
        )
        
        return route_id, plan, 0.95
    
    def _select_route_by_cadence(
        self,
        cadence_days: int,
        perspective: Optional[str]
    ) -> RouteId:
        """
        Select appropriate route based on agent cadence and perspective.
        
        Args:
            cadence_days: Days between generations
            perspective: Content angle ("news", "events", "analysis", "trends")
            
        Returns:
            RouteId for content discovery
        """
        # Perspective-based routing (overrides cadence)
        if perspective:
            perspective_lower = perspective.lower()
            if "event" in perspective_lower or "upcoming" in perspective_lower:
                return RouteId.UPCOMING_EVENTS
            elif "decision" in perspective_lower:
                return RouteId.RECENT_DECISIONS
            elif "trend" in perspective_lower or "topic" in perspective_lower:
                return RouteId.TOPICS_TREND
            elif "publication" in perspective_lower or "document" in perspective_lower:
                return RouteId.RECENT_PUBLICATIONS
        
        # Cadence-based routing
        if cadence_days <= 1:
            # Daily agents - use daily rollup
            return RouteId.WORKGROUP_DAILY_RECAP
        elif cadence_days <= 7:
            # Weekly agents - use weekly rollup
            return RouteId.WORKGROUP_WEEKLY_RECAP
        elif cadence_days <= 30:
            # Monthly agents - use monthly rollup
            return RouteId.WORKGROUP_MONTHLY_SUMMARY
        else:
            # Infrequent agents - use recent updates
            return RouteId.WORKGROUP_RECENT_UPDATES
    
    def _calculate_date_range(
        self,
        cadence_days: int,
        perspective: Optional[str]
    ) -> Tuple[Optional[date], Optional[date], Optional[int]]:
        """
        Calculate date range for content discovery.
        
        Args:
            cadence_days: Days between generations
            perspective: Content angle
            
        Returns:
            Tuple of (start_date, end_date, relative_days)
        """
        today = date.today()
        
        # For future events, look ahead instead of back
        if perspective and "upcoming" in perspective.lower():
            return today, today + timedelta(days=90), 90
        
        # For recent content, look back based on cadence
        # Use cadence * 1.5 to ensure enough content pool
        lookback_days = int(cadence_days * 1.5)
        start_date = today - timedelta(days=lookback_days)
        
        return start_date, today, lookback_days


def create_agent_preferences_from_dict(agent_data: Dict[str, Any]) -> CreatorAgentPreferences:
    """
    Create AgentPreferences from dictionary (e.g., from creator_service).
    
    Args:
        agent_data: Dictionary with agent configuration
        
    Returns:
        CreatorAgentPreferences instance
    """
    return CreatorAgentPreferences(
        agent_id=agent_data.get("id") or agent_data.get("agent_id"),
        agent_name=agent_data.get("name"),
        expertise_topics=agent_data.get("expertise_topics", []),
        expertise_organisations=agent_data.get("expertise_organisations", []),
        cadence_days=agent_data.get("cadence_window_days") or agent_data.get("cadence_days"),
        discovery_tolerance=agent_data.get("discovery_tolerance", 0.5),
        last_content_ids=agent_data.get("last_content_ids", [])
    )
