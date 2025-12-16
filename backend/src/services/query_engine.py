from typing import Any, Dict, List
import logging

from src.services.llm_service import parse_query_to_filters, summarise_documents
from src.services.graph_service import query_documents_from_filters, query_upcoming_events, query_past_events, query_temporal_documents
from src.services import postgres, graph_service

log = logging.getLogger("query_engine")


def run_query(user_id: str, question: str) -> Dict[str, Any]:  # Changed from int to str
    """Full question-answering pipeline:
    
    1. Accept a question and user_id (Cognito UUID)
    2. Load user preferences from Postgres (topics, organisations, people)
    3. Send question to LLM to extract structured filters
    4. Merge LLM-generated filters with user preferences as relevance signals
    5. Query Neo4j using merged filters for relevant documents
    6. Pass question, documents, and preferences to LLM summarizer
    7. Return answer with metadata (filters applied, documents retrieved)
    
    The pipeline is resilient to missing preferences - if none exist, relies solely
    on LLM filters and knowledge graph content.
    """
    log.info(f"Processing query for user_id={user_id}: {question}")
    
    # Step 1: Load user preferences from Postgres
    user_prefs = postgres.get_user_preferences(user_id)
    pref_topics = user_prefs.get("topics") or []
    pref_orgs = user_prefs.get("organisations") or []
    pref_people = user_prefs.get("people") or []
    
    has_preferences = bool(pref_topics or pref_orgs or pref_people)
    if has_preferences:
        log.info(f"✓ User preferences loaded: {len(pref_topics)} topics, {len(pref_orgs)} orgs, {len(pref_people)} people")
        log.info(f"  Topics: {pref_topics}")
        log.info(f"  Organisations: {pref_orgs}")
        log.info(f"  People: {pref_people}")
    else:
        log.info("✗ No user preferences found - using query-based filters only")
    
    # Step 2: Parse question with LLM to extract filters
    llm_filters = parse_query_to_filters(question)
    query_intent = llm_filters.get('query_intent', 'recent')
    temporal_focus = llm_filters.get('temporal_focus')  # None, "published", "updated", or "mixed"
    log.info(f"✓ LLM extracted filters:")
    log.info(f"  Query Intent: {query_intent}")
    log.info(f"  Temporal Focus: {temporal_focus or 'none'}")
    log.info(f"  Topics: {llm_filters.get('topics', [])}")
    log.info(f"  Organisations: {llm_filters.get('organisations', [])}")
    log.info(f"  People: {llm_filters.get('people', [])}")
    log.info(f"  Category: {llm_filters.get('category', 'any')}")
    log.info(f"  Doc Type: {llm_filters.get('doc_type', 'any')}")
    log.info(f"  Date range: {llm_filters.get('start_date')} to {llm_filters.get('end_date')}")
    log.info(f"  Limit: {llm_filters.get('limit', 20)}")
    
    # Step 2.5: Load system configuration for relevance weights from Neo4j
    try:
        system_config = graph_service.get_datasource_configuration("default")
        publish_weight = system_config.get("publish_weight", 1.0)
        update_weight = system_config.get("update_weight", 0.8)
        event_weight = system_config.get("event_weight", 0.9)
        log.info(f"✓ Loaded relevance weights from Neo4j: publish={publish_weight}, update={update_weight}, event={event_weight}")
    except Exception as e:
        # Fallback to defaults if config not found in Neo4j
        log.warning(f"Could not load config from Neo4j, using defaults: {e}")
        publish_weight = 1.0
        update_weight = 0.8
        event_weight = 0.9
    
    # Detect if this is a meta-query about the knowledge base itself
    # Meta-queries ask about stats, counts, or structure rather than content
    question_lower = question.lower()
    is_meta_query = any([
        "how many" in question_lower and any(x in question_lower for x in ["topics", "organisations", "people", "documents", "resources"]),
        "list all" in question_lower and any(x in question_lower for x in ["topics", "organisations", "people"]),
        "what topics" in question_lower and "available" in question_lower,
        "what organisations" in question_lower and "available" in question_lower,
        "show me all" in question_lower and any(x in question_lower for x in ["topics", "organisations", "people"]),
    ])
    
    # Check if LLM extracted any filters from the query
    has_query_filters = any([
        llm_filters.get("topics"),
        llm_filters.get("organisations"),
        llm_filters.get("people"),
        llm_filters.get("category"),
        llm_filters.get("doc_type"),
        llm_filters.get("start_date"),
        llm_filters.get("end_date")
    ])
    
    # Step 3: Use ONLY query filters, not user preferences
    # User preferences are tracked for analytics but don't affect document retrieval
    # This ensures precise, query-relevant results instead of preference-biased results
    if has_query_filters:
        log.info("✓ Using query filters only (no user preference merging for precise results)")
        merged_filters = {
            "topics": llm_filters.get("topics", []),
            "organisations": llm_filters.get("organisations", []),
            "people": llm_filters.get("people", []),
            "category": llm_filters.get("category"),
            "doc_type": llm_filters.get("doc_type"),
            "start_date": llm_filters.get("start_date"),
            "end_date": llm_filters.get("end_date"),
            "limit": llm_filters.get("limit", 20)
        }
    else:
        log.info("✓ No filters extracted from query - using query-only mode (no user preference merging)")
        merged_filters = {
            "topics": [],
            "organisations": [],
            "people": [],
            "category": None,
            "doc_type": None,
            "start_date": None,
            "end_date": None,
            "limit": llm_filters.get("limit", 20)
        }
    
    log.info(f"✓ Final filters for Neo4j query:")
    log.info(f"  Topics ({len(merged_filters.get('topics', []))}): {merged_filters.get('topics', [])}")
    log.info(f"  Organisations ({len(merged_filters.get('organisations', []))}): {merged_filters.get('organisations', [])}")
    log.info(f"  People ({len(merged_filters.get('people', []))}): {merged_filters.get('people', [])}")
    log.info(f"  Category: {merged_filters.get('category', 'any')}")
    log.info(f"  Doc Type: {merged_filters.get('doc_type', 'any')}")
    log.info(f"  Date range: {merged_filters.get('start_date')} to {merged_filters.get('end_date')}")
    log.info(f"  Result limit: {merged_filters.get('limit', 20)}")
    
    # Determine if we should retrieve documents or events based on query intent
    should_retrieve_docs = has_query_filters and not is_meta_query
    docs = []
    events = []
    
    if should_retrieve_docs:
        # Step 4: Query Neo4j based on temporal intent and temporal focus
        
        # Handle temporal focus for document queries (published/updated/mixed)
        if temporal_focus in ["published", "updated", "mixed"]:
            log.info(f"✓ Temporal document query detected - focus: {temporal_focus}")
            temporal_result = query_temporal_documents(
                merged_filters,
                temporal_focus,
                publish_weight=publish_weight,
                update_weight=update_weight
            )
            docs = temporal_result.get("documents", [])
            published_count = temporal_result.get("published_count", 0)
            updated_count = temporal_result.get("updated_count", 0)
            log.info(f"✓ Retrieved {len(docs)} temporal documents ({published_count} published, {updated_count} updated)")
            
            # Also query events based on query_intent
            if query_intent == "future":
                events = query_upcoming_events(merged_filters)
                log.info(f"✓ Also retrieved {len(events)} upcoming events")
            elif query_intent == "historical":
                events = query_past_events(merged_filters)
                log.info(f"✓ Also retrieved {len(events)} past events")
            elif query_intent == "mixed":
                events_future = query_upcoming_events(merged_filters)
                events_past = query_past_events(merged_filters)
                events = events_future + events_past
                log.info(f"✓ Also retrieved {len(events)} total events ({len(events_future)} upcoming, {len(events_past)} past)")
        
        # Handle event-focused queries (no temporal document focus)
        elif query_intent == "future":
            # Query for upcoming events
            log.info("✓ Future-oriented query detected - fetching upcoming events")
            events = query_upcoming_events(merged_filters)
            log.info(f"✓ Retrieved {len(events)} upcoming events from Neo4j")
            
            # Also get recent related documents for context
            log.info("✓ Also fetching related documents for context")
            docs = query_documents_from_filters(merged_filters)
            log.info(f"✓ Retrieved {len(docs)} related documents")
            
        elif query_intent == "historical":
            # Query for past events and documents
            log.info("✓ Historical query detected - fetching past events and documents")
            events = query_past_events(merged_filters)
            log.info(f"✓ Retrieved {len(events)} past events from Neo4j")
            
            docs = query_documents_from_filters(merged_filters)
            log.info(f"✓ Retrieved {len(docs)} documents from Neo4j")
            
        elif query_intent == "mixed":
            # Query both future events and recent documents
            log.info("✓ Mixed temporal query - fetching both events and documents")
            events_future = query_upcoming_events(merged_filters)
            events_past = query_past_events(merged_filters)
            events = events_future + events_past
            log.info(f"✓ Retrieved {len(events)} total events ({len(events_future)} upcoming, {len(events_past)} past)")
            
            docs = query_documents_from_filters(merged_filters)
            log.info(f"✓ Retrieved {len(docs)} documents from Neo4j")
            
        else:  # "recent" or default
            # Query for recent documents only
            log.info("✓ Recent/default query - fetching documents")
            docs = query_documents_from_filters(merged_filters)
            log.info(f"✓ Retrieved {len(docs)} documents from Neo4j knowledge graph")
        
        if not docs and not events:
            log.warning("✗ No documents or events found matching query and filters")
    else:
        if is_meta_query:
            log.info("✓ Meta-query detected - skipping document retrieval")
        else:
            log.info("✓ No filters specified - answering without document context")
    
    # Step 5: Summarize documents and events with LLM, incorporating user preferences
    user_pref_context = {
        "topics": pref_topics,
        "organisations": pref_orgs,
        "people": pref_people
    } if has_preferences else None
    
    # Combine documents and events for summarization
    # For now, pass events in user_pref_context to maintain backwards compatibility
    context_with_events = user_pref_context.copy() if user_pref_context else {}
    if events:
        context_with_events["events"] = events
    
    answer = summarise_documents(question, docs, context_with_events if context_with_events else None)
    
    # Step 6: Prepare response with limited topic display for users with many preferences
    formatted_docs = _format_documents_for_response(docs, max_topics_per_doc=10) if docs else []
    
    return {
        "answer": answer,
        "filters": {
            "applied": merged_filters if should_retrieve_docs else {},
            "from_query": llm_filters,
            "from_preferences": {
                "topics": pref_topics,
                "organisations": pref_orgs,
                "people": pref_people
            } if has_preferences else None
        },
        "query_intent": query_intent,
        "temporal_focus": temporal_focus,
        "documents": formatted_docs,
        "document_count": len(docs),
        "events": events,
        "event_count": len(events),
        "is_meta_query": is_meta_query,
        "pipeline_debug": {
            "stage_1_user_preferences": {
                "has_preferences": has_preferences,
                "topics_count": len(pref_topics),
                "organisations_count": len(pref_orgs),
                "people_count": len(pref_people)
            },
            "stage_2_llm_extraction": {
                "topics": llm_filters.get("topics", []),
                "organisations": llm_filters.get("organisations", []),
                "people": llm_filters.get("people", []),
                "category": llm_filters.get("category"),
                "doc_type": llm_filters.get("doc_type"),
                "date_range": f"{llm_filters.get('start_date') or 'none'} to {llm_filters.get('end_date') or 'none'}",
                "limit": llm_filters.get("limit", 20)
            },
            "stage_3_filter_merging": {
                "has_query_filters": has_query_filters,
                "applied_user_prefs": has_query_filters and has_preferences,
                "final_topics_count": len(merged_filters.get("topics", [])),
                "final_orgs_count": len(merged_filters.get("organisations", [])),
                "final_people_count": len(merged_filters.get("people", []))
            },
            "stage_4_document_retrieval": {
                "should_retrieve": should_retrieve_docs,
                "reason": "meta-query" if is_meta_query else ("has-filters" if has_query_filters else "no-filters"),
                "documents_found": len(docs)
            }
        }
    }


