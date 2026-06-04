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
from src.services.fast_cache import normalize_query
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


def _enrich_user_upload_sources(documents) -> None:
    """Replace generic "User Upload" source label with the uploader's email.

    For documents originating from the user_upload datasource, look up the
    uploader Person via the UPLOADED_BY relationship and overwrite the
    `source` field with "Uploaded by <email>" (or name as fallback). One
    bulk Cypher query covers all user-upload docs in the result set.

    Best-effort — any failure logs at debug and leaves docs untouched so
    user-facing answers are unaffected.
    """
    if not documents:
        return
    user_upload_urls = [
        d.url for d in documents
        if getattr(d, "datasource_id", None) == "user_upload" and d.url
    ]
    if not user_upload_urls:
        return
    try:
        repo = get_repo()
        rows = repo.client.execute_query(
            """
            MATCH (r:Resource)-[:UPLOADED_BY]->(p:Person)
            WHERE r.url IN $urls
            RETURN r.url AS url, p.email AS email, p.name AS name
            """,
            parameters={"urls": user_upload_urls},
        )
        url_to_label: dict[str, str] = {}
        for row in (rows or []):
            label = None
            if row.get("email"):
                label = f"Uploaded by {row['email']}"
            elif row.get("name"):
                label = f"Uploaded by {row['name']}"
            if label and row.get("url"):
                url_to_label[row["url"]] = label
        for doc in documents:
            if getattr(doc, "datasource_id", None) == "user_upload":
                new_source = url_to_label.get(doc.url)
                if new_source:
                    doc.source = new_source
    except Exception as exc:
        logger.debug(f"User-upload source enrichment skipped: {exc}")


