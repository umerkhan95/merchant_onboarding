"""Magento 2 OAuth authentication endpoints.

Implements both OAuth 1.0a callback flow and manual credential entry for Magento 2:

OAuth 1.0a flow (primary):
1. /connect -- returns callback_url and identity_url for Integration setup
2. /callback -- receives POST from Magento with consumer credentials + verifier,
   performs 2-step token exchange (request token -> access token)
3. /identity -- simple identity endpoint called by Magento during activation

Manual flow (fallback):
4. /manual -- accepts access_token directly, verifies against REST API, and stores
5. /disconnect -- revokes stored connection

Magento 2 OAuth 1.0a Integration flow:
- Merchant creates Integration in admin, sets Callback URL + Identity Link URL
- On activation, Magento POSTs consumer_key, consumer_secret, oauth_verifier to callback
- Our callback exchanges these for permanent access tokens via 2-step OAuth 1.0a
- Access tokens never expire -- no refresh needed
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import re
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.api.deps import get_db, limiter, verify_api_key
from app.config import settings
from app.security.nonce_store import TTLNonceStore

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/magento", tags=["auth"])

# 30-minute TTL: merchant needs time to create Integration and activate it.
_pending_nonces = TTLNonceStore(ttl=1800)


def _get_oauth_store(db):
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.db.oauth_store import OAuthStore
    return OAuthStore(db)


def _validate_magento_domain(shop: str) -> str:
    domain = shop.strip().lower()
    for prefix in ("https://", "http://"):
        if domain.startswith(prefix):
            domain = domain[len(prefix):]
    domain = domain.rstrip("/")

    if not domain:
        raise HTTPException(status_code=400, detail="Shop domain is required")

    if not re.match(r"^[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?(\.[a-zA-Z0-9]([a-zA-Z0-9\-]*[a-zA-Z0-9])?)*\.[a-zA-Z]{2,}$", domain):
        raise HTTPException(
            status_code=400,
            detail="Invalid shop domain: must be a valid hostname (e.g. my-store.com)",
        )

    return domain


def _extract_domain_from_url(store_base_url: str) -> str:
    """Extract domain from a Magento store base URL."""
    url = store_base_url.strip().lower()
    for prefix in ("https://", "http://"):
        if url.startswith(prefix):
            url = url[len(prefix):]
    # Remove path, query, fragment
    url = url.split("/")[0].split("?")[0].split("#")[0]
    return url


# -- OAuth 1.0a Signing --------------------------------------------------------


def _percent_encode(value: str) -> str:
    """RFC 5849 percent-encoding (same as RFC 3986 except space -> %20)."""
    return quote(value, safe="")


def _build_oauth1_header(
    method: str,
    url: str,
    consumer_key: str,
    consumer_secret: str,
    token: str = "",
    token_secret: str = "",
    verifier: str = "",
) -> str:
    """Build an OAuth 1.0a Authorization header per RFC 5849.

    Uses HMAC-SHA256 for signing. Returns the full header value string.
    """
    oauth_params = {
        "oauth_consumer_key": consumer_key,
        "oauth_nonce": secrets.token_hex(16),
        "oauth_signature_method": "HMAC-SHA256",
        "oauth_timestamp": str(int(time.time())),
        "oauth_version": "1.0",
    }

    if token:
        oauth_params["oauth_token"] = token
    if verifier:
        oauth_params["oauth_verifier"] = verifier

    # Build signature base string
    sorted_params = "&".join(
        f"{_percent_encode(k)}={_percent_encode(v)}"
        for k, v in sorted(oauth_params.items())
    )
    base_string = f"{method.upper()}&{_percent_encode(url)}&{_percent_encode(sorted_params)}"

    # Signing key
    signing_key = f"{_percent_encode(consumer_secret)}&{_percent_encode(token_secret)}"

    # HMAC-SHA256 signature
    signature = base64.b64encode(
        hmac.new(
            signing_key.encode("utf-8"),
            base_string.encode("utf-8"),
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    oauth_params["oauth_signature"] = signature

    # Build header string
    header_parts = ", ".join(
        f'{_percent_encode(k)}="{_percent_encode(v)}"'
        for k, v in sorted(oauth_params.items())
    )
    return f"OAuth {header_parts}"


# -- Token Exchange ------------------------------------------------------------


async def _exchange_magento_tokens(
    store_url: str,
    consumer_key: str,
    consumer_secret: str,
    verifier: str,
) -> dict | None:
    """Perform the 2-step OAuth 1.0a token exchange with Magento.

    Step 1: POST /oauth/token/request with consumer credentials -> request token
    Step 2: POST /oauth/token/access with consumer + request token + verifier -> access token

    Returns {"access_token": ..., "access_token_secret": ...} or None on failure.
    """
    request_token_url = f"{store_url}/oauth/token/request"
    access_token_url = f"{store_url}/oauth/token/access"

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Step 1: Get request token
            auth_header = _build_oauth1_header(
                method="POST",
                url=request_token_url,
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
            )
            logger.debug("Magento OAuth step 1: requesting token from %s", request_token_url)

            resp = await client.post(
                request_token_url,
                headers={"Authorization": auth_header},
            )
            if resp.status_code != 200:
                logger.warning(
                    "Magento request token failed: HTTP %d from %s",
                    resp.status_code, request_token_url,
                )
                return None

            # Response is URL-encoded: oauth_token=xxx&oauth_token_secret=yyy
            parsed = parse_qs(resp.text)
            request_token = parsed.get("oauth_token", [""])[0]
            request_token_secret = parsed.get("oauth_token_secret", [""])[0]
            if not request_token or not request_token_secret:
                logger.warning("Magento request token response missing fields: %s", resp.text)
                return None

            # Step 2: Exchange for access token
            auth_header = _build_oauth1_header(
                method="POST",
                url=access_token_url,
                consumer_key=consumer_key,
                consumer_secret=consumer_secret,
                token=request_token,
                token_secret=request_token_secret,
                verifier=verifier,
            )
            logger.debug("Magento OAuth step 2: exchanging for access token at %s", access_token_url)

            resp = await client.post(
                access_token_url,
                headers={"Authorization": auth_header},
            )
            if resp.status_code != 200:
                logger.warning(
                    "Magento access token exchange failed: HTTP %d from %s",
                    resp.status_code, access_token_url,
                )
                return None

            parsed = parse_qs(resp.text)
            access_token = parsed.get("oauth_token", [""])[0]
            access_token_secret = parsed.get("oauth_token_secret", [""])[0]
            if not access_token or not access_token_secret:
                logger.warning("Magento access token response missing fields: %s", resp.text)
                return None

            logger.info("Magento OAuth token exchange successful for %s", store_url)
            return {
                "access_token": access_token,
                "access_token_secret": access_token_secret,
            }

    except Exception as e:
        logger.warning("Magento token exchange error for %s: %s", store_url, e)
        return None


async def _verify_magento_token(
    domain: str, access_token: str
) -> dict | None:
    """Verify a Magento integration token by calling the storeConfigs endpoint.

    Returns the JSON response on success (list of store configs), or None on failure.
    """
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(
                f"https://{domain}/rest/V1/store/storeConfigs",
                headers={"Authorization": f"Bearer {access_token}"},
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning(
                "Magento token verification failed: HTTP %d for %s",
                resp.status_code, domain,
            )
            return None
    except Exception as e:
        logger.warning("Magento token verification error for %s: %s", domain, e)
        return None


# -- Magento OAuth Endpoints ---------------------------------------------------


@router.get("/connect")
@limiter.limit("5/minute")
async def magento_connect(
    request: Request,
    shop: str = Query(..., description="Magento store domain (e.g. my-store.com)"),
    _: str = Depends(verify_api_key),
) -> dict:
    """Initiate Magento OAuth 1.0a Integration setup.

    Returns callback_url and identity_url for the merchant to configure
    in their Magento admin panel Integration settings, plus step-by-step
    instructions.
    """
    domain = _validate_magento_domain(shop)

    # Register domain for CSRF validation (30min TTL)
    _pending_nonces[f"magento:{domain}"] = domain

    instructions = [
        {"step": 1, "text": "Open your Magento admin panel"},
        {"step": 2, "text": "Go to System > Extensions > Integrations > Add New Integration"},
        {"step": 3, "text": f"Set Callback URL to: {settings.magento_callback_url}"},
        {"step": 4, "text": f"Set Identity Link URL to: {settings.magento_identity_url}"},
        {"step": 5, "text": "Under API tab, grant access to Catalog resources"},
        {"step": 6, "text": "Save and click Activate"},
    ]

    return {
        "shop": domain,
        "platform": "magento",
        "admin_url": f"https://{domain}/admin",
        "callback_url": settings.magento_callback_url,
        "identity_url": settings.magento_identity_url,
        "instructions": instructions,
        "manual_url": "/api/v1/auth/magento/manual",
    }


@router.post("/callback")
@limiter.limit("10/minute")
async def magento_callback(
    request: Request,
    db=Depends(get_db),
) -> dict:
    """Handle Magento OAuth 1.0a Integration activation callback.

    Magento POSTs form data with:
    - oauth_consumer_key
    - oauth_consumer_secret
    - oauth_verifier
    - store_base_url

    This endpoint does NOT require API key auth -- it is called by Magento,
    not our frontend.
    """
    # Parse form data from Magento
    try:
        form = await request.form()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid form data")

    oauth_consumer_key = form.get("oauth_consumer_key", "")
    oauth_consumer_secret = form.get("oauth_consumer_secret", "")
    oauth_verifier = form.get("oauth_verifier", "")
    store_base_url = form.get("store_base_url", "")

    # Validate required fields
    if not oauth_consumer_key or not oauth_consumer_secret or not oauth_verifier:
        raise HTTPException(
            status_code=400,
            detail="Missing required fields: oauth_consumer_key, oauth_consumer_secret, oauth_verifier",
        )
    if not store_base_url:
        raise HTTPException(
            status_code=400,
            detail="Missing required field: store_base_url",
        )

    # Extract and validate domain
    domain = _extract_domain_from_url(str(store_base_url))
    if not domain:
        raise HTTPException(status_code=400, detail="Invalid store_base_url")

    # CSRF validation: check that this domain was registered via /connect
    nonce_key = f"magento:{domain}"
    expected_domain = _pending_nonces.pop(nonce_key, None)
    if expected_domain is None:
        logger.warning("Magento callback for unregistered domain: %s", domain)
        raise HTTPException(
            status_code=403,
            detail="Unknown domain: initiate connection via /connect first",
        )

    # Ensure store_base_url has scheme for token exchange
    store_url = str(store_base_url).rstrip("/")
    if not store_url.startswith("http"):
        store_url = f"https://{store_url}"

    # Perform 2-step OAuth 1.0a token exchange
    tokens = await _exchange_magento_tokens(
        store_url=store_url,
        consumer_key=str(oauth_consumer_key),
        consumer_secret=str(oauth_consumer_secret),
        verifier=str(oauth_verifier),
    )
    if tokens is None:
        raise HTTPException(
            status_code=502,
            detail="Failed to exchange OAuth tokens with Magento",
        )

    access_token = tokens["access_token"]
    access_token_secret = tokens["access_token_secret"]

    # Verify the access token works
    store_configs = await _verify_magento_token(domain, access_token)
    if store_configs is None:
        raise HTTPException(
            status_code=400,
            detail="Access token verification failed: could not authenticate with Magento REST API",
        )

    # Extract currency from storeConfigs
    currency = None
    if isinstance(store_configs, list) and store_configs:
        currency = store_configs[0].get("base_currency_code")

    # Store all credentials in OAuthStore
    oauth_store = _get_oauth_store(db)
    verified_at = datetime.now(timezone.utc).isoformat()
    await oauth_store.store_connection(
        platform="magento",
        shop_domain=domain,
        access_token=access_token,
        access_token_secret=access_token_secret,
        scopes="catalog",
        extra_data={
            "api_type": "oauth1",
            "consumer_key": str(oauth_consumer_key),
            "consumer_secret": str(oauth_consumer_secret),
            "verified_at": verified_at,
            "currency": currency,
        },
    )

    logger.info("Magento OAuth connected via callback: shop=%s", domain)
    return {
        "status": "connected",
        "platform": "magento",
        "shop": domain,
    }


@router.get("/identity", response_class=HTMLResponse)
@limiter.limit("10/minute")
async def magento_identity(request: Request) -> HTMLResponse:
    """Identity endpoint called by Magento during Integration activation.

    Magento GETs this URL to verify the Integration's identity link.
    Returns a simple confirmation page. No API key required.
    """
    return HTMLResponse(
        content="""
        <!DOCTYPE html>
        <html>
        <head><title>Merchant Onboarding - Identity Verification</title></head>
        <body>
            <h2>Merchant Onboarding Integration</h2>
            <p>Identity verified. You may close this window.</p>
        </body>
        </html>
        """,
        status_code=200,
    )


class MagentoCredentialInput(BaseModel):
    shop: str
    access_token: str


@router.post("/manual")
@limiter.limit("5/minute")
async def magento_manual(
    request: Request,
    body: MagentoCredentialInput,
    _: str = Depends(verify_api_key),
    db=Depends(get_db),
) -> dict:
    """Accept manually-entered Magento Integration access token.

    Fallback for merchants who prefer to paste their Integration token
    directly instead of using the OAuth 1.0a callback flow.
    """
    domain = _validate_magento_domain(body.shop)
    access_token = body.access_token.strip()

    if not access_token:
        raise HTTPException(status_code=400, detail="access_token is required")

    store_configs = await _verify_magento_token(domain, access_token)
    if store_configs is None:
        raise HTTPException(
            status_code=400,
            detail="Invalid access token: could not authenticate with Magento REST API",
        )

    # Extract currency from storeConfigs response
    currency = None
    if isinstance(store_configs, list) and store_configs:
        currency = store_configs[0].get("base_currency_code")

    oauth_store = _get_oauth_store(db)
    verified_at = datetime.now(timezone.utc).isoformat()
    await oauth_store.store_connection(
        platform="magento",
        shop_domain=domain,
        access_token=access_token,
        refresh_token=None,
        scopes="catalog",
        extra_data={
            "api_type": "integration",
            "verified_at": verified_at,
            "currency": currency,
        },
    )

    logger.info("Magento integration token stored: shop=%s", domain)
    return {
        "status": "connected",
        "platform": "magento",
        "shop": domain,
    }


@router.delete("/disconnect")
@limiter.limit("5/minute")
async def magento_disconnect(
    request: Request,
    shop: str = Query(..., description="Magento store domain"),
    _: str = Depends(verify_api_key),
    db=Depends(get_db),
) -> dict:
    domain = _validate_magento_domain(shop)
    oauth_store = _get_oauth_store(db)
    await oauth_store.revoke_connection("magento", domain)
    return {"status": "disconnected", "platform": "magento", "shop": domain}
