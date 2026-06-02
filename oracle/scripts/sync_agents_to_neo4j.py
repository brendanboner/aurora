#!/usr/bin/env python3
"""Sync content_creator_service agents (and their posts) into Neo4j.

Reads from the content_creator_service Postgres database:
  - `creator_agent` table     → :Agent nodes
  - `post` table              → :Resource nodes + (:Agent)-[:AUTHORED]->(:Resource)

The fast pipeline's entity-existence precheck looks at :Agent nodes when
deciding whether a user query like "what is Kevin's latest news" refers to
a known content-creator persona. Run this script once on deploy and any
time the agent roster changes (or wire it into the agent CRUD flow).

Usage:
  python -m scripts.sync_agents_to_neo4j [--dry-run]

Environment variables (uses the same names as the oracle/digester services):
  NEO4J_URI, NEO4J_USER (or NEO4J_USERNAME), NEO4J_PASSWORD
  POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from typing import Iterable

# Allow running as `python -m scripts.sync_agents_to_neo4j` from oracle/
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import psycopg2
import psycopg2.extras
from neo4j import GraphDatabase

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("sync_agents")
logging.getLogger("neo4j").setLevel(logging.WARNING)


AGENT_SELECT_SQL = """
    SELECT id, name, description, persona, expertise_topics,
           expertise_organisations, expertise_standards, tone_style,
           posting_cadence, enabled,
           created_at, updated_at
    FROM creator_agent
    ORDER BY id
"""

POSTS_SELECT_SQL = """
    SELECT id, agent_id, title, body, summary, tags, visibility,
           created_at, updated_at
    FROM post
    WHERE agent_id = %s
      AND visibility = 'public'
    ORDER BY created_at DESC
"""

# MERGE agent nodes by id (stable PK from creator_agent table) and refresh
# their attributes every sync. Posts are merged by (agent_id, post_id) on a
# composite url_hash so re-runs are idempotent.
MERGE_AGENT_CYPHER = """
MERGE (a:Agent {agent_id: $agent_id})
SET a.name = $name,
    a.description = $description,
    a.persona = $persona,
    a.expertise_topics = $expertise_topics,
    a.expertise_organisations = $expertise_organisations,
    a.expertise_standards = $expertise_standards,
    a.tone_style = $tone_style,
    a.posting_cadence = $posting_cadence,
    a.enabled = $enabled,
    a.created_at = $created_at,
    a.updated_at = $updated_at,
    a.synced_at = datetime()
RETURN a.name AS name
"""

MERGE_POST_CYPHER = """
MATCH (a:Agent {agent_id: $agent_id})
MERGE (r:Resource {url_hash: $url_hash})
SET r.title = $title,
    r.summary = $summary,
    r.publish_date = $publish_date,
    r.category = 'agent_post',
    r.source = 'content_creator_service',
    r.archived = false,
    r.synced_at = datetime()
MERGE (a)-[:AUTHORED]->(r)
RETURN r.url_hash AS url_hash
"""


def open_pg() -> psycopg2.extensions.connection:
    # content_creator_service shares the main `aurora` Postgres database
    # with the rest of the stack (creator_agent and post tables live there
    # alongside app_users / oracle_query_history / etc).
    return psycopg2.connect(
        host=os.environ.get("POSTGRES_HOST", "aurora-postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ.get("POSTGRES_DB", "aurora"),
        user=os.environ.get("POSTGRES_USER", "aurora"),
        password=os.environ["POSTGRES_PASSWORD"],
    )


def open_neo4j():
    uri = os.environ.get("NEO4J_URI", "bolt://aurora-neo4j:7687")
    user = os.environ.get("NEO4J_USER") or os.environ.get("NEO4J_USERNAME", "neo4j")
    password = os.environ["NEO4J_PASSWORD"]
    return GraphDatabase.driver(uri, auth=(user, password))


def fetch_agents(pg) -> list[dict]:
    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(AGENT_SELECT_SQL)
        return [dict(row) for row in cur.fetchall()]


def fetch_posts(pg, agent_id: int) -> list[dict]:
    with pg.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
        cur.execute(POSTS_SELECT_SQL, (agent_id,))
        return [dict(row) for row in cur.fetchall()]


def _post_url_hash(agent_id: int, post_id: int) -> str:
    return f"agent-post-{agent_id}-{post_id}"


def _post_url(agent_id: int, post_id: int) -> str:
    return f"internal://content_creator/agent/{agent_id}/post/{post_id}"


def sync_agent(session, agent: dict, posts: Iterable[dict], dry_run: bool) -> tuple[int, int]:
    """Sync one agent + its posts. Returns (agent_count=0|1, posts_count)."""
    if dry_run:
        log.info("[dry-run] would MERGE :Agent id=%s name=%r", agent["id"], agent["name"])
        post_count = 0
        for p in posts:
            log.info(
                "[dry-run]   would MERGE post id=%s title=%r",
                p["id"], (p.get("title") or "")[:80],
            )
            post_count += 1
        return 0, 0

    session.run(
        MERGE_AGENT_CYPHER,
        agent_id=agent["id"],
        name=agent["name"],
        description=agent.get("description"),
        persona=agent.get("persona"),
        expertise_topics=agent.get("expertise_topics") or [],
        expertise_organisations=agent.get("expertise_organisations") or [],
        expertise_standards=agent.get("expertise_standards") or [],
        tone_style=agent.get("tone_style"),
        posting_cadence=agent.get("posting_cadence"),
        enabled=bool(agent.get("enabled", True)),
        created_at=str(agent.get("created_at")) if agent.get("created_at") else None,
        updated_at=str(agent.get("updated_at")) if agent.get("updated_at") else None,
    )

    post_count = 0
    for p in posts:
        url_hash = _post_url_hash(agent["id"], p["id"])
        session.run(
            MERGE_POST_CYPHER,
            agent_id=agent["id"],
            url_hash=url_hash,
            title=p.get("title") or "(untitled)",
            summary=p.get("summary") or (p.get("body") or "")[:500],
            publish_date=str(p.get("created_at")) if p.get("created_at") else None,
        )
        post_count += 1
    return 1, post_count


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="List intended changes without writing")
    args = parser.parse_args()

    log.info("Connecting to content_creator Postgres")
    pg = open_pg()
    try:
        agents = fetch_agents(pg)
        log.info("Found %d creator_agent rows", len(agents))

        log.info("Connecting to Neo4j")
        driver = open_neo4j()
        try:
            total_agents = total_posts = 0
            with driver.session() as session:
                for agent in agents:
                    posts = fetch_posts(pg, agent["id"])
                    a_count, p_count = sync_agent(session, agent, posts, dry_run=args.dry_run)
                    total_agents += a_count
                    total_posts += p_count
                    if not args.dry_run:
                        log.info(
                            "synced :Agent %r (id=%s) + %d posts",
                            agent["name"], agent["id"], p_count,
                        )
        finally:
            driver.close()
    finally:
        pg.close()

    log.info(
        "Done. %s %d agents and %d posts",
        "would sync" if args.dry_run else "Synced",
        total_agents if not args.dry_run else len(agents),
        total_posts if not args.dry_run else sum(1 for _ in agents),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
