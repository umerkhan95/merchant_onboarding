"""Shopware 6 OAuth authentication endpoints.

Implements credential-based integration auth for Shopware 6:
1. /connect — returns instructions for creating a Shopware Integration
2. /manual — accepts client_id + client_secret, verifies, and stores
3. /disconnect — revokes stored connection

Shopware 6 uses OAuth 2.0 Client Credentials grant. Merchants create an
Integration in their admin panel (Settings → System → Integrations), which
generates a client_id (Access key ID) and client_secret (Secret access key).
These are permanent credentials — no redirect or token refresh required.
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

router = APIRouter(prefix="/shopware", tags=["auth"])


def _get_oauth_store(db):
    if db is None:
        raise HTTPException(status_code=503, detail="Database unavailable")
    from app.db.oauth_store import OAuthStore
    return OAuthStore(db)


def _validate_sw_domain(shop: str) -> str:
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


async def _verify_sw_credentials(
    domain: str, client_id: str, client_secret: str
) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"https://{domain}/api/oauth/token",
                json={
                    "grant_type": "client_credentials",
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
            )
            if resp.status_code == 200:
                return resp.json()
            logger.warning(
                "Shopware credential verification failed: HTTP %d for %s",
                resp.status_code, domain,
            )
            return None
    except Exception as e:
        logger.warning("Shopware credential verification error for %s: %s", domain, e)
        return None


# ── Shopware OAuth Endpoints ───────────────────────────────────────


@router.get("/connect")
@limiter.limit("5/minute")
async def shopware_connect(
    request: Request,
    shop: str = Query(..., description="Shopware store domain (e.g. my-store.com)"),
    _: str = Depends(verify_api_key),
) -> dict:
    domain = _validate_sw_domain(shop)
    return {
        "shop": domain,
        "platform": "shopware",
        "admin_url": f"https://{domain}/admin#/sw/integration/index",
        "instructions": [
            {"step": 1, "text": "Open your Shopware admin panel", "link": f"https://{domain}/admin#/sw/integration/index"},
            {"step": 2, "text": "Click 'Add Integration'"},
            {"step": 3, "text": "Enter a name (e.g. 'idealo Onboarding')"},
            {"step": 4, "text": "Enable 'Administrator' access"},
            {"step": 5, "text": "Save and copy the Access key ID and Secret access key"},
        ],
        "manual_url": "/api/v1/auth/shopware/manual",
    }


class ShopwareCredentialInput(BaseModel):
    shop: str
    client_id: str
    client_secret: str


@router.post("/manual")
@limiter.limit("5/minute")
async def shopware_manual(
    request: Request,
    body: ShopwareCredentialInput,
    _: str = Depends(verify_api_key),
    db=Depends(get_db),
) -> dict:
    domain = _validate_sw_domain(body.shop)
    client_id = body.client_id.strip()
    client_secret = body.client_secret.strip()

    if not client_id:
        raise HTTPException(status_code=400, detail="client_id is required")
    if not client_secret:
        raise HTTPException(status_code=400, detail="client_secret is required")

    token_data = await _verify_sw_credentials(domain, client_id, client_secret)
    if not token_data:
        raise HTTPException(
            status_code=400,
            detail="Invalid credentials: could not authenticate with Shopware API",
        )

    oauth_store = _get_oauth_store(db)
    verified_at = datetime.now(timezone.utc).isoformat()
    await oauth_store.store_connection(
        platform="shopware",
        shop_domain=domain,
        access_token=client_id,
        refresh_token=client_secret,
        scopes="admin",
        extra_data={"api_type": "integration", "verified_at": verified_at},
    )

    logger.info("Shopware integration credentials stored: shop=%s", domain)
    return {
        "status": "connected",
        "platform": "shopware",
        "shop": domain,
    }


@router.delete("/disconnect")
@limiter.limit("5/minute")
async def shopware_disconnect(
    request: Request,
    shop: str = Query(..., description="Shopware store domain"),
    _: str = Depends(verify_api_key),
    db=Depends(get_db),
) -> dict:
    domain = _validate_sw_domain(shop)
    oauth_store = _get_oauth_store(db)
    await oauth_store.revoke_connection("shopware", domain)
    return {"status": "disconnected", "platform": "shopware", "shop": domain}
