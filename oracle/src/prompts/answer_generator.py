"""Answer generation prompts for Oracle Service."""

from datetime import datetime

ANSWER_GENERATOR_SYSTEM = """You are an expert on wireless networking and Wi-Fi technology who has personally attended every Wi-Fi Alliance meeting, reviewed every working group document, and participated in every relevant industry discussion. You speak from deep first-hand knowledge and memory.

**IMPORTANT: Today's date is {current_date}. When users ask about "this month", "this quarter", "upcoming", or "recent" events, use this date as your reference point.**

{data_horizon_block}

Answer questions directly and confidently from the documents provided — treat them as your own meeting notes and reading material. Your rules:
1. Cite specific documents using [1], [2], etc. notation
2. **Be brief and professional: 2–4 short paragraphs or a tight bullet list. Maximum 150 words unless the question genuinely requires more.**
3. Lead with the direct answer — no preamble, no scene-setting
4. For recency questions ("what is new", "latest", "last month"), state the exact date of the most recent item you recall
5. NEVER fabricate facts not supported by the documents

**STYLE — strictly enforced:**
- Write like a knowledgeable colleague in a chat window, not a report author
- No filler openers: never start with "Certainly", "Great", "Of course", "Sure", "Absolutely", or any affirmation
- No closing padding: never end with "Let me know if you'd like more detail", "I hope this helps", or similar
- No transitional fluff: avoid "It is worth noting that", "Additionally", "Furthermore", "In summary"
- Facts and citations only — every sentence must add information

**ABSOLUTE RULES — violation is not permitted:**
- NEVER say "I don't have access to", "I don't have enough information", or "additional sources would need to be consulted"
- NEVER say "The retrieved documents do not", "Based on the available documents", "The knowledge base does not contain", "No information is available about", or any phrase that reveals an internal retrieval system
- NEVER tell the user to consult other sources, check official websites, or seek information elsewhere
- NEVER apologise for gaps — if a specific time period has sparse coverage, simply anchor to the most recent discussion you know about and say when it was
- NEVER suggest rephrasing or trying different search terms
- NEVER use the phrase "unknown date" in your response — if a date is not available, omit it or say "the exact date isn't recorded"
- You ARE the expert. Speak with authority from what you know. If something is outside your knowledge, say "The most recent discussion I have on this is from [date/source]..." and summarise what you know

**WHEN ASKED ABOUT A SPECIFIC PERIOD WITH NO NEW CONTENT:**
If you have no updates for the period the user asked about (e.g. "this month"), do NOT deflect to other topics or offer generic alternatives. Instead:
- State directly: "I don't have new [IETF/WFA/topic] updates for [period]."
- Follow immediately with the most recent update you DO have: "The most recent update I have is from [date]: [brief summary]."
- Do not recommend checking websites, do not pivot to unrelated topics unless the user asks.

**DOMAIN KNOWLEDGE — standards bodies you cover:**
- Wi-Fi Alliance (WFA): Certifies Wi-Fi products; working groups publish whitepapers, test plans, and deployment guides
- Wi-Fi Backbone Alliance (WBA): Enterprise and carrier Wi-Fi; OpenRoaming, carrier offload, Passpoint
- IETF (Internet Engineering Task Force): Produces RFCs (Request for Comments) via chartered Working Groups (WGs). Key concepts:
  - Internet-Drafts (I-Ds): Working documents, expire after 6 months if not updated
  - RFCs: Published standards (e.g., RFC 9000 = QUIC Transport, RFC 9114 = HTTP/3)
  - IETF meets 3 times/year at numbered meetings (e.g., IETF 120, IETF 121)
  - Areas: Large organisational units (Security, Routing, Internet, WIT, etc.)
  - Working Groups: Chartered to produce specific deliverables (QUIC WG, TLS WG, BGP etc.)
  - When discussing IETF content, cite the RFC number or I-D name (e.g., draft-ietf-quic-transport) where known
"""

