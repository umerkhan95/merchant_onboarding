"""Unit tests for ShopifyAPIExtractor."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from httpx import Response

from app.extractors.shopify_api import ShopifyAPIExtractor


@pytest.fixture
def shopify_products_fixture() -> dict:
    """Load shopify products test fixture."""
    fixture_path = Path(__file__).parent.parent.parent / "fixtures" / "shopify_products.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def extractor() -> ShopifyAPIExtractor:
    """Create a ShopifyAPIExtractor instance."""
    return ShopifyAPIExtractor(timeout=30, max_pages=100)


@pytest.mark.asyncio
async def test_single_page_extraction(extractor: ShopifyAPIExtractor, shopify_products_fixture: dict):
    """Test extraction with less than 250 products (single page)."""
    shop_url = "https://example.myshopify.com"

    with respx.mock:
        # Mock single page response with 3 products
        respx.get(f"{shop_url}/products.json?limit=250&page=1").mock(
            return_value=Response(200, json=shopify_products_fixture)
        )

        products = await extractor.extract(shop_url)

        assert len(products) == 3
        assert products[0]["id"] == 1001
        assert products[0]["title"] == "Tree Runner"
        assert products[1]["id"] == 1002
        assert products[2]["id"] == 1003


@pytest.mark.asyncio
async def test_multi_page_pagination(extractor: ShopifyAPIExtractor):
    """Test pagination when first page returns exactly 250 products."""
    shop_url = "https://example.myshopify.com"

    # Create 250 products for first page
    page1_products = [{"id": i, "title": f"Product {i}"} for i in range(1, 251)]
    page2_products = [{"id": i, "title": f"Product {i}"} for i in range(251, 301)]

    with respx.mock:
        # Mock first page with 250 products
        respx.get(f"{shop_url}/products.json?limit=250&page=1").mock(
            return_value=Response(200, json={"products": page1_products})
        )

        # Mock second page with 50 products
        respx.get(f"{shop_url}/products.json?limit=250&page=2").mock(
            return_value=Response(200, json={"products": page2_products})
        )

        products = await extractor.extract(shop_url)

        assert len(products) == 300
        assert products[0]["id"] == 1
        assert products[249]["id"] == 250
        assert products[250]["id"] == 251
        assert products[-1]["id"] == 300


@pytest.mark.asyncio
async def test_empty_response(extractor: ShopifyAPIExtractor):
    """Test extraction when shop has 0 products."""
    shop_url = "https://example.myshopify.com"

    with respx.mock:
        # Mock empty products response
        respx.get(f"{shop_url}/products.json?limit=250&page=1").mock(
            return_value=Response(200, json={"products": []})
        )

        products = await extractor.extract(shop_url)

        assert len(products) == 0


@pytest.mark.asyncio
async def test_http_404_returns_empty_list(extractor: ShopifyAPIExtractor):
    """Test that HTTP 404 returns empty list."""
    shop_url = "https://nonexistent.myshopify.com"

    with respx.mock:
        # Mock 404 response
        respx.get(f"{shop_url}/products.json?limit=250&page=1").mock(return_value=Response(404))

        products = await extractor.extract(shop_url)

        assert len(products) == 0


@pytest.mark.asyncio
async def test_http_429_retries_once(extractor: ShopifyAPIExtractor, shopify_products_fixture: dict):
    """Test that HTTP 429 (rate limit) retries once."""
    shop_url = "https://example.myshopify.com"

    with respx.mock:
        # Create a route that we can mock multiple responses for
        route = respx.get(f"{shop_url}/products.json?limit=250&page=1")

        # First call: rate limited
        route.mock(
            side_effect=[Response(429, headers={"Retry-After": "1"}), Response(200, json=shopify_products_fixture)]
        )

        products = await extractor.extract(shop_url)

        # Should retry and succeed
        assert len(products) == 3
        assert products[0]["title"] == "Tree Runner"


@pytest.mark.asyncio
async def test_http_429_twice_stops_extraction(extractor: ShopifyAPIExtractor):
    """Test that getting rate limited twice stops extraction."""
    shop_url = "https://example.myshopify.com"

    with respx.mock:
        # Mock 429 twice
        route = respx.get(f"{shop_url}/products.json?limit=250&page=1")
        route.mock(side_effect=[Response(429, headers={"Retry-After": "1"}), Response(429)])

        products = await extractor.extract(shop_url)

        assert len(products) == 0


@pytest.mark.asyncio
async def test_http_500_returns_empty_list(extractor: ShopifyAPIExtractor):
    """Test that HTTP 500 server error returns empty list."""
    shop_url = "https://example.myshopify.com"

    with respx.mock:
        # Mock 500 response
        respx.get(f"{shop_url}/products.json?limit=250&page=1").mock(return_value=Response(500))

        products = await extractor.extract(shop_url)

        assert len(products) == 0


@pytest.mark.asyncio
async def test_invalid_json_returns_empty_list(extractor: ShopifyAPIExtractor):
    """Test that invalid JSON response returns empty list."""
    shop_url = "https://example.myshopify.com"

    with respx.mock:
        # Mock response with invalid JSON
        respx.get(f"{shop_url}/products.json?limit=250&page=1").mock(
            return_value=Response(200, content=b"<html>Not JSON</html>", headers={"Content-Type": "text/html"})
        )

        products = await extractor.extract(shop_url)

        assert len(products) == 0


@pytest.mark.asyncio
async def test_returns_raw_dicts_not_models(extractor: ShopifyAPIExtractor, shopify_products_fixture: dict):
    """Test that extractor returns raw dicts, not Product models."""
    shop_url = "https://example.myshopify.com"

    with respx.mock:
        respx.get(f"{shop_url}/products.json?limit=250&page=1").mock(
            return_value=Response(200, json=shopify_products_fixture)
        )

        products = await extractor.extract(shop_url)

        # Verify returns raw dicts
        assert isinstance(products, list)
        assert len(products) == 3

        # First product should be a dict with expected raw Shopify fields
        product = products[0]
        assert isinstance(product, dict)
        assert product["id"] == 1001
        assert product["title"] == "Tree Runner"
        assert product["handle"] == "tree-runner"
        assert product["body_html"] == "<p>Lightweight running shoe</p>"
        assert product["vendor"] == "Allbirds"
        assert product["product_type"] == "Shoes"
        assert "variants" in product
        assert "images" in product


@pytest.mark.asyncio
async def test_timeout_returns_empty_list(extractor: ShopifyAPIExtractor):
    """Test that timeout errors return empty list."""
    shop_url = "https://example.myshopify.com"

    with respx.mock:
        # Mock timeout exception
        respx.get(f"{shop_url}/products.json?limit=250&page=1").mock(side_effect=httpx.TimeoutException("Timeout"))

        products = await extractor.extract(shop_url)

        assert len(products) == 0


@pytest.mark.asyncio
async def test_request_error_returns_empty_list(extractor: ShopifyAPIExtractor):
    """Test that request errors return empty list."""
    shop_url = "https://example.myshopify.com"

    with respx.mock:
        # Mock request error
        respx.get(f"{shop_url}/products.json?limit=250&page=1").mock(
            side_effect=httpx.RequestError("Connection failed")
        )

        products = await extractor.extract(shop_url)

        assert len(products) == 0


@pytest.mark.asyncio
async def test_pagination_stops_at_max_pages(extractor: ShopifyAPIExtractor):
    """Test that pagination respects max_pages limit."""
    # Create extractor with low max_pages for testing
    limited_extractor = ShopifyAPIExtractor(timeout=30, max_pages=2)
    shop_url = "https://example.myshopify.com"

    # Create 250 products per page
    page_products = [{"id": i, "title": f"Product {i}"} for i in range(250)]

    with respx.mock:
        # Mock pages that always return 250 products
        respx.get(f"{shop_url}/products.json?limit=250&page=1").mock(
            return_value=Response(200, json={"products": page_products})
        )
        respx.get(f"{shop_url}/products.json?limit=250&page=2").mock(
            return_value=Response(200, json={"products": page_products})
        )
        # Page 3 should not be called
        respx.get(f"{shop_url}/products.json?limit=250&page=3").mock(
            return_value=Response(200, json={"products": page_products})
        )

        products = await limited_extractor.extract(shop_url)

        # Should only get products from 2 pages
        assert len(products) == 500


@pytest.mark.asyncio
async def test_partial_extraction_on_error(extractor: ShopifyAPIExtractor, shopify_products_fixture: dict):
    """Test that partial results are returned when error occurs on later pages."""
    shop_url = "https://example.myshopify.com"

    with respx.mock:
        # First page succeeds
        respx.get(f"{shop_url}/products.json?limit=250&page=1").mock(
            return_value=Response(200, json=shopify_products_fixture)
        )

        # Second page fails
        respx.get(f"{shop_url}/products.json?limit=250&page=2").mock(return_value=Response(500))

        # Modify fixture to have 250 products to trigger pagination
        large_fixture = {"products": [{"id": i, "title": f"Product {i}"} for i in range(250)]}
        respx.get(f"{shop_url}/products.json?limit=250&page=1").mock(
            return_value=Response(200, json=large_fixture)
        )

        products = await extractor.extract(shop_url)

        # Should return products from first page only
        assert len(products) == 250


@pytest.mark.asyncio
async def test_trailing_slash_handling(extractor: ShopifyAPIExtractor, shopify_products_fixture: dict):
    """Test that shop URLs with trailing slashes are handled correctly."""
    shop_url_with_slash = "https://example.myshopify.com/"

    with respx.mock:
        # Should strip trailing slash and make correct request
        respx.get("https://example.myshopify.com/products.json?limit=250&page=1").mock(
            return_value=Response(200, json=shopify_products_fixture)
        )

        products = await extractor.extract(shop_url_with_slash)

        assert len(products) == 3


@pytest.mark.asyncio
async def test_timeout_logs_warning_with_partial_count(extractor: ShopifyAPIExtractor):
    """Test that timeout on page N>1 logs a WARNING (not ERROR) with products-so-far context."""
    import io
    import logging
    shop_url = "https://example.myshopify.com"

    # First page succeeds with 250 products (full page)
    page1_products = [{"id": i, "title": f"Product {i}", "handle": f"product-{i}",
                       "variants": [{"price": "10"}]} for i in range(250)]
    page1_response = {"products": page1_products}

    with respx.mock:
        respx.get(f"{shop_url}/products.json?limit=250&page=1").mock(
            return_value=Response(200, json=page1_response)
        )
        respx.get(f"{shop_url}/products.json?limit=250&page=2").mock(
            side_effect=httpx.TimeoutException("Timeout")
        )

        log_output = io.StringIO()
        handler = logging.StreamHandler(log_output)
        handler.setLevel(logging.WARNING)
        shopify_logger = logging.getLogger("app.extractors.shopify_api")
        shopify_logger.addHandler(handler)
        try:
            products = await extractor.extract(shop_url)
        finally:
            shopify_logger.removeHandler(handler)

    # Should return partial results from page 1
    assert len(products) == 250

    # Log should mention the page count and product count (at WARNING level, not ERROR)
    log_text = log_output.getvalue()
    assert "Timeout" in log_text or "timeout" in log_text.lower()
    assert "250" in log_text  # products count mentioned
    assert "incomplete" in log_text.lower()  # explicitly calls out incompleteness
