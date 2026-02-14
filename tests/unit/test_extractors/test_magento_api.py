"""Unit tests for MagentoAPIExtractor."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx
from httpx import Response

from app.extractors.magento_api import MagentoAPIExtractor


@pytest.fixture
def magento_products_fixture() -> dict:
    """Load magento products test fixture."""
    fixture_path = Path(__file__).parent.parent.parent / "fixtures" / "magento_products.json"
    with open(fixture_path) as f:
        return json.load(f)


@pytest.fixture
def extractor() -> MagentoAPIExtractor:
    """Create a MagentoAPIExtractor instance."""
    return MagentoAPIExtractor(timeout=30, page_size=100)


@pytest.mark.asyncio
async def test_single_page_extraction(extractor: MagentoAPIExtractor, magento_products_fixture: dict):
    """Test extraction with total_count matching items count (single page)."""
    shop_url = "https://example.com"

    with respx.mock:
        # Mock single page response with 2 products
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=1"
        ).mock(return_value=Response(200, json=magento_products_fixture))

        products = await extractor.extract(shop_url)

        assert len(products) == 2
        assert products[0]["id"] == 1
        assert products[0]["sku"] == "MAG-001"
        assert products[0]["name"] == "Magento Test Product"
        assert products[1]["id"] == 2
        assert products[1]["sku"] == "MAG-002"


@pytest.mark.asyncio
async def test_multi_page_pagination_using_total_count(extractor: MagentoAPIExtractor):
    """Test pagination using total_count to determine when to stop."""
    shop_url = "https://example.com"

    # Create page 1 with 100 products
    page1_products = [{"id": i, "sku": f"PROD-{i}", "name": f"Product {i}"} for i in range(1, 101)]
    page1_response = {"items": page1_products, "total_count": 150}

    # Create page 2 with 50 products
    page2_products = [
        {"id": i, "sku": f"PROD-{i}", "name": f"Product {i}"} for i in range(101, 151)
    ]
    page2_response = {"items": page2_products, "total_count": 150}

    with respx.mock:
        # Mock first page
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=1"
        ).mock(return_value=Response(200, json=page1_response))

        # Mock second page
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=2"
        ).mock(return_value=Response(200, json=page2_response))

        products = await extractor.extract(shop_url)

        # Should get all 150 products
        assert len(products) == 150
        assert products[0]["id"] == 1
        assert products[99]["id"] == 100
        assert products[100]["id"] == 101
        assert products[-1]["id"] == 150


@pytest.mark.asyncio
async def test_empty_response(extractor: MagentoAPIExtractor):
    """Test extraction when store has 0 products."""
    shop_url = "https://example.com"

    with respx.mock:
        # Mock empty products response
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=1"
        ).mock(return_value=Response(200, json={"items": [], "total_count": 0}))

        products = await extractor.extract(shop_url)

        assert len(products) == 0


@pytest.mark.asyncio
async def test_http_404_returns_empty_list(extractor: MagentoAPIExtractor):
    """Test that HTTP 404 (API not available) returns empty list."""
    shop_url = "https://example.com"

    with respx.mock:
        # Mock 404 response
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=1"
        ).mock(return_value=Response(404))

        products = await extractor.extract(shop_url)

        assert len(products) == 0


@pytest.mark.asyncio
async def test_http_500_returns_empty_list(extractor: MagentoAPIExtractor):
    """Test that HTTP 500 server error returns empty list."""
    shop_url = "https://example.com"

    with respx.mock:
        # Mock 500 response
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=1"
        ).mock(return_value=Response(500))

        products = await extractor.extract(shop_url)

        assert len(products) == 0


@pytest.mark.asyncio
async def test_http_429_returns_empty_list(extractor: MagentoAPIExtractor):
    """Test that HTTP 429 (rate limit) returns empty list."""
    shop_url = "https://example.com"

    with respx.mock:
        # Mock 429 response
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=1"
        ).mock(return_value=Response(429))

        products = await extractor.extract(shop_url)

        assert len(products) == 0


@pytest.mark.asyncio
async def test_invalid_json_returns_empty_list(extractor: MagentoAPIExtractor):
    """Test that invalid JSON response returns empty list."""
    shop_url = "https://example.com"

    with respx.mock:
        # Mock response with invalid JSON
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=1"
        ).mock(
            return_value=Response(200, content=b"<html>Not JSON</html>", headers={"Content-Type": "text/html"})
        )

        products = await extractor.extract(shop_url)

        assert len(products) == 0


@pytest.mark.asyncio
async def test_returns_raw_dicts_not_models(
    extractor: MagentoAPIExtractor, magento_products_fixture: dict
):
    """Test that extractor returns raw dicts, not Product models."""
    shop_url = "https://example.com"

    with respx.mock:
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=1"
        ).mock(return_value=Response(200, json=magento_products_fixture))

        products = await extractor.extract(shop_url)

        # Verify returns raw dicts
        assert isinstance(products, list)
        assert len(products) == 2

        # First product should be a dict with expected raw Magento fields
        product = products[0]
        assert isinstance(product, dict)
        assert product["id"] == 1
        assert product["sku"] == "MAG-001"
        assert product["name"] == "Magento Test Product"
        assert product["price"] == 49.99
        assert product["status"] == 1
        assert product["type_id"] == "simple"
        assert "custom_attributes" in product
        assert isinstance(product["custom_attributes"], list)


@pytest.mark.asyncio
async def test_timeout_returns_empty_list(extractor: MagentoAPIExtractor):
    """Test that timeout errors return empty list."""
    shop_url = "https://example.com"

    with respx.mock:
        # Mock timeout exception
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=1"
        ).mock(side_effect=httpx.TimeoutException("Timeout"))

        products = await extractor.extract(shop_url)

        assert len(products) == 0


@pytest.mark.asyncio
async def test_request_error_returns_empty_list(extractor: MagentoAPIExtractor):
    """Test that request errors return empty list."""
    shop_url = "https://example.com"

    with respx.mock:
        # Mock request error
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=1"
        ).mock(side_effect=httpx.RequestError("Connection failed"))

        products = await extractor.extract(shop_url)

        assert len(products) == 0


@pytest.mark.asyncio
async def test_partial_extraction_on_error(extractor: MagentoAPIExtractor):
    """Test that partial results are returned when error occurs on later pages."""
    shop_url = "https://example.com"

    # Create page 1 with 100 products
    page1_products = [{"id": i, "sku": f"PROD-{i}", "name": f"Product {i}"} for i in range(1, 101)]
    page1_response = {"items": page1_products, "total_count": 150}

    with respx.mock:
        # First page succeeds
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=1"
        ).mock(return_value=Response(200, json=page1_response))

        # Second page fails
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=2"
        ).mock(return_value=Response(500))

        products = await extractor.extract(shop_url)

        # Should return products from first page only
        assert len(products) == 100
        assert products[0]["id"] == 1
        assert products[-1]["id"] == 100


@pytest.mark.asyncio
async def test_trailing_slash_handling(
    extractor: MagentoAPIExtractor, magento_products_fixture: dict
):
    """Test that shop URLs with trailing slashes are handled correctly."""
    shop_url_with_slash = "https://example.com/"

    with respx.mock:
        # Should strip trailing slash and make correct request
        respx.get(
            "https://example.com/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=1"
        ).mock(return_value=Response(200, json=magento_products_fixture))

        products = await extractor.extract(shop_url_with_slash)

        assert len(products) == 2


@pytest.mark.asyncio
async def test_stops_when_total_count_reached(extractor: MagentoAPIExtractor):
    """Test that pagination stops when total_count is reached even if page has items."""
    shop_url = "https://example.com"

    # Create page 1 with 100 products, but total_count says there are only 100
    page1_products = [{"id": i, "sku": f"PROD-{i}", "name": f"Product {i}"} for i in range(1, 101)]
    page1_response = {"items": page1_products, "total_count": 100}

    with respx.mock:
        # Mock first page
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=1"
        ).mock(return_value=Response(200, json=page1_response))

        # Page 2 should not be called since we already have total_count products
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=100&searchCriteria[currentPage]=2"
        ).mock(return_value=Response(200, json={"items": [], "total_count": 100}))

        products = await extractor.extract(shop_url)

        # Should only fetch first page since we reached total_count
        assert len(products) == 100


@pytest.mark.asyncio
async def test_custom_page_size(magento_products_fixture: dict):
    """Test that custom page size is used in API requests."""
    shop_url = "https://example.com"
    custom_extractor = MagentoAPIExtractor(timeout=30, page_size=50)

    with respx.mock:
        # Mock request with custom page size
        respx.get(
            f"{shop_url}/rest/V1/products?searchCriteria[pageSize]=50&searchCriteria[currentPage]=1"
        ).mock(return_value=Response(200, json=magento_products_fixture))

        products = await custom_extractor.extract(shop_url)

        assert len(products) == 2
