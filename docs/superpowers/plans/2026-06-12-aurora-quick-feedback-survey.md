# Aurora Quick Feedback Survey Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a login-gated 2-minute survey at `/survey` that stores responses in Postgres and posts each submission to the Aurora Teams channel via the existing teams-agent service.

**Architecture:** New `survey_responses` Postgres table; new `POST /survey/submit` backend endpoint (auth required); fire-and-forget call to a new teams-agent `/internal/push-survey-result` endpoint that builds an Adaptive Card and pushes to a `survey-feedback` slug subscription; new React page at `/survey` rendered outside the standard app shell with its own CSS.

**Tech Stack:** FastAPI + psycopg2 (backend), React 18 + react-router (frontend), Node/TypeScript + restify + botbuilder (teams-agent), PostgreSQL.

**Spec:** `docs/superpowers/specs/2026-06-12-aurora-quick-feedback-survey-design.md`

---

## Conventions used in this plan

- Backend route module ships with its own router and is included in `backend/src/api.py` next to the existing `feedback` router.
- Frontend API calls hit the auth gateway as `/api/backend/<path>` via the shared `apiClient` axios instance in `frontend/src/services/api.js`.
- Postgres helpers live in `backend/src/services/postgres.py` and follow the existing `create_feedback` shape (single function, one INSERT, returning a dict).
- Teams-agent talks to the backend by URL: backend sends `httpx.post(...)` to `TEAMS_AGENT_URL + /internal/push-survey-result`, mirroring `content_creator_service/src/services/teams_notifier.py`. The `TEAMS_AGENT_URL` env var is already wired in `docker-compose.yml`; the **backend** service needs it added (it is currently only set on `content-creator-service` — Task 0 covers this).
- Migrations live in `prod-deployment/migrations/` and are applied via `make migrate` from the repo root. Numbering continues from existing files (next free number: `015`).
- Tests use the existing patterns: pytest with `unittest.mock.patch` for backend, jest + `@testing-library/react` for frontend.

---

## Task 0: Wire TEAMS_AGENT_URL into the backend container

**Files:**
- Modify: `docker-compose.yml`

The backend doesn't currently have `TEAMS_AGENT_URL` in its environment block (only the content-creator-service does). Without this, `survey_notifier.py` silently no-ops — the survey would persist but never reach Teams.

- [ ] **Step 1: Find the backend service block**

Run: `grep -n "^  backend:" docker-compose.yml`

Expected: a line number for the backend service definition.

- [ ] **Step 2: Add the env var**

Inside the backend service's `environment:` block (next to other internal-service URLs like `CURATOR_SERVICE_URL`), add:

```yaml
      TEAMS_AGENT_URL: ${TEAMS_AGENT_URL:-http://aurora-teams-agent:3978}
```

Use the same default as the existing entry on the content-creator service (`grep -n "TEAMS_AGENT_URL" docker-compose.yml` to confirm the exact form, lines ~655).

- [ ] **Step 3: Sanity-check**

Run: `grep -n "TEAMS_AGENT_URL" docker-compose.yml`

Expected: at least one match inside the `backend:` block (in addition to any existing matches in other services).

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git commit -m "chore(backend): expose TEAMS_AGENT_URL for survey notifier"
```

---

## Task 1: Postgres migration for `survey_responses`

**Files:**
- Create: `prod-deployment/migrations/015_survey_responses.sql`

- [ ] **Step 1: Write the migration**

```sql
-- 015_survey_responses.sql
-- Quick-feedback survey results captured at /survey.
-- One row per submission; unlimited re-submissions per user.

