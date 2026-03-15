"""Merchant authentication endpoints: register, login, refresh, logout, API keys."""

from __future__ import annotations

import logging
import uuid as _uuid
from typing import Any

from fastapi import APIRouter, Cookie, Depends, Request, Response
from pydantic import BaseModel, EmailStr, Field

from app.api.deps import (
    MerchantContext,
    get_current_merchant,
    get_db,
    parse_scopes,
    validate_scopes,
)
from app.db.merchant_store import MerchantStore
from app.exceptions.errors import (
    AuthenticationError,
    ForbiddenError,
    NotFoundError,
    ValidationError,
)
from app.security.jwt_handler import create_access_token
from app.security.password import verify_password

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/merchant", tags=["merchant-auth"])


# --- Request/Response Models ---

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=1, max_length=128)


class AuthResponse(BaseModel):
    access_token: str
    merchant_id: str
    token_type: str = "bearer"


class CreateApiKeyRequest(BaseModel):
    name: str = Field(default="", max_length=100)
    scopes: str = Field(default="")


class ApiKeyResponse(BaseModel):
    key: str
    id: str
    key_prefix: str
    name: str
    scopes: str
    expires_at: str | None = None
    created_at: str | None = None


def _get_client_info(request: Request) -> tuple[str, str]:
    """Extract IP and User-Agent from request."""
    ip = request.client.host if request.client else ""
    ua = request.headers.get("user-agent", "")
    return ip, ua


def _set_refresh_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key="refresh_token",
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=30 * 24 * 3600,
        path="/api/v1/auth/merchant",
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key="refresh_token",
        httponly=True,
        secure=True,
        samesite="lax",
        path="/api/v1/auth/merchant",
    )


# --- Endpoints ---

@router.post("/register", status_code=201, response_model=AuthResponse)
async def register(body: RegisterRequest, request: Request, response: Response):
    db = get_db(request)
    if not db:
        raise ValidationError("Database unavailable")

    store = MerchantStore(db)
    ip, ua = _get_client_info(request)

    # Check if email already exists
    existing, _ = await store.get_by_email(body.email)
    if existing:
        raise ValidationError("Email already registered")

    try:
        account = await store.create_account(body.email, body.password)
    except Exception as exc:
        # Handle race condition: concurrent registration with same email
        # asyncpg.UniqueViolationError when email_hash UNIQUE constraint fires
        exc_name = type(exc).__name__
        if "UniqueViolation" in exc_name:
            raise ValidationError("Email already registered")
        logger.error("Registration failed: %s", exc, exc_info=True)
        raise ValidationError("Registration failed — please try again")

    access_token = create_access_token(account.id)

    # Create refresh token + cookie
    raw_refresh, _ = await store.create_refresh_token(
        account.id, user_agent=ua, ip_address=ip,
    )
    _set_refresh_cookie(response, raw_refresh)

    await store.audit_log(account.id, "register", ip, ua)

    return AuthResponse(access_token=access_token, merchant_id=account.id)


@router.post("/login", response_model=AuthResponse)
async def login(body: LoginRequest, request: Request, response: Response):
    db = get_db(request)
    if not db:
        raise ValidationError("Database unavailable")

    store = MerchantStore(db)
    ip, ua = _get_client_info(request)

    try:
        account, pw_hash = await store.get_by_email(body.email)
    except Exception:
        logger.error("Login DB lookup failed", exc_info=True)
        raise ValidationError("Service temporarily unavailable")

    if not account or not pw_hash:
        await store.audit_log(None, "login_failed", ip, ua, {"reason": "unknown_email"})
        raise AuthenticationError("Invalid credentials")

    # Check lockout (temporary state — check before permanent status)
    if store.is_locked(account):
        await store.audit_log(account.id, "login_locked", ip, ua)
        raise AuthenticationError("Account temporarily locked. Try again later.")

    # Check account status (suspended, deactivated, etc.)
    if account.account_status != "active":
        await store.audit_log(account.id, "login_inactive", ip, ua)
        raise AuthenticationError("Account is not active")

    if not verify_password(body.password, pw_hash):
        await store.record_failed_login(account.id)
        await store.audit_log(account.id, "login_failed", ip, ua, {"reason": "wrong_password"})
        raise AuthenticationError("Invalid credentials")

    # Success — reset lockout counter
    await store.reset_failed_logins(account.id)
    access_token = create_access_token(account.id)

    raw_refresh, _ = await store.create_refresh_token(
        account.id, user_agent=ua, ip_address=ip,
    )
    _set_refresh_cookie(response, raw_refresh)

    await store.audit_log(account.id, "login_success", ip, ua)

    return AuthResponse(access_token=access_token, merchant_id=account.id)


@router.post("/refresh", response_model=AuthResponse)
async def refresh(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None),
):
    if not refresh_token:
        raise AuthenticationError("No refresh token")

    db = get_db(request)
    if not db:
        raise ValidationError("Database unavailable")

    store = MerchantStore(db)
    ip, ua = _get_client_info(request)

    try:
        # Verify the old token
        token_data = await store.verify_refresh_token(refresh_token)
    except Exception:
        logger.error("Refresh token verification failed", exc_info=True)
        _clear_refresh_cookie(response)
        raise AuthenticationError("Invalid refresh token")

    if not token_data:
        _clear_refresh_cookie(response)
        raise AuthenticationError("Invalid refresh token")

    merchant_id = str(token_data["merchant_id"])

    try:
        # Rotate
        result = await store.rotate_refresh_token(
            refresh_token, merchant_id, user_agent=ua, ip_address=ip,
        )
    except Exception:
        logger.error("Token rotation failed", exc_info=True)
        _clear_refresh_cookie(response)
        raise AuthenticationError("Refresh failed — please login again")

    if not result:
        _clear_refresh_cookie(response)
        raise AuthenticationError("Refresh token expired or reused")

    new_raw_token, _ = result
    access_token = create_access_token(merchant_id)
    _set_refresh_cookie(response, new_raw_token)

    await store.audit_log(merchant_id, "token_refresh", ip, ua)

    return AuthResponse(access_token=access_token, merchant_id=merchant_id)


