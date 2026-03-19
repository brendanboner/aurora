"""Fast answer engine using deterministic routing and Cypher templates.

Part 1 of 2: Core engine and routing logic.
"""

import logging
import time
import hashlib
import json
import uuid
from dataclasses import asdict, is_dataclass
from typing import Optional, Dict, List, Any
from datetime import datetime
from opentelemetry import trace

from src.models.request import QueryRequest, QueryMode, PersonalizeMode
from src.models.response import QueryResponse, QueryIntent, Document, Citation
from src.models.route_plan import RoutePlan, RouteResult, RouteId, DetailLevel
from src.services.local_router import LocalRouter
from src.services.query_template_registry import QueryTemplateRegistry
from src.services.fast_cache import FastCache, normalize_query
from src.services.cache import OracleCache
from src.services.keyword_retriever import get_repo
from src.services.personalization import decide_personalization, get_user_preferences
from src.services.llm_client import get_llm_client, call_llm
from src.services.rollup_generator import RollupGenerator
from src.services.topic_manager import initialize_topic_manager, get_topic_manager
from src.prompts.answer_generator import get_answer_generator_messages
from src.settings import settings

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


class FastEngine:
    """
    Fast answer engine using deterministic routing and Cypher templates.
    
    Pipeline:
    1. Parse/Route: LocalRouter -> LLM fallback (low confidence)
    2. Retrieve: Execute Cypher template from registry
    3. Optional Deep Dive: Fetch snippets if needed
    4. Compose Answer: Template-based or light LLM synthesis
    5. Cache: Multi-layer caching (plan, result, answer)
    
    Designed for 2x+ latency improvement over baseline for recap queries.
    """
    
    def __init__(self):
        """Initialize the fast engine."""
        self.local_router = LocalRouter()
        self.template_registry = QueryTemplateRegistry()
        self.fast_cache: Optional[FastCache] = None
        self.rollup_generator = RollupGenerator()
        
        # Initialize TopicManager with Neo4j client
        repo = get_repo()
        if not get_topic_manager():
            try:
                initialize_topic_manager(
                    neo4j_client=repo.client,
                    refresh_interval_hours=1,
                    auto_create_threshold=10
                )
                logger.info("Initialized TopicManager with Neo4j client")
            except Exception as e:
                logger.error(f"Failed to initialize TopicManager: {e}")
        
        # Will initialize in query() on first call
        self._initialized = False
        
        logger.info("Initialized FastEngine")
    
    async def _ensure_initialized(self):
        """Lazy initialization of cache (needs async context)."""
        if self._initialized:
            return
        
        # Get Redis client from OracleCache
        oracle_cache = await OracleCache.get_cache()
        redis_client = oracle_cache._redis_client if oracle_cache.enabled else None
        
        self.fast_cache = FastCache(redis_client=redis_client)
        self._initialized = True
    
    def get_name(self) -> str:
        """Get engine name."""
        return "fast"

    def _get_max_documents(self, request: QueryRequest) -> int:
        options = request.options
        requested = getattr(options, "max_documents", settings.default_max_documents) if options else settings.default_max_documents
        return max(1, min(requested, settings.default_max_documents))

    def _build_simple_summary(self, documents: List[Document]) -> tuple[str, List[Citation]]:
        """Build a deterministic fallback answer when LLM synthesis is unavailable or empty."""
        answer_parts = [f"Found {len(documents)} relevant items:"]
        citations = []

        for idx, doc in enumerate(documents[:5], 1):
            title = doc.title or "Untitled"
            answer_parts.append(f"\n[{idx}] {title}")
            if doc.summary:
                answer_parts.append(f"    {doc.summary[:150]}...")

            citations.append(Citation(
                index=idx,
                document_url=doc.url,
                title=doc.title,
                excerpt=doc.summary[:200] + "..." if doc.summary and len(doc.summary) > 200 else doc.summary
            ))

        return "".join(answer_parts), citations

    def _compose_recent_content_brief(
        self,
        route_result: RouteResult,
        request: QueryRequest,
    ) -> tuple[str, List[Document], List[Citation]]:
        """Build a fast, chat-like recent-content summary without an LLM round-trip."""
        documents = self._nodes_to_documents(
            route_result.nodes,
            max_documents=self._get_max_documents(request),
        )
        if not documents:
            return (
                "I couldn't find any recent reference documents for that query.",
                [],
                [],
            )

        citations = []
        bullets = []
        for idx, doc in enumerate(documents[:5], 1):
            source = doc.source or doc.datasource_id or "Unknown source"
            date_label = doc.publish_date or "Unknown date"
            bullets.append(f"- [{idx}] **{doc.title or 'Untitled'}** — {source} ({date_label})")
            citations.append(Citation(
                index=idx,
                document_url=doc.url,
                title=doc.title,
                excerpt=doc.summary[:200] + "..." if doc.summary and len(doc.summary) > 200 else doc.summary,
            ))

        answer = "Here are the most recent reference documents I found:\n\n" + "\n".join(bullets)
        return answer, documents, citations

    def _should_retry_recent_content_without_topics(self, plan: RoutePlan, params: Dict[str, Any]) -> bool:
        """Allow broad recency queries to fall back when generic topics over-constrain retrieval."""
        route_id = self._get_route_id_str(plan)
        if route_id != RouteId.RECENT_CONTENT.value:
            return False

        topics = [str(topic).strip().lower() for topic in (params.get("topics") or []) if str(topic).strip()]
        if not topics:
            return False

        generic_topics = {
            "wifi",
            "wi-fi",
            "wireless",
            "802.11",
            "wireless lan",
        }
        return all(topic in generic_topics for topic in topics)

    def _build_temporal_patterns(self, plan: RoutePlan, route_result: RouteResult) -> Optional[str]:
        if plan.route_id != RouteId.RECENT_CONTENT or not route_result.nodes:
            return None

        requested_days = plan.relative_days or 14
        fallback_nodes = [
            node for node in route_result.nodes
            if int(node.get("time_window_used") or requested_days) > requested_days
        ]
        latest_node = None
        latest_date = None
        for node in route_result.nodes:
            raw_date = node.get("last_content_date")
            if not raw_date:
                continue
            try:
                parsed = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))
            except ValueError:
                continue
            if latest_date is None or parsed > latest_date:
                latest_date = parsed
                latest_node = node

        if latest_node is None or latest_date is None:
            return None

        latest_label = latest_node.get("workgroup_name") or "the knowledge graph"
        latest_text = latest_date.strftime("%B %d, %Y")
        if fallback_nodes:
            expanded_days = max(int(node.get("time_window_used") or requested_days) for node in fallback_nodes)
            return (
                f"No matching content was found in the initial {requested_days}-day window. "
                f"The query expanded to the last {expanded_days} days. "
                f"The latest known discussion was on {latest_text} in {latest_label}."
            )

        return (
            f"The newest relevant discussion in the retrieved results is from {latest_text} in {latest_label}. "
            f"Prioritize that item first."
        )
    
    def get_capabilities(self) -> Dict[str, Any]:
        """Get fast engine capabilities."""
        return {
            "name": "fast",
            "description": "Fast retrieval using deterministic routing and Cypher templates",
            "features": [
                "local_routing",
                "cypher_templates",
                "rollup_summaries",
                "multi_layer_caching",
                "optional_deep_dive",
                "fallback_to_baseline"
            ],
            "supported_routes": [route.value for route in RouteId],
            "cache_layers": ["plan", "result", "answer"],
            "template_version": settings.fast_template_version,
        }
    
    async def query(
        self,
        request: QueryRequest,
        user: Optional[dict] = None,
        span = None,
        query_id: Optional[str] = None
    ) -> QueryResponse:
        """
        Execute the fast query pipeline.
        
        Args:
            request: Query request
            user: User context from auth middleware
            span: OpenTelemetry span
            query_id: Optional query ID for tracking
            
        Returns:
            QueryResponse with answer and metadata
        """
        await self._ensure_initialized()
        assert self.fast_cache is not None, "FastCache should be initialized"
        
        start_time = time.time()
        
        # Use provided query ID or generate new one
        if not query_id:
            query_id = str(uuid.uuid4())
        
        # Create span if not provided
        if span is None:
            span = tracer.start_span("fast_engine.query")
        
        span.set_attribute("engine.name", "fast")
        span.set_attribute("oracle.query_id", str(query_id))
        span.set_attribute("oracle.question", request.question[:100])
        span.set_attribute("oracle.mode", request.mode.value)
        
        logger.info(
            f"[{query_id}] Fast pipeline: question='{request.question[:80]}...' "
            f"mode={request.mode.value} user={request.user_id}"
        )
        
        try:
            # Extract options with defaults
            options = request.options
            personalize_mode = getattr(options, 'personalize', PersonalizeMode.AUTO) if options else PersonalizeMode.AUTO
            
            # Extract datasource_ids (workgroups) from options if provided
            datasource_ids = getattr(options, 'datasource_ids', None) if options else None
            if datasource_ids:
                logger.info(f"[{query_id}] Using datasource_ids filter: {datasource_ids}")
            else:
                logger.debug(f"[{query_id}] No datasource_ids filter provided")
            
            # Decide personalization and capture user context for answer synthesis.
            personalization_enabled = False
            personalization_reason = None
            personalization_prompt_context = None
            if request.user_id and personalize_mode != PersonalizeMode.OFF:
                try:
                    personalization_decision = await decide_personalization(
                        mode=personalize_mode,
                        user_id=str(request.user_id),
                        question=request.question,
                        intent=QueryIntent.TOPIC_DISCOVERY,  # Default intent for fast engine
                        parsed_topics=[],
                        parsed_orgs=[],
                        parsed_people=[]
                    )
                    personalization_enabled = personalization_decision.should_personalize
                    personalization_reason = personalization_decision.reason
                    if personalization_decision.user_context:
                        personalization_prompt_context = personalization_decision.user_context.to_prompt_section()
                    
                    if personalization_enabled:
                        span.set_attribute("oracle.personalized", True)
                        logger.info(f"[{query_id}] Personalization enabled: {personalization_decision.reason}")
                except Exception as e:
                    logger.warning(f"[{query_id}] Personalization decision failed: {e}")
                    personalization_enabled = False
                    personalization_reason = None
            
            # Normalize query for caching
            normalized_query = normalize_query(request.question)
            
            # Phase 1: Routing (with plan cache)
            plan, routing_time_ms, route_cache_hit = await self._route_query(
                question=request.question,
                normalized_query=normalized_query,
                user_id=request.user_id,
                datasource_ids=datasource_ids,
                span=span
            )
            
            if not plan:
                # Routing failed - should fallback to baseline
                logger.warning(f"[{query_id}] Fast routing failed, fallback needed")
                raise Exception("Fast routing failed - no route plan generated")
            
            # Handle route_id that might be enum or string (after cache deserialization)
            route_id_str = plan.route_id.value if hasattr(plan.route_id, 'value') else plan.route_id
            span.set_attribute("fast.route_id", route_id_str)
            span.set_attribute("fast.confidence", plan.confidence)
            span.set_attribute("fast.routing_method", plan.routing_method)
            
            # Check confidence threshold - if too low, use LLM fallback
            if plan.confidence < settings.fast_router_confidence_threshold:
                if settings.fast_router_llm_fallback_enabled:
                    logger.info(
                        f"[{query_id}] Local router confidence too low ({plan.confidence:.2f}), "
                        f"falling back to baseline LLM routing"
                    )
                    raise Exception(f"Low confidence routing: {plan.confidence:.2f}")
                else:
                    logger.warning(
                        f"[{query_id}] Low confidence ({plan.confidence:.2f}) but LLM fallback disabled, "
                        f"proceeding with local route"
                    )
            
            # Phase 2: Retrieve from Neo4j (with result cache)
            route_result, retrieval_time_ms, result_cache_hit = await self._retrieve_data(
                plan=plan,
                span=span
            )
            
            span.set_attribute("fast.nodes_retrieved", route_result.node_count)
            span.set_attribute("fast.cache_hit_result", route_result.cache_hit)
            span.set_attribute("fast.has_rollup", route_result.rollup is not None)
            
            # Phase 3: Optional Deep Dive
            deep_dive_result = None
            deep_dive_time_ms = 0
            
            if plan.deep_dive and settings.fast_deep_dive_enabled:
                deep_dive_result, deep_dive_time_ms = await self._deep_dive_retrieval(
                    plan=plan,
                    route_result=route_result,
                    span=span
                )
                
                span.set_attribute("fast.deep_dive_snippets", len(deep_dive_result.snippets) if deep_dive_result else 0)
            
            # Phase 4: Compose Answer (only in ANSWER mode, with answer cache)
            answer = ""
            citations = []
            answer_time_ms = 0
            answer_cache_hit = False
            cache_bypass_reason = None
            
            if request.mode == QueryMode.ANSWER:
                skip_answer_cache = personalization_enabled and not self._can_cache_personalized_answer(plan)
                if skip_answer_cache:
                    cache_bypass_reason = personalization_reason or "personalization_enabled"

                answer, documents, citations, answer_time_ms, answer_cache_hit, compose_cache_bypass_reason = await self._compose_answer(
                    plan=plan,
                    route_result=route_result,
                    deep_dive_result=deep_dive_result,
                    request=request,
                    span=span,
                    user_context=personalization_prompt_context,
                    skip_cache=skip_answer_cache,
                    skip_cache_reason=cache_bypass_reason,
                    cache_scope=self._build_answer_cache_scope(personalization_prompt_context),
                )
                cache_bypass_reason = compose_cache_bypass_reason
            else:
                # In retrieval mode, just convert nodes to documents without LLM synthesis
                documents = self._nodes_to_documents(
                    route_result.nodes,
                    max_documents=self._get_max_documents(request),
                )
            
            # Build response
            processing_time_ms = int((time.time() - start_time) * 1000)
            
            # Build metadata object
            from src.models.response import RetrievalMetadata
            metadata = RetrievalMetadata(
                intent=self._map_route_to_intent(plan.route_id),
                intent_confidence=plan.confidence,
                strategies_used=[self._get_route_id_str(plan)],
                total_candidates=len(documents),
                processing_time_ms=processing_time_ms,
                llm_tokens_used=None,
                cache_hit=route_cache_hit or result_cache_hit or answer_cache_hit,
                route_cache_hit=route_cache_hit,
                result_cache_hit=result_cache_hit,
                answer_cache_hit=answer_cache_hit,
                cache_bypass_reason=cache_bypass_reason,
            )
            
            response = QueryResponse(
                query_id=str(query_id),
                answer=answer,
                mode="answer" if request.mode == QueryMode.ANSWER else "retrieval",
                documents=documents,
                citations=citations,
                metadata=metadata,
                suggestions=[],
                confidence_score=None,
                personalization_applied=personalization_enabled
            )
            
            span.set_attribute("oracle.processing_time_ms", processing_time_ms)
            
            logger.info(
                f"[{query_id}] Fast pipeline complete: {processing_time_ms}ms "
                f"(route={routing_time_ms}ms, retrieve={retrieval_time_ms}ms, "
                f"answer={answer_time_ms}ms), {len(documents)} docs, "
                f"route={self._get_route_id_str(plan)}, "
                f"cache(route={route_cache_hit}, result={result_cache_hit}, "
                f"answer={answer_cache_hit}, bypass={cache_bypass_reason or 'none'})"
            )
            
            return response
            
        except Exception as e:
            # Log error and re-raise for fallback handling
            span.set_attribute("oracle.fast_error", str(e))
            span.set_attribute("oracle.fast_fallback_triggered", True)
            
            logger.error(
                f"[{query_id}] Fast engine error: {e}",
                exc_info=True
            )
            raise
    
    def _map_route_to_intent(self, route_id: RouteId) -> QueryIntent:
        """Map route ID to query intent for response."""
        intent_map = {
            RouteId.WORKGROUP_WEEKLY_RECAP: QueryIntent.ENTITY_FOCUSED,
            RouteId.WORKGROUP_DAILY_RECAP: QueryIntent.ENTITY_FOCUSED,
            RouteId.WORKGROUP_RECENT_UPDATES: QueryIntent.TOPIC_DISCOVERY,
            RouteId.DECISIONS_IN_RANGE: QueryIntent.ENTITY_FOCUSED,
            RouteId.DECISIONS_BY_WORKGROUP: QueryIntent.ENTITY_FOCUSED,
            RouteId.ACTION_ITEMS_OPEN: QueryIntent.ENTITY_FOCUSED,
            RouteId.ACTION_ITEMS_BY_WORKGROUP: QueryIntent.ENTITY_FOCUSED,
            RouteId.TOPICS_TREND: QueryIntent.TREND_ANALYSIS,
            RouteId.TOPICS_BY_WORKGROUP: QueryIntent.TREND_ANALYSIS,
            RouteId.WHO_SAID_WHAT: QueryIntent.RELATIONSHIP_QUERY,
            RouteId.MEETING_BY_TITLE: QueryIntent.ENTITY_FOCUSED,
            RouteId.GENERIC_SEARCH: QueryIntent.TOPIC_DISCOVERY,
        }
        
        return intent_map.get(route_id, QueryIntent.TOPIC_DISCOVERY)
    
    def _get_route_id_str(self, plan: RoutePlan) -> str:
        """Safely get route_id as string (handles both enum and string from cache)."""
        return plan.route_id.value if hasattr(plan.route_id, 'value') else plan.route_id
    
    async def _route_query(
        self,
        question: str,
        normalized_query: str,
        user_id: Optional[str],
        datasource_ids: Optional[list],
        span
    ) -> tuple[Optional[RoutePlan], int, bool]:
        """
        Route query to a plan (Phase 1).
        
        Args:
            datasource_ids: Optional list of datasource IDs to filter by
        
        Returns:
            Tuple of (RoutePlan, routing_time_ms)
        """
        route_start = time.time()
        
        with tracer.start_as_current_span("fast.route_query", context=trace.set_span_in_context(span)):
            # Get user preferences for intelligent entity extraction
            user_prefs = None
            if user_id:
                try:
                    user_prefs = await get_user_preferences(str(user_id))
                    logger.debug(f"User preferences: topics={len(user_prefs.topics)} orgs={len(user_prefs.organisations)}")
                except Exception as e:
                    logger.warning(f"Failed to fetch user preferences: {e}")

            user_prefs_payload = self._serialize_user_preferences(user_prefs)

            # Check plan cache first (includes datasource_ids and personalization context)
            cached_plan = await self.fast_cache.get_plan(
                normalized_query,
                user_prefs=user_prefs_payload,
                datasource_ids=datasource_ids,
            )
            
            if cached_plan:
                routing_time_ms = int((time.time() - route_start) * 1000)
                logger.info(f"Plan cache hit: route_id={self._get_route_id_str(cached_plan)}")
                return cached_plan, routing_time_ms, True
            
            # Pass datasource_ids to router
            if datasource_ids:
                logger.debug(f"Passing datasource_ids to router: {datasource_ids}")
            
            # Try local router
            plan, confidence = await self.local_router.route(question, user_id, user_prefs, datasource_ids)
            
            # Check if we should use LLM fallback
            if (not plan or confidence < settings.fast_router_confidence_threshold) and settings.fast_router_llm_fallback_enabled:
                logger.info(
                    f"Local router confidence too low ({confidence:.2f}), "
                    f"LLM fallback not yet implemented - using local result"
                )
                # TODO: Implement LLM router fallback
                # For now, use local result even if low confidence
            
            if plan:
                # Cache the plan (includes datasource_ids in cache key)
                await self.fast_cache.set_plan(
                    normalized_query,
                    plan,
                    user_prefs=user_prefs_payload,
                    datasource_ids=datasource_ids,
                )
            
            routing_time_ms = int((time.time() - route_start) * 1000)
            
            return plan, routing_time_ms, False
    
    async def _retrieve_data(
        self,
        plan: RoutePlan,
        span
    ) -> tuple[RouteResult, int, bool]:
        """
        Retrieve data using Cypher template or PostgreSQL rollups (Phase 2).
        
        Returns:
            Tuple of (RouteResult, retrieval_time_ms)
        """
        retrieval_start = time.time()
        
        with tracer.start_as_current_span("fast.retrieve_data", context=trace.set_span_in_context(span)):
            # Check result cache
            cached_result = await self.fast_cache.get_result(plan)
            
            if cached_result:
                retrieval_time_ms = int((time.time() - retrieval_start) * 1000)
                logger.info(f"Result cache hit: {cached_result.node_count} nodes")
                return cached_result, retrieval_time_ms, True
            
            # Check if this is a rollup route - query PostgreSQL instead of Neo4j
            if plan.route_id in [RouteId.WORKGROUP_DAILY_RECAP, RouteId.WORKGROUP_WEEKLY_RECAP]:
                route_result, retrieval_time_ms = await self._retrieve_rollup_data(plan, retrieval_start, span)
                return route_result, retrieval_time_ms, False
            
            # Standard Neo4j Cypher query
            route_result, retrieval_time_ms = await self._retrieve_neo4j_data(plan, retrieval_start, span)
            return route_result, retrieval_time_ms, False
    
    async def _retrieve_rollup_data(
        self,
        plan: RoutePlan,
        retrieval_start: float,
        span
    ) -> tuple[RouteResult, int]:
        """Retrieve data from PostgreSQL rollups for temporal workgroup queries."""
        query_start = time.time()
        
        # Determine rollup type from route
        rollup_type = "day" if plan.route_id == RouteId.WORKGROUP_DAILY_RECAP else "week"
        
        # Extract date range from plan
        # Note: start_date and end_date are already date objects per RoutePlan model
        start_date = plan.start_date
        end_date = plan.end_date
        
        # Query PostgreSQL
        logger.info(f"Querying PostgreSQL for {rollup_type} rollups: workgroups={plan.workgroups}, dates={start_date} to {end_date}")
        results = self.rollup_generator.query_rollups(
            rollup_type=rollup_type,
            workgroup_ids=plan.workgroups if plan.workgroups else None,
            start_date=start_date,
            end_date=end_date,
            limit=10
        )
        
        query_time_ms = int((time.time() - query_start) * 1000)
        
        # Extract rollup if we got one
        rollup = None
        if results:
            first = results[0]
            rollup = {
                "id": first["rollup_id"],
                "summary": first["rollup_summary"],
                "key_events": first.get("key_events", []),
                "key_decisions": first.get("key_decisions", []),
                "top_topics": first.get("top_topics", []),
                "links": first.get("links", []),
                "start": first.get("rollup_start"),
                "end": first.get("rollup_end"),
            }
        
        # Build RouteResult
        route_result = RouteResult(
            route_id=plan.route_id,
            nodes=results,
            rollup=rollup,
            execution_time_ms=query_time_ms,
            node_count=len(results),
            cache_hit=False
        )
        
        # Cache the result
        await self.fast_cache.set_result(plan, route_result)
        
        retrieval_time_ms = int((time.time() - retrieval_start) * 1000)
        logger.info(f"PostgreSQL rollup query: {len(results)} results in {query_time_ms}ms")
        
        return route_result, retrieval_time_ms
    
    async def _retrieve_neo4j_data(
        self,
        plan: RoutePlan,
        retrieval_start: float,
        span
    ) -> tuple[RouteResult, int]:
        """Retrieve data from Neo4j using Cypher templates."""
        # Get template for route
        template = self.template_registry.get_template(plan.route_id)
        
        if not template:
            raise Exception(f"No template found for route: {self._get_route_id_str(plan)}")
        
        # Build Cypher parameters
        params = template.build_params(plan)
        
        logger.debug(
            f"Executing Cypher template: route={self._get_route_id_str(plan)} "
            f"params={json.dumps(params, default=str)[:200]}"
        )
        
        # Execute Cypher query
        repo = get_repo()
        
        query_start = time.time()
        results = repo.client.execute_query(
            template.cypher,
            params
        )
        query_time_ms = int((time.time() - query_start) * 1000)
        
        # Post-process results
        processed_results = template.execute_post_process(results)
        
        # Fallback: If no results and query had date filters, retry without dates
        if len(processed_results) == 0 and (params.get('start_date') or params.get('end_date') or params.get('relative_days')):
            logger.info(
                f"Zero results with date filters, retrying without temporal constraints "
                f"(route={self._get_route_id_str(plan)})"
            )
            
            # Remove date filters for fallback
            fallback_params = params.copy()
            fallback_params['start_date'] = None
            fallback_params['end_date'] = None
            fallback_params['relative_days'] = None
            
            fallback_start = time.time()
            fallback_results = repo.client.execute_query(
                template.cypher,
                fallback_params
            )
            fallback_time_ms = int((time.time() - fallback_start) * 1000)
            processed_results = template.execute_post_process(fallback_results)
            
            if len(processed_results) > 0:
                logger.info(f"Fallback succeeded: retrieved {len(processed_results)} undated documents")
                query_time_ms += fallback_time_ms
            else:
                logger.warning("Fallback also returned zero results")
        
        # Cross-datasource fallback: If zero results and workgroups filter was used, retry without workgroups
        if len(processed_results) == 0 and params.get('workgroups') and len(params['workgroups']) > 0:
            logger.info(
                f"Zero results with workgroups filter, expanding to all datasources "
                f"(route={self._get_route_id_str(plan)}, workgroups={params['workgroups']})"
            )
            
            # Remove workgroups filter for cross-datasource fallback
            fallback_params = params.copy()
            fallback_params['workgroups'] = []
            
            fallback_start = time.time()
            fallback_results = repo.client.execute_query(
                template.cypher,
                fallback_params
            )
            fallback_time_ms = int((time.time() - fallback_start) * 1000)
            processed_results = template.execute_post_process(fallback_results)
            
            if len(processed_results) > 0:
                logger.info(f"Cross-datasource fallback succeeded: retrieved {len(processed_results)} documents")
                query_time_ms += fallback_time_ms
            else:
                logger.warning("Cross-datasource fallback also returned zero results")

        if len(processed_results) == 0 and self._should_retry_recent_content_without_topics(plan, params):
            logger.info(
                f"Zero results for broad recent-content topic filter, retrying without topic constraints "
                f"(route={self._get_route_id_str(plan)}, topics={params.get('topics')})"
            )

            fallback_params = params.copy()
            fallback_params['topics'] = []

            fallback_start = time.time()
            fallback_results = repo.client.execute_query(
                template.cypher,
                fallback_params
            )
            fallback_time_ms = int((time.time() - fallback_start) * 1000)
            processed_results = template.execute_post_process(fallback_results)

            if len(processed_results) > 0:
                logger.info(f"Broad-topic fallback succeeded: retrieved {len(processed_results)} documents")
                query_time_ms += fallback_time_ms
            else:
                logger.warning("Broad-topic fallback also returned zero results")

        # Tier-4 fallback: If still zero results, retry with GENERIC_SEARCH full-text template.
        # This catches cases where topic-node matching failed (e.g., plural vs. singular, alternate
        # phrasing) but document content or titles would match a free-text search.
        if len(processed_results) == 0:
            route_id_str = self._get_route_id_str(plan)
            raw_query = getattr(plan, 'raw_query', None) or ""
            if raw_query and route_id_str != RouteId.GENERIC_SEARCH.value:
                generic_template = self.template_registry.get_template(RouteId.GENERIC_SEARCH)
                if generic_template:
                    logger.info(
                        f"Tier-4 fallback: zero results for route={route_id_str}, "
                        f"retrying with GENERIC_SEARCH on raw_query={repr(raw_query[:80])}"
                    )
                    try:
                        # Build a minimal plan-like object for generic_search param building
                        from src.models.route_plan import RoutePlan as _RP
                        generic_plan = _RP(
                            route_id=RouteId.GENERIC_SEARCH,
                            confidence=plan.confidence,
                            detail_level=plan.detail_level,
                            params={},
                            raw_query=raw_query,
                            datasource_ids=getattr(plan, 'datasource_ids', None),
                        )
                        generic_params = generic_template.build_params(generic_plan)
                        fallback_start = time.time()
                        fallback_results = repo.client.execute_query(
                            generic_template.cypher,
                            generic_params
                        )
                        fallback_time_ms = int((time.time() - fallback_start) * 1000)
                        processed_results = generic_template.execute_post_process(fallback_results)
                        query_time_ms += fallback_time_ms
                        if len(processed_results) > 0:
                            logger.info(
                                f"Tier-4 GENERIC_SEARCH fallback succeeded: "
                                f"retrieved {len(processed_results)} documents"
                            )
                        else:
                            logger.warning("Tier-4 GENERIC_SEARCH fallback also returned zero results")
                    except Exception as gs_err:
                        logger.warning(f"Tier-4 GENERIC_SEARCH fallback failed: {gs_err}")
        
        # Check if we got a rollup (shouldn't happen for Neo4j queries now)
        rollup = None
        if processed_results and "rollup_id" in processed_results[0]:
            first = processed_results[0]
            if first.get("rollup_id"):
                rollup = {
                    "id": first["rollup_id"],
                    "summary": first.get("rollup_summary"),
                    "key_events": first.get("key_events", []),
                    "key_decisions": first.get("key_decisions", []),
                    "top_topics": first.get("top_topics", []),
                    "links": first.get("links", []),
                    "start": first.get("rollup_start"),
                    "end": first.get("rollup_end"),
                }
        
        # Build RouteResult
        route_result = RouteResult(
            route_id=plan.route_id,
            nodes=processed_results,
            rollup=rollup,
            execution_time_ms=query_time_ms,
            node_count=len(processed_results),
            cache_hit=False
        )
        
        # Cache result — only when we actually found something.
        # Never cache zero-node results: they trigger the zero_docs_fallback exception
        # and would cause the next identical request to instantly fail again from cache
        # instead of trying a fresh query (topic nodes may be added at any time).
        if len(processed_results) > 0:
            await self.fast_cache.set_result(plan, route_result)
        
        retrieval_time_ms = int((time.time() - retrieval_start) * 1000)
        
        logger.info(
            f"Retrieved {len(processed_results)} nodes in {query_time_ms}ms "
            f"(has_rollup={rollup is not None})"
        )
        
        return route_result, retrieval_time_ms
    
    async def _deep_dive_retrieval(
        self,
        plan: RoutePlan,
        route_result: RouteResult,
        span
    ):
        """
        Optional deep dive retrieval (Phase 3).
        
        Fetches document snippets for evidence if confidence is low
        or comprehensive detail is requested.
        
        Returns:
            Tuple of (DeepDiveResult, deep_dive_time_ms)
        """
        from src.models.route_plan import DeepDiveResult
        
        deep_dive_start = time.time()
        
        with tracer.start_as_current_span("fast.deep_dive", context=trace.set_span_in_context(span)):
            # TODO: Implement deep dive retrieval
            # For now, return empty result
            logger.info("Deep dive requested but not yet implemented")
            
            result = DeepDiveResult(
                snippets=[],
                total_tokens=0,
                vector_search_time_ms=0
            )
            
            deep_dive_time_ms = int((time.time() - deep_dive_start) * 1000)
            
            return result, deep_dive_time_ms
    
    async def _compose_answer(
        self,
        plan: RoutePlan,
        route_result: RouteResult,
        deep_dive_result,
        request: QueryRequest,
        span,
        user_context: Optional[str] = None,
        skip_cache: bool = False,
        skip_cache_reason: Optional[str] = None,
        cache_scope: Optional[str] = None,
    ) -> tuple[str, List[Document], List[Citation], int, bool, Optional[str]]:
        """
        Compose final answer (Phase 4).
        
        Uses template-based response for BRIEF with rollup,
        otherwise uses light LLM synthesis.
        
        Returns:
            Tuple of (answer_text, documents, citations, answer_time_ms)
        """
        answer_start = time.time()
        
        with tracer.start_as_current_span("fast.compose_answer", context=trace.set_span_in_context(span)):
            # Generate result digest for answer cache
            result_digest = hashlib.sha256(
                json.dumps(route_result.model_dump(), sort_keys=True, default=str).encode()
            ).hexdigest()
            
            # Check answer cache (skip if personalized)
            cached_answer_data = None
            if not skip_cache:
                cached_answer_data = await self.fast_cache.get_answer(plan, result_digest, scope=cache_scope)
            
            if cached_answer_data:
                answer_time_ms = int((time.time() - answer_start) * 1000)
                logger.info("Answer cache hit")
                
                return (
                    cached_answer_data["answer"],
                    [Document(**d) for d in cached_answer_data["documents"]],
                    [Citation(**c) for c in cached_answer_data["citations"]],
                    answer_time_ms,
                    True,
                    None,
                )
            
            # Compose answer based on detail level and availability
            if plan.detail_level == DetailLevel.BRIEF and route_result.rollup:
                answer, documents, citations = self._compose_from_rollup(
                    plan, route_result, request
                )
            elif plan.detail_level == DetailLevel.BRIEF and self._get_route_id_str(plan) == RouteId.RECENT_CONTENT.value:
                answer, documents, citations = self._compose_recent_content_brief(
                    route_result,
                    request,
                )
            elif self._get_route_id_str(plan) == RouteId.TOPIC_COMPARISON.value:
                comparison_answer = self._compose_standard_topic_comparison(plan, route_result)
                if comparison_answer is not None:
                    answer, documents, citations = comparison_answer
                else:
                    answer, documents, citations = await self._compose_with_llm(
                        plan, route_result, deep_dive_result, request, span, user_context=user_context
                    )
            else:
                # LLM-based synthesis
                answer, documents, citations = await self._compose_with_llm(
                    plan, route_result, deep_dive_result, request, span, user_context=user_context
                )
            
            answer_time_ms = int((time.time() - answer_start) * 1000)
            
            # Cache answer (skip if personalized)
            if not skip_cache:
                answer_data = {
                    "answer": answer,
                    "documents": [d.model_dump() for d in documents],
                    "citations": [c.model_dump() for c in citations],
                }
                await self.fast_cache.set_answer(plan, result_digest, answer_data, scope=cache_scope)
            
            return answer, documents, citations, answer_time_ms, False, skip_cache_reason

    def _can_cache_personalized_answer(self, plan: RoutePlan) -> bool:
        """Fast-engine answers are cacheable when keyed by the effective personalization scope."""
        return True

    def _compose_standard_topic_comparison(
        self,
        plan: RoutePlan,
        route_result: RouteResult,
    ) -> Optional[tuple[str, List[Document], List[Citation]]]:
        """Provide a deterministic comparison for the common Wi-Fi 7 vs Wi-Fi 6 prompt family."""
        topics = {topic.lower() for topic in (plan.topics or [])}
        has_wifi7 = any(topic in {"wi-fi 7", "wifi 7", "802.11be"} for topic in topics)
        has_wifi6 = any(topic in {"wi-fi 6", "wifi 6", "802.11ax"} for topic in topics)
        if not (has_wifi7 and has_wifi6):
            return None

        documents = self._nodes_to_documents(route_result.nodes, max_documents=4)
        citations = [
            Citation(
                index=idx,
                document_url=doc.url,
                title=doc.title,
                excerpt=(doc.summary[:200] + "...") if doc.summary and len(doc.summary) > 200 else doc.summary,
            )
            for idx, doc in enumerate(documents[:4], 1)
        ]
        answer = (
            "Wi-Fi 7 improves on Wi-Fi 6 in five headline ways: wider 320 MHz channels "
            "(vs 160 MHz), 4K-QAM for higher peak throughput, Multi-Link Operation to use "
            "multiple bands/links at once, more flexible puncturing so wide channels stay usable "
            "in noisy spectrum, and better scheduling/latency behavior for dense, demanding traffic. "
            "In practice that means more capacity, lower latency, and better multi-gig performance for "
            "AR/VR, gaming, high-density enterprise, and advanced IoT workloads.\n\n"
            "The Aurora documents retrieved here mention Wi-Fi 7 deployments, certification progress, "
            "and the broader evolution of Wi-Fi standards, but they do not contain a clean side-by-side "
            "specification table; this summary reflects the standard feature deltas between Wi-Fi 7 "
            "(802.11be) and Wi-Fi 6 (802.11ax)."
        )
        return answer, documents, citations

    def _build_answer_cache_scope(self, user_context: Optional[str]) -> Optional[str]:
        """Scope personalized answer cache entries so users don't share tailored narratives."""
        if not user_context:
            return None
        return hashlib.sha256(user_context.encode()).hexdigest()[:12]

    def _serialize_user_preferences(self, user_prefs) -> Optional[dict]:
        """Serialize preferences into a stable payload for plan cache keying."""
        if not user_prefs:
            return None

        if is_dataclass(user_prefs):
            prefs_payload = asdict(user_prefs)
        elif hasattr(user_prefs, "model_dump"):
            prefs_payload = user_prefs.model_dump()
        elif isinstance(user_prefs, dict):
            prefs_payload = dict(user_prefs)
        else:
            return None

        return {
            "topics": sorted(prefs_payload.get("topics") or []),
            "organisations": sorted(prefs_payload.get("organisations") or []),
            "people": sorted(prefs_payload.get("people") or []),
        }
    
    def _compose_from_rollup(
        self,
        plan: RoutePlan,
        route_result: RouteResult,
        request: QueryRequest
    ) -> tuple[str, List[Document], List[Citation]]:
        """
        Compose answer from rollup using templates (no LLM).
        
        Returns:
            Tuple of (answer, documents, citations)
        """
        rollup = route_result.rollup
        
        if not rollup:
            # No rollup available, use LLM path
            return "", [], []
        
        # Build answer from rollup
        answer_parts = []
        
        # Add summary
        if rollup.get("summary"):
            answer_parts.append(rollup["summary"])
        
        # Add key events
        if rollup.get("key_events"):
            events = rollup["key_events"]
            if events:
                answer_parts.append(f"\n\n**Key Events ({len(events)}):**")
                for event in events[:5]:  # Top 5
                    answer_parts.append(f"- {event}")
        
        # Add key decisions
        if rollup.get("key_decisions"):
            decisions = rollup["key_decisions"]
            if decisions:
                answer_parts.append(f"\n\n**Key Decisions ({len(decisions)}):**")
                for decision in decisions[:5]:
                    if isinstance(decision, dict):
                        answer_parts.append(f"- {decision.get('title', 'Decision')}: {decision.get('summary', '')}")
                    else:
                        answer_parts.append(f"- {decision}")
        
        # Add top topics
        if rollup.get("top_topics"):
            topics = rollup["top_topics"]
            if topics:
                answer_parts.append(f"\n\n**Top Topics:** {', '.join(topics[:10])}")
        
        answer = "\n".join(answer_parts)
        
        # Build documents from rollup links
        documents = []
        citations = []
        
        if rollup.get("links"):
            for idx, link in enumerate(rollup["links"][:10], 1):
                if isinstance(link, dict):
                    doc = Document(
                        title=link.get("title", "Document"),
                        url=link.get("url", ""),
                        relevance_score=1.0,
                        publish_date=link.get("date"),
                        source=link.get("source", "rollup")
                    )
                    documents.append(doc)
                    
                    citation = Citation(
                        index=idx,
                        document_url=doc.url,
                        title=doc.title,
                        excerpt=None
                    )
                    citations.append(citation)
        
        logger.info(f"Composed answer from rollup: {len(answer)} chars, {len(documents)} docs")
        
        return answer, documents, citations
    
    async def _compose_with_llm(
        self,
        plan: RoutePlan,
        route_result: RouteResult,
        deep_dive_result,
        request: QueryRequest,
        span,
        user_context: Optional[str] = None,
    ) -> tuple[str, List[Document], List[Citation]]:
        """
        Compose answer using LLM synthesis.
        
        Returns:
            Tuple of (answer, documents, citations)
        """
        # Convert nodes to documents
        documents = self._nodes_to_documents(
            route_result.nodes,
            max_documents=self._get_max_documents(request),
        )
        
        if not documents:
            # All retrieval tiers (including generic_search) returned nothing.
            # Raise so query.py falls back to the baseline engine, which uses
            # vector/entity search and is far more likely to find relevant content.
            raise Exception(
                f"zero_docs_fallback: no matching nodes after all retrieval tiers "
                f"(route={getattr(plan, 'route_id', 'unknown')})"
            )
        
        # Get LLM client
        client = get_llm_client()
        
        if client is None:
            answer, citations = self._build_simple_summary(documents)
            logger.info(f"Composed answer without LLM: {len(answer)} chars, {len(documents)} docs")
            return answer, documents, citations
        
        try:
            # Prepare documents for prompt (limit to 10 for context window)
            # For "which workgroups" queries, add datasource summary
            import re
            from collections import defaultdict
            is_workgroup_query = bool(re.search(r'(what|which)\s+(workgroups?|datasources?|groups?|wgs?)\s+(are|is|have|has|discussed|mentioned|talking|working)', request.question.lower()))
            
            datasource_summary = ""
            if is_workgroup_query and len(documents) > 10:
                # Group documents by datasource
                datasource_counts = defaultdict(int)
                for doc in documents:
                    ds = doc.datasource_id or "Unknown source"
                    datasource_counts[ds] += 1
                
                # Create summary
                sorted_datasources = sorted(datasource_counts.items(), key=lambda x: x[1], reverse=True)
                summary_parts = [f"**Document Distribution:** Total {len(documents)} documents from {len(datasource_counts)} datasources:"]
                for ds, count in sorted_datasources:
                    summary_parts.append(f"  - {ds}: {count} documents")
                datasource_summary = "\n".join(summary_parts) + "\n\n"
            
            docs_for_prompt = [
                {
                    "title": doc.title or "Untitled",
                    "summary": doc.summary or "No summary available",
                    "publish_date": doc.publish_date or "Unknown date",
                    "url": doc.url,
                    "topics": doc.topics,
                    "organizations": doc.organizations,
                    "datasource_id": doc.datasource_id or "Unknown source",
                }
                for doc in documents[:10]
            ]
            
            # Add datasource summary to the first doc's summary if it exists
            if datasource_summary and docs_for_prompt:
                docs_for_prompt.insert(0, {
                    "title": "📊 Distribution Summary",
                    "summary": datasource_summary.strip(),
                    "publish_date": "",
                    "url": "",
                    "topics": [],
                    "organizations": [],
                    "datasource_id": "summary",
                })
            
            # Generate answer using LLM
            graph_context = None
            temporal_patterns = self._build_temporal_patterns(plan, route_result)
            if temporal_patterns:
                graph_context = {
                    "central_topics": [],
                    "key_organizations": [],
                    "temporal_patterns": temporal_patterns,
                }

            messages = get_answer_generator_messages(
                request.question,
                docs_for_prompt,
                graph_context,
                user_context,
            )
            
            response = await call_llm(
                client=client,
                messages=messages,
                max_tokens=settings.max_answer_tokens,
                temperature=0.3
            )
            
            answer = (response.content or "").strip()
            if not answer:
                logger.warning("LLM synthesis returned empty content, falling back to deterministic summary")
                answer, citations = self._build_simple_summary(documents)
                return answer, documents, citations
            
            # Create citations from documents
            citations = []
            for idx, doc in enumerate(documents[:5], 1):
                citations.append(Citation(
                    index=idx,
                    document_url=doc.url,
                    title=doc.title,
                    excerpt=doc.summary[:200] + "..." if doc.summary and len(doc.summary) > 200 else doc.summary
                ))
            
            logger.info(f"Composed answer with LLM: {len(answer)} chars, {len(documents)} docs")
            
            return answer, documents, citations
            
        except Exception as e:
            logger.error(f"LLM synthesis failed: {e}, falling back to simple summary")
            answer, citations = self._build_simple_summary(documents)
            return answer, documents, citations
    
    def _nodes_to_documents(self, nodes: List[Dict], max_documents: Optional[int] = None) -> List[Document]:
        """
        Convert Neo4j nodes to Document objects.
        Handles both flat node structure and grouped structure (recent_documents/recent_events).
        
        Args:
            nodes: List of node dictionaries from Cypher results
            
        Returns:
            List of Document objects
        """
        documents = []
        limit = max_documents or settings.default_max_documents
        seen_keys = set()
        
        for idx, node in enumerate(nodes):
            # Check if this is a grouped result (from RECENT_CONTENT or ORGANIZATION_ACTIVITY templates)
            if "recent_documents" in node or "recent_events" in node or "recent_activity" in node or "sample_resources" in node:
                # Flatten recent_activity array (from ORGANIZATION_ACTIVITY)
                for doc_node in node.get("recent_activity", []):
                    if len(documents) >= limit:
                        return documents
                    doc_id = doc_node.get("id") or doc_node.get("url_hash") or f"doc_{len(documents)}"
                    title = doc_node.get("title") or "Untitled"
                    url = doc_node.get("url", "")
                    dedupe_key = (doc_id, url, title)
                    if dedupe_key in seen_keys:
                        continue
                    seen_keys.add(dedupe_key)
                    summary = doc_node.get("summary", "")
                    date = doc_node.get("date") or doc_node.get("publishDate") or doc_node.get("publish_date")
                    category = doc_node.get("category") or doc_node.get("type")
                    topics = doc_node.get("topics", [])
                    orgs = doc_node.get("organizations", [])
                    
                    # Organization context from parent node
                    datasource_id = node.get("datasource_id")
                    source = node.get("org_name") or (node.get("datasource_id", "").replace("_", " ").title() if node.get("datasource_id") else None)
                    
                    raw_score = doc_node.get("topic_score", 0)
                    doc = Document(
                        title=title,
                        summary=summary,
                        url=url,
                        relevance_score=min(1.0, float(raw_score) / 60.0) if raw_score else 0.0,
                        publish_date=date,
                        source=source,
                        datasource_id=datasource_id,
                        category=category,
                        topics=topics if isinstance(topics, list) else [],
                        organizations=orgs if isinstance(orgs, list) else []
                    )
                    documents.append(doc)
                
                # Flatten recent_documents array
                for doc_node in node.get("recent_documents", []):
                    if len(documents) >= limit:
                        return documents
                    doc_id = doc_node.get("id") or doc_node.get("url_hash") or f"doc_{len(documents)}"
                    title = doc_node.get("title") or "Untitled"
                    url = doc_node.get("url", "")
                    dedupe_key = (doc_id, url, title)
                    if dedupe_key in seen_keys:
                        continue
                    seen_keys.add(dedupe_key)
                    summary = doc_node.get("summary", "")
                    date = doc_node.get("publishDate") or doc_node.get("publish_date")
                    category = doc_node.get("category") or doc_node.get("type")
                    
                    # Grouped results include workgroup context
                    datasource_id = node.get("workgroup_id")
                    source = node.get("workgroup_name")
                    
                    doc = Document(
                        title=title,
                        summary=summary,
                        url=url,
                        relevance_score=1.0,
                        publish_date=date,
                        source=source,
                        datasource_id=datasource_id,
                        category=category
                    )
                    documents.append(doc)
                
                # Flatten recent_events array
                for event_node in node.get("recent_events", []):
                    if len(documents) >= limit:
                        return documents
                    event_id = event_node.get("id") or event_node.get("event_id") or f"event_{len(documents)}"
                    title = event_node.get("title") or event_node.get("name") or "Untitled Event"
                    url = event_node.get("url", "")
                    dedupe_key = (event_id, url, title)
                    if dedupe_key in seen_keys:
                        continue
                    seen_keys.add(dedupe_key)
                    summary = event_node.get("summary") or event_node.get("description", "")
                    date = event_node.get("eventDate") or event_node.get("start_time") or event_node.get("startTime")
                    category = event_node.get("category") or event_node.get("event_type") or "event"
                    
                    datasource_id = node.get("workgroup_id")
                    source = node.get("workgroup_name")
                    
                    doc = Document(
                        title=title,
                        summary=summary,
                        url=url,
                        relevance_score=1.0,
                        publish_date=date,
                        source=source,
                        datasource_id=datasource_id,
                        category=category
                    )
                    documents.append(doc)

                # Flatten sample_resources array (from TOPIC_COMPARISON)
                for doc_node in node.get("sample_resources", []):
                    if len(documents) >= limit:
                        return documents
                    doc_id = doc_node.get("id") or doc_node.get("url_hash") or f"doc_{len(documents)}"
                    title = doc_node.get("title") or "Untitled"
                    url = doc_node.get("url", "")
                    dedupe_key = (doc_id, url, title)
                    if dedupe_key in seen_keys:
                        continue
                    seen_keys.add(dedupe_key)
                    summary = doc_node.get("summary", "")
                    date = doc_node.get("date") or doc_node.get("publishDate") or doc_node.get("publish_date")

                    doc = Document(
                        title=title,
                        summary=summary,
                        url=url,
                        relevance_score=1.0,
                        publish_date=date,
                        source=node.get("topic_name"),
                        category=node.get("classification") or "comparison"
                    )
                    documents.append(doc)
            else:
                # Regular flat node structure
                if len(documents) >= limit:
                    return documents
                doc_id = node.get("id") or node.get("url_hash") or node.get("event_id") or f"node_{idx}"
                title = node.get("title") or node.get("name") or "Untitled"
                url = node.get("url", "")
                dedupe_key = (doc_id, url, title)
                if dedupe_key in seen_keys:
                    continue
                seen_keys.add(dedupe_key)
                summary = node.get("summary") or node.get("description", "")
                date = node.get("date") or node.get("start_time") or node.get("startTime") or node.get("publish_date")
                
                # Extract real metadata from Neo4j results
                datasource_id = node.get("datasource_id")
                category = node.get("category") or node.get("event_type") or node.get("type")
                topics = node.get("topics", []) or node.get("all_topic_names", [])
                organizations = node.get("organizations", []) or node.get("org_names", [])
                relevance = node.get("relevance_score", 1.0)
                
                # Build source name from datasource_id or fall back to category
                source = None
                if datasource_id:
                    # Convert datasource_id to readable name (e.g., "wfa_causeway" -> "WFA Causeway")
                    source = datasource_id.replace("_", " ").title()
                elif category:
                    source = category.replace("_", " ").title()
                
                doc = Document(
                    title=title,
                    summary=summary,
                    url=url,
                    relevance_score=relevance,
                    publish_date=date,
                    source=source,
                    datasource_id=datasource_id,
                    category=category,
                    topics=topics if isinstance(topics, list) else [],
                    organizations=organizations if isinstance(organizations, list) else []
                )
                
                documents.append(doc)
        
        return documents
