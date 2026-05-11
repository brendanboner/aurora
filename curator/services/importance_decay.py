"""
Importance Decay Service

Applies exponential time-decay to resource importance scores, writing the result
to r.effective_importance.  The raw LLM-assigned r.importance is never modified
so it remains auditable and reusable if decay parameters change.

Decay formula:
    effective_importance = raw_importance * exp(-lambda * days_since_scraped)

Lambda = 0.00057  →  content loses ~30% weight after 6 months, ~50% after 1 year.
This is intentionally gentle — even 2-year-old Wi-Fi standards are still relevant
for an enterprise networking knowledge base.

The job runs daily and is idempotent: re-running with the same data produces the
same output (effective_importance only depends on raw_importance and scraped_at).
"""

import math
from datetime import datetime
from typing import Optional

from settings import settings
from utils.logger import setup_logger
from neo4j_client import Neo4jClient

logger = setup_logger(__name__)

# Decay constant.  Derivation:
#   6 months ≈ 182 days  →  we want exp(-λ * 182) ≈ 0.70  →  λ ≈ 0.00191
# But Wi-Fi specs remain highly relevant for years, so we use a gentler λ:
#   1 year ≈ 365 days    →  exp(-λ * 365) ≈ 0.81            λ = 0.00057
DECAY_LAMBDA = 0.00057

# Resources scraped more than this many days ago are capped at the floor, not
# driven to zero (prevents ancient-but-foundational docs from disappearing).
DECAY_FLOOR = 0.10


class ImportanceDecayService:
    """
    Daily job that refreshes r.effective_importance for all Resource nodes.

    effective_importance is the value used by oracle retrieval ranking.
    raw r.importance stays unchanged as the LLM baseline score.
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
        Apply time-decay to all resources and return a summary dict.

        Returns:
            {"updated": int, "skipped_no_date": int, "errors": int}
        """
        logger.info("ImportanceDecayService: starting effective_importance refresh")
        start = datetime.now()

        # Pull all resources with their raw importance and scrape date.
        # We compute decay in Python rather than Cypher because Neo4j does not
        # have a native exp() function accessible in all versions.
        query = """
        MATCH (r:Resource)
        WHERE r.importance IS NOT NULL
        RETURN
            elementId(r)   AS eid,
            r.importance   AS raw_importance,
            r.scraped_at   AS scraped_at
        """
        try:
            rows = self._client.execute_query(query)
        except Exception as exc:
            logger.error(f"ImportanceDecayService: query failed: {exc}")
            return {"updated": 0, "skipped_no_date": 0, "errors": 1}

        today = datetime.utcnow()
        updated = 0
        skipped = 0
        errors = 0

        for row in rows:
            eid = row["eid"]
            raw = float(row["raw_importance"] or 0.0)
            scraped_at = row["scraped_at"]

            if not scraped_at:
                skipped += 1
                continue

            try:
                if isinstance(scraped_at, str):
                    # Handle ISO 8601 with or without fractional seconds
                    scraped_dt = datetime.fromisoformat(scraped_at.replace("Z", "+00:00"))
                else:
                    scraped_dt = scraped_at  # Neo4j datetime object

                # Strip timezone info for subtraction (both in UTC)
                if hasattr(scraped_dt, "tzinfo") and scraped_dt.tzinfo is not None:
                    scraped_dt = scraped_dt.replace(tzinfo=None)

                days_old = max(0, (today - scraped_dt).days)
                decay_factor = math.exp(-DECAY_LAMBDA * days_old)
                effective = max(DECAY_FLOOR, raw * decay_factor)
                effective = round(effective, 4)

                self._client.execute_query(
                    """
                    MATCH (r:Resource) WHERE elementId(r) = $eid
                    SET r.effective_importance = $effective_importance
                    """,
                    {"eid": eid, "effective_importance": effective},
                )
                updated += 1

            except Exception as exc:
                logger.warning(f"ImportanceDecayService: error on resource {eid}: {exc}")
                errors += 1

        elapsed = (datetime.now() - start).total_seconds()
        summary = {"updated": updated, "skipped_no_date": skipped, "errors": errors}
        logger.info(
            f"ImportanceDecayService: done in {elapsed:.1f}s — "
            f"updated={updated}, skipped={skipped}, errors={errors}"
        )
        return summary
