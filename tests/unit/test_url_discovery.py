"""Unit tests for URL discovery services."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from app.models.enums import Platform
from app.services.sitemap_parser import SitemapParser
from app.services.url_discovery import URLDiscoveryService

# Get fixtures directory
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def sample_sitemap_xml() -> str:
    """Load sample sitemap XML fixture."""
    return (FIXTURES_DIR / "sample_sitemap.xml").read_text()


@pytest.fixture
def sample_sitemap_index_xml() -> str:
    """Load sample sitemap index XML fixture."""
    return (FIXTURES_DIR / "sample_sitemap_index.xml").read_text()


@pytest.fixture
def sitemap_products_xml() -> str:
    """Load nested sitemap-products.xml fixture."""
    return (FIXTURES_DIR / "sitemap-products.xml").read_text()


@pytest.fixture
def sitemap_pages_xml() -> str:
    """Load nested sitemap-pages.xml fixture."""
    return (FIXTURES_DIR / "sitemap-pages.xml").read_text()


class TestSitemapParser:
    """Test cases for SitemapParser."""

    @respx.mock
    async def test_parse_standard_sitemap(self, sample_sitemap_xml):
        """Test parsing a standard sitemap XML."""
        parser = SitemapParser()

        # Mock HTTP request
        route = respx.get("https://example.com/sitemap.xml").mock(
            return_value=httpx.Response(200, text=sample_sitemap_xml)
        )

        entries = await parser.parse("https://example.com/sitemap.xml")

        assert route.called
        # Should filter to only product URLs (shirt, pants, shoes - 3 products)
        assert len(entries) == 3

        # Check first entry
        assert entries[0].url == "https://example.com/products/shirt"
        assert entries[0].lastmod == "2024-01-01"
        assert entries[0].priority == 0.8

        # Check second entry
        assert entries[1].url == "https://example.com/products/pants"
        assert entries[1].lastmod == "2024-01-02"
        assert entries[1].priority is None

        # Check third entry (shop URL)
        assert entries[2].url == "https://example.com/shop/shoes"

    @respx.mock
    async def test_parse_sitemap_index(
        self, sample_sitemap_index_xml, sitemap_products_xml, sitemap_pages_xml
    ):
        """Test parsing a sitemap index with nested sitemaps."""
        parser = SitemapParser()

        # Mock sitemap index
        respx.get("https://example.com/sitemap_index.xml").mock(
            return_value=httpx.Response(200, text=sample_sitemap_index_xml)
        )

        # Mock nested sitemaps
        respx.get("https://example.com/sitemap-products.xml").mock(
            return_value=httpx.Response(200, text=sitemap_products_xml)
        )

        respx.get("https://example.com/sitemap-pages.xml").mock(
            return_value=httpx.Response(200, text=sitemap_pages_xml)
        )

        entries = await parser.parse("https://example.com/sitemap_index.xml")

        # Should only get product URLs from sitemap-products.xml (2 products)
        # sitemap-pages.xml has no product URLs
        assert len(entries) == 2
        assert entries[0].url == "https://example.com/products/laptop"
        assert entries[0].lastmod == "2024-01-10"
        assert entries[0].priority == 1.0

        assert entries[1].url == "https://example.com/products/phone"
        assert entries[1].lastmod == "2024-01-11"
        assert entries[1].priority == 0.9

    async def test_filter_urls_by_product_patterns(self):
        """Test URL filtering by product patterns."""
        parser = SitemapParser()

        # Test with default patterns
        assert parser._is_product_url("https://example.com/products/shirt")
        assert parser._is_product_url("https://example.com/product/123")
        assert parser._is_product_url("https://example.com/shop/item")
        assert parser._is_product_url("https://example.com/p/abc")

        # Test non-product URLs
        assert not parser._is_product_url("https://example.com/about")
        assert not parser._is_product_url("https://example.com/contact")
        assert not parser._is_product_url("https://example.com/blog/post")

        # Test custom patterns
        custom_parser = SitemapParser(product_patterns=["/item/", "/catalog/"])
        assert custom_parser._is_product_url("https://example.com/item/123")
        assert custom_parser._is_product_url("https://example.com/catalog/abc")
        assert not custom_parser._is_product_url("https://example.com/products/shirt")

    @respx.mock
    async def test_handle_empty_sitemap(self):
        """Test handling of empty/invalid XML."""
        parser = SitemapParser()

        # Empty XML
        respx.get("https://example.com/empty.xml").mock(
            return_value=httpx.Response(200, text="<?xml version='1.0'?><urlset></urlset>")
        )

        entries = await parser.parse("https://example.com/empty.xml")
        assert entries == []

    @respx.mock
    async def test_handle_invalid_xml(self):
        """Test handling of invalid XML."""
        parser = SitemapParser()

        # Invalid XML
        respx.get("https://example.com/invalid.xml").mock(
            return_value=httpx.Response(200, text="not valid xml at all")
        )

        entries = await parser.parse("https://example.com/invalid.xml")
        assert entries == []

    @respx.mock
    async def test_handle_404_error(self):
        """Test handling of 404 errors."""
        parser = SitemapParser()

        respx.get("https://example.com/notfound.xml").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        entries = await parser.parse("https://example.com/notfound.xml")
        assert entries == []

    @respx.mock
    async def test_handle_network_error(self):
        """Test handling of network errors."""
        parser = SitemapParser()

        respx.get("https://example.com/error.xml").mock(side_effect=httpx.ConnectError)

        entries = await parser.parse("https://example.com/error.xml")
        assert entries == []

    @respx.mock
    async def test_parse_sitemap_without_namespace(self):
        """Test parsing sitemap XML without namespace."""
        parser = SitemapParser()

        # Sitemap without namespace
        xml_no_ns = """<?xml version="1.0" encoding="UTF-8"?>
