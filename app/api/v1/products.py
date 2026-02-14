"""Product query API routes."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query

from app.api.deps import require_api_key
from app.exceptions.errors import NotFoundError

router = APIRouter(prefix="/products", tags=["products"])


@router.get("", dependencies=[require_api_key])
async def list_products(
    shop_id: str = Query(..., description="Shop/merchant identifier"),
    page: int = Query(1, ge=1, description="Page number (1-indexed)"),
    per_page: int = Query(50, ge=1, le=100, description="Items per page"),
) -> dict[str, Any]:
    """List products for a shop with pagination.

    Args:
        shop_id: Shop/merchant identifier
        page: Page number (1-indexed)
        per_page: Number of items per page (max 100)

    Returns:
        Paginated product list with metadata

    Note:
        This is a placeholder implementation. Will be wired to the database
        in the pipeline orchestrator ticket.
    """
    # Placeholder response with pagination metadata
    return {
        "data": [],
        "pagination": {
            "page": page,
            "per_page": per_page,
            "total": 0,
            "total_pages": 0,
        },
        "shop_id": shop_id,
    }


@router.get("/{product_id}", dependencies=[require_api_key])
async def get_product(
    product_id: int,
) -> dict[str, Any]:
    """Get single product by ID.

    Args:
        product_id: Unique product identifier

    Returns:
        Product details

    Raises:
        NotFoundError: Product not found (always raised in placeholder)

    Note:
        This is a placeholder implementation. Will be wired to the database
        in the pipeline orchestrator ticket.
    """
    # Placeholder - always returns 404
    raise NotFoundError(f"Product {product_id} not found")
