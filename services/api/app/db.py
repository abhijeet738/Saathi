"""Postgres connection pool (Supabase session pooler).

Usage in a route:

    from ..db import conn

    with conn() as c:
        rows = c.execute("select id, title from documents where user_id = %s", (user_id,)).fetchall()

Rows come back as dicts. The transaction commits when the `with` block ends normally
and rolls back if an exception escapes it.

The pool is created on first use, so importing this file needs no database. That keeps
unit tests and CI independent of Supabase.
"""

from collections.abc import Iterator
from contextlib import contextmanager

import psycopg
from pgvector.psycopg import register_vector
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .config import get_settings

_pool: ConnectionPool | None = None


def _configure(connection: psycopg.Connection) -> None:
    # Lets us pass numpy arrays as `vector` values and read them back.
    # Needs the `vector` extension, which migration 001 creates.
    register_vector(connection)


def get_pool() -> ConnectionPool:
    global _pool
    if _pool is None:
        settings = get_settings()
        _pool = ConnectionPool(
            settings.database_url,
            min_size=1,
            # Kept small on purpose: n8n and the dashboard share Supabase's connection limit.
            max_size=settings.db_pool_max,
            # Fail fast (HTTP 500) instead of hanging when the database is unreachable.
            timeout=10,
            kwargs={
                "row_factory": dict_row,
                # Session pooler supports prepared statements, but turning them off is
                # harmless and keeps this working if you ever switch to transaction mode.
                "prepare_threshold": None,
            },
            configure=_configure,
            # Test each connection when it is handed out. The pooler drops idle
            # connections, and this replaces a dead one instead of failing the request.
            check=ConnectionPool.check_connection,
            open=True,
        )
    return _pool


@contextmanager
def conn() -> Iterator[psycopg.Connection]:
    """Borrow a connection for one unit of work."""
    with get_pool().connection() as connection:
        yield connection


def ping() -> bool:
    """True if the database answers a trivial query. Used by /health."""
    try:
        with conn() as c:
            c.execute("select 1")
        return True
    except Exception:
        return False


def close_pool() -> None:
    """Called on app shutdown."""
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None
