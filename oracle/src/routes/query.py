"""Query endpoint for Oracle Service."""

from fastapi import APIRouter, Depends, HTTPException
from typing import Optional
import logging
import time
import json
import uuid

from opentelemetry import trace

from common.auth_middleware import get_user_context, require_user_context

from src.exceptions import LLMTimeoutError
from src.models.request import (
    QueryRequest, 
    QueryMode,
    PersonalizeMode,
    AnalyzeRequest, 
    AnalyzeResponse, 
    EnhanceRequest,
    FeedbackRequest,
)
from src.models.response import (
    QueryResponse,
    QueryIntent,
    Document,
    Citation,
    GraphContext,
    RetrievalMetadata,
    ErrorResponse,
    EnhanceResponse,
    EnhanceMetadata,
    DataSourceInfo,
    DataSourcesResponse,
    FeedbackResponse,
)
from src.services.query_router import QueryRouter
from src.services.query_parser import QueryParser
from src.services.keyword_retriever import KeywordRetriever, get_repo
from src.services.hybrid_search import HybridSearch
from src.services.context_builder import ContextBuilder
from src.services.response_generator import ResponseGenerator
from src.services.confidence_scorer import calculate_confidence, ConfidenceScore
from src.services.query_suggestions import suggest_refinements, should_show_suggestions
from src.services.ranking_explainer import add_explanations_to_documents
from src.services.query_analyzer import analyze_query as analyze_query_impl
from src.services.cache import OracleCache, hash_options
from src.services.query_history import get_query_history_service
from src.services.personalization import decide_personalization, get_user_preferences
from src.services.ab_test import should_use_fast_pipeline
from src.engines.baseline_engine import BaselineEngine
from src.engines.fast_engine import FastEngine
from src.metrics import record_query_metrics, record_enhance_metrics, record_feedback_metrics
from src.routes.metrics import record_query, record_personalization, record_feedback, ACTIVE_QUERIES
from src.settings import settings

router = APIRouter(tags=["query"])
logger = logging.getLogger(__name__)

# Get tracer for enhanced spans
tracer = trace.get_tracer(__name__)

# Initialize services (legacy - for backward compatibility)
query_router = QueryRouter()
query_parser = QueryParser()
keyword_retriever = KeywordRetriever()
hybrid_search = HybridSearch()
context_builder = ContextBuilder()
response_generator = ResponseGenerator()

# Initialize answer engines
baseline_engine = BaselineEngine()
fast_engine = FastEngine()


@router.post("/analyze", response_model=AnalyzeResponse)
@require_user_context
async def analyze_query_endpoint(
    request: AnalyzeRequest,
    user: Optional[dict] = Depends(get_user_context)
) -> AnalyzeResponse:
    """
    Analyze a query for quality before execution.
    
    Returns feedback on query quality and suggests improvements
    if the query could be better formulated.
    """
    try:
        result = await analyze_query_impl(request.question)
        
        logger.info(
            f"Query analysis: query='{request.question[:50]}...' "
            f"is_good={result.is_good_query} score={result.quality_score:.2f} "
            f"issues={len(result.issues)} revised={'yes' if result.revised_query else 'no'}"
        )
        
        response = AnalyzeResponse(
            is_good_query=result.is_good_query,
            issues=result.issues,
            suggested_query=result.revised_query,
            suggestion_reason=result.revision_reason,
        )
        
        if result.revised_query:
            logger.info(f"Suggested revision: '{result.revised_query[:80]}...'")
        
        return response
    except Exception as e:
        logger.exception(f"Query analysis failed: {e}")
        # Return a permissive response on error - don't block queries
        return AnalyzeResponse(
            is_good_query=True,
            issues=[],
            suggested_query=None,
            suggestion_reason=None,
        )


