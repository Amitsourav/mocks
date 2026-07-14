"""Async Redis client — content cache, section deadlines, rate-limiting."""

from __future__ import annotations

import redis.asyncio as aioredis

from app.core.config import get_settings

_client: aioredis.Redis | None = None


async def connect() -> aioredis.Redis:
    global _client
    if _client is not None:
        return _client
    settings = get_settings()
    _client = aioredis.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
        health_check_interval=30,
    )
    # Fail fast if Redis is unreachable at startup.
    await _client.ping()
    return _client


async def disconnect() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def get_redis() -> aioredis.Redis:
    if _client is None:
        raise RuntimeError("Redis client is not initialized. Call connect() first.")
    return _client
