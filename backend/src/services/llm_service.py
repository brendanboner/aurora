import json
import os
import re
import logging
from typing import Any, Dict, List, Optional

try:
    from openai import AzureOpenAI  # type: ignore
except Exception:  # pragma: no cover - library import failures should not break app
    AzureOpenAI = None  # type: ignore

# Import OpenTelemetry instrumentation
from common.llm_instrumentation import instrument_llm_call, create_llm_span_manually
from common.telemetry import get_tracer

_client: Optional[AzureOpenAI] = None

log = logging.getLogger("llm_service")


def _safe_datetime_to_string(value: Any) -> str:
    """Safely convert any datetime-like value to a string.
    
    Handles Neo4j DateTime, Python datetime, strings, and None.
    Returns 'unknown date' for None values.
    """
    if value is None:
        return "unknown date"
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    if isinstance(value, str):
        return value
    return str(value)


def get_azure_client() -> Optional[AzureOpenAI]:
    """Return a cached AzureOpenAI client or None if env/config missing.

    We previously raised a RuntimeError when env vars were absent. That made the
    /query endpoint fail with a 500 and appear like a CORS issue to the UI. Now
    we degrade gracefully: if config is missing we return None and upstream
    logic will apply heuristic fallbacks.
    """
    global _client
    if _client is not None:
        return _client
    if AzureOpenAI is None:
        log.warning("AzureOpenAI library not available; using fallback parsing/summarisation")
        return None

    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

    if not api_key or not endpoint or not deployment:
        log.warning("Azure OpenAI env vars missing; skipping LLM usage")
        return None

    try:
        client = AzureOpenAI(
            api_key=api_key,
            api_version=api_version,
            azure_endpoint=endpoint,
        )
        client._deployment_name = deployment  # type: ignore[attr-defined]
        _client = client
        return client
    except Exception as e:  # network / auth errors
        log.error(f"Failed to initialise Azure OpenAI client: {e}")
        return None


