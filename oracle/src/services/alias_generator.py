"""
Datasource Alias Generator

Generates human-readable @mention aliases for datasources whose IDs are
internal UUIDs (e.g. wba_extranet_18cc7a64 → @wba-e2e-wifi-qos-l4s-edca).

Aliases are stored as arrays on the DataSource node in Neo4j:
    ds.primary_alias  = "wba-e2e-wifi-qos-l4s-edca"   (canonical, always set)
    ds.aliases        = ["wba-e2e-wifi-qos-l4s-edca",  (primary first)
                         "wba-qos", "wba-l4s", "wba-edca", "wba-e2e"]

Users can type @wba-qos, @wba-l4s, or @wba-e2e-wifi-qos-l4s-edca interchangeably.
The raw datasource_id (wba_extranet_18cc7a64) always works too.

Called:
  - On curator startup (generate for any DataSource that lacks aliases)
  - Via POST /admin/aliases/regenerate (manual trigger)
  - By the WBA/WFA scrapers after creating a new DataSource node
"""

import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Words to skip when generating keyword aliases
_STOPWORDS = {
    'the', 'and', 'for', 'with', 'from', 'this', 'that', 'are', 'has',
    'its', 'our', 'your', 'via', 'per', 'but', 'not', 'all', 'any',
    'wba', 'wfa', 'ieee', 'ietf', 'wifi', 'wi-fi',  # org prefixes (added separately)
}

# Org prefix for alias namespacing
_ORG_PREFIX = {
    'wba_extranet': 'wba',
    'wfa_causeway': 'wfa',
    'wfa_resource': 'wfa',
    'wfa_events': 'wfa',
    'ietf_wg': 'ietf',
    'ietf_blog': 'ietf',
    'ieee802': 'ieee',
    'wba_newsroom': 'wba',
    'wba_resources': 'wba',
    'mef': 'mef',
    'nist': 'nist',
    'onf': 'onf',
    'dmtf': 'dmtf',
}


def _org_prefix(datasource_id: str) -> str:
    """Return the org prefix for a datasource_id."""
    for pfx, org in _ORG_PREFIX.items():
        if datasource_id.startswith(pfx):
            return org
    # Generic fallback: use first part before underscore
    return datasource_id.split('_')[0]


def _slugify(text: str, max_len: int = 50) -> str:
    """Convert a name to a clean URL/mention slug."""
    # Expand common abbreviations/special chars
    text = text.replace('&', 'and').replace('/', '-').replace('+', 'plus')
    # Lowercase and replace non-alphanumeric runs with hyphens
    slug = re.sub(r'[^a-z0-9]+', '-', text.lower())
    slug = re.sub(r'-{2,}', '-', slug).strip('-')
    return slug[:max_len].strip('-')


def _significant_tokens(name: str) -> list[str]:
    """Extract meaningful short tokens from a name for keyword aliases."""
    # Split on spaces and punctuation
    raw = re.findall(r'[a-zA-Z0-9][a-zA-Z0-9]*', name)
    tokens = []
    for tok in raw:
        t = tok.lower()
        if len(t) < 2:
            continue
        if t in _STOPWORDS:
            continue
        # Keep acronyms, technical terms, and meaningful words
        tokens.append(t)
    return tokens


def generate_aliases(datasource_id: str, name: str, taken: set[str] | None = None) -> tuple[str, list[str]]:
    """
    Generate a primary alias and keyword aliases for a datasource.

    Args:
        datasource_id: The raw Neo4j datasource_id (e.g. wba_extranet_18cc7a64)
        name: Human-readable name (e.g. "E2E Wi-Fi QoS, L4S & EDCA")
        taken: Set of aliases already allocated to other datasources (for conflict avoidance)

    Returns:
        (primary_alias, [primary_alias, *keyword_aliases])
    """
    if taken is None:
        taken = set()

    prefix = _org_prefix(datasource_id)
    name_slug = _slugify(name)
    primary = f"{prefix}-{name_slug}"

    # Ensure primary alias is unique (append -2, -3 if needed)
    candidate = primary
    suffix = 2
    while candidate in taken:
        candidate = f"{primary}-{suffix}"
        suffix += 1
    primary = candidate
    taken.add(primary)

    aliases = [primary]

    # Keyword aliases: top tokens that aren't already used
    tokens = _significant_tokens(name)
    added = 0
    for tok in tokens:
        if added >= 4:  # max 4 keyword aliases per datasource
            break
        kw = f"{prefix}-{tok}"
        if kw not in taken and kw != primary:
            aliases.append(kw)
            taken.add(kw)
            added += 1

    return primary, aliases


def generate_all_aliases(client, dry_run: bool = False) -> dict:
    """
    Generate and store aliases for all DataSource nodes that lack them.

    Queries Neo4j for DataSources missing primary_alias, generates aliases,
    and writes them back. Safe to call repeatedly (idempotent via WHERE filter).

    Returns summary stats dict.
    """
    # Fetch all DataSources that need aliases (no primary_alias yet)
    rows = client.execute_query("""
        MATCH (ds:DataSource)
        WHERE ds.primary_alias IS NULL
          AND ds.name IS NOT NULL
          AND ds.name <> ''
        RETURN ds.datasource_id AS id, ds.name AS name
        ORDER BY ds.datasource_id
    """)

    if not rows:
        logger.info("AliasGenerator: all datasources already have aliases")
        return {"generated": 0, "skipped": 0}

    # Also fetch existing aliases to avoid conflicts
    existing_rows = client.execute_query("""
        MATCH (ds:DataSource)
        WHERE ds.aliases IS NOT NULL
        RETURN ds.aliases AS aliases
    """)
    taken: set[str] = set()
    for r in existing_rows:
        for a in (r.get("aliases") or []):
            taken.add(a)

    generated = 0
    for row in rows:
        ds_id = row.get("id", "")
        name = row.get("name", "")
        if not ds_id or not name:
            continue

        primary, all_aliases = generate_aliases(ds_id, name, taken)

        if not dry_run:
            try:
                client.execute_write("""
                    MATCH (ds:DataSource {datasource_id: $ds_id})
                    SET ds.primary_alias = $primary,
                        ds.aliases = $aliases,
                        ds.last_updated = datetime()
                """, {"ds_id": ds_id, "primary": primary, "aliases": all_aliases})
                generated += 1
                logger.info(f"  {ds_id} → {primary} ({len(all_aliases)} aliases)")
            except Exception as exc:
                logger.warning(f"  Failed to write aliases for {ds_id}: {exc}")
        else:
            generated += 1
            logger.info(f"  [dry_run] {ds_id} → {primary}: {all_aliases}")

    logger.info(f"AliasGenerator: generated aliases for {generated} datasources")
    return {"generated": generated, "skipped": len(rows) - generated}
