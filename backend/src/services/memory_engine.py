import json
from datetime import datetime, timedelta
from src.services.postgres import fetchall, fetchone

"""
Memory Engine for Aurora

This module provides:
- Retrieval of recent user queries
- Retrieval of feedback signals (ratings, comments)
- Extraction of memory topics and organisations from past behaviour
- A summarised memory context injected into the LLM prompt
- A lightweight long-term memory mechanism
"""


# -----------------------------------------------
# 1. Fetch recent query history
# -----------------------------------------------
def get_recent_queries(user_id, limit=10):
    sql = """
        SELECT id, question, filters, documents, answer, created_at
        FROM query_logs
        WHERE user_id = %s
        ORDER BY created_at DESC
        LIMIT %s;
    """
    rows = fetchall(sql, [user_id, limit])
    return rows or []


# -----------------------------------------------
# 2. Fetch user feedback signals
# -----------------------------------------------
def get_recent_feedback(user_id, limit=20):
    sql = """
        SELECT qf.rating, qf.comments, qf.created_at, ql.question
        FROM query_feedback qf
        JOIN query_logs ql ON qf.query_id = ql.id
        WHERE qf.user_id = %s
        ORDER BY qf.created_at DESC
        LIMIT %s;
    """
    rows = fetchall(sql, [user_id, limit])
    return rows or []


# -----------------------------------------------
# 3. Extract memory: topics, organisations, people
# -----------------------------------------------
def extract_memory_signals(recent_queries):
    memory_topics = set()
    memory_orgs = set()
    memory_people = set()

    for q in recent_queries:
        try:
            filters = q.get("filters")
            if isinstance(filters, str):
                filters = json.loads(filters)

            if isinstance(filters, dict):
                for t in filters.get("topics", []):
                    memory_topics.add(t)
                for o in filters.get("organisations", []):
                    memory_orgs.add(o)
                for p in filters.get("people", []):
                    memory_people.add(p)
        except Exception:
            continue

    return {
        "memory_topics": list(memory_topics),
        "memory_orgs": list(memory_orgs),
        "memory_people": list(memory_people)
    }


# -----------------------------------------------
# 4. Build overall memory context
# -----------------------------------------------
def build_memory_context(user_id, filters):
    recent_queries = get_recent_queries(user_id)
    feedback = get_recent_feedback(user_id)

    signals = extract_memory_signals(recent_queries)

    # lightweight long-term preferences summarisation
    longterm_pref = summarise_longterm_preferences(signals, feedback)

    return {
        "recent_queries": recent_queries,
        "recent_feedback": feedback,
        "memory_signals": signals,
        "longterm_summary": longterm_pref,
    }


# -----------------------------------------------
# 5. Lightweight LLM-driven long-term preference summary
# (optional but very useful)
# -----------------------------------------------
def summarise_longterm_preferences(memory_signals, feedback):
    """
    This is intentionally lightweight.
    A proper summarisation step will be handled by the LLM
    (we pass this into the prompt).
    """
    avg_rating = None
    if feedback:
        ratings = [f["rating"] for f in feedback if f.get("rating")]
        if ratings:
            avg_rating = sum(ratings) / len(ratings)

    return {
        "common_topics": memory_signals.get("memory_topics", []),
        "common_orgs": memory_signals.get("memory_orgs", []),
        "feedback_count": len(feedback),
        "average_rating": avg_rating,
    }
    