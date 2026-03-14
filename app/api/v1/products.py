"""Product query API routes."""

from __future__ import annotations

import csv
import io
import json
import math
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Query, Request, UploadFile

from app.api.deps import get_db, limiter, require_api_key
from app.config import settings
from app.db.bulk_ingestor import BulkIngestor
from app.db.queries import (
    COUNT_PRODUCTS_BY_DOMAIN,
    COUNT_PRODUCTS_BY_SHOP,
    COUNT_PRODUCTS_MISSING_FIELD,
    COUNT_PRODUCTS_MISSING_FIELD_BY_DOMAIN,
    SELECT_PRODUCTS_BY_DOMAIN,
    SELECT_PRODUCTS_BY_SHOP,
    SELECT_PRODUCT_BY_ID,
    SELECT_PRODUCT_COMPLETENESS,
    SELECT_PRODUCT_COMPLETENESS_BY_DOMAIN,
    UPDATE_PRODUCT,
)
from app.exceptions.errors import NotFoundError, ValidationError
from app.models.product import ProductUpdate
from app.services.product_normalizer import ProductNormalizer
from app.services.url_normalizer import normalize_shop_url

if TYPE_CHECKING:
    from app.db.supabase_client import DatabaseClient

router = APIRouter(prefix="/products", tags=["products"])

_MAX_BULK_ROWS = 50_000
_MAX_BULK_SIZE = 10 * 1024 * 1024  # 10 MB


def _row_to_dict(row: Any) -> dict[str, Any]:
    """Convert an asyncpg Record to a JSON-safe dict."""
    d = dict(row)
    for k, v in d.items():
        if isinstance(v, Decimal):
            d[k] = float(v)
        elif isinstance(v, datetime):
            d[k] = v.isoformat()
        elif isinstance(v, str) and k in ("variants", "tags", "raw_data", "additional_images", "category_path"):
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


@router.get("/cleanup/preview", dependencies=[require_api_key])
@limiter.limit(settings.rate_limit_default)
async def preview_cleanup(
    request: Request,
    db: DatabaseClient | None = Depends(get_db),
) -> dict[str, Any]:
    """Preview how many invalid products would be cleaned up.

    Invalid = price=0 AND no image AND no SKU AND no external_id.
    """
    if db is None:
        return {"invalid_count": 0, "message": "Database unavailable"}

    ingestor = BulkIngestor(db)
    count = await ingestor.count_invalid_products()
    return {"invalid_count": count}


@router.delete("/cleanup", dependencies=[require_api_key])
@limiter.limit(settings.rate_limit_onboard)
async def cleanup_invalid_products(
    request: Request,
    db: DatabaseClient | None = Depends(get_db),
) -> dict[str, Any]:
    """Remove invalid products from the database.

    Deletes products where price=0 AND no image AND no SKU AND no external_id.
    Legitimate free items with images or SKUs are preserved.
    """
    if db is None:
        return {"deleted_count": 0, "message": "Database unavailable"}

    ingestor = BulkIngestor(db)
    deleted = await ingestor.cleanup_invalid_products()
    return {"deleted_count": deleted}