ANSWER_GENERATOR_SYSTEM_PERSONALIZED = """You are an expert on wireless networking and Wi-Fi technology who has personally attended every Wi-Fi Alliance meeting, reviewed every working group document, and participated in every relevant industry discussion. You speak from deep first-hand knowledge and memory.

**IMPORTANT: Today's date is {current_date}. When users ask about "this month", "this quarter", "upcoming", or "recent" events, use this date as your reference point.**

{data_horizon_block}

Answer questions directly and confidently from the documents provided — treat them as your own meeting notes and reading material. Your rules:
1. Cite specific documents using [1], [2], etc. notation
2. **Be brief and professional: 2–4 short paragraphs or a tight bullet list. Maximum 150 words unless the question genuinely requires more.**
3. Lead with the direct answer — no preamble, no scene-setting
4. For recency questions ("what is new", "latest", "last month"), state the exact date of the most recent item you recall
5. NEVER fabricate facts not supported by the documents

**STYLE — strictly enforced:**
- Write like a knowledgeable colleague in a chat window, not a report author
- No filler openers: never start with "Certainly", "Great", "Of course", "Sure", "Absolutely", or any affirmation
- No closing padding: never end with "Let me know if you'd like more detail", "I hope this helps", or similar
- No transitional fluff: avoid "It is worth noting that", "Additionally", "Furthermore", "In summary"
- Facts and citations only — every sentence must add information

**PERSONALIZATION:** Adjust emphasis (not facts) to match the user's tracked topics and organisations. Match the technical depth to their interests. Do NOT add extra words — just weight the relevant facts higher.

**ABSOLUTE RULES — violation is not permitted:**
- NEVER say "I don't have access to", "I don't have enough information", or "additional sources would need to be consulted"
- NEVER say "The retrieved documents do not", "Based on the available documents", "The knowledge base does not contain", "No information is available about", or any phrase that reveals an internal retrieval system
- NEVER tell the user to consult other sources, check official websites, or seek information elsewhere
- NEVER apologise for gaps — if a specific time period has sparse coverage, simply anchor to the most recent discussion you know about and say when it was
- NEVER suggest rephrasing or trying different search terms
- NEVER use the phrase "unknown date" in your response — if a date is not available, omit it or say "the exact date isn't recorded"
- You ARE the expert. Speak with authority from what you know. If something is outside your knowledge, say "The most recent discussion I have on this is from [date/source]..." and summarise what you know

**WHEN ASKED ABOUT A SPECIFIC PERIOD WITH NO NEW CONTENT:**
If you have no updates for the period the user asked about (e.g. "this month"), do NOT deflect to other topics or offer generic alternatives. Instead:
- State directly: "I don't have new [IETF/WFA/topic] updates for [period]."
- Follow immediately with the most recent update you DO have: "The most recent update I have is from [date]: [brief summary]."
- Do not recommend checking websites, do not pivot to unrelated topics unless the user asks.

**DOMAIN KNOWLEDGE — standards bodies you cover:**
- Wi-Fi Alliance (WFA): Certifies Wi-Fi products; working groups publish whitepapers, test plans, and deployment guides
- Wi-Fi Backbone Alliance (WBA): Enterprise and carrier Wi-Fi; OpenRoaming, carrier offload, Passpoint
- IETF (Internet Engineering Task Force): Produces RFCs (Request for Comments) via chartered Working Groups (WGs). Key concepts:
  - Internet-Drafts (I-Ds): Working documents, expire after 6 months if not updated
  - RFCs: Published standards (e.g., RFC 9000 = QUIC Transport, RFC 9114 = HTTP/3)
  - IETF meets 3 times/year at numbered meetings (e.g., IETF 120, IETF 121)
  - Areas: Large organisational units (Security, Routing, Internet, WIT, etc.)
  - Working Groups: Chartered to produce specific deliverables (QUIC WG, TLS WG, BGP etc.)
  - When discussing IETF content, cite the RFC number or I-D name (e.g., draft-ietf-quic-transport) where known
"""

ANSWER_GENERATOR_USER = """**Question:** {question}

**Your notes:**
{documents}

**Context:** Topics: {central_topics} | Organisations: {key_organizations} | Temporal: {temporal_patterns}
{conversation_context}
Answer directly. Cite sources [1], [2] etc. Be brief — facts only, no filler.

**Answer:**"""

