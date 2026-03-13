"""OAuth authentication endpoints for platform integrations."""

from __future__ import annotations

import logging
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.api.deps import get_db, limiter, verify_api_key
from app.api.v1.shopify_auth import router as shopify_auth_router
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Include Shopify auth sub-router (mounted at /auth/shopify/*)
router.include_router(shopify_auth_router)


def _get_oauth_store(db):
    """Create OAuthStore from DB client."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.db.oauth_store import OAuthStore
    return OAuthStore(db)


# ── BigCommerce OAuth ────────────────────────────────────────────────

# In-memory nonce store for BigCommerce CSRF protection.
# For multi-process deployments, swap to Redis-backed store.
_bc_pending_nonces: dict[str, str] = {}


@router.get("/bigcommerce/connect")
@limiter.limit("5/minute")
async def bigcommerce_connect(
    request: Request,
    shop: str = Query(..., description="BigCommerce store domain (e.g. store-abc123.mybigcommerce.com)"),
    _: str = Depends(verify_api_key),
) -> dict:
    """Initiate BigCommerce OAuth flow.

    Returns the authorization URL that the merchant should be redirected to.
    The merchant approves access, then BigCommerce redirects to our callback.
    """
    if not settings.bigcommerce_client_id:
        raise HTTPException(status_code=501, detail="BigCommerce OAuth not configured")

    # Generate CSRF nonce
    nonce = secrets.token_urlsafe(32)
    _bc_pending_nonces[nonce] = shop

    # BigCommerce OAuth install URL
    params = urlencode({
        "client_id": settings.bigcommerce_client_id,
        "scope": "store_v2_products_read_only",
        "response_type": "code",
        "redirect_uri": settings.bigcommerce_callback_url,
        "context": f"stores/{shop}",
        "state": nonce,
    })
    auth_url = f"https://login.bigcommerce.com/oauth2/authorize?{params}"

    return {"auth_url": auth_url, "shop": shop}


@router.get("/bigcommerce/callback")
@limiter.limit("5/minute")
async def bigcommerce_callback(
    request: Request,
    code: str = Query(...),
    scope: str = Query(...),
    context: str = Query(...),
    state: str = Query(None),
    db=Depends(get_db),
) -> dict:
    """Handle BigCommerce OAuth callback — exchange code for permanent access token.

    BigCommerce redirects here after merchant approves. We exchange the
    authorization code for an access token (which never expires).
    """
    if not settings.bigcommerce_client_id or not settings.bigcommerce_client_secret:
        raise HTTPException(status_code=501, detail="BigCommerce OAuth not configured")

    # CSRF validation: verify the state nonce matches one we generated
    if not state or state not in _bc_pending_nonces:
        raise HTTPException(status_code=403, detail="Invalid or missing state parameter (CSRF check failed)")
    _bc_pending_nonces.pop(state, None)

    # Extract store hash from context (format: "stores/abc123")
    store_hash = context.replace("stores/", "") if context.startswith("stores/") else context

    # Exchange authorization code for access token
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            "https://login.bigcommerce.com/oauth2/token",
            json={
                "client_id": settings.bigcommerce_client_id,
                "client_secret": settings.bigcommerce_client_secret,
                "code": code,
                "scope": scope,
                "grant_type": "authorization_code",
                "redirect_uri": settings.bigcommerce_callback_url,
                "context": context,
            },
        )

    if resp.status_code != 200:
        logger.error("BigCommerce token exchange failed: HTTP %d", resp.status_code)
        raise HTTPException(status_code=502, detail="Failed to exchange BigCommerce authorization code")

    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(status_code=502, detail="BigCommerce did not return an access token")

    # Store encrypted in DB
    oauth_store = _get_oauth_store(db)
    shop_domain = token_data.get("context", context).replace("stores/", "")

    await oauth_store.store_connection(
        platform="bigcommerce",
        shop_domain=shop_domain,
        access_token=access_token,
        scopes=scope,
        store_hash=store_hash,
        extra_data={
            "user_id": token_data.get("user", {}).get("id"),
            "user_email": token_data.get("user", {}).get("email"),
        },
    )

    logger.info("BigCommerce OAuth connected: store_hash=%s", store_hash)
    return {
        "status": "connected",
        "platform": "bigcommerce",
        "store_hash": store_hash,
    }


@router.delete("/bigcommerce/disconnect")
@limiter.limit("5/minute")
async def bigcommerce_disconnect(
    request: Request,
    shop: str = Query(..., description="BigCommerce store hash or domain"),
    _: str = Depends(verify_api_key),
    db=Depends(get_db),
) -> dict:
    """Revoke BigCommerce OAuth connection."""
    oauth_store = _get_oauth_store(db)
    await oauth_store.revoke_connection("bigcommerce", shop)
    return {"status": "disconnected", "platform": "bigcommerce", "shop": shop}


# ── Connection Management ────────────────────────────────────────────


@router.get("/connections")
@limiter.limit(settings.rate_limit_default)
async def list_connections(
    request: Request,
    _: str = Depends(verify_api_key),
    db=Depends(get_db),
) -> list[dict]:
    """List all active OAuth connections (tokens not exposed)."""
    oauth_store = _get_oauth_store(db)
    return await oauth_store.list_connections()


@router.get("/connections/{shop_domain:path}")
@limiter.limit(settings.rate_limit_default)
async def get_connection_status(
    request: Request,
    shop_domain: str,
    _: str = Depends(verify_api_key),
    db=Depends(get_db),
) -> dict:
    """Check OAuth connection status for a specific shop domain."""
    oauth_store = _get_oauth_store(db)
    conn = await oauth_store.get_connection_by_domain(shop_domain)
    if not conn:
        return {"connected": False, "shop_domain": shop_domain}
    return {
        "connected": True,
        "platform": conn.platform,
        "shop_domain": conn.shop_domain,
        "store_hash": conn.store_hash,
        "scopes": conn.scopes,
        "connected_at": conn.connected_at.isoformat() if conn.connected_at else None,
        "last_used_at": conn.last_used_at.isoformat() if conn.last_used_at else None,
    }