@router.get("/datasources", response_model=DataSourcesResponse)
@require_user_context
async def list_datasources(
    user: Optional[dict] = Depends(get_user_context)
) -> DataSourcesResponse:
    """
    List all available datasources for filtering queries.
    
    Returns a list of datasources with their IDs, names, and document counts.
    This is used for @mention autocomplete in the chat interface.
    """
    try:
        repo = get_repo()
        
        # Query all DataSource nodes with document counts
        query = """
            MATCH (ds:DataSource)
            OPTIONAL MATCH (r:Resource)-[:INGESTED_FROM]->(ds)
            WITH ds, count(r) AS doc_count
            RETURN ds.datasource_id AS datasource_id,
                   ds.name AS name,
                   ds.description AS description,
                   doc_count
            ORDER BY doc_count DESC
        """
        
        results = repo.client.execute_query(query)
        
        datasources = []
        for record in results:
            datasources.append(DataSourceInfo(
                datasource_id=record.get("datasource_id", ""),
                name=record.get("name") or record.get("datasource_id", "Unknown"),
                description=record.get("description"),
                document_count=record.get("doc_count", 0),
            ))
        
        logger.info(f"Retrieved {len(datasources)} datasources")
        return DataSourcesResponse(datasources=datasources)
        
    except Exception as e:
        logger.exception(f"Failed to list datasources: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "INTERNAL_ERROR",
                "message": str(e),
            }
        )


