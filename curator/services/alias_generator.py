"""
Alias Sync Service (Curator wrapper)

Periodically calls the oracle's alias_generator to ensure all DataSource nodes
have human-readable @mention aliases. Runs:
  - Once at curator startup (to fix any existing nodes that lack aliases)
  - Daily at 04:30 UTC (after date_repair at 04:00 and importance_decay at 03:00)
  - Whenever a new datasource is added (triggered by the retriever after scraping)

The actual generation logic lives in oracle/src/services/alias_generator.py
(imported here via the shared neo4j-client).
"""

import sys
import os
import logging
from typing import Optional

from settings import settings
from utils.logger import setup_logger
from neo4j_client import Neo4jClient

logger = setup_logger(__name__)

# Re-use the oracle's generator logic (the oracle package is on sys.path in prod)
# Fallback: inline minimal version if oracle package not available.
try:
    # In the curator container, oracle src is NOT on the path — use inline logic
    raise ImportError("Using inline logic")
except ImportError:
    import re
    from typing import Optional as Opt

    _STOPWORDS = {
        'the', 'and', 'for', 'with', 'from', 'this', 'that', 'are', 'has',
        'its', 'our', 'your', 'via', 'per', 'but', 'not', 'all', 'any',
        'wba', 'wfa', 'ieee', 'ietf', 'wifi',
    }
    _ORG_PREFIX = {
        'wba_extranet': 'wba', 'wfa_causeway': 'wfa', 'wfa_resource': 'wfa',
        'wfa_events': 'wfa', 'ietf_wg': 'ietf', 'ietf_blog': 'ietf',
        'ieee802': 'ieee', 'wba_newsroom': 'wba', 'wba_resources': 'wba',
        'mef': 'mef', 'nist': 'nist', 'onf': 'onf', 'dmtf': 'dmtf',
    }

    def _org_prefix(ds_id: str) -> str:
        for pfx, org in _ORG_PREFIX.items():
            if ds_id.startswith(pfx):
                return org
        return ds_id.split('_')[0]

    def _slugify(text: str) -> str:
        s = text.replace('&', 'and').replace('/', '-').replace('+', 'plus')
        s = re.sub(r'[^a-z0-9]+', '-', s.lower()).strip('-')
        return re.sub(r'-{2,}', '-', s)[:50].strip('-')

    def _significant_tokens(name: str) -> list:
        raw = re.findall(r'[a-zA-Z0-9][a-zA-Z0-9]*', name)
        return [t.lower() for t in raw if len(t) >= 2 and t.lower() not in _STOPWORDS]

    def _generate_aliases(ds_id: str, name: str, taken: set) -> tuple:
        prefix = _org_prefix(ds_id)
        primary = f"{prefix}-{_slugify(name)}"
        cand = primary
        n = 2
        while cand in taken:
            cand = f"{primary}-{n}"; n += 1
        primary = cand
        taken.add(primary)
        aliases = [primary]
        for tok in _significant_tokens(name):
            if len(aliases) >= 5:
                break
            kw = f"{prefix}-{tok}"
            if kw not in taken and kw != primary:
                aliases.append(kw); taken.add(kw)
        return primary, aliases

    def _generate_all_aliases(client, dry_run=False) -> dict:
        rows = client.execute_query(
            "MATCH (ds:DataSource) WHERE ds.primary_alias IS NULL AND ds.name IS NOT NULL "
            "AND ds.name <> '' RETURN ds.datasource_id AS id, ds.name AS name ORDER BY ds.datasource_id"
        )
        if not rows:
            return {"generated": 0, "skipped": 0}
        existing = client.execute_query(
            "MATCH (ds:DataSource) WHERE ds.aliases IS NOT NULL RETURN ds.aliases AS aliases"
        )
        taken: set = set()
        for r in existing:
            for a in (r.get("aliases") or []):
                taken.add(a)
        generated = 0
        for row in rows:
            ds_id = row.get("id", ""); name = row.get("name", "")
            if not ds_id or not name:
                continue
            primary, all_aliases = _generate_aliases(ds_id, name, taken)
            if not dry_run:
                try:
                    client.execute_write(
                        "MATCH (ds:DataSource {datasource_id: $ds_id}) "
                        "SET ds.primary_alias = $primary, ds.aliases = $aliases, ds.last_updated = datetime()",
                        {"ds_id": ds_id, "primary": primary, "aliases": all_aliases}
                    )
                    generated += 1
                    logger.info(f"  {ds_id} → {primary} ({len(all_aliases)} aliases)")
                except Exception as exc:
                    logger.warning(f"  Failed for {ds_id}: {exc}")
        return {"generated": generated, "skipped": len(rows) - generated}


class AliasSyncService:
    """Curator wrapper — generates @mention aliases for all DataSource nodes."""

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

    def run(self, dry_run: bool = False) -> dict:
        logger.info("AliasSyncService: generating @mention aliases for datasources")
        result = _generate_all_aliases(self._client, dry_run=dry_run)
        logger.info(f"AliasSyncService: {result}")
        return result
