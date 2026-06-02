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
from src.services.personalization import decide_personalization, get_user_preferences, get_user_source_memberships
from src.services.llm_client import get_llm_client, call_llm
from src.services.conversation_store import ConversationStore
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
        self.conv_store: Optional[ConversationStore] = None
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
        self.conv_store = ConversationStore(redis_client=redis_client)
        self._initialized = True
    
    async def _expand_wba_children(self, datasource_ids: list) -> list:
        """Expand any WBA Extranet programme IDs to include their child workgroups.

        A one-hop lookup on parent_datasource_id so that "what's new in my
        groups" automatically includes workgroups belonging to joined programmes.
        Results are cached in Redis for 5 minutes.
        """
        if not datasource_ids:
            return datasource_ids

        cache_key = "fast:datasource_tree:wba_children"
        # Try Redis cache first
        if self.fast_cache and self.fast_cache._redis_client:
            try:
                import json as _json
                cached = self.fast_cache._redis_client.get(cache_key)
                if cached:
                    child_map: dict = _json.loads(cached)
                else:
                    child_map = {}
            except Exception:
                child_map = {}
        else:
            child_map = {}

        if not child_map:
            # Build map from Neo4j
            try:
                from src.services.graph_service_oracle import get_oracle_repo
                repo = get_oracle_repo()
                rows = repo.client.execute_query(
                    """
                    MATCH (child:DataSource {scraper_type: 'wba_extranet'})
                    WHERE child.parent_datasource_id IS NOT NULL
                    RETURN child.parent_datasource_id AS parent,
                           child.datasource_id        AS child
                    """,
                    {},
                )
                for r in rows:
                    child_map.setdefault(r["parent"], []).append(r["child"])
                if self.fast_cache and self.fast_cache._redis_client:
                    import json as _json
                    self.fast_cache._redis_client.setex(cache_key, 300, _json.dumps(child_map))
            except Exception as exc:
                logger.warning(f"_expand_wba_children: Neo4j lookup failed: {exc}")
                return datasource_ids

        expanded = list(datasource_ids)
        for ds_id in list(datasource_ids):
            for child_id in child_map.get(ds_id, []):
                if child_id not in expanded:
                    expanded.append(child_id)
        return expanded

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

            # Load user source memberships (joined=boost, ignored=hard-exclude)
            user_excluded_datasources: list = []
            user_preferred_datasources: list = []
            user_preferred_domains: list = []
            if request.user_id:
                try:
                    memberships = get_user_source_memberships(str(request.user_id))
                    user_excluded_datasources = memberships.get("ignored", [])
                    user_preferred_datasources = memberships.get("joined", [])
                    if user_excluded_datasources:
                        logger.info(f"[{query_id}] User ignoring datasources: {user_excluded_datasources}")
                    if user_preferred_datasources:
                        logger.info(f"[{query_id}] User joined datasources: {user_preferred_datasources}")
                except Exception as e:
                    logger.warning(f"[{query_id}] Failed to fetch source memberships: {e}")

                try:
                    user_prefs_for_domains = await get_user_preferences(str(request.user_id))
                    user_preferred_domains = user_prefs_for_domains.domains or []
                    if user_preferred_domains:
                        logger.info(f"[{query_id}] User domain preferences: {user_preferred_domains}")
                except Exception as e:
                    logger.warning(f"[{query_id}] Failed to fetch user domain preferences: {e}")
            
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

            # Load conversation history for contextual follow-up questions
            conversation_history: list[dict] = []
            if self.conv_store and request.user_id:
                conversation_history = await self.conv_store.get_context(
                    str(request.user_id), max_turns=2
                )
            
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

            # Attach source membership filters to plan for use in build_params()
            if user_excluded_datasources:
                plan.excluded_datasources = user_excluded_datasources
            if user_preferred_datasources:
                # If request already has explicit datasource_ids, honour those and don't
                # override with joined preferences. Still apply excluded filter.
                if not datasource_ids:
                    plan.preferred_datasources = user_preferred_datasources
            if user_preferred_domains:
                plan.preferred_domains = user_preferred_domains

            # WBA: for programme-level routes, expand preferred_datasources to
            # include child workgroups (one hop via parent_datasource_id).
            route_id_value = plan.route_id.value if hasattr(plan.route_id, 'value') else plan.route_id
            from src.models.route_plan import RouteId as _RI
            if route_id_value in (
                _RI.WBA_RECENT_ACTIVITY.value, _RI.MY_GROUPS_DIGEST.value
            ) and plan.preferred_datasources:
                plan.preferred_datasources = await self._expand_wba_children(
                    plan.preferred_datasources
                )

            # MEMBERSHIP_ACTION: short-circuit — do NOT execute Cypher,
            # do NOT raise (a raise triggers baseline fallback).
            if route_id_value == _RI.MEMBERSHIP_ACTION.value:
                from src.services.membership_action import handle as _handle_membership
                answer_text = await _handle_membership(
                    question=request.question,
                    user_id=str(request.user_id) if request.user_id else None,
                    neo4j_client=self.neo4j_client if hasattr(self, 'neo4j_client') else None,
                    span=span,
                )
                # Build a minimal response and return immediately.
                from src.models.response import OracleResponse, RetrievalMetadata
                processing_time_ms = int((time.time() - start_time) * 1000)
                metadata = RetrievalMetadata(
                    intent="membership_action",
                    intent_confidence=1.0,
                    strategies_used=["membership_action"],
                    total_candidates=0,
                    processing_time_ms=processing_time_ms,
                )
                return OracleResponse(
                    answer=answer_text,
                    documents=[],
                    citations=[],
                    metadata=metadata,
                    pipeline="fast",
                    fast_confidence=1.0,
                )

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
                    conversation_history=conversation_history or None,
                )
                cache_bypass_reason = compose_cache_bypass_reason

                # Persist this turn for future follow-up questions
                if answer and self.conv_store and request.user_id:
                    await self.conv_store.append_turn(
                        str(request.user_id), request.question, answer
                    )
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
            
            # Composite confidence:
            #   - routing quality (plan.confidence) — how specific the route pattern was
            #   - result coverage — did we get enough docs back
            #   - temporal quality — do those docs have valid dates
            #   - match quality — did the named entity actually exist in the graph
            #     (exact / fuzzy / missing). This last term is what stops the fast
            #     pipeline from reporting high confidence on tangentially-related
            #     fuzzy-text matches when the user named an entity not in the KG.
            if getattr(plan, "entity_missing", False):
                # "Did you mean" response. Calibrate confidence low so the UI signals
                # uncertainty even though the answer was produced quickly.
                fast_confidence = 0.2
            else:
                doc_count = len(documents)
                result_count_factor = min(doc_count / 5.0, 1.0) if doc_count > 0 else 0.0
                temporal_factor = (
                    sum(1 for d in documents if d.publish_date) / doc_count
                    if doc_count > 0 else 0.0
                )
                match_quality_factor = {
                    "exact": 1.0,
                    "fuzzy": 0.5,
                    "missing": 0.0,
                }.get(getattr(plan, "match_quality", None) or "exact", 1.0)
                fast_confidence = round(
                    plan.confidence * 0.3
                    + result_count_factor * 0.3
                    + temporal_factor * 0.1
                    + match_quality_factor * 0.3,
                    3,
                )

            response = QueryResponse(
                query_id=str(query_id),
                answer=answer,
                mode="answer" if request.mode == QueryMode.ANSWER else "retrieval",
                documents=documents,
                citations=citations,
                metadata=metadata,
                suggestions=[],
                confidence_score=fast_confidence,
                personalization_applied=personalization_enabled,
                pipeline="fast",
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

    # Route IDs whose Cypher templates look up a specific named entity.
    # When one of these fires, _retrieve_neo4j_data runs the entity-existence
    # precheck and short-circuits with a "did you mean" response if the named
    # entity isn't in the graph. DOCUMENTS_BY_TOPIC is intentionally NOT in
    # this list — its fuzzy text fallback is already gated by the 0.4 penalty
    # in the Cypher template.
    _ENTITY_PRECHECK_ROUTES = frozenset({
        RouteId.PERSON_PROFILE,
        RouteId.PERSON_ACTIVITY,
        RouteId.PERSON_AT_EVENT,
        RouteId.PERSON_CONTRIBUTIONS,
        RouteId.ORGANIZATION_ACTIVITY,
        RouteId.ORGANIZATION_REPRESENTATIVES,
        RouteId.WORKGROUP_RECENT_UPDATES,
        RouteId.WORKGROUP_MONTHLY_SUMMARY,
        RouteId.MEETING_BY_TITLE,
        RouteId.TOPIC_TIMELINE,
        RouteId.TOPIC_RELATIONSHIPS,
    })

    def _should_run_entity_precheck(self, plan: RoutePlan) -> bool:
        """Decide whether to precheck entity existence before running the template.

        Skip if the plan came from an explicit @mention (the datasource id is
        already authoritative and shouldn't be second-guessed).
        """
        if getattr(plan, "explicit_datasource_filter", False):
            return False
        route_id = plan.route_id if isinstance(plan.route_id, RouteId) else None
        if route_id is None:
            try:
                route_id = RouteId(self._get_route_id_str(plan))
            except ValueError:
                return False
        if route_id not in self._ENTITY_PRECHECK_ROUTES:
            return False
        return bool(plan.people or plan.organizations or plan.workgroups or plan.topics)

    def _pick_entity_for_precheck(self, plan: RoutePlan) -> Optional[str]:
        """Pick the single most-specific named entity from a plan to precheck.

        Order: people > organizations > workgroups > topics. Returns the first
        non-empty string entry from the highest-priority list.
        """
        for bucket in (plan.people, plan.organizations, plan.workgroups, plan.topics):
            for entry in bucket or []:
                if entry and isinstance(entry, str) and entry.strip():
                    return entry.strip()
        return None

    @staticmethod
    def _compose_entity_missing_answer(
        entity: str,
        suggestions: List[Dict[str, str]],
    ) -> str:
        """Build a templated 'did you mean' response.

        No LLM call — pure string formatting. Streams instantly through the
        existing /query/stream endpoint because the chunker just splits this
        text into tokens.
        """
        # Deduplicate suggestions by name, preserving order, cap at 5.
        seen, deduped = set(), []
        for s in suggestions or []:
            name = (s or {}).get("name") if isinstance(s, dict) else None
            if not name or name in seen:
                continue
            seen.add(name)
            deduped.append(s)
            if len(deduped) >= 5:
                break

        lines = [
            f"I don't have specific information about \"{entity}\" in the knowledge graph yet.",
        ]
        if deduped:
            label_map = {
                "Person": "person",
                "Organization": "organization",
                "Topic": "topic",
                "DataSource": "workgroup",
            }
            suggestion_strs = []
            for s in deduped:
                name = s.get("name", "")
                label = label_map.get(s.get("label", ""), "entity")
                suggestion_strs.append(f"**{name}** ({label})")
            lines.append("")
            if len(suggestion_strs) == 1:
                lines.append(f"Did you mean {suggestion_strs[0]}?")
            else:
                lines.append("Did you mean one of these?")
                lines.append("")
                for s in suggestion_strs:
                    lines.append(f"- {s}")
        else:
            lines.append("")
            lines.append(
                "I couldn't find any similar names either. You might try rephrasing "
                "or asking about a broader topic the system tracks (Wi-Fi standards, "
                "WBA programmes, IEEE 802.11 task groups, recent meetings)."
            )
        return "\n".join(lines)
    
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
        
        retrieval_time_ms = int((time.time() - retrieval_start) * 1000)
        logger.info(f"PostgreSQL rollup query: {len(results)} results in {query_time_ms}ms")

        # For explicit @mention queries with no rollup data (or empty-summary rollups),
        # fall back to DATASOURCE_LATEST so the user gets "last known content from this
        # source" instead of a blank answer.
        def _rollup_has_content(r: dict) -> bool:
            # Checks both the rollup-specific fields AND the doc fields _nodes_to_documents reads.
            # This ensures alignment: a rollup counts as "useful" only if its summary/links
            # will actually produce usable content for the LLM or rollup-compose path.
            rollup_summary = (r.get("rollup_summary") or "").strip()
            links = r.get("links") or []
            # rollup_summary is the canonical content field for PostgreSQL rollup records
            return len(rollup_summary) > 20 or len(links) > 0

        useful_rollups = [r for r in results if _rollup_has_content(r)]
        logger.info(
            f"Rollup content check: total={len(results)} useful={len(useful_rollups)} "
            f"explicit={getattr(plan, 'explicit_datasource_filter', False)} workgroups={plan.workgroups}"
        )
        if not useful_rollups and getattr(plan, 'explicit_datasource_filter', False) and plan.workgroups:
            logger.info(
                f"No useful PostgreSQL rollup for explicit @mention datasources={plan.workgroups}, "
                f"trying DATASOURCE_LATEST from Neo4j"
            )
            repo = get_repo()
            logger.info(f"DATASOURCE_LATEST repo={repo is not None} template={self.template_registry.get_template(RouteId.DATASOURCE_LATEST) is not None}")
            latest_template = self.template_registry.get_template(RouteId.DATASOURCE_LATEST)
            if latest_template and repo:
                try:
                    latest_params = {"workgroups": plan.workgroups, "limit": 10}
                    fallback_results = repo.client.execute_query(latest_template.cypher, latest_params)
                    latest_nodes = latest_template.execute_post_process(fallback_results)
                    if latest_nodes:
                        for r in latest_nodes:
                            r['_no_recent_updates_showing_latest'] = True
                        logger.info(
                            f"DATASOURCE_LATEST found {len(latest_nodes)} historical docs "
                            f"for @mention datasources={plan.workgroups}"
                        )
                        route_result = RouteResult(
                            route_id=plan.route_id,
                            nodes=latest_nodes,
                            rollup=None,
                            execution_time_ms=query_time_ms,
                            node_count=len(latest_nodes),
                            cache_hit=False,
                        )
                        return route_result, retrieval_time_ms
                    else:
                        logger.warning(
                            f"DATASOURCE_LATEST also empty for datasources={plan.workgroups}"
                        )
                except Exception as e:
                    logger.warning(f"DATASOURCE_LATEST fallback in rollup path failed: {e}")

        # Build RouteResult using useful_rollups (content-filtered) to avoid
        # passing empty placeholder rollups to the LLM.
        final_nodes = useful_rollups if useful_rollups else results
        rollup_from_nodes = None
        if useful_rollups and useful_rollups[0].get("rollup_id"):
            first = useful_rollups[0]
            rollup_from_nodes = {
                "id": first["rollup_id"],
                "summary": first["rollup_summary"],
                "key_events": first.get("key_events", []),
                "key_decisions": first.get("key_decisions", []),
                "top_topics": first.get("top_topics", []),
                "links": first.get("links", []),
                "start": first.get("rollup_start"),
                "end": first.get("rollup_end"),
            }
        route_result = RouteResult(
            route_id=plan.route_id,
            nodes=final_nodes,
            rollup=rollup_from_nodes,
            execution_time_ms=query_time_ms,
            node_count=len(final_nodes),
            cache_hit=False
        )

        # Cache only when we have useful content (not empty rollups)
        if useful_rollups:
            await self.fast_cache.set_result(plan, route_result)

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

        # Entity-existence guard: when the route plan targets a specific named
        # person/organization/workgroup (Person, Organization, DataSource node),
        # check that the entity actually exists in the graph before running the
        # main template. This addresses the failure mode where a query like
        # "Kevin's latest news" routed to PERSON_PROFILE returns confidently
        # incorrect content about a Person that's NOT in the graph because the
        # template's fuzzy/CONTAINS fallback matches any document mentioning
        # "Kevin" anywhere in its text.
        if self._should_run_entity_precheck(plan):
            entity = self._pick_entity_for_precheck(plan)
            if entity:
                from src.services.query_template_registry import run_entity_precheck
                repo = get_repo()
                pre = run_entity_precheck(repo.client, entity)
                if not pre.get("exists"):
                    plan.entity_missing = True
                    plan.entity_suggestions = pre.get("suggestions", [])
                    plan.match_quality = "missing"
                    logger.info(
                        f"entity '{entity}' not found in graph; short-circuiting with "
                        f"{len(plan.entity_suggestions)} suggestions"
                    )
                    retrieval_time_ms = int((time.time() - retrieval_start) * 1000)
                    return RouteResult(
                        route_id=plan.route_id,
                        nodes=[],
                        rollup=None,
                        execution_time_ms=retrieval_time_ms,
                        node_count=0,
                        cache_hit=False,
                    ), retrieval_time_ms
                plan.match_quality = "exact"

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

        # Apply source membership filters:
        # 1. Hard-exclude results from datasources the user has ignored
        # 2. Soft-boost results from datasources the user has joined
        excluded_ds = params.get("excluded_datasources", [])
        preferred_ds = params.get("preferred_datasources", [])
        if excluded_ds:
            before_count = len(processed_results)
            processed_results = [
                r for r in processed_results
                if r.get("datasource_id") not in excluded_ds
                and r.get("workgroup_id") not in excluded_ds
            ]
            if len(processed_results) < before_count:
                logger.info(
                    f"Excluded {before_count - len(processed_results)} results from ignored datasources"
                )
        if preferred_ds and processed_results:
            def _source_boost(r: dict) -> float:
                ds_id = r.get("datasource_id") or r.get("workgroup_id") or ""
                return 1.4 if ds_id in preferred_ds else 1.0
            # Apply boost to any existing score field, or add a boost multiplier
            for r in processed_results:
                if "score" in r and r["score"] is not None:
                    r["score"] = float(r["score"]) * _source_boost(r)
                else:
                    r["_source_boost"] = _source_boost(r)
            # Re-sort by score after boost
            try:
                processed_results.sort(
                    key=lambda r: (r.get("score") or 0.0) * r.get("_source_boost", 1.0),
                    reverse=True
                )
            except Exception:
                pass

        # Apply domain preferences boost (soft, 1.25x — weaker than datasource membership)
        preferred_domains = params.get("preferred_domains", [])
        if preferred_domains and processed_results:
            for r in processed_results:
                r_domains = r.get("domains") or []
                if any(d in preferred_domains for d in r_domains):
                    if "score" in r and r["score"] is not None:
                        r["score"] = float(r["score"]) * 1.25
                    else:
                        r["_domain_boost"] = 1.25
            try:
                processed_results.sort(
                    key=lambda r: (r.get("score") or 0.0) * r.get("_domain_boost", 1.0),
                    reverse=True
                )
            except Exception:
                pass
        
        # Strip empty placeholder nodes before fallback logic — nodes that have no title,
        # no URL, and no summary (rollup placeholders) produce LLM hallucination.
        # Filtering them here ensures the fallback chain (DATASOURCE_LATEST etc.) fires
        # correctly when a workgroup has no recent content rather than stale placeholders.
        def _node_has_content(r: dict) -> bool:
            if any(k in r for k in ("recent_documents", "recent_events", "recent_activity", "sample_resources")):
                return True  # grouped node — content is nested
            title = r.get("title") or r.get("name") or ""
            url = r.get("url") or ""
            summary = r.get("summary") or r.get("description") or ""
            return bool(title and title != "Untitled") or bool(url) or len(summary) > 10

        before_filter = len(processed_results)
        processed_results = [r for r in processed_results if _node_has_content(r)]
        if len(processed_results) < before_filter:
            logger.info(
                f"Dropped {before_filter - len(processed_results)} empty placeholder nodes "
                f"(route={self._get_route_id_str(plan)}) — will trigger fallback chain"
            )

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
            processed_results = [r for r in template.execute_post_process(fallback_results) if _node_has_content(r)]

            if len(processed_results) > 0:
                logger.info(f"Fallback succeeded: retrieved {len(processed_results)} undated documents")
                query_time_ms += fallback_time_ms
            else:
                logger.warning("Fallback also returned zero results")
        
        # Cross-datasource fallback: behaviour depends on whether the workgroups filter
        # was set by an explicit @mention/datasource_ids (explicit_datasource_filter=True)
        # or was inferred from the query text.
        #
        # Explicit filter  → NEVER expand to other sources (that's wrong).
        #                     Instead, return the most recent docs from that source
        #                     regardless of date window (DATASOURCE_LATEST template).
        # Inferred filter  → Expand to all datasources as before.
        if len(processed_results) == 0 and params.get('workgroups') and len(params['workgroups']) > 0:
            is_explicit = getattr(plan, 'explicit_datasource_filter', False)

            if is_explicit:
                # User explicitly targeted this source — stay within it.
                # Use DATASOURCE_LATEST: no date window, just the most recent N docs.
                logger.info(
                    f"Zero recent results for explicit @source filter, trying DATASOURCE_LATEST "
                    f"(workgroups={params['workgroups']})"
                )
                latest_template = self.template_registry.get_template(RouteId.DATASOURCE_LATEST)
                if latest_template:
                    try:
                        latest_params = {
                            "workgroups": params['workgroups'],
                            "limit": params.get('limit', 10),
                        }
                        fallback_start = time.time()
                        fallback_results = repo.client.execute_query(
                            latest_template.cypher,
                            latest_params
                        )
                        fallback_time_ms = int((time.time() - fallback_start) * 1000)
                        processed_results = latest_template.execute_post_process(fallback_results)
                        query_time_ms += fallback_time_ms
                        if len(processed_results) > 0:
                            logger.info(
                                f"DATASOURCE_LATEST fallback: {len(processed_results)} docs "
                                f"(oldest available from explicit source)"
                            )
                            # Tag results so answer generator can say "no recent updates; last known:"
                            for r in processed_results:
                                r['_explicit_source_latest_fallback'] = True
                        else:
                            logger.warning(
                                f"DATASOURCE_LATEST fallback: no documents at all for "
                                f"workgroups={params['workgroups']}"
                            )
                    except Exception as e:
                        logger.warning(f"DATASOURCE_LATEST fallback failed: {e}")
            else:
                # Inferred workgroup filter — first try DATASOURCE_LATEST for that workgroup
                # so the user gets "no updates this period, but last known content was…"
                # rather than silently expanding to all datasources.
                latest_template = self.template_registry.get_template(RouteId.DATASOURCE_LATEST)
                used_latest_for_inferred = False
                if latest_template and params.get('workgroups'):
                    try:
                        latest_params = {
                            "workgroups": params['workgroups'],
                            "limit": params.get('limit', 10),
                        }
                        fallback_start = time.time()
                        fallback_results = repo.client.execute_query(
                            latest_template.cypher,
                            latest_params
                        )
                        fallback_time_ms = int((time.time() - fallback_start) * 1000)
                        processed_results = latest_template.execute_post_process(fallback_results)
                        query_time_ms += fallback_time_ms
                        if len(processed_results) > 0:
                            logger.info(
                                f"DATASOURCE_LATEST (inferred workgroup) fallback: "
                                f"{len(processed_results)} docs — no recent updates in time window"
                            )
                            for r in processed_results:
                                r['_no_recent_updates_showing_latest'] = True
                            used_latest_for_inferred = True
                    except Exception as e:
                        logger.warning(f"DATASOURCE_LATEST (inferred) fallback failed: {e}")

                if not used_latest_for_inferred:
                    # Expand to all datasources as last resort
                    logger.info(
                        f"Zero results with inferred workgroups filter, expanding to all datasources "
                        f"(route={self._get_route_id_str(plan)}, workgroups={params['workgroups']})"
                    )
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

        # UPCOMING_EVENTS special fallback: if still zero, show the most recent past events
        # so the user gets something useful ("no upcoming events, but here were the most recent")
        if len(processed_results) == 0 and self._get_route_id_str(plan) == RouteId.UPCOMING_EVENTS.value:
            past_template = self.template_registry.get_template(RouteId.PAST_EVENTS)
            if past_template:
                logger.info("UPCOMING_EVENTS returned 0 — falling back to PAST_EVENTS (365-day window)")
                try:
                    past_params = {k: v for k, v in params.items()}
                    past_params['relative_days'] = 365
                    past_params['start_date'] = None
                    past_params['end_date'] = None
                    fallback_start = time.time()
                    fallback_results = repo.client.execute_query(past_template.cypher, past_params)
                    fallback_time_ms = int((time.time() - fallback_start) * 1000)
                    processed_results = past_template.execute_post_process(fallback_results)
                    query_time_ms += fallback_time_ms
                    if len(processed_results) > 0:
                        logger.info(f"PAST_EVENTS fallback: {len(processed_results)} historical events found")
                        for r in processed_results:
                            r['_no_upcoming_found_showing_past'] = True
                    else:
                        logger.warning("PAST_EVENTS fallback also returned zero results")
                except Exception as e:
                    logger.warning(f"PAST_EVENTS fallback failed: {e}")

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
        conversation_history: Optional[List[dict]] = None,
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

            # Entity-missing short-circuit: when the precheck found that the
            # named entity (Person/Organization/DataSource/Topic) isn't in the
            # graph, return a templated "did you mean" response instead of
            # synthesising a confident wrong answer. No LLM call; streams
            # essentially instantly. Skips the answer cache deliberately so a
            # later ingest of the missing entity doesn't keep serving stale
            # "we don't have info" replies.
            if getattr(plan, "entity_missing", False):
                entity = self._pick_entity_for_precheck(plan) or "that"
                answer = self._compose_entity_missing_answer(
                    entity=entity,
                    suggestions=plan.entity_suggestions or [],
                )
                answer_time_ms = int((time.time() - answer_start) * 1000)
                return answer, [], [], answer_time_ms, False, "entity_missing"

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
                        plan, route_result, deep_dive_result, request, span,
                        user_context=user_context, conversation_history=conversation_history
                    )
            else:
                # LLM-based synthesis
                answer, documents, citations = await self._compose_with_llm(
                    plan, route_result, deep_dive_result, request, span,
                    user_context=user_context, conversation_history=conversation_history
                )
            
            answer_time_ms = int((time.time() - answer_start) * 1000)
            
            # Cache answer (skip if personalized).
            # Also skip caching for temporal "no recent updates" disclaimers — these are
            # date-specific and will be stale on the next request, causing all queries that
            # share the same plan hash to return a stale dated response indefinitely.
            _NO_CACHE_PHRASES = (
                "i don't have new updates for",
                "i don't have updates for",
                "i have no new updates for",
                "no new updates for",
                "no updates for",
                "most recent update i have is from",
                "most recent information i have is from",
                "the latest i have is from",
            )
            answer_lower = (answer or "").lower()
            is_temporal_disclaimer = any(phrase in answer_lower for phrase in _NO_CACHE_PHRASES)
            
            if not skip_cache and not is_temporal_disclaimer:
                answer_data = {
                    "answer": answer,
                    "documents": [d.model_dump() for d in documents],
                    "citations": [c.model_dump() for c in citations],
                }
                await self.fast_cache.set_answer(plan, result_digest, answer_data, scope=cache_scope)
            elif is_temporal_disclaimer:
                logger.info("Skipping answer cache: response is a temporal disclaimer (date-specific no-update response)")
            
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
        
        # Add summary (now a rich multi-line text from _generate_summary)
        if rollup.get("summary"):
            answer_parts.append(rollup["summary"])

        # Add key events (if not already embedded in summary)
        if rollup.get("key_events"):
            events = rollup["key_events"]
            if events:
                answer_parts.append(f"\n\n**Key Events ({len(events)}):**")
                for event in events[:5]:
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

        # Build documents and citations from rollup links
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
                    citations.append(Citation(
                        index=idx,
                        document_url=doc.url,
                        title=doc.title,
                        excerpt=None
                    ))

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
        conversation_history: Optional[List[dict]] = None,
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
        
        # Safety-net: drop any remaining empty/useless nodes that slipped through the
        # early filter (e.g. from fallback paths that don't re-apply the filter).
        documents = [
            d for d in documents
            if (d.title and d.title != "Untitled") or d.url or (d.summary and len(d.summary) > 10)
        ]

        if not documents:
            # When nodes are empty/useless but a pre-computed rollup exists (e.g.
            # WORKGROUP_WEEKLY_RECAP with populated summary + links), use the rollup
            # instead of raising zero_docs_fallback.  This covers @mention queries
            # where the rollup was generated but has no individually-navigable
            # document URLs (the rollup itself IS the content).
            rollup = getattr(route_result, 'rollup', None)
            if rollup and rollup.get("summary") and len((rollup.get("summary") or "").strip()) > 20:
                logger.info("Documents empty but rollup has content — using rollup path")
                return self._compose_from_rollup(plan, route_result, request)

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

            # ── Coverage summary for broad recency queries ───────────────────────
            # For "what is new" / "what happened" queries, the RECENT_CONTENT template
            # returns a *sample* from the top N groups. The LLM only sees those docs —
            # it has no idea that dozens of other groups also had activity this week.
            # We inject a preamble so it can give the user an accurate picture and
            # tell them where to find more detail.
            coverage_summary = ""
            is_broad_recency = bool(re.search(
                r"(?:"
                r"what\s+(?:is|are|was|were)\s+new"
                r"|what.{0,4}(?:happening|latest|recent)"
                r"|what\s+(?:happened|came\s+out|was\s+released|was\s+published|was\s+updated)"
                r"|(?:latest|recent|newest)\s+(?:news|updates?|developments?|activity|content|documents?)"
                r"|this\s+(?:week|month|year)"
                r"|past\s+(?:week|month|few\s+(?:days|weeks))"
                r")",
                request.question.lower()
            ))
            if is_broad_recency and route_result.nodes:
                # Gather group info from the RECENT_CONTENT grouped nodes
                shown_groups: list[dict] = []
                total_before_limit: int = 0
                for node in route_result.nodes:
                    if "workgroup_name" not in node:
                        continue
                    wg_name = node.get("workgroup_name") or node.get("workgroup_id", "?")
                    doc_count = node.get("total_doc_count", 0) or len(node.get("recent_documents", []))
                    communities = node.get("community_names") or []
                    shown_groups.append({
                        "name": wg_name,
                        "doc_count": doc_count,
                        "communities": communities,
                    })
                    # total_groups_before_limit is the same for all rows (repeated by UNWIND)
                    total_before_limit = max(total_before_limit, node.get("total_groups_before_limit") or len(route_result.nodes))

                if shown_groups:
                    hidden_count = max(0, total_before_limit - len(shown_groups))
                    parts = ["**COVERAGE NOTE — sources with recent activity (this sample shows the top groups):**"]
                    for g in shown_groups:
                        comm = (", ".join(g["communities"][:4]) + ("…" if len(g["communities"]) > 4 else "")) if g["communities"] else ""
                        comm_note = f" — including: {comm}" if comm else ""
                        parts.append(f"  • **{g['name']}**: {g['doc_count']} documents{comm_note}")
                    if hidden_count > 0:
                        parts.append(
                            f"  • …and {hidden_count} more group(s) with recent activity not shown in this sample."
                        )
                    parts.append(
                        "\n**INSTRUCTIONS**: In your answer, mention ALL of these groups by name, even if briefly. "
                        "Give 1–2 sentence highlights per group. End your answer with a hint like: "
                        "\"For full details from a specific group, ask about @wba, @wfa-causeway, or @ietf.\""
                    )
                    coverage_summary = "\n".join(parts)
            
            docs_for_prompt = [
                {
                    "title": doc.title or "Untitled",
                    "summary": doc.summary or "No summary available",
                    "publish_date": doc.publish_date or "",
                    "temporal_confidence": doc.temporal_confidence or "high",
                    "url": doc.url,
                    "topics": doc.topics,
                    "organizations": doc.organizations,
                    "datasource_id": doc.datasource_id or "Unknown source",
                }
                for doc in documents[:10]
            ]
            
            # Inject coverage summary so the LLM knows about all active groups
            if coverage_summary:
                docs_for_prompt.insert(0, {
                    "title": "📡 Activity Coverage Across Sources",
                    "summary": coverage_summary,
                    "publish_date": "",
                    "temporal_confidence": "high",
                    "url": "",
                    "topics": [],
                    "organizations": [],
                    "datasource_id": "coverage_metadata",
                })
            elif datasource_summary and docs_for_prompt:
                docs_for_prompt.insert(0, {
                    "title": "📊 Distribution Summary",
                    "summary": datasource_summary.strip(),
                    "publish_date": "",
                    "temporal_confidence": "high",
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

            # Map DetailLevel enum to string for the prompt builder
            detail_str = "detailed"
            if plan.detail_level == DetailLevel.BRIEF:
                detail_str = "brief"
            elif plan.detail_level == DetailLevel.COMPREHENSIVE:
                detail_str = "comprehensive"

            messages = get_answer_generator_messages(
                request.question,
                docs_for_prompt,
                graph_context,
                user_context,
                conversation_history=conversation_history,
                detail_level=detail_str,
                agent_persona=getattr(request, 'agent_persona', None),
            )
            
            # Allow more tokens for comprehensive requests
            max_tokens = settings.max_answer_tokens
            if plan.detail_level == DetailLevel.COMPREHENSIVE:
                max_tokens = max(max_tokens, 1500)

            _agent_temp = getattr(getattr(request, 'agent_persona', None), 'llm_temperature_override', None)
            response = await call_llm(
                client=client,
                messages=messages,
                max_tokens=max_tokens,
                temperature=_agent_temp if _agent_temp is not None else 0.3
            )
            
            answer = (response.content or "").strip()
            answer = self._strip_trailing_references(answer)
            if not answer:
                logger.warning("LLM synthesis returned empty content, falling back to deterministic summary")
                answer, citations = self._build_simple_summary(documents)
                return answer, documents, citations
            
            # Create citations for all documents passed to the LLM prompt (up to 10)
            # Must match docs_for_prompt range so [6]..[10] refs in the answer are resolvable
            citations = []
            for idx, doc in enumerate(documents[:10], 1):
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
    
    @staticmethod
    def _strip_trailing_references(answer: str) -> str:
        """Remove any LLM-generated reference list appended after the answer.

        The LLM occasionally echoes the document metadata block at the end of
        its answer — e.g. lines like:
            [1] Title: Wi-Fi 8 TTG Meeting
            [2]URL: Wi-Fi Alliance Newsroom
            [1] https://...

        These are redundant (the frontend renders its own reference list) and
        look broken. Strip any trailing block that consists entirely of such lines.
        """
        import re
        lines = answer.rstrip().splitlines()
        # Walk backwards — drop consecutive lines that look like reference entries
        ref_pattern = re.compile(
            r"^\s*(\[\d+\]|\*\*\[\d+\]\*\*)"   # starts with [N] or **[N]**
            r"(\s*(Title|URL|Source|Date|Datasource|http|https):|\s+https?://|\s*$)",
            re.IGNORECASE,
        )
        cut = len(lines)
        for i in range(len(lines) - 1, -1, -1):
            line = lines[i].strip()
            if not line:
                cut = i  # skip trailing blank lines too
                continue
            if ref_pattern.match(lines[i]):
                cut = i
            else:
                break
        return "\n".join(lines[:cut]).rstrip()

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

                # Person nodes (from ORGANIZATION_REPRESENTATIVES / PERSON_PROFILE) carry
                # role + organization instead of a document summary.  Build a human-readable
                # summary so the LLM has substance to work with.
                if not summary and node.get("role") and node.get("organization"):
                    role = node["role"]
                    org  = node["organization"]
                    topics_list = node.get("topics") or []
                    topic_str = (", ".join(topics_list[:3]) + " ") if topics_list else ""
                    email_str  = f" ({node['email']})" if node.get("email") else ""
                    activity   = node.get("activity_count", 0)
                    activity_str = f" — {activity} document mention(s) found" if activity else ""
                    summary = (
                        f"{role} at {org}{email_str}. "
                        f"Known topics: {topic_str}in the knowledge graph{activity_str}."
                    )
                elif not summary and node.get("role"):
                    summary = node["role"]

                date = node.get("date") or node.get("start_time") or node.get("startTime") or node.get("publish_date")
                
                # Extract real metadata from Neo4j results
                datasource_id = node.get("datasource_id")
                category = node.get("category") or node.get("event_type") or node.get("type")
                topics = node.get("topics", []) or node.get("all_topic_names", [])
                organizations = node.get("organizations", []) or node.get("org_names", [])
                if node.get("organization") and not organizations:
                    organizations = [node["organization"]]
                relevance = node.get("relevance_score", 1.0)
                
                # Build source name from datasource_id or fall back to category
                source = None
                if datasource_id:
                    # Convert datasource_id to readable name (e.g., "wfa_causeway" -> "WFA Causeway")
                    source = datasource_id.replace("_", " ").title()
                elif category:
                    source = category.replace("_", " ").title()
                elif node.get("organization"):
                    source = node["organization"]
                
                doc = Document(
                    title=title,
                    summary=summary,
                    url=url,
                    relevance_score=relevance,
                    publish_date=date,
                    temporal_confidence=node.get("temporal_confidence") or ("high" if date else "low"),
                    source=source,
                    datasource_id=datasource_id,
                    category=category,
                    topics=topics if isinstance(topics, list) else [],
                    organizations=organizations if isinstance(organizations, list) else []
                )
                
                documents.append(doc)
        
        return documents
