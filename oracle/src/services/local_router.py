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
from src.services.topic_manager import get_topic_manager, initialize_topic_manager
from src.settings import settings

logger = logging.getLogger(__name__)


class LocalRouter:
    """
    Local deterministic router for fast query routing.
    
    Uses pattern matching and entity resolution to map queries
    to predefined routes without LLM calls.
    """
    
    # Date patterns
    # FIXED TIME WINDOWS: Used for explicit time references (daily/weekly/monthly recap routes)
    # EXPANDING TIME WINDOWS: Used for relative terms (recent/lately) via RECENT_CONTENT template
    DATE_PATTERNS = {
        # Fixed windows - explicit time references
        "today": lambda: timedelta(days=1),
        "yesterday": lambda: timedelta(days=1),
        "in the last week": lambda: timedelta(days=7),  # Check this BEFORE "last week"
        "in the last month": lambda: timedelta(days=30),  # Check this BEFORE "last month"
        "this week": lambda: timedelta(days=7),
        "last week": lambda: timedelta(days=7),  # Fixed 7 days for WORKGROUP_WEEKLY_RECAP
        "this month": lambda: timedelta(days=30),
        "last month": lambda: timedelta(days=30),  # Fixed 30 days for monthly queries
        
        # Expanding windows - relative terms (RECENT_CONTENT handles 14→56→180 day expansion)
        "recent": lambda: timedelta(days=14),  # Initial window, template expands if needed
        "recently": lambda: timedelta(days=14),
        "lately": lambda: timedelta(days=14),
        "latest": lambda: timedelta(days=7),
    }
    
    # Route patterns (query text -> route_id)
    # CRITICAL: ORDER MATTERS - Most specific patterns first, general patterns last
    ROUTE_PATTERNS = [
        # === WBA EXTRANET QUERIES (high priority — unambiguous intent) ===
        # Membership action: "join the AI/ML workgroup" / "leave PQC group"
        (r"^(join|leave|follow|unfollow|add|remove)\s+(the\s+)?[\w\s\-\/]+(\s+(workgroup|programme|program|group|community))?$",
         RouteId.MEMBERSHIP_ACTION),

        # "what's new in my groups" — MUST come before WBA_RECENT_ACTIVITY
        # so "my groups" queries are not captured as workgroup-specific activity
        (r"(what('?s|\s+is)\s+)?(new|happening|latest|recent|updates?)\s+(in|from|across)\s+my\s+(groups?|workgroups?|sources?|programmes?)",
         RouteId.MY_GROUPS_DIGEST),
        (r"my\s+(groups?|workgroups?|sources?|programmes?)\s+(digest|summary|updates?|news|activity)",
         RouteId.MY_GROUPS_DIGEST),
        (r"(updates?|news|activity|summary|digest)\s+(from|across|in)\s+my\s+(groups?|workgroups?)",
         RouteId.MY_GROUPS_DIGEST),

        # "what programmes / workgroups are available in WBA"
        # Allow optional "in" between the availability word and "wba" (e.g. "available in WBA")
        (r"(what|list|show)\s+(programmes?|programs?|workgroups?|groups?)\s+(are\s+)?(available|exist|in|under)\s+(in\s+)?(the\s+)?(wba|wi[-\s]?fi\s+broadband)",
         RouteId.WBA_PROGRAMME_LIST),
        # "show me WBA programmes" / "list WBA workgroups"
        (r"(show|list).{0,15}(wba|wi[-\s]?fi\s+broadband).{0,20}(programmes?|programs?|workgroups?)",
         RouteId.WBA_PROGRAMME_LIST),
        # "what WBA programmes are there"
        (r"(what|which).{0,10}(wba).{0,10}(programmes?|programs?|workgroups?|groups?)",
         RouteId.WBA_PROGRAMME_LIST),

        # "what workgroups / programs are in [programme name]"
        (r"(what|list|show)\s+(workgroups?|programs?|groups?|subgroups?)\s+(are\s+)?(in|under|part\s+of|inside|within)\s+(the\s+)?[\w\s\-\/]+",
         RouteId.WBA_WORKGROUPS_OF),
        (r"(workgroups?|programs?|groups?)\s+(in|under|inside|within)\s+(the\s+)?[\w\s\-\/]+\s+(programme|program|workgroup|group)?",
         RouteId.WBA_WORKGROUPS_OF),

        # "what is new / happening in [workgroup]"
        # NOTE: use \bworkgroup\b (not bare "group") to avoid matching "working groups"
        (r"(what('?s|\s+is)\s+)?(new|happening|going\s+on|latest|recent)\s+(in|at|with|for)\s+(the\s+)?[\w\s\-\/]+\s*\b(workgroup|programme|program)\b",
         RouteId.WBA_RECENT_ACTIVITY),
        (r"(what.{0,20}(in|at)\s+(the\s+)?[\w\s\-\/]+\b(workgroup|programme|program)\b)",
         RouteId.WBA_RECENT_ACTIVITY),

        # === PEOPLE QUERIES (highest priority - very specific) ===
        # "who do I talk to / who should I contact / who is the expert on X" → find people in org
        (r"who (do i|should i|can i)\s+(talk to|contact|speak (to|with)|reach out to|ask)\s+(about|regarding|on|for)?", RouteId.ORGANIZATION_REPRESENTATIVES),
        (r"who('s| is) (the\s+)?(expert|lead|contact|point of contact|poc|responsible|in charge|cto|ceo|chair)\s+(for|on|at|in|of)?", RouteId.ORGANIZATION_REPRESENTATIVES),
        (r"(contact|reach|speak|talk)\s+(to|with)\s+(someone|anyone|the\s+right\s+person)", RouteId.ORGANIZATION_REPRESENTATIVES),

        # "who represents X at Y" / "who is X's representative"
        (r"who (represents?|is representing)\s+[\w\s\-]+\s+(at|in|for|on)\s+", RouteId.ORGANIZATION_REPRESENTATIVES),
        (r"(who is|who's)\s+[\w\s\-]+('s)?\s+(representative|rep|liaison|contact|member)", RouteId.ORGANIZATION_REPRESENTATIVES),
        (r"(who attends?|who('s| is) (at|in|attending))\s+[\w\s\-]+\s+(meetings?|events?)", RouteId.MEETING_ATTENDEES),
        (r"(people|attendees|participants|members) (at|in|from|on)\s+[\w\s\-]+", RouteId.MEETING_ATTENDEES),
        
        # "who is X" (person identification - capital letter indicates name)
        (r"who is\s+[A-Z][\w\s\-]+\??$", RouteId.PERSON_PROFILE),
        (r"who('s| is)\s+(dr\.?|prof\.?|mr\.?|ms\.?|mrs\.?)\s+[\w\s\-]+", RouteId.PERSON_PROFILE),
        
        # "who spoke/presented at [EVENT]" (conference/event speaker queries - more specific than WHO_SAID_WHAT)
        (r"who (spoke|presented|talked|spoke\s+at|presented\s+at)\s+(at|in|during)\s+", RouteId.DOCUMENTS_BY_TOPIC),
        (r"(speakers?|presenters?|panelists?|keynotes?)\s+(at|for|in)\s+", RouteId.DOCUMENTS_BY_TOPIC),
        
        # "what was discussed/happened at [EVENT]" (event content queries - broader than workgroup/meeting patterns)
        # This catches: "what was discussed at cisco ai summit", "what happened at the live session"
        (r"what (was|is)\s+(discussed|covered|presented|talked about|shown|shared|announced|said)\s+at\s+", RouteId.DOCUMENTS_BY_TOPIC),
        (r"what (happened|occurred|took place)\s+at\s+(?!the\s+(last|latest|recent|previous)\s+(meeting|call|session))", RouteId.DOCUMENTS_BY_TOPIC),
        
        # "what did [PERSON] discuss/say at [EVENT]" (person + event combination - must come before general person activity)
        (r"what (did|does)\s+[\w\s\-]+\s+(discuss|say|present|talk about|cover|announce)\s+at\s+", RouteId.PERSON_AT_EVENT),
        (r"[\w\s\-]+('s)?\s+(presentation|talk|keynote|session|discussion)\s+at\s+", RouteId.PERSON_AT_EVENT),
        (r"did\s+[\w\s\-]+\s+(speak|present|talk)\s+at\s+", RouteId.PERSON_AT_EVENT),
        
        # "who said/mentioned" (person quotes/contributions - general pattern)
        (r"who (said|mentioned|talked about|discussed|presented|announced)\s+", RouteId.WHO_SAID_WHAT),
        (r"who (is )?talking (about|regarding|on)\s+", RouteId.WHO_SAID_WHAT),
        (r"did (anyone|someone|anybody) (say|mention|discuss|present|announce)\s+", RouteId.WHO_SAID_WHAT),
        
        # === ORGANIZATION PUBLICATION QUERIES (before person activity to avoid false matches) ===
        # "what has [ORG] published/released" - organization publications
        (r"what\s+(has\s+)?(the\s+)?([\w\s\-]+\s+)?(alliance|foundation|consortium|organization|institute|3gpp|ieee|ietf|etsi|wfa|oma|gsma)\s+(published|released|announced|issued)\s+(about|on|regarding)", RouteId.ORGANIZATION_ACTIVITY),
        # "recent/latest [ORG] publications" — org between recency word and publication type
        (r"(most\s+)?(recent|latest|new)\s+([\w\s\-]*?)(wi-fi alliance|wfa|wi-fi org|ieee|ietf|wba|3gpp|gsma|etsi)([\w\s\-]*?)(publications?|documents?|updates?|releases?|news|content)\b", RouteId.ORGANIZATION_ACTIVITY),
        # "[ORG] has published/released recently" - org then verb
        (r"(wi-fi alliance|wfa|ieee|ietf|wba|3gpp)\s+(has\s+)?(published|released|announced|issued|put out)", RouteId.ORGANIZATION_ACTIVITY),
        # Known company names contributing/publishing - must come BEFORE generic person_activity catch-all
        (r"what (has|did)\s+(?:qualcomm|intel|broadcom|cisco|aruba|apple|samsung|nokia|ericsson|huawei|mediatek|google|microsoft|extreme|commscope|tp-link|netgear|ubiquiti)\s+(contributed?|done|published|presented|submitted|worked on)", RouteId.ORGANIZATION_ACTIVITY),
        
        # Person activity
        (r"(activity|contributions?|work|involvement|papers|presentations) (by|from|of)\s+[\w\s\-]+", RouteId.PERSON_ACTIVITY),
        # \b after verb prevents "do" matching "documented", "say" matching "saying", etc.
        (r"what (has|did)\s+[\w\s\-]+\s+(do|say|contribute|present|work\s+on|publish)\b", RouteId.PERSON_ACTIVITY),
        # Match "John's work" but not "work in" (technical context)
        (r"[\w\s\-]+('s)\s+(contributions?|activity|work|papers|presentations|involvement)($|\s+(on|about|regarding|with))", RouteId.PERSON_ACTIVITY),
        
        # === COMPARISON QUERIES (high priority - very common) ===
        (r"compare\s+[\w\s\-]+\s+(and|vs\.?|versus|with|to)\s+", RouteId.TOPIC_COMPARISON),
        (r"[\w\s\-]+\s+(vs\.?|versus)\s+[\w\s\-]+", RouteId.TOPIC_COMPARISON),
        (r"(differences?|difference|diff) between\s+[\w\s\-]+\s+and\s+", RouteId.TOPIC_COMPARISON),
        (r"[\w\s\-]+\s+or\s+[\w\s\-]+\s+(which|better|best)", RouteId.TOPIC_COMPARISON),
        (r"(compare|comparison)\s+(of|between)\s+", RouteId.TOPIC_COMPARISON),
        (r"what (are the )?(key )?improvements?.*?compared (to|with|against)", RouteId.TOPIC_COMPARISON),
        (r"how does\s+[\w\s\-]+\s+compare\s+(to|with|against)\s+", RouteId.TOPIC_COMPARISON),
        (r"(improvements?|changes?|differences?)\s+(in|of)\s+[\w\s\-]+\s+(over|from|vs\.?|versus)\s+", RouteId.TOPIC_COMPARISON),
        
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
        (r"which\s+(countries|regions?|markets?|jurisdictions?)\s+(have|has|approved?|allowed?|authorized?|enabled?)", RouteId.REGULATORY_INFO),
        (r"(approved?|allowed?|authorized?|enabled?)\s+[\w\s\-]+\s+(unlicensed|spectrum|band|frequency)", RouteId.REGULATORY_INFO),
        
        # === IETF-SPECIFIC QUERIES (before general org/recent patterns) ===
        # IETF meeting agenda by number (most specific - e.g. "IETF 120 agenda")
        (r"(?:agenda|session|schedule|meeting)\s+(?:at|for|of)?\s*ietf\s*\d{2,3}\b", RouteId.IETF_MEETING_AGENDA),
        (r"ietf\s*\d{2,3}\s+(?:agenda|session|schedule|meeting)", RouteId.IETF_MEETING_AGENDA),
        (r"what\s+(?:is|are|was|were)\s+(?:the\s+)?(?:agenda|sessions?)\s+(?:at|for|of)?\s*ietf\s*\d{2,3}\b", RouteId.IETF_MEETING_AGENDA),

        # IETF WG updates (protocol/WG-specific news)
        (r"what\s+is\s+new\s+(?:with|in|for)\s+(?:quic|bgp|ospf|tls|http|dns|ipv6|mpls|bfd|isis|lldp|netconf|yang|pcep|rsvp|ldp|pim|igmp|mld|vxlan|evpn|srv6|segment.routing)\b", RouteId.IETF_WG_UPDATES),
        (r"(?:latest?|recent|current|new)\s+(?:updates?|drafts?|rfcs?|news)\s+(?:from|in|on)?\s+ietf\b", RouteId.IETF_WG_UPDATES),
        (r"(?:latest?|recent|current)\s+ietf\s+(?:updates?|drafts?|rfcs?|news|publications?)\b", RouteId.IETF_WG_UPDATES),
        (r"ietf\s+(?:working\s+group\s+)?(?:updates?|drafts?|rfcs?|status|news)\b", RouteId.IETF_WG_UPDATES),
        (r"(?:quic|bgp|ospf|tls|http|dns)\s+(?:wg|working\s+group)\s+(?:updates?|news|status|drafts?)\b", RouteId.IETF_WG_UPDATES),

        # === ORGANIZATION QUERIES (before general "what is") ===
        # "what is ORG doing" - organization activity
        (r"what is\s+(the\s+)?(3gpp|ieee|ietf|etsi|wfa|oma|gsma|wifi|wi-fi|qualcomm|intel|broadcom|extreme|cisco)\s+doing", RouteId.ORGANIZATION_ACTIVITY),
        (r"what('s| is)\s+(the\s+)?(3gpp|ieee|ietf|etsi|wfa|oma|gsma|wifi|wi-fi|alliance)\s+(working on|focusing on)", RouteId.ORGANIZATION_ACTIVITY),
        (r"(activity|updates?|news|progress) (from|by|at)\s+", RouteId.ORGANIZATION_ACTIVITY),
        # Note: Organization publication patterns moved earlier (before person activity patterns)
        
        # Workgroup/organization association queries
        (r"what (workgroups?|wgs?|groups?).*(people|person|members?|contributors?).*(from|at|with)", RouteId.ORGANIZATION_ACTIVITY),
        (r"(people|members?).*(from|at|with).*(associated|involved|participating).*(workgroups?|wgs?)", RouteId.ORGANIZATION_ACTIVITY),
        (r"(workgroups?|wgs?|groups?).*(have|with).*(people|members?).*(from|at)", RouteId.ORGANIZATION_ACTIVITY),
        
        # === WORKGROUP DISCOVERY BY TOPIC ===
        # "What workgroups are talking about X?" - find datasources discussing a topic
        (r"(what|which)\s+(workgroups?|wgs?|groups?|datasources?)\s+(are|is|have been|has been)?\s*(talking|discussing|working|focusing)\s+(about|on)", RouteId.DOCUMENTS_BY_TOPIC),
        (r"(what|which)\s+(workgroups?|wgs?|groups?)\s+(mentioned|discussed|covered|published about)", RouteId.DOCUMENTS_BY_TOPIC),
        
        # === WORKGROUP-SPECIFIC ACTIVITY QUERIES (highest priority for workgroup synopsis) ===
        # These patterns match queries asking about activity/discussions in specific workgroups
        (r"what happened in.*?(workgroup|wg|group)", RouteId.RECENT_CONTENT),
        (r"what was discussed in.*?(workgroup|wg|group)", RouteId.RECENT_CONTENT),
        (r"(activity|updates|discussions?) in (the )?(halow|security|802\.1x|802\.11|wifi|wi-fi|network).*?(workgroup|wg)", RouteId.RECENT_CONTENT),
        (r"(halow|security|802\.1x|802\.11|wifi|wi-fi|network)\s+(workgroup|wg)\s+(activity|updates|discussions?|progress)", RouteId.RECENT_CONTENT),
        (r"what('s| is) (happening|going on|being discussed) in.*?(workgroup|wg)", RouteId.RECENT_CONTENT),
        
        # === TIME-BASED "WHAT HAPPENED" & "WHAT WAS DISCUSSED" QUERIES ===
        (r"what happened.*?(today|yesterday)", RouteId.WORKGROUP_DAILY_RECAP),
        (r"what happened.*?(this|last|past) week", RouteId.WORKGROUP_WEEKLY_RECAP),
        (r"what happened.*?(this|last|past) month", RouteId.WORKGROUP_MONTHLY_SUMMARY),
        (r"what happened.*?in the last (week|month|\d+\s+days?)", RouteId.RECENT_CONTENT),
        
        # "What was discussed" patterns - similar to "what happened"
        (r"what was discussed.*?(today|yesterday)", RouteId.WORKGROUP_DAILY_RECAP),
        (r"what was discussed.*?(this|last|past) week", RouteId.WORKGROUP_WEEKLY_RECAP),
        (r"what was discussed.*?(this|last|past) month", RouteId.WORKGROUP_MONTHLY_SUMMARY),
        (r"what was discussed\s+(recently|lately)\b", RouteId.RECENT_CONTENT),
        (r"what was discussed.*?in the last (week|month|\d+\s+days?)", RouteId.RECENT_CONTENT),
        (r"what was discussed.*(at|in|during|from).*(last|latest|recent|previous).*(meeting|call|session)", RouteId.RECENT_CONTENT),
        (r"what happened\s+(recently|lately)\b", RouteId.RECENT_CONTENT),
        (r"what happened.*(at|in|during).*(last|latest|recent|previous).*(meeting|call|session)", RouteId.RECENT_CONTENT),
        (r"(last|latest|recent|previous) (meeting|call|session)", RouteId.RECENT_CONTENT),
        (r"what('s| is) being discussed", RouteId.RECENT_CONTENT),
        (r"what (have we|did we|were we) discuss", RouteId.RECENT_CONTENT),
        
        # Weekly recap patterns
        (r"(weekly|week)\s+(recap|summary|update|report)", RouteId.WORKGROUP_WEEKLY_RECAP),
        (r"(this|last|past) week('s)?\s+(activities|events|updates|summary)", RouteId.WORKGROUP_WEEKLY_RECAP),
        
        # Daily recap patterns
        (r"(daily|today('s)?)\s+(recap|summary|update|report)", RouteId.WORKGROUP_DAILY_RECAP),
        (r"(today('s)?|yesterday('s)?)\s+(activities|events|updates)", RouteId.WORKGROUP_DAILY_RECAP),
        
        # Monthly patterns
        (r"(monthly|month)\s+(recap|summary|update|report)", RouteId.WORKGROUP_MONTHLY_SUMMARY),
        (r"(this|last|past) month('s)?\s+(activities|summary|events)", RouteId.WORKGROUP_MONTHLY_SUMMARY),
        (r"(give|show).*?(idea|summary|overview).*(last|past|this)\s+month", RouteId.WORKGROUP_MONTHLY_SUMMARY),
        
        # "what is the latest on [specific IEEE/IETF standard + event]" → status check
        # Catches: "what is the latest on the IEEE 802.11bn March 2026 plenary"
        (r"what('s| is) (the )?latest on.*?(ieee|ietf|wba|wfa|802\.\d+|plenary|session|ballot|draft|amendment)", RouteId.STATUS_CHECK),

        # Recent updates (general)
        (r"what are the latest .*?(updates|news|developments|changes)", RouteId.RECENT_CONTENT),
        (r"recent (updates|changes|news|developments|activity)", RouteId.RECENT_CONTENT),
        (r"what('s| is) new\s+(in|with|at|for)?", RouteId.RECENT_CONTENT),
        (r"what('s| is) (the )?latest (in|on|with|for|at)\s+", RouteId.RECENT_CONTENT),
        (r"latest (updates|news|developments|activity)", RouteId.RECENT_CONTENT),
        (r"(what is|what's) (the )?latest (update|news|development)", RouteId.RECENT_CONTENT),  # "what is the latest update"
        (r"(give|show|provide).*?(update|summary|overview)\s+on", RouteId.RECENT_CONTENT),
        
        # === EVENTS & MEETINGS ===
        # Upcoming events - allow org names between "upcoming" and event type
        (r"upcoming\s+(?:[\w\-]+\s+){0,4}(events?|meetings?|conferences?|workshops?|summits?)", RouteId.UPCOMING_EVENTS),
        (r"on the agenda for\s+upcoming", RouteId.UPCOMING_EVENTS),
        (r"(future|planned|scheduled) (events?|meetings?|conferences?)", RouteId.UPCOMING_EVENTS),
        (r"what('s| is) (coming up|scheduled|planned)", RouteId.UPCOMING_EVENTS),
        (r"(next|future) (events?|meetings?|conferences?|workshops?)", RouteId.UPCOMING_EVENTS),
        (r"when is (the )?(next|upcoming)\s+", RouteId.UPCOMING_EVENTS),
        # "when is the WGC EMEA" / "when is the Wi-Fi World Congress" (named event without "next")
        (r"when (is|are|does?)\s+(the\s+)?([\w\s\-]{3,40}?)\s+(event|conference|meeting|summit|workshop|happening|scheduled|taking\s+place)", RouteId.UPCOMING_EVENTS),
        # "when is the WGC in europe" / "when is WGC EMEA" — short upper-case acronym queries
        (r"when\s+(?:is|are)\s+(?:the\s+)?(?:[A-Z]{2,}[\w\-]*(?:\s+[\w\-]+){0,5})\s*(?:\?|$)", RouteId.UPCOMING_EVENTS),
        (r"(events?|conferences?|meetings?).*?(this|next)\s+(quarter|month|week)", RouteId.UPCOMING_EVENTS),
        
        # Upcoming events — additional patterns for natural phrasing
        # "what wfa meetings are upcoming" / "what are the upcoming WBA events"
        (r"what\s+(?:[\w\s\-]+\s+)?(meetings?|events?|conferences?)\s+(?:are\s+)?(upcoming|scheduled|planned|coming up)", RouteId.UPCOMING_EVENTS),
        # "are there any meetings this week" / "what meetings are this week"
        (r"(?:are there|what|show|list)\s+(?:any\s+)?(?:[\w\s\-]+\s+)?(meetings?|events?|conferences?)\s+(?:[\w\s]*\s+)?(this|next)\s+week", RouteId.UPCOMING_EVENTS),
        # "when is wireless japan" / "when is the member meeting"
        (r"when\s+is\s+(?:the\s+)?[\w][\w\s\-]{2,40}$", RouteId.UPCOMING_EVENTS),

        # Past events
        (r"(past|previous|recent) (events?|meetings?|conferences?)", RouteId.PAST_EVENTS),
        (r"what (events?|meetings?) (happened|occurred|took place)", RouteId.PAST_EVENTS),
        (r"when (was|were) (the )?(last|previous|most recent)\s+", RouteId.PAST_EVENTS),
        (r"(last|most recent|previous)\s+[\w\s\-]+(event|conference|meeting|summit|workshop)", RouteId.PAST_EVENTS),
        
        # Meeting search by title/topic
        (r"meeting (about|regarding|on|covering|discussing)\s+", RouteId.MEETING_BY_TITLE),
        (r"(find|show|get|search for|locate)\s+(the )?meeting", RouteId.MEETING_BY_TITLE),
        (r"(minutes|notes|summary) (from|of)\s+(the )?meeting", RouteId.MEETING_MINUTES),
        
        # Meeting search by title / agenda
        (r"(what (was|is|were)|what's)\s+the\s+(agenda|schedule|topics?|programme)\s+(for|of|at)\s+", RouteId.MEETING_BY_TITLE),
        # Meeting minutes — route to RECENT_CONTENT (MEETING_MINUTES has no template)
        # RECENT_CONTENT will find meeting docs from WFA Causeway datasources
        (r"meeting\s+(minutes|notes|summary)\b", RouteId.RECENT_CONTENT),
        (r"(minutes|notes|summary)\s+(from|of)\s+(the\s+)?(last|latest|recent)\s+", RouteId.RECENT_CONTENT),

        # "what was discussed in the last [workgroup] meeting" — WBA Extranet specific
        # IMPORTANT: Kept AFTER general MEETING_MINUTES so WFA meeting minutes route correctly first
        (r"(what\s+was\s+|what\s+were\s+)(discussed|covered|talked\s+about|reviewed)\s+(in|at|during)\s+(the\s+)?(last|latest|recent|previous)\s+([\w\s\-\/]+)?\s*(meeting|call|session)",
         RouteId.WBA_LAST_MEETING),
        (r"(last|latest|recent|previous)\s+([\w\s\-\/]+)?\s*(meeting|call|session)\s+(notes?|summary|minutes?|recap)",
         RouteId.WBA_LAST_MEETING),

        # === DECISIONS ===
        (r"(decisions?|decided)\s+(were\s+)?(made|reached|taken|about)", RouteId.DECISIONS_IN_RANGE),
        (r"what (was|were|has been) decided\s+(on|about)?", RouteId.DECISIONS_IN_RANGE),
        (r"key decisions?\s+(on|about|regarding)?", RouteId.DECISIONS_IN_RANGE),
        (r"recent decisions?\s+(on|about)?", RouteId.RECENT_DECISIONS),
        (r"latest decisions?\s+(on|about)?", RouteId.RECENT_DECISIONS),
        (r"decisions? (on|about|regarding)\s+[\w\s\-]+", RouteId.DECISIONS_BY_TOPIC),

        # === ACTION ITEMS & TASKS ===
        # NOTE: "tasks?" removed from first pattern to prevent "task group" matching
        (r"\b(action items?|todos?|follow[- ]?ups?)\b", RouteId.ACTION_ITEMS_OPEN),
        (r"what needs to be done", RouteId.ACTION_ITEMS_OPEN),
        (r"(outstanding|open|pending) (items?|tasks?|actions?)", RouteId.ACTION_ITEMS_OPEN),
        # Possessive or pronoun must precede "action items|tasks|assignments" to avoid
        # matching "Wi-Fi 8 task group" (where "8" + " " + "task" would falsely match)
        (r"(my|his|her|their)\s+(action items?|tasks?|assignments?)", RouteId.ACTION_ITEMS_BY_PERSON),
        (r"[\w\-]+'s\s+(action items?|tasks?|assignments?)", RouteId.ACTION_ITEMS_BY_PERSON),
        (r"assigned to\s+[\w\s\-]+", RouteId.ACTION_ITEMS_BY_PERSON),
        
        # === STANDARDS & SPECIFICATIONS ===
        (r"(standard|spec|specification)\s+(status|progress|state)", RouteId.STANDARD_STATUS),
        (r"(updates?|changes?|modifications?) to\s+(the\s+)?[\w\s\-]+\s+(standard|spec)", RouteId.STANDARD_UPDATES),
        
        # === TOPICS & TRENDS ===
        (r"(topics?|discussions?)\s+(trend|discussed|covered|popular)", RouteId.TOPICS_TREND),
        (r"what (topics?|subjects?|themes?) (are|were|have been) discussed", RouteId.TOPICS_TREND),
        (r"trending (topics?|subjects?|discussions?)", RouteId.TOPICS_TREND),
        (r"(popular|hot|emerging|important) topics?", RouteId.TOPICS_TREND),
        (r"^(what|which)\s+(topics?|subjects?|themes?)\s+(are|is)\s+(related to|similar to|connected to)\s+", RouteId.RELATED_TOPICS),
        (r"(similar|related) (topics?|subjects?)", RouteId.RELATED_TOPICS),
        
        # === DOCUMENTS & PUBLICATIONS ===
        # Specific document queries
        (r"(recent|latest|new) (publications?|documents?|papers?|articles?|specs?|press releases?)", RouteId.RECENT_PUBLICATIONS),
        (r"press releases?(\s+about)?", RouteId.RECENT_PUBLICATIONS),
        # "published/released in the last N days/week/month/quarter"
        (r"(published|released|added|submitted)\s+(in\s+the\s+)?(last|past)\s+(\d+\s+days?|week|month|quarter|year)", RouteId.RECENT_PUBLICATIONS),
        # "new content added to the knowledge base recently"
        (r"new (content|documents?|articles?|publications?)\s+(added|ingested|uploaded)\s*(to|in|recently)?", RouteId.RECENT_CONTENT),
        (r"what (content|documents?|articles?|publications?)\s+(was|were|has been|have been)\s+(added|published|released)\s+(recently|lately|this week|this month)?", RouteId.RECENT_CONTENT),
        (r"(find|show|get|search for)\s+(documents?|papers?|publications?)", RouteId.DOCUMENTS_BY_TOPIC),
        (r"documents? (on|about|regarding|covering|discussing|mention|mentioning|related to)\s+", RouteId.DOCUMENTS_BY_TOPIC),
        (r"(papers?|articles?|specs?) (on|about|regarding)\s+", RouteId.DOCUMENTS_BY_TOPIC),
        (r"what has changed in.*?(ieee|802\.11).*(standards?|specs?)", RouteId.RECENT_PUBLICATIONS),
        (r"what (standards?|changes?).*?ieee\s+802", RouteId.RECENT_PUBLICATIONS),
        (r"(published|released)\s+(by|from)\s+[\w\s\-]+\s+about", RouteId.RECENT_PUBLICATIONS),
        
        # === DEFINITION/EXPLANATION QUERIES (must come late - very general) ===
        # "what is X" (topic/concept explanation) - comes after organization and status checks
        (r"what (is|are)\s+(?!the\s+latest\b|latest\b|recent\b|new\b|changed\b|changing\b)[\w\s\-]+\??$", RouteId.DOCUMENTS_BY_TOPIC),
        (r"what('s| is)\s+(?!the\s+latest\b|latest\b|recent\b|new\b|changed\b|changing\b)[\w\s\-]+\s+\??$", RouteId.DOCUMENTS_BY_TOPIC),
        (r"what (is )?new (in|about|with|for|on)\s+", RouteId.RECENT_CONTENT),
        (r"(tell me about|explain|describe|define)\s+[\w\s\-]+", RouteId.DOCUMENTS_BY_TOPIC),
        (r"(definition|meaning|explanation) of\s+[\w\s\-]+", RouteId.DOCUMENTS_BY_TOPIC),
        # Technical questions about topics/technologies
        (r"what (frequency|frequencies|bands?|channels?|spectrum|range)\s+(does|do)\s+[\w\s\-]+\s+(use|work|operate)", RouteId.DOCUMENTS_BY_TOPIC),
        (r"(how|where)\s+does\s+[\w\s\-]+\s+(work|operate|function)", RouteId.DOCUMENTS_BY_TOPIC),
        (r"what (has |should )?changed", RouteId.RECENT_CONTENT),
    ]
    
    def __init__(self):
        """Initialize the local router."""
        self.confidence_threshold = settings.fast_router_confidence_threshold
        logger.info("Initialized LocalRouter")

    def _prune_generic_recent_topics(self, route_id: RouteId, entities: dict) -> dict:
        """Avoid over-constraining broad recent-content queries with umbrella Wi-Fi terms."""
        if route_id != RouteId.RECENT_CONTENT:
            return entities

        generic_recent_topics = {"wifi", "wi-fi", "wireless", "802.11", "wireless lan"}
        topics = entities.get("topics", [])
        if not topics:
            return entities

        filtered_topics = [topic for topic in topics if topic.strip().lower() not in generic_recent_topics]
        if len(filtered_topics) == len(topics):
            return entities

        logger.info(
            "Dropping generic umbrella topics from RECENT_CONTENT query to preserve broad recency coverage: "
            f"{topics}"
        )
        entities["topics"] = filtered_topics
        return entities

    def _prefer_brief_recent_answer(self, question: str, route_id: RouteId, entities: Optional[dict] = None) -> bool:
        """Use deterministic brief answers only for broad recent-discussion prompts."""
        if route_id != RouteId.RECENT_CONTENT:
            return False

        if entities:
            has_explicit_scope = bool(
                entities.get("topics") or entities.get("organizations") or entities.get("people")
            )
            if has_explicit_scope:
                return False

        brief_recent_patterns = [
            r"what was discussed\s+(recently|lately)\b",
            r"what happened\s+(recently|lately)\b",
        ]
        return any(re.search(pattern, question, re.IGNORECASE) for pattern in brief_recent_patterns)
    
    async def route(self, question: str, user_id: Optional[str] = None, user_prefs: Optional[UserPreferences] = None, datasource_ids: Optional[List[str]] = None) -> Tuple[Optional[RoutePlan], float]:
        """
        Route a query to a specific route plan.
        
        Args:
            question: User query text
            user_id: Optional user ID for personalization
            user_prefs: Optional user preferences for intelligent entity extraction
            datasource_ids: Optional list of datasource IDs (workgroups) to filter by
            
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
        
        # Override routing when datasource_ids provided with temporal keywords
        # For specific meeting/discussion queries, prefer RECENT_CONTENT over rollups
        #  (rollups don't have full document URLs/summaries)
        is_meeting_query = bool(re.search(r'(meeting|discussion|talked about|discussed)', question_lower))
        
        if datasource_ids and relative_days and not is_meeting_query:
            # Has explicit workgroup + temporal context → Use rollup templates
            if relative_days <= 1:
                route_id = RouteId.WORKGROUP_DAILY_RECAP
                route_confidence = 0.90
                logger.debug(f"Override: Using WORKGROUP_DAILY_RECAP for datasource_ids={datasource_ids} with {relative_days} days")
            elif relative_days <= 7:
                route_id = RouteId.WORKGROUP_WEEKLY_RECAP
                route_confidence = 0.90
                logger.debug(f"Override: Using WORKGROUP_WEEKLY_RECAP for datasource_ids={datasource_ids} with {relative_days} days")
            else:
                route_id = RouteId.RECENT_CONTENT
                route_confidence = 0.85
                logger.debug(f"Override: Using RECENT_CONTENT for datasource_ids={datasource_ids} with {relative_days} days")
        elif is_meeting_query and datasource_ids:
            # Meeting queries need full document data, not rollups
            logger.debug(f"Meeting query with datasource_ids, using RECENT_CONTENT instead of rollups")
            route_id = RouteId.RECENT_CONTENT
            route_confidence = 0.90
        
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

        temporal_rollup_routes = {
            RouteId.WORKGROUP_DAILY_RECAP,
            RouteId.WORKGROUP_WEEKLY_RECAP,
            RouteId.WORKGROUP_MONTHLY_SUMMARY,
        }
        has_explicit_workgroup_scope = bool(datasource_ids or entities.get("workgroups"))
        if route_id in temporal_rollup_routes and not has_explicit_workgroup_scope:
            logger.info(
                "Broad temporal synopsis query without explicit workgroup scope - "
                "using RECENT_CONTENT instead of workgroup rollup"
            )
            route_id = RouteId.RECENT_CONTENT
            route_confidence = max(route_confidence, 0.84)

        entities = self._prune_generic_recent_topics(route_id, entities)
        
        if skip_user_prefs:
            logger.debug(f"Skipping user preference expansion for {route_id.value} (focused query)")
        
        # For PERSON_PROFILE, extract the person name from "who is [Name]" patterns
        if route_id in (RouteId.PERSON_PROFILE, RouteId.PERSON_ACTIVITY) and not entities.get("people"):
            name_match = (
                re.search(r"who is\s+([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)+)", question, re.IGNORECASE) or
                re.search(r"who(?:'s| is)\s+(?:dr\.?|prof\.?|mr\.?|ms\.?|mrs\.?)?\s*([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)+)", question, re.IGNORECASE) or
                re.search(r"(?:tell me about|about|find|search for)\s+([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)+)", question, re.IGNORECASE) or
                re.search(r"(?:activity|contributions?|work|involvement) (?:by|from|of)\s+([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)+)", question, re.IGNORECASE) or
                re.search(r"what (?:has|did)\s+([A-Z][a-zA-Z]+(?: [A-Z][a-zA-Z]+)+)\s+(?:do|say|contribute|present|work\s+on|publish)", question, re.IGNORECASE)
            )
            if name_match:
                person_name = name_match.group(1).strip()
                entities["people"] = [person_name]
                logger.info(f"Extracted person name for {route_id.value}: '{person_name}'")

        # For ORGANIZATION_REPRESENTATIVES with no org, promote topic→org for well-known mappings
        # e.g. "who do I talk to about Passpoint" → inject WBA so the template can find people
        _topic_to_org = {
            "passpoint": "Wireless Broadband Alliance",
            "openroaming": "Wireless Broadband Alliance",
            "openroaming network": "Wireless Broadband Alliance",
            "wireless broadband": "Wireless Broadband Alliance",
            "wi-fi certification": "Wi-Fi Alliance",
            "wi-fi alliance": "Wi-Fi Alliance",
        }
        if route_id == RouteId.ORGANIZATION_REPRESENTATIVES and not entities.get("organizations"):
            all_terms = [t.lower() for t in entities.get("topics", []) + entities.get("workgroups", [])]
            for term in all_terms:
                mapped = _topic_to_org.get(term)
                if mapped:
                    entities["organizations"] = [mapped]
                    logger.info(f"ORGANIZATION_REPRESENTATIVES: inferred org '{mapped}' from topic '{term}'")
                    break

        # For TOPIC_COMPARISON, workgroup names serve as comparison subjects when no
        # explicit topic entities were extracted (e.g. "wifi 7 vs wifi 8" lands in workgroups).
        if route_id == RouteId.TOPIC_COMPARISON and not entities.get("topics") and entities.get("workgroups"):
            entities["topics"] = list(entities["workgroups"])
            logger.debug(f"TOPIC_COMPARISON: promoting workgroups to topics: {entities['topics']}")

        # Validate route: DOCUMENTS_BY_TOPIC requires at least one topic
        # If no topics found, fall back to GENERIC_SEARCH (full-text search)
        if route_id == RouteId.DOCUMENTS_BY_TOPIC and not entities.get("topics"):
            logger.info(f"Route {route_id.value} requires topics but none found, falling back to GENERIC_SEARCH")
            route_id = RouteId.GENERIC_SEARCH
            route_confidence = 0.6  # Lower confidence for fallback
        
        # Determine detail level
        detail_level = self._determine_detail_level(question_lower)
        if self._prefer_brief_recent_answer(question_lower, route_id, entities):
            detail_level = DetailLevel.BRIEF
        
        # Should we do deep dive?
        deep_dive = self._should_deep_dive(question_lower, detail_level)
        
        # For event queries, detect if conferences (not meetings) are requested
        exclude_meetings = None
        if route_id == RouteId.UPCOMING_EVENTS:
            # Exclude meetings if query asks for conferences, events, summits, workshops (but not meetings)
            if re.search(r'\b(conference|summit|event|workshop)', question_lower) and not re.search(r'\b(meeting)', question_lower):
                exclude_meetings = True
                logger.debug("Detected conference query - will exclude meetings from results")
        
        # Build route plan
        # Use datasource_ids filter from request if provided, otherwise use extracted workgroups
        workgroups_filter = datasource_ids if datasource_ids else entities.get("workgroups", [])
        if datasource_ids:
            logger.debug(f"Using workgroups filter from datasource_ids: {datasource_ids}")
            # Boost confidence when explicit datasource filter provided (more focused query)
            route_confidence = min(0.95, route_confidence + 0.15)
            logger.debug(f"Boosted confidence to {route_confidence:.2f} due to datasource filter")
        
        plan = RoutePlan(
            route_id=route_id,
            confidence=route_confidence,
            start_date=start_date,
            end_date=end_date,
            relative_days=relative_days,
            workgroups=workgroups_filter,
            # Mark as explicit so fallback never removes the workgroup constraint
            explicit_datasource_filter=bool(datasource_ids),
            topics=entities.get("topics", []),
            organizations=entities.get("organizations", []),
            people=entities.get("people", []),
            category=entities.get("category"),
            exclude_meetings=exclude_meetings,
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
        return RouteId.GENERIC_SEARCH, settings.fast_router_confidence_threshold  # Use configured threshold
    
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
                    # Full calendar week: Monday to Sunday (includes future days)
                    start = today - timedelta(days=today.weekday())
                    end = start + timedelta(days=6)
                    return start, end, 7
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
            "regulatory affairs": "Regulatory",
            "location": "Location",
            "xrms": "XRMS",
            "xr": "XRMS",
            "sensing": "Sensing",
            # WBA programme names
            "openroaming": "OpenRoaming",
            "open roaming": "OpenRoaming",
            "ai/ml": "AI/ML",
            "ai ml": "AI/ML",
            "pqc": "PQC",
            "post quantum": "PQC",
            "post-quantum": "PQC",
            "next gen hotspot": "Next Gen Hotspot",
            "ngh": "Next Gen Hotspot",
            "identity": "Identity",
            # WFA Causeway task group long-form names
            "wifi 8 task group": "Wi-Fi 8",
            "wi-fi 8 task group": "Wi-Fi 8",
            "wifi 7 task group": "Wi-Fi 7",
            "wi-fi 7 task group": "Wi-Fi 7",
            "location task group": "Location",
            "sensing task group": "Sensing",
            # IEEE 802.11 task group / amendment aliases
            "802.11bn": "802.11bn",
            "tgbn": "802.11bn",
            "ultra high reliability": "802.11bn",
            "p802.11bn": "802.11bn",
            "802.11bi": "802.11bi",
            "tgbi": "802.11bi",
            "enhanced privacy protection": "802.11bi",
            "802.11bp": "802.11bp",
            "tgbp": "802.11bp",
            "ambient power": "802.11bp",
            "802.11bt": "802.11bt",
            "tgbt": "802.11bt",
            "post-quantum cryptography": "802.11bt",
            "802.11bq": "802.11bq",
            "tgbq": "802.11bq",
            "integrated mmwave": "802.11bq",
            "802.11br": "802.11br",
            "tgbr": "802.11br",
            "enhanced light": "802.11br",
            "802.11mf": "802.11mf",
            "tgmf": "802.11mf",
            "tgwng": "WNG",
            "wireless next generation": "WNG",
            # IETF working groups — map to datasource names used in IETF_WG_UPDATES
            "tls working group": "TLS",
            "tls wg": "TLS",
            "quic working group": "QUIC",
            "quic wg": "QUIC",
            "bgp": "BGP",
            "bess": "BESS",
            "bgp enabled services": "BESS",
        }
        
        # Extract workgroup mentions from query (case-insensitive)
        question_lower = question.lower()
        for keyword, workgroup_name in workgroup_keywords.items():
            if keyword.lower() in question_lower:
                entities["workgroups"].append(workgroup_name)
        
        # Remove duplicates from explicit mentions
        entities["workgroups"] = list(set(entities["workgroups"]))
        
        # Extract organization mentions with abbreviation expansion
        org_abbreviations = {
            "wfa": "Wi-Fi Alliance",
            "wifi alliance": "Wi-Fi Alliance",
            "wi-fi alliance": "Wi-Fi Alliance",
            "wba": "Wireless Broadband Alliance",
            "wireless broadband alliance": "Wireless Broadband Alliance",
            "ieee": "IEEE",
            "ieee 802.11": "IEEE",
            "802.11": "IEEE",
            "ietf": "IETF",
            "3gpp": "3GPP",
            "extreme": "Extreme Networks",
            "extreme networks": "Extreme Networks",
            # Chip/tech vendors commonly mentioned in Wi-Fi discussions
            "qualcomm": "Qualcomm",
            "intel": "Intel",
            "broadcom": "Broadcom",
            "cisco": "Cisco",
            "aruba": "Aruba",
            "apple": "Apple",
            "samsung": "Samsung",
            "nokia": "Nokia",
            "ericsson": "Ericsson",
            "mediatek": "MediaTek",
            "google": "Google",
            "microsoft": "Microsoft",
            "commscope": "CommScope",
            "tp-link": "TP-Link",
            "netgear": "Netgear",
            "ubiquiti": "Ubiquiti",
        }
        
        for abbrev, full_name in org_abbreviations.items():
            # Use word boundaries to match abbreviations
            pattern = r'\b' + re.escape(abbrev) + r'\b'
            if re.search(pattern, question_lower):
                entities["organizations"].append(full_name)
                logger.debug(f"Expanded organization abbreviation: {abbrev} -> {full_name}")
        
        # Remove duplicates
        entities["organizations"] = list(set(entities["organizations"]))
        
        # Use TopicManager for dynamic topic extraction from Neo4j
        topic_manager = get_topic_manager()
        if topic_manager:
            try:
                extracted_topics = topic_manager.extract_topics(question)
                # Filter out topics that match organization names (avoid double-counting WFA as both topic and org)
                org_names_lower = {org.lower() for org in entities["organizations"]}
                org_alias_only_terms = {
                    "wfa",
                    "wifi alliance",
                    "wi-fi alliance",
                    "wba",
                    "wireless broadband alliance",
                    "ieee",
                    "ietf",
                    "3gpp",
                    "extreme",
                    "extreme networks",
                }
                filtered_topics = [
                    t for t in extracted_topics
                    if t.lower() not in org_names_lower and t.lower() not in org_alias_only_terms
                ]
                entities["topics"].extend(filtered_topics)
                logger.debug(f"TopicManager extracted topics: {filtered_topics}")
            except Exception as e:
                logger.error(f"TopicManager extraction failed: {e}")
                # Fallback: Continue without topics rather than crash
        else:
            logger.warning("TopicManager not initialized - topics will not be extracted")
        
        # Extract category filter from query (press release, whitepaper, article, blog, newsletter, specification)
        category_keywords = {
            "press release": "press release",
            "press releases": "press release",
            "whitepaper": "whitepaper",
            "whitepapers": "whitepaper",
            "article": "article",
            "articles": "article",
            "blog": "blog",
            "blogs": "blog",
            "blog post": "blog",
            "newsletter": "newsletter",
            "newsletters": "newsletter",
            "technical specification": "technical specification",
            "specification": "technical specification",
            "specifications": "technical specification",
            "spec": "technical specification",
            "specs": "technical specification",
        }
        
        for keyword, category in category_keywords.items():
            if keyword in question_lower:
                entities["category"] = category
                logger.debug(f"Extracted category filter: {category}")
                break
        
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
            
            # Strategy 4: Synopsis/exploration queries - DON'T add preferences (they should boost, not filter)
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
                
                # DON'T add user preferences as filters - they should only boost ranking
                # User preferences are for personalization/ranking, not hard filtering
                logger.debug("Skipping user preference expansion (preferences used for ranking only)")
            
            # DON'T add user organization/people preferences as filters
            # They should be used for scoring/ranking in templates, not as hard filters
            # This ensures users can discover new content outside their preferences
        
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
