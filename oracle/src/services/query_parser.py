"""Query Parser - Entity and filter extraction for Oracle Service."""

from dataclasses import dataclass
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional

from src.prompts.entity_extractor import get_entity_extractor_messages
from src.services.llm_client import get_llm_client, call_llm
from src.settings import settings

logger = logging.getLogger(__name__)


@dataclass
class ParsedQuery:
    """Result of query parsing."""
    topics: list[str]
    organizations: list[str]
    people: list[str]
    start_date: Optional[str]
    end_date: Optional[str]
    category: Optional[str]
    doc_type: Optional[str]
    keywords: list[str]
    tokens_used: int
    # Track resolution metadata
    entities_resolved: bool = False
    unresolved_entities: list[str] = None
    
    def __post_init__(self):
        if self.unresolved_entities is None:
            self.unresolved_entities = []


class QueryParser:
    """Parses queries to extract entities, dates, and filters."""
    
    def __init__(self, resolve_entities: bool = None):
        """
        Initialize the query parser.
        
        Args:
            resolve_entities: Whether to resolve entities against the graph 
                            (default: from settings.entity_resolution_enabled)
        """
        if resolve_entities is None:
            resolve_entities = settings.entity_resolution_enabled
        self.resolve_entities = resolve_entities
    
    async def parse(self, query: str, resolve_against_graph: bool = None) -> ParsedQuery:
        """
        Parse a query to extract structured filters.
        
        Uses LLM for extraction with heuristic fallback.
        Optionally resolves extracted entities against the knowledge graph.
        
        Args:
            query: The user's question
            resolve_against_graph: Override instance setting for entity resolution
            
        Returns:
            ParsedQuery with extracted entities and filters
        """
        should_resolve = resolve_against_graph if resolve_against_graph is not None else self.resolve_entities
        
        client = get_llm_client()
        
        if client is None:
            logger.info("LLM unavailable, using heuristic parsing")
            result = self._parse_heuristic(query)
        else:
            try:
                messages = get_entity_extractor_messages(query)
                response = await call_llm(
                    client=client,
                    messages=messages,
                    max_tokens=512,
                    temperature=0.1
                )
                
                result = self._parse_extraction_response(response.content)
                result.tokens_used = response.tokens_used
                
            except Exception as e:
                logger.warning(f"LLM parsing failed, using heuristic: {e}")
                result = self._parse_heuristic(query)
        
        # Resolve entities against the graph if enabled
        if should_resolve and (result.topics or result.organizations or result.people):
            result = await self._resolve_entities(result)
        
        logger.info(f"Parsed query: topics={result.topics}, orgs={result.organizations}, resolved={result.entities_resolved}")
        return result
    
    async def _resolve_entities(self, parsed: ParsedQuery) -> ParsedQuery:
        """
        Resolve extracted entities against the knowledge graph.
        
        This matches candidate entity names to actual graph nodes,
        handling typos, aliases, and variations.
        """
        try:
            from src.services.entity_resolver import EntityResolver
            
            resolver = EntityResolver()
            resolution = await resolver.resolve(
                topics=parsed.topics,
                organizations=parsed.organizations,
                people=parsed.people,
            )
            
            # Update parsed result with resolved entity names
            parsed.topics = [r.resolved for r in resolution.topics]
            parsed.organizations = [r.resolved for r in resolution.organizations]
            parsed.people = [r.resolved for r in resolution.people]
            parsed.entities_resolved = True
            parsed.unresolved_entities = resolution.unresolved
            
            if resolution.unresolved:
                logger.info(f"Some entities could not be resolved: {resolution.unresolved}")
            
            return parsed
            
        except Exception as e:
            logger.warning(f"Entity resolution failed, using original entities: {e}")
            parsed.entities_resolved = False
            return parsed
    
    def _parse_extraction_response(self, content: str) -> ParsedQuery:
        """Parse the LLM's JSON response into a ParsedQuery."""
        try:
            # Clean up the response
            content = content.strip()
            if content.startswith("```"):
                content = re.sub(r'^```\w*\n?', '', content)
                content = re.sub(r'\n?```$', '', content)
            
            data = json.loads(content)
            
            return ParsedQuery(
                topics=data.get("topics") or [],
                organizations=data.get("organizations") or [],
                people=data.get("people") or [],
                start_date=data.get("start_date"),
                end_date=data.get("end_date"),
                category=data.get("category"),
                doc_type=data.get("doc_type"),
                keywords=data.get("keywords") or [],
                tokens_used=0
            )
            
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            return ParsedQuery(
                topics=[],
                organizations=[],
                people=[],
                start_date=None,
                end_date=None,
                category=None,
                doc_type=None,
                keywords=[],
                tokens_used=0
            )
    
    def _parse_heuristic(self, query: str) -> ParsedQuery:
        """
        Parse query using heuristics (fallback when LLM unavailable).
        """
        query_lower = query.lower()
        
        # Extract topics
        topics = []
        topic_patterns = {
            r'\bwi-?fi\s*8\b': 'Wi-Fi 8',
            r'\b802\.11bn\b': '802.11bn',
            r'\bwi-?fi\s*7\b': 'Wi-Fi 7',
            r'\bwi-?fi\s*6e?\b': 'Wi-Fi 6E',
            r'\bwi-?fi\s*6\b': 'Wi-Fi 6',
            r'\b802\.11be\b': '802.11be',
            r'\b802\.11ax\b': '802.11ax',
            r'\b6\s*ghz\b': '6 GHz',
            r'\bmlo\b': 'MLO',
            r'\b5g\b': '5G',
            r'\b6g\b': '6G',
            r'\bbluetooth\b': 'Bluetooth',
            r'\bthread\b': 'Thread',
            r'\bmatter\b': 'Matter',
            r'\bzigbee\b': 'Zigbee',
            r'\blora\b': 'LoRa',
            r'\buwb\b': 'UWB',
        }
        
        for pattern, topic in topic_patterns.items():
            if re.search(pattern, query_lower):
                topics.append(topic)
        
        # Extract organizations
        organizations = []
        org_patterns = {
            r'\bwi-?fi\s*alliance\b': 'Wi-Fi Alliance',
            r'\bwfa\b': 'Wi-Fi Alliance',
            r'\bieee\b': 'IEEE',
            r'\b3gpp\b': '3GPP',
            r'\bqualcomm\b': 'Qualcomm',
            r'\bbroadcom\b': 'Broadcom',
            r'\bintel\b': 'Intel',
            r'\bmediatek\b': 'MediaTek',
            r'\bsamsung\b': 'Samsung',
            r'\bapple\b': 'Apple',
            r'\bgoogle\b': 'Google',
            r'\bamazon\b': 'Amazon',
        }
        
        for pattern, org in org_patterns.items():
            if re.search(pattern, query_lower):
                organizations.append(org)
        
        # Extract dates
        start_date, end_date = self._extract_dates_heuristic(query)
        
        # Extract category
        category = None
        if 'press release' in query_lower:
            category = 'press release'
        elif 'whitepaper' in query_lower or 'white paper' in query_lower:
            category = 'whitepaper'
        elif 'blog' in query_lower:
            category = 'blog post'
        elif 'news' in query_lower:
            category = 'news article'
        
        # Extract keywords (words that aren't stopwords or already extracted)
        keywords = self._extract_keywords(query, topics, organizations)
        
        return ParsedQuery(
            topics=topics,
            organizations=organizations,
            people=[],  # Hard to extract without NER
            start_date=start_date,
            end_date=end_date,
            category=category,
            doc_type=None,
            keywords=keywords,
            tokens_used=0
        )
    
    def _extract_dates_heuristic(self, query: str) -> tuple[Optional[str], Optional[str]]:
        """Extract date ranges from query text."""
        query_lower = query.lower()
        today = datetime.now()
        
        # ISO dates
        iso_dates = re.findall(r'\b(20\d{2}-\d{2}-\d{2})\b', query)
        if len(iso_dates) >= 2:
            return iso_dates[0], iso_dates[1]
        elif len(iso_dates) == 1:
            return iso_dates[0], None
        
        # Relative dates
        if 'last week' in query_lower:
            start = (today - timedelta(days=7)).strftime('%Y-%m-%d')
            return start, today.strftime('%Y-%m-%d')
        
        if 'last month' in query_lower:
            start = (today - timedelta(days=30)).strftime('%Y-%m-%d')
            return start, today.strftime('%Y-%m-%d')
        
        if 'last quarter' in query_lower or 'past quarter' in query_lower:
            start = (today - timedelta(days=90)).strftime('%Y-%m-%d')
            return start, today.strftime('%Y-%m-%d')
        
        if 'last year' in query_lower:
            start = (today - timedelta(days=365)).strftime('%Y-%m-%d')
            return start, today.strftime('%Y-%m-%d')
        
        if 'this week' in query_lower:
            # Start of current week (Monday)
            start = (today - timedelta(days=today.weekday())).strftime('%Y-%m-%d')
            return start, today.strftime('%Y-%m-%d')
        
        if 'this month' in query_lower:
            start = today.replace(day=1).strftime('%Y-%m-%d')
            return start, today.strftime('%Y-%m-%d')
        
        if 'this year' in query_lower:
            start = today.replace(month=1, day=1).strftime('%Y-%m-%d')
            return start, today.strftime('%Y-%m-%d')
        
        # "latest" or "recent" implies recent documents
        if 'latest' in query_lower or 'recent' in query_lower:
            start = (today - timedelta(days=30)).strftime('%Y-%m-%d')
            return start, None
        
        return None, None
    
    def _extract_keywords(
        self,
        query: str,
        topics: list[str],
        organizations: list[str]
    ) -> list[str]:
        """Extract significant keywords from query."""
        # Stopwords to ignore
        stopwords = {
            'a', 'an', 'the', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
            'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'could',
            'should', 'may', 'might', 'must', 'shall', 'can', 'need', 'dare',
            'ought', 'used', 'to', 'of', 'in', 'for', 'on', 'with', 'at', 'by',
            'from', 'as', 'into', 'through', 'during', 'before', 'after',
            'above', 'below', 'between', 'under', 'again', 'further', 'then',
            'once', 'here', 'there', 'when', 'where', 'why', 'how', 'all',
            'each', 'few', 'more', 'most', 'other', 'some', 'such', 'no', 'nor',
            'not', 'only', 'own', 'same', 'so', 'than', 'too', 'very', 'just',
            'and', 'but', 'if', 'or', 'because', 'until', 'while', 'what',
            'which', 'who', 'whom', 'this', 'that', 'these', 'those', 'am',
            'me', 'my', 'myself', 'we', 'our', 'ours', 'you', 'your', 'yours',
            'he', 'him', 'his', 'she', 'her', 'hers', 'it', 'its', 'they',
            'them', 'their', 'theirs', 'about', 'show', 'tell', 'give', 'get',
            'latest', 'recent', 'new', 'old', 'last', 'first',
        }
        
        # Already extracted entities (lowercase for comparison)
        extracted = set(t.lower() for t in topics + organizations)
        
        # Extract words
        words = re.findall(r'\b[a-zA-Z]{3,}\b', query.lower())
        
        keywords = []
        for word in words:
            if word not in stopwords and word not in extracted:
                keywords.append(word)
        
        # Deduplicate while preserving order
        seen = set()
        unique_keywords = []
        for kw in keywords:
            if kw not in seen:
                seen.add(kw)
                unique_keywords.append(kw)
        
        return unique_keywords[:5]  # Limit to 5 keywords
