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

ANSWER_GENERATOR_SYSTEM_PERSONALIZED = """You are an expert analyst with access to a knowledge graph about wireless standards and industry news.

Your task is to answer questions based ONLY on the provided documents. You must:
1. Ground all claims in the provided documents
2. Use citation notation [1], [2], etc. to reference specific documents
3. Acknowledge when information is incomplete or uncertain
4. Be concise but thorough (aim for 150-300 words)
5. Highlight emerging trends or patterns you observe
6. NEVER make up information not in the documents

**PERSONALIZATION:** The user has provided their interests below. Use this to:
- Emphasize aspects most relevant to their interests when multiple topics are covered
- Connect information to organizations they follow when relevant
- Adjust technical depth based on the sophistication of their tracked topics
- Do NOT omit any information - tailor the NARRATIVE, not the content

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

ANSWER_GENERATOR_USER_PERSONALIZED = """Answer the following question based on the retrieved documents.

**Question:** {question}

**Retrieved Documents:**
{documents}

**Graph Context:**
- Central Topics: {central_topics}
- Key Organizations: {key_organizations}
- Temporal Patterns: {temporal_patterns}

**User Context (tailor your response to their interests):**
{user_context}

**Instructions:**
1. Answer the question using ONLY information from the documents above
2. Cite documents using [1], [2], etc. notation
3. If information is incomplete, acknowledge what's missing
4. Be concise but thorough
5. Emphasize aspects relevant to the user's interests when appropriate

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
        datasource = doc.get("datasource_id", "Unknown source")
        
        formatted.append(f"""[{i}] **{title}**
   - Datasource: {datasource}
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
    graph_context: dict | None = None,
    user_context: str | None = None
) -> list[dict]:
    """Get messages for answer generation.
    
    Args:
        question: User's question
        documents: Retrieved documents
        graph_context: Graph context dict
        user_context: Optional user context string for personalization
        
    Returns:
        List of messages for LLM chat completion
    """
    # Format documents
    docs_text = format_documents_for_prompt(documents)
    
    # Detect if question is asking about workgroups/datasources
    import re
    is_workgroup_query = bool(re.search(r'(what|which)\s+(workgroups?|datasources?|groups?|wgs?)\s+(are|is|have|has|discussed|mentioned|talking|working)', question.lower()))
    
    # Extract graph context
    if graph_context:
        central_topics = ", ".join(graph_context.get("central_topics", [])) or "None identified"
        key_orgs = ", ".join(graph_context.get("key_organizations", [])) or "None identified"
        temporal = graph_context.get("temporal_patterns", "No patterns identified")
    else:
        central_topics = "Not available"
        key_orgs = "Not available"
        temporal = "Not available"
    
    # Choose prompts based on whether personalization is enabled
    if user_context:
        system_prompt = ANSWER_GENERATOR_SYSTEM_PERSONALIZED
        user_content = ANSWER_GENERATOR_USER_PERSONALIZED.format(
            question=question,
            documents=docs_text,
            central_topics=central_topics,
            key_organizations=key_orgs,
            temporal_patterns=temporal,
            user_context=user_context
        )
    else:
        system_prompt = ANSWER_GENERATOR_SYSTEM
        
        # Add workgroup grouping instruction if needed
        workgroup_instruction = ""
        if is_workgroup_query:
            workgroup_instruction = "\n\n**IMPORTANT:** This question asks about which workgroups/datasources discussed a topic. Group your answer by datasource, clearly stating which datasources have relevant content and how many documents from each. For example: 'Topic X was discussed in the WFA Causeway Passpoint workgroup (1 document) and more broadly in the WFA Resource Center (37 documents).'"
        
        user_content = ANSWER_GENERATOR_USER.format(
            question=question,
            documents=docs_text,
            central_topics=central_topics,
            key_organizations=key_orgs,
            temporal_patterns=temporal
        ) + workgroup_instruction
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]