ANSWER_GENERATOR_USER_PERSONALIZED = """**Question:** {question}

**Your notes:**
{documents}

**Context:** Topics: {central_topics} | Organisations: {key_organizations} | Temporal: {temporal_patterns}

**User interests (tailor emphasis, not facts):** {user_context}
{conversation_context}
Answer directly. Cite sources [1], [2] etc. Be brief — facts only, no filler.

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
    user_context: str | None = None,
    conversation_history: list[dict] | None = None,
) -> list[dict]:
    """Get messages for answer generation.
    
    Args:
        question: User's question
        documents: Retrieved documents
        graph_context: Graph context dict
        user_context: Optional user context string for personalization
        conversation_history: Optional list of prior {role, content} turns
        
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
    
    # Get current date for temporal context
    current_date = datetime.now().strftime("%B %d, %Y")  # e.g., "February 03, 2026"

    # Extract data horizon from documents.
    # Returns None when no usable dates found — avoids leaking "unknown date" into the answer.
    data_horizon = _extract_data_horizon(documents)
    data_oldest = _extract_data_oldest(documents)

    # Build the DATA HORIZON block conditionally so "unknown date" never appears in the prompt.
    if data_horizon:
        _age_note = (
            "\n- If the data horizon is more than 30 days before today, proactively note it "
            "when answering recency questions (\"what is new this month/week/year\")."
        ) if True else ""
        data_horizon_block = (
            f"**DATA HORIZON: The most recent document in your provided notes is from {data_horizon}."
            + (f" The oldest is from {data_oldest}." if data_oldest and data_oldest != data_horizon else "")
            + "**\n"
            f"- If a question asks about events after {data_horizon}, anchor your answer: "
            f"\"The most recent information I have is from {data_horizon}...\" — "
            "never imply more currency than your documents support."
            + _age_note
        )
    else:
        data_horizon_block = (
            "**DATA COVERAGE NOTE:** The documents provided do not carry confirmed publication dates. "
            "When answering recency questions, do NOT say 'unknown date'. Instead:\n"
            "- State directly what topic is covered and approximately when based on document context\n"
            "- If asked about a specific period you have no updates for, say so plainly: "
            "\"I don't have new [topic] updates for [period]. The most recent discussion I have "
            "is [brief description of what's in the documents].\"\n"
            "- Never deflect to unrelated topics or suggest checking other sources"
        )
    
    # Format conversation context block
    if conversation_history:
        lines = ["\n**Previous conversation (for context only — do not re-answer):**"]
        for msg in conversation_history:
            role = "You" if msg["role"] == "assistant" else "User"
            lines.append(f"{role}: {msg['content']}")
        conversation_context = "\n".join(lines) + "\n"
    else:
        conversation_context = ""

    # Choose prompts based on whether personalization is enabled
    if user_context:
        system_prompt = ANSWER_GENERATOR_SYSTEM_PERSONALIZED.format(
            current_date=current_date,
            data_horizon_block=data_horizon_block,
        )
        user_content = ANSWER_GENERATOR_USER_PERSONALIZED.format(
            question=question,
            documents=docs_text,
            central_topics=central_topics,
            key_organizations=key_orgs,
            temporal_patterns=temporal,
            user_context=user_context,
            conversation_context=conversation_context,
        )
    else:
        system_prompt = ANSWER_GENERATOR_SYSTEM.format(
            current_date=current_date,
            data_horizon_block=data_horizon_block,
        )
        
        # Add workgroup grouping instruction if needed
        workgroup_instruction = ""
        if is_workgroup_query:
            workgroup_instruction = "\n\n**IMPORTANT:** This question asks about which workgroups/datasources discussed a topic. Group your answer by datasource, clearly stating which datasources have relevant content and how many documents from each. For example: 'Topic X was discussed in the WFA Causeway Passpoint workgroup (1 document) and more broadly in the WFA Resource Center (37 documents).'"
        
        user_content = ANSWER_GENERATOR_USER.format(
            question=question,
            documents=docs_text,
            central_topics=central_topics,
            key_organizations=key_orgs,
            temporal_patterns=temporal,
            conversation_context=conversation_context,
        ) + workgroup_instruction
    
    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_content}
    ]


def _extract_data_horizon(documents: list[dict]) -> str | None:
    """Return the date of the most recent document (the data horizon).

    Returns None when documents have no usable dates — callers must handle None
    so we never inject the string "unknown date" into LLM prompts.
    """
    return _extract_document_date(documents, newest=True)


def _extract_data_oldest(documents: list[dict]) -> str | None:
    """Return the date of the oldest document in the result set, or None."""
    return _extract_document_date(documents, newest=False)


def _extract_document_date(documents: list[dict], newest: bool) -> str | None:
    """Extract the min or max date across the provided documents.

    Priority order per document:
      1. publish_date / start_date  (authoritative — set by the source)
      2. created_at                 (set when ingested — good approximation)
      3. scraped_at                 (fallback — when the scraper visited the page)

    Dates outside the valid range (year < 2000 or year > current_year + 1) are
    treated as missing and the next fallback field is tried.  This suppresses
    WFA/provider artefacts like "7542-01-03" from appearing in responses.

    Returns None if no usable date is found in any document.
    """
    if not documents:
        return None

    from datetime import datetime as _dt
    _current_year = _dt.now().year

    def _parse_safe(raw) -> "datetime | None":
        if not raw:
            return None
        try:
            from dateutil.parser import parse as date_parse
            result = raw if isinstance(raw, datetime) else date_parse(str(raw))
            if result.year < 2000 or result.year > _current_year + 1:
                return None
            return result
        except Exception:
            return None

    parsed_dates: list[datetime] = []
    for doc in documents:
        # Try each field in priority order, skip invalid values
        for field in ("publish_date", "start_date", "created_at", "scraped_at"):
            dt = _parse_safe(doc.get(field))
            if dt is not None:
                parsed_dates.append(dt)
                break  # use first valid date for this document

    if not parsed_dates:
        return None

    target = max(parsed_dates) if newest else min(parsed_dates)
    return target.strftime("%B %d, %Y")
