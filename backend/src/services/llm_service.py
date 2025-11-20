import json
import os
import re
import logging
from typing import Any, Dict, List, Optional

try:
    from openai import AzureOpenAI  # type: ignore
except Exception:  # pragma: no cover - library import failures should not break app
    AzureOpenAI = None  # type: ignore

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
        
        data = {
            "start_date": dates[0] if dates else None,
            "end_date": dates[-1] if len(dates) > 1 else None,
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
                "Your goal is to extract structured filters that will retrieve relevant documents from the knowledge graph. "
                "When the user explicitly mentions an organization, topic, or technical standard, ensure it is captured in the filters. "
                "Focus on high-level subjects and topics relevant to wireless communications, standards bodies, and industry organizations. "
                "Always respond with JSON only."
            ),
        }
        user_msg = {
            "role": "user",
            "content": (
                f"User question:\n{question}\n\n"
                "Extract filter information and return JSON with these keys:\n"
                "{\n"
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
                "- Resolve explicit relative dates like 'last week', 'in November 2025' to ISO format (today's date: 2025-11-20)\n"
                "- If the query is broad or exploratory, increase the limit (e.g., 30-50)\n"
                "- Return empty arrays ONLY if the query is asking about knowledge base structure (meta-queries like 'how many topics', 'list all organizations')"
            ),
        }
        resp = client.chat.completions.create(
            model=deployment,
            messages=[system_msg, user_msg],
            temperature=0.0,
            max_tokens=512,
            response_format={"type": "json_object"},
        )
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
        
        data = {
            "start_date": dates[0] if dates else None,
            "end_date": dates[-1] if len(dates) > 1 else None,
            "topics": topics,
            "organisations": organisations,
            "people": people,
            "category": category,
            "doc_type": doc_type,
            "limit": int(limit_match.group(1)) if limit_match else 20,
        }
        log.info("Using heuristic filters due to LLM error: %s", data)
        return data

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
            resp = client.chat.completions.create(
                model=deployment,
                messages=[system_msg, user_msg],
                temperature=0.3,
                max_tokens=500,
            )
            return resp.choices[0].message.content.strip()
        except Exception as e:
            log.error(f"LLM meta-query response failed: {e}")
            return "I cannot provide information about the knowledge base structure at this time."
    
    docs_ctx = []
    for d in docs[:10]:
        # Convert any datetime objects to strings for JSON serialization
        publish_date = d.get("publish_date")
        if publish_date is not None:
            publish_date = _safe_datetime_to_string(publish_date)
            
        docs_ctx.append(
            {
                "title": d.get("title"),
                "url": d.get("url"),
                "publish_date": publish_date,
                "summary": d.get("summary"),
                "topics": d.get("topics", []),
                "organisations": d.get("organisations", []),
            }
        )
    
    # Build system message with preference context if available
    system_content = (
        "You are an assistant that answers questions about wireless standards, industry events, and technical documents. "
        "Your responses must be based ONLY on the provided documents from the knowledge graph. "
        "Do not make up information or hallucinate details not present in the documents. "
        "Be concise but specific, and highlight the most recent or important updates. "
        "Reference specific documents when making claims."
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
        user_msg = {
            "role": "user",
            "content": json.dumps(
                {"user_question": question, "documents": docs_ctx},
                indent=2,
            ),
        }
        resp = client.chat.completions.create(
            model=deployment,
            messages=[system_msg, user_msg],
            temperature=0.3,
            max_tokens=800,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        log.error(f"LLM summarisation failed; using fallback: {e}")
        # Return simple fallback instead of recursion to avoid infinite loop
        if not docs:
            return "No relevant documents found in the knowledge graph."
        parts = []
        for d in docs[:5]:
            date = _safe_datetime_to_string(d.get("publish_date"))
            title = d.get("title") or "Untitled"
            parts.append(f"- {title} ({date})")
        return (
            "(Fallback summary – LLM error) Recent documents related to your question:\n"
            + "\n".join(parts)
        )
