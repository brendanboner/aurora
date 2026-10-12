#!/usr/bin/env python3
"""
Dump the WBA Extranet community hierarchy discovered by the scraper.

Useful after the first scrape to:
  1. Identify community keys for each programme/workgroup
  2. Fill in scripts/datasource_hierarchy.yaml with correct parent links
     (e.g., AI/ML workgroup → Next Gen programme)

Usage:
    python scripts/wba_dump_hierarchy.py

Environment: reads .env from repo root.
"""

import os
from pathlib import Path

# Load .env
repo_root = Path(__file__).parent.parent
env_file = repo_root / ".env"
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, val = line.partition("=")
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))

from neo4j import GraphDatabase

driver = GraphDatabase.driver(
    os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
    auth=(os.environ.get("NEO4J_USER", "neo4j"), os.environ.get("NEO4J_PASSWORD", "password")),
)

with driver.session() as session:
    result = session.run(
        """
        MATCH (d:DataSource {scraper_type: 'wba_extranet'})
        RETURN d.datasource_id       AS id,
               coalesce(d.display_name, d.name) AS name,
               d.parent_datasource_id AS parent,
               d.fetch_url            AS url
        ORDER BY d.parent_datasource_id, d.name
        """
    )
    rows = list(result)

if not rows:
    print("No WBA Extranet DataSource nodes found. Run the scraper first.")
else:
    print(f"{'ID':<35} {'PARENT':<35} {'NAME'}")
    print("-" * 100)
    for r in rows:
        print(f"{r['id']:<35} {(r['parent'] or ''):<35} {r['name']}")

driver.close()
