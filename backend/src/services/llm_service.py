import json
import os
from typing import Any, Dict, List, Optional

from openai import AzureOpenAI

_client: Optional[AzureOpenAI] = None


def get_azure_client() -> AzureOpenAI:
    global _client
    if _client is not None:
        return _client

    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

    if not api_key or not endpoint or not deployment:
        raise RuntimeError("Azure OpenAI env vars are not set")

    client = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint,
    )
    client._deployment_name = deployment
    _client = client
    return client


def parse_query_to_filters(question: str) -> Dict[str, Any]:
    """
    Use Azure OpenAI to convert the natural language question into structured filters.
    """
    client = get_azure_client()
    deployment = client._deployment_name

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

    data.setdefault("start_date", None)
    data.setdefault("end_date", None)
    data.setdefault("topics", [])
    data.setdefault("organisations", [])
    data.setdefault("people", [])
    data.setdefault("limit", 20)

    return data


def summarise_documents(question: str, docs: List[Dict[str, Any]]) -> str:
    """
    Ask Azure OpenAI to summarise the given documents in the context of the question.
    """
    client = get_azure_client()
    deployment = client._deployment_name

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
