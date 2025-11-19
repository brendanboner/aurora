from typing import Any, Dict, List

from src.services.llm_service import parse_query_to_filters, summarise_documents
from src.services.graph_service import query_documents_from_filters



def run_query(user_id: int, question: str) -> Dict[str, Any]:
    """
    Full pipeline:
      1) LLM parses the question into filters
      2) Query Neo4j for matching documents
      3) LLM summarises the documents
    User preferences from Postgres can be added later using user_id.
    """
    filters = parse_query_to_filters(question)
    docs = query_documents_from_filters(filters)
    answer = summarise_documents(question, docs)

    return {
        "answer": answer,
        "filters": filters,
        "documents": docs,
    }
