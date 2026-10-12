"""Hybrid Search - Combines keyword, vector, and graph retrieval with Reciprocal Rank Fusion.

This module implements hybrid search that combines results from multiple retrieval
strategies (keyword search, vector similarity, and graph traversal) using Reciprocal 
Rank Fusion (RRF) to produce a unified ranking.

Phase 2 of Oracle Service implementation (vector search).
Phase 3 enhancement: Graph retriever integration.
Phase 4 enhancement: Parallel retrieval with asyncio.gather.
"""

import asyncio
from dataclasses import dataclass
import logging
from typing import Optional
from datetime import datetime, timedelta, timezone

from src.models.response import Document, QueryIntent
from src.services.keyword_retriever import KeywordRetriever, RetrievalResult
from src.services.vector_retriever import VectorRetriever, VectorSearchResult
from src.services.graph_retriever import GraphRetriever, GraphSearchResult
from src.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class HybridSearchResult:
    """Result of hybrid search combining multiple retrieval strategies."""
    documents: list[Document]
    total_candidates: int
    strategies_used: list[str]
    keyword_candidates: int
    vector_candidates: int
    graph_candidates: int = 0
    graph_data: Optional[dict] = None  # Additional graph context from graph retriever


@dataclass
class RankedDocument:
    """Document with ranking information from RRF."""
    document: Document
    rrf_score: float
    keyword_rank: Optional[int]
    vector_rank: Optional[int]
    sources: list[str]  # Which retrievers found this document


def reciprocal_rank_fusion(
    ranked_lists: list[list[Document]],
    list_weights: list[float] = None,
    list_names: list[str] = None,
    k: int = 60,
) -> list[RankedDocument]:
    """
    Combine ranked lists using Reciprocal Rank Fusion (RRF).
    
    RRF is a simple but effective method for combining ranked lists without
    requiring score normalization. It's particularly useful when combining
    results from different retrieval methods (keyword vs. semantic vs. graph).
    
    Formula: RRF(d) = Σ (weight_i / (k + rank_i(d)))
    
    Args:
        ranked_lists: List of ranked document lists from different retrievers
        list_weights: Optional weights for each list (default: equal weights)
        list_names: Optional names for each list (for tracking sources)
        k: RRF constant (higher = more equal weighting, default: 60)
        
    Returns:
        List of RankedDocument sorted by RRF score (highest first)
    """
    if not ranked_lists:
        return []
    
    # Default to equal weights if not specified
    if list_weights is None:
        list_weights = [1.0] * len(ranked_lists)
    
    # Ensure we have weights for all lists
    while len(list_weights) < len(ranked_lists):
        list_weights.append(1.0)
    
    # Default list names
    if list_names is None:
        list_names = ["keyword", "vector", "graph"]
    
    # Track scores and ranking info for each unique document
    doc_scores: dict[str, float] = {}
    doc_info: dict[str, dict] = {}  # url -> {document, keyword_rank, vector_rank, graph_rank, sources}
    
    # Process each ranked list
    for list_idx, ranked_list in enumerate(ranked_lists):
        weight = list_weights[list_idx]
        source_name = list_names[list_idx] if list_idx < len(list_names) else f"source_{list_idx}"
        
        for rank, doc in enumerate(ranked_list, start=1):
            url = doc.url
            
            # Calculate RRF contribution: weight / (k + rank)
            rrf_contribution = weight / (k + rank)
            
            # Update score
            if url in doc_scores:
                doc_scores[url] += rrf_contribution
            else:
                doc_scores[url] = rrf_contribution
            
            # Track document info
            if url not in doc_info:
                doc_info[url] = {
                    "document": doc,
                    "keyword_rank": None,
                    "vector_rank": None,
                    "graph_rank": None,
                    "sources": [],
                }
            
            # Update rank info based on source
            if source_name == "keyword":
                doc_info[url]["keyword_rank"] = rank
            elif source_name == "vector":
                doc_info[url]["vector_rank"] = rank
            elif source_name == "graph":
                doc_info[url]["graph_rank"] = rank
            
            if source_name not in doc_info[url]["sources"]:
                doc_info[url]["sources"].append(source_name)
    
    # Sort by RRF score and create result list
    sorted_urls = sorted(doc_scores.keys(), key=lambda u: doc_scores[u], reverse=True)
    
    # Normalize RRF scores to [0, 1] range
    # RRF scores are typically small (max ~0.05 for a single list, ~0.15 for 3 lists)
    # We normalize by dividing by the max score to get relative rankings
    max_score = max(doc_scores.values()) if doc_scores else 1.0
    min_score = min(doc_scores.values()) if doc_scores else 0.0
    score_range = max_score - min_score if max_score > min_score else 1.0
    
    results = []
    for url in sorted_urls:
        info = doc_info[url]
        
        # Create merged document with normalized relevance score
        merged_doc = info["document"].model_copy()
        
        # Normalize to [0.3, 1.0] range - even lowest ranked doc gets 0.3
        # This provides more meaningful scores for display
        raw_score = doc_scores[url]
        if score_range > 0:
            normalized = 0.3 + 0.7 * ((raw_score - min_score) / score_range)
        else:
            normalized = 0.65  # Single document gets middle score
        merged_doc.relevance_score = round(normalized, 3)
        
        # Update match reasons to reflect fusion
        match_reasons = []
        if info["keyword_rank"]:
            match_reasons.append(f"Keyword match (rank #{info['keyword_rank']})")
        if info["vector_rank"]:
            match_reasons.append(f"Semantic match (rank #{info['vector_rank']})")
        if info["graph_rank"]:
            match_reasons.append(f"Graph traversal (rank #{info['graph_rank']})")
        merged_doc.match_reasons = match_reasons
        
        results.append(RankedDocument(
            document=merged_doc,
            rrf_score=doc_scores[url],
            keyword_rank=info["keyword_rank"],
            vector_rank=info["vector_rank"],
            sources=info["sources"],
        ))
    
    return results


