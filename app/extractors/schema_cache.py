"""Redis-backed cache for auto-generated CSS extraction schemas per domain."""

from __future__ import annotations

import json
import logging
from urllib.parse import urlparse

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


class SchemaCache:
    """Cache auto-generated CSS schemas keyed by domain."""

    KEY_PREFIX = "schema_cache:"

    def __init__(self, redis_client: aioredis.Redis, ttl: int = 604800):
        """Initialize schema cache.

        Args:
            redis_client: Async Redis client
            ttl: Time-to-live in seconds (default 7 days)
        """
        self.redis = redis_client
        self.ttl = ttl

    @staticmethod
    def _normalize_domain(url: str) -> str:
        """Normalize URL to a consistent domain key.

        Strips scheme, www prefix, trailing slash, and port.
        """
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        domain = domain.lower().split(":")[0]  # strip port
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    def _key(self, domain: str) -> str:
        return f"{self.KEY_PREFIX}{domain}"

    async def get(self, url: str) -> dict | None:
        """Get cached schema for a domain.

        Args:
            url: Any URL from the domain

        Returns:
            Cached CSS schema dict or None if not cached
        """
        domain = self._normalize_domain(url)
        try:
            raw = await self.redis.get(self._key(domain))
            if raw is None:
                return None
            schema = json.loads(raw)
            logger.debug("Schema cache hit for %s", domain)
            return schema
        except Exception as e:
            logger.warning("Schema cache read failed for %s: %s", domain, e)
            return None

    async def set(self, url: str, schema: dict) -> None:
        """Cache a generated schema for a domain.

        Args:
            url: Any URL from the domain
            schema: CSS extraction schema dict (must have baseSelector and fields)
        """
        if not schema.get("baseSelector") or not schema.get("fields"):
            logger.warning("Refusing to cache invalid schema (missing baseSelector or fields)")
            return

        domain = self._normalize_domain(url)
        try:
            await self.redis.set(
                self._key(domain),
                json.dumps(schema),
                ex=self.ttl,
            )
            logger.info("Cached schema for %s (TTL: %ds)", domain, self.ttl)
        except Exception as e:
            logger.warning("Schema cache write failed for %s: %s", domain, e)

    async def invalidate(self, url: str) -> None:
        """Remove cached schema for a domain."""
        domain = self._normalize_domain(url)
        try:
            await self.redis.delete(self._key(domain))
            logger.info("Invalidated schema cache for %s", domain)
        except Exception as e:
            logger.warning("Schema cache invalidation failed for %s: %s", domain, e)
