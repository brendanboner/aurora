"""Postgres connection management utilities."""
from __future__ import annotations

from contextlib import contextmanager
from typing import Iterator, Optional

import psycopg2
from psycopg2.extras import RealDictCursor
from psycopg2.pool import ThreadedConnectionPool

from .settings import get_settings

_pool: Optional[ThreadedConnectionPool] = None


def init_pool() -> None:
    """Initialise the global psycopg2 connection pool."""
    global _pool
    if _pool is not None:
        return

    settings = get_settings()
    conn_kwargs = settings.pg_connect_kwargs()
    _pool = ThreadedConnectionPool(
        minconn=settings.pg_pool_min,
        maxconn=settings.pg_pool_max,
        **conn_kwargs,
    )


def close_pool() -> None:
    """Close the pool at process shutdown."""
    global _pool
    if _pool is None:
        return
    _pool.closeall()
    _pool = None


def _get_connection():
    if _pool is None:
        init_pool()
    assert _pool is not None, "Database pool not initialised"
    return _pool.getconn()


def _release_connection(conn) -> None:
    if _pool is None:
        conn.close()
        return
    _pool.putconn(conn)


@contextmanager
def connection() -> Iterator[psycopg2.extensions.connection]:
    """Yield a pooled connection."""
    conn = _get_connection()
    try:
        yield conn
    finally:
        _release_connection(conn)


@contextmanager
def cursor() -> Iterator[psycopg2.extensions.cursor]:
    """Yield a RealDictCursor tied to a pooled connection."""
    with connection() as conn:
        cur = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cur
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def fetch_one(query: str, params: tuple | dict | None = None):
    with cursor() as cur:
        cur.execute(query, params or {})
        return cur.fetchone()


def fetch_all(query: str, params: tuple | dict | None = None):
    with cursor() as cur:
        cur.execute(query, params or {})
        return cur.fetchall()


def execute(query: str, params: tuple | dict | None = None) -> int:
    with cursor() as cur:
        cur.execute(query, params or {})
        return cur.rowcount
