"""Shared FastAPI dependencies for dependency injection."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Callable

import jwt
import redis.asyncio
from fastapi import Cookie, Depends, Header, Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import settings
from app.security.api_key import verify_api_key
from app.security.jwt_handler import decode_access_token

if TYPE_CHECKING:
    from app.db.supabase_client import DatabaseClient

logger = logging.getLogger(__name__)

limiter = Limiter(key_func=get_remote_address)


# Recognised scopes -- used to validate API key scope strings.
VALID_SCOPES = frozenset({
    "products:read",
    "products:write",
    "products:delete",
    "exports:read",
    "exports:write",
    "settings:read",
    "settings:write",
    "oauth:read",
    "oauth:write",
    "onboard:write",
    "onboard:read",
    "analytics:read",
    "api_keys:manage",
    "admin:manage",
})


@dataclass
class MerchantContext:
    """Identity context resolved from authentication."""

    merchant_id: str | None = None
    auth_method: str = "legacy"  # "jwt", "api_key", "legacy"
    permissions: list[str] = field(default_factory=list)

    def has_permission(self, permission: str) -> bool:
        """Check if this context has a specific permission."""
        return permission in self.permissions


def get_redis(request: Request) -> redis.asyncio.Redis:
    """Retrieve the Redis client attached to the application state."""
    return request.app.state.redis


def get_db(request: Request) -> DatabaseClient | None:
    """Retrieve the DatabaseClient attached to the application state."""
    return getattr(request.app.state, "db", None)


async def get_current_merchant(
    request: Request,
    authorization: str | None = Header(default=None),
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
) -> MerchantContext:
    """Dual-auth dependency: JWT > per-merchant API key > legacy API key.

    Returns MerchantContext with merchant_id (None for legacy keys).

    For mk_ API keys, permissions are the *intersection* of the merchant's
    role-based permissions and the scopes declared on the key.  An API key
    with ``scopes=""`` (empty) inherits the full role permission set.
    """
    from app.exceptions.errors import AuthenticationError

    # 1. Bearer JWT
    if authorization and authorization.startswith("Bearer "):
        token = authorization[7:].strip()
        if not token:
            raise AuthenticationError("Empty bearer token")
        try:
            payload = decode_access_token(token)
            merchant_id = payload["sub"]
            # Load permissions from DB if available
            permissions = await _load_permissions(request, merchant_id)
            return MerchantContext(
                merchant_id=merchant_id,
                auth_method="jwt",
                permissions=permissions,
            )
        except jwt.ExpiredSignatureError:
            raise AuthenticationError("Token expired")
        except (jwt.InvalidTokenError, KeyError):
            raise AuthenticationError("Invalid token")

    # 2. Per-merchant API key (mk_ prefix)
    if x_api_key and x_api_key.startswith("mk_"):
        if len(x_api_key) <= 3:
            raise AuthenticationError("Invalid API key")
        db = get_db(request)
        if not db:
            raise AuthenticationError("API key verification unavailable")
        try:
            from app.db.merchant_store import MerchantStore
            store = MerchantStore(db)
            key_data = await store.verify_api_key(x_api_key)
            if key_data:
                merchant_id = str(key_data["merchant_id"])
                role_permissions = await _load_permissions(request, merchant_id)

                # Intersect role permissions with key scopes.
                # Empty scopes string means "inherit all role permissions".
                key_scopes_str = key_data.get("scopes", "") or ""
                if key_scopes_str.strip():
                    key_scopes = {
                        s.strip()
                        for s in key_scopes_str.split(",")
                        if s.strip()
                    }
                    permissions = [
                        p for p in role_permissions if p in key_scopes
                    ]
                else:
                    permissions = role_permissions

                return MerchantContext(
                    merchant_id=merchant_id,
                    auth_method="api_key",
                    permissions=permissions,
                )
        except AuthenticationError:
            raise
        except Exception:
            logger.warning("API key verification failed", exc_info=True)
        raise AuthenticationError("Invalid API key")

    # 3. Legacy API key
    if x_api_key and x_api_key in settings.valid_api_keys:
        return MerchantContext(merchant_id=None, auth_method="legacy")

    raise AuthenticationError()


async def _load_permissions(request: Request, merchant_id: str) -> list[str]:
    """Load merchant permissions from DB (best-effort)."""
    try:
        db = get_db(request)
        if db:
            from app.db.merchant_store import MerchantStore
            store = MerchantStore(db)
            return await store.get_permissions(merchant_id)
    except Exception:
        logger.debug("Failed to load permissions for %s", merchant_id, exc_info=True)
    return []


def require_permission(permission: str) -> Callable:
    """FastAPI dependency factory that enforces a specific permission.

    Usage::

        @router.get("/products")
        async def list_products(
            ctx: MerchantContext = Depends(require_permission("products:read")),
        ):
            ...

    Legacy API keys (no merchant_id) are allowed through -- they predate
    the permission system and are already gated by ``settings.valid_api_keys``.
    """

    async def _check(
        ctx: MerchantContext = Depends(get_current_merchant),
    ) -> MerchantContext:
        from app.exceptions.errors import ForbiddenError

        # Legacy keys bypass permission checks (backward compat)
        if ctx.auth_method == "legacy":
            return ctx

        if not ctx.has_permission(permission):
            raise ForbiddenError(
                f"Missing required permission: {permission}"
            )
        return ctx

    return _check


def parse_scopes(scopes_str: str) -> set[str]:
    """Parse a comma-separated scopes string into a set of scope codes."""
    if not scopes_str or not scopes_str.strip():
        return set()
    return {s.strip() for s in scopes_str.split(",") if s.strip()}


def validate_scopes(scopes_str: str) -> list[str]:
    """Validate that all scopes in a string are recognised.

    Returns list of invalid scope names (empty list = all valid).
    """
    parsed = parse_scopes(scopes_str)
    return sorted(parsed - VALID_SCOPES)


require_api_key = Depends(verify_api_key)

__all__ = [
    "MerchantContext",
    "VALID_SCOPES",
    "get_current_merchant",
    "get_db",
    "get_redis",
    "limiter",
    "parse_scopes",
    "require_api_key",
    "require_permission",
    "validate_scopes",
    "verify_api_key",
]
