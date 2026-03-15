"""Redis-backed nonce store for OAuth CSRF protection.

Drop-in replacement for TTLNonceStore that works across multiple workers.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio as aioredis

_DEFAULT_TTL = 600  # 10 minutes
_PREFIX = "nonce:"


class RedisNonceStore:
    """Redis-backed nonce store with automatic TTL expiry."""

    def __init__(self, redis_client: aioredis.Redis, ttl: int = _DEFAULT_TTL):
        self._redis = redis_client
        self._ttl = ttl

    async def set(self, nonce: str, value: object) -> None:
        """Store a nonce with TTL."""
        serialized = json.dumps(value) if not isinstance(value, str) else value
        await self._redis.set(f"{_PREFIX}{nonce}", serialized, ex=self._ttl)

    async def get(self, nonce: str) -> object | None:
        """Retrieve a nonce value without consuming it."""
        raw = await self._redis.get(f"{_PREFIX}{nonce}")
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def pop(self, nonce: str) -> object | None:
        """Retrieve and delete a nonce (consume it)."""
        key = f"{_PREFIX}{nonce}"
        raw = await self._redis.getdel(key)
        if raw is None:
            return None
        try:
            return json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return raw

    async def contains(self, nonce: str) -> bool:
        """Check if a nonce exists."""
        return bool(await self._redis.exists(f"{_PREFIX}{nonce}"))

    async def delete(self, nonce: str) -> None:
        """Explicitly delete a nonce."""
        await self._redis.delete(f"{_PREFIX}{nonce}")
