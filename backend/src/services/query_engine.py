from typing import Any, Dict, List
import logging

from src.services.llm_service import parse_query_to_filters, summarise_documents
from src.services.graph_service import query_documents_from_filters
from src.services import postgres

log = logging.getLogger("query_engine")


def run_query(user_id: int, question: str) -> Dict[str, Any]:
    """Full question-answering pipeline:
    
    1. Accept a question and user_id
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
        log.info(f"User preferences loaded: {len(pref_topics)} topics, {len(pref_orgs)} orgs, {len(pref_people)} people")
    else:
        log.info("No user preferences found - using query-based filters only")
    
    # Step 2: Parse question with LLM to extract filters
    llm_filters = parse_query_to_filters(question)
    log.info(f"LLM filters: {llm_filters}")
    
    # Step 3: Merge LLM filters with user preferences
    # User preferences act as relevance signals, not strict filters
    # If LLM detected specific entities, prioritize those
    # If LLM filters are empty or generic, boost with user preferences
    merged_filters = _merge_filters_with_preferences(
        llm_filters=llm_filters,
        pref_topics=pref_topics,
        pref_orgs=pref_orgs,
        pref_people=pref_people
    )
    
    log.info(f"Merged filters: {merged_filters}")
    
    # Step 4: Query Neo4j with merged filters
    docs = query_documents_from_filters(merged_filters)
    log.info(f"Retrieved {len(docs)} documents from knowledge graph")
    
    if not docs:
        log.warning("No documents found matching query and filters")
    
    # Step 5: Summarize documents with LLM, incorporating user preferences
    user_pref_context = {
        "topics": pref_topics,
        "organisations": pref_orgs,
        "people": pref_people
    } if has_preferences else None
    
    answer = summarise_documents(question, docs, user_pref_context)
    
    # Step 6: Prepare response with limited topic display for users with many preferences
    formatted_docs = _format_documents_for_response(docs, max_topics_per_doc=10)
    
    return {
        "answer": answer,
        "filters": {
            "applied": merged_filters,
            "from_query": llm_filters,
            "from_preferences": {
                "topics": pref_topics,
                "organisations": pref_orgs,
                "people": pref_people
            } if has_preferences else None
        },
        "documents": formatted_docs,
        "document_count": len(docs)
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