@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    refresh_token: str | None = Cookie(default=None),
):
    db = get_db(request)
    ip, ua = _get_client_info(request)

    if refresh_token and db:
        try:
            store = MerchantStore(db)
            token_data = await store.verify_refresh_token(refresh_token)
            if token_data and not token_data["revoked"]:
                from app.db.queries import REVOKE_REFRESH_TOKEN
                async with db.pool.acquire() as conn:
                    await conn.execute(REVOKE_REFRESH_TOKEN, token_data["id"])
                await store.audit_log(
                    str(token_data["merchant_id"]), "logout", ip, ua,
                )
        except Exception:
            # Logout should never fail -- best-effort revocation
            logger.warning("Failed to revoke token during logout", exc_info=True)

    _clear_refresh_cookie(response)
    return {"detail": "Logged out"}


@router.post("/logout-all")
async def logout_all(
    request: Request,
    response: Response,
    ctx: MerchantContext = Depends(get_current_merchant),
):
    if not ctx.merchant_id:
        raise AuthenticationError("JWT required")

    db = get_db(request)
    if not db:
        raise ValidationError("Database unavailable")

    store = MerchantStore(db)
    ip, ua = _get_client_info(request)
    await store.revoke_all_sessions(ctx.merchant_id)
    await store.audit_log(ctx.merchant_id, "logout_all", ip, ua)
    _clear_refresh_cookie(response)
    return {"detail": "All sessions revoked"}


@router.get("/sessions")
async def list_sessions(
    request: Request,
    ctx: MerchantContext = Depends(get_current_merchant),
):
    if not ctx.merchant_id:
        raise AuthenticationError("JWT required")

    db = get_db(request)
    if not db:
        raise ValidationError("Database unavailable")

    store = MerchantStore(db)
    sessions = await store.list_sessions(ctx.merchant_id)
    return {"sessions": sessions}


@router.post("/api-keys", status_code=201, response_model=ApiKeyResponse)
async def create_api_key(
    body: CreateApiKeyRequest,
    request: Request,
    ctx: MerchantContext = Depends(get_current_merchant),
):
    if not ctx.merchant_id:
        raise AuthenticationError("JWT required")

    # Validate that all requested scopes are recognised system scopes.
    if body.scopes:
        invalid = validate_scopes(body.scopes)
        if invalid:
            raise ValidationError(
                f"Unknown scopes: {', '.join(invalid)}"
            )

        # Ensure requested scopes are a subset of the merchant's own permissions.
        # This prevents privilege escalation (e.g. a 'merchant' role requesting
        # 'admin:manage' on an API key).
        requested = parse_scopes(body.scopes)
        merchant_perms = set(ctx.permissions)
        excess = sorted(requested - merchant_perms)
        if excess:
            raise ForbiddenError(
                f"Cannot grant scopes beyond your permissions: {', '.join(excess)}"
            )

    db = get_db(request)
    if not db:
        raise ValidationError("Database unavailable")

    store = MerchantStore(db)
    ip, ua = _get_client_info(request)
    raw_key, metadata = await store.create_api_key(
        ctx.merchant_id, name=body.name, scopes=body.scopes,
    )
    await store.audit_log(
        ctx.merchant_id, "api_key_created", ip, ua,
        {"key_prefix": metadata["key_prefix"], "name": body.name, "scopes": body.scopes},
    )
    return ApiKeyResponse(key=raw_key, **metadata)


@router.get("/api-keys")
async def list_api_keys(
    request: Request,
    ctx: MerchantContext = Depends(get_current_merchant),
):
    if not ctx.merchant_id:
        raise AuthenticationError("JWT required")

    db = get_db(request)
    if not db:
        raise ValidationError("Database unavailable")

    store = MerchantStore(db)
    keys = await store.list_api_keys(ctx.merchant_id)
    return {"api_keys": keys}


@router.delete("/api-keys/{key_id}")
async def revoke_api_key_endpoint(
    key_id: str,
    request: Request,
    ctx: MerchantContext = Depends(get_current_merchant),
):
    if not ctx.merchant_id:
        raise AuthenticationError("JWT required")

    # Validate key_id is a valid UUID before hitting the DB
    try:
        _uuid.UUID(key_id)
    except (ValueError, AttributeError):
        raise NotFoundError("API key not found")

    db = get_db(request)
    if not db:
        raise ValidationError("Database unavailable")

    store = MerchantStore(db)
    ip, ua = _get_client_info(request)
    revoked = await store.revoke_api_key(key_id, ctx.merchant_id)
    if not revoked:
        raise NotFoundError("API key not found")
    await store.audit_log(ctx.merchant_id, "api_key_revoked", ip, ua, {"key_id": key_id})
    return {"detail": "API key revoked"}
