"""Unit tests for WooCommerceAPIExtractor."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from httpx import Response

from app.extractors.browser_config import HTTPX_USER_AGENT
from app.extractors.woocommerce_api import WooCommerceAPIExtractor


@pytest.fixture
def woocommerce_products_fixture() -> list[dict]:
    """Load woocommerce products test fixture."""
    fixture_path = Path(__file__).parent.parent.parent / "fixtures" / "woocommerce_products.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def extractor() -> WooCommerceAPIExtractor:
    """Create a WooCommerceAPIExtractor instance."""
    return WooCommerceAPIExtractor(timeout=30, max_pages=100)


@pytest.mark.asyncio
async def test_single_page_extraction(extractor: WooCommerceAPIExtractor, woocommerce_products_fixture: list[dict]):
    """Test extraction with less than 100 products (single page)."""
    shop_url = "https://shop.example.com"

    with respx.mock:
        # Mock single page response with 2 products
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=1").mock(
            return_value=Response(200, json=woocommerce_products_fixture)
        )

        result = await extractor.extract(shop_url)

        assert len(result.products) == 2
        assert result.products[0]["id"] == 101
        assert result.products[0]["name"] == "Earl Grey Tea"
        assert result.products[1]["id"] == 102
        assert result.products[1]["name"] == "Green Tea Jasmine"


@pytest.mark.asyncio
async def test_multi_page_pagination(extractor: WooCommerceAPIExtractor):
    """Test pagination when first page returns exactly 100 products."""
    shop_url = "https://shop.example.com"

    # Create 100 products for first page
    page1_products = [{"id": i, "name": f"Product {i}"} for i in range(1, 101)]
    page2_products = [{"id": i, "name": f"Product {i}"} for i in range(101, 151)]

    with respx.mock:
        # Mock first page with 100 products
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=1").mock(
            return_value=Response(200, json=page1_products)
        )

        # Mock second page with 50 products
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=2").mock(
            return_value=Response(200, json=page2_products)
        )

        result = await extractor.extract(shop_url)

        assert len(result.products) == 150
        assert result.products[0]["id"] == 1
        assert result.products[99]["id"] == 100
        assert result.products[100]["id"] == 101
        assert result.products[-1]["id"] == 150


@pytest.mark.asyncio
async def test_empty_response(extractor: WooCommerceAPIExtractor):
    """Test extraction when shop has 0 products."""
    shop_url = "https://shop.example.com"

    with respx.mock:
        # Mock empty products response
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=1").mock(
            return_value=Response(200, json=[])
        )

        result = await extractor.extract(shop_url)

        assert len(result.products) == 0


@pytest.mark.asyncio
async def test_store_api_not_available_404(extractor: WooCommerceAPIExtractor):
    """Test that HTTP 404 (Store API not exposed) returns empty list."""
    shop_url = "https://shop.example.com"

    with respx.mock:
        # Mock 404 response - Store API not available
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=1").mock(return_value=Response(404))

        result = await extractor.extract(shop_url)

        assert len(result.products) == 0
        assert result.complete is False
        assert result.error is not None


@pytest.mark.asyncio
async def test_http_429_retries_once(extractor: WooCommerceAPIExtractor, woocommerce_products_fixture: list[dict]):
    """Test that HTTP 429 (rate limit) retries once."""
    shop_url = "https://shop.example.com"

    with respx.mock:
        # Create a route that we can mock multiple responses for
        route = respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=1")

        # First call: rate limited, second call: success
        route.mock(
            side_effect=[Response(429, headers={"Retry-After": "1"}), Response(200, json=woocommerce_products_fixture)]
        )

        result = await extractor.extract(shop_url)

        # Should retry and succeed
        assert len(result.products) == 2
        assert result.products[0]["name"] == "Earl Grey Tea"


@pytest.mark.asyncio
async def test_http_429_twice_stops_extraction(extractor: WooCommerceAPIExtractor):
    """Test that getting rate limited twice stops extraction."""
    shop_url = "https://shop.example.com"

    with respx.mock:
        # Mock 429 twice
        route = respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=1")
        route.mock(side_effect=[Response(429, headers={"Retry-After": "1"}), Response(429)])

        result = await extractor.extract(shop_url)

        assert len(result.products) == 0
        assert result.complete is False


@pytest.mark.asyncio
async def test_http_500_returns_empty_list(extractor: WooCommerceAPIExtractor):
    """Test that HTTP 500 server error returns empty list."""
    shop_url = "https://shop.example.com"

    with respx.mock:
        # Mock 500 response
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=1").mock(return_value=Response(500))

        result = await extractor.extract(shop_url)

        assert len(result.products) == 0
        assert result.complete is False


@pytest.mark.asyncio
async def test_invalid_json_returns_empty_list(extractor: WooCommerceAPIExtractor):
    """Test that invalid JSON response returns empty list."""
    shop_url = "https://shop.example.com"

    with respx.mock:
        # Mock response with invalid JSON
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=1").mock(
            return_value=Response(200, content=b"<html>Not JSON</html>", headers={"Content-Type": "text/html"})
        )

        result = await extractor.extract(shop_url)

        assert len(result.products) == 0
        assert result.complete is False


@pytest.mark.asyncio
async def test_returns_raw_dicts_not_models(
    extractor: WooCommerceAPIExtractor, woocommerce_products_fixture: list[dict]
):
    """Test that extractor returns raw dicts, not Product models."""
    shop_url = "https://shop.example.com"

    with respx.mock:
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=1").mock(
            return_value=Response(200, json=woocommerce_products_fixture)
        )

        result = await extractor.extract(shop_url)

        # Verify returns raw dicts
        assert isinstance(result.products, list)
        assert len(result.products) == 2

        # First product should be a dict with expected raw WooCommerce Store API fields
        product = result.products[0]
        assert isinstance(product, dict)
        assert product["id"] == 101
        assert product["name"] == "Earl Grey Tea"
        assert product["slug"] == "earl-grey-tea"
        assert product["permalink"] == "https://shop.example.com/product/earl-grey-tea/"
        assert product["description"] == "<p>Classic bergamot-flavored black tea</p>"
        assert "prices" in product
        assert "images" in product
        assert "categories" in product
        assert "tags" in product
        assert "attributes" in product


@pytest.mark.asyncio
async def test_timeout_returns_empty_list(extractor: WooCommerceAPIExtractor):
    """Test that timeout errors return empty list."""
    shop_url = "https://shop.example.com"

    with respx.mock:
        # Mock timeout exception
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=1").mock(
            side_effect=httpx.TimeoutException("Timeout")
        )

        result = await extractor.extract(shop_url)

        assert len(result.products) == 0
        assert result.complete is False


@pytest.mark.asyncio
async def test_request_error_returns_empty_list(extractor: WooCommerceAPIExtractor):
    """Test that request errors return empty list."""
    shop_url = "https://shop.example.com"

    with respx.mock:
        # Mock request error
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=1").mock(
            side_effect=httpx.RequestError("Connection failed")
        )

        result = await extractor.extract(shop_url)

        assert len(result.products) == 0
        assert result.complete is False


@pytest.mark.asyncio
async def test_pagination_stops_at_max_pages(extractor: WooCommerceAPIExtractor):
    """Test that pagination respects max_pages limit."""
    # Create extractor with low max_pages for testing
    limited_extractor = WooCommerceAPIExtractor(timeout=30, max_pages=2)
    shop_url = "https://shop.example.com"

    # Create 100 products per page
    page_products = [{"id": i, "name": f"Product {i}"} for i in range(100)]

    with respx.mock:
        # Mock pages that always return 100 products
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=1").mock(
            return_value=Response(200, json=page_products)
        )
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=2").mock(
            return_value=Response(200, json=page_products)
        )
        # Page 3 should not be called
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=3").mock(
            return_value=Response(200, json=page_products)
        )

        result = await limited_extractor.extract(shop_url)

        # Should only get products from 2 pages
        assert len(result.products) == 200


@pytest.mark.asyncio
async def test_partial_extraction_on_error(extractor: WooCommerceAPIExtractor):
    """Test that partial results are returned when error occurs on later pages."""
    shop_url = "https://shop.example.com"

    # Create 100 products for first page to trigger pagination
    large_products = [{"id": i, "name": f"Product {i}"} for i in range(100)]

    with respx.mock:
        # First page succeeds
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=1").mock(
            return_value=Response(200, json=large_products)
        )

        # Second page fails
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=2").mock(return_value=Response(500))

        result = await extractor.extract(shop_url)

        # Should return products from first page only
        assert len(result.products) == 100


@pytest.mark.asyncio
async def test_trailing_slash_handling(extractor: WooCommerceAPIExtractor, woocommerce_products_fixture: list[dict]):
    """Test that shop URLs with trailing slashes are handled correctly."""
    shop_url_with_slash = "https://shop.example.com/"

    with respx.mock:
        # Should strip trailing slash and make correct request
        respx.get("https://shop.example.com/wp-json/wc/store/v1/products?per_page=100&page=1").mock(
            return_value=Response(200, json=woocommerce_products_fixture)
        )

        result = await extractor.extract(shop_url_with_slash)

        assert len(result.products) == 2


@pytest.mark.asyncio
async def test_uses_shared_browser_config_headers(extractor: WooCommerceAPIExtractor, woocommerce_products_fixture: list[dict]):
    """Verify WooCommerce extractor uses centralized User-Agent from browser_config."""
    shop_url = "https://shop.example.com"

    with respx.mock:
        route = respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=1").mock(
            return_value=Response(200, json=woocommerce_products_fixture)
        )

        await extractor.extract(shop_url)

        # Verify the request used a User-Agent from the shared pool (not hardcoded Chrome/122)
        request = route.calls[0].request
        user_agent = request.headers.get("user-agent", "")
        assert HTTPX_USER_AGENT in user_agent, f"Expected shared UA, got: {user_agent}"
        assert "Chrome/122" not in user_agent, "Should not use hardcoded Chrome/122"
        assert request.headers.get("accept-language") == "en-US,en;q=0.9"


@pytest.mark.asyncio
async def test_unexpected_response_format(extractor: WooCommerceAPIExtractor):
    """Test that non-list response format returns empty list."""
    shop_url = "https://shop.example.com"

    with respx.mock:
        # Mock response with unexpected format (dict instead of list)
        respx.get(f"{shop_url}/wp-json/wc/store/v1/products?per_page=100&page=1").mock(
            return_value=Response(200, json={"error": "Something went wrong"})
        )

        result = await extractor.extract(shop_url)

        assert len(result.products) == 0
        assert result.complete is False
