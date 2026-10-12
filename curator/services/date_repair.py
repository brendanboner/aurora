"""
Date Repair Service

Daily job that back-fills publish_date on Resource nodes that the scrapers
ingested without a formal date. Without a valid publish_date these documents
receive effective_date = 1970-01-01 in oracle Cypher queries and become
completely invisible to recency-based retrieval.

Inference strategies (applied in priority order):
  1. wba_extranet_* / wfa_causeway_* + scraped_at present  -> use scraped_at
     (incremental scrapers, so scraped_at approximates document upload date)
  2. Title regex extraction: ISO date, compact date, month+year variants
  3. Any other recently-scraped doc (scraped_at >= 2024-01-01) -> use scraped_at
     as last-resort (better than 1970-01-01)

Repaired documents get temporal_confidence = 'inferred_from_scrape' or
'inferred_from_title' so they can be distinguished from genuine dates ('high').
The job is idempotent: skips docs that already have a publish_date.
"""

import re
from datetime import datetime
from typing import Optional

from settings import settings
from utils.logger import setup_logger
from neo4j_client import Neo4jClient

logger = setup_logger(__name__)

MIN_SCRAPED_AT = "2024-01-01"

_MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}


def _month_to_date(month_str: str, year_str: str, day_str: str = "1") -> Optional[str]:
    key = month_str[:3].lower()
    month = _MONTH_MAP.get(key)
    if not month:
        return None
    try:
        return f"{int(year_str):04d}-{month:02d}-{int(day_str):02d}"
    except ValueError:
        return None


_DATE_PATTERNS = [
    (r'\b(20\d{2})[-/](0[1-9]|1[0-2])[-/](0[1-9]|[12]\d|3[01])\b',
     lambda m: f"{m.group(1)}-{m.group(2)}-{m.group(3)}"),
    (r'\b(20\d{2})(0[1-9]|1[0-2])(0[1-9]|[12]\d|3[01])\b',
     lambda m: f"{m.group(1)}-{m.group(2)}-{m.group(3)}"),
    (r'\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
     r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
     r'\.?\s+(0?[1-9]|[12]\d|3[01]),?\s+(20\d{2})\b',
     lambda m: _month_to_date(m.group(1), m.group(3), m.group(2))),
    (r'\b(0?[1-9]|[12]\d|3[01])\s+'
     r'(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
     r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
     r'\.?\s+(20\d{2})\b',
     lambda m: _month_to_date(m.group(2), m.group(3), m.group(1))),
    (r'\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|'
     r'Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)'
     r'\.?\s+(20\d{2})\b',
     lambda m: _month_to_date(m.group(1), m.group(2), "1")),
    (r'\bQ([1-4])\s+(20\d{2})\b',
     lambda m: f"{m.group(2)}-{('01','04','07','10')[int(m.group(1))-1]}-01"),
]


def _extract_date_from_title(title: str) -> Optional[str]:
    if not title:
        return None
    for pattern, extractor in _DATE_PATTERNS:
        m = re.search(pattern, title, re.IGNORECASE)
        if m:
            try:
                result = extractor(m)
                if result:
                    datetime.fromisoformat(result)
                    return result
            except (ValueError, TypeError):
                continue
    return None


def _is_incremental_scraper(datasource_id: str) -> bool:
    return datasource_id.startswith("wba_extranet_") or datasource_id.startswith("wfa_causeway_")


class DateRepairService:
    """Repairs publish_date on Resources that arrived without a date."""

    def __init__(self, neo4j_client: Optional[Neo4jClient] = None):
        self._client = neo4j_client or Neo4jClient(
            uri=settings.neo4j_uri,
            user=settings.neo4j_user,
            password=settings.neo4j_password,
            database=settings.neo4j_database,
        )

    def close(self):
        try:
            self._client.close()
        except Exception:
            pass

    def run(self) -> dict:
        logger.info("DateRepairService: starting publish_date back-fill")

        candidates = self._client.execute_query(
            """
            MATCH (r:Resource)
            WHERE (r.publish_date IS NULL OR r.publish_date IN ['', 'unknown'])
              AND r.scraped_at IS NOT NULL
              AND datetime(r.scraped_at) >= datetime($min_scraped)
            RETURN r.url_hash AS id,
                   r.title AS title,
                   r.datasource_id AS ds_id,
                   toString(r.scraped_at) AS scraped_at
            ORDER BY r.scraped_at DESC
            """,
            {"min_scraped": MIN_SCRAPED_AT},
        )

        logger.info(f"DateRepairService: {len(candidates)} candidates found")

        patched_scrape = 0
        patched_title = 0
        skipped = 0
        by_datasource: dict = {}

        for row in candidates:
            url_hash = row.get("id")
            title = row.get("title") or ""
            ds_id = row.get("ds_id") or ""
            scraped_at_str = (row.get("scraped_at") or "")[:10]

            if not url_hash or not scraped_at_str:
                skipped += 1
                continue

            if _is_incremental_scraper(ds_id):
                # Incremental private-portal scraper — scraped_at IS the upload date
                self._patch(url_hash, scraped_at_str, "inferred_from_scrape")
                patched_scrape += 1
                by_datasource[ds_id] = by_datasource.get(ds_id, 0) + 1
            else:
                # Non-incremental (bulk re-scraper): ONLY patch if we can extract a real
                # date from the title. Do NOT fall back to scraped_at — for bulk scrapers
                # scraped_at is when Aurora indexed the document, not when it was published.
                # Using scraped_at here makes 2019-era articles appear as "new 2026" content.
                inferred = _extract_date_from_title(title)
                if inferred:
                    self._patch(url_hash, inferred, "inferred_from_title")
                    patched_title += 1
                    by_datasource[ds_id] = by_datasource.get(ds_id, 0) + 1
                else:
                    skipped += 1  # leave publish_date=NULL — oracle created_at fallback handles it

        total = patched_scrape + patched_title
        logger.info(
            f"DateRepairService: patched {total} resources "
            f"({patched_scrape} from scraped_at, {patched_title} from title), "
            f"{skipped} skipped"
        )
        for ds, count in sorted(by_datasource.items(), key=lambda x: -x[1])[:10]:
            logger.info(f"  {ds}: {count} repaired")

        return {
            "total_repaired": total,
            "patched_from_scrape": patched_scrape,
            "patched_from_title": patched_title,
            "skipped": skipped,
            "by_datasource": by_datasource,
        }

    def _patch(self, url_hash: str, pub_date: str, confidence: str) -> None:
        try:
            self._client.execute_write(
                """
                MATCH (r:Resource {url_hash: $url_hash})
                WHERE r.publish_date IS NULL OR r.publish_date IN ['', 'unknown']
                SET r.publish_date        = $pub_date,
                    r.temporal_confidence = $confidence,
                    r.last_updated        = datetime()
                """,
                {"url_hash": url_hash, "pub_date": pub_date, "confidence": confidence},
            )
        except Exception as exc:
            logger.warning(f"DateRepairService: patch failed for {url_hash}: {exc}")
