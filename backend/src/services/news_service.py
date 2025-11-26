"""
News Service - Generates curated news and events based on user interests.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta
import json
import logging
import redis
import os
from openai import AzureOpenAI

from neo4j_client import Neo4jClient

logger = logging.getLogger(__name__)


class NewsService:
    """Service for generating curated news and events."""
    
    def __init__(self):
        """Initialize the news service."""
        # Initialize Redis for caching
        redis_host = os.getenv("REDIS_HOST", "localhost")
        redis_port = int(os.getenv("REDIS_PORT", "6379"))
        self.redis_client = redis.Redis(
            host=redis_host,
            port=redis_port,
            decode_responses=True,
            socket_connect_timeout=5
        )
        
        # Initialize Neo4j client
        self.neo4j_client = Neo4jClient(
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            user=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", "password"),
            database=os.getenv("NEO4J_DATABASE", "neo4j")
        )
        self.neo4j_client.connect()
        
        # Initialize Azure OpenAI client
        self.llm_client = AzureOpenAI(
            api_key=os.getenv("AZURE_OPENAI_API_KEY"),
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-08-01-preview"),
            azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
        )
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        
        logger.info("NewsService initialized")
    
    def _get_cache_key(self, user_id: int, time_range: str) -> str:
        """Generate cache key for news content."""
        return f"news:user:{user_id}:range:{time_range}"
    
    def _get_last_refresh_key(self, user_id: int) -> str:
        """Generate cache key for last refresh timestamp."""
        return f"news:user:{user_id}:last_refresh"
    
    def should_refresh(self, user_id: int, force: bool = False) -> bool:
        """
        Check if news should be refreshed for this user.
        
        Args:
            user_id: The user ID
            force: If True, always return True
            
        Returns:
            True if news should be refreshed
        """
        if force:
            return True
        
        try:
            last_refresh = self.redis_client.get(self._get_last_refresh_key(user_id))
            if not last_refresh:
                return True  # Never refreshed before
            
            # Refresh if last refresh was more than 24 hours ago
            last_refresh_time = datetime.fromisoformat(last_refresh)
            return (datetime.now() - last_refresh_time) > timedelta(hours=24)
        except Exception as e:
            logger.warning(f"Error checking refresh status: {e}")
            return True
    
    def get_cached_news(self, user_id: int, time_range: str) -> Optional[Dict[str, Any]]:
        """
        Get cached news content if available.
        
        Args:
            user_id: The user ID
            time_range: Time range (1week, 1month, 6months, 1year)
            
        Returns:
            Cached news dict or None
        """
        try:
            cache_key = self._get_cache_key(user_id, time_range)
            cached = self.redis_client.get(cache_key)
            if cached:
                return json.loads(cached)
        except Exception as e:
            logger.warning(f"Error retrieving cached news: {e}")
        return None
    
    def cache_news(self, user_id: int, time_range: str, content: Dict[str, Any]):
        """
        Cache news content with TTL.
        
        Args:
            user_id: The user ID
            time_range: Time range
            content: News content to cache
        """
        try:
            cache_key = self._get_cache_key(user_id, time_range)
            # Cache for 24 hours
            self.redis_client.setex(cache_key, 86400, json.dumps(content))
            
            # Update last refresh timestamp
            refresh_key = self._get_last_refresh_key(user_id)
            self.redis_client.set(refresh_key, datetime.now().isoformat())
        except Exception as e:
            logger.warning(f"Error caching news: {e}")
    
    def _get_time_range_dates(self, time_range: str) -> tuple[datetime, datetime]:
        """
        Calculate start and end dates based on time range.
        
        Args:
            time_range: One of: 1week, 1month, 6months, 1year
            
        Returns:
            Tuple of (start_date, end_date)
        """
        now = datetime.now()
        
        if time_range == "1week":
            start = now - timedelta(days=7)
            end = now + timedelta(days=7)
        elif time_range == "6months":
            start = now - timedelta(days=180)
            end = now + timedelta(days=180)
        elif time_range == "1year":
            start = now - timedelta(days=365)
            end = now + timedelta(days=365)
        else:  # 1month (default)
            start = now - timedelta(days=30)
            end = now + timedelta(days=60)
        
        return start, end
    
    def _fetch_relevant_documents(
        self, 
        topics: List[str], 
        organisations: List[str],
        people: List[str],
        start_date: datetime,
        end_date: datetime,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        Fetch relevant documents from Neo4j based on user interests and time range.
        
        Args:
            topics: List of topic names
            organisations: List of organisation names
            people: List of people names
            start_date: Start date for document filter
            end_date: End date for document filter
            limit: Maximum number of documents to return
            
        Returns:
            List of document dictionaries
        """
        # Build Cypher query based on interests
        query_parts = []
        params = {
            "start_date_iso": start_date.isoformat(),
            "end_date_iso": end_date.isoformat(),
            "limit": limit
        }
        
        # Base query to match Resources
        # Handle both timestamp (float) and ISO string formats for scraped_at
        query = """
        MATCH (r:Resource)
        WHERE (
            (r.scraped_at >= $start_date_iso AND r.scraped_at <= $end_date_iso)
            OR (toFloat(r.scraped_at) IS NOT NULL AND toFloat(r.scraped_at) >= timestamp($start_date_iso)/1000.0 AND toFloat(r.scraped_at) <= timestamp($end_date_iso)/1000.0)
        )
        """
        
        # Add filters based on interests
        if topics:
            query += """
            OPTIONAL MATCH (r)-[:DISCUSSES]->(t:Topic)
            WHERE t.name IN $topics
            WITH r, COUNT(DISTINCT t) as topic_matches
            """
            params["topics"] = topics
        else:
            query += "\nWITH r, 0 as topic_matches\n"
        
        if organisations:
            query += """
            OPTIONAL MATCH (r)-[:INVOLVES|PUBLISHED_BY]->(o:Organisation)
            WHERE o.name IN $organisations
            WITH r, topic_matches, COUNT(DISTINCT o) as org_matches
            """
            params["organisations"] = organisations
        else:
            query += "\nWITH r, topic_matches, 0 as org_matches\n"
        
        if people:
            query += """
            OPTIONAL MATCH (r)-[:AUTHORED_BY|MENTIONS]->(p:Person)
            WHERE p.name IN $people
            WITH r, topic_matches, org_matches, COUNT(DISTINCT p) as people_matches
            """
            params["people"] = people
        else:
            query += "\nWITH r, topic_matches, org_matches, 0 as people_matches\n"
        
        # Calculate relevance score and return top matches
        query += """
        WITH r, 
             (topic_matches * 3 + org_matches * 2 + people_matches * 2) as relevance_score,
             r.importance as importance
        ORDER BY relevance_score DESC, importance DESC, r.scraped_at DESC
        LIMIT $limit
        
        OPTIONAL MATCH (r)-[:DISCUSSES]->(t:Topic)
        OPTIONAL MATCH (r)-[:INVOLVES|PUBLISHED_BY]->(o:Organisation)
        OPTIONAL MATCH (r)-[:AUTHORED_BY|MENTIONS]->(p:Person)
        OPTIONAL MATCH (r)-[:RELATES_TO]->(e:Event)
        
        RETURN r.title as title,
               r.url as url,
               r.category as category,
               r.summary as summary,
               r.publish_date as publish_date,
               r.importance as importance,
               r.importance_explanation as importance_explanation,
               COLLECT(DISTINCT t.name) as topics,
               COLLECT(DISTINCT o.name) as organisations,
               COLLECT(DISTINCT p.name) as people,
               COLLECT(DISTINCT e.name) as events,
               relevance_score
        """
        
        with self.neo4j_client.driver.session(database=self.neo4j_client.database) as session:
            result = session.run(query, params)
            documents = [dict(record) for record in result]
        
        logger.info(f"Fetched {len(documents)} relevant documents")
        return documents
    
    def _generate_news_content(
        self,
        user_preferences: Dict[str, Any],
        documents: List[Dict[str, Any]],
        time_range: str
    ) -> Dict[str, Any]:
        """
        Generate curated news content using LLM.
        
        Args:
            user_preferences: User preferences dict
            documents: List of relevant documents
            time_range: Time range string
            
        Returns:
            Generated news content dictionary
        """
        # Prepare context for LLM
        topics = user_preferences.get("topics", [])
        organisations = user_preferences.get("organisations", [])
        people = user_preferences.get("people", [])
        
        interests_text = "general technology and standards"
        if topics or organisations or people:
            interest_parts = []
            if topics:
                interest_parts.append(f"topics: {', '.join(topics)}")
            if organisations:
                interest_parts.append(f"organisations: {', '.join(organisations)}")
            if people:
                interest_parts.append(f"people: {', '.join(people)}")
            interests_text = "; ".join(interest_parts)
        
        # Format documents for prompt
        docs_context = []
        for i, doc in enumerate(documents[:30], 1):  # Limit to top 30 to avoid token limits
            doc_text = f"""
Document {i}:
- Title: {doc.get('title', 'N/A')}
- URL: {doc.get('url', 'N/A')}
- Category: {doc.get('category', 'N/A')}
- Summary: {doc.get('summary', 'N/A')}
- Importance: {doc.get('importance', 0):.2f}
- Topics: {', '.join(doc.get('topics', []))}
- Organisations: {', '.join(doc.get('organisations', []))}
- Events: {', '.join(doc.get('events', []))}
- Publish Date: {doc.get('publish_date', 'N/A')}
"""
            docs_context.append(doc_text.strip())
        
        time_range_text = {
            "1week": "the past week and upcoming week",
            "1month": "the past month and next two months",
            "6months": "the past 6 months and next 6 months",
            "1year": "the past year and next year"
        }.get(time_range, "recent period")
        
        prompt = f"""You are a curated news assistant helping users stay informed about developments in technology standards and industry events.

User Interests: {interests_text}
Time Range: {time_range_text}

Based on the following documents from our knowledge base, create a comprehensive, well-organized news digest that highlights:
1. Key recent developments and announcements
2. Upcoming events and important dates
3. Significant publications and standards updates
4. Trends and patterns worth noting

Documents:
{chr(10).join(docs_context)}

Generate a detailed news digest in the following JSON format:
{{
  "headline": "Brief headline summarizing the most important developments",
  "summary": "2-3 paragraph executive summary of key developments",
  "sections": [
    {{
      "title": "Section title (e.g., 'Recent Announcements', 'Upcoming Events')",
      "content": "Markdown-formatted content for this section",
      "documents": [
        {{
          "title": "Document title",
          "url": "Document URL",
          "summary": "Brief description of relevance",
          "category": "document category",
          "importance": 0.95
        }}
      ]
    }}
  ],
  "highlights": [
    "Key highlight 1",
    "Key highlight 2",
    "Key highlight 3"
  ],
  "generated_at": "{datetime.now().isoformat()}"
}}

Focus on:
- Recent developments (prefer recent dates)
- Upcoming events (future dates are important)
- High-importance documents (importance > 0.7)
- Relevance to user's stated interests
- Clear, professional writing
- Grouping related items logically

Return ONLY valid JSON, no additional text."""

        try:
            response = self.llm_client.chat.completions.create(
                model=self.deployment,
                messages=[
                    {"role": "system", "content": "You are a professional news curator and technical writer. Always respond with valid JSON."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=4096
            )
            
            content = response.choices[0].message.content
            
            # Parse JSON response
            if "```json" in content:
                content = content.split("```json")[1].split("```")[0].strip()
            elif "```" in content:
                content = content.split("```")[1].split("```")[0].strip()
            
            news_content = json.loads(content)
            
            # Add metadata
            news_content["time_range"] = time_range
            news_content["document_count"] = len(documents)
            
            return news_content
            
        except Exception as e:
            logger.error(f"Failed to generate news content: {e}", exc_info=True)
            raise
    
    def generate_news(
        self,
        user_id: int,
        user_preferences: Dict[str, Any],
        time_range: str = "1month",
        force_refresh: bool = False
    ) -> Dict[str, Any]:
        """
        Generate curated news for a user.
        
        Args:
            user_id: The user ID
            user_preferences: User preferences including topics, organisations, people
            time_range: Time range (1week, 1month, 6months, 1year)
            force_refresh: If True, bypass cache and regenerate
            
        Returns:
            News content dictionary
        """
        # Check cache first
        if not force_refresh:
            cached = self.get_cached_news(user_id, time_range)
            if cached:
                logger.info(f"Returning cached news for user {user_id}, range {time_range}")
                return cached
        
        logger.info(f"Generating news for user {user_id}, range {time_range}")
        
        # Get time range dates
        start_date, end_date = self._get_time_range_dates(time_range)
        
        # Fetch relevant documents
        documents = self._fetch_relevant_documents(
            topics=user_preferences.get("topics", []),
            organisations=user_preferences.get("organisations", []),
            people=user_preferences.get("people", []),
            start_date=start_date,
            end_date=end_date,
            limit=50
        )
        
        if not documents:
            # No documents found - return empty state
            return {
                "headline": "No Recent Updates",
                "summary": "We haven't found any recent documents matching your interests in the selected time range. Try expanding the time range or adjusting your interests in your profile.",
                "sections": [],
                "highlights": [],
                "time_range": time_range,
                "document_count": 0,
                "generated_at": datetime.now().isoformat()
            }
        
        # Generate news content using LLM
        news_content = self._generate_news_content(user_preferences, documents, time_range)
        
        # Cache the result
        self.cache_news(user_id, time_range, news_content)
        
        return news_content


# Singleton instance
_news_service = None

def get_news_service() -> NewsService:
    """Get or create the news service singleton."""
    global _news_service
    if _news_service is None:
        _news_service = NewsService()
    return _news_service
