"""Enhanced Answer Generation Prompts for Oracle Service.

These prompts are specifically designed for Phase 5 "Enhanced Answers" which uses
full document content (chunked and re-ranked) instead of just summaries.

The enhanced prompts focus on:
1. Direct quote extraction from source passages
2. More detailed and comprehensive answers
3. Specific fact extraction with source attribution
4. Better handling of technical details
"""

ENHANCED_ANSWER_SYSTEM = """You are an expert analyst with access to detailed content from authoritative sources about wireless standards, industry news, and technology developments.

Your task is to provide a COMPREHENSIVE and DETAILED answer based on the provided document passages. You have access to the full content of relevant documents, not just summaries.

**Guidelines:**
1. **Ground all claims in source material**: Every factual claim must be traceable to the provided passages
2. **Use direct quotes**: Include relevant direct quotes from the passages using quotation marks, with citation notation like [Doc 1]
3. **Be thorough**: Since you have full content, provide more detail than a summary-based answer would
4. **Cite sources**: Use [Doc 1], [Doc 2], etc. to reference which document/passage supports each claim
5. **Synthesize across documents**: Connect information from multiple sources when relevant
6. **Technical accuracy**: Preserve technical details, numbers, specifications, and proper terminology from the sources
7. **Acknowledge limitations**: If the passages don't fully answer the question, clearly state what information is available vs missing

**Answer Structure:**
- Lead with a clear, direct answer to the question
- Provide supporting details with citations
- Include relevant direct quotes for key facts
- Conclude with any caveats or areas needing more information

**Never** make up information not present in the passages.
"""

ENHANCED_ANSWER_USER = """Provide a comprehensive answer to the following question based on the document passages below.

**Question:** {question}

**Document Passages (ranked by relevance to your question):**

{passages}

**Instructions:**
1. Answer thoroughly using the detailed content from these passages
2. Include direct quotes for important facts (use quotation marks and cite source)
3. Use [Doc 1], [Doc 2], etc. to cite which document supports each claim
4. Connect information across documents when relevant
5. If the passages don't fully answer the question, explain what IS covered

**Detailed Answer:**"""


def format_passages_for_enhanced_prompt(
    ranked_chunks: list,  # list[RankedChunk] - avoiding circular import
) -> str:
    """
    Format re-ranked chunks for the enhanced answer prompt.
    
    Groups passages by document and presents them with relevance scores.
    """
    if not ranked_chunks:
        return "No relevant passages found."
    
    # Group by source document
    grouped = {}
    for rc in ranked_chunks:
        url = rc.chunk.source_url
        if url not in grouped:
            grouped[url] = {
                'title': rc.chunk.source_title or 'Untitled Document',
                'url': url,
                'passages': []
            }
        grouped[url]['passages'].append({
            'text': rc.chunk.text,
            'score': rc.score,
            'rank': rc.rank,
        })
    
    # Format output
    formatted_docs = []
    doc_num = 1
    
    for url, doc_data in grouped.items():
        doc_header = f"[Doc {doc_num}] **{doc_data['title']}**"
        doc_header += f"\nSource: {doc_data['url']}"
        
        passages_text = []
        for p in doc_data['passages']:
            # Sort passages by original chunk order within the document
            passages_text.append(f"```\n{p['text']}\n```")
        
        formatted_docs.append(f"{doc_header}\n\n" + "\n\n".join(passages_text))
        doc_num += 1
    
    return "\n\n---\n\n".join(formatted_docs)


def format_documents_with_content(
    documents: list[dict],
) -> str:
    """
    Format documents that have full content for the enhanced prompt.
    
    Used when documents include their 'content' field.
    """
    if not documents:
        return "No documents available."
    
    formatted = []
    for i, doc in enumerate(documents, 1):
        title = doc.get("title", "Untitled")
        url = doc.get("url", "")
        content = doc.get("content", doc.get("summary", "No content available."))
        date = doc.get("publish_date", "Unknown date")
        
        # Truncate very long content for prompt
        if len(content) > 3000:
            content = content[:3000] + "...[truncated]"
        
        formatted.append(f"""[Doc {i}] **{title}**
Source: {url}
Date: {date}

{content}
""")
    
    return "\n---\n".join(formatted)


def get_enhanced_answer_messages(
    question: str,
    ranked_chunks: list,  # list[RankedChunk]
) -> list[dict]:
    """
    Get messages for enhanced answer generation using re-ranked passages.
    
    Args:
        question: The user's question
        ranked_chunks: List of RankedChunk objects from the reranking service
        
    Returns:
        List of message dicts for the LLM
    """
    passages_text = format_passages_for_enhanced_prompt(ranked_chunks)
    
    user_content = ENHANCED_ANSWER_USER.format(
        question=question,
        passages=passages_text,
    )
    
    return [
        {"role": "system", "content": ENHANCED_ANSWER_SYSTEM},
        {"role": "user", "content": user_content}
    ]


# Quote extraction prompt for finding direct quotes
QUOTE_EXTRACTION_SYSTEM = """Extract the most relevant direct quotes from the provided passages that answer the question.

For each quote:
1. Copy the exact text from the passage
2. Note which document it comes from
3. Explain why this quote is relevant

Return a JSON array of quotes."""

QUOTE_EXTRACTION_USER = """Question: {question}

Passages:
{passages}

Extract 3-5 of the most relevant direct quotes that help answer this question.
Return as JSON array:
[
  {{"quote": "exact text from passage", "source_doc": 1, "relevance": "why this answers the question"}}
]"""


def get_quote_extraction_messages(
    question: str,
    ranked_chunks: list,
) -> list[dict]:
    """Get messages for extracting direct quotes from passages."""
    passages_text = format_passages_for_enhanced_prompt(ranked_chunks)
    
    return [
        {"role": "system", "content": QUOTE_EXTRACTION_SYSTEM},
        {"role": "user", "content": QUOTE_EXTRACTION_USER.format(
            question=question,
            passages=passages_text,
        )}
    ]
