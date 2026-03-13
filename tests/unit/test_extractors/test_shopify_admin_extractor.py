"""Unit tests for ShopifyAdminExtractor."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from app.extractors.shopify_admin_extractor import (
    ShopifyAdminExtractor,
    _API_VERSION,
    _RATE_LIMIT_FILL_RATIO,
)


@pytest.fixture
def extractor() -> ShopifyAdminExtractor:
    return ShopifyAdminExtractor(
        access_token="shpat_test_token_123",
        shop_domain="example.myshopify.com",
    )


SAMPLE_PRODUCT = {
    "id": 1234567890,
    "title": "Test Sneaker",
    "body_html": "<p>A great sneaker</p>",
    "vendor": "TestBrand",
    "product_type": "Shoes",
    "handle": "test-sneaker",
    "status": "active",
    "variants": [
        {
            "id": 11111,
            "title": "Size 10 / Red",
            "price": "89.99",
            "compare_at_price": "109.99",
            "sku": "SNKR-RED-10",
            "barcode": "0012345678905",
            "inventory_quantity": 15,
            "weight": 0.8,
            "weight_unit": "kg",
        },
    ],
    "images": [
        {"id": 1, "src": "https://cdn.shopify.com/img1.jpg", "position": 1},
        {"id": 2, "src": "https://cdn.shopify.com/img2.jpg", "position": 2},
    ],
}

BASE_URL = f"https://example.myshopify.com/admin/api/{_API_VERSION}"
PRODUCTS_URL = f"{BASE_URL}/products.json?limit=250&status=active"


def _products_response(products: list[dict]) -> dict:
    """Build a Shopify products response envelope."""
    return {"products": products}


# ── Constructor ──────────────────────────────────────────────────────


def test_requires_access_token():
    with pytest.raises(ValueError, match="access_token"):
        ShopifyAdminExtractor(access_token="", shop_domain="example.myshopify.com")


def test_requires_shop_domain():
    with pytest.raises(ValueError, match="shop_domain"):
        ShopifyAdminExtractor(access_token="tok", shop_domain="")


def test_strips_trailing_slash():
    ext = ShopifyAdminExtractor(access_token="tok", shop_domain="example.myshopify.com/")
    assert ext._shop_domain == "example.myshopify.com"


def test_base_url_adds_https():
    ext = ShopifyAdminExtractor(access_token="tok", shop_domain="example.myshopify.com")
    assert ext._base_url() == f"https://example.myshopify.com/admin/api/{_API_VERSION}"


def test_base_url_preserves_existing_scheme():
    ext = ShopifyAdminExtractor(access_token="tok", shop_domain="https://example.myshopify.com")
    assert ext._base_url() == f"https://example.myshopify.com/admin/api/{_API_VERSION}"


def test_headers_include_access_token():
    ext = ShopifyAdminExtractor(access_token="my-token", shop_domain="example.myshopify.com")
    headers = ext._headers()
    assert headers["X-Shopify-Access-Token"] == "my-token"
    assert headers["Accept"] == "application/json"


# ── Single page extraction ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_single_page_extraction(extractor: ShopifyAdminExtractor):
    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            return_value=Response(
                200,
                json=_products_response([SAMPLE_PRODUCT]),
                headers={"X-Shopify-Shop-Api-Call-Limit": "2/40"},
            )
        )

        result = await extractor.extract("https://example.myshopify.com")

    assert len(result.products) == 1
    assert result.products[0]["title"] == "Test Sneaker"
    assert result.products[0]["id"] == 1234567890
    assert result.complete is True
    assert result.error is None
    assert result.pages_completed == 1


# ── Multi-page cursor pagination ────────────────────────────────────


@pytest.mark.asyncio
async def test_multi_page_cursor_pagination(extractor: ShopifyAdminExtractor):
    page1_products = [{"id": i, "title": f"Product {i}"} for i in range(1, 4)]
    page2_products = [{"id": i, "title": f"Product {i}"} for i in range(4, 6)]

    next_page_url = (
        f"{BASE_URL}/products.json?page_info=eyJsYXN0X2lkIjozfQ&limit=250"
    )

    with respx.mock:
        # Page 1: returns Link header pointing to page 2
        respx.get(PRODUCTS_URL).mock(
            return_value=Response(
                200,
                json=_products_response(page1_products),
                headers={
                    "Link": f'<{next_page_url}>; rel="next"',
                    "X-Shopify-Shop-Api-Call-Limit": "5/40",
                },
            )
        )
        # Page 2: no Link header (last page)
        respx.get(next_page_url).mock(
            return_value=Response(
                200,
                json=_products_response(page2_products),
                headers={"X-Shopify-Shop-Api-Call-Limit": "7/40"},
            )
        )

        result = await extractor.extract("https://example.myshopify.com")

    assert len(result.products) == 5
    assert result.complete is True
    assert result.pages_completed == 2


# ── Empty store ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_store(extractor: ShopifyAdminExtractor):
    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            return_value=Response(200, json=_products_response([]))
        )

        result = await extractor.extract("https://example.myshopify.com")

    assert result.products == []
    assert result.complete is True
    assert result.pages_completed == 0


# ── Auth error handling ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_401_returns_oauth_invalid(extractor: ShopifyAdminExtractor):
    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            return_value=Response(401, json={"errors": "Not authorized"})
        )

        result = await extractor.extract("https://example.myshopify.com")

    assert result.products == []
    assert result.complete is False
    assert result.error == "OAuth token invalid"


@pytest.mark.asyncio
async def test_403_returns_scope_error(extractor: ShopifyAdminExtractor):
    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            return_value=Response(403, json={"errors": "Forbidden"})
        )

        result = await extractor.extract("https://example.myshopify.com")

    assert result.products == []
    assert result.complete is False
    assert result.error == "OAuth token lacks read_products scope"


# ── Rate limit handling ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_429_retries_once_then_succeeds(extractor: ShopifyAdminExtractor):
    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            side_effect=[
                Response(
                    429,
                    headers={
                        "Retry-After": "0.01",
                        "X-Shopify-Shop-Api-Call-Limit": "40/40",
                    },
                ),
                Response(
                    200,
                    json=_products_response([SAMPLE_PRODUCT]),
                    headers={"X-Shopify-Shop-Api-Call-Limit": "2/40"},
                ),
            ]
        )

        result = await extractor.extract("https://example.myshopify.com")

    assert len(result.products) == 1
    assert result.complete is True


@pytest.mark.asyncio
async def test_429_twice_stops_extraction(extractor: ShopifyAdminExtractor):
    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            side_effect=[
                Response(429, headers={"Retry-After": "0.01", "X-Shopify-Shop-Api-Call-Limit": "40/40"}),
                Response(429, headers={"Retry-After": "0.01", "X-Shopify-Shop-Api-Call-Limit": "40/40"}),
            ]
        )

        result = await extractor.extract("https://example.myshopify.com")

    assert result.products == []
    assert result.complete is False
    assert "Rate limited" in result.error


@pytest.mark.asyncio
async def test_leaky_bucket_throttle_below_threshold(extractor: ShopifyAdminExtractor):
    """When call limit usage is below threshold, no sleeping occurs."""
    usage = int(40 * _RATE_LIMIT_FILL_RATIO) - 1  # Below threshold
    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            return_value=Response(
                200,
                json=_products_response([SAMPLE_PRODUCT]),
                headers={"X-Shopify-Shop-Api-Call-Limit": f"{usage}/40"},
            )
        )

        result = await extractor.extract("https://example.myshopify.com")

    assert len(result.products) == 1
    assert result.complete is True


# ── HTTP error handling ──────────────────────────────────────────────


@pytest.mark.asyncio
async def test_500_stops_extraction(extractor: ShopifyAdminExtractor):
    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            return_value=Response(500, text="Internal Server Error")
        )

        result = await extractor.extract("https://example.myshopify.com")

    assert result.products == []
    assert result.complete is False
    assert "HTTP 500" in result.error


@pytest.mark.asyncio
async def test_timeout_stops_extraction(extractor: ShopifyAdminExtractor):
    import httpx as _httpx

    with respx.mock:
        respx.get(PRODUCTS_URL).mock(side_effect=_httpx.ReadTimeout("timed out"))

        result = await extractor.extract("https://example.myshopify.com")

    assert result.products == []
    assert result.complete is False
    assert "Timeout" in result.error


@pytest.mark.asyncio
async def test_request_error_stops_extraction(extractor: ShopifyAdminExtractor):
    import httpx as _httpx

    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            side_effect=_httpx.ConnectError("connection refused")
        )

        result = await extractor.extract("https://example.myshopify.com")

    assert result.products == []
    assert result.complete is False
    assert "Request error" in result.error


# ── Link header parsing ──────────────────────────────────────────────


class TestParseLinkHeader:
    """Tests for _parse_next_link static method."""

    def test_empty_header_returns_none(self):
        assert ShopifyAdminExtractor._parse_next_link("") is None

    def test_next_link_extracted(self):
        header = '<https://shop.myshopify.com/admin/api/2024-10/products.json?page_info=abc&limit=250>; rel="next"'
        result = ShopifyAdminExtractor._parse_next_link(header)
        assert result == "https://shop.myshopify.com/admin/api/2024-10/products.json?page_info=abc&limit=250"

    def test_previous_and_next_link(self):
        header = (
            '<https://shop.myshopify.com/admin/api/2024-10/products.json?page_info=prev123&limit=250>; rel="previous", '
            '<https://shop.myshopify.com/admin/api/2024-10/products.json?page_info=next456&limit=250>; rel="next"'
        )
        result = ShopifyAdminExtractor._parse_next_link(header)
        assert "page_info=next456" in result

    def test_only_previous_link_returns_none(self):
        header = '<https://shop.myshopify.com/admin/api/2024-10/products.json?page_info=prev123&limit=250>; rel="previous"'
        result = ShopifyAdminExtractor._parse_next_link(header)
        assert result is None

    def test_malformed_link_no_angle_brackets(self):
        header = 'https://example.com/products.json; rel="next"'
        result = ShopifyAdminExtractor._parse_next_link(header)
        assert result is None


# ── Rate limit header parsing ────────────────────────────────────────


class TestHandleRateLimit:
    """Tests for _handle_rate_limit static method."""

    @pytest.mark.asyncio
    async def test_no_header_does_nothing(self):
        resp = Response(200, headers={})
        # Should not raise
        await ShopifyAdminExtractor._handle_rate_limit(resp)

    @pytest.mark.asyncio
    async def test_malformed_header_does_nothing(self):
        resp = Response(200, headers={"X-Shopify-Shop-Api-Call-Limit": "invalid"})
        await ShopifyAdminExtractor._handle_rate_limit(resp)

    @pytest.mark.asyncio
    async def test_low_usage_does_not_sleep(self):
        resp = Response(200, headers={"X-Shopify-Shop-Api-Call-Limit": "5/40"})
        # Should complete nearly instantly (no sleep)
        await ShopifyAdminExtractor._handle_rate_limit(resp)

    @pytest.mark.asyncio
    async def test_high_usage_triggers_sleep(self):
        """When usage >= threshold, _handle_rate_limit should sleep."""
        from unittest.mock import AsyncMock, patch

        resp = Response(
            200,
            headers={"X-Shopify-Shop-Api-Call-Limit": f"{int(40 * _RATE_LIMIT_FILL_RATIO)}/40"},
        )

        with patch("app.extractors.shopify_admin_extractor.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await ShopifyAdminExtractor._handle_rate_limit(resp)
            mock_sleep.assert_called_once()
            # At threshold/40 ratio < 0.95, sleep should be 1.0
            assert mock_sleep.call_args[0][0] == 1.0

    @pytest.mark.asyncio
    async def test_near_max_usage_sleeps_longer(self):
        """When usage >= 95% of max, sleep time should be 2.0."""
        from unittest.mock import AsyncMock, patch

        resp = Response(
            200,
            headers={"X-Shopify-Shop-Api-Call-Limit": "39/40"},
        )

        with patch("app.extractors.shopify_admin_extractor.asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            await ShopifyAdminExtractor._handle_rate_limit(resp)
            mock_sleep.assert_called_once()
            assert mock_sleep.call_args[0][0] == 2.0


# ── Partial extraction (error mid-pagination) ───────────────────────


@pytest.mark.asyncio
async def test_error_on_page_2_returns_partial_results(extractor: ShopifyAdminExtractor):
    page1_products = [{"id": 1, "title": "Product 1"}]
    next_page_url = f"{BASE_URL}/products.json?page_info=abc&limit=250"

    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            return_value=Response(
                200,
                json=_products_response(page1_products),
                headers={
                    "Link": f'<{next_page_url}>; rel="next"',
                    "X-Shopify-Shop-Api-Call-Limit": "2/40",
                },
            )
        )
        respx.get(next_page_url).mock(
            return_value=Response(500, text="Internal Server Error")
        )

        result = await extractor.extract("https://example.myshopify.com")

    # Should keep products from page 1 but mark as incomplete
    assert len(result.products) == 1
    assert result.complete is False
    assert "HTTP 500 on page 2" in result.error
