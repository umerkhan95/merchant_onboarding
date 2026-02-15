"""In-memory fallback for schema cache when Redis is not available."""

from __future__ import annotations

import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class InMemorySchemaCache:
    """In-memory schema cache (no persistence) for evals when Redis unavailable."""

    def __init__(self):
        """Initialize in-memory cache."""
        self._cache: dict[str, dict] = {}

    @staticmethod
    def _normalize_domain(url: str) -> str:
        """Normalize URL to a consistent domain key."""
        parsed = urlparse(url)
        domain = parsed.netloc or parsed.path
        domain = domain.lower().split(":")[0]  # strip port
        if domain.startswith("www."):
            domain = domain[4:]
        return domain

    async def get(self, url: str) -> dict | None:
        """Get cached schema for a domain."""
        domain = self._normalize_domain(url)
        schema = self._cache.get(domain)
        if schema:
            logger.debug("In-memory schema cache hit for %s", domain)
        return schema

    async def set(self, url: str, schema: dict) -> None:
        """Cache a generated schema for a domain."""
        if not schema.get("baseSelector") or not schema.get("fields"):
            logger.warning("Refusing to cache invalid schema (missing baseSelector or fields)")
            return

        domain = self._normalize_domain(url)
        self._cache[domain] = schema
        logger.info("Cached schema in memory for %s", domain)

    async def invalidate(self, url: str) -> None:
        """Remove cached schema for a domain."""
        domain = self._normalize_domain(url)
        if domain in self._cache:
            del self._cache[domain]
            logger.info("Invalidated in-memory schema cache for %s", domain)
