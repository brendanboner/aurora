"""Enhanced Answer Service - Full content analysis for detailed answers.

This module provides the core logic for the /oracle/enhance endpoint,
including content fetching, chunking, re-ranking, and answer generation.

Phase 5 of Oracle Service implementation.
"""

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Optional

import aiohttp

from src.models.request import EnhanceDocumentReference
from src.models.response import Citation, DirectQuote, EnhanceMetadata
from src.services.chunking import chunk_document, ChunkedDocument, get_all_chunks
from src.services.reranking import rerank_chunks, RankedChunk, extract_best_quotes
from src.services.cache import OracleCache
from src.services.llm_client import get_llm_client, call_llm
from src.prompts.enhanced_answer import get_enhanced_answer_messages
from src.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class FetchedDocument:
    """A document with its fetched content."""
    url: str
    title: Optional[str]
    datasource_id: str
    content: Optional[str]
    success: bool
    error: Optional[str] = None
    from_cache: bool = False


@dataclass
class EnhanceResult:
    """Result of the enhance operation."""
    answer: str
    direct_quotes: list[DirectQuote]
    citations: list[Citation]
    metadata: EnhanceMetadata
    confidence_score: float


async def fetch_document_content(
    url: str,
    datasource_id: str,
    title: Optional[str] = None,
) -> FetchedDocument:
    """
    Fetch full content for a single document.
    
    First checks Redis cache, then calls the retriever service.
    
    Args:
        url: Document URL
        datasource_id: Datasource ID for routing to correct scraper
        title: Optional document title
        
    Returns:
        FetchedDocument with content or error
    """
    # Check cache first
    cache = await OracleCache.get_cache()
    if cache.is_available():
        cached_content = await cache.get_document_content(url)
        if cached_content:
            logger.debug(f"Cache hit for document content: {url[:50]}...")
            return FetchedDocument(
                url=url,
                title=title,
                datasource_id=datasource_id,
                content=cached_content,
                success=True,
                from_cache=True,
            )
    
    # Fetch from retriever service
    try:
        retriever_url = f"{settings.retriever_service_url}/retrieve/content"
        
        async with aiohttp.ClientSession() as session:
            async with session.post(
                retriever_url,
                json={
                    "documents": [{"url": url, "datasource_id": datasource_id}]
                },
                timeout=aiohttp.ClientTimeout(total=30),
            ) as response:
                if response.status != 200:
                    error_text = await response.text()
                    logger.error(f"Retriever service error for {url}: {response.status} - {error_text}")
                    return FetchedDocument(
                        url=url,
                        title=title,
                        datasource_id=datasource_id,
                        content=None,
                        success=False,
                        error=f"HTTP {response.status}",
                    )
                
                data = await response.json()
                results = data.get("results", [])
                
                if results and results[0].get("content"):
                    content = results[0]["content"]
                    
                    # Cache the content
                    if cache.is_available():
                        await cache.set_document_content(
                            url=url,
                            content=content,
                            ttl=settings.content_cache_ttl,
                        )
                    
                    return FetchedDocument(
                        url=url,
                        title=title,
                        datasource_id=datasource_id,
                        content=content,
                        success=True,
                    )
                else:
                    return FetchedDocument(
                        url=url,
                        title=title,
                        datasource_id=datasource_id,
                        content=None,
                        success=False,
                        error="No content returned",
                    )
                    
    except asyncio.TimeoutError:
        logger.error(f"Timeout fetching content for {url}")
        return FetchedDocument(
            url=url,
            title=title,
            datasource_id=datasource_id,
            content=None,
            success=False,
            error="Timeout",
        )
    except Exception as e:
        logger.error(f"Error fetching content for {url}: {e}")
        return FetchedDocument(
            url=url,
            title=title,
            datasource_id=datasource_id,
            content=None,
            success=False,
            error=str(e),
        )


async def fetch_documents_content(
    documents: list[EnhanceDocumentReference],
) -> list[FetchedDocument]:
    """
    Fetch content for multiple documents in parallel.
    
    Args:
        documents: List of document references to fetch
        
    Returns:
        List of FetchedDocument results
    """
    tasks = [
        fetch_document_content(
            url=doc.url,
            datasource_id=doc.datasource_id,
            title=doc.title,
        )
        for doc in documents
    ]
    
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    fetched = []
    for i, result in enumerate(results):
        if isinstance(result, Exception):
            logger.error(f"Exception fetching document {documents[i].url}: {result}")
            fetched.append(FetchedDocument(
                url=documents[i].url,
                title=documents[i].title,
                datasource_id=documents[i].datasource_id,
                content=None,
                success=False,
                error=str(result),
            ))
        else:
            fetched.append(result)
    
    return fetched


