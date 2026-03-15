"""JWT access token creation and verification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt

from app.config import settings


_ALGORITHM = "HS256"

# Allow up to 30 seconds of clock skew between servers
_CLOCK_SKEW_LEEWAY = timedelta(seconds=30)


def create_access_token(merchant_id: str, *, expires_minutes: int | None = None) -> str:
    """Create a signed JWT access token.

    Args:
        merchant_id: UUID string of the merchant.
        expires_minutes: Override for token lifetime.

    Returns:
        Encoded JWT string.
    """
    exp = expires_minutes or settings.jwt_access_expiry_minutes
    now = datetime.now(timezone.utc)
    payload = {
        "sub": merchant_id,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=exp),
    }
    return jwt.encode(payload, settings.jwt_secret_key, algorithm=_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT access token.

    Args:
        token: Encoded JWT string.

    Returns:
        Decoded payload dict with at least ``sub`` and ``type``.

    Raises:
        jwt.ExpiredSignatureError: If the token has expired.
        jwt.InvalidTokenError: If the token is malformed or invalid.
    """
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[_ALGORITHM],
        options={"require": ["sub", "type", "iat", "exp"]},
        leeway=_CLOCK_SKEW_LEEWAY,
    )
    if payload.get("type") != "access":
        raise jwt.InvalidTokenError("Not an access token")
    if not payload.get("sub"):
        raise jwt.InvalidTokenError("Missing subject claim")
    return payload
