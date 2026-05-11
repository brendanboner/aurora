"""Baseline answer engine - wraps existing Oracle pipeline."""

import logging
import re
import time
import uuid
from typing import Optional, Dict, List
from opentelemetry import trace

from src.models.request import QueryRequest, QueryMode, PersonalizeMode
from src.models.response import QueryResponse, QueryIntent
from src.services.query_router import QueryRouter
from src.services.query_parser import QueryParser
from src.services.hybrid_search import HybridSearch
from src.services.context_builder import ContextBuilder
from src.services.response_generator import ResponseGenerator
from src.services.confidence_scorer import calculate_confidence
from src.services.query_suggestions import suggest_refinements, should_show_suggestions
from src.services.ranking_explainer import add_explanations_to_documents
from src.services.cache import OracleCache, hash_options
from src.services.personalization import decide_personalization, get_user_preferences, get_user_source_memberships
from src.settings import settings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


# ---------------------------------------------------------------------------
# Stop-words stripped before fuzzy topic matching
# ---------------------------------------------------------------------------
_STOP_WORDS = frozenset({
    "a", "an", "the", "and", "or", "of", "in", "on", "at", "to", "for",
    "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "do", "does", "did", "with", "what", "which", "who", "how", "when",
    "where", "why", "latest", "new", "news", "update", "updates",
    "recent", "current", "this", "that", "these", "those",
})


def _query_terms(question: str) -> List[str]:
    """Extract meaningful terms from a question for fuzzy topic matching."""
    tokens = re.findall(r"[a-z0-9][a-z0-9\.\-]*", question.lower())
    return [t for t in tokens if t not in _STOP_WORDS and len(t) >= 3]


def _find_related_topics(question: str, limit: int = 5) -> List[dict]:
    """Query Neo4j for topics and datasources related to terms in the question.

    Returns a list of dicts with keys: name, doc_count, datasource (optional).
    Falls back to empty list on any error so the caller is never blocked.
    """
    try:
        from src.services.keyword_retriever import get_repo
        repo = get_repo()
        terms = _query_terms(question)
        if not terms:
            return []

        results = repo.client.execute_query(
            """
            UNWIND $terms AS term
            MATCH (t:Topic)
            WHERE toLower(t.name) CONTAINS toLower(term)
            WITH t, count(term) AS term_hits
            OPTIONAL MATCH (r:Resource)-[:RELATES_TO]->(t)
            WHERE coalesce(r.archived, false) = false
            WITH t, term_hits, count(r) AS doc_count
            WHERE doc_count > 0
            OPTIONAL MATCH (r2:Resource)-[:RELATES_TO]->(t)
            WHERE coalesce(r2.archived, false) = false
            OPTIONAL MATCH (r2)-[:INGESTED_FROM]->(ds:DataSource)
            WITH t, term_hits, doc_count,
                 collect(DISTINCT ds.name)[0] AS example_source
            RETURN t.name AS name,
                   doc_count,
                   example_source AS datasource
            ORDER BY term_hits DESC, doc_count DESC
            LIMIT $limit
            """,
            parameters={"terms": terms, "limit": limit},
        )
        return results or []
    except Exception as exc:
        logger.warning("Fuzzy topic lookup failed (non-fatal): %s", exc)
        return []


def _build_no_docs_answer(question: str, related: List[dict]) -> str:
    """Build a direct, honest answer when zero documents were retrieved."""
    if not related:
        return (
            "I don't have documents in my knowledge base that match this query. "
            "Try asking about Wi-Fi Alliance certifications, IETF working groups, "
            "or specific Wi-Fi technologies like Wi-Fi 6, Wi-Fi 7, or Passpoint."
        )

    lines = ["I don't have documents that directly match this query. Related topics I do have coverage on:\n"]
    for r in related:
        source = f" — via {r['datasource']}" if r.get("datasource") else ""
        lines.append(f"- **{r['name']}** ({r['doc_count']} documents{source})")

    lines.append(
        "\nAsk me about any of these topics for a sourced answer, "
        "or rephrase your question to focus on one of them."
    )
    return "\n".join(lines)