def parse_query_to_filters(question: str) -> Dict[str, Any]:
    """Convert natural language into structured filters.

    If Azure OpenAI is configured, use it. Otherwise perform a lightweight
    heuristic extraction so the system remains usable without the LLM.
    """
    client = get_azure_client()
    if client is None:
        # Heuristic fallback: extract ISO dates, simple integers for limit, and keywords.
        dates = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", question)
        limit_match = re.search(r"\b(?:limit|top)\s+(\d{1,3})\b", question, re.IGNORECASE)
        topics = []
        organisations = []
        people = []
        # Very naive keyword buckets
        lower_q = question.lower()
        if "wifi" in lower_q or "wi-fi" in lower_q:
            topics.append("Wi-Fi")
        if "wfa" in lower_q or "wi-fi alliance" in lower_q:
            organisations.append("Wi-Fi Alliance")
        if "ieee" in lower_q:
            organisations.append("IEEE")
        # Extract category from common keywords
        category = None
        if "press release" in lower_q:
            category = "press release"
        elif "whitepaper" in lower_q or "white paper" in lower_q:
            category = "whitepaper"
        elif "blog" in lower_q:
            category = "blog"
        elif "article" in lower_q:
            category = "article"
        elif "paper" in lower_q:
            category = "paper"
        elif "podcast" in lower_q:
            category = "podcast"
        elif "newsletter" in lower_q:
            category = "newsletter"
        
        # Extract doc_type from common keywords
        doc_type = None
        if "pdf" in lower_q:
            doc_type = "pdf"
        elif "html" in lower_q or "webpage" in lower_q:
            doc_type = "html"
        elif "video" in lower_q:
            doc_type = "video"
        
        # Detect temporal intent from keywords
        query_intent = "recent"  # default
        if any(word in lower_q for word in ["next", "upcoming", "future", "scheduled", "when is"]):
            query_intent = "future"
        elif any(word in lower_q for word in ["last", "past", "previous", "historical", "happened"]):
            query_intent = "historical"
        elif any(word in lower_q for word in ["latest", "recent", "newest", "current"]):
            query_intent = "recent"
        
        # Detect document temporal focus (published vs updated vs mixed)
        temporal_focus = None
        if any(word in lower_q for word in ["updated", "changed", "modified", "revised"]):
            temporal_focus = "updated"
        elif any(word in lower_q for word in ["published", "released", "announced"]):
            temporal_focus = "published"
        elif any(word in lower_q for word in ["happened", "changed or published", "new or updated"]):
            temporal_focus = "mixed"
        
        # Resolve relative dates for document queries
        from datetime import datetime, timedelta
        resolved_start = dates[0] if dates else None
        resolved_end = dates[-1] if len(dates) > 1 else None
        
        if not resolved_start and temporal_focus in ["updated", "published", "mixed"]:
            # Default date ranges for temporal document queries
            if "last week" in lower_q:
                resolved_start = (datetime.now() - timedelta(days=7)).date().isoformat()
                resolved_end = datetime.now().date().isoformat()
            elif "last month" in lower_q:
                resolved_start = (datetime.now() - timedelta(days=30)).date().isoformat()
                resolved_end = datetime.now().date().isoformat()
            elif "last year" in lower_q:
                resolved_start = (datetime.now() - timedelta(days=365)).date().isoformat()
                resolved_end = datetime.now().date().isoformat()
        
        data = {
            "query_intent": query_intent,
            "temporal_focus": temporal_focus,
            "start_date": resolved_start,
            "end_date": resolved_end,
            "topics": topics,
            "organisations": organisations,
            "people": people,
            "category": category,
            "doc_type": doc_type,
            "limit": int(limit_match.group(1)) if limit_match else 20,
        }
        log.info("Using heuristic filters fallback: %s", data)
        return data

    deployment = getattr(client, "_deployment_name", None)
    try:
        system_msg = {
            "role": "system",
            "content": (
                "You are a query planner for a knowledge graph of wireless standards, industry events, and technical documents. "
                "Your goal is to extract structured filters AND determine the temporal intent of the query. "
                "When the user explicitly mentions an organization, topic, or technical standard, ensure it is captured in the filters. "
                "Focus on high-level subjects and topics relevant to wireless communications, standards bodies, and industry organizations. "
                "Pay special attention to temporal keywords like 'next', 'upcoming', 'future', 'scheduled', 'last', 'recent', 'past'. "
                "Always respond with JSON only."
            ),
        }
        user_msg = {
            "role": "user",
            "content": (
                f"User question:\n{question}\n\n"
                "Extract filter information and return JSON with these keys:\n"
                "{\n"
                '  "query_intent": string,       // Temporal intent: "future" (upcoming events), "historical" (past documents), "recent" (latest news), or "mixed" (both)\n'
                '  "temporal_focus": string | null,  // Document temporal focus: "published" (newly published), "updated" (recently changed), "mixed" (both), or null (not temporal)\n'
                '  "start_date": string | null,  // YYYY-MM-DD format\n'
                '  "end_date": string | null,    // YYYY-MM-DD format\n'
                '  "topics": string[],           // Any keywords, locations, events, technologies, standards (e.g., "Dubai", "Wi-Fi 6", "802.11ax", "5G", "upper 6 GHz band", "congress")\n'
                '  "organisations": string[],    // Industry orgs or companies (e.g., "Wi-Fi Alliance", "WFA", "IEEE", "3GPP")\n'
                '  "people": string[],           // People or authors mentioned\n'
                '  "category": string | null,    // Document category (e.g., "press release", "whitepaper", "blog", "article", "paper", "podcast", "newsletter")\n'
                '  "doc_type": string | null,    // File format if specified (e.g., "pdf", "html", "video", "docx")\n'
                '  "limit": number               // max docs to retrieve (default 20, increase for broad queries)\n'
                "}\n\n"
                "Important guidelines:\n"
                "- ALWAYS extract meaningful keywords from the query as topics, including locations (e.g., 'Dubai', 'Europe', 'US'), events (e.g., 'congress', 'conference'), and general terms\n"
                "- When user explicitly mentions an organization (e.g., 'Wi-Fi Alliance', 'WFA', 'IEEE'), include it in organisations\n"
                "- When user mentions a specific technology, standard, or spectrum band (e.g., 'Wi-Fi 6', '802.11ax', '6 GHz', 'RSPG'), include it in topics\n"
                "- Include both formal names and acronyms/identifiers (e.g., 'Wi-Fi Alliance' OR 'WFA', '802.11be' OR 'Wi-Fi 7')\n"
                "- When user asks for a specific document category (e.g., 'press release', 'whitepaper', 'podcast'), set the category\n"
                "- When user specifies file format (e.g., 'PDF documents', 'HTML pages', 'videos'), set the doc_type\n"
                "- Extract ANY relevant keywords that could help find related documents - be inclusive, not restrictive\n"
                "- For queries like 'what is happening in [location]', include the location as a topic\n"
                "- Words like 'latest', 'recent', 'newest' should NOT be converted to date filters - ranking handles recency\n"
                "- Only set date filters for EXPLICIT dates or periods (e.g., 'last week', 'in November', 'since 2024')\n"
                "- Resolve explicit relative dates like 'last week', 'in November 2025' to ISO format (today's date: 2025-11-24)\n"
                "- If the query is broad or exploratory, increase the limit (e.g., 30-50)\n"
                "- Return empty arrays ONLY if the query is asking about knowledge base structure (meta-queries like 'how many topics', 'list all organizations')\n\n"
                "Temporal Intent Detection:\n"
                '- Set query_intent="future" when query asks about upcoming/next/scheduled events, future meetings, or deadlines (e.g., "when is the next WFA meeting", "upcoming conferences")\n'
                '- Set query_intent="historical" when query asks about past events, published documents, or historical analysis (e.g., "what happened last month", "documents from 2024")\n'
                '- Set query_intent="recent" when query asks for latest/newest/recent information without specific dates (e.g., "latest Wi-Fi news", "recent developments")\n'
                '- Set query_intent="mixed" when query combines past and future (e.g., "WFA events this year", "all meetings") OR when temporal intent is unclear\n'
                "- For future-oriented queries, set start_date to today (2025-11-24) to filter upcoming events\n\n"
                "Document Temporal Focus Detection:\n"
                '- Set temporal_focus="updated" when query asks about documents that changed/updated/modified (e.g., "what documents changed last week", "recently updated content")\n'
                '- Set temporal_focus="published" when query asks about newly published/released/announced documents (e.g., "what was published last month", "new press releases")\n'
                '- Set temporal_focus="mixed" when query asks about both published AND updated documents (e.g., "what happened last week", "new or changed documents")\n'
                '- Set temporal_focus=null for non-temporal queries or event-focused queries\n'
                '- When temporal_focus is set, resolve relative dates: "last week" = 7 days ago to today, "last month" = 30 days ago to today, "last year" = 365 days ago to today'
            ),
        }
        
        # Create instrumentation span for LLM call with metrics
        with create_llm_span_manually(prompt_type="query_parse", model_provider="azure_openai") as ctx:
            resp = client.chat.completions.create(
                model=deployment,
                messages=[system_msg, user_msg],
                temperature=0.0,
                max_tokens=512,
                response_format={"type": "json_object"},
            )
            # Record response to emit metrics
            ctx.record_response(resp)
        
        content = resp.choices[0].message.content
        data = json.loads(content)
    except Exception as e:
        log.error(f"LLM filter parsing failed, using heuristic fallback: {e}")
        # Use heuristic fallback instead of recursion to avoid infinite loop
        dates = re.findall(r"\b(20\d{2}-\d{2}-\d{2})\b", question)
        limit_match = re.search(r"\b(?:limit|top)\s+(\d{1,3})\b", question, re.IGNORECASE)
        topics = []
        organisations = []
        people = []
        lower_q = question.lower()
        if "wifi" in lower_q or "wi-fi" in lower_q:
            topics.append("Wi-Fi")
        if "wfa" in lower_q or "wi-fi alliance" in lower_q:
            organisations.append("Wi-Fi Alliance")
        if "ieee" in lower_q:
            organisations.append("IEEE")
        # Extract category from common keywords
        category = None
        if "press release" in lower_q:
            category = "press release"
        elif "whitepaper" in lower_q or "white paper" in lower_q:
            category = "whitepaper"
        elif "blog" in lower_q:
            category = "blog"
        elif "article" in lower_q:
            category = "article"
        elif "paper" in lower_q:
            category = "paper"
        elif "podcast" in lower_q:
            category = "podcast"
        elif "newsletter" in lower_q:
            category = "newsletter"
        
        # Extract doc_type from common keywords
        doc_type = None
        if "pdf" in lower_q:
            doc_type = "pdf"
        elif "html" in lower_q or "webpage" in lower_q:
            doc_type = "html"
        elif "video" in lower_q:
            doc_type = "video"
        
        # Detect temporal intent from keywords
        query_intent = "recent"  # default
        if any(word in lower_q for word in ["next", "upcoming", "future", "scheduled", "when is"]):
            query_intent = "future"
        elif any(word in lower_q for word in ["last", "past", "previous", "historical", "happened"]):
            query_intent = "historical"
        elif any(word in lower_q for word in ["latest", "recent", "newest", "current"]):
            query_intent = "recent"
        
        # Detect document temporal focus (published vs updated vs mixed)
        temporal_focus = None
        if any(word in lower_q for word in ["updated", "changed", "modified", "revised"]):
            temporal_focus = "updated"
        elif any(word in lower_q for word in ["published", "released", "announced"]):
            temporal_focus = "published"
        elif any(word in lower_q for word in ["happened", "changed or published", "new or updated"]):
            temporal_focus = "mixed"
        
        # Resolve relative dates for document queries
        from datetime import datetime, timedelta
        resolved_start = dates[0] if dates else None
        resolved_end = dates[-1] if len(dates) > 1 else None
        
        if not resolved_start and temporal_focus in ["updated", "published", "mixed"]:
            # Default date ranges for temporal document queries
            if "last week" in lower_q:
                resolved_start = (datetime.now() - timedelta(days=7)).date().isoformat()
                resolved_end = datetime.now().date().isoformat()
            elif "last month" in lower_q:
                resolved_start = (datetime.now() - timedelta(days=30)).date().isoformat()
                resolved_end = datetime.now().date().isoformat()
            elif "last year" in lower_q:
                resolved_start = (datetime.now() - timedelta(days=365)).date().isoformat()
                resolved_end = datetime.now().date().isoformat()
        
        data = {
            "query_intent": query_intent,
            "temporal_focus": temporal_focus,
            "start_date": resolved_start,
            "end_date": resolved_end,
            "topics": topics,
            "organisations": organisations,
            "people": people,
            "category": category,
            "doc_type": doc_type,
            "limit": int(limit_match.group(1)) if limit_match else 20,
        }
        log.info("Using heuristic filters due to LLM error: %s", data)
        return data

    data.setdefault("query_intent", "recent")  # default to recent if not specified
    data.setdefault("temporal_focus", None)  # default to null if not specified
    data.setdefault("start_date", None)
    data.setdefault("end_date", None)
    data.setdefault("topics", [])
    data.setdefault("organisations", [])
    data.setdefault("people", [])
    data.setdefault("category", None)
    data.setdefault("doc_type", None)
    data.setdefault("limit", 20)
    
    log.info(f"LLM extracted filters: {data}")
    return data


