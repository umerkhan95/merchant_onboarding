"""Unit tests for BigCommerceAdminExtractor."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from app.db.oauth_store import OAuthConnection
from app.extractors.bigcommerce_admin_extractor import BigCommerceAdminExtractor


def _make_connection(
    access_token: str = "test-token",
    store_hash: str = "abc123",
    **kwargs,
) -> OAuthConnection:
    return OAuthConnection(
        id=1,
        platform="bigcommerce",
        shop_domain="store-abc123.mybigcommerce.com",
        access_token=access_token,
        store_hash=store_hash,
        **kwargs,
    )


@pytest.fixture
def connection() -> OAuthConnection:
    return _make_connection()


@pytest.fixture
def extractor(connection: OAuthConnection) -> BigCommerceAdminExtractor:
    return BigCommerceAdminExtractor(connection)


def _product_response(products: list[dict], page: int = 1, total_pages: int = 1) -> dict:
    """Build a BigCommerce catalog response envelope."""
    return {
        "data": products,
        "meta": {"pagination": {"page": page, "total_pages": total_pages, "total": len(products)}},
    }


SAMPLE_PRODUCT = {
    "id": 77,
    "name": "Test Widget",
    "description": "<p>A nice widget</p>",
    "price": 29.99,
    "retail_price": 39.99,
    "sku": "WIDGET-001",
    "upc": "0012345678905",
    "mpn": "MPN-001",
    "weight": 1.5,
    "type": "physical",
    "availability": "available",
    "inventory_level": 10,
    "brand_id": 5,
    "condition": "New",
    "custom_url": {"url": "/test-widget/"},
    "images": [
        {"id": 1, "url_zoom": "https://cdn.bc.com/img1_zoom.jpg", "sort_order": 0},
        {"id": 2, "url_zoom": "https://cdn.bc.com/img2_zoom.jpg", "sort_order": 1},
    ],
    "variants": [
        {
            "id": 101,
            "sku": "WIDGET-001-RED",
            "upc": "0012345678912",
            "price": 29.99,
            "inventory_level": 5,
            "option_values": [{"label": "Red"}],
        },
    ],
}


# ── Constructor ──────────────────────────────────────────────────────


def test_requires_access_token():
    conn = OAuthConnection(id=1, platform="bigcommerce", shop_domain="x.com", store_hash="abc")
    with pytest.raises(ValueError, match="access_token"):
        BigCommerceAdminExtractor(conn)


def test_requires_store_hash():
    conn = OAuthConnection(id=1, platform="bigcommerce", shop_domain="x.com", access_token="tok")
    with pytest.raises(ValueError, match="store_hash"):
        BigCommerceAdminExtractor(conn)


# ── Single page extraction ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_page_extraction(extractor: BigCommerceAdminExtractor):
    shop_url = "https://store-abc123.mybigcommerce.com"
    base = "https://api.bigcommerce.com/stores/abc123/v3"

    with respx.mock:
        respx.get(f"{base}/catalog/brands").mock(
            return_value=Response(200, json=_product_response([{"id": 5, "name": "WidgetCo"}]))
        )
        respx.get(f"{base}/catalog/products").mock(
            return_value=Response(200, json=_product_response([SAMPLE_PRODUCT]))
        )

        result = await extractor.extract(shop_url)

    assert len(result.products) == 1
    p = result.products[0]
    assert p["title"] == "Test Widget"
    assert p["price"] == "29.99"
    assert p["sku"] == "WIDGET-001"
    assert p["barcode"] == "0012345678905"
    assert p["gtin"] == "0012345678905"
    assert p["mpn"] == "MPN-001"
    assert p["vendor"] == "WidgetCo"
    assert p["image_url"] == "https://cdn.bc.com/img1_zoom.jpg"
    assert p["additional_images"] == ["https://cdn.bc.com/img2_zoom.jpg"]
    assert p["compare_at_price"] == "39.99"
    assert p["product_url"] == "https://store-abc123.mybigcommerce.com/test-widget/"
    assert p["_source"] == "bigcommerce_admin_api"
    assert result.complete is True
    assert result.error is None


# ── Pagination ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_page_pagination(extractor: BigCommerceAdminExtractor):
    shop_url = "https://store-abc123.mybigcommerce.com"
    base = "https://api.bigcommerce.com/stores/abc123/v3"

    page1_products = [{"id": i, "name": f"P{i}", "price": 10, "custom_url": {"url": f"/p{i}/"}} for i in range(1, 4)]
    page2_products = [{"id": i, "name": f"P{i}", "price": 10, "custom_url": {"url": f"/p{i}/"}} for i in range(4, 6)]

    with respx.mock:
        respx.get(f"{base}/catalog/brands").mock(
            return_value=Response(200, json=_product_response([]))
        )
        # First call: page 1 of 2
        respx.get(f"{base}/catalog/products").mock(
            side_effect=[
                Response(200, json=_product_response(page1_products, page=1, total_pages=2)),
                Response(200, json=_product_response(page2_products, page=2, total_pages=2)),
            ]
        )

        result = await extractor.extract(shop_url)

    assert len(result.products) == 5
    assert result.complete is True


# ── Error handling ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_401_returns_oauth_invalid(extractor: BigCommerceAdminExtractor):
    base = "https://api.bigcommerce.com/stores/abc123/v3"

    with respx.mock:
        respx.get(f"{base}/catalog/brands").mock(return_value=Response(200, json=_product_response([])))
        respx.get(f"{base}/catalog/products").mock(return_value=Response(401, json={"status": 401}))

        result = await extractor.extract("https://store.example.com")

    assert result.products == []
    assert result.complete is False
    assert result.error == "OAuth token invalid"


@pytest.mark.asyncio
async def test_500_stops_extraction(extractor: BigCommerceAdminExtractor):
    base = "https://api.bigcommerce.com/stores/abc123/v3"

    with respx.mock:
        respx.get(f"{base}/catalog/brands").mock(return_value=Response(200, json=_product_response([])))
        respx.get(f"{base}/catalog/products").mock(return_value=Response(500, text="Internal Server Error"))

        result = await extractor.extract("https://store.example.com")

    assert result.products == []
    assert result.complete is False
    assert "HTTP 500" in result.error


# ── Brand resolution ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_brand_resolution_failure_continues(extractor: BigCommerceAdminExtractor):
    """Brand fetch failure shouldn't block product extraction."""
    base = "https://api.bigcommerce.com/stores/abc123/v3"

    product = {**SAMPLE_PRODUCT, "brand_id": 99}

    with respx.mock:
        respx.get(f"{base}/catalog/brands").mock(return_value=Response(500, text="Error"))
        respx.get(f"{base}/catalog/products").mock(
            return_value=Response(200, json=_product_response([product]))
        )

        result = await extractor.extract("https://store.example.com")

    assert len(result.products) == 1
    assert result.products[0]["vendor"] == ""  # Brand not resolved, but extraction continues


