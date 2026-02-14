from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class RateLimiter:
    """Per-domain rate limiter using asyncio.Semaphore.

    Manages concurrent request limits on a per-domain basis to prevent
    overwhelming target servers.
    """

    def __init__(self, max_concurrent: int = 5) -> None:
        """Initialize rate limiter.

        Args:
            max_concurrent: Maximum concurrent requests per domain (default: 5)
        """
        self.max_concurrent = max_concurrent
        self._semaphores: dict[str, asyncio.Semaphore] = {}
        self._lock = asyncio.Lock()

    @asynccontextmanager
    async def acquire(self, domain: str) -> AsyncIterator[None]:
        """Acquire rate limit slot for domain.

        Args:
            domain: Domain name to rate limit

        Yields:
            None when slot is acquired

        Example:
            async with rate_limiter.acquire("example.com"):
                # Make request to example.com
                pass
        """
        semaphore = await self._get_semaphore(domain)
        async with semaphore:
            yield

    async def _get_semaphore(self, domain: str) -> asyncio.Semaphore:
        """Get or create semaphore for domain (thread-safe).

        Args:
            domain: Domain name

        Returns:
            Semaphore for the domain
        """
        if domain in self._semaphores:
            return self._semaphores[domain]

        async with self._lock:
            # Double-check pattern for thread safety
            if domain not in self._semaphores:
                self._semaphores[domain] = asyncio.Semaphore(self.max_concurrent)
            return self._semaphores[domain]
