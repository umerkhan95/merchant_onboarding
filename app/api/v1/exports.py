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
from app.db.queries import (
    SELECT_MERCHANT_SETTINGS,
    SELECT_MERCHANT_SETTINGS_BY_DOMAIN,
    SELECT_PRODUCTS_BY_DOMAIN,
    SELECT_PRODUCTS_BY_SHOP,
)
from app.exceptions.errors import NotFoundError, ValidationError
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
    delivery_time: str = Query("", description="Delivery time override (uses stored settings if empty)"),
    delivery_costs: str = Query("", description="Delivery costs override (uses stored settings if empty)"),
    payment_costs: str = Query("", description="Payment costs override (uses stored settings if empty)"),
    brand_fallback: str = Query("", description="Fallback brand name override"),
    validate: bool = Query(False, description="If true, return validation errors instead of CSV when mandatory fields missing"),
    db: DatabaseClient | None = Depends(get_db),
) -> PlainTextResponse:
    """Export products as idealo-compatible CSV feed.

    Uses stored merchant settings for delivery/costs/payment. Query params override stored values.
    When validate=true, returns validation errors if mandatory settings are missing.
    """
    if db is None:
        raise NotFoundError("Database unavailable")

    shop_id = normalize_shop_url(shop_id)

    # Load stored merchant settings, let query params override
    stored_settings: dict[str, Any] = {}
    async with db.pool.acquire() as conn:
        settings_row = await conn.fetchrow(SELECT_MERCHANT_SETTINGS, shop_id)
        if not settings_row:
            domain = _extract_domain(shop_id)
            settings_row = await conn.fetchrow(SELECT_MERCHANT_SETTINGS_BY_DOMAIN, domain)
    if settings_row:
        stored_settings = dict(settings_row)

    final_delivery_time = delivery_time or stored_settings.get("delivery_time", "")
    final_delivery_costs = delivery_costs or stored_settings.get("delivery_costs", "")
    final_payment_costs = payment_costs or stored_settings.get("payment_costs", "")
    final_brand_fallback = brand_fallback or stored_settings.get("brand_fallback", "")

    # Validation gate: check mandatory settings when validate=true
    if validate:
        issues = []
        if not final_delivery_time:
            issues.append("delivery_time is required")
        if not final_delivery_costs:
            issues.append("delivery_costs is required")
        if not final_payment_costs:
            issues.append("payment_costs is required")
        if issues:
            raise ValidationError(f"Export blocked: {'; '.join(issues)}")

    rows = await _fetch_all_products(db, shop_id)
    if not rows:
        raise NotFoundError(f"No products found for shop: {shop_id}")

    product_models = _rows_to_products(rows)

    # Use shop domain as brand fallback if neither query param nor stored setting provides one
    domain = _extract_domain(shop_id)
    fallback = final_brand_fallback or domain.split(".")[0].replace("-", " ").title()

    exporter = IdealoCSVExporter(
        delivery_time=final_delivery_time,
        delivery_costs=final_delivery_costs,
        payment_costs=final_payment_costs,
        brand_fallback=fallback,
    )
    csv_content = exporter.export(product_models)

    filename = _safe_filename(_extract_domain(shop_id))
    return PlainTextResponse(
        content=csv_content,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="idealo-feed-{filename}.csv"'},
    )


@router.get("/idealo/validate", dependencies=[require_api_key])
@limiter.limit(settings.rate_limit_default)
async def validate_idealo_export(
    request: Request,
    shop_id: str = Query(..., description="Shop/merchant identifier"),
    db: DatabaseClient | None = Depends(get_db),
) -> dict[str, Any]:
    """Check if shop is ready for idealo export.

    Returns validation status with list of issues to fix.
    """
    if db is None:
        raise NotFoundError("Database unavailable")

    shop_id = normalize_shop_url(shop_id)
    issues: list[str] = []
    warnings: list[str] = []

    # Check merchant settings
    async with db.pool.acquire() as conn:
        settings_row = await conn.fetchrow(SELECT_MERCHANT_SETTINGS, shop_id)
        if not settings_row:
            domain = _extract_domain(shop_id)
            settings_row = await conn.fetchrow(SELECT_MERCHANT_SETTINGS_BY_DOMAIN, domain)

    if not settings_row:
        issues.append("Merchant settings not configured (delivery, costs, payment)")
    else:
        s = dict(settings_row)
        if not s.get("delivery_time"):
            issues.append("delivery_time is required")
        if not s.get("delivery_costs"):
            issues.append("delivery_costs is required")
        if not s.get("payment_costs"):
            issues.append("payment_costs is required")

    # Check products
    rows = await _fetch_all_products(db, shop_id)
    if not rows:
        issues.append("No products found")
    else:
        product_models = _rows_to_products(rows)
        missing_brand = sum(1 for p in product_models if not p.vendor)
        missing_gtin = sum(1 for p in product_models if not p.gtin)
        missing_sku = sum(1 for p in product_models if not p.sku and not p.external_id)

        if missing_sku > 0:
            issues.append(f"{missing_sku} products missing SKU/external_id (mandatory)")
        if missing_brand > 0:
            warnings.append(f"{missing_brand} products missing brand (will use fallback)")
        if missing_gtin > 0:
            warnings.append(f"{missing_gtin} products missing GTIN/EAN")

    return {
        "shop_id": shop_id,
        "ready": len(issues) == 0,
        "issues": issues,
        "warnings": warnings,
        "issue_count": len(issues),
        "warning_count": len(warnings),
    }