CREATE TABLE IF NOT EXISTS survey_responses (
    id                  BIGSERIAL    PRIMARY KEY,
    user_id             TEXT         NOT NULL REFERENCES app_users(id) ON DELETE CASCADE,
    user_email          TEXT,
    user_display_name   TEXT,
    submitted_at        TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    duration_seconds    INTEGER,
    client_user_agent   TEXT,
    responses           JSONB        NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_survey_responses_user_submitted
    ON survey_responses (user_id, submitted_at DESC);

COMMENT ON TABLE survey_responses
    IS 'Quick-feedback survey results captured at /survey during the Aurora trial';
COMMENT ON COLUMN survey_responses.responses
    IS 'JSONB blob keyed by qN_<slug>; shape validated at the API layer';
COMMENT ON COLUMN survey_responses.duration_seconds
    IS 'Client-reported time from page mount to submit; informational only';
```

- [ ] **Step 2: Apply locally and verify**

Run from repo root: `make migrate`

Then verify with `make migrate-status`. Expected output includes `015_survey_responses` listed as applied. If `make migrate` is not available locally, run the SQL directly against the dev Postgres via `docker compose exec postgres psql -U aurora -d aurora -f /path/to/015_survey_responses.sql`.

Confirm the table exists:

```bash
docker compose exec postgres psql -U aurora -d aurora -c '\d survey_responses'
```

Expected: column list matching the migration, with the index on `(user_id, submitted_at DESC)`.

- [ ] **Step 3: Commit**

```bash
git add prod-deployment/migrations/015_survey_responses.sql
git commit -m "feat(db): add survey_responses table for /survey results"
```

---

## Task 2: Backend `postgres.create_survey_response` helper

**Files:**
- Modify: `backend/src/services/postgres.py` (add a new function near the existing `create_feedback` at line ~1065)
- Create: `backend/tests/test_survey_postgres.py`

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_survey_postgres.py
"""Tests for postgres.create_survey_response."""

from unittest.mock import patch


def test_create_survey_response_returns_row():
    from backend.src.services.postgres import create_survey_response

    expected = {
        "id": 42,
        "user_id": "user-1",
        "user_email": "u1@example.com",
        "user_display_name": "User One",
        "submitted_at": "2026-06-12T10:00:00Z",
        "duration_seconds": 73,
        "client_user_agent": "Mozilla/5.0",
        "responses": {"q1_overall_rating": 4},
    }

    with patch("backend.src.services.postgres.fetchone", return_value=expected) as m:
        result = create_survey_response(
            user_id="user-1",
            user_email="u1@example.com",
            user_display_name="User One",
            duration_seconds=73,
            client_user_agent="Mozilla/5.0",
            responses={"q1_overall_rating": 4},
        )

    assert result == expected
    # The function should pass JSONB-serialised responses to the SQL layer.
    args = m.call_args.args
    assert "INSERT INTO survey_responses" in args[0]
    # Positional params order matches the function arg order in the SQL.
    assert args[1][0] == "user-1"
    assert args[1][5] == {"q1_overall_rating": 4}


def test_create_survey_response_handles_optional_fields():
    from backend.src.services.postgres import create_survey_response

    with patch("backend.src.services.postgres.fetchone", return_value={}) as m:
        create_survey_response(
            user_id="user-1",
            user_email=None,
            user_display_name=None,
            duration_seconds=None,
            client_user_agent=None,
            responses={"q1_overall_rating": 5},
        )

    args = m.call_args.args
    assert args[1] == (
        "user-1",
        None,
        None,
        None,
        None,
        {"q1_overall_rating": 5},
    )
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd backend && make install   # one-time, seeds .venv
PYTHONPATH=..:$PYTHONPATH .venv/bin/pytest tests/test_survey_postgres.py -v
```

Expected: FAIL with `ImportError: cannot import name 'create_survey_response'`.

- [ ] **Step 3: Add the helper**

Insert after the existing `create_feedback` function in `backend/src/services/postgres.py`:

```python
def create_survey_response(
    user_id: str,
    user_email: Optional[str],
    user_display_name: Optional[str],
    duration_seconds: Optional[int],
    client_user_agent: Optional[str],
    responses: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Insert one quick-feedback survey submission.

    Args:
        user_id: app_users.id of the submitter (FK enforced).
        user_email: snapshotted email for convenience in admin views.
        user_display_name: snapshotted name for convenience in admin views.
        duration_seconds: client-reported page-mount-to-submit time.
        client_user_agent: raw User-Agent header for diagnostics.
        responses: JSONB blob — keyed by qN_<slug>, validated upstream.

    Returns:
        The inserted row as a dict (id, user_id, ..., submitted_at, responses).
    """
    query = """
        INSERT INTO survey_responses (
            user_id, user_email, user_display_name,
            duration_seconds, client_user_agent, responses
        )
        VALUES (%s, %s, %s, %s, %s, %s)
        RETURNING id, user_id, user_email, user_display_name,
                  submitted_at, duration_seconds, client_user_agent, responses;
    """
    return fetchone(
        query,
        (user_id, user_email, user_display_name,
         duration_seconds, client_user_agent, responses),
    )
```

Note: psycopg2 serialises Python dicts to JSONB automatically when the target column is JSONB. If the project uses `psycopg2.extras.Json` elsewhere for JSONB columns (grep for `Json(`), wrap the `responses` parameter the same way to stay consistent. Otherwise the dict-direct form above is correct.

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=..:$PYTHONPATH .venv/bin/pytest tests/test_survey_postgres.py -v
```

Expected: PASS (both tests green).

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/postgres.py backend/tests/test_survey_postgres.py
git commit -m "feat(backend): add create_survey_response helper"
```

---

## Task 3: Backend Teams notifier — `survey_notifier.py`

**Files:**
- Create: `backend/src/services/survey_notifier.py`
- Create: `backend/tests/test_survey_notifier.py`

Mirrors the existing `content_creator_service/src/services/teams_notifier.py` pattern: fire-and-forget, short timeout, silently skipped when `TEAMS_AGENT_URL` is empty (Teams not deployed), failures logged at WARN.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_survey_notifier.py
"""Tests for survey_notifier.push_survey_result."""

from unittest.mock import patch, MagicMock


def _payload():
    return dict(
        user_email="u1@example.com",
        user_display_name="User One",
        submitted_at="2026-06-12T10:00:00Z",
        duration_seconds=73,
        responses={"q1_overall_rating": 4, "q11_would_use_again": "both"},
    )


def test_no_op_when_teams_agent_url_unset(monkeypatch):
    monkeypatch.setenv("TEAMS_AGENT_URL", "")
    # Force module-level cache reload so the env change takes effect.
    import importlib
    from backend.src.services import survey_notifier
    importlib.reload(survey_notifier)

    with patch("backend.src.services.survey_notifier.httpx.post") as m:
        survey_notifier.push_survey_result(**_payload())

    m.assert_not_called()


def test_posts_to_correct_endpoint(monkeypatch):
    monkeypatch.setenv("TEAMS_AGENT_URL", "http://teams-agent:3978")
    import importlib
    from backend.src.services import survey_notifier
    importlib.reload(survey_notifier)

    resp = MagicMock()
    resp.is_success = True
    with patch("backend.src.services.survey_notifier.httpx.post", return_value=resp) as m:
        survey_notifier.push_survey_result(**_payload())

    assert m.called
    url, = m.call_args.args
    assert url == "http://teams-agent:3978/internal/push-survey-result"
    kwargs = m.call_args.kwargs
    assert kwargs["json"]["user_email"] == "u1@example.com"
    assert kwargs["json"]["responses"]["q1_overall_rating"] == 4
    assert kwargs["timeout"] == 5


def test_failure_is_swallowed(monkeypatch, caplog):
    monkeypatch.setenv("TEAMS_AGENT_URL", "http://teams-agent:3978")
    import importlib
    from backend.src.services import survey_notifier
    importlib.reload(survey_notifier)

    with patch(
        "backend.src.services.survey_notifier.httpx.post",
        side_effect=RuntimeError("boom"),
    ):
        # Must NOT raise.
        survey_notifier.push_survey_result(**_payload())

    assert "Teams push failed" in caplog.text
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=..:$PYTHONPATH .venv/bin/pytest tests/test_survey_notifier.py -v
```

Expected: FAIL with `ModuleNotFoundError: backend.src.services.survey_notifier`.

- [ ] **Step 3: Write the notifier**

```python
# backend/src/services/survey_notifier.py
"""Fire-and-forget Teams push for /survey submissions.

Posts to the teams-agent's /internal/push-survey-result endpoint, which
builds an Adaptive Card and delivers it to channels subscribed to the
`survey-feedback` slug. Silently skipped when TEAMS_AGENT_URL is unset.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx

logger = logging.getLogger(__name__)

_TEAMS_AGENT_URL = os.getenv("TEAMS_AGENT_URL", "")


def push_survey_result(
    *,
    user_email: Optional[str],
    user_display_name: Optional[str],
    submitted_at: str,
    duration_seconds: Optional[int],
    responses: Dict[str, Any],
) -> None:
    """
    Fire-and-forget: POST a survey submission to teams-agent.

    Failure is logged at WARN but never raised — the survey row is already
    persisted by the time we get here, so the user-facing response is 200.
    """
    if not _TEAMS_AGENT_URL:
        return

    url = f"{_TEAMS_AGENT_URL.rstrip('/')}/internal/push-survey-result"
    payload = {
        "user_email":        user_email,
        "user_display_name": user_display_name,
        "submitted_at":      submitted_at,
        "duration_seconds":  duration_seconds,
        "responses":         responses,
    }

    try:
        resp = httpx.post(url, json=payload, timeout=5)
        if resp.is_success:
            logger.info("Teams push queued for survey from %s", user_email)
        else:
            logger.warning(
                "Teams push returned %d: %s",
                resp.status_code, resp.text[:200],
            )
    except Exception as exc:
        logger.warning("Teams push failed (non-fatal): %s", exc)
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=..:$PYTHONPATH .venv/bin/pytest tests/test_survey_notifier.py -v
```

Expected: PASS (all three tests green).

- [ ] **Step 5: Commit**

```bash
git add backend/src/services/survey_notifier.py backend/tests/test_survey_notifier.py
git commit -m "feat(backend): add fire-and-forget Teams notifier for surveys"
```

---

## Task 4: Backend route — `POST /survey/submit`

**Files:**
- Create: `backend/src/routes/survey.py`
- Create: `backend/tests/test_survey_route.py`

The contract: 11 questions with stable JSON keys. Q9 and Q10 are optional; everything else is required. Free-text Q10 capped at 500 chars.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/test_survey_route.py
"""Tests for POST /survey/submit."""

from unittest.mock import patch, AsyncMock
import pytest
from fastapi.testclient import TestClient


def _good_responses(**overrides):
    payload = {
        "q1_overall_rating": 4,
        "q2_findability": "easy",
        "q3_speed": "ok",
        "q4_accuracy": "mostly",
        "q5_citation_accuracy": "sometimes",
        "q6_hallucination": "never",
        "q7_works_best_for": ["specs", "events"],
        "q8_source_coverage": "mostly",
        "q9_missing_sources": ["ieee"],
        "q10_one_thing": "Better event filters.",
        "q11_would_use_again": "both",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def client():
    # Bypass auth_middleware for tests by patching require_user_context to a no-op.
    from backend.src.api import app
    return TestClient(app)


def _auth_headers():
    return {
        "X-User-Id": "user-1",
        "X-User-Email": "u1@example.com",
        "X-User-Role": "user",
        "User-Agent": "Mozilla/5.0 (test)",
    }


def test_submit_happy_path(client):
    inserted = {
        "id": 1,
        "user_id": "user-1",
        "user_email": "u1@example.com",
        "user_display_name": "User One",
        "submitted_at": "2026-06-12T10:00:00Z",
        "duration_seconds": 73,
        "client_user_agent": "Mozilla/5.0 (test)",
        "responses": _good_responses(),
    }

    with patch(
        "backend.src.routes.survey.postgres.create_survey_response",
        return_value=inserted,
    ) as p_create, patch(
        "backend.src.routes.survey.survey_notifier.push_survey_result"
    ) as p_push:
        r = client.post(
            "/survey/submit",
            json={"responses": _good_responses(), "duration_seconds": 73},
            headers=_auth_headers(),
        )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == 1
    assert body["responses"]["q1_overall_rating"] == 4
    p_create.assert_called_once()
    p_push.assert_called_once()


def test_submit_missing_required_question_rejected(client):
    bad = _good_responses()
    del bad["q4_accuracy"]
    r = client.post(
        "/survey/submit",
        json={"responses": bad, "duration_seconds": 50},
        headers=_auth_headers(),
    )
    assert r.status_code == 422


def test_submit_free_text_too_long_rejected(client):
    bad = _good_responses(q10_one_thing="x" * 501)
    r = client.post(
        "/survey/submit",
        json={"responses": bad, "duration_seconds": 50},
        headers=_auth_headers(),
    )
    assert r.status_code == 422


def test_submit_succeeds_even_if_teams_push_raises(client):
    inserted = {
        "id": 2, "user_id": "user-1", "user_email": "u1@example.com",
        "user_display_name": None, "submitted_at": "2026-06-12T10:00:00Z",
        "duration_seconds": 50, "client_user_agent": None,
        "responses": _good_responses(),
    }
    with patch(
        "backend.src.routes.survey.postgres.create_survey_response",
        return_value=inserted,
    ), patch(
        "backend.src.routes.survey.survey_notifier.push_survey_result",
        side_effect=RuntimeError("teams down"),
    ):
        r = client.post(
            "/survey/submit",
            json={"responses": _good_responses(), "duration_seconds": 50},
            headers=_auth_headers(),
        )

    # The notifier swallows its own errors; survey.py must also not let an
    # accidental exception break the user-facing response.
    assert r.status_code == 200
```

- [ ] **Step 2: Run test to verify it fails**

```bash
PYTHONPATH=..:$PYTHONPATH .venv/bin/pytest tests/test_survey_route.py -v
```

Expected: FAIL — module `backend.src.routes.survey` does not exist.

- [ ] **Step 3: Write the route module**

```python
# backend/src/routes/survey.py
"""Quick-feedback survey route — POST /survey/submit."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field, conint, conlist, constr
from typing import List, Literal, Optional
import logging

from common.auth_middleware import get_user_context, require_user_context
from src.services import postgres
from src.services import survey_notifier

router = APIRouter(prefix="/survey", tags=["Survey"])
logger = logging.getLogger(__name__)


# ── Question contract ──────────────────────────────────────────────────────
# Keys are stable (qN_<slug>). Wording can change in the UI without DDL.

Findability = Literal["very_easy", "easy", "ok", "hard"]
Speed = Literal["fast", "ok", "slow"]
Accuracy = Literal["very", "mostly", "mixed", "often_wrong"]
CitationAccuracy = Literal["yes", "sometimes", "rarely", "na"]
Hallucination = Literal["never", "once_or_twice", "often"]
WorksBestFor = Literal["specs", "people_orgs", "events", "trends", "other"]
SourceCoverage = Literal["yes", "mostly", "missing_some", "not_really"]
MissingSource = Literal["ietf", "ieee", "vendor_blogs", "internal_docs", "other"]
WouldUseAgain = Literal["web", "teams", "both", "no", "not_sure"]


class SurveyResponses(BaseModel):
    """Locked question contract for v1 of the quick-feedback survey."""

    q1_overall_rating: conint(ge=1, le=5)
    q2_findability: Findability
    q3_speed: Speed
    q4_accuracy: Accuracy
    q5_citation_accuracy: CitationAccuracy
    q6_hallucination: Hallucination
    q7_works_best_for: conlist(WorksBestFor, min_length=1, max_length=5)
    q8_source_coverage: SourceCoverage
    q9_missing_sources: Optional[List[MissingSource]] = None
    q10_one_thing: Optional[constr(max_length=500)] = None
    q11_would_use_again: WouldUseAgain


class SurveySubmit(BaseModel):
    responses: SurveyResponses
    duration_seconds: Optional[conint(ge=0, le=3600)] = None


@router.post("/submit")
@require_user_context
async def submit_survey(
    body: SurveySubmit,
    request: Request,
    user: Optional[dict] = Depends(get_user_context),
):
    """Persist one survey submission and fire-and-forget a Teams push."""
    user_agent = request.headers.get("user-agent")

    row = postgres.create_survey_response(
        user_id=user["user_id"],
        user_email=user.get("email"),
        user_display_name=user.get("display_name") or user.get("name"),
        duration_seconds=body.duration_seconds,
        client_user_agent=user_agent,
        responses=body.responses.model_dump(),
    )

    # Best-effort: never let a Teams push failure surface to the user.
    try:
        survey_notifier.push_survey_result(
            user_email=row.get("user_email"),
            user_display_name=row.get("user_display_name"),
            submitted_at=str(row.get("submitted_at")),
            duration_seconds=row.get("duration_seconds"),
            responses=row.get("responses") or body.responses.model_dump(),
        )
    except Exception as exc:
        logger.warning("Survey Teams push raised — swallowed: %s", exc)

    return row
```

- [ ] **Step 4: Run test to verify it passes**

```bash
PYTHONPATH=..:$PYTHONPATH .venv/bin/pytest tests/test_survey_route.py -v
```

Expected: PASS (all four tests green).

- [ ] **Step 5: Commit**

```bash
git add backend/src/routes/survey.py backend/tests/test_survey_route.py
git commit -m "feat(backend): add POST /survey/submit"
```

---

## Task 5: Register the survey router in `api.py`

**Files:**
- Modify: `backend/src/api.py:36-40` (router imports), `~line 80` (router registration)

- [ ] **Step 1: Add the import next to the other route imports**

In the block that reads:

```python
from src.routes import admin
from src.routes import events
from src.routes import feedback
from src.routes import documents
```

Add (alphabetical-ish, next to `feedback`):

```python
from src.routes import survey
```

- [ ] **Step 2: Register the router**

Next to the existing `app.include_router(feedback.router, prefix="")`, add:

```python
# Include survey routes
app.include_router(survey.router, prefix="")
```

- [ ] **Step 3: Smoke-test the import**

```bash
cd backend
PYTHONPATH=..:$PYTHONPATH .venv/bin/python -c "from src.api import app; print([r.path for r in app.routes if 'survey' in r.path])"
```

Expected output (one line): `['/survey/submit']`.

- [ ] **Step 4: Run the full backend test suite**

```bash
cd .. && make test-backend  # or: cd backend && make test
```

Expected: all tests pass (including the three new test files).

- [ ] **Step 5: Commit**

```bash
git add backend/src/api.py
git commit -m "feat(backend): mount /survey router"
```

---

## Task 6: Frontend API client — `submitSurvey`

**Files:**
- Modify: `frontend/src/services/api.js` (add next to existing `submitFeedback` at line ~687)

- [ ] **Step 1: Add the function**

```javascript
// Quick-feedback Survey (login-gated, /survey route)
export const submitSurvey = async (responses, durationSeconds) => {
  const response = await apiClient.post('/backend/survey/submit', {
    responses,
    duration_seconds: durationSeconds,
  });
  return response.data;
};
```

- [ ] **Step 2: Verify it's exported**

```bash
grep -n "submitSurvey" frontend/src/services/api.js
```

Expected: one match for the `export const` line.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/services/api.js
git commit -m "feat(frontend): submitSurvey API client"
```

---

## Task 7: Frontend Survey page — `Survey.jsx` and `Survey.css`

**Files:**
- Create: `frontend/src/pages/Survey.jsx`
- Create: `frontend/src/pages/Survey.css`

Visually independent: own CSS file, no theme imports. Octo logo + "Office of the CTO" wordmark in a top strip; eleven question cards stacked vertically; sticky progress bar; submit button locked until all required questions are answered; "Thanks!" screen post-submit.

- [ ] **Step 1: Write `Survey.css`**

```css
/* frontend/src/pages/Survey.css
 * Independent from the main app theme. No imports.
 * Mobile-first; chip buttons wrap; comfortable line lengths.
 */

.survey-root {
  --survey-bg: #f5f6fa;
  --survey-fg: #1a1d2b;
  --survey-muted: #5b6172;
  --survey-card: #ffffff;
  --survey-border: #e1e3ec;
  --survey-accent: #6b46c1;        /* purple */
  --survey-accent-soft: #ede9fe;
  --survey-accent-fg: #ffffff;
  --survey-danger: #d63b3b;
  --survey-radius: 12px;

  background: var(--survey-bg);
  color: var(--survey-fg);
  min-height: 100vh;
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  font-size: 16px;
  line-height: 1.45;
}

.survey-shell {
  max-width: 720px;
  margin: 0 auto;
  padding: 0 16px 80px;
}

.survey-header {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 20px 0 16px;
}

.survey-header img {
  height: 40px;
  width: 40px;
  border-radius: 8px;
}

.survey-header .wordmark {
  display: flex;
  flex-direction: column;
}

.survey-header .wordmark .small {
  font-size: 12px;
  letter-spacing: 0.08em;
  text-transform: uppercase;
  color: var(--survey-muted);
}

.survey-header .wordmark .title {
  font-size: 20px;
  font-weight: 600;
}

.survey-progress {
  position: sticky;
  top: 0;
  background: var(--survey-bg);
  padding: 8px 0 12px;
  z-index: 5;
  border-bottom: 1px solid var(--survey-border);
  font-size: 13px;
  color: var(--survey-muted);
}

.survey-progress-bar {
  height: 6px;
  background: var(--survey-border);
  border-radius: 999px;
  overflow: hidden;
  margin-top: 6px;
}

.survey-progress-bar > div {
  height: 100%;
  background: var(--survey-accent);
  transition: width 200ms ease-out;
}

.q-card {
  background: var(--survey-card);
  border: 1px solid var(--survey-border);
  border-radius: var(--survey-radius);
  padding: 18px 18px 16px;
  margin-top: 16px;
}

.q-title {
  font-weight: 600;
  margin: 0 0 12px;
}

.q-title .req {
  color: var(--survey-danger);
  margin-left: 2px;
}

.q-options {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
}

.q-chip {
  border: 1px solid var(--survey-border);
  background: #fff;
  border-radius: 999px;
  padding: 8px 14px;
  font: inherit;
  cursor: pointer;
  transition: background 120ms, border-color 120ms, color 120ms;
}

.q-chip:hover {
  border-color: var(--survey-accent);
}

.q-chip.selected {
  background: var(--survey-accent);
  color: var(--survey-accent-fg);
  border-color: var(--survey-accent);
}

.q-chip.star {
  font-size: 20px;
  line-height: 1;
  padding: 8px 12px;
}

.q-textarea {
  width: 100%;
  min-height: 90px;
  padding: 10px 12px;
  border-radius: 8px;
  border: 1px solid var(--survey-border);
  font: inherit;
  resize: vertical;
  background: #fff;
}

.q-char-count {
  text-align: right;
  font-size: 12px;
  color: var(--survey-muted);
  margin-top: 4px;
}

.survey-submit {
  margin-top: 24px;
  display: flex;
  justify-content: flex-end;
}

.survey-submit button {
  background: var(--survey-accent);
  color: var(--survey-accent-fg);
  border: none;
  border-radius: 8px;
  padding: 12px 24px;
  font: inherit;
  font-weight: 600;
  cursor: pointer;
}

.survey-submit button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.survey-thanks {
  text-align: center;
  padding: 80px 16px;
}

.survey-thanks h1 {
  font-size: 28px;
  margin-bottom: 8px;
}

.survey-thanks p {
  color: var(--survey-muted);
}

.survey-error {
  margin-top: 12px;
  color: var(--survey-danger);
  font-size: 14px;
}
```

- [ ] **Step 2: Write `Survey.jsx`**

```jsx
// frontend/src/pages/Survey.jsx
import React, { useMemo, useRef, useState } from 'react';
import { submitSurvey } from '../services/api';
import './Survey.css';

const QUESTIONS = [
  {
    key: 'q1_overall_rating',
    title: 'Overall, how would you rate Aurora?',
    required: true,
    type: 'stars',                  // 1..5
  },
  {
    key: 'q2_findability',
    title: 'Was it easy to find what you needed?',
    required: true,
    type: 'single',
    options: [
      { value: 'very_easy', label: 'Very easy' },
      { value: 'easy',      label: 'Easy' },
      { value: 'ok',        label: 'OK' },
      { value: 'hard',      label: 'Hard' },
    ],
  },
  {
    key: 'q3_speed',
    title: 'Speed felt…',
    required: true,
    type: 'single',
    options: [
      { value: 'fast', label: 'Fast' },
      { value: 'ok',   label: 'OK' },
      { value: 'slow', label: 'Slow' },
    ],
  },
  {
    key: 'q4_accuracy',
    title: "How accurate were Aurora's answers?",
    required: true,
    type: 'single',
    options: [
      { value: 'very',        label: 'Very accurate' },
      { value: 'mostly',      label: 'Mostly' },
      { value: 'mixed',       label: 'Mixed' },
      { value: 'often_wrong', label: 'Often wrong' },
    ],
  },
  {
    key: 'q5_citation_accuracy',
    title: 'Did Aurora cite the right sources?',
    required: true,
    type: 'single',
    options: [
      { value: 'yes',       label: 'Yes' },
      { value: 'sometimes', label: 'Sometimes' },
      { value: 'rarely',    label: 'Rarely' },
      { value: 'na',        label: 'N/A' },
    ],
  },
  {
    key: 'q6_hallucination',
    title: "Did Aurora invent things that weren't in the sources?",
    required: true,
    type: 'single',
    options: [
      { value: 'never',         label: 'Never' },
      { value: 'once_or_twice', label: 'Once or twice' },
      { value: 'often',         label: 'Often' },
    ],
  },
  {
    key: 'q7_works_best_for',
    title: 'What kind of question worked best? (pick any)',
    required: true,
    type: 'multi',
    options: [
      { value: 'specs',       label: 'Specs' },
      { value: 'people_orgs', label: 'People/orgs' },
      { value: 'events',      label: 'Events' },
      { value: 'trends',      label: 'Trends' },
      { value: 'other',       label: 'Other' },
    ],
  },
  {
    key: 'q8_source_coverage',
    title: 'Were the sources Aurora used the right ones?',
    required: true,
    type: 'single',
    options: [
      { value: 'yes',           label: 'Yes' },
      { value: 'mostly',        label: 'Mostly' },
      { value: 'missing_some',  label: 'Missing some' },
      { value: 'not_really',    label: 'Not really' },
    ],
  },
  {
    key: 'q9_missing_sources',
    title: 'What sources are missing? (optional, pick any)',
    required: false,
    type: 'multi',
    options: [
      { value: 'ietf',          label: 'IETF' },
      { value: 'ieee',          label: 'IEEE' },
      { value: 'vendor_blogs',  label: 'Vendor blogs' },
      { value: 'internal_docs', label: 'Internal docs' },
      { value: 'other',         label: 'Other' },
    ],
  },
  {
    key: 'q10_one_thing',
    title: 'One thing we should fix or add? (optional)',
    required: false,
    type: 'text',
    maxLength: 500,
  },
  {
    key: 'q11_would_use_again',
    title: 'Would you use Aurora again?',
    required: true,
    type: 'single',
    options: [
      { value: 'web',      label: 'Yes (web)' },
      { value: 'teams',    label: 'Yes (Teams)' },
      { value: 'both',     label: 'Both' },
      { value: 'no',       label: 'No' },
      { value: 'not_sure', label: 'Not sure' },
    ],
  },
];

const REQUIRED_KEYS = QUESTIONS.filter(q => q.required).map(q => q.key);

function isAnswered(q, value) {
  if (value === undefined || value === null) return false;
  if (q.type === 'multi') return Array.isArray(value) && value.length > 0;
  if (q.type === 'text')  return typeof value === 'string' && value.trim().length > 0;
  return true;
}

export default function Survey() {
  const [answers, setAnswers] = useState({});
  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);
  const [error, setError] = useState(null);
  const mountedAtRef = useRef(Date.now());

  const setAnswer = (key, value) => {
    setAnswers(prev => ({ ...prev, [key]: value }));
  };

  const toggleMulti = (key, value) => {
    setAnswers(prev => {
      const current = Array.isArray(prev[key]) ? prev[key] : [];
      const next = current.includes(value)
        ? current.filter(v => v !== value)
        : [...current, value];
      return { ...prev, [key]: next };
    });
  };

  const answeredCount = useMemo(
    () => QUESTIONS.filter(q => isAnswered(q, answers[q.key])).length,
    [answers]
  );

  const allRequiredAnswered = useMemo(
    () => REQUIRED_KEYS.every(k => isAnswered(QUESTIONS.find(q => q.key === k), answers[k])),
    [answers]
  );

  const handleSubmit = async () => {
    setSubmitting(true);
    setError(null);
    try {
      const durationSeconds = Math.round((Date.now() - mountedAtRef.current) / 1000);
      // Drop optional empties so the JSON stays clean.
      const cleaned = { ...answers };
      QUESTIONS.forEach(q => {
        if (!q.required && !isAnswered(q, cleaned[q.key])) {
          delete cleaned[q.key];
        }
      });
      await submitSurvey(cleaned, durationSeconds);
      setSubmitted(true);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('Survey submit failed:', err);
      setError(
        err?.response?.data?.detail
        ?? 'Could not submit. Please try again in a moment.'
      );
    } finally {
      setSubmitting(false);
    }
  };

  if (submitted) {
    return (
      <div className="survey-root">
        <div className="survey-shell survey-thanks">
          <h1>Thanks for the feedback.</h1>
          <p>This goes straight to the Office of the CTO. You can close this tab.</p>
        </div>
      </div>
    );
  }

  return (
    <div className="survey-root">
      <div className="survey-shell">
        <header className="survey-header">
          <img src="/octo_logo.png" alt="Octo" />
          <div className="wordmark">
            <span className="small">Office of the CTO &mdash; Extreme Networks</span>
            <span className="title">Aurora Quick Feedback</span>
          </div>
        </header>

        <div className="survey-progress" aria-live="polite">
          <span>{answeredCount} of {QUESTIONS.length} answered &middot; takes ~2 minutes</span>
          <div className="survey-progress-bar">
            <div style={{ width: `${(answeredCount / QUESTIONS.length) * 100}%` }} />
          </div>
        </div>

        {QUESTIONS.map(q => (
          <div className="q-card" key={q.key}>
            <p className="q-title">
              {q.title}
              {q.required && <span className="req" aria-hidden="true">*</span>}
            </p>

            {q.type === 'stars' && (
              <div className="q-options" role="radiogroup" aria-label={q.title}>
                {[1, 2, 3, 4, 5].map(n => (
                  <button
                    key={n}
                    type="button"
                    className={`q-chip star ${answers[q.key] === n ? 'selected' : ''}`}
                    aria-pressed={answers[q.key] === n}
                    onClick={() => setAnswer(q.key, n)}
                  >
                    {'★'.repeat(n)}{'☆'.repeat(5 - n)}
                  </button>
                ))}
              </div>
            )}

            {q.type === 'single' && (
              <div className="q-options" role="radiogroup" aria-label={q.title}>
                {q.options.map(o => (
                  <button
                    key={o.value}
                    type="button"
                    className={`q-chip ${answers[q.key] === o.value ? 'selected' : ''}`}
                    aria-pressed={answers[q.key] === o.value}
                    onClick={() => setAnswer(q.key, o.value)}
                  >
                    {o.label}
                  </button>
                ))}
              </div>
            )}

            {q.type === 'multi' && (
              <div className="q-options">
                {q.options.map(o => {
                  const checked = Array.isArray(answers[q.key]) && answers[q.key].includes(o.value);
                  return (
                    <button
                      key={o.value}
                      type="button"
                      className={`q-chip ${checked ? 'selected' : ''}`}
                      aria-pressed={checked}
                      onClick={() => toggleMulti(q.key, o.value)}
                    >
                      {o.label}
                    </button>
                  );
                })}
              </div>
            )}

            {q.type === 'text' && (
              <>
                <textarea
                  className="q-textarea"
                  maxLength={q.maxLength}
                  value={answers[q.key] || ''}
                  onChange={(e) => setAnswer(q.key, e.target.value)}
                  placeholder="Optional"
                />
                <div className="q-char-count">
                  {(answers[q.key] || '').length} / {q.maxLength}
                </div>
              </>
            )}
          </div>
        ))}

        {error && <div className="survey-error">{error}</div>}

        <div className="survey-submit">
          <button
            type="button"
            disabled={!allRequiredAnswered || submitting}
            onClick={handleSubmit}
          >
            {submitting ? 'Submitting…' : 'Submit feedback'}
          </button>
        </div>
      </div>
    </div>
  );
}
```

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Survey.jsx frontend/src/pages/Survey.css
git commit -m "feat(frontend): Survey page (independent UI)"
```

---

## Task 8: Frontend tests — `Survey.test.jsx`

**Files:**
- Create: `frontend/src/pages/Survey.test.jsx`

- [ ] **Step 1: Write the failing test**

```jsx
// frontend/src/pages/Survey.test.jsx
import React from 'react';
import { render, screen, fireEvent, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom';
import Survey from './Survey';

// Mock the API client so submit doesn't hit the network.
jest.mock('../services/api', () => ({
  submitSurvey: jest.fn(() => Promise.resolve({ id: 1 })),
}));

import { submitSurvey } from '../services/api';

const ANSWER_ORDER = [
  // [question title fragment, button label to click]
  ['Overall, how would you rate Aurora?', '★★★★☆'],
  ['Was it easy to find what you needed?', 'Very easy'],
  ['Speed felt', 'Fast'],
  ["How accurate were Aurora's answers?", 'Mostly'],
  ['Did Aurora cite the right sources?', 'Yes'],
  ["Did Aurora invent things that weren't in the sources?", 'Never'],
  ['What kind of question worked best?', 'Specs'],
  ['Were the sources Aurora used the right ones?', 'Mostly'],
  ['Would you use Aurora again?', 'Both'],
];

function answerAllRequired() {
  ANSWER_ORDER.forEach(([titleFragment, label]) => {
    const heading = screen.getByText(new RegExp(titleFragment, 'i'));
    const card = heading.closest('.q-card');
    const btn = within(card).getByRole('button', { name: label });
    fireEvent.click(btn);
  });
}

// `within` from RTL
import { within } from '@testing-library/react';

describe('Survey', () => {
  beforeEach(() => {
    submitSurvey.mockClear();
  });

  test('renders all 11 questions', () => {
    render(<Survey />);
    expect(screen.getByText(/Overall, how would you rate Aurora/i)).toBeInTheDocument();
    expect(screen.getByText(/Would you use Aurora again/i)).toBeInTheDocument();
    expect(screen.getByText(/One thing we should fix or add/i)).toBeInTheDocument();
    // Sticky progress strip exists.
    expect(screen.getByText(/0 of 11 answered/)).toBeInTheDocument();
  });

  test('submit is disabled until all required questions are answered', () => {
    render(<Survey />);
    const submitBtn = screen.getByRole('button', { name: /Submit feedback/i });
    expect(submitBtn).toBeDisabled();

    answerAllRequired();

    expect(submitBtn).toBeEnabled();
  });

  test('free-text caps at 500 characters', () => {
    render(<Survey />);
    const textarea = screen.getByPlaceholderText('Optional');
    fireEvent.change(textarea, { target: { value: 'x'.repeat(600) } });
    // Browsers enforce maxLength so React state never exceeds 500.
    expect(textarea.value.length).toBeLessThanOrEqual(500);
  });

  test('submit calls submitSurvey with the JSON contract and shows thanks', async () => {
    render(<Survey />);
    answerAllRequired();
    fireEvent.click(screen.getByRole('button', { name: /Submit feedback/i }));

    await waitFor(() => expect(submitSurvey).toHaveBeenCalledTimes(1));
    const [responses, durationSeconds] = submitSurvey.mock.calls[0];

    expect(responses.q1_overall_rating).toBe(4);
    expect(responses.q2_findability).toBe('very_easy');
    expect(responses.q3_speed).toBe('fast');
    expect(responses.q11_would_use_again).toBe('both');
    expect(responses.q7_works_best_for).toEqual(['specs']);
    // Optional q9/q10 absent when not answered.
    expect(responses).not.toHaveProperty('q9_missing_sources');
    expect(responses).not.toHaveProperty('q10_one_thing');
    expect(typeof durationSeconds).toBe('number');
    expect(durationSeconds).toBeGreaterThanOrEqual(0);

    await waitFor(() =>
      expect(screen.getByText(/Thanks for the feedback/i)).toBeInTheDocument()
    );
  });
});
```

- [ ] **Step 2: Run test to verify it fails (or passes if we got it right first try)**

```bash
cd frontend && npm test -- --watchAll=false Survey.test.jsx
```

Expected: PASS (the implementation in Task 7 already satisfies these). If it fails, fix the implementation, not the test — the test encodes the spec.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/pages/Survey.test.jsx
git commit -m "test(frontend): Survey page tests"
```

---

## Task 9: Mount `/survey` outside the app shell

**Files:**
- Modify: `frontend/src/App.js` (add an import and a `<Route>` next to the existing `/teams-tab` route)

The existing `/teams-tab` route sits OUTSIDE the `app-shell` `<div>`, with no `Header`/`Sidebar`/`IconRail`. We follow the same pattern so `/survey` is visually independent and free of nav.

- [ ] **Step 1: Add the import**

Near the other page imports in `frontend/src/App.js`:

```javascript
import Survey from './pages/Survey';
```

- [ ] **Step 2: Add the route**

Inside the `<Routes>` block at the top level (the one that already contains the `/teams-tab` route, NOT the inner one inside `app-shell`), add:

```jsx
{/* Survey — full-screen, no header/sidebar; URL-only entry */}
<Route
  path="/survey"
  element={
    <ProtectedRoute>
      <Survey />
    </ProtectedRoute>
  }
/>
```

This must sit ABOVE the catch-all `<Route path="/*" element={<ProtectedRoute>...` so it matches first.

- [ ] **Step 3: Run frontend tests**

```bash
cd frontend && npm test -- --watchAll=false
```

Expected: existing tests still pass; the new Survey tests still pass.

- [ ] **Step 4: Manual smoke**

```bash
docker compose up -d
# In a browser, go to http://localhost:8000/survey (or your dev URL).
# Expected: Cognito login redirect if not authed; then the Survey page
# with no Header/Sidebar/IconRail. The octo logo + wordmark show in the
# top strip. Answering all required questions enables Submit.
```

If the page renders inside the app shell instead of standalone, the `<Route>` was placed in the wrong `<Routes>` block — move it next to `/teams-tab`.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/App.js
git commit -m "feat(frontend): mount /survey route outside app shell"
```

---

## Task 10: Teams-agent — Adaptive Card template

**Files:**
- Create: `teams-agent/src/adaptiveCards/surveyResultCard.json`

This is the visual template for the Teams card. Uses the same `adaptivecards-templating` pattern as the existing `proactiveFeedCard.json`.

- [ ] **Step 1: Write the template**

```json
{
  "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
  "type": "AdaptiveCard",
  "version": "1.5",
  "body": [
    {
      "type": "Container",
      "items": [
        {
          "type": "TextBlock",
          "text": "New Aurora feedback from ${user_display_name}",
          "weight": "Bolder",
          "size": "Medium",
          "wrap": true
        },
        {
          "type": "TextBlock",
          "text": "${user_email} · ${submitted_at_display}",
          "size": "Small",
          "isSubtle": true,
          "spacing": "None"
        }
      ]
    },
    {
      "type": "Container",
      "spacing": "Medium",
      "items": [
        {
          "type": "TextBlock",
          "text": "${star_line}",
          "size": "ExtraLarge",
          "color": "Accent"
        }
      ]
    },
    {
      "type": "FactSet",
      "facts": [
        { "title": "Findability",       "value": "${q2_findability}" },
        { "title": "Speed",             "value": "${q3_speed}" },
        { "title": "Accuracy",          "value": "${q4_accuracy}" },
        { "title": "Citation accuracy", "value": "${q5_citation_accuracy}" },
        { "title": "Hallucination",     "value": "${q6_hallucination}" },
        { "title": "Worked best for",   "value": "${q7_works_best_for}" },
        { "title": "Source coverage",   "value": "${q8_source_coverage}" },
        { "title": "Missing sources",   "value": "${q9_missing_sources}" },
        { "title": "Would use again",   "value": "${q11_would_use_again}" }
      ]
    },
    {
      "type": "Container",
      "spacing": "Medium",
      "$when": "${comment_present}",
      "items": [
        {
          "type": "TextBlock",
          "text": "One thing to fix or add",
          "weight": "Bolder",
          "size": "Small"
        },
        {
          "type": "TextBlock",
          "text": "${q10_one_thing}",
          "wrap": true,
          "isSubtle": false
        }
      ]
    },
    {
      "type": "TextBlock",
      "spacing": "Medium",
      "text": "Completed in ${duration_display}",
      "size": "Small",
      "isSubtle": true
    }
  ]
}
```

- [ ] **Step 2: Commit**

```bash
git add teams-agent/src/adaptiveCards/surveyResultCard.json
git commit -m "feat(teams-agent): Adaptive Card template for survey results"
```

---

## Task 11: Teams-agent — `pushSurveyResult` in `ProactiveMessenger`

**Files:**
- Modify: `teams-agent/src/services/proactiveMessenger.ts`

Adds a payload interface and a method that reuses the existing slug-subscription delivery path (same as `pushFeedUpdate`, simpler — no webhook variant).

- [ ] **Step 1: Add the payload interface**

In `teams-agent/src/services/proactiveMessenger.ts`, near the existing `interface FeedUpdatePayload`, add:

```typescript
export interface SurveyResultPayload {
  user_email: string | null;
  user_display_name: string | null;
  submitted_at: string;
  duration_seconds: number | null;
  responses: Record<string, unknown>;
}

export const SURVEY_FEEDBACK_SLUG = 'survey-feedback';
```

- [ ] **Step 2: Add the import for the template**

At the top of the file, next to the existing `proactiveFeedCardTemplate` import:

```typescript
import surveyResultCardTemplate from '../adaptiveCards/surveyResultCard.json';
```

- [ ] **Step 3: Add the method to `ProactiveMessenger`**

Inside the `ProactiveMessenger` class, alongside the other `push*` methods:

```typescript
  /**
   * Push a quick-feedback survey result to every conversation subscribed to
   * the `survey-feedback` slug (the Aurora feedback channel).
   * One-time setup per channel: `@aurora subscribe survey-feedback`.
   */
  async pushSurveyResult(payload: SurveyResultPayload): Promise<{ sent: number; errors: number }> {
    const refs = await conversationReferenceStore.getSubscribed(SURVEY_FEEDBACK_SLUG);
    if (refs.length === 0) {
      console.log(`[ProactiveMessenger] pushSurveyResult: no subscribers for slug "${SURVEY_FEEDBACK_SLUG}"`);
      return { sent: 0, errors: 0 };
    }

    const card = this.buildSurveyCard(payload);
    const activity = MessageFactory.attachment(card);

    let sent = 0, errors = 0;
    for (const ref of refs) {
      try {
        await this.adapter.continueConversation(ref as Partial<ConversationReference>, async (ctx: TurnContext) => {
          await ctx.sendActivity(activity);
        });
        sent++;
      } catch (e) {
        errors++;
        console.error(`[ProactiveMessenger] pushSurveyResult error for ${ref.conversation_id}:`, e);
      }
    }

    return { sent, errors };
  }

  private buildSurveyCard(p: SurveyResultPayload): any {
    const r = p.responses as Record<string, any>;
    const rating = Number(r.q1_overall_rating) || 0;
    const starLine = '★'.repeat(rating) + '☆'.repeat(Math.max(0, 5 - rating));

    const submittedDisplay = (() => {
      try { return new Date(p.submitted_at).toLocaleString(); }
      catch { return p.submitted_at; }
    })();

    const durationDisplay = p.duration_seconds == null
      ? 'n/a'
      : `${Math.max(1, Math.round(p.duration_seconds))}s`;

    const arrOrDash = (v: any): string => Array.isArray(v) && v.length ? v.join(', ') : '—';

    const data = {
      user_display_name:    p.user_display_name || p.user_email || 'Anonymous',
      user_email:           p.user_email || '',
      submitted_at_display: submittedDisplay,
      star_line:            starLine,
      q2_findability:       String(r.q2_findability ?? '—'),
      q3_speed:             String(r.q3_speed ?? '—'),
      q4_accuracy:          String(r.q4_accuracy ?? '—'),
      q5_citation_accuracy: String(r.q5_citation_accuracy ?? '—'),
      q6_hallucination:     String(r.q6_hallucination ?? '—'),
      q7_works_best_for:    arrOrDash(r.q7_works_best_for),
      q8_source_coverage:   String(r.q8_source_coverage ?? '—'),
      q9_missing_sources:   arrOrDash(r.q9_missing_sources),
      q10_one_thing:        String(r.q10_one_thing ?? ''),
      comment_present:      Boolean(r.q10_one_thing && String(r.q10_one_thing).trim().length),
      q11_would_use_again:  String(r.q11_would_use_again ?? '—'),
      duration_display:     durationDisplay,
    };

    const template = new ACData.Template(surveyResultCardTemplate as any);
    const json = template.expand({ $root: data });
    return CardFactory.adaptiveCard(json);
  }
```

- [ ] **Step 4: Build**

```bash
cd teams-agent && npm run build
```

Expected: TypeScript build succeeds. If it complains about `JSON module imports`, the codebase already supports them (the existing `proactiveFeedCardTemplate` import proves it).

- [ ] **Step 5: Commit**

```bash
git add teams-agent/src/services/proactiveMessenger.ts
git commit -m "feat(teams-agent): pushSurveyResult method"
```

---

## Task 12: Teams-agent — `POST /internal/push-survey-result` endpoint

**Files:**
- Modify: `teams-agent/src/index.ts`

- [ ] **Step 1: Add the handler**

In `teams-agent/src/index.ts`, after the existing `/internal/system-alert` handler block, add:

```typescript
/**
 * POST /internal/push-survey-result
 * Body: SurveyResultPayload
 *   { user_email, user_display_name, submitted_at, duration_seconds, responses }
 *
 * Delivers an Adaptive Card with the survey results to every Teams channel
 * subscribed to the `survey-feedback` slug. Internal-only — not exposed
 * through nginx. Called by the Aurora backend after persisting the row.
 */
server.post('/internal/push-survey-result', async (req, res) => {
  const body = req.body ?? {};
  if (!body?.responses || typeof body.responses !== 'object') {
    res.send(400, { error: 'responses object is required' });
    return;
  }

  console.log(
    `[${new Date().toISOString()}] Survey result push from ${body.user_email ?? 'unknown'}`
  );

  // Respond immediately so the caller doesn't block.
  res.json({ status: 'queued', user_email: body.user_email ?? null });

  proactiveMessenger.pushSurveyResult({
    user_email:        body.user_email ?? null,
    user_display_name: body.user_display_name ?? null,
    submitted_at:      body.submitted_at ?? new Date().toISOString(),
    duration_seconds:  body.duration_seconds ?? null,
    responses:         body.responses,
  }).catch((err) => {
    console.error('[internal/push-survey-result] Delivery error:', err);
  });
});
```

- [ ] **Step 2: Build and smoke-test**

```bash
cd teams-agent && npm run build && npm start &
sleep 2
curl -sS -X POST http://localhost:3978/internal/push-survey-result \
  -H 'Content-Type: application/json' \
  -d '{"user_email":"smoke@test","responses":{"q1_overall_rating":5}}'
```

Expected output: `{"status":"queued","user_email":"smoke@test"}`. Then check the teams-agent log: it should print "no subscribers for slug" (because the channel isn't subscribed yet — that's fine; Task 13 covers the manual step).

Kill the background process when done: `kill %1`.

- [ ] **Step 3: Commit**

```bash
git add teams-agent/src/index.ts
git commit -m "feat(teams-agent): /internal/push-survey-result endpoint"
```

---

## Task 13: One-time channel subscription + launch notes

**Files:**
- Create or modify: `docs/superpowers/specs/2026-06-12-aurora-quick-feedback-survey-design.md` (append a "Launch checklist" section)

This is documentation, not code. It captures the one-time human steps so the survey actually lands in Teams in production.

- [ ] **Step 1: Append launch checklist to the spec**

Add at the bottom of `docs/superpowers/specs/2026-06-12-aurora-quick-feedback-survey-design.md`:

```markdown
## Launch checklist

1. Apply migration 015 in each environment: `make migrate` (CI/CD runs
   this; manual `make connect_aurora_ec2` + `make migrate` for prod
   if the deploy pipeline skips migrations).
2. Ensure `TEAMS_AGENT_URL` is set in the backend service's environment
   for every environment (Task 0 wired this for compose; prod uses the
   same variable through prod-deployment compose).
3. Open the Aurora Teams channel where survey results should land.
4. Invite the `@aurora` bot if not already a member.
5. In that channel, post: `@aurora subscribe survey-feedback`.
6. Confirm by posting a smoke submission from `/survey` in dev — the
   Adaptive Card should appear in the channel within a few seconds.
   If nothing arrives, check the teams-agent log for
   `pushSurveyResult: no subscribers for slug "survey-feedback"` — the
   subscribe step did not stick.
7. Share the `/survey` URL with the 25 trial users via the usual
   channel. No in-app link is required (or wanted).
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/specs/2026-06-12-aurora-quick-feedback-survey-design.md
git commit -m "docs: launch checklist for /survey"
```

---

## Task 14: Full local verification

**No new files.** Final pass: everything green, manual end-to-end flows.

- [ ] **Step 1: All backend tests**

```bash
make test-backend
```

Expected: green. (If `make test-backend` doesn't exist, use `cd backend && make test`.)

- [ ] **Step 2: All frontend tests**

```bash
cd frontend && npm test -- --watchAll=false
```

Expected: green.

- [ ] **Step 3: TypeScript build of teams-agent**

```bash
cd teams-agent && npm run build
```

Expected: clean build, no type errors.

- [ ] **Step 4: End-to-end against running compose stack**

```bash
docker compose up -d --build backend frontend teams-agent
# Wait a few seconds, then:
curl -sS http://localhost:8000/api/backend/survey/submit  # expect 401/method-not-allowed without auth — confirms route is mounted
```

Then in a browser:

1. Visit `/survey` while signed out → Cognito redirect.
2. Sign in → land on `/survey` with no header/sidebar.
3. Fill in all required, type a comment, submit.
4. Verify the row in Postgres:

   ```bash
   docker compose exec postgres psql -U aurora -d aurora \
     -c "SELECT id, user_email, duration_seconds, responses->>'q1_overall_rating' AS rating FROM survey_responses ORDER BY id DESC LIMIT 1;"
   ```

   Expected: the row you just submitted.

5. Check teams-agent log for `Survey result push from <email>`.

- [ ] **Step 5: No more commits — just a clean working tree**

```bash
git status
```

Expected: nothing to commit, working tree clean.

---

## Self-review checklist (filled in by author)

- **Spec coverage:**
  - Route `/survey` outside app shell — Task 9.
  - Login-gated — Task 9 wraps in `ProtectedRoute`.
  - No nav link anywhere — verified by NOT touching `Sidebar`/`IconRail`/`Header`.
  - 11 questions (9 required, 2 optional) — Tasks 7, 8.
  - Free-text max 500 chars — Tasks 4 (server) + 7 (client) + 8 (test).
  - Unlimited re-submissions — Task 1 (no UNIQUE constraint on user_id).
  - Octo logo + "Office of the CTO" wordmark — Task 7 header strip.
  - Independent UI (no theme imports) — Task 7 CSS, Task 9 placement.
  - Persists in Postgres — Tasks 1, 2.
  - Posts to Aurora Teams channel via teams-agent — Tasks 10, 11, 12.
  - Teams failure does NOT fail submit — Tasks 3, 4 (tests + impl).
  - One-time subscribe `survey-feedback` documented — Task 13.

- **Placeholder scan:** No TBDs, no "implement later," every code step
  contains the actual code, every command shows expected output.

- **Type consistency:**
  - `create_survey_response` signature matches between Tasks 2 (definition)
    and 4 (caller).
  - `SurveyResponses` field names match the React `QUESTIONS[].key`
    values across Tasks 4 and 7.
  - `SurveyResultPayload` in Task 11 matches the JSON body in Tasks 3
    (caller) and 12 (endpoint).
  - The slug literal `survey-feedback` matches across Tasks 11
    (constant) and 13 (subscribe command).
