"""Tests for "X working group" recency routing.

Production query "what is the latest from the bgp working group" previously
fell through to RouteId.GENERIC_SEARCH because no router pattern recognised
"working group" (two words) variants. It now routes to RECENT_CONTENT, and
the RECENT_CONTENT template's workgroup filter CONTAINS-matches against
DataSource name/id so a short token like "BGP" resolves to the actual
datasource "IETF BGP Enabled Services (BESS)" / "ietf_wg_bess".
"""

import pytest

from src.models.route_plan import RouteId
from src.services.local_router import LocalRouter
from src.services.query_template_registry import QueryTemplateRegistry


@pytest.mark.parametrize("question", [
    "what is the latest from the bgp working group",
    "what is the latest from the BGP working group",
    "latest news from the quic working group",
    "what's happening in the tls wg",
    "what's new from the bgp wg",
    "tls working group news",
    "quic wg updates",
    "bgp working group activity",
])
def test_working_group_recency_routes_to_recent_content(question):
    """Generic "X working group / wg / workgroup" recency queries → RECENT_CONTENT."""
    router = LocalRouter()
    route_id, confidence = router._match_route_pattern(question)
    assert route_id == RouteId.RECENT_CONTENT, f"got {route_id} for {question!r}"
    assert confidence > 0


@pytest.mark.parametrize("question", [
    "what is wi-fi 7",                          # Definition query — must NOT match
    "list workgroups in WBA",                   # WBA listing
    "what programmes are available in WBA",     # WBA listing
])
def test_working_group_pattern_does_not_overreach(question):
    """The new patterns must not catch non-workgroup queries."""
    router = LocalRouter()
    route_id, _ = router._match_route_pattern(question)
    assert route_id != RouteId.RECENT_CONTENT, (
        f"unexpectedly matched RECENT_CONTENT for {question!r} (got {route_id})"
    )


def test_recent_content_cypher_includes_workgroup_contains_branch():
    """The RECENT_CONTENT Cypher must allow CONTAINS-resolution of workgroup names
    so "BGP" can match a DataSource named "IETF BGP Enabled ServiceS (BESS)".
    """
    reg = QueryTemplateRegistry()
    tpl = reg.get_template(RouteId.RECENT_CONTENT)
    assert tpl is not None
    cypher = tpl.cypher
    # The new branch is keyed on "ANY(wg IN $workgroups WHERE ... CONTAINS ...)"
    assert "ANY(wg IN $workgroups" in cypher
    assert "toLower(ds.name) CONTAINS toLower(wg)" in cypher
    assert "toLower(ds.datasource_id) CONTAINS toLower(wg)" in cypher