@router.post("/query", response_model=QueryResponse)
@require_user_context
async def query(
    request: QueryRequest,
    user: Optional[dict] = Depends(get_user_context)
) -> QueryResponse:
    """
    Main query endpoint for Oracle Service.
    
    Processes a natural language question and returns either:
    - Retrieval mode: Ranked list of relevant documents
    - Answer mode: LLM-generated answer with citations
    
    The pipeline:
    1. Check cache for identical queries (Phase 4)
    2. Classify query intent (entity_focused, topic_discovery, etc.)
    3. Extract entities, dates, and filters from query
    4. Execute parallel retrieval strategies based on intent (Phase 4)
    5. Build graph context around retrieved documents
    6. Add ranking explanations to documents (Phase 4)
    7. Generate response based on mode (retrieval vs answer)
    8. Calculate confidence score for answers (Phase 4)
    9. Generate query suggestions if results are poor (Phase 4)
    10. Cache the response (Phase 4)
    11. Record analytics metrics (Phase 6)
    """
    start_time = time.time()
    llm_tokens_used = 0
    cache_hit = False
    query_id = str(uuid.uuid4())  # Generate unique ID for tracking
    
    # Phase 6: Start enhanced span for query tracking
    with tracer.start_as_current_span("oracle.query") as span:
        span.set_attribute("oracle.query_id", query_id)
        span.set_attribute("oracle.query.text", request.question[:200])  # Truncate for privacy
        span.set_attribute("oracle.query.mode_requested", request.mode.value)
        span.set_attribute("oracle.user_id", str(request.user_id) if request.user_id else "anonymous")
        
        try:
            logger.info(f"[{query_id}] Processing query for user={request.user_id}: {request.question[:100]}...")
            
            # Determine which pipeline to use (A/B test)
            use_fast_pipeline = should_use_fast_pipeline(str(request.user_id) if request.user_id else None)
            pipeline_name = "fast" if use_fast_pipeline else "baseline"
            
            span.set_attribute("oracle.pipeline", pipeline_name)
            span.set_attribute("oracle.ab_test_enabled", settings.fast_pipeline_enabled)
            
            logger.info(f"[{query_id}] Using {pipeline_name} pipeline (A/B test)")
            
            # Shadow mode: run fast pipeline but return baseline
            if settings.fast_pipeline_shadow_mode and not use_fast_pipeline:
                logger.info(f"[{query_id}] Shadow mode: running fast pipeline in background")
                # TODO: Implement async shadow execution
                pass
            
            # Select engine
            if use_fast_pipeline:
                engine = fast_engine
                
                # Try fast engine with fallback to baseline
                try:
                    response = await engine.query(request, user, span, query_id)
                    
                    # Set pipeline field to indicate fast pipeline was used
                    response.pipeline = "fast"
                    
                    # Record successful fast pipeline execution
                    processing_time_ms = response.metadata.processing_time_ms
                    
                    logger.info(
                        f"[{query_id}] Fast pipeline success: {processing_time_ms}ms, "
                        f"route={response.metadata.strategies_used[0] if response.metadata.strategies_used else 'unknown'}"
                    )
                    
                    span.set_attribute("oracle.fast_success", True)
                    
                    # Record metrics
                    record_query_metrics(
                        intent=response.metadata.intent.value,
                        mode=response.mode,
                        documents_count=len(response.documents),
                        confidence_score=response.confidence_score if response.confidence_score else None,
                        latency_ms=processing_time_ms,
                        cache_hit=False,  # Cache hit info not exposed in metadata
                        has_suggestions=len(response.suggestions) > 0,
                        strategies_used=response.metadata.strategies_used,
                    )
                    
                    # Store query history
                    if settings.query_history_enabled:
                        try:
                            history_service = get_query_history_service()
                            await history_service.save_query(
                                query_id=query_id,
                                user_id=str(request.user_id) if request.user_id else None,
                                question=request.question,
                                mode=response.mode,
                                response=response.model_dump(),
                                intent=response.metadata.intent.value if response.metadata else None,
                                intent_confidence=response.metadata.intent_confidence if response.metadata else None,
                                processing_time_ms=response.metadata.processing_time_ms if response.metadata else None,
                                cache_hit=False,
                                strategies_used=response.metadata.strategies_used if response.metadata else []
                            )
                        except Exception as e:
                            logger.error(f"Failed to store query history: {e}")
                    
                    return response
                    
                except Exception as e:
                    # Fast pipeline failed, fallback to baseline
                    if settings.fast_fallback_to_baseline:
                        logger.warning(
                            f"[{query_id}] Fast pipeline failed, falling back to baseline: {e}"
                        )
                        span.set_attribute("oracle.fast_success", False)
                        span.set_attribute("oracle.fast_fallback_reason", str(e))
                        
                        # Switch to baseline engine
                        engine = baseline_engine
                        use_fast_pipeline = False
                        pipeline_name = "baseline"
                    else:
                        # Re-raise if fallback disabled
                        raise
            else:
                engine = baseline_engine
            
            # Execute engine (baseline or fallback)
            response = await engine.query(request, user, span, query_id)
            
            # Set pipeline field to indicate which pipeline was used
            response.pipeline = pipeline_name
            
            # Record metrics
            processing_time_ms = response.metadata.processing_time_ms
            
            record_query_metrics(
                intent=response.metadata.intent.value,
                mode=response.mode,
                documents_count=len(response.documents),
                confidence_score=response.confidence_score if response.confidence_score else None,
                latency_ms=processing_time_ms,
                cache_hit=False,  # Cache hit info not exposed in metadata
                has_suggestions=len(response.suggestions) > 0,
                strategies_used=response.metadata.strategies_used,
            )
            
            # Store query history
            if settings.query_history_enabled:
                try:
                    history_service = get_query_history_service()
                    await history_service.save_query(
                        query_id=query_id,
                        user_id=str(request.user_id) if request.user_id else None,
                        question=request.question,
                        mode=response.mode,
                        response=response.model_dump(),
                        intent=response.metadata.intent.value if response.metadata else None,
                        intent_confidence=response.metadata.intent_confidence if response.metadata else None,
                        processing_time_ms=response.metadata.processing_time_ms if response.metadata else None,
                        cache_hit=False,
                        strategies_used=response.metadata.strategies_used if response.metadata else []
                    )
                except Exception as e:
                    logger.error(f"Failed to store query history: {e}")
            
            return response
            
            # OLD PIPELINE CODE BELOW (kept for reference, not executed)
            # =====================================================
            if False:  # Unreachable code - old pipeline preserved
                # Apply default options if not provided
                options = request.options or {}
                max_documents = getattr(options, 'max_documents', settings.default_max_documents) if options else settings.default_max_documents
                include_graph_context = getattr(options, 'include_graph_context', True) if options else True
            
            # Get personalization mode early to determine cache eligibility
            personalize_mode = getattr(options, 'personalize', PersonalizeMode.AUTO) if options else PersonalizeMode.AUTO
            
            # Check if user might have personalization applied
            # We skip cache if personalization could affect the response
            may_personalize = False
            if personalize_mode == PersonalizeMode.ON:
                may_personalize = True
            elif personalize_mode == PersonalizeMode.AUTO and request.user_id:
                # For AUTO mode, check if user has preferences that could trigger personalization
                try:
                    user_prefs = await get_user_preferences(str(request.user_id))
                    may_personalize = not user_prefs.is_empty()
                except Exception as e:
                    logger.warning(f"Failed to check user preferences for cache decision: {e}")
                    may_personalize = False  # Default to allowing cache on error
            
            # Phase 4: Check cache for identical queries (skip for personalized queries)
            cache = await OracleCache.get_cache()
            options_hash = hash_options(options.__dict__ if options else {})
            
            if settings.cache_enabled and cache.is_available() and not may_personalize:
                cached_response = await cache.get_query_response(
                    query=request.question,
                    mode=request.mode.value,
                    options_hash=options_hash,
                )
                if cached_response:
                    logger.info("Cache hit - returning cached response")
                    cache_hit = True
                    span.set_attribute("oracle.cache_hit", True)
                    # Update processing time for cached response
                    processing_time_ms = int((time.time() - start_time) * 1000)
                    cached_response["metadata"]["processing_time_ms"] = processing_time_ms
                    
                    # Phase 6: Record metrics for cache hit
                    cached_intent = cached_response.get("metadata", {}).get("intent", "unknown")
                    cached_mode = cached_response.get("mode", "retrieval")
                    record_query_metrics(
                        intent=cached_intent,
                        mode=cached_mode,
                        documents_count=len(cached_response.get("documents", [])),
                        confidence_score=cached_response.get("confidence_score"),
                        latency_ms=processing_time_ms,
                        cache_hit=True,
                        has_suggestions=len(cached_response.get("suggestions", [])) > 0,
                        strategies_used=cached_response.get("metadata", {}).get("strategies_used", []),
                    )
                    
                    return QueryResponse(**cached_response)
            
            span.set_attribute("oracle.cache_hit", False)
            
            # Step 1: Classify query intent
            intent_result = await query_router.classify_intent(request.question)
            intent = intent_result.intent
            intent_confidence = intent_result.confidence
            llm_tokens_used += intent_result.tokens_used
            
            span.set_attribute("oracle.intent", intent.value)
            span.set_attribute("oracle.intent_confidence", intent_confidence)
            
            logger.info(f"Intent classified: {intent.value} (confidence: {intent_confidence:.2f})")
            
            # Step 2: Extract entities and filters from query
            parsed = await query_parser.parse(request.question)
            llm_tokens_used += parsed.tokens_used
            
            # Merge parsed filters with user-provided options
            filters = {
                "topics": parsed.topics or (getattr(options, 'topics', None) if options else None),
                "organizations": parsed.organizations or (getattr(options, 'organizations', None) if options else None),
                "people": parsed.people,
                "start_date": parsed.start_date or (getattr(options, 'date_start', None) if options else None),
                "end_date": parsed.end_date or (getattr(options, 'date_end', None) if options else None),
                "category": parsed.category,
                "keywords": parsed.keywords,
                "datasource_ids": getattr(options, 'datasource_ids', None) if options else None,
            }
            
            logger.info(f"Parsed filters: topics={filters['topics']}, orgs={filters['organizations']}, dates={filters['start_date']}-{filters['end_date']}, datasources={filters['datasource_ids']}")
            
            # Step 3: Execute hybrid search (keyword + vector + graph retrieval with RRF fusion)
            # Phase 4: Uses parallel retrieval for improved latency
            search_result = await hybrid_search.search(
                query=request.question,
                filters=filters,
                intent=intent,
                max_results=max_documents,
            )
            
            documents = search_result.documents
            total_candidates = search_result.total_candidates
            strategies_used = search_result.strategies_used
            graph_data = search_result.graph_data
            
            span.set_attribute("oracle.documents_count", len(documents))
            span.set_attribute("oracle.total_candidates", total_candidates)
            span.set_attribute("oracle.strategies_used", ",".join(strategies_used))
            
            logger.info(
                f"Hybrid search returned {len(documents)} documents from {total_candidates} candidates "
                f"(strategies: {strategies_used}, keyword: {search_result.keyword_candidates}, "
                f"vector: {search_result.vector_candidates}, graph: {search_result.graph_candidates})"
            )
            
            # Step 4: Build graph context (if requested and documents found)
            graph_context = None
            if include_graph_context and documents:
                graph_context = await context_builder.build(documents, graph_data=graph_data)
            
            # Phase 4: Add ranking explanations to documents
            if settings.explainability_enabled and documents:
                documents = add_explanations_to_documents(
                    documents=documents,
                    query=request.question,
                    intent=intent,
                )
            
            # Step 5: Determine effective mode
            effective_mode = request.mode
            if effective_mode == QueryMode.AUTO:
                # Auto mode: use answer for complex queries, retrieval for simple lookups
                effective_mode = QueryMode.ANSWER if intent_confidence > 0.7 else QueryMode.RETRIEVAL
            
            span.set_attribute("oracle.mode_effective", effective_mode.value)
            
            # Step 5.5: Handle personalization
            personalize_mode = getattr(options, 'personalize', PersonalizeMode.AUTO) if options else PersonalizeMode.AUTO
            user_context_for_prompt = None
            personalization_applied = False
            
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
                    
                    # Record personalization decision in Prometheus
                    record_personalization(
                        applied=personalization_decision.should_personalize,
                        reason=personalization_decision.reason
                    )
                    
                    if personalization_decision.should_personalize:
                        user_context_for_prompt = personalization_decision.user_context.to_prompt_section() if personalization_decision.user_context else None
                        personalization_applied = True
                        span.set_attribute("oracle.personalization_applied", True)
                        span.set_attribute("oracle.personalization_reason", personalization_decision.reason)
                        logger.info(f"Personalization enabled for user {request.user_id} (reason: {personalization_decision.reason})")
                    else:
                        span.set_attribute("oracle.personalization_applied", False)
                        span.set_attribute("oracle.personalization_reason", personalization_decision.reason)
                        logger.info(f"Personalization skipped for user {request.user_id} (reason: {personalization_decision.reason})")
                except Exception as e:
                    logger.warning(f"Failed to decide personalization: {e}")
                    span.set_attribute("oracle.personalization_error", str(e))
            
            # Step 6: Generate response based on mode
            confidence_score = None
            if effective_mode == QueryMode.ANSWER:
                response_result = await response_generator.generate_answer(
                    question=request.question,
                    documents=documents,
                    graph_context=graph_context,
                    intent=intent,
                    user_context=user_context_for_prompt
                )
                answer = response_result.answer
                citations = response_result.citations
                llm_tokens_used += response_result.tokens_used
                
                # Phase 4: Calculate detailed confidence score
                if settings.confidence_scoring_enabled and answer:
                    confidence_result = calculate_confidence(
                        answer=answer,
                        documents=documents,
                        citations=citations,
                        query=request.question,
                        intent=intent,
                    )
                    confidence_score = confidence_result.score
                    span.set_attribute("oracle.confidence_score", confidence_score)
                    span.set_attribute("oracle.confidence_level", confidence_result.level)
                    logger.info(f"Confidence score: {confidence_score:.3f} ({confidence_result.level})")
            else:
                answer = None
                citations = []
            
            # Phase 4: Generate query suggestions if results are poor
            suggestions = []
            if settings.suggestions_enabled and should_show_suggestions(
                documents=documents,
                min_results=settings.suggestions_min_results,
                min_relevance=settings.suggestions_min_relevance,
            ):
                suggestions = await suggest_refinements(
                    query=request.question,
                    documents=documents,
                    graph_context=graph_context,
                    intent=intent,
                    max_suggestions=settings.suggestions_max_count,
                )
                if suggestions:
                    logger.info(f"Generated {len(suggestions)} query suggestions")
            
            has_suggestions = len(suggestions) > 0
            span.set_attribute("oracle.has_suggestions", has_suggestions)
            
            # Calculate processing time
            processing_time_ms = int((time.time() - start_time) * 1000)
            span.set_attribute("oracle.processing_time_ms", processing_time_ms)
            span.set_attribute("oracle.llm_tokens_used", llm_tokens_used)
            
            # Build metadata
            metadata = RetrievalMetadata(
                intent=intent,
                intent_confidence=intent_confidence,
                strategies_used=strategies_used,
                total_candidates=total_candidates,
                processing_time_ms=processing_time_ms,
                llm_tokens_used=llm_tokens_used if llm_tokens_used > 0 else None
            )
            
            # Build response
            response = QueryResponse(
                query_id=query_id,
                mode="answer" if effective_mode == QueryMode.ANSWER else "retrieval",
                answer=answer,
                citations=citations,
                documents=documents,
                graph_context=graph_context,
                metadata=metadata,
                suggestions=suggestions,
                confidence_score=confidence_score,
                personalization_applied=personalization_applied
            )
            
            # Phase 6: Record analytics metrics (OpenTelemetry)
            record_query_metrics(
                intent=intent.value,
                mode=response.mode,
                documents_count=len(documents),
                confidence_score=confidence_score,
                latency_ms=processing_time_ms,
                cache_hit=cache_hit,
                has_suggestions=has_suggestions,
                strategies_used=strategies_used,
            )
            
            # Record Prometheus metrics
            record_query(
                intent=intent.value,
                mode=response.mode,
                latency_seconds=processing_time_ms / 1000.0,
                confidence=confidence_score,
                documents_count=len(documents),
                cache_hit=cache_hit,
                personalized=personalization_applied
            )
            
            # Phase 6: Structured logging for Loki
            if settings.analytics_logging_enabled:
                logger.info(
                    "query_completed",
                    extra={
                        "event_type": "oracle_query",
                        "query_id": query_id,
                        "query_text": request.question[:200],
                        "intent": intent.value,
                        "intent_confidence": intent_confidence,
                        "mode": response.mode,
                        "documents_count": len(documents),
                        "confidence_score": confidence_score,
                        "processing_time_ms": processing_time_ms,
                        "cache_hit": cache_hit,
                        "has_suggestions": has_suggestions,
                        "strategies_used": strategies_used,
                        "llm_tokens_used": llm_tokens_used,
                    }
                )
            
            logger.info(f"Query completed in {processing_time_ms}ms, mode={response.mode}, docs={len(documents)}, personalized={personalization_applied}")
            
            # Phase 4: Cache the response (only cache successful responses with results)
            # Don't cache: empty results, low confidence answers, personalized responses, or error-like responses
            should_cache = (
                settings.cache_enabled 
                and cache.is_available() 
                and not cache_hit
                and not personalization_applied  # Don't cache personalized responses
                and len(documents) > 0  # Must have found some documents
                and (confidence_score is None or confidence_score >= 0.3)  # Don't cache very low confidence
            )
            
            if should_cache:
                await cache.set_query_response(
                    query=request.question,
                    mode=request.mode.value,
                    options_hash=options_hash,
                    response=response.model_dump(),
                    ttl=settings.cache_query_ttl,
                )
            elif not cache_hit and settings.cache_enabled:
                if personalization_applied:
                    logger.debug(f"Skipping cache for personalized response")
                else:
                    logger.info(f"Skipping cache for poor results (docs={len(documents)}, confidence={confidence_score})")
            
            # Phase 6: Save to query history for analytics
            if settings.query_history_enabled:
                try:
                    query_history = get_query_history_service()
                    # Get values from options, with defaults
                    options = request.options
                    opts_max_documents = getattr(options, 'max_documents', settings.default_max_documents) if options else settings.default_max_documents
                    opts_include_graph_context = getattr(options, 'include_graph_context', True) if options else True
                    opts_datasource_filter = getattr(options, 'datasource_ids', None) if options else None
                    if opts_datasource_filter:
                        opts_datasource_filter = ','.join(opts_datasource_filter)
                    await query_history.save_query(
                        query_id=query_id,
                        question=request.question,
                        mode=request.mode.value,
                        response=response.model_dump(),
                        user_id=user.get("user_id") if user else None,
                        session_id=user.get("session_id") if user else None,
                        max_documents=opts_max_documents,
                        include_graph_context=opts_include_graph_context,
                        datasource_filter=opts_datasource_filter,
                        intent=intent.value,
                        intent_confidence=intent_confidence,
                        processing_time_ms=processing_time_ms,
                        llm_tokens_used=llm_tokens_used,
                        cache_hit=cache_hit,
                        strategies_used=strategies_used,
                    )
                except Exception as hist_err:
                    logger.warning(f"Failed to save query history: {hist_err}")
            
            return response
            
        except Exception as e:
            # Phase 6: Record error metrics
            processing_time_ms = int((time.time() - start_time) * 1000)
            span.set_attribute("oracle.error", True)
            span.set_attribute("oracle.error_message", str(e)[:200])
            span.record_exception(e)
            
            record_query_metrics(
                intent="unknown",
                mode=request.mode.value,
                documents_count=0,
                confidence_score=None,
                latency_ms=processing_time_ms,
                cache_hit=cache_hit,
                has_suggestions=False,
                strategies_used=[],
                error=True,
            )
            
            # Phase 6: Save error to query history
            if settings.query_history_enabled:
                try:
                    query_history = get_query_history_service()
                    await query_history.save_query(
                        query_id=query_id,
                        question=request.question,
                        mode=request.mode.value,
                        response={},
                        user_id=user.get("user_id") if user else None,
                        processing_time_ms=processing_time_ms,
                        cache_hit=cache_hit,
                        error=True,
                        error_message=str(e)[:500],
                    )
                except Exception as hist_err:
                    logger.warning(f"Failed to save error to query history: {hist_err}")
            
            logger.exception(f"Query failed: {e}")
            raise HTTPException(
                status_code=500,
                detail={
                    "error": "INTERNAL_ERROR",
                    "message": str(e),
                }
            )


