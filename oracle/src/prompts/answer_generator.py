"""Answer generation prompts for Oracle Service."""

from datetime import datetime

# Length/depth instruction injected into the system prompt based on detected detail_level.
_DETAIL_INSTRUCTIONS = {
    "brief":         "**Be concise: 1–2 short paragraphs or a tight bullet list. Maximum 80 words.**",
    "detailed":      "**Be brief and professional: 2–4 short paragraphs or a tight bullet list. Maximum 150 words unless the question genuinely requires more.**",
    "comprehensive": (
        "**The user has explicitly asked for a detailed response — provide one.**\n"
        "- Use 400–600 words. Structure with headers (##) and bullet sub-points where it aids clarity.\n"
        "- Cover background, key technical detail, implications, and any open issues or debates.\n"
        "- Cite every major claim with [n]. Quality over brevity — leave nothing important out."
    ),
}

ANSWER_GENERATOR_SYSTEM = """You are an expert on wireless networking and Wi-Fi technology who has personally attended every Wi-Fi Alliance meeting, reviewed every working group document, and participated in every relevant industry discussion. You speak from deep first-hand knowledge and memory.

**IMPORTANT: Today's date is {current_date}. When users ask about "this month", "this quarter", "upcoming", or "recent" events, use this date as your reference point. "Last month" means the past 30 days — NOT the previous calendar month.**

{data_horizon_block}

Answer questions directly and confidently from the documents provided — treat them as your own meeting notes and reading material. Your rules:
1. Cite specific documents using [1], [2], etc. notation
2. {detail_instruction}
3. Lead with the direct answer — no preamble, no scene-setting
4. For recency questions ("what is new", "latest", "last month", "this month"): if the DATA HORIZON shows content within the past 30 days, that content IS the answer — present it directly. Only use the "I don't have new updates" phrasing when the data horizon is genuinely older than 30 days.
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
Only trigger this if the DATA HORIZON is older than 30 days relative to today. In that case:
- State directly: "I don't have new [topic] updates for [period]."
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

**IMPORTANT: Today's date is {current_date}. When users ask about "this month", "this quarter", "upcoming", or "recent" events, use this date as your reference point. "Last month" means the past 30 days — NOT the previous calendar month.**

{data_horizon_block}

Answer questions directly and confidently from the documents provided — treat them as your own meeting notes and reading material. Your rules:
1. Cite specific documents using [1], [2], etc. notation
2. {detail_instruction}
3. Lead with the direct answer — no preamble, no scene-setting
4. For recency questions ("what is new", "latest", "last month", "this month"): if the DATA HORIZON shows content within the past 30 days, that content IS the answer — present it directly. Only use the "I don't have new updates" phrasing when the data horizon is genuinely older than 30 days.
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
Only trigger this if the DATA HORIZON is older than 30 days relative to today. In that case:
- State directly: "I don't have new [topic] updates for [period]."
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
Answer directly. Cite inline with [1], [2] etc. — do NOT add a reference list or write "URL:", "Title:", "Source:" after the answer. Be brief — facts only, no filler.

**Answer:**"""

ANSWER_GENERATOR_USER_PERSONALIZED = """**Question:** {question}

**Your notes:**
{documents}

**Context:** Topics: {central_topics} | Organisations: {key_organizations} | Temporal: {temporal_patterns}

**User interests (tailor emphasis, not facts):** {user_context}
{conversation_context}
Answer directly. Cite inline with [1], [2] etc. — do NOT add a reference list or write "URL:", "Title:", "Source:" after the answer. Be brief — facts only, no filler.

**Answer:**"""

# Agent persona system prompt — injected when a creator agent @-mentions a question.
# Replaces the generic "meeting attendee" identity while preserving all factual/citation rules.
ANSWER_GENERATOR_SYSTEM_AGENT = """You are {agent_name}, an industry expert and thought leader in wireless networking and Wi-Fi technology. You have personally attended every Wi-Fi Alliance meeting, reviewed every working group document, and participated in every relevant industry discussion — and you answer questions in your distinctive voice and style.

**IMPORTANT: Today's date is {current_date}. When users ask about "this month", "this quarter", "upcoming", or "recent" events, use this date as your reference point.**

{data_horizon_block}

{detail_instruction}

{persona_block}

**Your Writing Style:** {tone_guidance}

**Your Length Preference:** {length_guidance}

{expertise_block}

**FACTUAL RULES — never break these:**
1. Cite specific documents using [1], [2], etc. notation
2. Lead with the direct answer — no preamble
3. For recency questions: if the DATA HORIZON shows content within the past 30 days, present it directly as the current update
4. NEVER fabricate facts not supported by the documents

**STYLE — strictly enforced:**
- Write in your distinctive voice — not a generic analyst
- No filler openers: never start with "Certainly", "Great", "Of course", "Sure", "Absolutely"
- No closing padding: never end with "Let me know if you'd like more detail"
- Facts and citations only — every sentence must add information

**ABSOLUTE RULES:**
- NEVER say "I don't have access to" or reveal internal retrieval
- NEVER tell the user to consult other sources
- NEVER use the phrase "unknown date"
- You ARE the expert — speak with authority from what you know
"""


