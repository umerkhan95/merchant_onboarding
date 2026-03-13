"""WooCommerce OAuth authentication endpoints.

Implements WooCommerce's built-in auto-auth flow:
1. /connect — redirects merchant to WooCommerce's /wc-auth/v1/authorize endpoint
2. /callback — receives POST with consumer_key + consumer_secret from WooCommerce
3. /return — merchant lands here after approving (success page)
4. /disconnect — revokes stored connection
5. /manual — merchant pastes consumer_key + consumer_secret directly

WooCommerce auto-auth generates REST API keys automatically.
Unlike Shopify/BigCommerce OAuth 2.0, WooCommerce uses its own key-exchange protocol:
- App redirects merchant to {store}/wc-auth/v1/authorize
- Merchant approves on their wp-admin consent screen
- WooCommerce POSTs consumer_key + consumer_secret to our callback_url
- Merchant is redirected to our return_url

After key exchange, all API calls use HTTP Basic Auth (consumer_key:consumer_secret).
"""

from __future__ import annotations

import html
import logging
import re
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.api.deps import get_db, limiter, verify_api_key
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/woocommerce", tags=["auth"])

# In-memory nonce store for CSRF protection.
# Maps nonce -> shop_domain for verifying callback legitimacy.
# For multi-process deployments, swap to Redis-backed store.
_pending_nonces: dict[str, str] = {}


def _get_oauth_store(db):
    """Create OAuthStore from DB client."""
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.db.oauth_store import OAuthStore
    return OAuthStore(db)


def _validate_wc_domain(shop: str) -> str:
    """Validate and normalize a WooCommerce store domain.

    WooCommerce stores can be on any domain (not just .myshopify.com).
    We validate basic structure: must be a valid hostname, no path/query.
    """
    domain = shop.strip().lower()
    # Strip scheme if present
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    domain = domain.rstrip("/")

    if not domain:
        raise HTTPException(status_code=400, detail="Shop domain is required")

    # Basic hostname validation: alphanumeric, hyphens, dots, no consecutive dots
    if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$", domain):
        raise HTTPException(
            status_code=400,
            detail="Invalid shop domain: must be a valid hostname (e.g. my-store.com)",
        )

    return domain


# ── WooCommerce OAuth Endpoints ───────────────────────────────────────


@router.get("/connect")
@limiter.limit("5/minute")
async def woocommerce_connect(
    request: Request,
    shop: str = Query(..., description="WooCommerce store domain (e.g. my-store.com)"),
    _: str = Depends(verify_api_key),
) -> dict:
    """Initiate WooCommerce auto-auth flow.

    Validates the shop domain, generates a CSRF nonce, and returns the
    WooCommerce authorization URL. The merchant is redirected to their
    wp-admin where they approve read-only API key generation.
    """
    if not settings.woocommerce_callback_url:
        raise HTTPException(status_code=501, detail="WooCommerce OAuth not configured")

    domain = _validate_wc_domain(shop)

    # Generate CSRF nonce — used as user_id param (echoed back by WooCommerce)
    nonce = secrets.token_urlsafe(32)
    _pending_nonces[nonce] = domain

    # WooCommerce auto-auth endpoint
    # https://woocommerce.github.io/woocommerce-rest-api-docs/#authentication
    params = urlencode({
        "app_name": settings.woocommerce_app_name,
        "scope": "read",
        "user_id": nonce,
        "return_url": settings.woocommerce_return_url,
        "callback_url": settings.woocommerce_callback_url,
    })
    auth_url = f"https://{domain}/wc-auth/v1/authorize?{params}"

    return {"auth_url": auth_url, "shop": domain}


