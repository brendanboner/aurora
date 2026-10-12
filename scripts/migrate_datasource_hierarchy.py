#!/usr/bin/env python3
"""
One-off migration: set parent_datasource_id on existing DataSource nodes
in Neo4j according to scripts/datasource_hierarchy.yaml.

This is purely additive — no nodes or resources are deleted or modified
other than setting the parent_datasource_id property.

Usage:
    python scripts/migrate_datasource_hierarchy.py [--dry-run]

Environment:
    Reads database credentials from .env in repo root.
"""

import argparse
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

import yaml
from neo4j import GraphDatabase


def connect_neo4j():
    driver = GraphDatabase.driver(
        os.environ.get("NEO4J_URI", "bolt://localhost:7687"),
        auth=(
            os.environ.get("NEO4J_USER", "neo4j"),
            os.environ.get("NEO4J_PASSWORD", "password"),
        ),
    )
    return driver


def main():
    parser = argparse.ArgumentParser(description="Apply DataSource hierarchy YAML to Neo4j")
    parser.add_argument("--dry-run", action="store_true", help="Print actions without writing")
    parser.add_argument("--clear", nargs="*", metavar="ID",
                        help="Null parent_datasource_id for these datasource_ids (or all if no args)")
    args = parser.parse_args()

    yaml_path = Path(__file__).parent / "datasource_hierarchy.yaml"
    hierarchy = yaml.safe_load(yaml_path.read_text()) or {}
    print(f"Loaded {len(hierarchy)} entries from datasource_hierarchy.yaml")

    driver = connect_neo4j()

    with driver.session() as session:
        # Optional clear pass
        if args.clear is not None:
            targets = args.clear if args.clear else None
            if targets:
                for ds_id in targets:
                    if not args.dry_run:
                        session.run(
                            "MATCH (d:DataSource {datasource_id: $id}) "
                            "REMOVE d.parent_datasource_id",
                            {"id": ds_id},
                        )
                    print(f"  CLEAR  {ds_id}")
            else:
                if not args.dry_run:
                    session.run(
                        "MATCH (d:DataSource) WHERE d.parent_datasource_id IS NOT NULL "
                        "REMOVE d.parent_datasource_id"
                    )
                print("  CLEAR ALL parent_datasource_id properties")

        updated = 0
        skipped = 0

        for child_id, parent_id in hierarchy.items():
            # Verify both nodes exist
            check = session.run(
                "MATCH (c:DataSource {datasource_id: $cid}), "
                "(p:DataSource {datasource_id: $pid}) "
                "RETURN c.datasource_id AS cid, p.datasource_id AS pid LIMIT 1",
                {"cid": child_id, "pid": parent_id},
            )
            row = check.single()
            if not row:
                print(f"  SKIP   {child_id} → {parent_id}  (one or both nodes missing)")
                skipped += 1
                continue

            if not args.dry_run:
                session.run(
                    "MATCH (d:DataSource {datasource_id: $id}) "
                    "SET d.parent_datasource_id = $parent",
                    {"id": child_id, "parent": parent_id},
                )
            print(f"  SET    {child_id} → {parent_id}")
            updated += 1

    driver.close()
    print(f"\n{'DRY RUN — ' if args.dry_run else ''}Set parent on {updated} nodes, skipped {skipped}.")


if __name__ == "__main__":
    main()
