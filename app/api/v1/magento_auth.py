"""Magento 2 OAuth authentication endpoints.

Implements credential-based integration auth for Magento 2:
1. /connect — returns instructions for creating a Magento Integration
2. /manual — accepts access_token, verifies against REST API, and stores
3. /disconnect — revokes stored connection

Magento 2 uses Integration tokens. Merchants create an Integration in their
admin panel (System -> Extensions -> Integrations), which generates an
Access Token. This is a permanent bearer token — no refresh required.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel

from app.api.deps import get_db, limiter, verify_api_key

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/magento", tags=["auth"])


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
    domain = _validate_magento_domain(shop)
    return {
        "shop": domain,
        "platform": "magento",
        "instructions": (
            "Create an Integration in your Magento admin: "
            "System \u2192 Extensions \u2192 Integrations \u2192 Add New Integration. "
            "Grant API access to Catalog resources, then activate the integration "
            "and copy the Access Token."
        ),
        "manual_url": "/api/v1/auth/magento/manual",
    }


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
