"""Product query API routes."""

from __future__ import annotations

import json
import math
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import get_db, limiter, require_api_key
from app.config import settings
from app.db.queries import (
    COUNT_PRODUCTS_BY_DOMAIN,
    COUNT_PRODUCTS_BY_SHOP,
    SELECT_PRODUCTS_BY_DOMAIN,
    SELECT_PRODUCTS_BY_SHOP,
    SELECT_PRODUCT_BY_ID,
)
from app.exceptions.errors import NotFoundError
from app.services.url_normalizer import normalize_shop_url

if TYPE_CHECKING:
    from app.db.supabase_client import DatabaseClient

router = APIRouter(prefix="/products", tags=["products"])


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert an asyncpg Record to a JSON-safe dict."""
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, Decimal):
            d[k] = float(v)
        elif isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, str) and k in ("variants", "tags", "raw_data"):
            try:
                d[k] = json.loads(v)
            except (json.JSONDecodeError, TypeError):
                pass
    return d


def _extract_domain(shop_id: str) -> str:
    """Extract bare domain from a shop URL for fuzzy matching."""
    parsed = urlparse(shop_id if "://" in shop_id else f"https://{shop_id}")
    hostname = parsed.hostname or shop_id
    # Strip www. prefix for broader matching
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


@router.get("", dependencies=[require_api_key])
@limiter.limit(settings.rate_limit_default)
async def list_products(
    request: Request,
    shop_id: str = Query(..., description="Shop/merchant identifier"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(50, ge=1, le=100, description="Items per page"),
    db: DatabaseClient | None = Depends(get_db),
) -> dict[str, Any]:
    """List products for a shop with pagination."""
    shop_id = normalize_shop_url(shop_id)

    if db is None:
        return {
            "data": [],
            "pagination": {"page": page, "per_page": per_page, "total": 0, "total_pages": 0},
            "shop_id": shop_id,
        }

    offset = (page - 1) * per_page

    async with db.pool.acquire() as conn:
        # Try exact match first
        rows = await conn.fetch(SELECT_PRODUCTS_BY_SHOP, shop_id, per_page, offset)
        count_row = await conn.fetchval(COUNT_PRODUCTS_BY_SHOP, shop_id)
        total = count_row or 0

        # Fall back to domain-based match if exact match found nothing
        if total == 0:
            domain = _extract_domain(shop_id)
            rows = await conn.fetch(SELECT_PRODUCTS_BY_DOMAIN, domain, per_page, offset)
            total = await conn.fetchval(COUNT_PRODUCTS_BY_DOMAIN, domain) or 0

    total_pages = math.ceil(total / per_page) if per_page > 0 else 0

    return {
        "data": [_row_to_dict(r) for r in rows],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
        },
        "shop_id": shop_id,
    }


@router.get("/{product_id}", dependencies=[require_api_key])
@limiter.limit(settings.rate_limit_default)
async def get_product(
    request: Request,
    product_id: int,
    db: DatabaseClient | None = Depends(get_db),
) -> dict[str, Any]:
    """Get single product by ID."""
    if db is None:
        raise NotFoundError(f"Product {product_id} not found (database unavailable)")

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(SELECT_PRODUCT_BY_ID, product_id)

    if row is None:
        raise NotFoundError(f"Product {product_id} not found")

    return _row_to_dict(row)