@router.post("/enhance", response_model=EnhanceResponse)
@require_user_context
async def enhance_answer(
    request: EnhanceRequest,
    user: Optional[dict] = Depends(get_user_context)
) -> EnhanceResponse:
    """
    Enhance an answer by analyzing document content.
    
    This endpoint provides more detailed answers by:
    1. Fetching full content for the specified documents
    2. Chunking and re-ranking by relevance to the question
    3. Generating a comprehensive answer with direct quotes
    
    Use this when the summary-based answer from /oracle/query isn't
    detailed enough and you need deeper analysis of the source documents.
    
    Phase 5 of Oracle Service implementation.
    """
    from src.services.enhance import generate_enhanced_answer
    
    if not settings.enhance_enabled:
        raise HTTPException(
            status_code=503,
            detail={
                "error": "FEATURE_DISABLED",
                "message": "Enhanced answers feature is disabled",
            }
        )
    
    try:
        logger.info(
            f"Processing enhance request: question='{request.question[:50]}...' "
            f"documents={len(request.documents)}"
        )
        
        result = await generate_enhanced_answer(
            question=request.question,
            documents=request.documents,
        )
        
        logger.info(
            f"Enhance completed in {result.metadata.processing_time_ms}ms, "
            f"docs_fetched={result.metadata.documents_fetched}, "
            f"chunks_used={result.metadata.chunks_used}, "
            f"quotes={len(result.direct_quotes)}"
        )
        
        return EnhanceResponse(
            enhanced_answer=result.answer,
            direct_quotes=result.direct_quotes,
            citations=result.citations,
            metadata=result.metadata,
            confidence_score=result.confidence_score,
        )
    
    except LLMTimeoutError as e:
        logger.warning(f"Enhance timed out: {e}")
        raise HTTPException(
            status_code=504,
            detail={
                "error": "LLM_TIMEOUT",
                "message": "The enhanced answer generation timed out. Please try again.",
            }
        )
        
    except Exception as e:
        logger.exception(f"Enhance failed: {e}")
        raise HTTPException(
            status_code=500,
            detail={
                "error": "INTERNAL_ERROR",
                "message": str(e),
            }
        )