def _build_agent_persona_system_prompt(
    agent_persona,
    current_date: str,
    data_horizon_block: str,
    detail_instruction: str,
) -> str:
    """Build a system prompt flavoured with the creator agent's persona and style."""
    tone_guidance_map = {
        "analytical": "Provide data-driven insights with clear reasoning. Use numbers, comparisons, and evidence-based conclusions.",
        "conversational": "Share insights like explaining to a colleague. Be approachable, use personal observations, keep jargon minimal.",
        "technical": "Dive deep into technical details while staying readable. Use specific terminology correctly and explain implications.",
        "journalistic": "Report on developments objectively, then add your expert take. Separate facts from interpretation clearly.",
        "opinion": "Lead with your distinctive perspective, back it up with facts. Own your viewpoint while acknowledging complexity.",
    }
    length_guidance_map = {
        "short": "Keep responses concise: 2–3 short paragraphs. Get to the point quickly.",
        "medium": "Write 3–5 paragraphs. Balance depth with readability.",
        "long": "Develop comprehensive answers. Include examples, nuances, and thorough analysis.",
    }

    persona_block = ""
    if agent_persona.persona:
        persona_block = (
            f"{'=' * 60}\n"
            f"YOUR UNIQUE PROFESSIONAL IDENTITY:\n"
            f"{'=' * 60}\n"
            f"{agent_persona.persona}\n"
            f"{'=' * 60}"
        )

    expertise_parts = []
    if agent_persona.expertise_topics:
        expertise_parts.append(f"**Topic specialisms:** {', '.join(agent_persona.expertise_topics)}")
    if agent_persona.expertise_organisations:
        expertise_parts.append(f"**Organisations you follow closely:** {', '.join(agent_persona.expertise_organisations)}")
    if agent_persona.expertise_standards:
        expertise_parts.append(f"**Standards bodies you cover:** {', '.join(agent_persona.expertise_standards)}")
    expertise_block = "\n".join(expertise_parts) if expertise_parts else ""

    return ANSWER_GENERATOR_SYSTEM_AGENT.format(
        agent_name=agent_persona.name,
        current_date=current_date,
        data_horizon_block=data_horizon_block,
        detail_instruction=detail_instruction,
        persona_block=persona_block,
        tone_guidance=tone_guidance_map.get(agent_persona.tone_style, "Maintain a professional, thoughtful tone."),
        length_guidance=length_guidance_map.get(agent_persona.content_length_preference, "Write 3–5 balanced paragraphs."),
        expertise_block=expertise_block,
    )


def format_documents_for_prompt(documents: list[dict]) -> str:
    """Format documents for inclusion in the answer generation prompt."""
    if not documents:
        return "No documents retrieved."
    
    formatted = []
    for i, doc in enumerate(documents, 1):
        title = doc.get("title", "Untitled")
        summary = doc.get("summary", "No summary available.")
        raw_date = doc.get("publish_date")
        url = doc.get("url", "")
        topics = ", ".join(doc.get("topics", [])) or "None"
        orgs = ", ".join(doc.get("organizations", [])) or "None"
        datasource = doc.get("datasource_id", "Unknown source")
        
        # Build a date label that never leaks scraped_at as a fake publish date.
        # temporal_confidence='low' means no valid publish_date was found — the
        # document should be treated as reference material, not as recent news.
        temporal_confidence = doc.get("temporal_confidence", "high")
        if raw_date and raw_date not in ("", "Unknown date", "unknown"):
            date_display = raw_date
        elif temporal_confidence == "low":
            date_display = "publication date unknown — treat as reference material, not recent news"
        else:
            date_display = "date not recorded"
        
        # URL is intentionally not labeled here — the LLM echoes labeled fields
        # (e.g. "URL:") verbatim into the answer text, producing "[2]URL: ..." noise.
        formatted.append(f"""[{i}] **{title}** ({datasource}, {date_display})
   {url}
   Topics: {topics} | Orgs: {orgs}
   {summary}
""")
    
    return "\n".join(formatted)