<urlset>
  <url>
    <loc>https://example.com/products/item1</loc>
    <lastmod>2024-01-01</lastmod>
  </url>
  <url>
    <loc>https://example.com/products/item2</loc>
  </url>
</urlset>"""

        respx.get("https://example.com/sitemap-no-ns.xml").mock(
            return_value=httpx.Response(200, text=xml_no_ns)
        )

        entries = await parser.parse("https://example.com/sitemap-no-ns.xml")
        assert len(entries) == 2
        assert entries[0].url == "https://example.com/products/item1"
        assert entries[1].url == "https://example.com/products/item2"


class TestURLDiscoveryService:
    """Test cases for URLDiscoveryService."""

    @respx.mock
    async def test_shopify_returns_paginated_api_urls(self):
        """Test Shopify platform returns paginated API URLs."""
        service = URLDiscoveryService()

        # Mock Shopify products API
        mock_products = {
            "products": [{"id": i, "title": f"Product {i}"} for i in range(250)]
        }
        respx.get("https://shop.example.com/products.json?limit=250&page=1").mock(
            return_value=httpx.Response(200, json=mock_products)
        )

        urls = await service.discover("https://shop.example.com", Platform.SHOPIFY)

        # Should return pagination URLs (10 pages since first page returned 250)
        assert len(urls) == 10
        assert urls[0] == "https://shop.example.com/products.json?limit=250&page=1"
        assert urls[9] == "https://shop.example.com/products.json?limit=250&page=10"

    @respx.mock
    async def test_shopify_single_page(self):
        """Test Shopify with less than 250 products (single page)."""
        service = URLDiscoveryService()

        # Mock Shopify products API with < 250 products
        mock_products = {
            "products": [{"id": i, "title": f"Product {i}"} for i in range(50)]
        }
        respx.get("https://shop.example.com/products.json?limit=250&page=1").mock(
            return_value=httpx.Response(200, json=mock_products)
        )

        urls = await service.discover("https://shop.example.com", Platform.SHOPIFY)

        # Should return only first page
        assert len(urls) == 1
        assert urls[0] == "https://shop.example.com/products.json?limit=250&page=1"

    @respx.mock
    async def test_shopify_fallback_to_sitemap(self, sample_sitemap_xml):
        """Test Shopify falls back to sitemap when API fails."""
        service = URLDiscoveryService()

        # Mock failed API request
        respx.get("https://shop.example.com/products.json?limit=250&page=1").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        # Mock sitemap
        respx.get("https://shop.example.com/sitemap.xml").mock(
            return_value=httpx.Response(200, text=sample_sitemap_xml)
        )

        urls = await service.discover("https://shop.example.com", Platform.SHOPIFY)

        # Should return URLs from sitemap
        assert len(urls) == 3
        assert "https://example.com/products/shirt" in urls

    @respx.mock
    async def test_woocommerce_api_success(self):
        """Test WooCommerce API detection."""
        service = URLDiscoveryService()

        # Mock WooCommerce Store API
        respx.get("https://shop.example.com/wp-json/wc/store/v1/products").mock(
            return_value=httpx.Response(200, json=[])
        )

        urls = await service.discover("https://shop.example.com", Platform.WOOCOMMERCE)

        # Should return the API endpoint
        assert len(urls) == 1
        assert urls[0] == "https://shop.example.com/wp-json/wc/store/v1/products"

    @respx.mock
    async def test_woocommerce_fallback_to_sitemap(self, sample_sitemap_xml):
        """Test WooCommerce falls back to sitemap when API fails."""
        service = URLDiscoveryService()

        # Mock failed API
        respx.get("https://shop.example.com/wp-json/wc/store/v1/products").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        # Mock sitemap
        respx.get("https://shop.example.com/sitemap.xml").mock(
            return_value=httpx.Response(200, text=sample_sitemap_xml)
        )

        urls = await service.discover("https://shop.example.com", Platform.WOOCOMMERCE)

        assert len(urls) == 3
        assert "https://example.com/products/shirt" in urls

    @respx.mock
    async def test_magento_api_success(self):
        """Test Magento API detection."""
        service = URLDiscoveryService()

        # Mock Magento REST API
        respx.get("https://shop.example.com/rest/V1/products?searchCriteria[pageSize]=100").mock(
            return_value=httpx.Response(200, json={"items": []})
        )

        urls = await service.discover("https://shop.example.com", Platform.MAGENTO)

        # Should return the API endpoint
        assert len(urls) == 1
        assert urls[0] == "https://shop.example.com/rest/V1/products?searchCriteria[pageSize]=100"

    @respx.mock
    async def test_magento_fallback_to_sitemap(self, sample_sitemap_xml):
        """Test Magento falls back to sitemap when API fails."""
        service = URLDiscoveryService()

        # Mock failed API
        respx.get("https://shop.example.com/rest/V1/products?searchCriteria[pageSize]=100").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        # Mock sitemap
        respx.get("https://shop.example.com/sitemap.xml").mock(
            return_value=httpx.Response(200, text=sample_sitemap_xml)
        )

        urls = await service.discover("https://shop.example.com", Platform.MAGENTO)

        assert len(urls) == 3

    @respx.mock
    async def test_bigcommerce_uses_sitemap(self, sample_sitemap_xml):
        """Test BigCommerce uses sitemap."""
        service = URLDiscoveryService()

        # Mock sitemap
        respx.get("https://shop.example.com/sitemap.xml").mock(
            return_value=httpx.Response(200, text=sample_sitemap_xml)
        )

        urls = await service.discover("https://shop.example.com", Platform.BIGCOMMERCE)

        assert len(urls) == 3

    @respx.mock
    async def test_generic_uses_sitemap(self, sample_sitemap_xml):
        """Test generic platform uses sitemap."""
        service = URLDiscoveryService()

        # Mock sitemap
        respx.get("https://shop.example.com/sitemap.xml").mock(
            return_value=httpx.Response(200, text=sample_sitemap_xml)
        )

        urls = await service.discover("https://shop.example.com", Platform.GENERIC)

        assert len(urls) == 3

    @respx.mock
    async def test_generic_returns_base_url_when_no_sitemap(self):
        """Test generic platform returns base URL when no sitemap found."""
        service = URLDiscoveryService()

        # Mock all sitemap URLs as 404
        respx.get("https://shop.example.com/sitemap.xml").mock(
            return_value=httpx.Response(404, text="Not Found")
        )
        respx.get("https://shop.example.com/sitemap_index.xml").mock(
            return_value=httpx.Response(404, text="Not Found")
        )
        respx.get("https://shop.example.com/product-sitemap.xml").mock(
            return_value=httpx.Response(404, text="Not Found")
        )
        respx.get("https://shop.example.com/sitemap-products.xml").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        urls = await service.discover("https://shop.example.com", Platform.GENERIC)

        # Should return base URL for BFS crawling
        assert len(urls) == 1
        assert urls[0] == "https://shop.example.com"

    @respx.mock
    async def test_generic_returns_base_url_on_sitemap_failure(self):
        """Test generic platform returns base URL when sitemap fails."""
        service = URLDiscoveryService()

        # Mock all requests to fail
        respx.get(url__regex=r".*").mock(side_effect=httpx.ConnectError)

        # For generic platform, should return base URL for crawling
        urls = await service.discover("https://shop.example.com", Platform.GENERIC)
        assert urls == ["https://shop.example.com"]

    @respx.mock
    async def test_returns_empty_list_on_exception(self):
        """Test service returns empty list on unexpected exception."""
        service = URLDiscoveryService()

        # Mock Shopify API to fail completely
        respx.get(url__regex=r".*").mock(side_effect=httpx.ConnectError)

        # Shopify should return empty list if both API and sitemap fail
        urls = await service.discover("https://shop.example.com", Platform.SHOPIFY)
        assert urls == []

    @respx.mock
    async def test_url_normalization(self, sample_sitemap_xml):
        """Test that base URLs are normalized (trailing slash removed)."""
        service = URLDiscoveryService()

        # Mock sitemap
        respx.get("https://shop.example.com/sitemap.xml").mock(
            return_value=httpx.Response(200, text=sample_sitemap_xml)
        )

        # Test with trailing slash
        urls1 = await service.discover("https://shop.example.com/", Platform.GENERIC)

        # Test without trailing slash
        urls2 = await service.discover("https://shop.example.com", Platform.GENERIC)

        # Both should return the same results
        assert urls1 == urls2

    @respx.mock
    async def test_sitemap_deduplication(self):
        """Test that duplicate URLs from multiple sitemaps are deduplicated."""
        service = URLDiscoveryService()

        # Sitemap with duplicate products
        sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/products/item1</loc></url>
  <url><loc>https://example.com/products/item1</loc></url>
  <url><loc>https://example.com/products/item2</loc></url>
</urlset>"""

        respx.get("https://shop.example.com/sitemap.xml").mock(
            return_value=httpx.Response(200, text=sitemap_xml)
        )

        urls = await service.discover("https://shop.example.com", Platform.GENERIC)

        # Should deduplicate
        assert len(urls) == 2
        assert urls.count("https://example.com/products/item1") == 1
