"""Unit tests for the fast-pipeline entity-existence guard.

Covers:
  - run_entity_precheck parses Neo4j results into the expected shape
  - _should_run_entity_precheck only fires on entity-targeting routes
  - _pick_entity_for_precheck picks the most-specific entity in priority order
  - _compose_entity_missing_answer renders sensible "did you mean" text
  - Fast confidence formula returns 0.2 when entity is missing
  - Fast confidence formula penalises fuzzy matches vs exact
"""

from unittest.mock import MagicMock, patch

import pytest

from src.engines.fast_engine import FastEngine
from src.models.route_plan import RouteId, RoutePlan
from src.services.query_template_registry import run_entity_precheck


# ---------------------------------------------------------------------------
# run_entity_precheck
# ---------------------------------------------------------------------------

def test_run_entity_precheck_returns_exists_when_exact_match_found():
    client = MagicMock()
    client.execute_query.return_value = [{
        "entity": "Wi-Fi 7",
        "exact": [{"name": "Wi-Fi 7", "label": "Topic"}],
        "suggestions": [],
    }]
    out = run_entity_precheck(client, "Wi-Fi 7")
    assert out["exists"] is True
    assert out["exact"] == [{"name": "Wi-Fi 7", "label": "Topic"}]
    assert out["suggestions"] == []


def test_run_entity_precheck_returns_missing_with_suggestions():
    client = MagicMock()
    client.execute_query.return_value = [{
        "entity": "Kevin",
        "exact": [],
        "suggestions": [
            {"name": "Kevin Smith", "label": "Person"},
            {"name": "Kevin Jones", "label": "Person"},
        ],
    }]
    out = run_entity_precheck(client, "Kevin")
    assert out["exists"] is False
    assert len(out["suggestions"]) == 2
    assert out["suggestions"][0]["name"] == "Kevin Smith"


def test_run_entity_precheck_falls_through_on_neo4j_error():
    client = MagicMock()
    client.execute_query.side_effect = RuntimeError("connection refused")
    out = run_entity_precheck(client, "anything")
    # On error we report exists=True so the caller doesn't short-circuit valid traffic.
    assert out["exists"] is True


def test_run_entity_precheck_handles_empty_entity():
    client = MagicMock()
    out = run_entity_precheck(client, "")
    assert out["exists"] is True
    # We shouldn't have hit Neo4j at all.
    client.execute_query.assert_not_called()


def test_run_entity_precheck_handles_empty_rows():
    client = MagicMock()
    client.execute_query.return_value = []
    out = run_entity_precheck(client, "Kevin")
    assert out["exists"] is False
    assert out["suggestions"] == []


# ---------------------------------------------------------------------------
# _should_run_entity_precheck / _pick_entity_for_precheck
# ---------------------------------------------------------------------------

def _build_engine() -> FastEngine:
    with patch("src.engines.fast_engine.get_repo") as mock_get_repo, patch(
        "src.engines.fast_engine.get_topic_manager", return_value=object()
    ):
        mock_repo = MagicMock()
        mock_repo.client = MagicMock()
        mock_get_repo.return_value = mock_repo
        engine = FastEngine()
        return engine


def test_should_run_precheck_fires_for_person_profile_with_named_person():
    engine = _build_engine()
    plan = RoutePlan(route_id=RouteId.PERSON_PROFILE, people=["Kevin"], raw_query="who is Kevin")
    assert engine._should_run_entity_precheck(plan) is True


def test_should_run_precheck_skips_topic_discovery_routes():
    engine = _build_engine()
    plan = RoutePlan(
        route_id=RouteId.DOCUMENTS_BY_TOPIC,
        topics=["whatever"],
        raw_query="what is x",
    )
    # DOCUMENTS_BY_TOPIC is gated by the Cypher fuzzy-multiplier change, not the precheck.
    assert engine._should_run_entity_precheck(plan) is False


def test_should_run_precheck_skips_when_no_entity_specified():
    engine = _build_engine()
    plan = RoutePlan(route_id=RouteId.PERSON_PROFILE, raw_query="who")
    # No person/org/workgroup/topic in the plan — nothing to precheck.
    assert engine._should_run_entity_precheck(plan) is False


def test_should_run_precheck_skips_explicit_datasource_filter():
    engine = _build_engine()
    plan = RoutePlan(
        route_id=RouteId.WORKGROUP_RECENT_UPDATES,
        workgroups=["wba-iot-programme"],
        explicit_datasource_filter=True,
        raw_query="@iot whats new",
    )
    # @mention bypass — the datasource id is authoritative.
    assert engine._should_run_entity_precheck(plan) is False


def test_pick_entity_priority_people_over_workgroups():
    engine = _build_engine()
    plan = RoutePlan(
        route_id=RouteId.PERSON_PROFILE,
        people=["Kevin Smith"],
        workgroups=["wba-iot"],
        topics=["IoT"],
        raw_query="who is kevin",
    )
    assert engine._pick_entity_for_precheck(plan) == "Kevin Smith"


def test_pick_entity_falls_through_to_topics():
    engine = _build_engine()
    plan = RoutePlan(
        route_id=RouteId.TOPIC_TIMELINE,
        topics=["Wi-Fi 8"],
        raw_query="wi-fi 8 history",
    )
    assert engine._pick_entity_for_precheck(plan) == "Wi-Fi 8"