def _merge_filters_with_preferences(
    llm_filters: Dict[str, Any],
    pref_topics: List[str],
    pref_orgs: List[str],
    pref_people: List[str]
) -> Dict[str, Any]:
    """Merge LLM-extracted filters with user preferences.
    
    Strategy:
    - LLM filters take priority when they contain specific entities
    - User preferences augment LLM filters to improve relevance
    - Both are treated as relevance signals, not hard constraints
    - If LLM found specific entities, add user prefs as secondary signals
    - If LLM found nothing, user prefs become primary signals
    """
    merged = llm_filters.copy()
    
    # Combine topics: LLM topics + user preference topics (deduplicated)
    llm_topics = set(t.lower() for t in llm_filters.get("topics", []))
    pref_topics_lower = set(t.lower() for t in pref_topics)
    
    # Union of both sets, but preserve original casing
    all_topics = list(llm_filters.get("topics", []))
    for pref_topic in pref_topics:
        if pref_topic.lower() not in llm_topics:
            all_topics.append(pref_topic)
    
    merged["topics"] = all_topics
    
    # Combine organisations
    llm_orgs = set(o.lower() for o in llm_filters.get("organisations", []))
    all_orgs = list(llm_filters.get("organisations", []))
    for pref_org in pref_orgs:
        if pref_org.lower() not in llm_orgs:
            all_orgs.append(pref_org)
    
    merged["organisations"] = all_orgs
    
    # Combine people
    llm_people = set(p.lower() for p in llm_filters.get("people", []))
    all_people = list(llm_filters.get("people", []))
    for pref_person in pref_people:
        if pref_person.lower() not in llm_people:
            all_people.append(pref_person)
    
    merged["people"] = all_people
    
    # Category filter is explicit and should be the primary filter
    # When category is specified, don't add user preferences unless the user explicitly mentioned entities
    if merged.get("category"):
        # Check if user explicitly mentioned any entities in their query
        has_explicit_filters = (
            len(llm_filters.get("topics", [])) > 0 or
            len(llm_filters.get("organisations", [])) > 0 or
            len(llm_filters.get("people", [])) > 0
        )
        
        if not has_explicit_filters:
            # No explicit entities mentioned - category is the only filter
            # Clear out user preferences to avoid false negatives
            log.info("Category-only query detected - clearing user preferences to avoid over-filtering")
            merged["topics"] = []
            merged["organisations"] = []
            merged["people"] = []
        else:
            # User mentioned specific entities along with category
            # Keep explicit filters, but don't add many preferences
            max_pref_additions = 3
            if len(all_topics) > len(llm_filters.get("topics", [])) + max_pref_additions:
                merged["topics"] = llm_filters.get("topics", []) + pref_topics[:max_pref_additions]
            if len(all_orgs) > len(llm_filters.get("organisations", [])) + max_pref_additions:
                merged["organisations"] = llm_filters.get("organisations", []) + pref_orgs[:max_pref_additions]
            if len(all_people) > len(llm_filters.get("people", [])) + max_pref_additions:
                merged["people"] = llm_filters.get("people", []) + pref_people[:max_pref_additions]
    else:
        # No category specified - use all preferences to improve relevance
        # If we now have many filters due to preferences, increase limit
        # to ensure we get good coverage
        total_filters = len(merged["topics"]) + len(merged["organisations"]) + len(merged["people"])
        if total_filters > 10 and merged.get("limit", 20) < 30:
            merged["limit"] = 30
    
    return merged


def _format_documents_for_response(
    docs: List[Dict[str, Any]],
    max_topics_per_doc: int = 10
) -> List[Dict[str, Any]]:
    """Format documents for API response, limiting topic display for readability."""
    formatted = []
    for doc in docs:
        topics = doc.get("topics", [])
        formatted_doc = doc.copy()
        
        # Limit topics if there are too many
        if len(topics) > max_topics_per_doc:
            formatted_doc["topics"] = topics[:max_topics_per_doc]
            formatted_doc["topics_truncated"] = True
            formatted_doc["total_topics"] = len(topics)
        else:
            formatted_doc["topics_truncated"] = False
            formatted_doc["total_topics"] = len(topics)
        
        formatted.append(formatted_doc)
    
    return formatted
