"""Tests for clickable links in rollup digest summaries.

Background: production users see deterministic recency digests like:

    **IETF BGP Enabled Services (BESS)** — June 01 - June 02, 2026
    48 document(s).
    Documents:
    - **Wg Update — Ietf 125 Bgp Enabled Services** (2026-03-17) [presentation]

Document titles weren't hyperlinked, so users had to use the citations
panel to navigate. The rollup_generator now wraps each title in a
markdown link `[title](url)` when a URL is available.
"""

from datetime import date
from unittest.mock import MagicMock

from src.services.rollup_generator import RollupGenerator


def _gen() -> RollupGenerator:
    # _generate_summary is pure; skip the heavy __init__ by constructing without engines.
    gen = RollupGenerator.__new__(RollupGenerator)
    return gen


def test_summary_wraps_titles_in_markdown_links_when_url_present():
    docs = [
        {
            "title": "Wg Update — Ietf 125 Bgp Enabled Services",
            "url": "https://datatracker.ietf.org/doc/wg-update-ietf-125",
            "publish_date": "2026-03-17",
            "doc_type": "presentation",
            "summary": "",
        }
    ]
    summary = _gen()._generate_summary(
        workgroup_name="IETF BGP Enabled Services (BESS)",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        events=[],
        docs=docs,
        period_type="week",
    )
    assert (
        "[Wg Update — Ietf 125 Bgp Enabled Services]"
        "(https://datatracker.ietf.org/doc/wg-update-ietf-125)"
    ) in summary
    assert "(2026-03-17)" in summary
    assert "[presentation]" in summary


def test_summary_falls_back_to_plain_title_when_no_url():
    docs = [
        {
            "title": "Untitled-but-not-the-string-untitled",
            "url": "",
            "publish_date": "2026-03-17",
            "doc_type": "memo",
        }
    ]
    summary = _gen()._generate_summary(
        workgroup_name="Test",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        events=[],
        docs=docs,
        period_type="day",
    )
    assert "**Untitled-but-not-the-string-untitled**" in summary
    assert "](" not in summary  # no markdown link rendered


def test_summary_escapes_bracket_in_title():
    docs = [
        {
            "title": "Action [Item] discussed",
            "url": "https://example.com/doc",
            "publish_date": "2026-03-17",
        }
    ]
    summary = _gen()._generate_summary(
        workgroup_name="Test",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        events=[],
        docs=docs,
        period_type="day",
    )
    # The closing ']' inside the title is escaped so the markdown link parses correctly.
    assert "[Action [Item\\] discussed](https://example.com/doc)" in summary


def test_summary_skips_docs_with_literal_untitled_title():
    docs = [
        {"title": "Untitled", "url": "https://example.com/doc"},
        {"title": "Real Doc", "url": "https://example.com/real"},
    ]
    summary = _gen()._generate_summary(
        workgroup_name="Test",
        start_date=date(2026, 6, 1),
        end_date=date(2026, 6, 2),
        events=[],
        docs=docs,
        period_type="day",
    )
    assert "Untitled" not in summary
    assert "[Real Doc](https://example.com/real)" in summary
