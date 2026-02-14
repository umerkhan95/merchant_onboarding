"""Shared FastAPI dependencies for dependency injection."""

from __future__ import annotations

import redis.asyncio
from fastapi import Depends, Request

from app.security.api_key import verify_api_key


def get_redis(request: Request) -> redis.asyncio.Redis:
    """Retrieve the Redis client attached to the application state.

    Args:
        request: The incoming FastAPI request (injected automatically).

    Returns:
        The ``redis.asyncio.Redis`` instance created during app startup.
    """
    return request.app.state.redis


require_api_key = Depends(verify_api_key)

__all__ = ["get_redis", "require_api_key", "verify_api_key"]
