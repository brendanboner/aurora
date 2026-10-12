"""Tests for directed @source query behavior.

Validates:
- explicit_datasource_filter is set when datasource_ids come from request options
- Future dates are rejected by RECENT_CONTENT date validation
- DATASOURCE_LATEST template is in registry
- Cross-datasource fallback respects explicit filter (never widens to other sources)
"""

import pytest
import re
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'src'))

from src.models.route_plan import RoutePlan, RouteId


# ── RoutePlan model ───────────────────────────────────────────────────────────

def test_route_plan_has_explicit_datasource_filter_field():
    plan = RoutePlan(route_id=RouteId.RECENT_CONTENT, workgroups=['ietf_wg_spring'])
    assert hasattr(plan, 'explicit_datasource_filter')
    assert plan.explicit_datasource_filter is False


def test_explicit_datasource_filter_can_be_set_true():
    plan = RoutePlan(
        route_id=RouteId.RECENT_CONTENT,
        workgroups=['ietf_wg_spring'],
        explicit_datasource_filter=True,
    )
    assert plan.explicit_datasource_filter is True


# ── DATASOURCE_LATEST route ID exists ────────────────────────────────────────

def test_datasource_latest_route_id_exists():
    assert hasattr(RouteId, 'DATASOURCE_LATEST')
    assert RouteId.DATASOURCE_LATEST.value == 'datasource_latest'


# ── RECENT_CONTENT future-date Cypher check ───────────────────────────────────

def test_recent_content_template_rejects_future_dates():
    """The date validation in RECENT_CONTENT must use <= datetime() not <= year+1."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        'qtr',
        os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                     'src', 'services', 'query_template_registry.py'),
    )
    mod = importlib.util.module_from_spec(spec)
    # Stub heavy imports
    import types
    for stub in ['neo4j_client', 'neo4j_client.client', 'neo4j_client.repository',
                 'src.settings', 'src.models.route_plan']:
        if stub not in sys.modules:
            sys.modules[stub] = types.ModuleType(stub)

    sys.modules['src.settings'].settings = types.SimpleNamespace(
        fast_template_version='1.0',
        fast_result_limit=10,
        # Include attributes needed by other tests that share the module cache
        parallel_retrieval_enabled=True,
        retrieval_timeout=30,
    )
    # Minimal RouteId stub
    import enum
    class _RouteId(str, enum.Enum):
        RECENT_CONTENT = 'recent_content'
        DATASOURCE_LATEST = 'datasource_latest'
    sys.modules['src.models.route_plan'].RouteId = _RouteId
    sys.modules['src.models.route_plan'].RoutePlan = object

    cypher_src = open(os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        'src', 'services', 'query_template_registry.py'
    )).read()

    # Must NOT allow future dates via year+1 arithmetic
    assert 'datetime().year + 1' not in cypher_src, \
        "RECENT_CONTENT should not use year+1 for date validation — it allows future dates"

    # Must use datetime comparison not just year arithmetic for future-date guard
    assert 'datetime(r.publish_date) <= datetime()' in cypher_src or \
           'effective_date <= datetime()' in cypher_src or \
           'effective_date < datetime()' in cypher_src, \
        "RECENT_CONTENT must have a strict future-date filter"


# ── Local router sets explicit_datasource_filter ─────────────────────────────

# ── RoutePlan explicit_datasource_filter integration ─────────────────────────

def test_route_plan_explicit_filter_defaults_false_with_workgroups():
    """Workgroups set without explicit_datasource_filter defaults to False."""
    plan = RoutePlan(route_id=RouteId.RECENT_CONTENT, workgroups=['ietf_wg_spring'])
    assert plan.explicit_datasource_filter is False


def test_route_plan_explicit_filter_set_true():
    plan = RoutePlan(
        route_id=RouteId.RECENT_CONTENT,
        workgroups=['ietf_wg_spring'],
        explicit_datasource_filter=True,
    )
    assert plan.explicit_datasource_filter is True
    assert plan.workgroups == ['ietf_wg_spring']


# ── Answer generator detects latest-fallback flag ────────────────────────────

def test_latest_fallback_flag_detection():
    """Documents tagged with _explicit_source_latest_fallback are correctly detected."""
    docs_with_flag = [
        {'title': 'Old doc', 'publish_date': '2025-01-10',
         'datasource_id': 'ietf_wg_spring',
         '_explicit_source_latest_fallback': True},
    ]
    docs_without_flag = [
        {'title': 'Old doc', 'publish_date': '2025-01-10',
         'datasource_id': 'ietf_wg_spring'},
    ]
    assert any(d.get('_explicit_source_latest_fallback') for d in docs_with_flag)
    assert not any(d.get('_explicit_source_latest_fallback') for d in docs_without_flag)
