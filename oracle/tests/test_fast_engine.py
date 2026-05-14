"""Focused regression tests for the fast query engine."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.engines.fast_engine import FastEngine
from src.models.request import QueryMode, QueryOptions, QueryRequest
from src.models.route_plan import DetailLevel, RouteId, RoutePlan, RouteResult
from src.services.fast_cache import FastCache
from src.services.local_router import LocalRouter
from src.services.topic_manager import TopicManager


def _build_engine() -> FastEngine:
    with patch("src.engines.fast_engine.get_repo") as mock_get_repo, patch(
        "src.engines.fast_engine.get_topic_manager", return_value=object()
    ):
        mock_repo = MagicMock()
        mock_repo.client = MagicMock()
        mock_get_repo.return_value = mock_repo
        engine = FastEngine()
        engine.fast_cache = MagicMock()
        engine.fast_cache.set_result = AsyncMock()
        return engine


def test_local_router_prunes_generic_wifi_topic_for_recent_content():
    """The most common broad recency query should not be hard-filtered to a generic Wi-Fi topic."""
    router = LocalRouter()
    entities = {"topics": ["Wi-Fi"], "workgroups": [], "organizations": [], "people": []}

    pruned = router._prune_generic_recent_topics(RouteId.RECENT_CONTENT, entities)

    assert pruned["topics"] == []


def test_local_router_prefers_brief_recent_answer_for_whats_new_queries():
    """Broad recency prompts should keep the richer answer path."""
    router = LocalRouter()

    assert router._prefer_brief_recent_answer("what is new in wi-fi?", RouteId.RECENT_CONTENT) is False


def test_local_router_prefers_brief_recent_answer_for_recent_discussion_queries():
    """Explicit recent-discussion prompts can still use the deterministic brief path."""
    router = LocalRouter()

    assert router._prefer_brief_recent_answer("what was discussed recently in wi-fi halow?", RouteId.RECENT_CONTENT) is True


def test_local_router_prefers_rich_recent_answer_when_topic_scope_is_explicit():
    """Recent discussion prompts with explicit entities should use the richer synthesis path."""
    router = LocalRouter()

    assert router._prefer_brief_recent_answer(
        "what happened recently regarding wi-fi 7?",
        RouteId.RECENT_CONTENT,
        {"topics": ["Wi-Fi 7"], "organizations": [], "people": [], "workgroups": []},
    ) is False


def test_local_router_routes_recent_discussion_query_to_recent_content():
    """Recent discussion prompts should avoid the generic-search fallback."""
    router = LocalRouter()

    route_id, confidence = router._match_route_pattern("what was discussed recently in wi-fi halow?")

    assert route_id == RouteId.RECENT_CONTENT
    assert confidence > 0


def test_topic_manager_filters_question_stopwords_from_matched_topics():
    """Common question words should not survive topic extraction."""
    neo4j_client = MagicMock()
    neo4j_client.execute_query.return_value = [
        {"name": "Wi-Fi", "aliases": ["wifi"], "search_count": None},
        {"name": "HaLow", "aliases": ["Wi-Fi HaLow"], "search_count": None},
        {"name": "was", "aliases": [], "search_count": None},
    ]
    manager = TopicManager(neo4j_client)

    topics = manager.extract_topics("what was discussed recently in wi-fi halow?")

    assert "was" not in [topic.lower() for topic in topics]
    assert any(topic.lower() == "halow" for topic in topics)


def test_topic_manager_keeps_topic_extraction_for_temporal_queries_with_subject():
    """Temporal wording should not suppress explicit subject extraction."""
    neo4j_client = MagicMock()
    neo4j_client.execute_query.return_value = [
        {"name": "Wi-Fi 7", "aliases": ["802.11be"], "search_count": None},
    ]
    manager = TopicManager(neo4j_client)

    topics = manager.extract_topics("what happened recently regarding wi-fi 7?")

    assert "Wi-Fi 7" in topics


def test_local_router_routes_latest_updates_query_to_recent_content():
    """Temporal update prompts without explicit org should route to RECENT_CONTENT.
    Queries that name a known org (wi-fi alliance, ietf, etc.) correctly route to
    ORGANIZATION_ACTIVITY — use a generic phrasing to test the RECENT_CONTENT path."""
    router = LocalRouter()

    # Generic recency query (no org name) → RECENT_CONTENT
    route_id, confidence = router._match_route_pattern("what are the latest updates?")
    assert route_id == RouteId.RECENT_CONTENT
    assert confidence > 0

    # Org-specific recency query → ORGANIZATION_ACTIVITY (correct)
    route_id_org, _ = router._match_route_pattern("what are the latest wi-fi alliance updates?")
    assert route_id_org == RouteId.ORGANIZATION_ACTIVITY


def test_local_router_keeps_standards_topic_when_org_also_matches():
    """Technical standards terms should survive topic filtering even when an org is also detected."""
    router = LocalRouter()

    with patch("src.services.local_router.get_topic_manager") as mock_get_topic_manager:
        mock_manager = MagicMock()
        mock_manager.extract_topics.return_value = ["ieee 802.11"]
        mock_get_topic_manager.return_value = mock_manager

        entities = router._extract_entities("what has changed in the latest ieee 802.11 standards?")

    assert "IEEE" in entities["organizations"]
    assert "ieee 802.11" in [topic.lower() for topic in entities["topics"]]


@pytest.mark.asyncio
async def test_recent_content_retries_without_generic_topics():
    """Broad Wi-Fi recency queries should fall back instead of returning zero results."""
    engine = _build_engine()

    template = MagicMock()
    template.cypher = "MATCH (n) RETURN n"
    template.build_params.return_value = {
        "topics": ["Wi-Fi"],
        "workgroups": [],
        "start_date": None,
        "end_date": None,
        "relative_days": None,
    }
    template.execute_post_process.side_effect = [
        [],
        [{"workgroup_name": "Wi-Fi", "recent_documents": [{"title": "Recent Wi-Fi update", "url": "https://example.com/doc"}]}],
    ]
    engine.template_registry.get_template = MagicMock(return_value=template)

    mock_repo = MagicMock()
    mock_repo.client.execute_query.side_effect = [
        [],
        [{"workgroup_name": "Wi-Fi", "recent_documents": [{"title": "Recent Wi-Fi update", "url": "https://example.com/doc"}]}],
    ]

    plan = RoutePlan(
        route_id=RouteId.RECENT_CONTENT,
        raw_query="What is new in Wi-Fi?",
        topics=["Wi-Fi"],
    )

    with patch("src.engines.fast_engine.get_repo", return_value=mock_repo):
        result, _ = await engine._retrieve_neo4j_data(plan, time.time(), MagicMock())

    assert result.node_count == 1
    assert mock_repo.client.execute_query.call_count == 2
    assert mock_repo.client.execute_query.call_args_list[1].args[1]["topics"] == []


@pytest.mark.asyncio
async def test_compose_with_llm_falls_back_when_llm_returns_empty():
    """Fast mode should still return a useful answer if the LLM returns blank content."""
    engine = _build_engine()

    route_result = RouteResult(
        route_id=RouteId.RECENT_CONTENT,
        nodes=[
            {
                "workgroup_name": "Wi-Fi",
                "workgroup_id": "wifi",
                "recent_documents": [
                    {
                        "title": "Recent Wi-Fi update",
                        "url": "https://example.com/doc",
                        "summary": "A recent update about Wi-Fi.",
                    }
                ],
            }
        ],
        execution_time_ms=5,
        node_count=1,
        cache_hit=False,
    )
    request = QueryRequest(
        user_id="user-1",
        question="What is new in Wi-Fi?",
        mode=QueryMode.ANSWER,
        options=QueryOptions(max_documents=5),
    )

    mock_response = MagicMock()
    mock_response.content = ""

    with patch("src.engines.fast_engine.get_llm_client", return_value=MagicMock()), patch(
        "src.engines.fast_engine.call_llm", new_callable=AsyncMock, return_value=mock_response
    ):
        answer, documents, citations = await engine._compose_with_llm(
            RoutePlan(route_id=RouteId.RECENT_CONTENT, raw_query=request.question),
            route_result,
            None,
            request,
            MagicMock(),
        )

    assert answer.startswith("Found 1 relevant items:")
    assert len(documents) == 1
    assert len(citations) == 1


def test_compose_recent_content_brief_skips_llm_and_returns_citations():
    """Brief recent-content answers should stay deterministic and cite documents."""
    engine = _build_engine()
    route_result = RouteResult(
        route_id=RouteId.RECENT_CONTENT,
        nodes=[
            {
                "workgroup_name": "Wi-Fi",
                "workgroup_id": "wifi",
                "recent_documents": [
                    {
                        "title": "Recent Wi-Fi update",
                        "url": "https://example.com/doc",
                        "summary": "A recent update about Wi-Fi.",
                        "publishDate": "2026-03-19",
                    }
                ],
            }
        ],
        execution_time_ms=5,
        node_count=1,
        cache_hit=False,
    )
    request = QueryRequest(
        user_id="user-1",
        question="What is new in Wi-Fi?",
        mode=QueryMode.ANSWER,
        options=QueryOptions(max_documents=5),
    )

    answer, documents, citations = engine._compose_recent_content_brief(route_result, request)

    assert "Here are the most recent reference documents I found:" in answer
    assert len(documents) == 1
    assert len(citations) == 1


def test_nodes_to_documents_flattens_topic_comparison_sample_resources():
    """Comparison template results should surface sample resources as documents."""
    engine = _build_engine()

    documents = engine._nodes_to_documents([
        {
            "topic_name": "Wi-Fi 7",
            "sample_resources": [
                {
                    "id": "doc-1",
                    "title": "Wi-Fi 7 Overview",
                    "summary": "A summary of Wi-Fi 7 improvements.",
                    "url": "https://example.com/wifi7",
                    "date": "2026-03-01",
                }
            ],
        }
    ])

    assert len(documents) == 1
    assert documents[0].title == "Wi-Fi 7 Overview"
    assert documents[0].source == "Wi-Fi 7"


def test_compose_standard_topic_comparison_returns_deterministic_wifi_answer():
    """Common Wi-Fi 7 vs Wi-Fi 6 comparisons should return a deterministic fast answer."""
    engine = _build_engine()
    plan = RoutePlan(
        route_id=RouteId.TOPIC_COMPARISON,
        raw_query="What are the key improvements in Wi-Fi 7 compared to Wi-Fi 6?",
        topics=["Wi-Fi 7", "Wi-Fi 6"],
    )
    route_result = RouteResult(
        route_id=RouteId.TOPIC_COMPARISON,
        nodes=[
            {
                "topic_name": "Wi-Fi 7",
                "sample_resources": [
                    {
                        "id": "doc-1",
                        "title": "Wi-Fi 7 Overview",
                        "summary": "Wi-Fi 7 overview.",
                        "url": "https://example.com/wifi7",
                        "date": "2026-03-01",
                    }
                ],
            }
        ],
        execution_time_ms=5,
        node_count=1,
        cache_hit=False,
    )

    answer, documents, citations = engine._compose_standard_topic_comparison(plan, route_result)

    assert "320 MHz channels" in answer
    assert len(documents) == 1
    assert len(citations) == 1


def test_fast_cache_plan_key_varies_with_user_preferences():
    """Personalized plan cache keys must differ for different preference sets."""
    cache = FastCache(redis_client=None)

    key_a = cache._plan_cache_key(
        "What is new in Wi-Fi?",
        user_prefs={"topics": ["Wi-Fi"], "organisations": ["WFA"], "people": []},
    )
    key_b = cache._plan_cache_key(
        "What is new in Wi-Fi?",
        user_prefs={"topics": ["HaLow"], "organisations": ["WFA"], "people": []},
    )

    assert key_a != key_b


def test_fast_engine_caches_deterministic_personalized_answers():
    """Deterministic brief answers should remain cacheable even when personalization is enabled."""
    engine = _build_engine()

    assert engine._can_cache_personalized_answer(
        RoutePlan(
            route_id=RouteId.RECENT_CONTENT,
            raw_query="What is new in Wi-Fi?",
            detail_level=DetailLevel.BRIEF,
        )
    ) is True
