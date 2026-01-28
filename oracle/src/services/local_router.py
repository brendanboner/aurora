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
        "in the last week": lambda: timedelta(days=7),  # Check this BEFORE "last week"
        "in the last month": lambda: timedelta(days=30),  # Check this BEFORE "last month"
        "this week": lambda: timedelta(days=7),
        "last week": lambda: timedelta(days=14),
        "this month": lambda: timedelta(days=30),
        "last month": lambda: timedelta(days=60),
        "recent": lambda: timedelta(days=14),  # Default "recent" to last 2 weeks
        "latest": lambda: timedelta(days=7),  # Default "latest" to last week
    }
    
    # Route patterns (query text -> route_id)
    # CRITICAL: ORDER MATTERS - Most specific patterns first, general patterns last
    ROUTE_PATTERNS = [
        # === PEOPLE QUERIES (highest priority - very specific) ===
        # "who represents X at Y" / "who is X's representative"
        (r"who (represents?|is representing)\s+[\w\s\-]+\s+(at|in|for|on)\s+", RouteId.ORGANIZATION_REPRESENTATIVES),
        (r"(who is|who's)\s+[\w\s\-]+('s)?\s+(representative|rep|liaison|contact|member)", RouteId.ORGANIZATION_REPRESENTATIVES),
        (r"(who attends?|who('s| is) (at|in|attending))\s+[\w\s\-]+\s+(meetings?|events?)", RouteId.MEETING_ATTENDEES),
        (r"(people|attendees|participants|members) (at|in|from|on)\s+[\w\s\-]+", RouteId.MEETING_ATTENDEES),
        
        # "who is X" (person identification - capital letter indicates name)
        (r"who is\s+[A-Z][\w\s\-]+\??$", RouteId.PERSON_PROFILE),
        (r"who('s| is)\s+(dr\.?|prof\.?|mr\.?|ms\.?|mrs\.?)\s+[\w\s\-]+", RouteId.PERSON_PROFILE),
        
        # "who said/mentioned" (person quotes/contributions)
        (r"who (said|mentioned|talked about|discussed|presented|announced)\s+", RouteId.WHO_SAID_WHAT),
        (r"did (anyone|someone|anybody) (say|mention|discuss|present|announce)\s+", RouteId.WHO_SAID_WHAT),
        
        # Person activity
        (r"(activity|contributions?|work|involvement|papers|presentations) (by|from|of)\s+[\w\s\-]+", RouteId.PERSON_ACTIVITY),
        (r"what (has|did)\s+[\w\s\-]+\s+(do|say|contribute|present|work on|publish)", RouteId.PERSON_ACTIVITY),
        (r"[\w\s\-]+('s)?\s+(contributions?|activity|work|papers|presentations|involvement)", RouteId.PERSON_ACTIVITY),
        
        # === COMPARISON QUERIES (high priority - very common) ===
        (r"compare\s+[\w\s\-]+\s+(and|vs\.?|versus|with|to)\s+", RouteId.TOPIC_COMPARISON),
        (r"[\w\s\-]+\s+(vs\.?|versus)\s+[\w\s\-]+", RouteId.TOPIC_COMPARISON),
        (r"(differences?|difference|diff) between\s+[\w\s\-]+\s+and\s+", RouteId.TOPIC_COMPARISON),
        (r"[\w\s\-]+\s+or\s+[\w\s\-]+\s+(which|better|best)", RouteId.TOPIC_COMPARISON),
        (r"(compare|comparison)\s+(of|between)\s+", RouteId.TOPIC_COMPARISON),
        
        # === STATUS & PROGRESS QUERIES (high priority) ===
        (r"(status|state|progress) of\s+[\w\s\-]+", RouteId.STATUS_CHECK),
        (r"(where is|what('s| is) the status)\s+[\w\s\-]+", RouteId.STATUS_CHECK),
        (r"is\s+[\w\s\-]+\s+(ready|done|complete|finalized|approved)", RouteId.STATUS_CHECK),
        (r"(when will|when is)\s+[\w\s\-]+\s+(be )?(ready|done|released|finalized)", RouteId.STATUS_CHECK),
        (r"[\w\s\-]+\s+(certification|approval|ratification)\s+status", RouteId.STATUS_CHECK),
        (r"progress (on|of|with)\s+[\w\s\-]+", RouteId.PROGRESS_TRACKING),
        
        # === ADOPTION & "WHO SUPPORTS" QUERIES ===
        (r"who (supports?|uses?|implements?|adopted|deploys?)\s+", RouteId.ADOPTION_STATUS),
        (r"(companies|organizations|vendors) (using|supporting|with)\s+", RouteId.ADOPTION_STATUS),
        (r"[\w\s\-]+\s+(adoption|deployment|support|implementation)\s+(status|rate)?", RouteId.ADOPTION_STATUS),
        (r"(adoption|deployment|support) (of|for)\s+[\w\s\-]+", RouteId.ADOPTION_STATUS),
        (r"market share\s+(of|for)\s+", RouteId.ADOPTION_STATUS),
        
        # === VENDOR/COMPANY-SPECIFIC PRODUCT QUERIES ===
        (r"[\w\s\-]+\s+(products?|chipsets?|solutions?|platforms?)\s+(for|with|supporting)\s+", RouteId.VENDOR_PRODUCTS),
        (r"[\w\s\-]+('s)?\s+(implementation|support|version)\s+of\s+", RouteId.VENDOR_PRODUCTS),
        
        # === TECHNICAL EXPLANATION QUERIES ===
        (r"how (does|do|did)\s+[\w\s\-]+\s+work", RouteId.TECHNICAL_EXPLANATION),
        (r"how to (implement|use|configure|setup|deploy)\s+", RouteId.IMPLEMENTATION_GUIDE),
        (r"[\w\s\-]+\s+(architecture|design|structure|mechanism)", RouteId.TECHNICAL_EXPLANATION),
        (r"[\w\s\-]+\s+(specification|requirements|specs?)\s*$", RouteId.TECHNICAL_EXPLANATION),
        (r"(explain|describe)\s+how\s+[\w\s\-]+\s+works?", RouteId.TECHNICAL_EXPLANATION),
        
        # === LEARNING & TUTORIAL QUERIES ===
        (r"(learn|learning|study)\s+[\w\s\-]+", RouteId.LEARNING_RESOURCES),
        (r"[\w\s\-]+\s+(tutorial|guide|introduction|intro)", RouteId.LEARNING_RESOURCES),
        (r"(getting started|get started|begin|start)\s+with\s+", RouteId.LEARNING_RESOURCES),
        (r"[\w\s\-]+\s+for\s+(beginners?|dummies|newbies)", RouteId.LEARNING_RESOURCES),
        
        # === TIMELINE & HISTORY QUERIES ===
        (r"(history|timeline|evolution) (of|for)\s+[\w\s\-]+", RouteId.TOPIC_TIMELINE),
        (r"when (did|was)\s+[\w\s\-]+\s+(start|begin|launch|release)", RouteId.TOPIC_TIMELINE),
        (r"[\w\s\-]+\s+over time", RouteId.TOPIC_TIMELINE),
        (r"(versions?|releases?) of\s+[\w\s\-]+\s+over time", RouteId.STANDARD_VERSIONS),
        
        # === ISSUE & PROBLEM QUERIES ===
        (r"(problems?|issues?|bugs?) (with|in)\s+[\w\s\-]+", RouteId.ISSUE_TRACKING),
        (r"[\w\s\-]+\s+(limitations?|challenges?|concerns?|drawbacks?)", RouteId.ISSUE_TRACKING),
        (r"(security|vulnerability|exploit)\s+(issues?|problems?)\s+(in|with)\s+", RouteId.ISSUE_TRACKING),
        
        # === REGULATORY & COMPLIANCE QUERIES ===
        (r"[\w\s\-]+\s+(regulations?|compliance|rules?|requirements?)", RouteId.REGULATORY_INFO),
        (r"(fcc|etsi|regulatory)\s+(rules?|requirements?)\s+for\s+", RouteId.REGULATORY_INFO),
        (r"(certification|compliance)\s+requirements?\s+for\s+", RouteId.REGULATORY_INFO),
        (r"legal\s+requirements?\s+(for|of)\s+", RouteId.REGULATORY_INFO),
        
        # === ORGANIZATION QUERIES (before general "what is") ===
        # "what is ORG doing" - organization activity
        (r"what is\s+(the\s+)?(3gpp|ieee|ietf|etsi|wfa|oma|gsma|wifi|wi-fi|qualcomm|intel|broadcom|extreme|cisco)\s+doing", RouteId.ORGANIZATION_ACTIVITY),
        (r"what('s| is)\s+(the\s+)?(3gpp|ieee|ietf|etsi|wfa|oma|gsma|wifi|wi-fi|alliance)\s+(working on|focusing on)", RouteId.ORGANIZATION_ACTIVITY),
        (r"(activity|updates?|news|progress) (from|by|at)\s+", RouteId.ORGANIZATION_ACTIVITY),
        
        # === WORKGROUP-SPECIFIC ACTIVITY QUERIES (highest priority for workgroup synopsis) ===
        # These patterns match queries asking about activity/discussions in specific workgroups
        (r"what happened in.*?(workgroup|wg|group)", RouteId.WORKGROUP_RECENT_UPDATES),
        (r"what was discussed in.*?(workgroup|wg|group)", RouteId.WORKGROUP_RECENT_UPDATES),
        (r"(activity|updates|discussions?) in (the )?(halow|security|802\.1x|802\.11|wifi|wi-fi|network).*?(workgroup|wg)", RouteId.WORKGROUP_RECENT_UPDATES),
        (r"(halow|security|802\.1x|802\.11|wifi|wi-fi|network)\s+(workgroup|wg)\s+(activity|updates|discussions?|progress)", RouteId.WORKGROUP_RECENT_UPDATES),
        (r"what('s| is) (happening|going on|being discussed) in.*?(workgroup|wg)", RouteId.WORKGROUP_RECENT_UPDATES),
        
        # === TIME-BASED "WHAT HAPPENED" & "WHAT WAS DISCUSSED" QUERIES ===
        (r"what happened.*?(today|yesterday)", RouteId.WORKGROUP_DAILY_RECAP),
        (r"what happened.*?(this|last|past) week", RouteId.WORKGROUP_WEEKLY_RECAP),
        (r"what happened.*?(this|last|past) month", RouteId.WORKGROUP_MONTHLY_SUMMARY),
        (r"what happened.*?in the last (week|month|\d+\s+days?)", RouteId.WORKGROUP_RECENT_UPDATES),
        
        # "What was discussed" patterns - similar to "what happened"
        (r"what was discussed.*?(today|yesterday)", RouteId.WORKGROUP_DAILY_RECAP),
        (r"what was discussed.*?(this|last|past) week", RouteId.WORKGROUP_WEEKLY_RECAP),
        (r"what was discussed.*?(this|last|past) month", RouteId.WORKGROUP_MONTHLY_SUMMARY),
        (r"what was discussed.*?in the last (week|month|\d+\s+days?)", RouteId.WORKGROUP_RECENT_UPDATES),
        (r"what('s| is) being discussed", RouteId.WORKGROUP_RECENT_UPDATES),
        (r"what (have we|did we|were we) discuss", RouteId.WORKGROUP_RECENT_UPDATES),
        
        # Weekly recap patterns
        (r"(weekly|week)\s+(recap|summary|update|report)", RouteId.WORKGROUP_WEEKLY_RECAP),
        (r"(this|last|past) week('s)?\s+(activities|events|updates|summary)", RouteId.WORKGROUP_WEEKLY_RECAP),
        
        # Daily recap patterns
        (r"(daily|today('s)?)\s+(recap|summary|update|report)", RouteId.WORKGROUP_DAILY_RECAP),
        (r"(today('s)?|yesterday('s)?)\s+(activities|events|updates)", RouteId.WORKGROUP_DAILY_RECAP),
        
        # Monthly patterns
        (r"(monthly|month)\s+(recap|summary|update|report)", RouteId.WORKGROUP_MONTHLY_SUMMARY),
        (r"(this|last|past) month('s)?\s+(activities|summary|events)", RouteId.WORKGROUP_MONTHLY_SUMMARY),
        
        # Recent updates (general)
        (r"recent (updates|changes|news|developments|activity)", RouteId.WORKGROUP_RECENT_UPDATES),
        (r"what('s| is) new\s+(in|with|at|for)?", RouteId.WORKGROUP_RECENT_UPDATES),
        (r"what('s| is) (the )?latest (in|on|with|for|at)\s+", RouteId.WORKGROUP_RECENT_UPDATES),
        (r"latest (updates|news|developments|activity)", RouteId.WORKGROUP_RECENT_UPDATES),
        
        # === EVENTS & MEETINGS ===
        # Upcoming events
        (r"upcoming (events?|meetings?|conferences?|workshops?|summits?)", RouteId.UPCOMING_EVENTS),
        (r"(future|planned|scheduled) (events?|meetings?|conferences?)", RouteId.UPCOMING_EVENTS),
        (r"what('s| is) (coming up|scheduled|planned)", RouteId.UPCOMING_EVENTS),
        (r"(next|future) (events?|meetings?|conferences?|workshops?)", RouteId.UPCOMING_EVENTS),
        (r"when is (the )?(next|upcoming)\s+", RouteId.UPCOMING_EVENTS),
        
        # Past events
        (r"(past|previous|recent) (events?|meetings?|conferences?)", RouteId.PAST_EVENTS),
        (r"what (events?|meetings?) (happened|occurred|took place)", RouteId.PAST_EVENTS),
        
        # Meeting search by title/topic
        (r"meeting (about|regarding|on|covering|discussing)\s+", RouteId.MEETING_BY_TITLE),
        (r"(find|show|get|search for|locate)\s+(the )?meeting", RouteId.MEETING_BY_TITLE),
        (r"(minutes|notes|summary) (from|of)\s+(the )?meeting", RouteId.MEETING_MINUTES),
        
        # === DECISIONS ===
        (r"(decisions?|decided)\s+(made|reached|taken|about)", RouteId.DECISIONS_IN_RANGE),
        (r"what (was|were|has been) decided\s+(on|about)?", RouteId.DECISIONS_IN_RANGE),
        (r"key decisions?\s+(on|about|regarding)?", RouteId.DECISIONS_IN_RANGE),
        (r"recent decisions?\s+(on|about)?", RouteId.RECENT_DECISIONS),
        (r"latest decisions?\s+(on|about)?", RouteId.RECENT_DECISIONS),
        (r"decisions? (on|about|regarding)\s+[\w\s\-]+", RouteId.DECISIONS_BY_TOPIC),
        
        # === ACTION ITEMS & TASKS ===
        (r"(action items?|tasks?|todos?|follow[- ]?ups?)\s+(for|from|by)?", RouteId.ACTION_ITEMS_OPEN),
        (r"what needs to be done", RouteId.ACTION_ITEMS_OPEN),
        (r"(outstanding|open|pending) (items?|tasks?|actions?)", RouteId.ACTION_ITEMS_OPEN),
        (r"(my|his|her|their|[\w\-]+('s)?)\s+(action items?|tasks?|assignments?)", RouteId.ACTION_ITEMS_BY_PERSON),
        (r"(assigned to|for)\s+[\w\s\-]+", RouteId.ACTION_ITEMS_BY_PERSON),
        
        # === STANDARDS & SPECIFICATIONS ===
        (r"(standard|spec|specification)\s+(status|progress|state)", RouteId.STANDARD_STATUS),
        (r"(updates?|changes?|modifications?) to\s+(the\s+)?[\w\s\-]+\s+(standard|spec)", RouteId.STANDARD_UPDATES),
        
        # === TOPICS & TRENDS ===
        (r"(topics?|discussions?)\s+(trend|discussed|covered|popular)", RouteId.TOPICS_TREND),
        (r"what (topics?|subjects?|themes?) (are|were|have been) discussed", RouteId.TOPICS_TREND),
        (r"trending (topics?|subjects?|discussions?)", RouteId.TOPICS_TREND),
        (r"(popular|hot|emerging|important) topics?", RouteId.TOPICS_TREND),
        (r"(related to|similar to|connected to)\s+[\w\s\-]+", RouteId.RELATED_TOPICS),
        (r"(similar|related) (topics?|subjects?)", RouteId.RELATED_TOPICS),
        
        # === DOCUMENTS & PUBLICATIONS ===
        # Specific document queries
        (r"(recent|latest|new) (publications?|documents?|papers?|articles?|specs?)", RouteId.RECENT_PUBLICATIONS),
        (r"(find|show|get|search for)\s+(documents?|papers?|publications?)", RouteId.DOCUMENTS_BY_TOPIC),
        (r"documents? (on|about|regarding|covering|discussing)\s+", RouteId.DOCUMENTS_BY_TOPIC),
        (r"(papers?|articles?|specs?) (on|about|regarding)\s+", RouteId.DOCUMENTS_BY_TOPIC),
        
        # === DEFINITION/EXPLANATION QUERIES (must come late - very general) ===
        # "what is X" (topic/concept explanation) - comes after organization and status checks
        (r"what (is|are)\s+[\w\s\-]+\??$", RouteId.DOCUMENTS_BY_TOPIC),
        (r"what('s| is)\s+[\w\s\-]+\s+\??$", RouteId.DOCUMENTS_BY_TOPIC),
        (r"(tell me about|explain|describe|define)\s+[\w\s\-]+", RouteId.DOCUMENTS_BY_TOPIC),
        (r"(definition|meaning|explanation) of\s+[\w\s\-]+", RouteId.DOCUMENTS_BY_TOPIC),
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
        
        # For definition/document queries, skip user preference expansion to focus on explicit topic
        skip_user_prefs_routes = [
            RouteId.DOCUMENTS_BY_TOPIC,
            RouteId.TECHNICAL_EXPLANATION,
            RouteId.TOPIC_COMPARISON,
            RouteId.STATUS_CHECK,
            RouteId.LEARNING_RESOURCES,
        ]
        skip_user_prefs = route_id in skip_user_prefs_routes
        
        # Extract entities (workgroups, topics, etc.) with conditional user preference boost
        entities = self._extract_entities(question_lower, user_prefs, skip_user_prefs)
        
        if skip_user_prefs:
            logger.debug(f"Skipping user preference expansion for {route_id.value} (focused query)")
        
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
        
        # Fallback to generic search instead of None
        logger.debug("No specific pattern matched, using GENERIC_SEARCH fallback")
        return RouteId.GENERIC_SEARCH, 0.5
    
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
                
                if "yesterday" in question:
                    return today - timedelta(days=1), today - timedelta(days=1), 1
                elif "today" in question:
                    return today, today, 0
                elif "in the last week" in question:
                    # Rolling last 7 days
                    start = today - timedelta(days=7)
                    return start, today, 7
                elif "this week" in question:
                    # Current week (Monday to today)
                    start = today - timedelta(days=today.weekday())
                    return start, today, 7
                elif "last week" in question:
                    # Previous calendar week (Monday-Sunday)
                    end = today - timedelta(days=today.weekday() + 1)
                    start = end - timedelta(days=6)
                    return start, end, 7
                elif "in the last month" in question:
                    # Rolling last 30 days
                    start = today - timedelta(days=30)
                    return start, today, 30
                elif "this month" in question:
                    # Current month (1st to today)
                    start = today.replace(day=1)
                    days_in_month = (today - start).days + 1
                    return start, today, days_in_month
                elif "last month" in question:
                    # Previous calendar month
                    first_today = today.replace(day=1)
                    end = first_today - timedelta(days=1)
                    start = end.replace(day=1)
                    days_in_last_month = (end - start).days + 1
                    return start, end, days_in_last_month
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
    
    def _extract_entities(self, question: str, user_prefs: Optional[UserPreferences] = None, skip_user_prefs: bool = False) -> dict:
        """
        Extract entities from question using keyword matching.
        
        User preferences boost relevant entities but DO NOT filter:
        - If query mentions "HaLow", prioritize HaLow even if not in preferences
        - If query mentions "802.1x security" and user prefers Wi-Fi, boost Wi-Fi 802.1x over RADIUS 802.1x
        - If no explicit entities mentioned, use preferences as hints
        
        Args:
            question: Query text to extract entities from
            user_prefs: Optional user preferences for boosting
            skip_user_prefs: If True, skip adding user preferences (for focused queries)
        
        Returns:
            Dictionary with entity lists
        """
        entities = {
            "workgroups": [],
            "topics": [],
            "organizations": [],
            "people": []
        }
        
        # Common workgroup name patterns (explicit mentions always take precedence)
        # These map query keywords to actual Neo4j workgroup names
        workgroup_keywords = {
            "wifi 7": "Wi-Fi 7",
            "wi-fi 7": "Wi-Fi 7",
            "wifi7": "Wi-Fi 7",
            "wifi 8": "Wi-Fi 8",
            "wi-fi 8": "Wi-Fi 8",
            "wifi8": "Wi-Fi 8",
            "broadcast": "Broadcast",
            "passpoint": "Passpoint",
            "security": "Security",
            "regulatory": "Regulatory",
            "location": "Location",
            "xrms": "XRMS",
            "sensing": "Sensing",
        }
        
        # Extract workgroup mentions from query
        for keyword, workgroup_name in workgroup_keywords.items():
            if keyword in question:
                entities["workgroups"].append(workgroup_name)
        
        # Remove duplicates from explicit mentions
        entities["workgroups"] = list(set(entities["workgroups"]))
        
        # Check for topic keywords (e.g., "security", "6 GHz")
        topic_keywords = {
            # IEEE 802.11 Standards (Wi-Fi generations)
            # NOTE: These keys must match exact Topic.name values in Neo4j
            "802.11bn": ["802.11bn", "bn", "wifi 8", "wi-fi 8"],
            "802.11be": ["802.11be", "be", "wifi 7", "wi-fi 7", "extremely high throughput", "eht"],
            "802.11ax": ["802.11ax", "ax", "wifi 6", "wi-fi 6", "high efficiency"],
            "802.11ac": ["802.11ac", "ac", "wifi 5", "wi-fi 5"],
            "802.11n": ["802.11n", "wifi 4", "wi-fi 4"],
            "wi-fi certified halow": ["halow", "wi-fi halow", "wifi halow"],  # Primary HaLow topic (41 docs)
            "ieee p802.11ah": ["802.11ah", "ah", "sub-1 ghz"],  # Technical designation (1 doc)
            "802.11ad": ["802.11ad", "ad", "wigig", "60 ghz"],
            "802.11ay": ["802.11ay", "ay"],
            "802.11az": ["802.11az", "az", "next generation positioning", "ngp"],
            
            # Security standards
            "security": ["security", "authentication", "encryption", "802.1x", "wpa", "secure"],
            "WPA3": ["wpa3", "wpa 3"],
            "WPA2": ["wpa2", "wpa 2"],
            "802.1X": ["802.1x", "radius", "eap"],
            
            # Spectrum and frequency bands
            "6 GHz": ["6 ghz", "6ghz", "6 gigahertz"],
            "5 GHz": ["5 ghz", "5ghz", "5 gigahertz"],
            "2.4 GHz": ["2.4 ghz", "2.4ghz"],
            "60 GHz": ["60 ghz", "60ghz"],
            
            # Key technologies
            "MLO": ["mlo", "multi-link", "multilink"],
            "OFDMA": ["ofdma"],
            "MU-MIMO": ["mu-mimo", "mumimo", "multi-user mimo"],
            "Beamforming": ["beamforming", "beam forming"],
            "TWT": ["twt", "target wake time"],
            
            # Wi-Fi Alliance programs
            "Passpoint": ["passpoint", "hotspot 2.0"],
            "Easy Connect": ["easy connect", "dpp", "device provisioning"],
            "WPA3-Enterprise": ["wpa3-enterprise", "wpa3 enterprise"],
            
            # Sensing and location
            "Sensing": ["sensing", "wi-fi sensing", "motion detection"],
            "Location": ["location", "positioning", "ftm", "fine timing"],
            "SLAM": ["slam", "simultaneous localization"],
        }
        
        for topic_name, keywords in topic_keywords.items():
            if any(kw in question for kw in keywords):
                entities["topics"].append(topic_name)
        
        # Generate query hints for intelligent routing (pattern-based, no LLM)
        query_hints = {
            # Definition queries: "what is X" or "what are X"
            "is_definition": bool(re.search(r"^what (is|are)\s+[^?]+\??", question, re.IGNORECASE)),
            
            # Workgroup synopsis queries: mentions workgroup/wg with activity keywords
            "is_workgroup_synopsis": bool(
                re.search(r"(workgroup|wg)\s+(activity|updates?|discussions?|progress)", question, re.IGNORECASE) or
                re.search(r"(activity|updates?|discussions?|progress)\s+in.*(workgroup|wg)", question, re.IGNORECASE) or
                re.search(r"what (happened|was discussed).*?(workgroup|wg)", question, re.IGNORECASE)
            ),
            
            # Synopsis queries: "what happened", "what was discussed"
            "is_synopsis": bool(re.search(r"what (happened|was discussed|is (happening|going on))", question, re.IGNORECASE)),
            
            # Exploration queries: broad questions without specific entities
            "is_exploration": len(entities["topics"]) == 0 and len(entities["workgroups"]) == 0,
            
            # Focused queries: explicit entity mentions
            "is_focused": len(entities["topics"]) > 0 or len(entities["workgroups"]) > 0,
        }
        
        # Store hints in entities for downstream use
        entities["_query_hints"] = query_hints
        
        logger.debug(f"Query hints: definition={query_hints['is_definition']}, "
                    f"workgroup_synopsis={query_hints['is_workgroup_synopsis']}, "
                    f"synopsis={query_hints['is_synopsis']}, "
                    f"exploration={query_hints['is_exploration']}, "
                    f"focused={query_hints['is_focused']}")
        
        # If user has preferences, use them intelligently:based on query hints:
        # 1. Workgroup synopsis with explicit workgroup → Skip topic preferences (focus on workgroup only)
        # 2. Definition query with explicit topic → Skip preferences (focus on exact topic)
        # 3. Definition query without explicit topic → Use preferences as fallback
        # 4. Synopsis/exploration query → Add preferences for boosting
        if user_prefs and not skip_user_prefs:
            # Strategy 1: Workgroup synopsis with explicit workgroup - DON'T add topic preferences
            if query_hints["is_workgroup_synopsis"] and entities["workgroups"]:
                logger.debug("Workgroup synopsis with explicit workgroup - skipping topic preferences to focus on workgroup activity")
                # Don't add topic preferences - let workgroup be the primary filter
                pass
            
            # Strategy 2: Definition query with explicit topic - DON'T add preferences (focused lookup)
            elif query_hints["is_definition"] and entities["topics"]:
                logger.debug("Definition query with explicit topic - skipping preferences for focused lookup")
                # Don't dilute with preferences - user wants THIS topic specifically
                pass
            
            # Strategy 3: Definition query without explicit topic - USE preferences as fallback
            elif query_hints["is_definition"] and not entities["topics"] and user_prefs.topics:
                logger.debug("Definition query without explicit topic - using user preferences as fallback")
                # No explicit topic, so interpret based on user's domain
                for topic in user_prefs.topics[:3]:  # Use top 3 preferences
                    entities["topics"].append(topic)
            
            # Strategy 4: Synopsis/exploration queries - ADD preferences for boosting
            else:
                # If query mentions topics and user has preferences, prioritize user's domain
                if entities["topics"] and user_prefs.topics:
                    # Example: If user prefers "Wi-Fi" and query mentions "802.1x",
                    # boost Wi-Fi 802.1x interpretation over RADIUS 802.1x
                    user_topics_lower = [t.lower() for t in user_prefs.topics]
                    if any(topic in ["wi-fi", "wifi", "802.11"] for topic in user_topics_lower):
                        # User is in Wi-Fi domain - boost Wi-Fi interpretations
                        if "802.1x" in question.lower() or "security" in question.lower():
                            entities["topics"].append("Wi-Fi Security")
                
                # Add user topic preferences to steer the response
                if user_prefs.topics:
                    # Add topics that aren't already explicitly mentioned
                    existing_topics_lower = [t.lower() for t in entities["topics"]]
                    for topic in user_prefs.topics:
                        if topic.lower() not in existing_topics_lower:
                            entities["topics"].append(topic)
                    logger.debug(f"Added {len(user_prefs.topics)} user topic preferences for steering")
            
            # Add user organization preferences to steer the response
            # Organizations help filter and prioritize results from specific workgroups
            if user_prefs.organisations:
                # Add organizations that aren't already explicitly mentioned
                existing_orgs_lower = [o.lower() for o in entities["organizations"]]
                for org in user_prefs.organisations:
                    if org.lower() not in existing_orgs_lower:
                        entities["organizations"].append(org)
                logger.debug(f"Added {len(user_prefs.organisations)} user organization preferences for steering")
            
            # Add user people preferences for steering (when relevant)
            if user_prefs.people:
                entities["people"].extend(user_prefs.people)
                logger.debug(f"Added {len(user_prefs.people)} user people preferences for steering")
        
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
