"""Re-ranking Service - Rank document chunks by query relevance.

This module provides functionality to re-rank document chunks using vector
similarity to identify the most relevant passages for a given query.

Phase 5 of Oracle Service implementation (Enhanced Answers).
"""

import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import numpy as np

from src.services.chunking import TextChunk, ChunkedDocument
from src.services.llm_client import generate_embedding, batch_generate_embeddings
from src.settings import settings

logger = logging.getLogger(__name__)

# Re-ranking configuration
DEFAULT_TOP_K = 15  # Maximum chunks to return for LLM context
MAX_CONTEXT_TOKENS = 7500  # Maximum total tokens for context (leaving room for prompt/response)


@dataclass
class RankedChunk:
    """A chunk with its relevance score."""
    chunk: TextChunk
    score: float
    rank: int
    

@dataclass
class ReRankingResult:
    """Result of re-ranking operation."""
    chunks: list[RankedChunk]
    total_chunks_considered: int
    total_tokens: int
    query_embedding_generated: bool


def cosine_similarity(vec1: list[float], vec2: list[float]) -> float:
    """Calculate cosine similarity between two vectors."""
    a = np.array(vec1)
    b = np.array(vec2)
    
    dot_product = np.dot(a, b)
    norm_a = np.linalg.norm(a)
    norm_b = np.linalg.norm(b)
    
    if norm_a == 0 or norm_b == 0:
        return 0.0
    
    return float(dot_product / (norm_a * norm_b))


async def rerank_chunks(
    query: str,
    chunks: list[TextChunk],
    top_k: int = DEFAULT_TOP_K,
    max_tokens: int = MAX_CONTEXT_TOKENS,
) -> ReRankingResult:
    """
    Re-rank chunks by their relevance to the query using vector similarity.
    
    Args:
        query: The user's question
        chunks: List of TextChunk objects to rank
        top_k: Maximum number of chunks to return
        max_tokens: Maximum total tokens to include
        
    Returns:
        ReRankingResult with ranked chunks
    """
    if not chunks:
        return ReRankingResult(
            chunks=[],
            total_chunks_considered=0,
            total_tokens=0,
            query_embedding_generated=False,
        )
    
    try:
        # Generate query embedding
        logger.info(f"Generating embedding for reranking query: {query[:50]}...")
        query_embedding = await generate_embedding(query)
        
        if not query_embedding:
            logger.warning("Failed to generate query embedding for reranking")
            return ReRankingResult(
                chunks=[],
                total_chunks_considered=len(chunks),
                total_tokens=0,
                query_embedding_generated=False,
            )
        
        # Generate embeddings for all chunks in batches
        chunk_texts = [chunk.text for chunk in chunks]
        logger.info(f"Generating embeddings for {len(chunk_texts)} chunks...")
        chunk_embeddings = await batch_generate_embeddings(chunk_texts)
        
        if not chunk_embeddings or len(chunk_embeddings) != len(chunks):
            logger.warning("Failed to generate chunk embeddings for reranking")
            # Fall back to returning chunks in original order
            return _fallback_ranking(chunks, top_k, max_tokens)
        
        # Calculate similarity scores
        scored_chunks = []
        for chunk, embedding in zip(chunks, chunk_embeddings):
            if embedding:
                score = cosine_similarity(query_embedding, embedding)
            else:
                score = 0.0
            scored_chunks.append((chunk, score))
        
        # Sort by score (highest first)
        scored_chunks.sort(key=lambda x: x[1], reverse=True)
        
        # Select top chunks while respecting token limit
        selected_chunks = []
        total_tokens = 0
        
        for rank, (chunk, score) in enumerate(scored_chunks, start=1):
            if len(selected_chunks) >= top_k:
                break
            if total_tokens + chunk.token_count > max_tokens:
                # Try to fit smaller chunks
                continue
            
            selected_chunks.append(RankedChunk(
                chunk=chunk,
                score=score,
                rank=rank,
            ))
            total_tokens += chunk.token_count
        
        logger.info(
            f"Reranking complete: selected {len(selected_chunks)} chunks "
            f"({total_tokens} tokens) from {len(chunks)} candidates"
        )
        
        return ReRankingResult(
            chunks=selected_chunks,
            total_chunks_considered=len(chunks),
            total_tokens=total_tokens,
            query_embedding_generated=True,
        )
        
    except Exception as e:
        logger.error(f"Reranking failed: {e}")
        return _fallback_ranking(chunks, top_k, max_tokens)