def get_answer_generator_messages(
    question: str,
    documents: list[dict],
    graph_context: dict | None = None,
    user_context: str | None = None,
    conversation_history: list[dict] | None = None,
    detail_level: str = "detailed",
    agent_persona=None,
) -> list[dict]:
    """Get messages for answer generation.
    
    Args:
        question: User's question
        documents: Retrieved documents
        graph_context: Graph context dict
        user_context: Optional user context string for personalization
        conversation_history: Optional list of prior {role, content} turns
        detail_level: One of 'brief', 'detailed', 'comprehensive'
        agent_persona: Optional AgentPersona — when set, answer is generated in the agent's voice
        
    Returns:
        List of messages for LLM chat completion
    """
    detail_instruction = _DETAIL_INSTRUCTIONS.get(detail_level, _DETAIL_INSTRUCTIONS["detailed"])

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
    now = datetime.now()
    current_date = now.strftime("%B %d, %Y")  # e.g., "February 03, 2026"

    # Extract data horizon from documents.
    # Returns None when no usable dates found — avoids leaking "unknown date" into the answer.
    data_horizon = _extract_data_horizon(documents)
    data_oldest = _extract_data_oldest(documents)

    # Build the DATA HORIZON block conditionally so "unknown date" never appears in the prompt.
    if data_horizon:
        # Compute age of the most recent document so we can tell the LLM
        # whether the retrieved content is "fresh" (within the last 30 days)
        # or genuinely stale.
        from dateutil.parser import parse as _dp
        try:
            _horizon_dt = _dp(data_horizon)
            _horizon_age_days = (now - _horizon_dt).days
        except Exception:
            _horizon_age_days = 999  # treat as old if unparseable

        _oldest_clause = (
            f" The oldest is from {data_oldest}."
            if data_oldest and data_oldest != data_horizon else ""
        )

        if _horizon_age_days <= 30:
            # Data IS fresh — the retrieved documents are the answer to any
            # recency question. Tell the LLM explicitly so it doesn't trigger
            # the "no new content" fallback.
            data_horizon_block = (
                f"**DATA HORIZON: The most recent document in your notes is from {data_horizon}"
                f" ({_horizon_age_days} day(s) ago).{_oldest_clause}**\n"
                f"- **RECENCY MATCH:** This document is within the past 30 days. "
                f"When the user asks \"what is new\", \"what happened last month\", "
                f"\"recent updates\", or similar, the retrieved documents ARE the answer — "
                f"present their content directly as the current update. "
                f"Do NOT say \"I don't have new updates for [period]\" when the content is this fresh."
            )
        else:
            # Data is genuinely older than 30 days — use the anchoring / fallback behaviour.
            data_horizon_block = (
                f"**DATA HORIZON: The most recent document in your notes is from {data_horizon}"
                f" ({_horizon_age_days} day(s) ago).{_oldest_clause}**\n"
                f"- If a question asks about events after {data_horizon}, anchor your answer: "
                f"\"The most recent information I have is from {data_horizon}...\" — "
                f"never imply more currency than your documents support.\n"
                f"- For recency questions (\"what is new this month/week/year\"), note that "
                f"your most recent information is from {data_horizon}."
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

    # Choose prompts: agent persona > personalization > generic
    if agent_persona is not None:
        # Agent voice mode — use the creator agent's persona, tone and expertise
        system_prompt = _build_agent_persona_system_prompt(
            agent_persona=agent_persona,
            current_date=current_date,
            data_horizon_block=data_horizon_block,
            detail_instruction=detail_instruction,
        )
        user_content = ANSWER_GENERATOR_USER.format(
            question=question,
            documents=docs_text,
            central_topics=central_topics,
            key_organizations=key_orgs,
            temporal_patterns=temporal,
            conversation_context=conversation_context,
        )
    elif user_context:
        system_prompt = ANSWER_GENERATOR_SYSTEM_PERSONALIZED.format(
            current_date=current_date,
            data_horizon_block=data_horizon_block,
            detail_instruction=detail_instruction,
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
            detail_instruction=detail_instruction,
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
            # Strip timezone info to ensure all datetimes are comparable (naive)
            if hasattr(result, 'tzinfo') and result.tzinfo is not None:
                result = result.replace(tzinfo=None)
            if result.year < 2000 or result.year > _current_year + 1:
                return None
            return result
        except Exception:
            return None

    parsed_dates: list[datetime] = []
    for doc in documents:
        # Only use authoritative publication dates — never scraped_at or created_at.
        # A document with only scraped_at has an unknown publication date; falling
        # back to scraped_at would make a 2019 document scraped today appear as
        # "most recent content from today", poisoning recency answers.
        for field in ("publish_date", "start_date"):
            dt = _parse_safe(doc.get(field))
            if dt is not None:
                parsed_dates.append(dt)
                break  # use first valid date for this document

    if not parsed_dates:
        return None

    target = max(parsed_dates) if newest else min(parsed_dates)
    return target.strftime("%B %d, %Y")
