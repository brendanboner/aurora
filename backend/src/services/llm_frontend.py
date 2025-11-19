import json
import os
import logging
from typing import Any, Dict, List, Optional

from openai import AzureOpenAI

from neo4j_client.client import Neo4jClient
from neo4j_client.repository import GraphRepository

logger = logging.getLogger(__name__)


# ---------- Azure OpenAI client ----------

_azure_client: Optional[AzureOpenAI] = None


def get_azure_client() -> AzureOpenAI:
    global _azure_client
    if _azure_client is not None:
        return _azure_client

    api_key = os.getenv("AZURE_OPENAI_API_KEY")
    endpoint = os.getenv("AZURE_OPENAI_ENDPOINT")
    api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview")
    deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT")

    if not api_key or not endpoint or not deployment:
        raise RuntimeError("Azure OpenAI env vars not set (AZURE_OPENAI_*).")

    client = AzureOpenAI(
        api_key=api_key,
        api_version=api_version,
        azure_endpoint=endpoint,
    )
    client._deployment_name = deployment  # stash for convenience
    _azure_client = client
    return client


def _chat_json_prompt(messages: List[Dict[str, str]], temperature: float = 0.0) -> Dict[str, Any]:
    client = get_azure_client()
    deployment = client._deployment_name

    resp = client.chat.completions.create(
        model=deployment,
        messages=messages,
        temperature=temperature,
        max_tokens=512,
        response_format={"type": "json_object"},
    )
    content = resp.choices[0].message.content
    return json.loads(content)


# ---------- Neo4j repo helper ----------

def get_graph_repo() -> GraphRepository:
    uri = os.getenv("NEO4J_URI", "bolt://localhost:7687")
    user = os.getenv("NEO4J_USER", "neo4j")
    password = os.getenv("NEO4J_PASSWORD", "neo4j")
    database = os.getenv("NEO4J_DATABASE", "neo4j")

    client = Neo4jClient(uri=uri, user=user, password=password, database=database)
    return GraphRepository(client)


# ---------- LLM front-end API ----------

def parse_user_query(nl_query: str, client: Optional[AzureOpenAI] = None) -> Dict[str, Any]:
    """
    Use Azure OpenAI to turn a natural language question into structured filters.

    Returns dict like:
        {
          "start_date": "2025-11-10",
          "end_date": "2025-11-17",
          "topics": ["wifi 7", "3gpp"],
          "organisations": ["3gpp", "wi-fi alliance"],
          "people": [],
          "limit": 20
        }
    """
    if client is None:
        client = get_azure_client()
    deployment = client._deployment_name

    system_msg = {
        "role": "system",
        "content": (
            "You are a query planner for a knowledge graph. "
            "Your job is to convert a user's question into structured filters. "
            "Always answer with a JSON object and nothing else."
        ),
    }

    user_msg = {
        "role": "user",
        "content": (
            f"User question:\n{nl_query}\n\n"
            "Return JSON with these fields:\n"
            "{\n"
            '  "start_date": string | null,  // YYYY-MM-DD, inferred time window start\n'
            '  "end_date": string | null,    // YYYY-MM-DD, inferred time window end\n'
            '  "topics": string[],           // topic names or identifiers\n'
            '  "organisations": string[],    // org names (e.g., IEEE, 3GPP, Wi-Fi Alliance)\n'
            '  "people": string[],           // person names if relevant\n'
            '  "limit": number               // max number of documents to return (default 20)\n'
            "}\n"
            "If dates are vague like 'last week', resolve them relative to today and fill start_date/end_date. "
            "If the user doesn't specify dates, leave start_date/end_date as null."
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
    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        logger.error("Failed to parse LLM JSON: %s", content)
        raise

    # Normalise / defaults
    data.setdefault("start_date", None)
    data.setdefault("end_date", None)
    data.setdefault("topics", [])
    data.setdefault("organisations", [])
    data.setdefault("people", [])
    data.setdefault("limit", 20)

    return data


def summarise_results(
    nl_query: str,
    resources: List[Dict[str, Any]],
    client: Optional[AzureOpenAI] = None,
) -> str:
    """
    Ask the LLM to summarise the set of resources for the user.

    resources is the raw list returned by GraphRepository.get_recent_resources().
    """
    if client is None:
        client = get_azure_client()
    deployment = client._deployment_name

    # Build a compact context
    docs_context = []
    for row in resources:
        r = row["resource"]
        topics = [t.get("name") for t in row.get("topics", []) if t.get("name")]
        orgs = [o.get("name") for o in row.get("organisations", []) if o.get("name")]

        docs_context.append(
            {
                "title": r.get("title"),
                "url": r.get("url"),
                "publish_date": r.get("publish_date"),
                "summary": r.get("summary"),
                "topics": topics,
                "organisations": orgs,
            }
        )

    system_msg = {
        "role": "system",
        "content": (
            "You are a concise analyst for standards and industry events. "
            "The user sees both a list of documents and your summary. "
            "Focus on the most important changes, trends, and upcoming actions."
        ),
    }

    user_msg = {
        "role": "user",
        "content": json.dumps(
            {
                "user_question": nl_query,
                "documents": docs_context,
            },
            indent=2,
        ),
    }

    resp = client.chat.completions.create(
        model=deployment,
        messages=[system_msg, user_msg],
        temperature=0.2,
        max_tokens=700,
    )
    return resp.choices[0].message.content.strip()


def run_semantic_query(nl_query: str) -> Dict[str, Any]:
    """
    High-level API for the CLI:

    1. Parse NL query into filters
    2. Query Neo4j for matching resources
    3. Summarise results with LLM

    Returns:
        {
          "filters": {...},
          "resources": [...],
          "summary": "..."
        }
    """
    filters = parse_user_query(nl_query)
    repo = get_graph_repo()

    resources = repo.get_recent_resources(
        start=filters.get("start_date"),
        end=filters.get("end_date"),
        topics=filters.get("topics") or [],
        organisations=filters.get("organisations") or [],
        people=filters.get("people") or [],
        limit=int(filters.get("limit") or 20),
    )

    summary = summarise_results(nl_query, resources)

    return {
        "filters": filters,
        "resources": resources,
        "summary": summary,
    }