def apply_recency_boost(
    documents: list[Document],
    boost_days: int = None,
    boost_factor: float = None,
) -> list[Document]:
    """
    Apply a recency boost to document relevance scores.
    
    Documents published within the boost window receive a score multiplier.
    
    Args:
        documents: List of documents to boost
        boost_days: Number of days for the recency window (default from settings)
        boost_factor: Multiplier for recent documents (default from settings)
        
    Returns:
        Documents with boosted scores (maintains original order)
    """
    boost_days = boost_days or settings.recency_boost_days
    boost_factor = boost_factor or settings.recency_boost_factor
    
    if not settings.recency_boost_enabled:
        return documents
    
    # Use timezone-aware datetime to match Neo4j ISO dates with timezone info
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=boost_days)
    
    boosted_docs = []
    for doc in documents:
        boosted_doc = doc.model_copy()
        
        if doc.publish_date:
            try:
                # Parse publish date
                if isinstance(doc.publish_date, str):
                    pub_date = datetime.fromisoformat(doc.publish_date.replace("Z", "+00:00"))
                else:
                    pub_date = doc.publish_date
                
                # Ensure timezone-aware for comparison
                if pub_date.tzinfo is None:
                    pub_date = pub_date.replace(tzinfo=timezone.utc)
                
                # Apply boost if recent
                if pub_date >= cutoff_date:
                    original_score = boosted_doc.relevance_score
                    boosted_doc.relevance_score = min(original_score * boost_factor, 1.0)
                    
                    if boosted_doc.relevance_score > original_score:
                        boosted_doc.match_reasons = boosted_doc.match_reasons + ["Recent publication boost"]
                        
            except (ValueError, TypeError) as e:
                logger.debug(f"Could not parse publish date for recency boost: {e}")
        
        boosted_docs.append(boosted_doc)
    
    return boosted_docs


