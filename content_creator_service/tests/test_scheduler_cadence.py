"""Cadence-alignment unit tests.

The scheduler used to drift earlier each day because the cadence window was
23h (less than a full day). These tests pin down the post-fix behaviour:
daily/weekly runs are anchored to the agent's created_at time-of-day.
"""
from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCHEDULER_SOURCE = ROOT / "src" / "services" / "scheduler.py"


def _load_helper():
    """Load only the module-level helper without triggering DB-bound imports.

    The scheduler module's class body imports siblings that hit Postgres /
    Neo4j on construction; the helper itself is pure, so we extract it via
    AST trimming and exec into a fresh module.
    """
    import ast
    source = SCHEDULER_SOURCE.read_text()
    tree = ast.parse(source)
    keep = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            continue
        if isinstance(node, ast.Import):
            keep.append(node)
            continue
        if isinstance(node, ast.Assign) and any(
            getattr(t, "id", None) == "CADENCE_WINDOWS" for t in node.targets
        ):
            keep.append(node)
            continue
        if isinstance(node, ast.AnnAssign) and getattr(node.target, "id", None) == "CADENCE_WINDOWS":
            keep.append(node)
            continue
        if isinstance(node, ast.FunctionDef) and node.name == "compute_next_run_at":
            keep.append(node)
            continue
    trimmed = ast.Module(body=keep, type_ignores=[])
    ast.fix_missing_locations(trimmed)
    mod = type(sys)("scheduler_helper_under_test")
    mod.__dict__["datetime"] = datetime
    mod.__dict__["timedelta"] = timedelta
    mod.__dict__["timezone"] = timezone
    from typing import Optional
    mod.__dict__["Optional"] = Optional
    exec(compile(trimmed, str(SCHEDULER_SOURCE), "exec"), mod.__dict__)
    return mod


HELPER = _load_helper()
compute_next_run_at = HELPER.compute_next_run_at


def test_first_post_lands_at_creation_time():
    created = datetime(2026, 6, 1, 9, 30, tzinfo=timezone.utc)
    assert compute_next_run_at(cadence="daily", created_at=created, last_run=None) == created


def test_daily_next_slot_is_creation_hour_next_day():
    created = datetime(2026, 6, 1, 9, 30, tzinfo=timezone.utc)
    last_run = datetime(2026, 6, 1, 9, 35, tzinfo=timezone.utc)
    assert compute_next_run_at(cadence="daily", created_at=created, last_run=last_run) == \
        datetime(2026, 6, 2, 9, 30, tzinfo=timezone.utc)


def test_daily_does_not_drift_when_previous_run_was_early():
    """Anchoring on created_at means no inheritable drift from a slightly-early run."""
    created = datetime(2026, 6, 1, 9, 30, tzinfo=timezone.utc)
    last_run = datetime(2026, 6, 1, 8, 0, tzinfo=timezone.utc)  # 90 min early
    # base = last_run + 23h = 2026-06-02 07:00 → snap up to 09:30 same day
    assert compute_next_run_at(cadence="daily", created_at=created, last_run=last_run) == \
        datetime(2026, 6, 2, 9, 30, tzinfo=timezone.utc)


def test_weekly_matches_weekday_and_hour():
    # Monday 2026-06-01 at 14:00 UTC — weekday()==0
    created = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    last_run = datetime(2026, 6, 1, 14, 0, tzinfo=timezone.utc)
    assert compute_next_run_at(cadence="weekly", created_at=created, last_run=last_run) == \
        datetime(2026, 6, 8, 14, 0, tzinfo=timezone.utc)


def test_unknown_cadence_returns_none():
    created = datetime(2026, 6, 1, 9, 0, tzinfo=timezone.utc)
    assert compute_next_run_at(cadence="per-event", created_at=created, last_run=None) is None


def test_naive_datetimes_are_treated_as_utc():
    created = datetime(2026, 6, 1, 9, 30)  # naive
    last_run = datetime(2026, 6, 1, 9, 30)  # naive
    out = compute_next_run_at(cadence="daily", created_at=created, last_run=last_run)
    assert out == datetime(2026, 6, 2, 9, 30, tzinfo=timezone.utc)
