"""Tests for category alias expansion in query templates.

Production has hundreds of distinct `r.category` values across ingestion
sources (e.g. WBA Newsroom tags content as 'newsroom'; Wi-Fi Alliance uses
'press release'; some IETF flows use 'press_release'). Templates that
filter on exact category match would miss obvious related buckets — these
tests pin the alias-expansion behaviour that fixes that.
"""
import pytest

from src.models.route_plan import RouteId, RoutePlan
from src.services.query_template_registry import (
    CATEGORY_ALIASES,
    QueryTemplateRegistry,
    expand_category_aliases,
)


def test_press_release_expands_to_newsroom_etc():
    aliases = expand_category_aliases("press release")
    assert "press release" in aliases
    assert "newsroom" in aliases
    assert "press_release" in aliases


def test_unknown_category_returns_just_itself():
    aliases = expand_category_aliases("hieroglyphic_carvings")
    assert aliases == ["hieroglyphic_carvings"]


def test_none_category_returns_empty_list():
    assert expand_category_aliases(None) == []
    assert expand_category_aliases("") == []


def test_case_insensitive():
    aliases = expand_category_aliases("Press Release")
    assert "newsroom" in aliases


def test_meeting_minutes_aliases_cover_observed_variants():
    aliases = expand_category_aliases("meeting minutes")
    assert "meeting minutes" in aliases
    assert "minutes & attendance" in aliases
    assert "3-minutes" in aliases


def test_build_params_passes_category_aliases():
    reg = QueryTemplateRegistry()
    tpl = reg.get_template(RouteId.RECENT_PUBLICATIONS)
    plan = RoutePlan(
        route_id=RouteId.RECENT_PUBLICATIONS,
        category="press release",
        raw_query="what is the latest press release",
    )
    params = tpl.build_params(plan)
    assert params["category"] == "press release"
    assert "newsroom" in params["category_aliases"]
    assert "press release" in params["category_aliases"]


def test_build_params_empty_aliases_when_no_category():
    reg = QueryTemplateRegistry()
    tpl = reg.get_template(RouteId.RECENT_PUBLICATIONS)
    plan = RoutePlan(
        route_id=RouteId.RECENT_PUBLICATIONS,
        raw_query="what's new",
    )
    params = tpl.build_params(plan)
    assert params["category_aliases"] == []


def test_category_filter_widens_window_and_drops_conflicting_topics():
    """When the router extracted 'press release' as both category and topic,
    build_params should: (1) keep the category, (2) drop 'press release' from
    topics so rows tagged with the alias 'newsroom' aren't excluded by a
    topic AND that they can't satisfy, (3) extend the date lookback to 365
    days since user is asking for the latest-of-category, not last-week."""
    reg = QueryTemplateRegistry()
    tpl = reg.get_template(RouteId.RECENT_PUBLICATIONS)
    plan = RoutePlan(
        route_id=RouteId.RECENT_PUBLICATIONS,
        category="press release",
        topics=["press release", "wi-fi"],
        relative_days=7,
        raw_query="what is the latest press release",
    )
    params = tpl.build_params(plan)
    assert params["category"] == "press release"
    # "press release" stripped from topics (it's the category); "wi-fi" stays.
    assert "press release" not in [t.lower() for t in params["topics"]]
    assert any("wi-fi" in t.lower() for t in params["topics"])
    # Window widened to 365 days
    assert params["relative_days"] == 365
    # Organizations cleared as part of the existing press-release adjustment
    assert params["organizations"] == []


def test_category_filter_respects_explicit_dates():
    """If the user typed an explicit temporal phrase ("in the last week"),
    honour it. The override widens only when the user did NOT request a
    specific window — i.e. plain "latest press release"."""
    from datetime import date
    reg = QueryTemplateRegistry()
    tpl = reg.get_template(RouteId.RECENT_PUBLICATIONS)
    plan = RoutePlan(
        route_id=RouteId.RECENT_PUBLICATIONS,
        category="press release",
        start_date=date(2026, 5, 27),
        end_date=date(2026, 6, 3),
        relative_days=7,
        raw_query="press releases in the last week",
    )
    params = tpl.build_params(plan)
    # "in the last week" → user-specified window honoured
    assert params["start_date"] == "2026-05-27"
    assert params["end_date"] == "2026-06-03"
    assert params["relative_days"] == 7


def test_category_filter_widens_even_when_router_set_dates():
    """Plain 'latest press release' without an explicit "in the last X"
    phrase: even if the router heuristically set a 7-day window, widen to
    365d so we surface the most recent press release across the year."""
    from datetime import date
    reg = QueryTemplateRegistry()
    tpl = reg.get_template(RouteId.RECENT_PUBLICATIONS)
    plan = RoutePlan(
        route_id=RouteId.RECENT_PUBLICATIONS,
        category="press release",
        start_date=date(2026, 5, 27),  # set by router heuristic
        end_date=date(2026, 6, 3),
        relative_days=7,
        raw_query="what is the latest press release?",
    )
    params = tpl.build_params(plan)
    assert params["relative_days"] == 365
    assert params["start_date"] is None
    assert params["end_date"] is None