def summarise_documents(question: str, docs: List[Dict[str, Any]], user_preferences: Optional[Dict[str, Any]] = None) -> str:
    """Summarise documents with LLM or fallback heuristic.

    If the LLM is unavailable, produce a concise synthetic answer based on the
    document titles and dates so the UI still shows something useful.
    
    For meta-queries (when docs is empty), the LLM will answer based on its knowledge
    of the knowledge graph structure and general information.
    
    Args:
        question: The user's natural language question
        docs: Retrieved documents from the knowledge graph (may be empty for meta-queries)
        user_preferences: Optional user preferences (topics, organisations, people)
    """
    client = get_azure_client()
    if client is None:
        if not docs:
            return "I cannot answer questions about the knowledge base without LLM access."
        parts = []
        for d in docs[:5]:
            date = _safe_datetime_to_string(d.get("publish_date"))
            title = d.get("title") or "Untitled"
            parts.append(f"- {title} ({date})")
        return (
            "(Fallback summary – LLM unavailable) Recent documents related to your question:\n"
            + "\n".join(parts)
        )

    deployment = getattr(client, "_deployment_name", None)
    
    # For meta-queries, docs will be empty - we'll ask the LLM to answer based on KB structure
    if not docs:
        try:
            system_msg = {
                "role": "system",
                "content": (
                    "You are an assistant that answers questions about a knowledge graph containing wireless standards, "
                    "industry events, and technical documents. This knowledge graph includes:\n"
                    "- Topics: technical standards (Wi-Fi 6, 802.11ax, 5G, 6 GHz band, etc.), spectrum policy, regulatory bodies\n"
                    "- Organizations: Wi-Fi Alliance (WFA), IEEE, 3GPP, FCC, RSPG, industry companies\n"
                    "- Document types: press releases, whitepapers, blog posts, articles, academic papers, podcasts, newsletters\n"
                    "- File formats: PDF, HTML, video\n\n"
                    "Answer questions about the knowledge base structure, available topics, organizations, and document types. "
                    "Be helpful and informative, but acknowledge that specific counts may vary as the knowledge base grows."
                ),
            }
            user_msg = {
                "role": "user",
                "content": question,
            }
            
            with create_llm_span_manually(
                prompt_type="meta_query",
                model_provider="azure_openai"
            ) as ctx:
                resp = client.chat.completions.create(
                    model=deployment,
                    messages=[system_msg, user_msg],
                    temperature=0.3,
                    max_tokens=500,
                )
                # Record response to emit metrics
                ctx.record_response(resp)
                
            return resp.choices[0].message.content.strip()
        except Exception as e:
            log.error(f"LLM meta-query response failed: {e}")
            return "I cannot provide information about the knowledge base structure at this time."
    
    # Extract events from user_preferences if present
    events = []
    if user_preferences and "events" in user_preferences:
        events = user_preferences.get("events", [])
    
    docs_ctx = []
    for d in docs[:10]:
        # Convert any datetime objects to strings for JSON serialization
        publish_date = d.get("publish_date")
        if publish_date is not None:
            publish_date = _safe_datetime_to_string(publish_date)
        
        # Build enriched context that includes people mentioned with their roles/affiliations
        # This is crucial for "Who is X" queries where person names may not appear in summaries
        people_mentioned = d.get("people", [])
        people_details = d.get("people_details", [])
        orgs_mentioned = d.get("organisations", [])
        
        # Create a richer summary that includes entity mentions with roles
        enriched_summary = d.get("summary", "")
        if people_details or orgs_mentioned:
            entity_context = []
            
            # Add detailed people information with roles/affiliations
            if people_details:
                people_lines = []
                for person in people_details:
                    name = person.get("name", "Unknown")
                    affiliations = person.get("affiliations", [])
                    if affiliations:
                        # Build affiliation strings like "David Coleman (VP, Wi-Fi Alliance)"
                        aff_strs = []
                        for aff in affiliations:
                            role = aff.get("role")
                            org = aff.get("organization")
                            if role and org:
                                aff_strs.append(f"{role} at {org}")
                            elif role:
                                aff_strs.append(role)
                            elif org:
                                aff_strs.append(org)
                        if aff_strs:
                            people_lines.append(f"{name} ({', '.join(aff_strs)})")
                        else:
                            people_lines.append(name)
                    else:
                        people_lines.append(name)
                
                if people_lines:
                    entity_context.append(f"People mentioned: {'; '.join(people_lines)}")
            elif people_mentioned:
                # Fallback to simple list if details aren't available
                entity_context.append(f"People mentioned: {', '.join(people_mentioned)}")
            
            if orgs_mentioned:
                entity_context.append(f"Organizations mentioned: {', '.join(orgs_mentioned)}")
            
            if entity_context:
                enriched_summary = f"{enriched_summary}\n\n{'. '.join(entity_context)}."
            
        docs_ctx.append(
            {
                "title": d.get("title"),
                "url": d.get("url"),
                "publish_date": publish_date,
                "summary": enriched_summary,
                "topics": d.get("topics", []),
                "organisations": orgs_mentioned,
                "people": people_mentioned,
                "people_details": people_details,
            }
        )
    
    # Build events context if available
    events_ctx = []
    if events:
        from datetime import datetime
        today = datetime.now()
        
        for e in events[:5]:  # Limit to top 5 events
            start_date = _safe_datetime_to_string(e.get("start_date"))
            end_date = _safe_datetime_to_string(e.get("end_date"))
            
            # Calculate temporal context (e.g., "in 2 days", "3 weeks ago")
            temporal_context = ""
            if start_date:
                try:
                    event_date = datetime.fromisoformat(start_date.replace('Z', '+00:00'))
                    days_diff = (event_date - today).days
                    if days_diff > 0:
                        if days_diff < 7:
                            temporal_context = f" (in {days_diff} day{'s' if days_diff != 1 else ''})"
                        elif days_diff < 30:
                            weeks = days_diff // 7
                            temporal_context = f" (in {weeks} week{'s' if weeks != 1 else ''})"
                        else:
                            months = days_diff // 30
                            temporal_context = f" (in {months} month{'s' if months != 1 else ''})"
                    elif days_diff < 0:
                        days_ago = abs(days_diff)
                        if days_ago < 7:
                            temporal_context = f" ({days_ago} day{'s' if days_ago != 1 else ''} ago)"
                        elif days_ago < 30:
                            weeks = days_ago // 7
                            temporal_context = f" ({weeks} week{'s' if weeks != 1 else ''} ago)"
                        else:
                            months = days_ago // 30
                            temporal_context = f" ({months} month{'s' if months != 1 else ''} ago)"
                except Exception:
                    pass
            
            events_ctx.append({
                "name": e.get("name"),
                "event_type": e.get("event_type"),
                "start_date": start_date,
                "end_date": end_date,
                "temporal_context": temporal_context,
                "location": e.get("location"),
                "description": e.get("description"),
                "url": e.get("url"),
                "topics": e.get("topics", []),
                "organisations": e.get("organisations", [])
            })
    
    # Build system message with preference context if available
    system_content = (
        "You are an assistant that answers questions about wireless standards, industry events, and technical documents. "
        "Your responses must be based ONLY on the provided documents and events from the knowledge graph. "
        "Do not make up information or hallucinate details not present in the documents/events. "
        "Be concise but specific, and highlight the most recent or important updates. "
        "Reference specific documents or events when making claims."
    )
    
    if events_ctx:
        system_content += (
            "\n\nWhen answering about events, include temporal context (e.g., 'in 2 days', '3 weeks ago') to help users "
            "understand timing. For upcoming events, mention the date, location, and any relevant details."
        )
    
    if user_preferences and any([
        user_preferences.get("topics"),
        user_preferences.get("organisations"),
        user_preferences.get("people")
    ]):
        system_content += (
            "\n\nThe user has expressed interest in: "
        )
        pref_parts = []
        if user_preferences.get("topics"):
            pref_parts.append(f"Topics: {', '.join(user_preferences['topics'][:10])}")
        if user_preferences.get("organisations"):
            pref_parts.append(f"Organizations: {', '.join(user_preferences['organisations'][:10])}")
        if user_preferences.get("people"):
            pref_parts.append(f"People: {', '.join(user_preferences['people'][:10])}")
        system_content += "; ".join(pref_parts) + ". "
        system_content += "Consider these preferences when prioritizing information in your response, but answer based on the query and documents provided."
    
    try:
        system_msg = {
            "role": "system",
            "content": system_content,
        }
        context_data = {
            "user_question": question,
            "documents": docs_ctx
        }
        
        if events_ctx:
            context_data["events"] = events_ctx
        
        user_msg = {
            "role": "user",
            "content": json.dumps(context_data, indent=2),
        }
        
        with create_llm_span_manually(
            prompt_type="summarization",
            model_provider="azure_openai"
        ) as ctx:
            resp = client.chat.completions.create(
                model=deployment,
                messages=[system_msg, user_msg],
                temperature=0.3,
                max_tokens=800,
            )
            # Record response to emit metrics
            ctx.record_response(resp)
            
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"LLM summarisation failed; using fallback: {e}")
        # Return simple fallback instead of recursion to avoid infinite loop
        if not docs:
            return (
                "I couldn't find any documents in our knowledge base to answer your question.\n\n"
                "**Suggestions:**\n"
                "• Try rephrasing with different keywords\n"
                "• Check spelling of technical terms or organization names\n"
                "• Broaden your search criteria\n"
                "• Ask about related topics or industry trends\n\n"
                "Our knowledge base focuses on wireless standards, Wi-Fi technology, and industry news."
            )
        parts = []
        for d in docs[:5]:
            date = _safe_datetime_to_string(d.get("publish_date"))
            title = d.get("title") or "Untitled"
            parts.append(f"- {title} ({date})")
        return (
            "(Fallback summary – LLM error) Recent documents related to your question:\n"
            + "\n".join(parts)
        )
