# Aurora Quick Feedback Survey — Design

**Date:** 2026-06-12
**Owner:** bbonner
**Status:** Approved for implementation

## Purpose

Capture fast, structured feedback from the 25-user Aurora trial without
disrupting the main app experience. The existing `/feedback` page collects
open-ended bug reports — this is a complementary instrument that produces
quantitative, comparable signal across users and over time.

Hard requirements from the requester:

- Reachable only at `/survey`; no link from anywhere else in the app.
- Authenticated — uses the existing login (Cognito) so responses are
  tied to a known user.
- Completable in under two minutes.
- Single-click answers dominate; occasional multi-select; the last two
  questions are open text and an explicit "would you use this again."
- Mix of site UX, accuracy/performance, and sources coverage.
- Visually independent from the rest of the app, but carries the Octo /
  Office of the CTO mark.
- On submit: persist the response and post an update to the Aurora Teams
  channel.

## Non-goals

- No admin UI for browsing responses in this iteration. Reviewer reads
  results from the Teams channel.
- No analytics dashboard, no email digest, no scheduled reminders.
- No rate limiting beyond authentication. Unlimited re-submissions; each
  is its own row so sentiment drift over the trial is visible.
- No anonymous mode. Responses are always tied to a user.

## User-facing behavior

### Route

- New route `GET /survey` rendered **outside** the standard app shell
  (`Header` / `Sidebar` / `IconRail`). Same isolation pattern that
  `/teams-tab` already uses in `frontend/src/App.js`.
- Wrapped in `ProtectedRoute`, so unauthenticated visitors get the
  Cognito redirect.
- No nav entry anywhere — `Sidebar.jsx`, `IconRail.jsx`, `Header.jsx`
  are not modified.

### Layout

- Header strip: `octo_logo.png` on the left + the wordmark
  "Office of the CTO — Aurora Feedback" as styled text. The existing
  `ExtremeNetworksLogo` component already wraps `/octo_logo.png` and
  may be reused.
- Body: single vertical scroll containing all eleven question cards.
  A sticky top progress bar shows "N of 11 answered." Single-scroll
  (rather than step-by-step wizard) was chosen so users can see the
  full commitment up front — fewer abandons on a survey this short.
- Submit button locked until every required question has an answer.
  Q9 ("missing sources") and Q10 (free-text comment) are optional.
- Post-submit: a "Thanks!" confirmation screen on the same page. No
  auto-redirect back into the app.

### Styling

- Self-contained CSS in `Survey.css`. Does **not** import `App.css` or
  any of the shared theme files. The page should be visually
  distinguishable from the rest of the app at a glance.
- Light background, single accent color (purple/teal in the Octo
  family), generous whitespace.
- Mobile-friendly: question cards stack, chip buttons wrap.

### Questions (locked)

All questions use chip-style buttons unless noted.

1. **Overall, how would you rate Aurora?** — ★ 1 / 2 / 3 / 4 / 5
2. **Was it easy to find what you needed?** — Very easy / OK / Hard
3. **Speed felt…** — Fast / OK / Slow
4. **How accurate were Aurora's answers?** — Very / Mostly / Mixed / Often wrong
5. **Did Aurora cite the right sources?** — Yes / Sometimes / Rarely / N/A
6. **Did Aurora invent things that weren't in the sources?** — Never / Once or twice / Often
7. **What kind of question worked best?** *(multi-select)* — Specs, People/orgs, Events, Trends, Other
8. **Were the sources Aurora used the right ones?** — Yes / Mostly / Missing some / Not really
9. **What sources are missing?** *(multi-select, optional)* — IETF, IEEE, vendor blogs, internal docs, Other
10. **One thing we should fix or add?** *(free text, optional, max 500 chars)*
11. **Would you use Aurora again?** — Yes (web) / Yes (Teams) / Both / No / Not sure

Required: 1, 2, 3, 4, 5, 6, 7, 8, 11. Optional: 9, 10.

## Data model

New PostgreSQL table, created via the existing migration pattern in
`backend/src/services/migrations.py`:

```sql
CREATE TABLE IF NOT EXISTS survey_responses (
    id                  BIGSERIAL PRIMARY KEY,
    user_id             TEXT        NOT NULL,
    user_email          TEXT,
    user_display_name   TEXT,
    submitted_at        TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    duration_seconds    INTEGER,
    client_user_agent   TEXT,
    responses           JSONB       NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_survey_responses_user_submitted
    ON survey_responses (user_id, submitted_at DESC);
```

`responses` shape (validated by the Pydantic request model on the way
in, but stored as JSONB so the question set can evolve without DDL):

```json
{
  "q1_overall_rating": 4,
  "q2_findability": "easy",
  "q3_speed": "ok",
  "q4_accuracy": "mostly",
  "q5_citation_accuracy": "sometimes",
  "q6_hallucination": "once_or_twice",
  "q7_works_best_for": ["specs", "events"],
  "q8_source_coverage": "missing_some",
  "q9_missing_sources": ["ieee", "vendor_blogs"],
  "q10_one_thing": "Better date filtering on events would help.",
  "q11_would_use_again": "both"
}
```

