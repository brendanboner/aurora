"""
Orphan Resource Monitor

Flags Resource nodes that have no entity relationships (no RELATES_TO topic,
no MENTIONS person or organisation) 48 hours after ingestion.

Orphaned resources are never surfaced by oracle queries and represent either:
  - Digestion failures (entity extraction produced no results)
  - Legacy test inserts or direct Cypher writes that bypassed the digester
  - Edge-case content (e.g. pure download pages) where extraction found nothing

This service logs a warning for each orphan found.  It does not delete
resources automatically — deletion requires human review to avoid losing
content that is waiting to be re-queued.

Run interval: every 6 hours (configurable).
"""

from datetime import datetime
from typing import Optional

from settings import settings
from utils.logger import setup_logger
from neo4j_client import Neo4jClient

logger = setup_logger(__name__)

# Resources are considered orphaned only after this grace period (hours).
# New resources need time for the digester to extract entities.
ORPHAN_GRACE_PERIOD_HOURS = 48


class OrphanMonitorService:
    """
    Periodic check for Resource nodes with no entity relationships.

    Returns a summary dict so results can be surfaced via the curator API
    or logged for alerting.
    """

    def __init__(self, neo4j_client: Optional[Neo4jClient] = None):
        if neo4j_client is not None:
            self._client = neo4j_client
        else:
            self._client = Neo4jClient(
                uri=settings.neo4j_uri,
                user=settings.neo4j_user,
                password=settings.neo4j_password,
                database=settings.neo4j_database,
            )

    def close(self):
        if self._client:
            self._client.close()

    def run(self) -> dict:
        """
        Query for orphaned resources and log warnings.

        Returns:
            {
                "orphan_count": int,
                "samples": [{"url": str, "title": str, "datasource_id": str, "scraped_at": str}],
            }
        """
        logger.info("OrphanMonitorService: checking for orphaned resources")

        query = f"""
        MATCH (r:Resource)
        WHERE
            NOT EXISTS {{ (r)-[:RELATES_TO]->() }}
            AND NOT EXISTS {{ (r)-[:MENTIONS]->() }}
            AND r.scraped_at IS NOT NULL
            AND duration.inHours(
                datetime(r.scraped_at), datetime()
            ).hours >= {ORPHAN_GRACE_PERIOD_HOURS}
        RETURN
            count(r)       AS total,
            collect({{
                url:           r.url,
                title:         r.title,
                datasource_id: r.datasource_id,
                scraped_at:    r.scraped_at
            }})[0..10]      AS samples
        """

        try:
            rows = self._client.execute_query(query)
        except Exception as exc:
            logger.error(f"OrphanMonitorService: query failed: {exc}")
            return {"orphan_count": 0, "samples": [], "error": str(exc)}

        if not rows:
            return {"orphan_count": 0, "samples": []}

        row = rows[0]
        orphan_count = row.get("total", 0)
        samples = row.get("samples", [])

        if orphan_count > 0:
            logger.warning(
                f"OrphanMonitorService: {orphan_count} orphaned resource(s) found "
                f"(>{ORPHAN_GRACE_PERIOD_HOURS}h old with no entity relationships)"
            )
            for s in samples:
                logger.warning(
                    f"  Orphan: [{s.get('datasource_id', '?')}] "
                    f"{s.get('title', '(no title)')} — {s.get('url', '?')}"
                )
        else:
            logger.info("OrphanMonitorService: no orphaned resources found")

        return {"orphan_count": orphan_count, "samples": samples}
