"""Shared FastAPI dependencies for dependency injection."""

from __future__ import annotations

from typing import TYPE_CHECKING

import redis.asyncio
from fastapi import Depends, Request

from app.security.api_key import verify_api_key

if TYPE_CHECKING:
    from app.db.supabase_client import DatabaseClient


def get_redis(request: Request) -> redis.asyncio.Redis:
    """Retrieve the Redis client attached to the application state.

    Args:
        request: The incoming FastAPI request (injected automatically).

    Returns:
        The ``redis.asyncio.Redis`` instance created during app startup.
    """
    return request.app.state.redis


def get_db(request: Request) -> DatabaseClient | None:
    """Retrieve the DatabaseClient attached to the application state.

    Args:
        request: The incoming FastAPI request (injected automatically).

    Returns:
        The ``DatabaseClient`` instance or None if DB is unavailable.
    """
    return getattr(request.app.state, "db", None)


require_api_key = Depends(verify_api_key)

__all__ = ["get_db", "get_redis", "require_api_key", "verify_api_key"]
