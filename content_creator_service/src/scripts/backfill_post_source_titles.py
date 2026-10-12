"""Backfill post_source.title by resolving titles from Neo4j via URL.

Run inside the content_creator_service container:

    python -m content_creator_service.src.scripts.backfill_post_source_titles

"""
from __future__ import annotations

import logging
from typing import Optional

from .. import db
from ..neo4j_context import get_context_gateway

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


def _lookup_title_by_url(url: str) -> Optional[str]:
    try:
        gateway = get_context_gateway()
        rows = gateway._client.execute_query(
            "MATCH (r:Resource {url: $url}) RETURN r.title AS title LIMIT 1",
            {"url": url},
        )
        if rows and rows[0].get("title"):
            return rows[0]["title"]
    except Exception as e:
        logger.warning("Neo4j lookup failed for %s: %s", url, e)
    return None


def main() -> None:
    logger.info("Starting backfill of post_source.title")
    rows = db.fetch_all(
        "SELECT id, url FROM post_source WHERE (title IS NULL OR title = '') AND url IS NOT NULL"
    )
    total = len(rows)
    logger.info("Found %d post_source rows without title", total)
    updated = 0
    for row in rows:
        ps_id = row["id"]
        url = row["url"]
        if not url:
            continue
        title = _lookup_title_by_url(url)
        if not title:
            # As a fallback, try to use the domain as a pseudo-title
            try:
                from urllib.parse import urlparse
                domain = urlparse(url).hostname or url
                title = domain.replace("www.", "")
            except Exception:
                title = None
        if title:
            db.execute("UPDATE post_source SET title = %s WHERE id = %s", (title, ps_id))
            updated += 1
    logger.info("Backfill complete. Updated %d/%d rows.", updated, total)


if __name__ == "__main__":
    main()