`duration_seconds` is computed client-side (timestamp at mount vs. at
submit) and is informational only — used to verify the two-minute
target is realistic in practice.

## Service flow

```
Browser (Survey.jsx)
   └── POST /api/survey/submit
        Authorization: <cookie/JWT via auth gateway>
        body: { responses, duration_seconds, client_user_agent }
              │
              ▼
        backend/src/routes/survey.py
          1. Pydantic validation
          2. postgres.create_survey_response(...)   ← always succeeds first
          3. Fire-and-forget POST to teams-agent
                                  │
                                  ▼
                  teams-agent  /internal/push-survey-result
                    body: { user_email, user_display_name,
                            submitted_at, duration_seconds, responses }
                    Builds an Adaptive Card and pushes via
                    proactiveMessenger to the "survey-feedback" slug
                    subscription in the Aurora Teams channel.
```

Key invariants:

- The Teams delivery is best-effort. If teams-agent is unreachable or
  errors, the `/survey/submit` response to the browser is still 200
  and the row is still in Postgres. Failure is logged at WARN.
- Service-to-service call from backend → teams-agent goes through
  `common.service_client.call_internal_service` per the existing
  pattern (CLAUDE.md invariant #4). No raw HTTP.
- No PII normalization beyond what Postgres already does for the
  existing `feedback` table — same user identity columns.

## Teams channel delivery

Reuses the existing slug-subscription mechanism in
`teams-agent/src/services/conversationReferenceStore.ts`.

One-time setup (documented in the implementation plan, not enforced
by code):

1. Invite the `@aurora` bot into the target Aurora Teams channel.
2. In that channel, type `@aurora subscribe survey-feedback`.

After that, `proactiveMessenger.pushSurveyResult(payload)` finds the
subscribed conversation(s) for slug `survey-feedback` and posts the
Adaptive Card there. No env-var hardcoding of channel IDs.

The Adaptive Card includes:

- Header: "New Aurora feedback from <display name>"
- Big star rating (Q1) as the headline visual
- Each Q/A as a label+value row, in the order above
- The free-text comment quoted, if present
- Timestamp and duration in the card footer

## Files added or modified

**New**
- `backend/src/routes/survey.py` — `POST /survey/submit`
- `backend/tests/test_survey.py` — endpoint tests
- `frontend/src/pages/Survey.jsx`
- `frontend/src/pages/Survey.css`
- `frontend/src/pages/Survey.test.jsx`
- `teams-agent/src/services/surveyCardBuilder.ts` — Adaptive Card
  template + builder (kept separate from `proactiveMessenger.ts` so
  the messenger file doesn't keep growing)

**Modified**
- `backend/src/api.py` — register the new router
- `backend/src/services/postgres.py` — add `create_survey_response(...)`
- `backend/src/services/migrations.py` — add the migration entry
- `frontend/src/App.js` — add `/survey` route OUTSIDE the app-shell
  block (alongside `/teams-tab`)
- `frontend/src/services/api.js` — `submitSurvey(payload)`
- `teams-agent/src/index.ts` — add `POST /internal/push-survey-result`
- `teams-agent/src/services/proactiveMessenger.ts` — add
  `pushSurveyResult(payload)`

## Testing strategy

**Frontend (`Survey.test.jsx`)**
- All eleven questions render with their expected labels.
- Submit is disabled until every required answer is selected; enabling
  works as soon as Q11 is answered.
- Free-text field caps at 500 characters.
- On submit, `submitSurvey` is called with the correct JSON shape,
  including a non-zero `duration_seconds`.
- Post-submit "Thanks!" screen replaces the form.

**Backend (`tests/test_survey.py`)**
- 200 happy path: row written, response shape matches contract.
- 401 when unauthenticated.
- 422 when `responses` is missing a required question key.
- 422 when free-text exceeds 500 chars.
- Teams-agent unreachable → still 200, row written, WARN logged.

**Manual / out-of-test coverage**
- Adaptive Card rendering in the actual Aurora Teams channel after the
  one-time `subscribe` step.
- 2-minute completion target — observed informally during dogfooding,
  validated by the `duration_seconds` column over the trial.

## Open questions resolved during brainstorming

- **Discovery:** URL-only, manually shared. No toast, no post-logout
  redirect.
- **Teams delivery mechanism:** Through the existing `teams-agent`
  service (not a raw incoming webhook).
- **Re-submission policy:** Unlimited. Each submission its own row.
- **Logos:** Existing `octo_logo.png` + "Office of the CTO — Aurora
  Feedback" wordmark. No new assets to ship.
- **Question set:** Locked above (eleven questions).

## Risks and mitigations

- **Teams-agent delivery failure goes unnoticed.** Mitigation: log at
  WARN with full payload; row is still in Postgres so nothing is lost.
  Future improvement: surface delivery failures in `AdminMonitoring`.
- **Slug-subscription not configured before launch.** Mitigation:
  implementation plan calls out the one-time `@aurora subscribe
  survey-feedback` step explicitly as a launch checklist item.
- **Question wording changes break stored data.** Mitigation: JSONB
  storage + stable key names (`q1_overall_rating`, etc.) decouple
  storage from display labels. Renames go in the Pydantic schema; the
  DB doesn't care.
