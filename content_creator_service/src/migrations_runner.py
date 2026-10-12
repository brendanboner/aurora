"""Utility to apply SQL migrations in order."""
from __future__ import annotations

import logging
from pathlib import Path

from . import db

logger = logging.getLogger(__name__)

MIGRATION_TABLE = "content_creator_schema_migrations"


def apply_all_migrations() -> None:
    """Apply pending SQL migration files in lexical order."""
    migrations_dir = Path(__file__).resolve().parent.parent / "migrations"
    sql_files = sorted(p for p in migrations_dir.glob("*.sql"))
    if not sql_files:
        logger.info("No migrations found under %s", migrations_dir)
        return

    with db.connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                f"""
                CREATE TABLE IF NOT EXISTS {MIGRATION_TABLE} (
                    filename TEXT PRIMARY KEY,
                    applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                )
                """
            )

            cur.execute(f"SELECT filename FROM {MIGRATION_TABLE}")
            applied = {row[0] for row in cur.fetchall()}

            for sql_file in sql_files:
                if sql_file.name in applied:
                    continue
                logger.info("Applying migration %s", sql_file.name)
                cur.execute(sql_file.read_text())
                cur.execute(
                    f"INSERT INTO {MIGRATION_TABLE} (filename) VALUES (%s)",
                    (sql_file.name,),
                )
            conn.commit()
    logger.info("Migrations up to date")
