"""Quick-feedback survey route — POST /survey/submit.

Login-gated, no in-app nav link. The contract is locked here via Pydantic;
the storage column is JSONB so wording can change without DDL.
"""

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, conint, conlist, constr
from typing import Any, Dict, List, Literal, Optional
import logging

from common.auth_middleware import get_user_context, require_user_context
from src.services import postgres
from src.services import survey_notifier

router = APIRouter(prefix="/survey", tags=["Survey"])
logger = logging.getLogger(__name__)


# ── Question contract ──────────────────────────────────────────────────────
# Keys are stable (qN_<slug>). UI wording can change independently.

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


def _serializable(row: Dict[str, Any]) -> Dict[str, Any]:
    """Make sure datetimes etc. survive the JSON response."""
    out = dict(row) if row else {}
    submitted = out.get("submitted_at")
    if submitted is not None and not isinstance(submitted, str):
        out["submitted_at"] = submitted.isoformat()
    return out


@router.post("/submit")
@require_user_context
async def submit_survey(
    body: SurveySubmit,
    request: Request,
    user: Optional[dict] = Depends(get_user_context),
):
    """Persist one survey submission and fire-and-forget a Teams push."""
    user_agent = request.headers.get("user-agent")
    responses_dict = body.responses.model_dump(exclude_none=True)

    row = postgres.create_survey_response(
        user_id=user["user_id"],
        user_email=user.get("email"),
        user_display_name=user.get("display_name") or user.get("name"),
        duration_seconds=body.duration_seconds,
        client_user_agent=user_agent,
        responses=responses_dict,
    )

    # Best-effort: never let a Teams push failure surface to the user.
    try:
        survey_notifier.push_survey_result(
            user_email=row.get("user_email") if row else user.get("email"),
            user_display_name=row.get("user_display_name") if row else None,
            submitted_at=str(row.get("submitted_at")) if row else "",
            duration_seconds=row.get("duration_seconds") if row else body.duration_seconds,
            responses=row.get("responses") if row else responses_dict,
        )
    except Exception as exc:
        logger.warning("Survey Teams push raised — swallowed: %s", exc)

    return _serializable(row)