@router.get("/completeness", dependencies=[require_api_key])
@limiter.limit(settings.rate_limit_default)
async def product_completeness(
    request: Request,
    shop_id: str = Query(..., description="Shop/merchant identifier"),
    page: int = Query(1, ge=1),
    per_page: int = Query(100, ge=1, le=500),
    db: DatabaseClient | None = Depends(get_db),
) -> dict[str, Any]:
    """Get completeness scores per product and shop-wide summary.

    Returns per-product missing fields and an aggregate field coverage summary.
    Products are "idealo-ready" when all 8 mandatory fields are present.
    """
    if db is None:
        return {"products": [], "summary": {}, "shop_id": shop_id}

    shop_id = normalize_shop_url(shop_id)
    offset = (page - 1) * per_page

    async with db.pool.acquire() as conn:
        rows = await conn.fetch(SELECT_PRODUCT_COMPLETENESS, shop_id, per_page, offset)
        stats_row = await conn.fetchrow(COUNT_PRODUCTS_MISSING_FIELD, shop_id)

        # Fall back to domain-based match if exact match found nothing
        if not rows or (stats_row and stats_row["total"] == 0):
            domain = _extract_domain(shop_id)
            rows = await conn.fetch(SELECT_PRODUCT_COMPLETENESS_BY_DOMAIN, domain, per_page, offset)
            stats_row = await conn.fetchrow(COUNT_PRODUCTS_MISSING_FIELD_BY_DOMAIN, domain)

    # Per-product completeness
    mandatory_fields = ("gtin", "vendor", "price", "image_url", "title", "product_url", "sku", "condition")
    products = []
    for row in rows:
        d = dict(row)
        missing = []
        for field in mandatory_fields:
            db_field = "vendor" if field == "vendor" else field
            val = d.get(db_field)
            if not val or (isinstance(val, str) and not val.strip()):
                missing.append("brand" if field == "vendor" else field)
            elif field == "price" and val == 0:
                missing.append(field)
        score = 1.0 - (len(missing) / len(mandatory_fields)) if mandatory_fields else 1.0
        products.append({
            "id": d["id"],
            "title": d.get("title", ""),
            "sku": d.get("sku", ""),
            "score": round(score, 2),
            "missing_fields": missing,
            "idealo_ready": len(missing) == 0,
        })

    # Shop-wide summary
    total = stats_row["total"] if stats_row else 0
    summary = {
        "total": total,
        "fields": {},
    }
    if stats_row and total > 0:
        for field_key in ("gtin", "brand", "mpn", "condition", "image", "description", "category"):
            present = stats_row[f"has_{field_key}"]
            summary["fields"][field_key] = {
                "present": present,
                "missing": total - present,
                "coverage_pct": round(present / total * 100, 1),
            }
        idealo_ready = sum(1 for p in products if p["idealo_ready"])
        summary["idealo_ready"] = idealo_ready
        summary["idealo_ready_pct"] = round(idealo_ready / len(products) * 100, 1) if products else 0.0

    return {
        "products": products,
        "summary": summary,
        "shop_id": shop_id,
        "pagination": {"page": page, "per_page": per_page},
    }


