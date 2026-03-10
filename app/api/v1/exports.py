"""Export API routes — generate idealo-compatible feeds from ingested products."""

from __future__ import annotations

import json
import logging
import re
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import PlainTextResponse

from app.api.deps import get_db, limiter, require_api_key
from app.config import settings
from app.db.queries import SELECT_PRODUCTS_BY_DOMAIN, SELECT_PRODUCTS_BY_SHOP
from app.exceptions.errors import NotFoundError
from app.exporters.idealo_csv import IdealoCSVExporter
from app.models.enums import Platform
from app.models.product import Product
from app.services.url_normalizer import normalize_shop_url

if TYPE_CHECKING:
    from app.db.supabase_client import DatabaseClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/exports", tags=["exports"])

_SAFE_FILENAME_RE = re.compile(r"[^a-zA-Z0-9.\-]")


def _extract_domain(shop_id: str) -> str:
    """Extract bare domain from a shop URL for fuzzy matching."""
    parsed = urlparse(shop_id if "://" in shop_id else f"https://{shop_id}")
    hostname = parsed.hostname or shop_id
    if hostname.startswith("www."):
        hostname = hostname[4:]
    return hostname


def _safe_filename(domain: str) -> str:
    """Sanitize domain for use in Content-Disposition filename."""
    return _SAFE_FILENAME_RE.sub("_", domain)


def _parse_jsonb(value: Any, default: Any) -> Any:
    """Parse JSONB field from DB — may be str, list, or already parsed."""
    if value is None:
        return default
    if isinstance(value, (list, dict)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except (json.JSONDecodeError, TypeError):
            return default
    return default


def _rows_to_products(rows: list) -> list[Product]:
    """Convert asyncpg rows to Product models, skipping corrupt rows."""
    products = []
    for row in rows:
        try:
            d = dict(row)
            products.append(Product(
                external_id=d["external_id"],
                shop_id=d["shop_id"],
                platform=Platform(d["platform"]),
                title=d["title"],
                description=d.get("description", ""),
                price=Decimal(str(d["price"])),
                compare_at_price=Decimal(str(d["compare_at_price"])) if d.get("compare_at_price") else None,
                currency=d.get("currency", "EUR"),
                image_url=d.get("image_url", ""),
                product_url=d.get("product_url", ""),
                sku=d.get("sku"),
                gtin=d.get("gtin"),
                mpn=d.get("mpn"),
                vendor=d.get("vendor"),
                product_type=d.get("product_type"),
                in_stock=d.get("in_stock", True),
                condition=d.get("condition"),
                variants=_parse_jsonb(d.get("variants"), []),
                tags=_parse_jsonb(d.get("tags"), []),
                additional_images=_parse_jsonb(d.get("additional_images"), []),
                category_path=_parse_jsonb(d.get("category_path"), []),
            ))
        except Exception:
            logger.warning("Skipping corrupt product row: id=%s", dict(row).get("id", "?"))
    return products


async def _fetch_all_products(db: DatabaseClient, shop_id: str) -> list:
    """Fetch all products for a shop (capped at 10,000)."""
    async with db.pool.acquire() as conn:
        rows = await conn.fetch(SELECT_PRODUCTS_BY_SHOP, shop_id, 10000, 0)
        if not rows:
            domain = _extract_domain(shop_id)
            rows = await conn.fetch(SELECT_PRODUCTS_BY_DOMAIN, domain, 10000, 0)
        return rows


@router.get("/idealo/csv", dependencies=[require_api_key])
@limiter.limit(settings.rate_limit_default)
async def export_idealo_csv(
    request: Request,
    shop_id: str = Query(..., description="Shop/merchant identifier"),
    delivery_time: str = Query("", description="Delivery time (e.g. '1-3 working days')"),
    delivery_costs: str = Query("", description="Delivery costs (e.g. '4.95' or 'DHL:4.95;DPD:5.95')"),
    payment_costs: str = Query("", description="Payment costs (e.g. '0.00' or 'PayPal:0.35')"),
    brand_fallback: str = Query("", description="Fallback brand name when product has no vendor"),
    db: DatabaseClient | None = Depends(get_db),
) -> PlainTextResponse:
    """Export products as idealo-compatible CSV feed.

    Returns comma-separated values with idealo's required columns.
    Merchant must provide delivery_time, delivery_costs, and payment_costs.
    """
    if db is None:
        raise NotFoundError("Database unavailable")

    shop_id = normalize_shop_url(shop_id)
    rows = await _fetch_all_products(db, shop_id)

    if not rows:
        raise NotFoundError(f"No products found for shop: {shop_id}")

    product_models = _rows_to_products(rows)

    # Use shop domain as brand fallback if merchant didn't provide one
    domain = _extract_domain(shop_id)
    fallback = brand_fallback or domain.split(".")[0].replace("-", " ").title()

    exporter = IdealoCSVExporter(
        delivery_time=delivery_time,
        delivery_costs=delivery_costs,
        payment_costs=payment_costs,
        brand_fallback=fallback,
    )
    csv_content = exporter.export(product_models)

    filename = _safe_filename(_extract_domain(shop_id))
    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="idealo-feed-{filename}.csv"'},
    )
