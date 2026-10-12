"""History-driven fast-cache prewarming."""

import logging
from typing import Any

from src.models.request import PersonalizeMode, QueryMode, QueryOptions, QueryRequest
from src.services.query_history import get_query_history_service

logger = logging.getLogger(__name__)


class FastPrewarmService:
    """Prewarm the fast pipeline from recent hot query history."""

    def __init__(self, fast_engine):
        self.fast_engine = fast_engine

    async def prewarm_hot_queries(self, days: int = 30, limit: int = 10) -> int:
        """Run the current fast pipeline against recent hot fast-mode prompts."""
        history_service = get_query_history_service()
        hot_queries = await history_service.get_hot_queries(days=days, limit=limit, fast_only=True)

        if not hot_queries:
            logger.info("No hot fast queries available for prewarming")
            return 0

        warmed = 0
        for candidate in hot_queries:
            question = candidate.get("sample_question")
            if not question:
                continue

            try:
                request = self._build_request(candidate)
                await self.fast_engine.query(
                    request=request,
                    user=None,
                    span=None,
                    query_id=f"prewarm-{warmed + 1}",
                )
                warmed += 1
                logger.info(
                    "Prewarmed fast query: question=%r frequency=%s avg_latency_ms=%s",
                    question[:120],
                    candidate.get("frequency"),
                    candidate.get("avg_processing_time_ms"),
                )
            except Exception as exc:
                logger.warning("Failed to prewarm hot query %r: %s", question[:120], exc)

        logger.info("Completed hot-query prewarm: %s/%s warmed", warmed, len(hot_queries))
        return warmed

    def _build_request(self, candidate: dict[str, Any]) -> QueryRequest:
        """Reconstruct a representative fast query from history."""
        request_options = candidate.get("sample_request_options") or {}
        options_payload = {
            key: value
            for key, value in request_options.items()
            if key in QueryOptions.model_fields
        }
        options_payload["pipeline_override"] = "fast"
        if candidate.get("sample_user_id"):
            options_payload.setdefault("personalize", PersonalizeMode.ON.value)
        else:
            options_payload.setdefault("personalize", PersonalizeMode.OFF.value)

        return QueryRequest(
            user_id=candidate.get("sample_user_id") or "system-prewarm",
            question=candidate["sample_question"],
            mode=QueryMode.ANSWER,
            options=QueryOptions(**options_payload),
        )