@router.post("/bulk-update", dependencies=[require_api_key])
@limiter.limit(settings.rate_limit_onboard)
async def bulk_update_products(
    request: Request,
    shop_id: str = Query(..., description="Shop/merchant identifier"),
    file: UploadFile = File(..., description="CSV file with columns: sku/external_id, gtin, brand, mpn"),
    db: DatabaseClient | None = Depends(get_db),
) -> dict[str, Any]:
    """Bulk update product fields via CSV upload.

    CSV must have a header row. First column must be `sku` or `external_id`.
    Subsequent columns can be: gtin, brand, mpn.
    """
    if db is None:
        raise ValidationError("Database unavailable")

    # Size check
    contents = await file.read()
    if len(contents) > _MAX_BULK_SIZE:
        raise ValidationError(f"File too large (max {_MAX_BULK_SIZE // 1024 // 1024}MB)")

    shop_id = normalize_shop_url(shop_id)
    text = contents.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))

    if not reader.fieldnames:
        raise ValidationError("CSV has no header row")

    # Determine match column
    headers_lower = [h.strip().lower() for h in reader.fieldnames]
    if "sku" in headers_lower:
        match_col = "sku"
    elif "external_id" in headers_lower:
        match_col = "external_id"
    else:
        raise ValidationError("CSV must have 'sku' or 'external_id' column")

    # Parse rows
    updates: list[dict[str, str]] = []
    invalid = 0
    for i, row in enumerate(reader):
        if i >= _MAX_BULK_ROWS:
            break
        # Normalize keys to lowercase
        normalized = {k.strip().lower(): (v or "").strip() for k, v in row.items()}
        match_val = normalized.get(match_col, "").strip()
        if not match_val:
            invalid += 1
            continue

        update: dict[str, str] = {"_match_col": match_col, "_match_val": match_val}
        if "gtin" in normalized and normalized["gtin"]:
            validated = ProductNormalizer._validate_gtin(normalized["gtin"])
            if validated:
                update["gtin"] = validated
            else:
                invalid += 1
                continue
        if "brand" in normalized and normalized["brand"]:
            update["vendor"] = normalized["brand"]
        if "mpn" in normalized and normalized["mpn"]:
            update["mpn"] = normalized["mpn"]

        if len(update) > 2:  # has at least one field besides _match_col and _match_val
            updates.append(update)
        else:
            invalid += 1

    # Apply updates — try exact shop_id first, fall back to domain LIKE match
    matched = 0
    updated = 0
    not_found = 0
    domain = _extract_domain(shop_id)

    async with db.pool.acquire() as conn:
        for upd in updates:
            match_col_name = upd.pop("_match_col")
            match_val = upd.pop("_match_val")

            # Build SET clause
            set_parts = []
            params = [shop_id, match_val]
            param_idx = 3
            for col, val in upd.items():
                set_parts.append(f"{col} = ${param_idx}")
                params.append(val)
                param_idx += 1

            if not set_parts:
                continue

            set_clause = ", ".join(set_parts)
            query = f"""
                UPDATE products
                SET {set_clause}, updated_at = NOW()
                WHERE shop_id = $1 AND {match_col_name} = $2
                RETURNING id;
            """
            rows = await conn.fetch(query, *params)

            # Fall back to domain-based match
            if not rows:
                params[0] = f"%{domain}%"
                query = f"""
                    UPDATE products
                    SET {set_clause}, updated_at = NOW()
                    WHERE shop_id LIKE $1 AND {match_col_name} = $2
                    RETURNING id;
                """
                rows = await conn.fetch(query, *params)

            if rows:
                matched += len(rows)
                updated += len(rows)
            else:
                not_found += 1

    return {
        "matched": matched,
        "updated": updated,
        "not_found": not_found,
        "invalid": invalid,
        "total_rows": len(updates) + invalid,
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


@router.patch("/{product_id}", dependencies=[require_api_key])
@limiter.limit(settings.rate_limit_default)
async def update_product(
    request: Request,
    product_id: int,
    body: ProductUpdate,
    db: DatabaseClient | None = Depends(get_db),
) -> dict[str, Any]:
    """Update individual product fields (GTIN, brand, condition, etc.)."""
    if db is None:
        raise NotFoundError(f"Product {product_id} not found (database unavailable)")

    # Build dynamic SET clause from non-None fields
    update_data = body.model_dump(exclude_none=True)
    if not update_data:
        raise ValidationError("No fields to update")

    # Validate GTIN if provided
    if "gtin" in update_data:
        validated = ProductNormalizer._validate_gtin(update_data["gtin"])
        if not validated:
            raise ValidationError(f"Invalid GTIN format: {update_data['gtin']}")
        update_data["gtin"] = validated

    # Map 'brand' to 'vendor' column
    if "brand" in update_data:
        update_data["vendor"] = update_data.pop("brand")

    # Convert category_path list to JSON
    if "category_path" in update_data:
        update_data["category_path"] = json.dumps(update_data["category_path"])

    # Build parameterized query
    set_parts = []
    params: list[Any] = [product_id]
    param_idx = 2
    for col, val in update_data.items():
        set_parts.append(f"{col} = ${param_idx}")
        params.append(val)
        param_idx += 1

    set_clause = ", ".join(set_parts)
    query = UPDATE_PRODUCT.format(set_clause=set_clause)

    async with db.pool.acquire() as conn:
        row = await conn.fetchrow(query, *params)

    if row is None:
        raise NotFoundError(f"Product {product_id} not found")

    return _row_to_dict(row)