class HybridSearch:
    """
    Combines keyword, vector, and graph retrieval for improved search quality.
    
    The hybrid approach addresses limitations of each method:
    - Keyword search: Misses conceptual matches, sensitive to typos
    - Vector search: May miss exact matches, less precise for entity names
    - Graph search: Leverages relationships for context-aware retrieval
    
    By combining all three with RRF, we get robust retrieval that handles
    exact matches, semantic similarity, and relationship-based context.
    """
    
    def __init__(self):
        self.keyword_retriever = KeywordRetriever()
        self.vector_retriever = VectorRetriever()
        self.graph_retriever = GraphRetriever()
    
    async def search(
        self,
        query: str,
        filters: dict,
        intent: QueryIntent,
        max_results: int = 20,
        enable_vector: bool = None,
        enable_keyword: bool = True,
        enable_graph: bool = None,
    ) -> HybridSearchResult:
        """
        Execute hybrid search combining keyword, vector, and graph retrieval.
        
        Phase 4: Uses asyncio.gather for parallel retrieval when enabled,
        significantly reducing latency by running retrievers concurrently.
        
        Args:
            query: User's natural language query
            filters: Parsed filters from query
            intent: Classified query intent
            max_results: Maximum final results to return
            enable_vector: Whether to use vector search (default from settings)
            enable_keyword: Whether to use keyword search (default: True)
            enable_graph: Whether to use graph search (default from settings)
            
        Returns:
            HybridSearchResult with fused document rankings
        """
        enable_vector = enable_vector if enable_vector is not None else settings.vector_search_enabled
        enable_graph = enable_graph if enable_graph is not None else settings.graph_search_enabled
        
        # Fetch more candidates from each retriever for better fusion
        pool_size = max_results * settings.retrieval_pool_multiplier
        
        # Phase 4: Use parallel retrieval if enabled
        if settings.parallel_retrieval_enabled:
            return await self._parallel_search(
                query=query,
                filters=filters,
                intent=intent,
                pool_size=pool_size,
                max_results=max_results,
                enable_keyword=enable_keyword,
                enable_vector=enable_vector,
                enable_graph=enable_graph,
            )
        else:
            return await self._sequential_search(
                query=query,
                filters=filters,
                intent=intent,
                pool_size=pool_size,
                max_results=max_results,
                enable_keyword=enable_keyword,
                enable_vector=enable_vector,
                enable_graph=enable_graph,
            )
    
    async def _parallel_search(
        self,
        query: str,
        filters: dict,
        intent: QueryIntent,
        pool_size: int,
        max_results: int,
        enable_keyword: bool,
        enable_vector: bool,
        enable_graph: bool,
    ) -> HybridSearchResult:
        """
        Execute retrieval strategies in parallel using asyncio.gather.
        
        This significantly reduces latency by running all enabled retrievers
        concurrently instead of sequentially.
        """
        tasks = []
        task_names = []
        
        # Create retrieval tasks for enabled strategies
        if enable_keyword:
            tasks.append(self._safe_keyword_retrieve(query, filters, intent, pool_size))
            task_names.append("keyword")
        
        if enable_vector and settings.hybrid_search_enabled:
            tasks.append(self._safe_vector_retrieve(query, filters, intent, pool_size))
            task_names.append("vector")
        
        if enable_graph and settings.graph_search_enabled:
            tasks.append(self._safe_graph_retrieve(query, filters, intent, pool_size))
            task_names.append("graph")
        
        if not tasks:
            logger.warning("No retrieval strategies enabled")
            return HybridSearchResult(
                documents=[],
                total_candidates=0,
                strategies_used=[],
                keyword_candidates=0,
                vector_candidates=0,
                graph_candidates=0,
                graph_data=None,
            )
        
        # Execute all retrievers in parallel with timeout
        logger.info(f"Executing parallel retrieval with strategies: {task_names}")
        try:
            results = await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=settings.retrieval_timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"Parallel retrieval timed out after {settings.retrieval_timeout}s")
            results = [None] * len(tasks)
        
        # Process results
        return self._process_retrieval_results(
            results=results,
            task_names=task_names,
            max_results=max_results,
        )
    
    async def _safe_keyword_retrieve(
        self,
        query: str,
        filters: dict,
        intent: QueryIntent,
        pool_size: int,
    ) -> Optional[RetrievalResult]:
        """Execute keyword retrieval with error handling."""
        try:
            return await self.keyword_retriever.retrieve(
                query=query,
                filters=filters,
                intent=intent,
                max_results=pool_size,
            )
        except Exception as e:
            logger.error(f"Keyword retrieval failed: {e}")
            return None
    
    async def _safe_vector_retrieve(
        self,
        query: str,
        filters: dict,
        intent: QueryIntent,
        pool_size: int,
    ) -> Optional[VectorSearchResult]:
        """Execute vector retrieval with error handling."""
        try:
            return await self.vector_retriever.retrieve(
                query=query,
                filters=filters,
                intent=intent,
                max_results=pool_size,
            )
        except Exception as e:
            logger.error(f"Vector retrieval failed: {e}")
            return None
    
    async def _safe_graph_retrieve(
        self,
        query: str,
        filters: dict,
        intent: QueryIntent,
        pool_size: int,
    ) -> Optional[GraphSearchResult]:
        """Execute graph retrieval with error handling."""
        try:
            return await self.graph_retriever.retrieve(
                query=query,
                filters=filters,
                intent=intent,
                max_results=pool_size,
            )
        except Exception as e:
            logger.error(f"Graph retrieval failed: {e}")
            return None
    
    def _process_retrieval_results(
        self,
        results: list,
        task_names: list[str],
        max_results: int,
    ) -> HybridSearchResult:
        """Process results from parallel retrieval."""
        strategies_used = []
        ranked_lists = []
        list_weights = []
        list_names = []
        keyword_candidates = 0
        vector_candidates = 0
        graph_candidates = 0
        graph_data = None
        
        for name, result in zip(task_names, results):
            # Skip failed or empty results
            if result is None or isinstance(result, Exception):
                if isinstance(result, Exception):
                    logger.error(f"{name} retrieval raised exception: {result}")
                continue
            
            if name == "keyword" and isinstance(result, RetrievalResult):
                if result.documents:
                    ranked_lists.append(result.documents)
                    list_weights.append(settings.keyword_weight)
                    list_names.append("keyword")
                    strategies_used.append("keyword")
                    keyword_candidates = result.total_candidates
                    logger.info(f"Keyword retrieval returned {len(result.documents)} documents")
            
            elif name == "vector" and isinstance(result, VectorSearchResult):
                if result.documents:
                    ranked_lists.append(result.documents)
                    list_weights.append(settings.vector_weight)
                    list_names.append("vector")
                    strategies_used.append("vector")
                    vector_candidates = result.total_candidates
                    logger.info(f"Vector retrieval returned {len(result.documents)} documents")
            
            elif name == "graph" and isinstance(result, GraphSearchResult):
                if result.documents:
                    ranked_lists.append(result.documents)
                    list_weights.append(settings.graph_weight)
                    list_names.append("graph")
                    strategies_used.append("graph")
                    graph_candidates = result.total_candidates
                    graph_data = result.graph_data
                    logger.info(f"Graph retrieval ({result.query_pattern}) returned {len(result.documents)} documents")
        
        # Handle case where no results from any retriever
        if not ranked_lists:
            logger.warning("No results from any retrieval strategy")
            return HybridSearchResult(
                documents=[],
                total_candidates=0,
                strategies_used=[],
                keyword_candidates=0,
                vector_candidates=0,
                graph_candidates=0,
                graph_data=None,
            )
        
        # Apply Reciprocal Rank Fusion if we have multiple result sets
        if len(ranked_lists) > 1:
            fused_results = reciprocal_rank_fusion(
                ranked_lists=ranked_lists,
                list_weights=list_weights,
                list_names=list_names,
                k=settings.rrf_k,
            )
            documents = [r.document for r in fused_results]
            logger.info(f"RRF fusion produced {len(documents)} unique documents from {len(strategies_used)} strategies")
        else:
            # Single retriever, just use its results
            documents = ranked_lists[0]
        
        # Apply recency boost
        documents = apply_recency_boost(documents)
        
        # Re-sort by score after boost and limit results
        documents.sort(key=lambda d: d.relevance_score, reverse=True)
        documents = documents[:max_results]
        
        total_candidates = keyword_candidates + vector_candidates + graph_candidates
        
        return HybridSearchResult(
            documents=documents,
            total_candidates=total_candidates,
            strategies_used=strategies_used,
            keyword_candidates=keyword_candidates,
            vector_candidates=vector_candidates,
            graph_candidates=graph_candidates,
            graph_data=graph_data,
        )
    
    async def _sequential_search(
        self,
        query: str,
        filters: dict,
        intent: QueryIntent,
        pool_size: int,
        max_results: int,
        enable_keyword: bool,
        enable_vector: bool,
        enable_graph: bool,
    ) -> HybridSearchResult:
        """
        Execute retrieval strategies sequentially (legacy behavior).
        
        Kept for backward compatibility and debugging.
        """
        strategies_used = []
        ranked_lists = []
        list_weights = []
        list_names = []
        keyword_candidates = 0
        vector_candidates = 0
        graph_candidates = 0
        graph_data = None
        
        # Execute keyword retrieval
        if enable_keyword:
            try:
                keyword_result = await self.keyword_retriever.retrieve(
                    query=query,
                    filters=filters,
                    intent=intent,
                    max_results=pool_size,
                )
                
                if keyword_result.documents:
                    ranked_lists.append(keyword_result.documents)
                    list_weights.append(settings.keyword_weight)
                    list_names.append("keyword")
                    strategies_used.append("keyword")
                    keyword_candidates = keyword_result.total_candidates
                    
                logger.info(f"Keyword retrieval returned {len(keyword_result.documents)} documents")
                
            except Exception as e:
                logger.error(f"Keyword retrieval failed: {e}")
        
        # Execute vector retrieval
        if enable_vector and settings.hybrid_search_enabled:
            try:
                vector_result = await self.vector_retriever.retrieve(
                    query=query,
                    filters=filters,
                    intent=intent,
                    max_results=pool_size,
                )
                
                if vector_result.documents:
                    ranked_lists.append(vector_result.documents)
                    list_weights.append(settings.vector_weight)
                    list_names.append("vector")
                    strategies_used.append("vector")
                    vector_candidates = vector_result.total_candidates
                    
                logger.info(f"Vector retrieval returned {len(vector_result.documents)} documents")
                
            except Exception as e:
                logger.error(f"Vector retrieval failed: {e}")
        
        # Execute graph retrieval
        if enable_graph and settings.graph_search_enabled:
            try:
                graph_result = await self.graph_retriever.retrieve(
                    query=query,
                    filters=filters,
                    intent=intent,
                    max_results=pool_size,
                )
                
                if graph_result.documents:
                    ranked_lists.append(graph_result.documents)
                    list_weights.append(settings.graph_weight)
                    list_names.append("graph")
                    strategies_used.append("graph")
                    graph_candidates = graph_result.total_candidates
                    graph_data = graph_result.graph_data
                    
                logger.info(f"Graph retrieval ({graph_result.query_pattern}) returned {len(graph_result.documents)} documents")
                
            except Exception as e:
                logger.error(f"Graph retrieval failed: {e}")
        
        # Handle case where no results from any retriever
        if not ranked_lists:
            logger.warning("No results from any retrieval strategy")
            return HybridSearchResult(
                documents=[],
                total_candidates=0,
                strategies_used=[],
                keyword_candidates=0,
                vector_candidates=0,
                graph_candidates=0,
                graph_data=None,
            )
        
        # Apply Reciprocal Rank Fusion if we have multiple result sets
        if len(ranked_lists) > 1:
            fused_results = reciprocal_rank_fusion(
                ranked_lists=ranked_lists,
                list_weights=list_weights,
                list_names=list_names,
                k=settings.rrf_k,
            )
            documents = [r.document for r in fused_results]
            logger.info(f"RRF fusion produced {len(documents)} unique documents from {len(strategies_used)} strategies")
        else:
            # Single retriever, just use its results
            documents = ranked_lists[0]
        
        # Apply recency boost
        documents = apply_recency_boost(documents)
        
        # Re-sort by score after boost and limit results
        documents.sort(key=lambda d: d.relevance_score, reverse=True)
        documents = documents[:max_results]
        
        total_candidates = keyword_candidates + vector_candidates + graph_candidates
        
        return HybridSearchResult(
            documents=documents,
            total_candidates=total_candidates,
            strategies_used=strategies_used,
            keyword_candidates=keyword_candidates,
            vector_candidates=vector_candidates,
            graph_candidates=graph_candidates,
            graph_data=graph_data,
        )


# Convenience function for simple usage
async def hybrid_search(
    query: str,
    filters: dict = None,
    intent: QueryIntent = QueryIntent.TOPIC_DISCOVERY,
    max_results: int = 20,
) -> list[Document]:
    """
    Convenience function for hybrid search.
    
    Args:
        query: Search query
        filters: Optional filters
        intent: Query intent (default: topic_discovery)
        max_results: Maximum results
        
    Returns:
        List of ranked documents
    """
    searcher = HybridSearch()
    result = await searcher.search(
        query=query,
        filters=filters or {},
        intent=intent,
        max_results=max_results,
    )
    return result.documents