async def generate_enhanced_answer(
    question: str,
    documents: list[EnhanceDocumentReference],
) -> EnhanceResult:
    """
    Generate an enhanced answer by analyzing full document content.
    
    The process:
    1. Fetch full content for all documents (parallel)
    2. Chunk each document into smaller pieces
    3. Re-rank chunks by relevance to the question
    4. Generate detailed answer with citations and quotes
    
    Args:
        question: The user's question
        documents: Documents to analyze
        
    Returns:
        EnhanceResult with answer, quotes, and metadata
    """
    start_time = time.time()
    
    # Step 1: Fetch document content
    logger.info(f"Fetching content for {len(documents)} documents...")
    fetched_docs = await fetch_documents_content(documents)
    
    successful_docs = [d for d in fetched_docs if d.success and d.content]
    failed_count = len(fetched_docs) - len(successful_docs)
    cache_hits = sum(1 for d in fetched_docs if d.from_cache)
    
    logger.info(f"Fetched {len(successful_docs)} documents successfully ({cache_hits} from cache, {failed_count} failed)")
    
    if not successful_docs:
        return EnhanceResult(
            answer="Unable to fetch document content. Please try again later.",
            direct_quotes=[],
            citations=[],
            metadata=EnhanceMetadata(
                documents_fetched=0,
                documents_failed=failed_count,
                chunks_analyzed=0,
                chunks_used=0,
                total_tokens_analyzed=0,
                processing_time_ms=int((time.time() - start_time) * 1000),
                cache_hits=cache_hits,
            ),
            confidence_score=0.0,
        )
    
    # Step 2: Chunk documents
    logger.info("Chunking documents...")
    chunked_docs = []
    for doc in successful_docs:
        chunked = chunk_document(
            content=doc.content,
            url=doc.url,
            title=doc.title,
            chunk_size=settings.enhance_chunk_size,
            chunk_overlap=settings.enhance_chunk_overlap,
        )
        chunked_docs.append(chunked)
    
    all_chunks = get_all_chunks(chunked_docs)
    total_tokens = sum(c.token_count for c in all_chunks)
    
    logger.info(f"Created {len(all_chunks)} chunks ({total_tokens} tokens) from {len(chunked_docs)} documents")
    
    # Step 3: Re-rank chunks by relevance
    logger.info("Re-ranking chunks by relevance...")
    rerank_result = await rerank_chunks(
        query=question,
        chunks=all_chunks,
        top_k=settings.enhance_max_chunks,
        max_tokens=settings.enhance_max_context_tokens,
    )
    
    ranked_chunks = rerank_result.chunks
    logger.info(f"Selected {len(ranked_chunks)} most relevant chunks ({rerank_result.total_tokens} tokens)")
    
    if not ranked_chunks:
        return EnhanceResult(
            answer="Unable to find relevant content in the documents.",
            direct_quotes=[],
            citations=[],
            metadata=EnhanceMetadata(
                documents_fetched=len(successful_docs),
                documents_failed=failed_count,
                chunks_analyzed=len(all_chunks),
                chunks_used=0,
                total_tokens_analyzed=total_tokens,
                processing_time_ms=int((time.time() - start_time) * 1000),
                cache_hits=cache_hits,
            ),
            confidence_score=0.0,
        )
    
    # Step 4: Generate enhanced answer
    logger.info("Generating enhanced answer...")
    client = get_llm_client()
    
    if client is None:
        return EnhanceResult(
            answer="LLM service unavailable. Please try again later.",
            direct_quotes=[],
            citations=[],
            metadata=EnhanceMetadata(
                documents_fetched=len(successful_docs),
                documents_failed=failed_count,
                chunks_analyzed=len(all_chunks),
                chunks_used=len(ranked_chunks),
                total_tokens_analyzed=total_tokens,
                processing_time_ms=int((time.time() - start_time) * 1000),
                cache_hits=cache_hits,
            ),
            confidence_score=0.0,
        )
    
    messages = get_enhanced_answer_messages(question, ranked_chunks)
    
    try:
        response = await call_llm(
            client=client,
            messages=messages,
            max_tokens=settings.max_answer_tokens * 2,  # Allow longer enhanced answers
            temperature=0.3,
        )
        answer = response.content
    except Exception as e:
        logger.error(f"Enhanced answer generation failed: {e}")
        answer = "Error generating enhanced answer. Please try again."
    
    # Step 5: Extract best quotes
    raw_quotes = extract_best_quotes(
        ranked_chunks,
        max_quotes=settings.enhance_max_quotes,
        min_score=settings.enhance_min_relevance_score,
    )
    
    direct_quotes = [
        DirectQuote(
            text=q['text'],
            source_url=q['source_url'],
            source_title=q.get('source_title'),
            relevance_score=q['relevance_score'],
        )
        for q in raw_quotes
    ]
    
    # Step 6: Build citations from top chunks (only unique documents)
    seen_urls = set()
    citations = []
    citation_index = 0
    
    for rc in ranked_chunks:
        if rc.chunk.source_url in seen_urls:
            continue
        seen_urls.add(rc.chunk.source_url)
        citation_index += 1
        
        # Get an excerpt from the chunk
        excerpt = rc.chunk.text[:200]
        if len(rc.chunk.text) > 200:
            excerpt += "..."
        
        citations.append(Citation(
            index=citation_index,
            document_url=rc.chunk.source_url,
            title=rc.chunk.source_title,
            excerpt=excerpt,
        ))
        
        if len(citations) >= 5:
            break
    
    # Calculate confidence based on coverage and chunk scores
    avg_score = sum(rc.score for rc in ranked_chunks) / len(ranked_chunks) if ranked_chunks else 0
    coverage = len(successful_docs) / len(documents) if documents else 0
    confidence = min(0.95, avg_score * 0.7 + coverage * 0.3)
    
    processing_time = int((time.time() - start_time) * 1000)
    
    return EnhanceResult(
        answer=answer,
        direct_quotes=direct_quotes,
        citations=citations,
        metadata=EnhanceMetadata(
            documents_fetched=len(successful_docs),
            documents_failed=failed_count,
            chunks_analyzed=len(all_chunks),
            chunks_used=len(ranked_chunks),
            total_tokens_analyzed=total_tokens,
            processing_time_ms=processing_time,
            cache_hits=cache_hits,
        ),
        confidence_score=round(confidence, 3),
    )
