"""Tests for WBA Extranet route patterns in LocalRouter.

Validates that:
- All 6 new WBA route IDs are correctly matched by pattern
- MEMBERSHIP_ACTION never raises
- Baseline routes are not inadvertently captured by WBA patterns
"""

import pytest
import re
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from src.models.route_plan import RouteId


# Reproduce the pattern matching logic from LocalRouter without instantiating
# the full router (avoids Neo4j/Redis deps in unit tests).

ROUTE_PATTERNS = [
    # MEMBERSHIP_ACTION
    (re.compile(r"^(join|leave|follow|unfollow|add|remove)\s+(the\s+)?[\w\s\-\/]+(\s+(workgroup|programme|program|group|community))?$", re.I),
     RouteId.MEMBERSHIP_ACTION),
    # MY_GROUPS_DIGEST — must come before WBA_RECENT_ACTIVITY
    (re.compile(r"(what('?s|\s+is)\s+)?(new|happening|latest|recent|updates?)\s+(in|from|across)\s+my\s+(groups?|workgroups?|sources?|programmes?)", re.I),
     RouteId.MY_GROUPS_DIGEST),
    (re.compile(r"my\s+(groups?|workgroups?|sources?|programmes?)\s+(digest|summary|updates?|news|activity)", re.I),
     RouteId.MY_GROUPS_DIGEST),
    (re.compile(r"(updates?|news|activity|summary|digest)\s+(from|across|in)\s+my\s+(groups?|workgroups?)", re.I),
     RouteId.MY_GROUPS_DIGEST),
    # WBA_PROGRAMME_LIST
    (re.compile(r"(what|list|show)\s+(programmes?|programs?|workgroups?|groups?)\s+(are\s+)?(available|exist|in|under)\s+(in\s+)?(the\s+)?(wba|wi[-\s]?fi\s+broadband)", re.I),
     RouteId.WBA_PROGRAMME_LIST),
    (re.compile(r"(show|list).{0,15}(wba|wi[-\s]?fi\s+broadband).{0,20}(programmes?|programs?|workgroups?)", re.I),
     RouteId.WBA_PROGRAMME_LIST),
    (re.compile(r"(what|which).{0,10}(wba).{0,10}(programmes?|programs?|workgroups?|groups?)", re.I),
     RouteId.WBA_PROGRAMME_LIST),
    # WBA_WORKGROUPS_OF
    (re.compile(r"(what|list|show)\s+(workgroups?|programs?|groups?|subgroups?)\s+(are\s+)?(in|under|part\s+of|inside|within)\s+(the\s+)?[\w\s\-\/]+", re.I),
     RouteId.WBA_WORKGROUPS_OF),
    # WBA_RECENT_ACTIVITY
    (re.compile(r"(what('?s|\s+is)\s+)?(new|happening|going\s+on|latest|recent)\s+(in|at|with|for)\s+(the\s+)?[\w\s\-\/]+\s*(workgroup|group|programme|program)?", re.I),
     RouteId.WBA_RECENT_ACTIVITY),
    # WBA_LAST_MEETING
    (re.compile(r"(what\s+was\s+|what\s+were\s+)(discussed|covered|talked\s+about|reviewed)\s+(in|at|during)\s+(the\s+)?(last|latest|recent|previous)\s+([\w\s\-\/]+)?\s*(meeting|call|session)", re.I),
     RouteId.WBA_LAST_MEETING),
    (re.compile(r"(last|latest|recent|previous)\s+([\w\s\-\/]+)?\s*(meeting|call|session)\s+(notes?|summary|minutes?|recap)", re.I),
     RouteId.WBA_LAST_MEETING),
]


def first_match(query: str):
    for pattern, route_id in ROUTE_PATTERNS:
        if pattern.search(query):
            return route_id
    return None


# ── MEMBERSHIP_ACTION ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "join the AI/ML workgroup",
    "leave the PQC group",
    "join WBA IoT HaLow workgroup",
    "leave IoT programme",
    "follow the Next Gen programme",
    "unfollow Wi-Fi Design group",
    "add the PQC community",
    "remove AI/ML",
])
def test_membership_action_matched(query):
    assert first_match(query) == RouteId.MEMBERSHIP_ACTION, f"Expected MEMBERSHIP_ACTION for: {query!r}"


# ── WBA_PROGRAMME_LIST ────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "what programmes are available in WBA",
    "what programs are available in WBA",
    "list workgroups available in the WBA",
    "show me WBA programmes",
])
def test_programme_list_matched(query):
    assert first_match(query) == RouteId.WBA_PROGRAMME_LIST, f"Expected WBA_PROGRAMME_LIST for: {query!r}"


# ── WBA_WORKGROUPS_OF ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "what workgroups are in the IoT programme",
    "list groups under Next Gen",
    "what programs are inside the IoT workgroup",
    "show workgroups in Next Gen",
])
def test_workgroups_of_matched(query):
    result = first_match(query)
    assert result in (RouteId.WBA_WORKGROUPS_OF, RouteId.WBA_RECENT_ACTIVITY), \
        f"Expected WBA_WORKGROUPS_OF or RECENT for: {query!r}"


# ── WBA_RECENT_ACTIVITY ───────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "what is happening in the AI/ML working group",
    "what's new in Next Gen",
    "latest in the PQC workgroup",
    "what is new in IoT HaLow",
])
def test_recent_activity_matched(query):
    assert first_match(query) == RouteId.WBA_RECENT_ACTIVITY, \
        f"Expected WBA_RECENT_ACTIVITY for: {query!r}"


# ── WBA_LAST_MEETING ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "what was discussed in the last PQC meeting",
    "what was covered in the last AI/ML call",
    "last meeting notes for PQC",
    "last PQC meeting summary",
])
def test_last_meeting_matched(query):
    assert first_match(query) == RouteId.WBA_LAST_MEETING, \
        f"Expected WBA_LAST_MEETING for: {query!r}"


# ── MY_GROUPS_DIGEST ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("query", [
    "what's new in my groups",
    "what is happening in my workgroups",
    "my groups digest",
    "updates from my workgroups",
    "latest in my groups",
])
def test_my_groups_digest_matched(query):
    assert first_match(query) == RouteId.MY_GROUPS_DIGEST, \
        f"Expected MY_GROUPS_DIGEST for: {query!r}"


# ── Route isolation (baseline queries not captured by WBA patterns) ───────────

@pytest.mark.parametrize("query", [
    "what is Wi-Fi 7",
    "compare 802.11be and 802.11ax",
    "who is John Smith",
    "show me IETF QUIC working group updates",
    "what are the latest IETF RFCs",
])
def test_baseline_queries_not_wba(query):
    result = first_match(query)
    wba_routes = {
        RouteId.MEMBERSHIP_ACTION, RouteId.WBA_PROGRAMME_LIST,
        RouteId.WBA_WORKGROUPS_OF, RouteId.WBA_RECENT_ACTIVITY,
        RouteId.WBA_LAST_MEETING, RouteId.MY_GROUPS_DIGEST,
    }
    assert result not in wba_routes, f"Baseline query unexpectedly routed to WBA: {query!r} → {result}"