# ── Variant fallback ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_upc_fallback_to_variant(extractor: BigCommerceAdminExtractor):
    """When product has no UPC, should fall back to first variant's UPC."""
    base = "https://api.bigcommerce.com/stores/abc123/v3"

    product = {
        "id": 1,
        "name": "No UPC Product",
        "price": 19.99,
        "upc": "",
        "custom_url": {"url": "/no-upc/"},
        "variants": [{"id": 10, "upc": "9876543210987", "sku": "V-SKU"}],
    }

    with respx.mock:
        respx.get(f"{base}/catalog/brands").mock(return_value=Response(200, json=_product_response([])))
        respx.get(f"{base}/catalog/products").mock(
            return_value=Response(200, json=_product_response([product]))
        )

        result = await extractor.extract("https://store.example.com")

    assert result.products[0]["barcode"] == "9876543210987"
    assert result.products[0]["gtin"] == "9876543210987"


# ── Empty store ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_store(extractor: BigCommerceAdminExtractor):
    base = "https://api.bigcommerce.com/stores/abc123/v3"

    with respx.mock:
        respx.get(f"{base}/catalog/brands").mock(return_value=Response(200, json=_product_response([])))
        respx.get(f"{base}/catalog/products").mock(
            return_value=Response(200, json=_product_response([]))
        )

        result = await extractor.extract("https://store.example.com")

    assert result.products == []
    assert result.complete is True
    assert result.pages_completed == 0
