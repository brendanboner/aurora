#!/usr/bin/env python3
"""
One-off migration: transfer user_preferences.sources TEXT[] values into
the new user_source_preferences table (datasource_id + weight).

Run this BEFORE applying migration 008 (which drops the sources column).

Strategy:
  - For each user with non-empty sources[], fuzzy-match each string against
    DataSource.name and DataSource.fetch_url in Neo4j (case-insensitive
    substring). First match wins.
  - Matched entries get weight=1.0 in user_source_preferences.
  - Unmatched entries are printed as warnings and dropped.
  - The script is idempotent — it uses INSERT ... ON CONFLICT DO NOTHING.

Usage:
    python scripts/migrate_user_sources.py [--dry-run]

Environment:
    Reads database credentials from .env in repo root (same as all services).
"""

import argparse
import os
import re
import sys
from pathlib import Path

# Load .env from repo root
repo_root = Path(__file__).parent.parent
env_file = repo_root / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

import psycopg2
from neo4j import GraphDatabase


def connect_postgres():
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "localhost"),
        port=int(os.environ.get("POSTGRES_PORT", 5432)),
        user=os.environ.get("POSTGRES_USER", "aurora"),
        password=os.environ.get("POSTGRES_PASSWORD", "aurora_password"),
        dbname=os.environ.get("POSTGRES_DB", "aurora"),
    )


def connect_neo4j():
    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "password"),
        ),
    )
    return driver


def fetch_datasources(driver) -> list[dict]:
    with driver.session() as session:
        result = session.run(
            """
            MATCH (d:DataSource)
            WHERE d.datasource_id IS NOT NULL
            RETURN d.datasource_id AS id,
                   coalesce(d.display_name, d.name) AS name,
                   coalesce(d.fetch_url, '') AS fetch_url
            """
        )
        return [dict(r) for r in result]


def fuzzy_match(source_str: str, datasources: list[dict]) -> str | None:
    """Return the best-matching datasource_id for a raw sources[] string."""
    s = source_str.strip().lower()
    if not s:
        return None
    # Exact datasource_id match first
    for ds in datasources:
        if ds["id"].lower() == s:
            return ds["id"]
    # Substring match on fetch_url (strip protocol + trailing slash)
    cleaned_s = re.sub(r"^https?://|/$", "", s)
    for ds in datasources:
        cleaned_url = re.sub(r"^https?://|/$", "", (ds["fetch_url"] or "").lower())
        if cleaned_url and (cleaned_s in cleaned_url or cleaned_url in cleaned_s):
            return ds["id"]
    # Substring match on display_name
    for ds in datasources:
        name = (ds["name"] or "").lower()
        if s in name or name in s:
            return ds["id"]
    return None


def main():
    parser = argparse.ArgumentParser(description="Migrate user_preferences.sources to user_source_preferences")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    args = parser.parse_args()

    pg = connect_postgres()
    neo = connect_neo4j()

    datasources = fetch_datasources(neo)
    print(f"Loaded {len(datasources)} DataSource nodes from Neo4j")

    cur = pg.cursor()
    cur.execute("SELECT user_id, sources FROM user_preferences WHERE sources IS NOT NULL AND array_length(sources, 1) > 0")
    rows = cur.fetchall()
    print(f"Found {len(rows)} users with non-empty sources[]")

    migrated = 0
    unmatched_all: list[str] = []

    for user_id, sources in rows:
        for raw in sources:
            ds_id = fuzzy_match(raw, datasources)
            if ds_id:
                if not args.dry_run:
                    cur.execute(
                        """
                        INSERT INTO user_source_preferences (user_id, datasource_id, weight)
                        VALUES (%s, %s, 1.0)
                        ON CONFLICT (user_id, datasource_id) DO NOTHING
                        """,
                        (user_id, ds_id),
                    )
                print(f"  MATCH  {raw!r:50s} → {ds_id}")
                migrated += 1
            else:
                unmatched_all.append(raw)
                print(f"  SKIP   {raw!r:50s} (no matching DataSource)")

    if not args.dry_run:
        pg.commit()

    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Migrated {migrated} entries.")
    if unmatched_all:
        unique_unmatched = sorted(set(unmatched_all))
        print(f"Unmatched sources ({len(unique_unmatched)} unique):")
        for u in unique_unmatched:
            print(f"  - {u!r}")

    cur.close()
    pg.close()
    neo.close()


if __name__ == "__main__":
    main()
