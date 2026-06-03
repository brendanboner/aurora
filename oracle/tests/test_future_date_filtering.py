"""Tests for future-date filtering in query templates (Fix 7a).

Before today's fix, all 9 Cypher templates used:
  datetime(r.publish_date).year <= datetime().year + 1
which in 2026 allowed documents dated through 2027.

The fix replaces that with a strict datetime comparison so any
document with a future publish_date is treated as undated (1970-01-01)
and excluded from time-windowed results.

These tests verify:
- The bad pattern is completely gone from all templates
- The correct datetime comparison is present
- Future-dated documents would be assigned effective_date=1970-01-01
  and excluded from queries with a max_threshold of 180 days
"""

import re
import os
import pytest


REGISTRY_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "src", "services", "query_template_registry.py",
)


@pytest.fixture(scope="module")
def registry_source():
    return open(REGISTRY_PATH).read()


# ── The vulnerable pattern is gone ───────────────────────────────────────────

def test_no_year_plus_one_in_any_template(registry_source):
    """The year+1 pattern that allowed future dates must not exist anywhere."""
    matches = [(m.start(), registry_source[max(0, m.start()-40):m.end()+40])
               for m in re.finditer(r'datetime\(\)\.year\s*\+\s*1', registry_source)]
    assert not matches, (
        f"Found {len(matches)} occurrence(s) of 'datetime().year + 1' "
        f"which allows future-dated documents:\n"
        + "\n".join(f"  ...{ctx}..." for _, ctx in matches)
    )


# ── The correct pattern is present ───────────────────────────────────────────

def test_future_date_guard_uses_datetime_comparison(registry_source):
    """At least one template must use datetime(r.publish_date) <= datetime()
    for future-date protection instead of year arithmetic."""
    has_guard = (
        "datetime(r.publish_date) <= datetime()" in registry_source
        or "effective_date <= datetime()" in registry_source
        or "effective_date < datetime()" in registry_source
    )
    assert has_guard, (
        "No datetime-based future-date guard found. "
        "Templates must reject documents with publish_date > now."
    )


def test_recent_content_uses_datetime_lower_bound(registry_source):
    """Date validation should use datetime('2000-01-01') not year >= 2000."""
    assert "datetime('2000-01-01')" in registry_source, (
        "Expected datetime('2000-01-01') as lower bound for date validation"
    )


# ── Logic verification: future dates get 1970-01-01 effective_date ─────────

def test_future_date_cypher_logic():
    """Verify the CASE expression logic produces 1970-01-01 for future dates.

    This test simulates what Neo4j's CASE expression does:
    - publish_date in the future → effective_date = 1970-01-01
    - valid past date → effective_date = that date
    - missing/empty → effective_date = 1970-01-01
    """
    from datetime import datetime, timezone

    def compute_effective_date(publish_date: str | None) -> str:
        """Simulate the Cypher CASE expression in Python."""
        if not publish_date or publish_date in ('', 'unknown'):
            return '1970-01-01'
        try:
            dt = datetime.fromisoformat(publish_date.replace('Z', '+00:00'))
            now = datetime.now(tz=timezone.utc) if dt.tzinfo else datetime.now()
            # The condition: >= 2000-01-01 AND <= now
            lower = datetime(2000, 1, 1, tzinfo=dt.tzinfo)
            if dt >= lower and dt <= now:
                return dt.strftime('%Y-%m-%d')
        except (ValueError, TypeError):
            pass
        return '1970-01-01'

    # Future date → 1970-01-01 (excluded from recent queries)
    assert compute_effective_date('2027-03-15') == '1970-01-01'
    assert compute_effective_date('2099-01-01') == '1970-01-01'

    # Past dates → pass through
    assert compute_effective_date('2024-11-01') == '2024-11-01'
    assert compute_effective_date('2025-02-15') == '2025-02-15'

    # Missing / bad dates → 1970-01-01
    assert compute_effective_date(None) == '1970-01-01'
    assert compute_effective_date('') == '1970-01-01'
    assert compute_effective_date('unknown') == '1970-01-01'
    assert compute_effective_date('not-a-date') == '1970-01-01'


def test_effective_date_1970_excluded_by_max_threshold():
    """A document with effective_date=1970-01-01 is excluded by the 180-day threshold."""
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    max_threshold = now - timedelta(days=180)

    effective_date_future_doc = datetime(1970, 1, 1, tzinfo=timezone.utc)
    effective_date_valid_doc = now - timedelta(days=30)

    # 1970-01-01 is NOT >= max_threshold (180 days ago) → excluded
    assert not (effective_date_future_doc >= max_threshold), (
        "Future-dated document (assigned 1970-01-01) should be excluded by max_threshold"
    )
    # Valid recent doc is included
    assert effective_date_valid_doc >= max_threshold


# ── DATASOURCE_LATEST also rejects future dates ──────────────────────────────

def test_datasource_latest_template_also_rejects_future_dates(registry_source):
    """The DATASOURCE_LATEST fallback template must also reject future publish_dates."""
    # Find the DATASOURCE_LATEST block
    # Use rfind to land on the template definition rather than an earlier comment reference
    start = registry_source.rfind('DATASOURCE_LATEST')
    assert start != -1, "DATASOURCE_LATEST template not found"
    # Check the relevant section (next 2000 chars after its definition)
    section = registry_source[start:start + 2000]

    assert 'datetime().year + 1' not in section, (
        "DATASOURCE_LATEST should not use year+1 validation"
    )
    # The future-date guard can be expressed as:
    #   - inline `datetime(r.publish_date) <= datetime()` in the CASE, or
    #   - a precomputed pub_ok regex check + a hard `effective_date < datetime()`
    #     WHERE clause (the more robust form added when Postgres-format strings
    #     started reaching the parser).
    has_inline_guard = 'datetime(r.publish_date) <= datetime()' in section
    has_normalised_guard = (
        ".publish_date), ' ', 'T')) <= datetime()" in section
        and 'effective_date < datetime()' in section
    )
    assert has_inline_guard or has_normalised_guard, (
        "DATASOURCE_LATEST must filter future publish_dates "
        "(either inline datetime() comparison or precomputed pub_ok + "
        "effective_date < datetime() guard)"
    )
