"""Client for Oracle service agent endpoint."""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

from ..settings import get_settings

logger = logging.getLogger(__name__)


class OracleAgentClient:
    """Client for Oracle agent content discovery endpoint."""
    
    def __init__(self, base_url: Optional[str] = None):
        settings = get_settings()
        self.base_url = base_url or getattr(settings, 'oracle_service_url', 'http://oracle:8000')
        self.timeout = httpx.Timeout(30.0)
        
    async def discover_content(
        self,
        agent_id: int,
        agent_name: str,
        topics: List[str],
        organizations: List[str],
        cadence_days: int = 7,
        last_content_ids: Optional[List[str]] = None,
        perspective: Optional[str] = None,
        limit: int = 20,
    ) -> Dict[str, Any]:
        """
        Discover content for creator agent via Oracle service.
        
        Args:
            agent_id: Agent database ID
            agent_name: Agent display name
            topics: Agent's expertise topics
            organizations: Agent's tracked organizations
            cadence_days: Days between posts (determines rollup route)
            last_content_ids: Previously used content IDs to exclude
            perspective: Optional perspective override ("events", "trends", "decisions", "news")
            limit: Maximum content items to return
            
        Returns:
            Response dict with:
            - route_used: Which query template was selected
            - confidence: Route selection confidence
            - date_range: Query date range
            - content_items: List of content with topics/orgs/events/people
            - rollup_used: Whether pre-computed rollup was used
            - excluded_count: Number of items excluded via deduplication
        """
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.post(
                    f"{self.base_url}/agent/discover",
                    json={
                        "agent_id": str(agent_id),
                        "agent_name": agent_name,
                        "expertise_topics": topics,
                        "expertise_organisations": organizations,
                        "cadence_days": cadence_days,
                        "discovery_tolerance": 0.5,  # Medium tolerance
                        "last_content_ids": last_content_ids or [],
                        "perspective": perspective,
                        "limit": limit,
                    },
                )
                response.raise_for_status()
                return response.json()
                
            except httpx.HTTPStatusError as e:
                logger.error(
                    "Oracle API error: status=%d, body=%s",
                    e.response.status_code,
                    e.response.text,
                )
                raise
            except httpx.RequestError as e:
                logger.error("Oracle connection error: %s", e)
                raise
    
    async def health_check(self) -> bool:
        """Check if Oracle service is available."""
        async with httpx.AsyncClient(timeout=httpx.Timeout(5.0)) as client:
            try:
                response = await client.get(f"{self.base_url}/agent/health")
                return response.status_code == 200
            except Exception as e:
                logger.warning("Oracle health check failed: %s", e)
                return False