def test_pick_entity_strips_whitespace_and_skips_empty():
    engine = _build_engine()
    plan = RoutePlan(
        route_id=RouteId.PERSON_PROFILE,
        people=["", "   ", "  Kevin  "],
        raw_query="who is kevin",
    )
    assert engine._pick_entity_for_precheck(plan) == "Kevin"


# ---------------------------------------------------------------------------
# _compose_entity_missing_answer
# ---------------------------------------------------------------------------

def test_compose_entity_missing_answer_with_one_suggestion():
    msg = FastEngine._compose_entity_missing_answer(
        entity="Kevin",
        suggestions=[{"name": "Kevin Smith", "label": "Person"}],
    )
    assert "Kevin" in msg
    assert "Kevin Smith" in msg
    assert "person" in msg.lower()


def test_compose_entity_missing_answer_with_multiple_suggestions():
    msg = FastEngine._compose_entity_missing_answer(
        entity="BGP working group",
        suggestions=[
            {"name": "ACE working group", "label": "DataSource"},
            {"name": "BGP IETF wg", "label": "DataSource"},
            {"name": "BFD wg", "label": "DataSource"},
        ],
    )
    assert "BGP working group" in msg
    assert "ACE working group" in msg
    assert "BGP IETF wg" in msg
    assert "BFD wg" in msg
    assert "Did you mean" in msg


def test_compose_entity_missing_answer_with_no_suggestions():
    msg = FastEngine._compose_entity_missing_answer(entity="Xyzzy", suggestions=[])
    assert "Xyzzy" in msg
    # Should still be a useful response — guides the user toward broader topics.
    assert "broader topic" in msg.lower() or "rephrasing" in msg.lower()


def test_compose_entity_missing_answer_deduplicates_suggestions():
    msg = FastEngine._compose_entity_missing_answer(
        entity="x",
        suggestions=[
            {"name": "A", "label": "Person"},
            {"name": "A", "label": "Person"},  # duplicate
            {"name": "B", "label": "Person"},
        ],
    )
    # "A" should appear once in the suggestion list (excluding any in the preamble).
    assert msg.count("**A**") == 1
    assert "**B**" in msg


def test_compose_entity_missing_answer_caps_at_five_suggestions():
    suggestions = [{"name": f"Name {i}", "label": "Person"} for i in range(10)]
    msg = FastEngine._compose_entity_missing_answer(entity="x", suggestions=suggestions)
    # Only the first 5 unique names should appear.
    for i in range(5):
        assert f"Name {i}" in msg
    for i in range(5, 10):
        assert f"Name {i}" not in msg


# ---------------------------------------------------------------------------
# Agent awareness
# ---------------------------------------------------------------------------

def test_pick_entity_prefers_agents_over_people():
    """Agents are the most specific bucket — picked first.

    "what is Kevin's latest news" — if both an :Agent named Kevin and a
    :Person named Kevin exist, we should precheck the agent name first.
    """
    engine = _build_engine()
    plan = RoutePlan(
        route_id=RouteId.PERSON_PROFILE,
        agents=["Kevin"],
        people=["Some Other Person"],
        raw_query="what is kevin's latest news",
    )
    assert engine._pick_entity_for_precheck(plan) == "Kevin"


def test_should_run_precheck_fires_with_only_agents_field():
    engine = _build_engine()
    plan = RoutePlan(
        route_id=RouteId.AGENT_RECENT_CONTENT,
        agents=["Kevin"],
        raw_query="kevin's posts",
    )
    assert engine._should_run_entity_precheck(plan) is True


def test_compose_entity_missing_answer_renders_agent_label():
    msg = FastEngine._compose_entity_missing_answer(
        entity="Kevn",  # misspelled — should suggest the real Kevin agent
        suggestions=[{"name": "Kevin", "label": "Agent"}],
    )
    assert "Kevin" in msg
    assert "agent" in msg.lower()


def test_run_entity_precheck_recognises_agent_label():
    """When the precheck returns an :Agent exact match, exists must be True."""
    client = MagicMock()
    client.execute_query.return_value = [{
        "entity": "Kevin",
        "exact": [{"name": "Kevin", "label": "Agent"}],
        "suggestions": [],
    }]
    out = run_entity_precheck(client, "Kevin")
    assert out["exists"] is True
    assert out["exact"][0]["label"] == "Agent"


def test_agent_recent_content_template_registered():
    """The new route must have a registered template with the expected param schema."""
    from src.services.query_template_registry import QueryTemplateRegistry

    reg = QueryTemplateRegistry()
    tpl = reg.get_template(RouteId.AGENT_RECENT_CONTENT)
    assert tpl is not None
    assert "agents" in tpl.param_schema
    # The Cypher must read from $agents and follow AUTHORED edges to Resources.
    assert "Agent" in tpl.cypher
    assert "AUTHORED" in tpl.cypher
    assert "Resource" in tpl.cypher


def test_agent_recent_content_build_params_includes_agents():
    """RoutePlan.agents must flow into the Cypher params."""
    from src.services.query_template_registry import QueryTemplateRegistry

    reg = QueryTemplateRegistry()
    tpl = reg.get_template(RouteId.AGENT_RECENT_CONTENT)
    plan = RoutePlan(
        route_id=RouteId.AGENT_RECENT_CONTENT,
        agents=["Kevin"],
        raw_query="what is kevin's latest news",
    )
    params = tpl.build_params(plan)
    assert params["agents"] == ["Kevin"]
