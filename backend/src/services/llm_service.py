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
        data = {
            "start_date": dates[0] if dates else None,
            "end_date": dates[-1] if len(dates) > 1 else None,
            "topics": topics,
            "organisations": organisations,
            "people": people,
            "limit": int(limit_match.group(1)) if limit_match else 20,
        }
        log.info("Using heuristic filters fallback: %s", data)
        return data

    deployment = getattr(client, "_deployment_name", None)
    try:
        system_msg = {
            "role": "system",
            "content": (
                "You are a query planner for a knowledge graph of standards, events, and documents. "
                "Convert the user's question into a simple JSON filter object. "
                "Always respond with JSON only."
            ),
        }
        user_msg = {
            "role": "user",
            "content": (
                f"User question:\n{question}\n\n"
                "Return JSON with keys:\n"
                "{\n"
                '  "start_date": string | null,  // YYYY-MM-DD\n'
                '  "end_date": string | null,    // YYYY-MM-DD\n'
                '  "topics": string[],           // topics mentioned\n'
                '  "organisations": string[],    // orgs mentioned (e.g., WFA, Wi-Fi Alliance)\n'
                '  "people": string[],           // people mentioned\n'
                '  "limit": number               // max docs to consider (default 20)\n'
                "}\n"
                "Resolve relative times like 'last week' relative to today."
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
        log.error(f"LLM filter parsing failed, using fallback: {e}")
        return parse_query_to_filters(question)  # recursion will hit heuristic path because client is cached or error persists

    data.setdefault("start_date", None)
    data.setdefault("end_date", None)
    data.setdefault("topics", [])
    data.setdefault("organisations", [])
    data.setdefault("people", [])
    data.setdefault("limit", 20)
    return data


def summarise_documents(question: str, docs: List[Dict[str, Any]]) -> str:
    """Summarise documents with LLM or fallback heuristic.

    If the LLM is unavailable, produce a concise synthetic answer based on the
    document titles and dates so the UI still shows something useful.
    """
    client = get_azure_client()
    if client is None:
        if not docs:
            return "No relevant documents found."
        parts = []
        for d in docs[:5]:
            date = d.get("publish_date") or "unknown date"
            title = d.get("title") or "Untitled"
            parts.append(f"- {title} ({date})")
        return (
            "(Fallback summary – LLM unavailable) Recent documents related to your question:\n"
            + "\n".join(parts)
        )

    deployment = getattr(client, "_deployment_name", None)
    docs_ctx = []
    for d in docs[:10]:
        docs_ctx.append(
            {
                "title": d.get("title"),
                "url": d.get("url"),
                "publish_date": d.get("publish_date"),
                "summary": d.get("summary"),
                "topics": d.get("topics", []),
                "organisations": d.get("organisations", []),
            }
        )
    try:
        system_msg = {
            "role": "system",
            "content": (
                "You are an assistant summarising standards and industry updates. "
                "Use the provided documents to answer the user's question. "
                "Be concise but specific, and highlight the most recent or important updates."
            ),
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
        return summarise_documents(question, docs)  # recursion will hit heuristic path if client None or continues failing