def _build_history_request_options(request: QueryRequest, response: QueryResponse) -> dict:
    """Persist request options and fast-cache details in existing history JSON."""
    request_options = request.options.model_dump(mode="json") if request.options else {}
    metadata = response.metadata
    request_options.update({
        "pipeline": response.pipeline,
        "normalized_question": normalize_query(request.question),
        "personalization_applied": response.personalization_applied,
        "cache": {
            "overall_hit": metadata.cache_hit,
            "route_hit": metadata.route_cache_hit,
            "result_hit": metadata.result_cache_hit,
            "answer_hit": metadata.answer_cache_hit,
            "bypass_reason": metadata.cache_bypass_reason,
        },
    })
    return request_options


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
        
        # Query all DataSource nodes with document counts, hierarchy, and aliases
        query = """
            MATCH (ds:DataSource)
            OPTIONAL MATCH (r:Resource)-[:INGESTED_FROM]->(ds)
            WITH ds, count(r) AS doc_count
            RETURN ds.datasource_id AS datasource_id,
                   coalesce(ds.display_name, ds.name) AS name,
                   ds.description AS description,
                   ds.parent_datasource_id AS parent_datasource_id,
                   ds.scraper_type AS scraper_type,
                   ds.primary_alias AS primary_alias,
                   coalesce(ds.aliases, []) AS aliases,
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
                parent_datasource_id=record.get("parent_datasource_id"),
                scraper_type=record.get("scraper_type"),
                primary_alias=record.get("primary_alias"),
                aliases=record.get("aliases") or [],
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
            
            # Extract @mentions from query text if datasource_ids not provided
            # Example: "@broadcast what happened?" -> datasource_ids=["wfa_causeway_broadcasttg"]
            if not request.options or not request.options.datasource_ids:
                import re
                mention_pattern = r'@(\w+)'
                mentions = re.findall(mention_pattern, request.question)
                
                logger.debug(f"[{query_id}] Found @mentions: {mentions}")
                
                if mentions:
                    # Map mention names to datasource_ids
                    from neo4j_client import Neo4jClient
                    neo4j_client = Neo4jClient(
                        uri=settings.neo4j_uri,
                        user=settings.neo4j_user,
                        password=settings.neo4j_password
                    )
                    
                    datasource_ids = []
                    for mention in mentions:
                        logger.debug(f"[{query_id}] Looking up datasource for mention: {mention}")
                        # Match by: exact datasource_id, alias array match (primary_alias or any alias),
                        # display_name/name substring, or datasource_id substring.
                        # Alias match is ranked highest (match_exact=0) alongside exact ID match.
                        result = neo4j_client.execute_query("""
                            MATCH (ds:DataSource)
                            WHERE toLower(ds.datasource_id) = toLower($mention)
                               OR toLower(coalesce(ds.primary_alias, '')) = toLower($mention)
                               OR any(a IN coalesce(ds.aliases, []) WHERE toLower(a) = toLower($mention))
                               OR toLower(coalesce(ds.display_name, ds.name, '')) CONTAINS toLower($mention)
                               OR toLower(ds.datasource_id) CONTAINS toLower($mention)
                            RETURN ds.datasource_id AS datasource_id,
                              CASE
                                WHEN toLower(ds.datasource_id) = toLower($mention) THEN 0
                                WHEN toLower(coalesce(ds.primary_alias, '')) = toLower($mention) THEN 0
                                WHEN any(a IN coalesce(ds.aliases, []) WHERE toLower(a) = toLower($mention)) THEN 0
                                ELSE 1
                              END AS match_exact,
                              CASE WHEN ds.parent_datasource_id IS NULL THEN 0 ELSE 1 END AS is_child,
                              size(ds.datasource_id) AS id_len
                            ORDER BY match_exact, is_child, id_len, ds.datasource_id
                            LIMIT 1
                        """, parameters={"mention": mention})

                        logger.debug(f"[{query_id}] Query result for '{mention}': {result}")

                        if result and len(result) > 0:
                            matched_id = result[0]["datasource_id"]
                            datasource_ids.append(matched_id)

                            # Expand: also include any child datasources so that
                            # @wba includes all WBA Extranet communities,
                            # @nextgen includes its workgroups, etc.
                            children = neo4j_client.execute_query("""
                                MATCH (child:DataSource {parent_datasource_id: $parent_id})
                                RETURN child.datasource_id AS datasource_id
                            """, parameters={"parent_id": matched_id})
                            for child in (children or []):
                                child_id = child.get("datasource_id")
                                if child_id and child_id not in datasource_ids:
                                    datasource_ids.append(child_id)
                    
                    if datasource_ids:
                        logger.info(f"[{query_id}] Extracted datasource_ids from @mentions: {datasource_ids}")
                        # Create or update options with datasource_ids
                        if not request.options:
                            from src.models.request import QueryOptions
                            request.options = QueryOptions()
                        request.options.datasource_ids = datasource_ids
                        
                        # Remove @mentions from question text
                        clean_question = re.sub(mention_pattern, '', request.question).strip()
                        request.question = clean_question
                        logger.info(f"[{query_id}] Cleaned question: {clean_question[:100]}...")
                    else:
                        logger.debug(f"[{query_id}] No matching datasources found for mentions: {mentions}")

            # Plain-text datasource aliases — activates when the query contains a
            # well-known source name without an @mention and no explicit filter is set.
            # Uses the same prefix-expansion as @mention resolution so "causeway"
            # expands to all wfa_causeway_* child datasources automatically.
            # Longer/more-specific aliases MUST come before shorter ones.
            # Patterns containing "workgroup", "programme", or a programme name
            # after the org prefix are safe to filter — "Compare WBA and WFA" is not.
            _TEXT_DATASOURCE_ALIASES = {
                "wfa causeway":       "wfa_causeway",
                "causeway":           "wfa_causeway",
                "wba extranet":       "wba_extranet",
                "extranet":           "wba_extranet",
                "wba workgroup":      "wba_extranet",
                "wba programme":      "wba_extranet",
                "wba program":        "wba_extranet",
                "wba ai/ml":          "wba_extranet",
                "wba ai ml":          "wba_extranet",
                "wba pqc":            "wba_extranet",
                "wba iot":            "wba_extranet",
                "wba openroaming":    "wba_extranet",
                "wba open roaming":   "wba_extranet",
                "wba next gen":       "wba_extranet",
                "wba identity":       "wba_extranet",
            }
            if not (request.options and request.options.datasource_ids):
                question_lower = request.question.lower()
                for alias, prefix in _TEXT_DATASOURCE_ALIASES.items():
                    if alias in question_lower:
                        from neo4j_client import Neo4jClient as _Neo4jClient
                        _nc = _Neo4jClient(
                            uri=settings.neo4j_uri,
                            user=settings.neo4j_user,
                            password=settings.neo4j_password,
                        )
                        _rows = _nc.execute_query(
                            "MATCH (ds:DataSource) WHERE ds.datasource_id STARTS WITH $prefix "
                            "RETURN ds.datasource_id AS datasource_id",
                            parameters={"prefix": prefix},
                        )
                        _ids = [r["datasource_id"] for r in (_rows or []) if r.get("datasource_id")]
                        if _ids:
                            if not request.options:
                                from src.models.request import QueryOptions
                                request.options = QueryOptions()
                            request.options.datasource_ids = _ids
                            logger.info(
                                f"[{query_id}] Text-alias '{alias}' → {len(_ids)} datasource(s): {_ids[:5]}"
                            )
                        break

            # Determine which pipeline to use. Source of truth (in priority order):
            #   1. request.options.pipeline_override (explicit per-request)
            #   2. settings.oracle_pipeline_mode ("auto" → fast / "baseline" → baseline)
            #   3. settings.fast_pipeline_enabled (kill switch)
            options = request.options
            pipeline_override = getattr(options, 'pipeline_override', None) if options else None
            use_fast_pipeline = should_use_fast_pipeline(
                str(request.user_id) if request.user_id else None,
                pipeline_override=pipeline_override,
            )
            pipeline_name = "fast" if use_fast_pipeline else "baseline"

            span.set_attribute("oracle.pipeline", pipeline_name)
            span.set_attribute("oracle.pipeline_mode", settings.oracle_pipeline_mode)
            if pipeline_override:
                span.set_attribute("oracle.pipeline_override_used", True)
                span.set_attribute("oracle.pipeline_override_value", pipeline_override)

            logger.info(
                f"[{query_id}] Using {pipeline_name} pipeline "
                f"({'override' if pipeline_override else 'mode=' + settings.oracle_pipeline_mode})"
            )
            
            # Select engine
            if use_fast_pipeline:
                engine = fast_engine
                
                # Try fast engine with fallback to baseline
                try:
                    response = await engine.query(request, user, span, query_id)

                    # Set pipeline field to indicate fast pipeline was used
                    response.pipeline = "fast"

                    # Show "Uploaded by <email>" in place of "User Upload"
                    _enrich_user_upload_sources(response.documents)
                    
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
                        cache_hit=response.metadata.cache_hit,
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
                                cache_hit=response.metadata.cache_hit if response.metadata else False,
                                strategies_used=response.metadata.strategies_used if response.metadata else [],
                                request_options=_build_history_request_options(request, response),
                                datasource_filter=",".join(request.options.datasource_ids) if request.options and request.options.datasource_ids else None,
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

            # Show "Uploaded by <email>" in place of "User Upload"
            _enrich_user_upload_sources(response.documents)
            
            # Record metrics
            processing_time_ms = response.metadata.processing_time_ms
            
            record_query_metrics(
                intent=response.metadata.intent.value,
                mode=response.mode,
                documents_count=len(response.documents),
                confidence_score=response.confidence_score if response.confidence_score else None,
                latency_ms=processing_time_ms,
                cache_hit=response.metadata.cache_hit,
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
                        cache_hit=response.metadata.cache_hit if response.metadata else False,
                        strategies_used=response.metadata.strategies_used if response.metadata else [],
                        request_options=_build_history_request_options(request, response),
                        datasource_filter=",".join(request.options.datasource_ids) if request.options and request.options.datasource_ids else None,
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
                    user_context=user_context_for_prompt,
                    agent_persona=request.agent_persona,
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


@router.post("/query/stream")
@require_user_context
async def query_stream(
    request: QueryRequest,
    user: Optional[dict] = Depends(get_user_context),
):
    """
    Streaming query endpoint — returns tokens as Server-Sent Events.

    The client receives a stream of `data: <token>\\n\\n` lines while the LLM
    is generating.  A final `data: [DONE]\\n\\n` event signals completion,
    followed by a `data: [META] <json>\\n\\n` event carrying the full response
    metadata (documents, citations, confidence, pipeline).

    Falls back to the non-streaming /query endpoint silently if the LLM
    client is not available.
    """
    from fastapi.responses import StreamingResponse as _StreamingResponse
    from src.services.llm_client import get_llm_client, call_llm_stream
    from src.services.conversation_store import ConversationStore
    from src.engines.fast_engine import FastEngine
    from src.engines.baseline_engine import BaselineEngine
    from src.services.cache import OracleCache

    query_id = str(uuid.uuid4())

    async def _event_stream():
        try:
            # Determine pipeline
            use_fast = should_use_fast_pipeline(
                user_id=str(request.user_id) if request.user_id else None,
                pipeline_override=getattr(request.options, 'pipeline_override', None) if request.options else None,
            )

            # Run retrieval (non-streaming) to get documents + metadata
            if use_fast:
                engine = FastEngine()
                await engine._ensure_initialized()
            else:
                engine = BaselineEngine()

            try:
                response = await engine.query(request, user=user, query_id=query_id)
            except Exception as fast_err:
                # Streaming path needs the same fast→baseline fallback as the
                # non-streaming path.  Without this, any fast-engine failure
                # (zero_docs_fallback, Cypher error, etc.) surfaces as
                # "Unable to get a response" instead of trying the baseline.
                if use_fast and settings.fast_fallback_to_baseline:
                    logger.warning(
                        f"[{query_id}] Stream: fast engine failed, falling back to baseline: {fast_err}"
                    )
                    engine = BaselineEngine()
                    use_fast = False
                    response = await engine.query(request, user=user, query_id=query_id)
                else:
                    raise

            # Show "Uploaded by <email>" in place of "User Upload"
            _enrich_user_upload_sources(response.documents)

            # Fast pipeline: answer is already fully synthesised — stream the pre-generated
            # text as word chunks rather than calling the LLM a second time.
            # Baseline: re-stream so the user sees tokens arriving live.
            if use_fast or not get_llm_client() or not response.documents:
                answer = response.answer or ""
                # Emit META first so the frontend has documents/citations before DONE fires
                meta = _build_stream_meta(response)
                meta["answer"] = answer
                yield f"data: [META] {json.dumps(meta)}\n\n"
                for chunk in _split_into_chunks(answer):
                    yield f"data: {json.dumps({'token': chunk})}\n\n"
                yield "data: [DONE]\n\n"
                return

            # Baseline: Re-generate the answer with token-by-token streaming
            # (documents already retrieved by the engine above)
            from src.prompts.answer_generator import get_answer_generator_messages
            from src.services.conversation_store import ConversationStore

            cache = await OracleCache.get_cache()
            redis_client = cache._redis_client if cache.enabled else None
            conv_store = ConversationStore(redis_client=redis_client)

            conversation_history: list[dict] = []
            if request.user_id:
                conversation_history = await conv_store.get_context(
                    str(request.user_id), max_turns=2
                )

            docs_for_prompt = [
                {
                    "title": d.title or "Untitled",
                    "summary": d.summary or "",
                    "publish_date": d.publish_date or "",
                    "url": d.url,
                    "topics": d.topics,
                    "organizations": d.organizations,
                    "datasource_id": d.datasource_id or "",
                }
                for d in response.documents[:10]
            ]

            gc_dict = None
            if response.graph_context:
                gc_dict = {
                    "central_topics": response.graph_context.central_topics,
                    "key_organizations": response.graph_context.key_organizations,
                    "temporal_patterns": response.graph_context.temporal_patterns,
                }

            messages = get_answer_generator_messages(
                request.question,
                docs_for_prompt,
                gc_dict,
                user_context=None,
                conversation_history=conversation_history or None,
                persona_lens=getattr(request.options, 'persona_lens', None) if request.options else None,
            )

            client = get_llm_client()
            if not client:
                # LLM unavailable — fall back to the pre-generated answer
                answer = response.answer or ""
                meta = _build_stream_meta(response)
                meta["answer"] = answer
                yield f"data: [META] {json.dumps(meta)}\n\n"
                for chunk in _split_into_chunks(answer):
                    yield f"data: {json.dumps({'token': chunk})}\n\n"
                yield "data: [DONE]\n\n"
                return

            full_answer = []
            async for token in call_llm_stream(
                client, messages,
                max_tokens=settings.max_answer_tokens,
                temperature=0.3,
            ):
                full_answer.append(token)
                yield f"data: {json.dumps({'token': token})}\n\n"

            # Save the streaming turn to conversation store
            complete_answer = "".join(full_answer)
            if complete_answer and request.user_id:
                await conv_store.append_turn(
                    str(request.user_id), request.question, complete_answer
                )

            # Emit META before DONE so the frontend receives documents/citations/confidence
            # before the generator closes on [DONE]
            meta = _build_stream_meta(response)
            meta["answer"] = complete_answer
            yield f"data: [META] {json.dumps(meta)}\n\n"
            yield "data: [DONE]\n\n"

        except Exception as exc:
            logger.error(f"[{query_id}] Streaming query failed: {exc}")
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"
            yield "data: [DONE]\n\n"

    return _StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


def _split_into_chunks(text: str, size: int = 50) -> list[str]:
    """Split text into word-boundary chunks for non-streaming fallback.

    Preserves newlines so markdown list/paragraph structure survives chunking.
    """
    import re
    # Split by whitespace runs but keep the separators so we can reconstruct
    tokens = re.split(r'(\s+)', text)
    chunks: list[str] = []
    current: list[str] = []
    word_count = 0
    for token in tokens:
        current.append(token)
        if token and not token.isspace():
            word_count += 1
        if word_count >= size:
            chunks.append("".join(current))
            current = []
            word_count = 0
    if current:
        chunks.append("".join(current))
    return chunks or [text]


def _build_stream_meta(response) -> dict:
    """Serialise the key metadata fields for the [META] SSE event."""
    meta = response.metadata
    return {
        "query_id": response.query_id,
        "pipeline": response.pipeline if hasattr(response, "pipeline") else None,
        "confidence_score": response.confidence_score,
        "documents": [
            {
                "url": d.url,
                "title": d.title,
                "publish_date": d.publish_date,
                "summary": d.summary,
                "topics": d.topics or [],
                "organizations": d.organizations or [],
                "source": d.source,
                "datasource_id": d.datasource_id,
                "relevance_score": d.relevance_score,
                "match_reasons": d.match_reasons or [],
            }
            for d in (response.documents or [])
        ],
        "citations": [
            {"index": c.index, "document_url": c.document_url, "title": c.title}
            for c in (response.citations or [])
        ],
        # Metadata for the debug/admin tab
        "metadata": {
            "intent": meta.intent.value if meta and meta.intent else None,
            "intent_confidence": meta.intent_confidence if meta else None,
            "strategies_used": meta.strategies_used if meta else [],
            "total_candidates": meta.total_candidates if meta else None,
            "processing_time_ms": meta.processing_time_ms if meta else None,
            "cache_hit": meta.cache_hit if meta else False,
            "llm_tokens_used": meta.llm_tokens_used if meta else None,
        } if meta else None,
        "personalization_applied": response.personalization_applied if hasattr(response, "personalization_applied") else False,
    }


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


@router.post("/conversation/clear")
@require_user_context
async def clear_conversation(
    user: Optional[dict] = Depends(get_user_context),
) -> dict:
    """Wipe the caller's server-side conversation memory.

    The chat UI calls this when the user clicks "New chat" so the next query
    starts with a clean slate — without this, the Redis-backed memory
    survives until its 2-hour TTL expires and bleeds context into what the
    user perceives as a fresh conversation.
    """
    from src.services.conversation_store import ConversationStore
    from src.services.cache import OracleCache

    user_id = user.get("user_id") if user else None
    if not user_id:
        return {"status": "skipped", "reason": "no user context"}

    cache = await OracleCache.get_cache()
    redis_client = cache._redis_client if cache.enabled else None
    conv_store = ConversationStore(redis_client=redis_client)
    await conv_store.clear(str(user_id))
    logger.info(f"Cleared conversation memory for user={user_id}")
    return {"status": "cleared", "user_id": str(user_id)}


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
