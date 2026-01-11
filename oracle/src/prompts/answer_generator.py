"""Answer generation prompts for Oracle Service."""

ANSWER_GENERATOR_SYSTEM = """You are an expert analyst with access to a knowledge graph about wireless standards and industry news.

Your task is to answer questions based ONLY on the provided documents. You must:
1. Ground all claims in the provided documents
2. Use citation notation [1], [2], etc. to reference specific documents
3. Acknowledge when information is incomplete or uncertain
4. Be concise but thorough (aim for 150-300 words)
5. Highlight emerging trends or patterns you observe
6. NEVER make up information not in the documents

If the documents don't contain enough information to fully answer the question, say so clearly and explain what information is available.
"""

ANSWER_GENERATOR_USER = """Answer the following question based on the retrieved documents.

**Question:** {question}

**Retrieved Documents:**
{documents}

**Graph Context:**
- Central Topics: {central_topics}
- Key Organizations: {key_organizations}
- Temporal Patterns: {temporal_patterns}

**Instructions:**
1. Answer the question using ONLY information from the documents above
2. Cite documents using [1], [2], etc. notation
3. If information is incomplete, acknowledge what's missing
4. Be concise but thorough

**Answer:**"""


def format_documents_for_prompt(documents: list[dict]) -> str:
    """Format documents for inclusion in the answer generation prompt."""
    if not documents:
        return "No documents retrieved."
    
    formatted = []
    for i, doc in enumerate(documents, 1):
        title = doc.get("title", "Untitled")
        summary = doc.get("summary", "No summary available.")
        date = doc.get("publish_date", "Unknown date")
        url = doc.get("url", "")
        topics = ", ".join(doc.get("topics", [])) or "None"
        orgs = ", ".join(doc.get("organizations", [])) or "None"
        
        formatted.append(f"""[{i}] **{title}**
   - Date: {date}
   - URL: {url}
   - Topics: {topics}
   - Organizations: {orgs}
   - Summary: {summary}
""")
    
    return "\n".join(formatted)


def get_answer_generator_messages(
    question: str,
    documents: list[dict],
    graph_context: dict | None = None
) -> list[dict]:
    """Get messages for answer generation."""
    # Format documents
    docs_text = format_documents_for_prompt(documents)
    
    # Extract graph context
    if graph_context:
        central_topics = ", ".join(graph_context.get("central_topics", [])) or "None identified"
        key_orgs = ", ".join(graph_context.get("key_organizations", [])) or "None identified"
        temporal = graph_context.get("temporal_patterns", "No patterns identified")
    else:
        central_topics = "Not available"
        key_orgs = "Not available"
        temporal = "Not available"
    
    user_content = ANSWER_GENERATOR_USER.format(
        question=question,
        documents=docs_text,
        central_topics=central_topics,
        key_organizations=key_orgs,
        temporal_patterns=temporal
    )
    
    return [
        {"role": "system", "content": ANSWER_GENERATOR_SYSTEM},
        {"role": "user", "content": user_content}
    ]