def _fallback_ranking(
    chunks: list[TextChunk],
    top_k: int,
    max_tokens: int,
) -> ReRankingResult:
    """Fallback ranking when embedding generation fails - use original order."""
    selected_chunks = []
    total_tokens = 0
    
    for rank, chunk in enumerate(chunks[:top_k * 2], start=1):
        if len(selected_chunks) >= top_k:
            break
        if total_tokens + chunk.token_count > max_tokens:
            continue
        
        selected_chunks.append(RankedChunk(
            chunk=chunk,
            score=1.0 - (rank * 0.01),  # Decreasing score by position
            rank=rank,
        ))
        total_tokens += chunk.token_count
    
    return ReRankingResult(
        chunks=selected_chunks,
        total_chunks_considered=len(chunks),
        total_tokens=total_tokens,
        query_embedding_generated=False,
    )


async def rerank_documents(
    query: str,
    chunked_documents: list[ChunkedDocument],
    top_k: int = DEFAULT_TOP_K,
    max_tokens: int = MAX_CONTEXT_TOKENS,
) -> ReRankingResult:
    """
    Re-rank chunks from multiple documents.
    
    Flattens all chunks and ranks them together to find the most
    relevant passages across all documents.
    
    Args:
        query: The user's question
        chunked_documents: List of ChunkedDocument objects
        top_k: Maximum chunks to return
        max_tokens: Maximum total tokens
        
    Returns:
        ReRankingResult with ranked chunks from any document
    """
    # Flatten all chunks
    all_chunks = []
    for doc in chunked_documents:
        all_chunks.extend(doc.chunks)
    
    logger.info(f"Reranking {len(all_chunks)} chunks from {len(chunked_documents)} documents")
    
    return await rerank_chunks(query, all_chunks, top_k, max_tokens)


def group_chunks_by_document(
    ranked_chunks: list[RankedChunk],
) -> dict[str, list[RankedChunk]]:
    """
    Group ranked chunks by their source document URL.
    
    Useful for organizing chunks by document for display.
    """
    grouped = {}
    for rc in ranked_chunks:
        url = rc.chunk.source_url
        if url not in grouped:
            grouped[url] = []
        grouped[url].append(rc)
    
    return grouped


def format_chunks_for_llm(
    ranked_chunks: list[RankedChunk],
    include_source: bool = True,
) -> str:
    """
    Format ranked chunks as context for LLM prompt.
    
    Args:
        ranked_chunks: List of RankedChunk objects (already sorted by relevance)
        include_source: Whether to include source attribution
        
    Returns:
        Formatted string suitable for LLM context
    """
    if not ranked_chunks:
        return ""
    
    parts = []
    
    # Group by document for cleaner presentation
    grouped = group_chunks_by_document(ranked_chunks)
    
    doc_num = 1
    for url, chunks in grouped.items():
        # Get title from first chunk
        title = chunks[0].chunk.source_title or "Untitled Document"
        
        if include_source:
            parts.append(f"\n--- Document {doc_num}: {title} ---")
            parts.append(f"Source: {url}")
        else:
            parts.append(f"\n--- Document {doc_num} ---")
        
        # Sort chunks within document by their position (chunk_index)
        sorted_chunks = sorted(chunks, key=lambda x: x.chunk.chunk_index)
        
        for chunk in sorted_chunks:
            parts.append(f"\n[Passage, relevance: {chunk.score:.2f}]")
            parts.append(chunk.chunk.text)
        
        doc_num += 1
    
    return '\n'.join(parts)


def extract_best_quotes(
    ranked_chunks: list[RankedChunk],
    max_quotes: int = 5,
    min_score: float = 0.7,
) -> list[dict]:
    """
    Extract the best direct quotes from ranked chunks.
    
    Args:
        ranked_chunks: List of RankedChunk objects
        max_quotes: Maximum number of quotes to extract
        min_score: Minimum relevance score for inclusion
        
    Returns:
        List of quote dicts with text, source, and score
    """
    quotes = []
    
    for rc in ranked_chunks:
        if rc.score < min_score:
            continue
        if len(quotes) >= max_quotes:
            break
        
        # Extract first substantial sentence as quote
        text = rc.chunk.text.strip()
        sentences = text.split('. ')
        
        # Find a good quote (not too short, not too long)
        for sentence in sentences:
            sentence = sentence.strip()
            if 20 < len(sentence) < 300:
                quotes.append({
                    'text': sentence if sentence.endswith('.') else sentence + '.',
                    'source_url': rc.chunk.source_url,
                    'source_title': rc.chunk.source_title,
                    'relevance_score': rc.score,
                })
                break
    
    return quotes
