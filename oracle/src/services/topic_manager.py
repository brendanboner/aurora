"""
TopicManager: Dynamic topic extraction and management for Aurora query system.

This module provides intelligent topic detection by:
1. Loading existing topics from Neo4j knowledge graph
2. Auto-creating Topic nodes for frequently searched terms
3. Supporting aliases and fuzzy matching
4. Refreshing topic cache periodically

Replaces hardcoded topic keywords with dynamic graph-based approach.
"""

import logging
import re
from collections import defaultdict
from datetime import datetime, timedelta
from typing import List, Set, Dict, Optional
from threading import Lock

logger = logging.getLogger(__name__)


class TopicManager:
    """
    Manages dynamic topic extraction from Neo4j knowledge graph.
    
    Features:
    - Loads topics and aliases from Neo4j
    - Tracks search frequency for rare terms
    - Auto-creates Topic nodes after threshold (10 searches)
    - Hourly cache refresh
    - Thread-safe operations
    """
    
    def __init__(self, neo4j_client, refresh_interval_hours: int = 1, auto_create_threshold: int = 10):
        """
        Initialize TopicManager.
        
        Args:
            neo4j_client: Neo4j client for graph queries
            refresh_interval_hours: How often to reload topics from graph
            auto_create_threshold: Number of searches before auto-creating topic
        """
        self.neo4j_client = neo4j_client
        self.refresh_interval = timedelta(hours=refresh_interval_hours)
        self.auto_create_threshold = auto_create_threshold
        
        # Topic cache: {normalized_name: [original_name, alias1, alias2, ...]}
        self.topic_cache: Dict[str, List[str]] = {}
        self.last_refresh: Optional[datetime] = None
        
        # Search frequency tracking for auto-creation
        self.search_frequency: Dict[str, int] = defaultdict(int)
        
        # Thread safety
        self.lock = Lock()
        
        # Initial load
        self._refresh_topics()
    
    def _normalize(self, text: str) -> str:
        """Normalize text for matching: lowercase, strip, collapse spaces."""
        return re.sub(r'\s+', ' ', text.lower().strip())
    
    def _refresh_topics(self) -> None:
        """Load all topics and aliases from Neo4j."""
        try:
            query = """
            MATCH (t:Topic)
            RETURN t.name AS name, t.aliases AS aliases
            """
            results = self.neo4j_client.execute_query(query)
            
            new_cache = {}
            for record in results:
                name = record.get('name')
                if not name:
                    continue
                
                # Store original name + all aliases
                variations = [name]
                aliases = record.get('aliases', [])
                if aliases and isinstance(aliases, list):
                    variations.extend(aliases)
                
                # Index by normalized form
                normalized = self._normalize(name)
                new_cache[normalized] = variations
                
                # Also index aliases
                for alias in aliases:
                    if alias:
                        norm_alias = self._normalize(alias)
                        if norm_alias not in new_cache:
                            new_cache[norm_alias] = variations
            
            with self.lock:
                self.topic_cache = new_cache
                self.last_refresh = datetime.utcnow()
            
            logger.info(f"Loaded {len(new_cache)} topics from Neo4j")
            
        except Exception as e:
            logger.error(f"Failed to refresh topics from Neo4j: {e}")
            # Keep existing cache on error
    
    def _should_refresh(self) -> bool:
        """Check if cache needs refresh."""
        if not self.last_refresh:
            return True
        return datetime.utcnow() - self.last_refresh > self.refresh_interval
    
    def _auto_create_topic(self, term: str) -> None:
        """
        Auto-create Topic node in Neo4j for frequently searched terms.
        
        Args:
            term: The term to create as a Topic node
        """
        try:
            query = """
            MERGE (t:Topic {name: $name})
            ON CREATE SET t.created_at = datetime(),
                         t.auto_created = true,
                         t.source = 'query_frequency'
            RETURN t.name AS name
            """
            result = self.neo4j_client.run_query(query, {'name': term})
            
            if result:
                logger.info(f"Auto-created Topic node for '{term}' (searched {self.search_frequency[term]} times)")
                # Add to cache immediately
                normalized = self._normalize(term)
                with self.lock:
                    self.topic_cache[normalized] = [term]
            
        except Exception as e:
            logger.error(f"Failed to auto-create topic '{term}': {e}")
    
    def extract_topics(self, question: str) -> List[str]:
        """
        Extract topics from question text.
        
        Strategy:
        1. Check if cache needs refresh
        2. Match against known topics (exact and fuzzy)
        3. Track frequency of unmatched terms
        4. Auto-create topics for frequent terms
        
        Args:
            question: User's question text
        
        Returns:
            List of matched topic names
        """
        # Refresh cache if needed
        if self._should_refresh():
            self._refresh_topics()
        
        question_lower = self._normalize(question)
        matched_topics = set()
        
        # Extract potential definition queries: "What is X?", "Define X", etc.
        definition_patterns = [
            r'what\s+(?:is|are|was|were)\s+(?:a|an|the)?\s*([a-zA-Z0-9\s\-_]+?)(?:\?|$)',
            r'define\s+(?:a|an|the)?\s*([a-zA-Z0-9\s\-_]+?)(?:\?|$)',
            r'explain\s+(?:a|an|the)?\s*([a-zA-Z0-9\s\-_]+?)(?:\?|$)',
            r'tell\s+me\s+about\s+(?:a|an|the)?\s*([a-zA-Z0-9\s\-_]+?)(?:\?|$)',
        ]
        
        definition_terms = []
        for pattern in definition_patterns:
            matches = re.finditer(pattern, question_lower)
            for match in matches:
                term = match.group(1).strip()
                if len(term) > 2:  # Avoid very short terms
                    definition_terms.append(term)
        
        # Match against topic cache
        with self.lock:
            topic_cache = self.topic_cache.copy()
        
        for normalized, variations in topic_cache.items():
            # Exact match on normalized form
            if normalized in question_lower:
                # Return the variation that best matches what appeared in the question
                # This ensures we use "wi-fi halow" when user asks about it, not "wi-fi certified halow"
                best_match = variations[0]  # Default to canonical
                for variation in variations:
                    if self._normalize(variation) in question_lower:
                        best_match = variation
                        break
                matched_topics.add(best_match)
        
        # Handle definition terms
        unmatched_definition_terms = []
        for term in definition_terms:
            norm_term = self._normalize(term)
            if norm_term in topic_cache:
                # For definition queries, prefer the exact term asked about if it's an alias
                variations = topic_cache[norm_term]
                best_match = variations[0]  # Default to canonical
                for variation in variations:
                    if self._normalize(variation) == norm_term:
                        best_match = variation
                        break
                matched_topics.add(best_match)
            else:
                # Track frequency for auto-creation
                unmatched_definition_terms.append(term)
                self.search_frequency[term] += 1
                
                # Auto-create if threshold reached
                if self.search_frequency[term] >= self.auto_create_threshold:
                    self._auto_create_topic(term)
                    matched_topics.add(term)
                    # Reset counter
                    del self.search_frequency[term]
                else:
                    # Include in topics list for fuzzy search fallback
                    matched_topics.add(term)
        
        result = list(matched_topics)
        
        # For definition queries, filter out overly broad topics if more specific ones exist
        # e.g., if we have both "wi-fi" and "wi-fi halow", only keep "wi-fi halow"
        if definition_terms and len(result) > 1:
            # Sort by length (longer = more specific)
            result_sorted = sorted(result, key=len, reverse=True)
            filtered = []
            for topic in result_sorted:
                # Include if it's not a substring of any already included topic
                if not any(topic.lower() in included.lower() and topic.lower() != included.lower() 
                          for included in filtered):
                    filtered.append(topic)
            result = filtered
        
        if result:
            logger.debug(f"Extracted topics from question: {result}")
        else:
            logger.debug(f"No topics extracted from question: {question[:100]}")
        
        return result
    
    def get_topic_variations(self, topic: str) -> List[str]:
        """
        Get all known variations (aliases) for a topic.
        
        Args:
            topic: Topic name to lookup
        
        Returns:
            List of all variations including original name
        """
        normalized = self._normalize(topic)
        with self.lock:
            return self.topic_cache.get(normalized, [topic])
    
    def force_refresh(self) -> None:
        """Force immediate refresh of topic cache."""
        self._refresh_topics()
    
    def get_cache_stats(self) -> Dict:
        """Get statistics about topic cache."""
        with self.lock:
            return {
                'total_topics': len(self.topic_cache),
                'last_refresh': self.last_refresh.isoformat() if self.last_refresh else None,
                'pending_auto_create': len(self.search_frequency),
                'top_pending': sorted(
                    [(term, count) for term, count in self.search_frequency.items()],
                    key=lambda x: x[1],
                    reverse=True
                )[:10]
            }


# Singleton instance
_topic_manager_instance: Optional[TopicManager] = None
_instance_lock = Lock()


def initialize_topic_manager(neo4j_client, **kwargs) -> TopicManager:
    """
    Initialize the global TopicManager instance.
    
    Args:
        neo4j_client: Neo4j client for graph queries
        **kwargs: Additional arguments for TopicManager
    
    Returns:
        Initialized TopicManager instance
    """
    global _topic_manager_instance
    
    with _instance_lock:
        if _topic_manager_instance is None:
            _topic_manager_instance = TopicManager(neo4j_client, **kwargs)
        return _topic_manager_instance


def get_topic_manager() -> Optional[TopicManager]:
    """
    Get the global TopicManager instance.
    
    Returns:
        TopicManager instance if initialized, None otherwise
    """
    return _topic_manager_instance
