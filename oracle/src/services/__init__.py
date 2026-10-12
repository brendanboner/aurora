"""Oracle Service - Services module.

Phase 1 Components:
- query_router: Intent classification and routing
- query_parser: Entity and filter extraction
- keyword_retriever: Neo4j keyword-based retrieval
- context_builder: Graph context assembly
- response_generator: Mode-based response formatting
- llm_client: Azure OpenAI integration

Phase 2 Components:
- vector_retriever: Semantic similarity search using embeddings
- hybrid_search: Combined keyword + vector retrieval with RRF
- entity_resolver: Resolve entity mentions against the knowledge graph

Phase 3 Components:
- graph_retriever: Graph-native queries for relationship-aware retrieval
"""

from src.services.query_router import QueryRouter
from src.services.query_parser import QueryParser
from src.services.keyword_retriever import KeywordRetriever
from src.services.vector_retriever import VectorRetriever
from src.services.graph_retriever import GraphRetriever, graph_search
from src.services.hybrid_search import HybridSearch, reciprocal_rank_fusion
from src.services.entity_resolver import EntityResolver, resolve_entities
from src.services.context_builder import ContextBuilder
from src.services.response_generator import ResponseGenerator
from src.services.llm_client import get_llm_client, call_llm, generate_embedding

__all__ = [
    "QueryRouter",
    "QueryParser",
    "KeywordRetriever",
    "VectorRetriever",
    "GraphRetriever",
    "graph_search",
    "HybridSearch",
    "reciprocal_rank_fusion",
    "EntityResolver",
    "resolve_entities",
    "ContextBuilder",
    "ResponseGenerator",
    "get_llm_client",
    "call_llm",
    "generate_embedding",
]
