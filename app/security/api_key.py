"""API key verification for FastAPI endpoints."""

from __future__ import annotations

from fastapi import Header

from app.config import settings
from app.exceptions.errors import AuthenticationError


def verify_api_key(
    api_key: str = Header(alias="X-API-Key"),
) -> dict[str, str]:
    """FastAPI dependency that verifies the X-API-Key header.

    Args:
        api_key: Value of the ``X-API-Key`` request header, injected
            automatically by FastAPI.

    Returns:
        ``{"client": "authenticated"}`` when the key is valid.

    Raises:
        AuthenticationError: When the key is missing or not in the
            configured set of valid keys.
    """
    if not api_key or api_key not in settings.valid_api_keys:
        raise AuthenticationError()
    return {"client": "authenticated"}