@router.post("/callback")
@limiter.limit("10/minute")
async def woocommerce_callback(
    request: Request,
    db=Depends(get_db),
) -> dict:
    """Handle WooCommerce auto-auth callback.

    WooCommerce POSTs a JSON body with:
    - key_id: int
    - user_id: str (our nonce)
    - consumer_key: str (ck_...)
    - consumer_secret: str (cs_...)
    - key_permissions: str ("read", "write", or "read_write")

    We validate the nonce, verify the keys work, and store them encrypted.
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    user_id = body.get("user_id", "")
    consumer_key = body.get("consumer_key", "")
    consumer_secret = body.get("consumer_secret", "")
    key_permissions = body.get("key_permissions", "")

    # Validate required fields
    if not consumer_key or not consumer_secret:
        raise HTTPException(status_code=400, detail="Missing consumer_key or consumer_secret")

    # CSRF validation: verify user_id (our nonce) is one we generated
    expected_domain = _pending_nonces.pop(user_id, None)
    if expected_domain is None:
        logger.warning("WooCommerce callback with unknown nonce: user_id not recognized")
        raise HTTPException(status_code=403, detail="Invalid or expired state parameter")

    # Verify the consumer key format (WooCommerce keys always start with ck_/cs_)
    if not consumer_key.startswith("ck_"):
        logger.warning("WooCommerce callback with invalid consumer_key format")
        raise HTTPException(status_code=400, detail="Invalid consumer_key format")
    if not consumer_secret.startswith("cs_"):
        logger.warning("WooCommerce callback with invalid consumer_secret format")
        raise HTTPException(status_code=400, detail="Invalid consumer_secret format")

    # Verify the keys work by making a test API call
    verified = await _verify_wc_credentials(expected_domain, consumer_key, consumer_secret)
    if not verified:
        logger.warning("WooCommerce credentials failed verification for %s", expected_domain)
        raise HTTPException(
            status_code=502,
            detail="Failed to verify WooCommerce API credentials",
        )

    # Store encrypted in DB
    oauth_store = _get_oauth_store(db)
    await oauth_store.store_connection(
        platform="woocommerce",
        shop_domain=expected_domain,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        scopes=key_permissions or "read",
    )

    logger.info("WooCommerce OAuth connected: shop=%s, permissions=%s", expected_domain, key_permissions)

    return {
        "status": "connected",
        "platform": "woocommerce",
        "shop": expected_domain,
    }


@router.get("/return", response_class=HTMLResponse)
@limiter.limit("10/minute")
async def woocommerce_return(
    request: Request,
    success: str = Query(None),
    user_id: str = Query(None),
) -> HTMLResponse:
    """Return page after WooCommerce auto-auth completes.

    WooCommerce redirects the merchant here with ?success=1&user_id={nonce}.
    This page closes the popup and signals the frontend.
    """
    is_success = success in ("1", "true", "yes")
    frontend_origin = getattr(settings, "frontend_url", "http://localhost:3001")

    if is_success:
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
                            {{ type: 'woocommerce_oauth_complete', success: true }},
                            '{html.escape(frontend_origin, quote=True)}'
                        );
                    }}
                    setTimeout(() => window.close(), 1500);
                </script>
            </body>
            </html>
            """
        )
    else:
        return HTMLResponse(
            content=f"""
            <!DOCTYPE html>
            <html>
            <head><title>Authorization Failed</title></head>
            <body>
                <h2>Authorization was not completed.</h2>
                <p>You can close this window and try again.</p>
                <script>
                    if (window.opener) {{
                        window.opener.postMessage(
                            {{ type: 'woocommerce_oauth_complete', success: false }},
                            '{html.escape(frontend_origin, quote=True)}'
                        );
                    }}
                    setTimeout(() => window.close(), 3000);
                </script>
            </body>
            </html>
            """
        )


class ManualKeyInput(BaseModel):
    """Request body for manual WooCommerce API key input."""
    shop: str
    consumer_key: str
    consumer_secret: str


@router.post("/manual")
@limiter.limit("5/minute")
async def woocommerce_manual(
    request: Request,
    body: ManualKeyInput,
    _: str = Depends(verify_api_key),
    db=Depends(get_db),
) -> dict:
    """Accept manually-entered WooCommerce REST API credentials.

    Fallback for stores where the auto-auth endpoint is unavailable
    (e.g. pretty permalinks disabled, security plugins blocking wc-auth).

    Validates credentials by making a test API call before storing.
    """
    domain = _validate_wc_domain(body.shop)
    consumer_key = body.consumer_key.strip()
    consumer_secret = body.consumer_secret.strip()

    if not consumer_key.startswith("ck_"):
        raise HTTPException(status_code=400, detail="Consumer key must start with 'ck_'")
    if not consumer_secret.startswith("cs_"):
        raise HTTPException(status_code=400, detail="Consumer secret must start with 'cs_'")

    # Verify credentials by making a test API call
    verified = await _verify_wc_credentials(domain, consumer_key, consumer_secret)
    if not verified:
        raise HTTPException(
            status_code=400,
            detail="Invalid credentials: could not authenticate with WooCommerce REST API",
        )

    oauth_store = _get_oauth_store(db)
    await oauth_store.store_connection(
        platform="woocommerce",
        shop_domain=domain,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
        scopes="read",
    )

    logger.info("WooCommerce manual credentials stored: shop=%s", domain)
    return {
        "status": "connected",
        "platform": "woocommerce",
        "shop": domain,
    }


@router.delete("/disconnect")
@limiter.limit("5/minute")
async def woocommerce_disconnect(
    request: Request,
    shop: str = Query(..., description="WooCommerce store domain"),
    _: str = Depends(verify_api_key),
    db=Depends(get_db),
) -> dict:
    """Revoke WooCommerce OAuth connection."""
    domain = _validate_wc_domain(shop)
    oauth_store = _get_oauth_store(db)
    await oauth_store.revoke_connection("woocommerce", domain)
    return {"status": "disconnected", "platform": "woocommerce", "shop": domain}


# ── Helpers ───────────────────────────────────────────────────────────


async def _verify_wc_credentials(
    domain: str, consumer_key: str, consumer_secret: str
) -> bool:
    """Verify WooCommerce REST API credentials by fetching a single product.

    Uses HTTP Basic Auth (consumer_key as username, consumer_secret as password).
    Returns True if the API responds with 200.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://{domain}/wp-json/wc/v3/products",
                params={"per_page": 1},
                auth=(consumer_key, consumer_secret),
            )
            if resp.status_code == 200:
                return True
            logger.warning(
                "WooCommerce credential verification failed: HTTP %d for %s",
                resp.status_code, domain,
            )
            return False
    except Exception as e:
        logger.warning("WooCommerce credential verification error for %s: %s", domain, e)
        return False