class BaselineEngine:
    """
    Baseline answer engine using the existing Oracle pipeline.
    
    This is the sophisticated hybrid search pipeline with:
    - Intent classification
    - Entity extraction
    - Hybrid search (keyword + vector + graph with RRF fusion)
    - Graph context building
    - LLM synthesis with citations
    - Confidence scoring
    
    This engine serves as the control group in A/B testing.
    """
    
    def __init__(self):
        """Initialize the baseline engine with existing services."""
        self.query_router = QueryRouter()
        self.query_parser = QueryParser()
        self.hybrid_search = HybridSearch()
        self.context_builder = ContextBuilder()
        self.response_generator = ResponseGenerator()
        
        logger.info("Initialized BaselineEngine")
    
    def get_name(self) -> str:
        """Get engine name."""
        return "baseline"
    
    def get_capabilities(self) -> Dict[str, any]:
        """Get baseline engine capabilities."""
        return {
            "name": "baseline",
            "description": "Sophisticated hybrid search with intent classification and graph context",
            "features": [
                "intent_classification",
                "entity_extraction",
                "hybrid_search",
                "vector_search",
                "graph_traversal",
                "context_building",
                "confidence_scoring",
                "query_suggestions",
                "personalization"
            ],
            "supported_modes": ["answer", "search", "summary"],
            "cache_enabled": settings.cache_enabled,
        }
    
    async def query(
        self,
        request: QueryRequest,
        user: Optional[dict] = None,
        span = None,
        query_id: Optional[str] = None
    ) -> QueryResponse:
        """
        Execute the baseline query pipeline.
        
        This wraps the existing Oracle pipeline logic from routes/query.py
        """
        start_time = time.time()
        
        # Use provided query ID or generate new one
        if not query_id:
            query_id = str(uuid.uuid4())
        
        # Create span if not provided
        if span is None:
            span = tracer.start_span("baseline_engine.query")
        
        span.set_attribute("engine.name", "baseline")
        span.set_attribute("oracle.query_id", str(query_id))
        span.set_attribute("oracle.question", request.question[:100])
        span.set_attribute("oracle.mode", request.mode.value)
        
        logger.info(
            f"[{query_id}] Baseline pipeline: question='{request.question[:80]}...' "
            f"mode={request.mode.value} user={request.user_id}"
        )
        
        try:
            # Extract options with defaults
            options = request.options
            personalize_mode = getattr(options, 'personalize', PersonalizeMode.AUTO) if options else PersonalizeMode.AUTO
            max_documents = getattr(options, 'max_documents', settings.default_max_documents) if options else settings.default_max_documents
            min_relevance = getattr(options, 'min_relevance', settings.min_relevance_score) if options else settings.min_relevance_score
            
            # Phase 1: Intent Classification (needed for personalization decision)
            with tracer.start_as_current_span("baseline.classify_intent"):
                intent_result = await self.query_router.classify_intent(request.question)
                intent = intent_result.intent
                intent_confidence = intent_result.confidence
                
                span.set_attribute("oracle.intent", intent.value)
                span.set_attribute("oracle.intent_confidence", intent_confidence)
                
                logger.info(
                    f"[{query_id}] Intent: {intent.value} "
                    f"(confidence={intent_confidence:.2f})"
                )
            
            # Phase 2: Entity Extraction (needed for personalization decision)
            with tracer.start_as_current_span("baseline.parse_query"):
                parsed = await self.query_parser.parse(request.question)
                
                logger.info(
                    f"[{query_id}] Parsed: topics={len(parsed.topics) if parsed.topics else 0} "
                    f"orgs={len(parsed.organizations) if parsed.organizations else 0} "
                    f"people={len(parsed.people) if parsed.people else 0}"
                )
            
            # Decide personalization (with all required parameters)
            cache = await OracleCache.get_cache()
            personalization_decision = None
            personalization_enabled = False
            
            if request.user_id:
                try:
                    personalization_decision = await decide_personalization(
                        mode=personalize_mode,
                        user_id=str(request.user_id),
                        question=request.question,
                        intent=intent,
                        parsed_topics=parsed.topics or [],
                        parsed_orgs=parsed.organizations or [],
                        parsed_people=parsed.people or []
                    )
                    personalization_enabled = personalization_decision.should_personalize
                    
                    if personalization_enabled:
                        span.set_attribute("oracle.personalized", True)
                        logger.info(f"[{query_id}] Personalization enabled: {personalization_decision.reason}")
                except Exception as e:
                    logger.warning(f"[{query_id}] Personalization decision failed: {e}")
                    personalization_enabled = False
            
            if settings.cache_enabled and not personalization_enabled:
                options_hash = hash_options({
                    "mode": request.mode.value,
                    "max_documents": max_documents,
                    "min_relevance": min_relevance,
                })
                
                cached = await cache.get_query_response(
                    query=request.question,
                    mode=request.mode.value,
                    options_hash=options_hash
                )
                
                if cached:
                    span.set_attribute("oracle.cache_hit", True)
                    logger.info(f"[{query_id}] Cache hit - returning cached response")
                    
                    # Add query_id and processing time
                    cached["query_id"] = str(query_id)
                    cached["metadata"]["processing_time_ms"] = int((time.time() - start_time) * 1000)
                    cached["metadata"]["cache_hit"] = True
                    
                    return QueryResponse(**cached)
            
            span.set_attribute("oracle.cache_hit", False)
            
            # Build filters from parsed query
            filters = {
                "topics": parsed.topics,
                "organizations": parsed.organizations,
                "people": parsed.people,
                "start_date": parsed.start_date,
                "end_date": parsed.end_date,
                "category": parsed.category,
                "keywords": parsed.keywords,
            }

            # Load user source memberships and apply to filters
            user_excluded_datasources: list = []
            user_preferred_datasources: list = []
            if request.user_id:
                try:
                    memberships = get_user_source_memberships(str(request.user_id))
                    user_excluded_datasources = memberships.get("ignored", [])
                    user_preferred_datasources = memberships.get("joined", [])
                    if user_excluded_datasources:
                        logger.info(f"[{query_id}] Baseline: excluding datasources {user_excluded_datasources}")
                    # Pass explicit datasource_ids from request, or user's preferred (if no explicit filter)
                    request_datasource_ids = getattr(options, 'datasource_ids', None) if options else None
                    if user_excluded_datasources:
                        filters["excluded_datasource_ids"] = user_excluded_datasources
                    if user_preferred_datasources and not request_datasource_ids:
                        filters["preferred_datasource_ids"] = user_preferred_datasources
                except Exception as e:
                    logger.warning(f"[{query_id}] Failed to fetch source memberships (baseline): {e}")
            
            # Phase 3: Hybrid Search
            with tracer.start_as_current_span("baseline.hybrid_search"):
                search_result = await self.hybrid_search.search(
                    query=request.question,
                    filters=filters,
                    intent=intent,
                    max_results=max_documents,
                )
                
                documents = search_result.documents
                strategies_used = search_result.strategies_used

                # Apply source membership filters post-retrieval
                if user_excluded_datasources:
                    before_count = len(documents)
                    documents = [
                        d for d in documents
                        if getattr(d, 'datasource_id', None) not in user_excluded_datasources
                    ]
                    if len(documents) < before_count:
                        logger.info(
                            f"[{query_id}] Baseline: excluded {before_count - len(documents)} "
                            f"docs from ignored datasources"
                        )
                if user_preferred_datasources and documents:
                    for d in documents:
                        ds_id = getattr(d, 'datasource_id', None) or ""
                        if ds_id in user_preferred_datasources and hasattr(d, 'relevance_score'):
                            d.relevance_score = (d.relevance_score or 0.0) * 1.4
                    documents.sort(key=lambda d: getattr(d, 'relevance_score', 0.0) or 0.0, reverse=True)
                
                span.set_attribute("oracle.documents_found", len(documents))
                span.set_attribute("oracle.strategies", ",".join(strategies_used))
                
                logger.info(
                    f"[{query_id}] Retrieved {len(documents)} documents "
                    f"via {', '.join(strategies_used)}"
                )
            
            # Phase 4: Build Graph Context
            graph_context = None
            if settings.graph_search_enabled and documents:
                with tracer.start_as_current_span("baseline.build_context"):
                    graph_context = await self.context_builder.build(
                        documents=documents,
                        graph_data=search_result.graph_data if hasattr(search_result, 'graph_data') else None
                    )
                    
                    if graph_context:
                        logger.info(
                            f"[{query_id}] Graph context: "
                            f"topics={len(graph_context.central_topics)} "
                            f"orgs={len(graph_context.key_organizations)} "
                            f"people={len(graph_context.key_people)}"
                        )
            
            # Phase 5: Generate Answer
            answer_text = ""
            citations = []
            
            if request.mode == QueryMode.ANSWER:
                with tracer.start_as_current_span("baseline.generate_answer"):
                    # --- Zero-doc hallucination guard ---
                    # When the retrieval pipeline found no documents, do NOT call the LLM —
                    # it will hallucinate from training data.  Instead, run a fuzzy topic
                    # lookup so the user gets an honest, grounded response with related
                    # topics they CAN ask about.
                    if not documents:
                        logger.info(
                            "[%s] Zero documents retrieved — skipping LLM, returning fuzzy topic suggestions",
                            query_id,
                        )
                        related = _find_related_topics(request.question)
                        answer_text = _build_no_docs_answer(request.question, related)
                        # Return immediately — no scoring, no caching, no LLM cost
                        processing_time_ms = int((time.time() - start_time) * 1000)
                        from src.models.response import RetrievalMetadata
                        metadata = RetrievalMetadata(
                            intent=intent,
                            intent_confidence=intent_confidence,
                            strategies_used=strategies_used,
                            total_candidates=0,
                            processing_time_ms=processing_time_ms,
                            llm_tokens_used=None,
                        )
                        return QueryResponse(
                            query_id=str(query_id),
                            answer=answer_text,
                            mode="answer",
                            documents=[],
                            citations=[],
                            graph_context=None,
                            confidence_score=0.0,
                            suggestions=[],
                            personalization_applied=False,
                            metadata=metadata,
                        )

                    # Get user context if personalization is enabled
                    user_context_str = None
                    if personalization_enabled and personalization_decision and personalization_decision.user_context:
                        user_context_str = personalization_decision.user_context.to_prompt_section()
                    
                    answer_result = await self.response_generator.generate_answer(
                        question=request.question,
                        documents=documents[:10],  # Limit for context window
                        graph_context=graph_context,
                        intent=intent,
                        user_context=user_context_str
                    )
                    
                    answer_text = answer_result.answer
                    citations = answer_result.citations
                    
                    logger.info(
                        f"[{query_id}] Generated answer: {len(answer_text)} chars, "
                        f"{len(citations)} citations"
                    )
            
            # Phase 6: Add Ranking Explanations
            if settings.explainability_enabled:
                documents = add_explanations_to_documents(
                    documents=documents,
                    query=request.question,
                    intent=intent
                )
            
            # Phase 7: Calculate Confidence
            confidence_score = None
            if settings.confidence_scoring_enabled and answer_text:
                confidence_score = calculate_confidence(
                    answer=answer_text,
                    documents=documents,
                    citations=citations,
                    query=request.question,
                    intent=intent
                )
                
                span.set_attribute("oracle.confidence", confidence_score.score)
                logger.info(f"[{query_id}] Confidence: {confidence_score.score:.2f}")
            
            # Phase 8: Query Suggestions
            query_suggestions = []
            if settings.suggestions_enabled:
                if should_show_suggestions(
                    documents=documents,
                    min_results=3,
                    min_relevance=min_relevance
                ):
                    query_suggestions = await suggest_refinements(
                        query=request.question,
                        documents=documents,
                        graph_context=graph_context,
                        intent=intent,
                        max_suggestions=settings.suggestions_max_count
                    )
                    
                    if query_suggestions:
                        logger.info(
                            f"[{query_id}] Suggestions: {len(query_suggestions)}"
                        )
            
            # Build response
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            # Build metadata object
            from src.models.response import RetrievalMetadata
            metadata = RetrievalMetadata(
                intent=intent,
                intent_confidence=intent_confidence,
                strategies_used=strategies_used,
                total_candidates=len(documents),
                processing_time_ms=processing_time_ms,
                llm_tokens_used=None
            )
            
            response = QueryResponse(
                query_id=str(query_id),
                answer=answer_text,
                mode="answer" if request.mode == QueryMode.ANSWER else "retrieval",
                documents=documents,
                citations=citations,
                graph_context=graph_context,
                confidence_score=confidence_score.score if confidence_score else None,
                suggestions=query_suggestions,
                personalization_applied=personalization_enabled,
                metadata=metadata
            )
            
            # Cache response if not personalized
            if settings.cache_enabled and not personalization_enabled:
                await cache.set_query_response(
                    query=request.question,
                    mode=request.mode.value,
                    options_hash=options_hash,
                    response=response.model_dump(),
                    ttl=settings.cache_query_ttl
                )
            
            span.set_attribute("oracle.processing_time_ms", processing_time_ms)
            logger.info(
                f"[{query_id}] Baseline complete: {processing_time_ms}ms, "
                f"{len(documents)} docs, confidence={confidence_score.score if confidence_score else 'N/A'}"
            )
            
            return response
            
        except Exception as e:
            span.set_attribute("oracle.error", str(e))
            logger.error(f"[{query_id}] Baseline engine error: {e}", exc_info=True)
            raise
