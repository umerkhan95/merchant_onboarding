"""Password hashing and verification using bcrypt."""

from __future__ import annotations

import bcrypt


_COST_FACTOR = 12


def hash_password(password: str) -> str:
    """Hash a password with bcrypt.

    Args:
        password: Plain-text password.

    Returns:
        bcrypt hash string (includes salt).
    """
    salt = bcrypt.gensalt(rounds=_COST_FACTOR)
    return bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    """Verify a password against a bcrypt hash.

    Args:
        password: Plain-text password to check.
        hashed: bcrypt hash string to compare against.

    Returns:
        True if the password matches.
    """
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
