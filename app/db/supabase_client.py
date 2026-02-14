"""Supabase/asyncpg database client for connection pooling."""

from __future__ import annotations

import asyncpg


class DatabaseClient:
    """Manages asyncpg connection pool for Supabase database."""

    def __init__(self, database_url: str):
        """Initialize database client.

        Args:
            database_url: PostgreSQL connection string
        """
        self.database_url = database_url
        self._pool: asyncpg.Pool | None = None

    async def connect(self) -> None:
        """Create connection pool.

        Raises:
            asyncpg.PostgresError: If connection fails
        """
        self._pool = await asyncpg.create_pool(
            self.database_url,
            min_size=2,
            max_size=10,
            command_timeout=60.0,
        )

    async def close(self) -> None:
        """Close connection pool gracefully."""
        if self._pool:
            await self._pool.close()

    @property
    def pool(self) -> asyncpg.Pool:
        """Get connection pool.

        Returns:
            asyncpg.Pool: Active connection pool

        Raises:
            RuntimeError: If database not connected
        """
        if not self._pool:
            raise RuntimeError("Database not connected. Call connect() first.")
        return self._pool
