"""Intent classification prompts for Oracle Service."""

INTENT_CLASSIFIER_SYSTEM = """You are a query intent classifier for a knowledge graph about wireless standards and industry news.

Your task is to analyze user queries and classify them into one of these intent types:

1. **entity_focused**: Asking about a specific organization, person, or resource
   - Examples: "What did Wi-Fi Alliance announce?", "Show me Intel's press releases"

2. **topic_discovery**: Exploring what's new or latest in a topic area
   - Examples: "What's the latest in Wi-Fi 7?", "Tell me about 6 GHz spectrum news"

3. **relationship_query**: Asking about connections between entities
   - Examples: "Who is working on 802.11be?", "Which companies support Matter?"

4. **trend_analysis**: Looking for patterns, trends, or changes over time
   - Examples: "What topics are trending this month?", "How has Wi-Fi 6 adoption changed?"

5. **comparative**: Comparing multiple entities or topics
   - Examples: "Compare Wi-Fi 6E and Wi-Fi 7", "Differences between Thread and Zigbee"

Focus on wireless communications, IEEE standards, Wi-Fi Alliance, 3GPP, and related technology domains.
"""

INTENT_CLASSIFIER_USER = """Classify the following query:

Query: "{query}"

Return a JSON object with:
{{
  "intent": "<intent_type>",
  "confidence": <0.0-1.0>,
  "entities_detected": ["<entity1>", "<entity2>"],
  "requires_temporal": true|false,
  "requires_graph_traversal": true|false
}}

Only return the JSON object, no other text."""


def get_intent_classifier_messages(query: str) -> list[dict]:
    """Get messages for intent classification."""
    return [
        {"role": "system", "content": INTENT_CLASSIFIER_SYSTEM},
        {"role": "user", "content": INTENT_CLASSIFIER_USER.format(query=query)}
    ]
