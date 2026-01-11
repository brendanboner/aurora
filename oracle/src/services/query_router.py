"""Query Router - Intent classification and strategy selection for Oracle Service."""

from dataclasses import dataclass
import json
import logging
import re
from typing import Optional

from src.models.response import QueryIntent
from src.prompts.intent_classifier import get_intent_classifier_messages
from src.services.llm_client import get_llm_client, call_llm
from src.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class IntentResult:
    """Result of intent classification."""
    intent: QueryIntent
    confidence: float
    entities_detected: list[str]
    requires_temporal: bool
    requires_graph_traversal: bool
    tokens_used: int


class QueryRouter:
    """Routes queries to appropriate retrieval strategies based on intent."""
    
    def __init__(self):
        """Initialize the query router."""
        self.confidence_threshold = settings.intent_confidence_threshold
    
    async def classify_intent(self, query: str) -> IntentResult:
        """
        Classify the intent of a query using LLM.
        
        Falls back to heuristic classification if LLM is unavailable.
        
        Args:
            query: The user's question
            
        Returns:
            IntentResult with classified intent and metadata
        """
        client = get_llm_client()
        
        if client is None:
            logger.info("LLM unavailable, using heuristic intent classification")
            return self._classify_heuristic(query)
        
        try:
            messages = get_intent_classifier_messages(query)
            response = await call_llm(
                client=client,
                messages=messages,
                max_tokens=256,
                temperature=0.1
            )
            
            # Parse the JSON response
            result = self._parse_classification_response(response.content)
            result.tokens_used = response.tokens_used
            
            logger.info(f"LLM classified intent: {result.intent.value} (confidence: {result.confidence:.2f})")
            
            # Fall back to heuristic if confidence is too low
            if result.confidence < self.confidence_threshold:
                logger.info(f"Low confidence ({result.confidence:.2f}), supplementing with heuristic")
                heuristic = self._classify_heuristic(query)
                # Use heuristic if it seems more confident
                if heuristic.confidence > result.confidence:
                    heuristic.tokens_used = result.tokens_used
                    return heuristic
            
            return result
            
        except Exception as e:
            logger.warning(f"LLM classification failed, using heuristic: {e}")
            return self._classify_heuristic(query)
    
    def _parse_classification_response(self, content: str) -> IntentResult:
        """Parse the LLM's JSON response into an IntentResult."""
        try:
            # Clean up the response (remove markdown code blocks if present)
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r'^```\w*\n?', '', content)
                content = re.sub(r'\n?```$', '', content)
            
            data = json.loads(content)
            
            # Map intent string to enum
            intent_str = data.get("intent", "topic_discovery").lower().replace(" ", "_")
            try:
                intent = QueryIntent(intent_str)
            except ValueError:
                logger.warning(f"Unknown intent '{intent_str}', defaulting to topic_discovery")
                intent = QueryIntent.TOPIC_DISCOVERY
            
            return IntentResult(
                intent=intent,
                confidence=float(data.get("confidence", 0.5)),
                entities_detected=data.get("entities_detected", []),
                requires_temporal=data.get("requires_temporal", False),
                requires_graph_traversal=data.get("requires_graph_traversal", False),
                tokens_used=0  # Will be set by caller
            )
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            # Return default result
            return IntentResult(
                intent=QueryIntent.TOPIC_DISCOVERY,
                confidence=0.5,
                entities_detected=[],
                requires_temporal=False,
                requires_graph_traversal=False,
                tokens_used=0
            )
    
    def _classify_heuristic(self, query: str) -> IntentResult:
        """
        Classify query intent using heuristics (fallback when LLM unavailable).
        
        Uses keyword patterns to identify likely intent.
        """
        query_lower = query.lower()
        
        # Entity-focused patterns
        entity_patterns = [
            r'\bwhat did\b.*\b(announce|release|publish)\b',
            r'\bshow me\b.*\b(from|by)\b',
            r'\b(from|by)\b.*\b(alliance|ieee|company)\b',
            r'\bwi-fi alliance\b',
            r'\bieee\b',
            r'\bqualcomm\b',
            r'\bintel\b',
        ]
        
        # Relationship patterns
        relationship_patterns = [
            r'\bwho is\b.*\bworking on\b',
            r'\bwhich (companies|organizations)\b',
            r'\bwho (supports|works|collaborates)\b',
            r'\bconnected to\b',
            r'\brelated to\b',
        ]
        
        # Trend patterns
        trend_patterns = [
            r'\btrending\b',
            r'\btrend\b',
            r'\bover time\b',
            r'\bchanged?\b.*\b(this|last)\b',
            r'\bgrowth\b',
            r'\b(increase|decrease)\b',
        ]
        
        # Comparative patterns
        comparative_patterns = [
            r'\bcompare\b',
            r'\bvs\.?\b',
            r'\bversus\b',
            r'\bdifferences?\b.*\bbetween\b',
            r'\b(better|worse)\b.*\bthan\b',
        ]
        
        # Topic discovery patterns (default)
        topic_patterns = [
            r'\b(latest|recent|new)\b',
            r'\bwhat.*(is|are)\b',
            r'\btell me about\b',
            r'\bwhat.*happening\b',
            r'\bupdates?\b',
        ]
        
        # Check patterns in order of specificity
        for pattern in relationship_patterns:
            if re.search(pattern, query_lower):
                return IntentResult(
                    intent=QueryIntent.RELATIONSHIP_QUERY,
                    confidence=0.7,
                    entities_detected=self._extract_entities_heuristic(query),
                    requires_temporal=False,
                    requires_graph_traversal=True,
                    tokens_used=0
                )
        
        for pattern in trend_patterns:
            if re.search(pattern, query_lower):
                return IntentResult(
                    intent=QueryIntent.TREND_ANALYSIS,
                    confidence=0.7,
                    entities_detected=self._extract_entities_heuristic(query),
                    requires_temporal=True,
                    requires_graph_traversal=False,
                    tokens_used=0
                )
        
        for pattern in comparative_patterns:
            if re.search(pattern, query_lower):
                return IntentResult(
                    intent=QueryIntent.COMPARATIVE,
                    confidence=0.7,
                    entities_detected=self._extract_entities_heuristic(query),
                    requires_temporal=False,
                    requires_graph_traversal=False,
                    tokens_used=0
                )
        
        for pattern in entity_patterns:
            if re.search(pattern, query_lower):
                return IntentResult(
                    intent=QueryIntent.ENTITY_FOCUSED,
                    confidence=0.7,
                    entities_detected=self._extract_entities_heuristic(query),
                    requires_temporal=False,
                    requires_graph_traversal=False,
                    tokens_used=0
                )
        
        # Default to topic discovery
        return IntentResult(
            intent=QueryIntent.TOPIC_DISCOVERY,
            confidence=0.6,
            entities_detected=self._extract_entities_heuristic(query),
            requires_temporal="latest" in query_lower or "recent" in query_lower,
            requires_graph_traversal=False,
            tokens_used=0
        )
    
    def _extract_entities_heuristic(self, query: str) -> list[str]:
        """Extract potential entities from query using simple patterns."""
        entities = []
        query_lower = query.lower()
        
        # Known entities
        known_entities = [
            "Wi-Fi Alliance", "IEEE", "3GPP", "Qualcomm", "Broadcom", "Intel",
            "MediaTek", "Samsung", "Apple", "Google", "Amazon",
            "Wi-Fi 6", "Wi-Fi 6E", "Wi-Fi 7", "802.11ax", "802.11be",
            "6 GHz", "MLO", "5G", "6G", "Bluetooth", "Thread", "Matter",
        ]
        
        for entity in known_entities:
            if entity.lower() in query_lower:
                entities.append(entity)
        
        return entities
    
    def get_retrieval_strategies(self, intent: QueryIntent) -> list[str]:
        """
        Determine which retrieval strategies to use based on intent.
        
        Returns a list of strategy names to execute.
        """
        # Phase 1: Only keyword retrieval
        # Phase 2+: Add vector, graph strategies
        
        strategies = ["keyword"]  # Always include keyword search
        
        # Note: These will be enabled in later phases
        # if intent in [QueryIntent.TOPIC_DISCOVERY, QueryIntent.COMPARATIVE]:
        #     strategies.append("vector")
        # 
        # if intent in [QueryIntent.RELATIONSHIP_QUERY, QueryIntent.ENTITY_FOCUSED]:
        #     strategies.append("graph")
        
        return strategies
