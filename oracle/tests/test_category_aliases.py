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
