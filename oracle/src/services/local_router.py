"""Local router for deterministic query routing.

Uses regex patterns, date parsing, and entity lookup to map queries
to route IDs without LLM calls (fast path).
"""

import re
import logging
from typing import Optional, Tuple, List
from datetime import datetime, timedelta, date

from src.models.route_plan import RoutePlan, RouteId, DetailLevel
from src.settings import settings

logger = logging.getLogger(__name__)


class LocalRouter:
    """
    Local deterministic router for fast query routing.
    
    Uses pattern matching and entity resolution to map queries
    to predefined routes without LLM calls.
    """
    
    # Date patterns
    DATE_PATTERNS = {
        "today": lambda: timedelta(days=0),
        "yesterday": lambda: timedelta(days=1),
        "this week": lambda: timedelta(days=7),
        "last week": lambda: timedelta(days=14),
        "this month": lambda: timedelta(days=30),
        "last month": lambda: timedelta(days=60),
    }
    
    # Route patterns (query text -> route_id)
    ROUTE_PATTERNS = [
        # Weekly recap patterns
        (r"(weekly|week)\s+(recap|summary|update)", RouteId.WORKGROUP_WEEKLY_RECAP),
        (r"what happened (this|last) week", RouteId.WORKGROUP_WEEKLY_RECAP),
        (r"(this|last) week('s)?\s+(activities|events|updates)", RouteId.WORKGROUP_WEEKLY_RECAP),
        
        # Daily recap patterns
        (r"(daily|today('s)?)\s+(recap|summary|update)", RouteId.WORKGROUP_DAILY_RECAP),
        (r"what happened (today|yesterday)", RouteId.WORKGROUP_DAILY_RECAP),
        
        # Monthly patterns
        (r"(monthly|month)\s+(recap|summary|update)", RouteId.WORKGROUP_MONTHLY_SUMMARY),
        (r"what happened (this|last) month", RouteId.WORKGROUP_MONTHLY_SUMMARY),
        (r"(this|last) month('s)?\s+(activities|summary)", RouteId.WORKGROUP_MONTHLY_SUMMARY),
        
        # Recent updates
        (r"recent (updates|changes|news|developments)", RouteId.WORKGROUP_RECENT_UPDATES),
        (r"what('s| is) new", RouteId.WORKGROUP_RECENT_UPDATES),
        (r"latest (updates|news)", RouteId.WORKGROUP_RECENT_UPDATES),
        
        # Events - upcoming
        (r"upcoming (events?|meetings?)", RouteId.UPCOMING_EVENTS),
        (r"future (events?|meetings?)", RouteId.UPCOMING_EVENTS),
        (r"what('s| is) (coming up|scheduled)", RouteId.UPCOMING_EVENTS),
        (r"next (events?|meetings?)", RouteId.UPCOMING_EVENTS),
        
        # Events - past
        (r"past (events?|meetings?)", RouteId.PAST_EVENTS),
        (r"previous (events?|meetings?)", RouteId.PAST_EVENTS),
        (r"recent (events?|meetings?)", RouteId.PAST_EVENTS),
        
        # Decisions
        (r"(decisions?|decided)\s+(made|reached|taken)", RouteId.DECISIONS_IN_RANGE),
        (r"what (was|were) decided", RouteId.DECISIONS_IN_RANGE),
        (r"key decisions", RouteId.DECISIONS_IN_RANGE),
        (r"recent decisions", RouteId.RECENT_DECISIONS),
        (r"latest decisions", RouteId.RECENT_DECISIONS),
        (r"decisions? (on|about|regarding)\s+\w+", RouteId.DECISIONS_BY_TOPIC),
        
        # Action items
        (r"(action items?|tasks?|todos?|follow[- ]?ups?)", RouteId.ACTION_ITEMS_OPEN),
        (r"what needs to be done", RouteId.ACTION_ITEMS_OPEN),
        (r"outstanding (items|tasks)", RouteId.ACTION_ITEMS_OPEN),
        (r"(my|his|her|their)\s+(action items?|tasks?)", RouteId.ACTION_ITEMS_BY_PERSON),
        (r"assigned to\s+\w+", RouteId.ACTION_ITEMS_BY_PERSON),
        
        # Topics
        (r"(topics?|discussions?)\s+(trend|discussed|covered)", RouteId.TOPICS_TREND),
        (r"what (topics?|subjects?) (are|were) discussed", RouteId.TOPICS_TREND),
        (r"trending topics?", RouteId.TOPICS_TREND),
        (r"(topics?|discussions?)\s+timeline", RouteId.TOPIC_TIMELINE),
        (r"evolution of\s+\w+", RouteId.TOPIC_TIMELINE),
        (r"related to\s+\w+", RouteId.RELATED_TOPICS),
        (r"similar topics?", RouteId.RELATED_TOPICS),
        
        # Documents
        (r"documents? (on|about|regarding)\s+\w+", RouteId.DOCUMENTS_BY_TOPIC),
        (r"(find|show|get)\s+documents?", RouteId.DOCUMENTS_BY_TOPIC),
        (r"recent (publications?|documents?|papers?)", RouteId.RECENT_PUBLICATIONS),
        (r"latest (publications?|documents?|papers?)", RouteId.RECENT_PUBLICATIONS),
        
        # People
        (r"who (said|mentioned|talked about)", RouteId.WHO_SAID_WHAT),
        (r"did (anyone|someone) (say|mention)", RouteId.WHO_SAID_WHAT),
        (r"(activity|contributions?) (by|from)\s+\w+", RouteId.PERSON_ACTIVITY),
        (r"what (has|did)\s+\w+\s+(do|say|contribute)", RouteId.PERSON_ACTIVITY),
        
        # Organizations
        (r"(activity|updates?) (from|by)\s+\w+", RouteId.ORGANIZATION_ACTIVITY),
        (r"what is\s+\w+\s+doing", RouteId.ORGANIZATION_ACTIVITY),
        
        # Meeting search
        (r"meeting (about|regarding|on)", RouteId.MEETING_BY_TITLE),
        (r"(find|search for) meeting", RouteId.MEETING_BY_TITLE),
    ]
    
    def __init__(self):
        """Initialize the local router."""
        self.confidence_threshold = settings.fast_router_confidence_threshold
        logger.info("Initialized LocalRouter")
    
    async def route(self, question: str, user_id: Optional[str] = None) -> Tuple[Optional[RoutePlan], float]:
        """
        Route a query to a specific route plan.
        
        Args:
            question: User query text
            user_id: Optional user ID for personalization
            
        Returns:
            Tuple of (RoutePlan, confidence) or (None, 0.0) if no match
        """
        question_lower = question.lower().strip()
        
        logger.debug(f"Local routing: '{question[:80]}...'")
        
        # Try to match route pattern
        route_id, route_confidence = self._match_route_pattern(question_lower)
        
        if not route_id:
            logger.debug("No route pattern matched")
            return None, 0.0
        
        # Parse date/time references
        start_date, end_date, relative_days = self._parse_dates(question_lower)
        
        # Extract entities (workgroups, topics, etc.)
        entities = self._extract_entities(question_lower)
        
        # Determine detail level
        detail_level = self._determine_detail_level(question_lower)
        
        # Should we do deep dive?
        deep_dive = self._should_deep_dive(question_lower, detail_level)
        
        # Build route plan
        plan = RoutePlan(
            route_id=route_id,
            confidence=route_confidence,
            start_date=start_date,
            end_date=end_date,
            relative_days=relative_days,
            workgroups=entities.get("workgroups", []),
            topics=entities.get("topics", []),
            organizations=entities.get("organizations", []),
            people=entities.get("people", []),
            detail_level=detail_level,
            deep_dive=deep_dive,
            template_version=settings.fast_template_version,
            routing_method="local",
            raw_query=question
        )
        
        logger.info(
            f"Local route: route_id={route_id.value} confidence={route_confidence:.2f} "
            f"date_range={start_date or 'none'} to {end_date or 'none'} "
            f"entities={len(entities)} detail={detail_level.value}"
        )
        
        return plan, route_confidence
    
    def _match_route_pattern(self, question: str) -> Tuple[Optional[RouteId], float]:
        """
        Match question against route patterns.
        
        Returns:
            Tuple of (RouteId, confidence) or (None, 0.0)
        """
        for pattern, route_id in self.ROUTE_PATTERNS:
            if re.search(pattern, question, re.IGNORECASE):
                # Higher confidence for more specific patterns
                confidence = min(0.9, 0.7 + len(pattern) / 200)
                logger.debug(f"Matched pattern: {pattern} -> {route_id.value}")
                return route_id, confidence
        
        return None, 0.0
    
    def _parse_dates(self, question: str) -> Tuple[Optional[date], Optional[date], Optional[int]]:
        """
        Parse date references from question.
        
        Returns:
            Tuple of (start_date, end_date, relative_days)
        """
        # Check for relative date patterns
        for pattern, delta_fn in self.DATE_PATTERNS.items():
            if pattern in question:
                delta = delta_fn()
                today = date.today()
                
                if "yesterday" in pattern:
                    return today - timedelta(days=1), today - timedelta(days=1), 1
                elif "today" in pattern:
                    return today, today, 0
                elif "this week" in pattern:
                    # Current week
                    start = today - timedelta(days=today.weekday())
                    return start, today, 7
                elif "last week" in pattern:
                    # Previous week
                    end = today - timedelta(days=today.weekday() + 1)
                    start = end - timedelta(days=6)
                    return start, end, 7
                elif "this month" in pattern:
                    start = today.replace(day=1)
                    return start, today, 30
                elif "last month" in pattern:
                    # Previous month
                    first_today = today.replace(day=1)
                    end = first_today - timedelta(days=1)
                    start = end.replace(day=1)
                    return start, end, 30
                
                # Default relative range
                start_date = today - delta
                return start_date, today, delta.days
        
        # Try to parse explicit dates (YYYY-MM-DD format)
        date_pattern = r'\b(\d{4})-(\d{2})-(\d{2})\b'
        matches = re.findall(date_pattern, question)
        
        if len(matches) >= 2:
            # Two dates found - treat as range
            try:
                start = date(int(matches[0][0]), int(matches[0][1]), int(matches[0][2]))
                end = date(int(matches[1][0]), int(matches[1][1]), int(matches[1][2]))
                return start, end, (end - start).days
            except ValueError:
                pass
        elif len(matches) == 1:
            # Single date found
            try:
                single = date(int(matches[0][0]), int(matches[0][1]), int(matches[0][2]))
                return single, single, 0
            except ValueError:
                pass
        
        # No dates found
        return None, None, None
    
    def _extract_entities(self, question: str) -> dict:
        """
        Extract entities from question using keyword matching.
        
        This is a simple pattern-based extractor. For better accuracy,
        we'd use the entity resolver from the graph.
        
        Returns:
            Dictionary with entity lists
        """
        entities = {
            "workgroups": [],
            "topics": [],
            "organizations": [],
            "people": []
        }
        
        # Common workgroup patterns
        workgroup_patterns = [
            r"802\.11\w*",  # 802.11be, 802.11ax, etc.
            r"wi-?fi\s*\d*",  # Wi-Fi, WiFi 6, WiFi 7
            r"wfa",  # Wi-Fi Alliance
            r"ieee",
        ]
        
        for pattern in workgroup_patterns:
            matches = re.findall(pattern, question, re.IGNORECASE)
            entities["workgroups"].extend([m.strip() for m in matches])
        
        # Remove duplicates
        entities["workgroups"] = list(set(entities["workgroups"]))
        
        return entities
    
    def _determine_detail_level(self, question: str) -> DetailLevel:
        """
        Determine desired detail level from question.
        
        Returns:
            DetailLevel enum value
        """
        # Brief indicators
        if any(word in question for word in ["brief", "summary", "quick", "tldr", "overview"]):
            return DetailLevel.BRIEF
        
        # Comprehensive indicators
        if any(word in question for word in ["detailed", "comprehensive", "full", "complete", "in-depth", "thorough"]):
            return DetailLevel.COMPREHENSIVE
        
        # Default to detailed
        return DetailLevel.DETAILED
    
    def _should_deep_dive(self, question: str, detail_level: DetailLevel) -> bool:
        """
        Determine if deep dive retrieval is needed.
        
        Args:
            question: Query text
            detail_level: Requested detail level
            
        Returns:
            True if deep dive should be enabled
        """
        # Always deep dive for comprehensive
        if detail_level == DetailLevel.COMPREHENSIVE:
            return True
        
        # Deep dive if user asks for evidence or details
        if any(word in question for word in ["why", "evidence", "details", "explain", "how"]):
            return True
        
        # No deep dive for brief
        if detail_level == DetailLevel.BRIEF:
            return False
        
        # Default based on settings
        return False
