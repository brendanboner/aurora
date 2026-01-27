"""Local router for deterministic query routing.

Uses regex patterns, date parsing, and entity lookup to map queries
to route IDs without LLM calls (fast path).
"""

import re
import logging
from typing import Optional, Tuple, List
from datetime import datetime, timedelta, date

from src.models.route_plan import RoutePlan, RouteId, DetailLevel
from src.services.personalization import UserPreferences
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
        "recent": lambda: timedelta(days=14),  # Default "recent" to last 2 weeks
        "latest": lambda: timedelta(days=7),  # Default "latest" to last week
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
        (r"upcoming (events?|meetings?|conferences?|workshops?)", RouteId.UPCOMING_EVENTS),
        (r"future (events?|meetings?|conferences?)", RouteId.UPCOMING_EVENTS),
        (r"what('s| is) (coming up|scheduled)", RouteId.UPCOMING_EVENTS),
        (r"next (events?|meetings?|conferences?|workshops?)", RouteId.UPCOMING_EVENTS),
        (r"(conferences?|workshops?|summits?) (coming up|scheduled)", RouteId.UPCOMING_EVENTS),
        
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
    
    async def route(self, question: str, user_id: Optional[str] = None, user_prefs: Optional[UserPreferences] = None) -> Tuple[Optional[RoutePlan], float]:
        """
        Route a query to a specific route plan.
        
        Args:
            question: User query text
            user_id: Optional user ID for personalization
            user_prefs: Optional user preferences for intelligent entity extraction
            
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
        
        # Extract entities (workgroups, topics, etc.) with user preference boost
        entities = self._extract_entities(question_lower, user_prefs)
        
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
        today = date.today()
        
        # Check for relative date patterns (ordered by specificity)
        for pattern, delta_fn in self.DATE_PATTERNS.items():
            if pattern in question:
                delta = delta_fn()
                
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
                elif "recent" in pattern or "latest" in pattern:
                    # Recent/latest - default to last 2 weeks for recent, 1 week for latest
                    start_date = today - delta
                    logger.debug(f"Detected '{pattern}' - using date range {start_date} to {today}")
                    return start_date, today, delta.days
                
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
        
        # For routes that inherently need recent data (events, updates, decisions),
        # provide a sensible default if no date is specified
        # This will be handled per-route in the Cypher templates
        return None, None, None
    
    def _extract_entities(self, question: str, user_prefs: Optional[UserPreferences] = None) -> dict:
        """
        Extract entities from question using keyword matching.
        
        User preferences boost relevant entities but DO NOT filter:
        - If query mentions "HaLow", prioritize HaLow even if not in preferences
        - If query mentions "802.1x security" and user prefers Wi-Fi, boost Wi-Fi 802.1x over RADIUS 802.1x
        - If no explicit entities mentioned, use preferences as hints
        
        Returns:
            Dictionary with entity lists
        """
        entities = {
            "workgroups": [],
            "topics": [],
            "organizations": [],
            "people": []
        }
        
        # Common workgroup patterns (explicit mentions always take precedence)
        workgroup_patterns = [
            r"802\.11\w*",  # 802.11be, 802.11ax, etc.
            r"halow",  # HaLow
            r"wi-?fi\s*\d*",  # Wi-Fi, WiFi 6, WiFi 7
            r"wfa",  # Wi-Fi Alliance
            r"ieee",
            r"802\.1\w*",  # 802.1x, 802.1Q, etc.
        ]
        
        # Extract explicit mentions from query
        for pattern in workgroup_patterns:
            matches = re.findall(pattern, question, re.IGNORECASE)
            entities["workgroups"].extend([m.strip() for m in matches])
        
        # Remove duplicates from explicit mentions
        entities["workgroups"] = list(set(entities["workgroups"]))
        
        # Check for topic keywords (e.g., "security", "6 GHz")
        topic_keywords = {
            "security": ["security", "authentication", "encryption", "802.1x"],
            "6 GHz": ["6 ghz", "6ghz"],
            "MLO": ["mlo", "multi-link"],
            "WPA3": ["wpa3", "wpa 3"],
        }
        
        for topic_name, keywords in topic_keywords.items():
            if any(kw in question for kw in keywords):
                entities["topics"].append(topic_name)
        
        # If user has preferences, use them intelligently:
        # 1. If query has explicit entities, DON'T override
        # 2. If query has ambiguous context (e.g., "security"), prefer user's domain
        # 3. If no explicit entities AND query could benefit from filtering (events, conferences), add preferences
        if user_prefs:
            # If query mentions topics and user has preferences, prioritize user's domain
            if entities["topics"] and user_prefs.topics:
                # Example: If user prefers "Wi-Fi" and query mentions "802.1x",
                # boost Wi-Fi 802.1x interpretation over RADIUS 802.1x
                user_topics_lower = [t.lower() for t in user_prefs.topics]
                if any(topic in ["wi-fi", "wifi", "802.11"] for topic in user_topics_lower):
                    # User is in Wi-Fi domain - boost Wi-Fi interpretations
                    if "802.1x" in question.lower() or "security" in question.lower():
                        entities["topics"].append("Wi-Fi Security")
            
            # If NO explicit topics AND query is about events/conferences, add user topic preferences
            # This handles: "What conferences are coming up?" when user prefers "security"
            if not entities["topics"] and user_prefs.topics:
                query_keywords = ["conference", "workshop", "event", "summit", "upcoming", "coming up"]
                if any(kw in question.lower() for kw in query_keywords):
                    # User wants events - filter by their topic interests
                    entities["topics"].extend(user_prefs.topics[:3])  # Add top 3 preferences
                    logger.debug(f"Event query without explicit topics - adding user preferences: {user_prefs.topics[:3]}")
            
            # If NO explicit workgroups mentioned, add preferred ones as hints (not filters)
            if not entities["workgroups"] and user_prefs.organisations:
                # Add as low-priority hints (will be used for boosting, not filtering)
                logger.debug(f"No explicit workgroups, adding user prefs as hints: {user_prefs.organisations[:3]}")
                # DON'T add to entities - let Cypher templates handle boosting
        
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
