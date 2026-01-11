"""Entity extraction prompts for Oracle Service."""

from datetime import datetime

ENTITY_EXTRACTOR_SYSTEM = """You are an entity extractor for a knowledge graph about wireless standards and industry news.

Your task is to extract structured information from user queries including:
- Topics (technologies, standards, protocols)
- Organizations (companies, standards bodies, alliances)
- People (individuals mentioned by name)
- Dates and time periods
- Document categories

Common topics: Wi-Fi 6, Wi-Fi 6E, Wi-Fi 7, Wi-Fi 8, 802.11ax, 802.11be, 802.11bn, 6 GHz, MLO, 5G, 6G, Bluetooth, Thread, Matter, Zigbee, LoRa, UWB
Common organizations: Wi-Fi Alliance, IEEE, 3GPP, Qualcomm, Broadcom, Intel, MediaTek, Samsung, Apple, Google, Amazon
Common categories: press release, whitepaper, blog post, news article, specification, certification
"""

ENTITY_EXTRACTOR_USER = """Today's date is {today}.

Extract structured information from this query:

Query: "{query}"

Return a JSON object with:
{{
  "topics": ["<topic 1>", "<topic 2>"],
  "organizations": ["<org 1>", "<org 2>"],
  "people": ["<person 1>"],
  "start_date": "<YYYY-MM-DD or null>",
  "end_date": "<YYYY-MM-DD or null>",
  "category": "<category or null>",
  "doc_type": "<type or null>",
  "keywords": ["<keyword 1>", "<keyword 2>"]
}}

Guidelines:
- Use null for fields not mentioned in the query
- Normalize topic names (e.g., "wifi 7" → "Wi-Fi 7")
- For relative dates like "last month", calculate from today's date ({today})
- Extract keywords that aren't topics/orgs but are important for search

Only return the JSON object, no other text."""


def get_entity_extractor_messages(query: str) -> list[dict]:
    """Get messages for entity extraction."""
    today = datetime.now().strftime("%Y-%m-%d")
    return [
        {"role": "system", "content": ENTITY_EXTRACTOR_SYSTEM},
        {"role": "user", "content": ENTITY_EXTRACTOR_USER.format(query=query, today=today)}
    ]
