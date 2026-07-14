"""Async Postgres connection pool (asyncpg) against Supabase via Supavisor.

The pool is created at app startup and closed at shutdown. `search_path` is set
per connection so unqualified identifiers resolve to `mock_db`. The backend
connects with a privileged role (bypasses RLS by design — see migration 0002).
"""

from __future__ import annotations

import asyncpg

from app.core.config import get_settings

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    settings = get_settings()
    # Resolve unqualified names to our schema, keeping public for extensions.
    await conn.execute(f"set search_path = {settings.db_schema}, public;")


async def connect() -> asyncpg.Pool:
    global _pool
    if _pool is not None:
        return _pool
    settings = get_settings()
    _pool = await asyncpg.create_pool(
        dsn=settings.database_url,
        min_size=settings.db_pool_min,
        max_size=settings.db_pool_max,
        init=_init_connection,
        # Supavisor is a transaction-mode pooler; disable client-side statement
        # cache which is incompatible with server-side prepared statements there.
        statement_cache_size=0,
        command_timeout=30,
    )
    return _pool


async def disconnect() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


def get_pool() -> asyncpg.Pool:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized. Call connect() first.")
    return _pool