@router.post("/feedback", response_model=FeedbackResponse)
@require_user_context
async def submit_feedback(
    request: FeedbackRequest,
    user: Optional[dict] = Depends(get_user_context)
) -> FeedbackResponse:
    """
    Submit user feedback for a query response.
    
    Allows users to indicate whether a response was helpful or not.
    Feedback is logged and tracked via metrics for quality monitoring.
    
    Phase 6 of Oracle Service implementation.
    """
    feedback_id = f"fb-{uuid.uuid4()}"
    
    try:
        # Record feedback metrics
        record_feedback_metrics(
            feedback_type=request.feedback.value,
            intent=request.intent,
            mode=request.mode,
        )
        
        # Phase 6: Update query history with feedback
        if settings.query_history_enabled and request.query_id:
            try:
                query_history = get_query_history_service()
                await query_history.update_feedback(
                    query_id=request.query_id,
                    feedback_type=request.feedback.value,
                    comment=request.comment,
                )
            except Exception as hist_err:
                logger.warning(f"Failed to update query history with feedback: {hist_err}")
        
        # Phase 6: Structured logging for feedback
        if settings.analytics_logging_enabled:
            logger.info(
                "feedback_submitted",
                extra={
                    "event_type": "oracle_feedback",
                    "feedback_id": feedback_id,
                    "query_id": request.query_id,
                    "feedback_type": request.feedback.value,
                    "has_comment": request.comment is not None,
                    "comment_length": len(request.comment) if request.comment else 0,
                    "intent": request.intent,
                    "mode": request.mode,
                }
            )
        
        logger.info(
            f"Feedback recorded: query_id={request.query_id} "
            f"feedback={request.feedback.value} "
            f"intent={request.intent} mode={request.mode}"
        )
        
        return FeedbackResponse(
            status="recorded",
            feedback_id=feedback_id,
            message="Thank you for your feedback",
        )
        
    except Exception as e:
        logger.exception(f"Failed to record feedback: {e}")
        # Don't fail the request - just log and return success
        # Feedback is nice-to-have, not critical
        return FeedbackResponse(
            status="recorded",
            feedback_id=feedback_id,
            message="Thank you for your feedback",
        )
