"""Shopify OAuth authentication endpoints.

Implements the Shopify OAuth 2.0 authorization code flow:
1. /connect — generates auth URL with HMAC nonce for CSRF protection
2. /callback — validates HMAC, exchanges code for access token, stores encrypted
3. /disconnect — revokes stored connection
"""

from __future__ import annotations

import hashlib
import hmac
import html
import logging
import re
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse

from app.api.deps import get_db, limiter, verify_api_key
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/shopify", tags=["auth"])

# In-memory nonce store (for single-process deployments).
# For multi-process, swap to Redis-backed store.
_pending_nonces: dict[str, str] = {}


def _get_oauth_store(db):
    """Create OAuthStore from DB client."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.db.oauth_store import OAuthStore
    return OAuthStore(db)


def _validate_shop_domain(shop: str) -> str:
    """Validate and normalize a Shopify shop domain.

    Shopify domains must match: {shop}.myshopify.com per Shopify's security model.
    Returns the normalized domain (no scheme, no trailing slash).
    """
    domain = shop.strip().lower()
    # Strip scheme if present
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    domain = domain.rstrip("/")

    if not domain:
        raise HTTPException(status_code=400, detail="Shop domain is required")

    # Strict validation: must match Shopify's myshopify.com pattern
    if not re.match(r"^[a-zA-Z0-9][a-zA-Z0-9\-]*\.myshopify\.com$", domain):
        raise HTTPException(
            status_code=400,
            detail="Invalid shop domain: must be {store}.myshopify.com",
        )

    return domain


def _verify_shopify_hmac(query_params: dict[str, str], client_secret: str) -> bool:
    """Verify the HMAC signature Shopify sends with the OAuth callback.

    Shopify computes HMAC-SHA256 over all query params (except 'hmac' itself),
    sorted alphabetically and joined with '&', using the app's client_secret.
    """
    received_hmac = query_params.get("hmac", "")
    if not received_hmac:
        return False

    # Build the message: all params except 'hmac', sorted, URL-encoded
    filtered = {k: v for k, v in sorted(query_params.items()) if k != "hmac"}
    message = "&".join(f"{k}={v}" for k, v in filtered.items())

    computed = hmac.new(
        client_secret.encode("utf-8"),
        message.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()

    return hmac.compare_digest(computed, received_hmac)


# ── Shopify OAuth Endpoints ──────────────────────────────────────────


@router.get("/connect")
@limiter.limit("5/minute")
async def shopify_connect(
    request: Request,
    shop: str = Query(..., description="Shopify store domain (e.g. example.myshopify.com)"),
    _: str = Depends(verify_api_key),
) -> dict:
    """Initiate Shopify OAuth flow.

    Validates the shop domain, generates a CSRF nonce, and returns the
    Shopify authorization URL that the merchant should be redirected to.
    """
    if not settings.shopify_client_id:
        raise HTTPException(status_code=501, detail="Shopify OAuth not configured")

    domain = _validate_shop_domain(shop)

    # Generate CSRF nonce
    nonce = secrets.token_urlsafe(32)
    _pending_nonces[nonce] = domain

    params = urlencode({
        "client_id": settings.shopify_client_id,
        "scope": "read_products",
        "redirect_uri": settings.shopify_callback_url,
        "state": nonce,
    })
    auth_url = f"https://{domain}/admin/oauth/authorize?{params}"

    return {"auth_url": auth_url, "shop": domain}


@router.get("/callback", response_class=HTMLResponse)
@limiter.limit("5/minute")
async def shopify_callback(
    request: Request,
    code: str = Query(...),
    shop: str = Query(...),
    state: str = Query(...),
    db=Depends(get_db),
) -> HTMLResponse:
    """Handle Shopify OAuth callback.

    Validates HMAC signature and state nonce, exchanges authorization code
    for a permanent access token, and stores it encrypted.

    Returns an HTML page that closes the popup window.
    """
    if not settings.shopify_client_id or not settings.shopify_client_secret:
        raise HTTPException(status_code=501, detail="Shopify OAuth not configured")

    # 1. Validate HMAC signature (Shopify signs all callback params)
    query_params = dict(request.query_params)
    if not _verify_shopify_hmac(query_params, settings.shopify_client_secret):
        logger.warning("Shopify callback HMAC validation failed for shop=%s", shop)
        raise HTTPException(status_code=403, detail="HMAC validation failed")

    # 2. Validate state/nonce (CSRF protection)
    expected_domain = _pending_nonces.pop(state, None)
    if expected_domain is None:
        logger.warning("Shopify callback with unknown state nonce for shop=%s", shop)
        raise HTTPException(status_code=403, detail="Invalid or expired state parameter")

    domain = _validate_shop_domain(shop)

    # 3. Exchange authorization code for permanent access token
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            f"https://{domain}/admin/oauth/access_token",
            json={
                "client_id": settings.shopify_client_id,
                "client_secret": settings.shopify_client_secret,
                "code": code,
            },
        )

    if resp.status_code != 200:
        logger.error(
            "Shopify token exchange failed: HTTP %d", resp.status_code
        )
        raise HTTPException(
            status_code=502,
            detail="Failed to exchange Shopify authorization code",
        )

    token_data = resp.json()
    access_token = token_data.get("access_token")
    if not access_token:
        raise HTTPException(
            status_code=502, detail="Shopify did not return an access token"
        )

    scope = token_data.get("scope", "read_products")

    # 4. Store encrypted token
    oauth_store = _get_oauth_store(db)
    await oauth_store.store_connection(
        platform="shopify",
        shop_domain=domain,
        access_token=access_token,
        scopes=scope,
    )

    logger.info("Shopify OAuth connected: shop=%s, scopes=%s", domain, scope)

    # 5. Return HTML that closes the popup window
    safe_domain = html.escape(domain, quote=True)
    frontend_origin = getattr(settings, "frontend_url", "http://localhost:3001")
    return HTMLResponse(
        content=f"""
        <!DOCTYPE html>
        <html>
        <head><title>Connected</title></head>
        <body>
            <h2>Store connected successfully!</h2>
            <p>You can close this window.</p>
            <script>
                if (window.opener) {{
                    window.opener.postMessage(
                        {{ type: 'shopify_oauth_complete', shop: '{safe_domain}' }},
                        '{html.escape(frontend_origin, quote=True)}'
                    );
                }}
                setTimeout(() => window.close(), 1500);
            </script>
        </body>
        </html>
        """
    )


@router.delete("/disconnect")
@limiter.limit("5/minute")
async def shopify_disconnect(
    request: Request,
    shop: str = Query(..., description="Shopify store domain"),
    _: str = Depends(verify_api_key),
    db=Depends(get_db),
) -> dict:
    """Revoke Shopify OAuth connection."""
    domain = _validate_shop_domain(shop)
    oauth_store = _get_oauth_store(db)
    await oauth_store.revoke_connection("shopify", domain)
    return {"status": "disconnected", "platform": "shopify", "shop": domain}
