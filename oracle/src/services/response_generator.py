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
        intent: QueryIntent,
        user_context: Optional[str] = None,
        conversation_history: Optional[list[dict]] = None,
    ) -> AnswerResult:
        """
        Generate an LLM answer with citations.
        
        Args:
            question: Original user question
            documents: Retrieved documents
            graph_context: Graph context information
            intent: Classified query intent
            user_context: Optional user preferences context string for personalization
            
        Returns:
            AnswerResult with answer, citations, and confidence
        """
        if not documents:
            # Try to provide a helpful response even without documents
            return await self._generate_no_documents_response(question, graph_context, intent)
        
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
            messages = get_answer_generator_messages(
                question, docs_for_prompt, gc_dict, user_context,
                conversation_history=conversation_history,
            )
            response = await call_llm(
                client=client,
                messages=messages,
                max_tokens=settings.max_answer_tokens,
                temperature=0.3  # Slightly higher for more natural responses
            )
            
            # Extract citations from answer
            citations, cited_indices = self._extract_citations(response.content, documents)
            
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
    ) -> tuple[list[Citation], set[int]]:
        """Extract citation references from the answer.
        
        Returns:
            Tuple of (citations list, set of cited document indices)
        """
        citations = []
        cited_indices = set()
        
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
                cited_indices.add(idx - 1)  # Store 0-based index
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
        
        return citations, cited_indices
    
    def filter_documents_by_citations(
        self,
        documents: list[Document],
        cited_indices: set[int],
        max_cited: int = 10,
        max_additional: int = 5
    ) -> tuple[list[Document], list[Document]]:
        """
        Separate documents into cited and additional context groups.
        
        Args:
            documents: All retrieved documents
            cited_indices: Set of 0-based indices for cited documents
            max_cited: Maximum cited documents to return
            max_additional: Maximum additional context documents
            
        Returns:
            Tuple of (cited_documents, additional_documents)
        """
        cited_docs = []
        additional_docs = []
        
        for i, doc in enumerate(documents):
            if i in cited_indices:
                cited_docs.append(doc)
            else:
                additional_docs.append(doc)
        
        # Limit counts
        cited_docs = cited_docs[:max_cited]
        additional_docs = additional_docs[:max_additional]
        
        logger.info(
            f"Filtered documents: {len(cited_docs)} cited, "
            f"{len(additional_docs)} additional context"
        )
        
        return cited_docs, additional_docs
    
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
    
    async def _generate_no_documents_response(
        self,
        question: str,
        graph_context: Optional[GraphContext],
        intent: QueryIntent
    ) -> AnswerResult:
        """Generate a helpful response when no documents are found."""
        client = get_llm_client()
        
        if client is None:
            # No LLM available — give a graceful response without revealing system internals
            return AnswerResult(
                answer=(
                    "This topic doesn't appear in my recent meeting notes. "
                    "Try asking about a specific Wi-Fi Alliance standard, working group, or recent publication."
                ),
                citations=[],
                confidence_score=0.0,
                tokens_used=0
            )
        
        # Use LLM to answer from general knowledge, without revealing internal data gaps.
        # NOTE: get_llm_client() returns a *synchronous* AzureOpenAI; use call_llm (not await client.create).
        try:
            messages = [
                {
                    "role": "system",
                    "content": (
                        "You are an expert who has personally attended every Wi-Fi Alliance meeting, "
                        "reviewed every working group document, and participated in every industry discussion. "
                        "You speak from first-hand knowledge and memory. "
                        "Answer the question with specific, informative detail — even if you rely on "
                        "your general deep expertise rather than a specific document. "
                        "NEVER say 'No matching documents', 'knowledge base', 'retrieved documents', "
                        "or reveal any internal system limitations. "
                        "NEVER tell the user to consult other sources or seek information elsewhere. "
                        "Be concise (under 200 words) and directly answer the question asked."
                    ),
                },
                {
                    "role": "user",
                    "content": f"Question: {question}",
                },
            ]

            llm_response = await call_llm(client, messages, max_tokens=400, temperature=0.5)

            return AnswerResult(
                answer=llm_response.content.strip(),
                citations=[],
                confidence_score=0.3,
                tokens_used=llm_response.tokens_used,
            )

        except Exception as e:
            logger.error(f"Failed to generate no-documents response: {e}")
            # Last-resort: answer from the meeting-attendee persona without revealing system state
            return AnswerResult(
                answer=(
                    "This topic isn't something I have detailed notes on from recent meetings. "
                    "If you'd like, try rephrasing or asking about a related Wi-Fi Alliance standard or working group."
                ),
                citations=[],
                confidence_score=0.0,
                tokens_used=0,
            )
    
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
