"""Response Generator - Mode-based response formatting for Oracle Service."""

from dataclasses import dataclass
import logging
import re
from typing import Optional

from src.models.response import Document, Citation, GraphContext, QueryIntent
from src.prompts.answer_generator import get_answer_generator_messages
from src.services.llm_client import get_llm_client, call_llm
from src.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class AnswerResult:
    """Result of answer generation."""
    answer: str
    citations: list[Citation]
    confidence_score: float
    tokens_used: int


class ResponseGenerator:
    """Generates responses based on mode (retrieval or answer)."""
    
    async def generate_answer(
        self,
        question: str,
        documents: list[Document],
        graph_context: Optional[GraphContext],
        intent: QueryIntent
    ) -> AnswerResult:
        """
        Generate an LLM answer with citations.
        
        Args:
            question: Original user question
            documents: Retrieved documents
            graph_context: Graph context information
            intent: Classified query intent
            
        Returns:
            AnswerResult with answer, citations, and confidence
        """
        if not documents:
            return AnswerResult(
                answer="I couldn't find any relevant documents to answer your question. Please try rephrasing or broadening your search.",
                citations=[],
                confidence_score=0.0,
                tokens_used=0
            )
        
        client = get_llm_client()
        
        if client is None:
            # No LLM available - return simple summary
            return self._generate_fallback_answer(question, documents, graph_context)
        
        try:
            # Prepare documents for prompt
            docs_for_prompt = [
                {
                    "title": doc.title or "Untitled",
                    "summary": doc.summary or "No summary available",
                    "publish_date": doc.publish_date or "Unknown date",
                    "url": doc.url,
                    "topics": doc.topics,
                    "organizations": doc.organizations,
                }
                for doc in documents[:10]  # Limit to 10 docs for context window
            ]
            
            # Prepare graph context
            gc_dict = None
            if graph_context:
                gc_dict = {
                    "central_topics": graph_context.central_topics,
                    "key_organizations": graph_context.key_organizations,
                    "temporal_patterns": graph_context.temporal_patterns,
                }
            
            # Generate answer
            messages = get_answer_generator_messages(question, docs_for_prompt, gc_dict)
            response = await call_llm(
                client=client,
                messages=messages,
                max_tokens=settings.max_answer_tokens,
                temperature=0.3  # Slightly higher for more natural responses
            )
            
            # Extract citations from answer
            citations = self._extract_citations(response.content, documents)
            
            # Calculate confidence based on citations and document relevance
            confidence = self._calculate_confidence(response.content, documents, citations)
            
            return AnswerResult(
                answer=response.content,
                citations=citations,
                confidence_score=confidence,
                tokens_used=response.tokens_used
            )
            
        except Exception as e:
            logger.error(f"Answer generation failed: {e}")
            return self._generate_fallback_answer(question, documents, graph_context)
    
    def _extract_citations(
        self,
        answer: str,
        documents: list[Document]
    ) -> list[Citation]:
        """Extract citation references from the answer."""
        citations = []
        
        # Find all citation markers like [1], [2], etc.
        citation_pattern = r'\[(\d+)\]'
        found_citations = re.findall(citation_pattern, answer)
        
        # Deduplicate while preserving order
        seen = set()
        unique_citations = []
        for c in found_citations:
            if c not in seen:
                seen.add(c)
                unique_citations.append(int(c))
        
        # Map to documents
        for idx in unique_citations:
            if 1 <= idx <= len(documents):
                doc = documents[idx - 1]
                
                # Extract a relevant excerpt (first 200 chars of summary)
                excerpt = None
                if doc.summary:
                    excerpt = doc.summary[:200]
                    if len(doc.summary) > 200:
                        excerpt += "..."
                
                citations.append(Citation(
                    index=idx,
                    document_url=doc.url,
                    title=doc.title,
                    excerpt=excerpt
                ))
        
        return citations
    
    def _calculate_confidence(
        self,
        answer: str,
        documents: list[Document],
        citations: list[Citation]
    ) -> float:
        """Calculate confidence score for the generated answer."""
        if not documents:
            return 0.0
        
        # Factors:
        # 1. Citation coverage (30%): How many documents are cited
        citation_coverage = len(citations) / min(len(documents), 5)
        citation_score = min(citation_coverage, 1.0) * 0.3
        
        # 2. Document relevance (30%): Average relevance of cited documents
        if citations:
            cited_indices = [c.index - 1 for c in citations if c.index <= len(documents)]
            cited_relevance = sum(documents[i].relevance_score for i in cited_indices) / len(cited_indices)
        else:
            cited_relevance = sum(d.relevance_score for d in documents[:3]) / min(len(documents), 3)
        relevance_score = cited_relevance * 0.3
        
        # 3. Answer length (20%): Reasonable length indicates thorough answer
        word_count = len(answer.split())
        if word_count < 50:
            length_score = 0.1
        elif word_count < 100:
            length_score = 0.15
        elif word_count < 300:
            length_score = 0.2
        else:
            length_score = 0.15  # Too long might indicate rambling
        
        # 4. Hedging language (20%): Less hedging = more confident
        hedging_phrases = [
            "i'm not sure", "it's unclear", "may or may not",
            "possibly", "perhaps", "might be", "could be",
            "insufficient information", "cannot determine"
        ]
        answer_lower = answer.lower()
        hedging_count = sum(1 for phrase in hedging_phrases if phrase in answer_lower)
        hedging_penalty = min(hedging_count * 0.05, 0.2)
        hedging_score = 0.2 - hedging_penalty
        
        total_confidence = citation_score + relevance_score + length_score + hedging_score
        
        # Ensure in valid range
        return max(0.1, min(total_confidence, 0.95))
    
    def _generate_fallback_answer(
        self,
        question: str,
        documents: list[Document],
        graph_context: Optional[GraphContext]
    ) -> AnswerResult:
        """Generate a simple answer when LLM is unavailable."""
        if not documents:
            return AnswerResult(
                answer="No relevant documents found for your query.",
                citations=[],
                confidence_score=0.0,
                tokens_used=0
            )
        
        # Build a simple summary
        parts = [f"Found {len(documents)} relevant documents:"]
        
        citations = []
        for i, doc in enumerate(documents[:5], 1):
            title = doc.title or "Untitled"
            date = doc.publish_date or "Unknown date"
            parts.append(f"\n[{i}] **{title}** ({date})")
            if doc.summary:
                parts.append(f"   {doc.summary[:150]}...")
            
            citations.append(Citation(
                index=i,
                document_url=doc.url,
                title=doc.title,
                excerpt=doc.summary[:200] if doc.summary else None
            ))
        
        if graph_context and graph_context.central_topics:
            parts.append(f"\n\nKey topics: {', '.join(graph_context.central_topics)}")
        
        return AnswerResult(
            answer="\n".join(parts),
            citations=citations,
            confidence_score=0.5,  # Medium confidence for fallback
            tokens_used=0
        )
