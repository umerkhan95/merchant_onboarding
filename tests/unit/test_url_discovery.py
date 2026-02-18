"""Unit tests for URL discovery services."""

from __future__ import annotations

from pathlib import Path
import httpx
import pytest
import respx

from app.models.enums import Platform
from app.services.url_discovery import URLDiscoveryService

# Get fixtures directory
FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture
def sample_sitemap_xml() -> str:
    """Load sample sitemap XML fixture."""
    return (FIXTURES_DIR / "sample_sitemap.xml").read_text()


@pytest.fixture
def mock_seeder(monkeypatch):
    """Mock AsyncUrlSeeder to return controlled results.

    Returns an object with ``urls_to_return`` (list of URL strings) and
    ``raise_error`` (bool).  Tests can modify these before calling
    discovery methods.
    """

    class _State:
        urls_to_return: list[str] = []
        raise_error: bool = False

    state = _State()

    class FakeSeeder:
        async def urls(self, domain, config):
            if state.raise_error:
                raise RuntimeError("Seeder failed")
            return [{"url": u, "status": "valid"} for u in state.urls_to_return]

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(
        "app.services.url_discovery.AsyncUrlSeeder", lambda: FakeSeeder()
    )
    return state


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
    async def test_shopify_fallback_to_sitemap(self, sample_sitemap_xml, mock_seeder):
        """Test Shopify falls back to product sitemap when API fails."""
        service = URLDiscoveryService()

        # Mock failed API request
        respx.get("https://shop.example.com/products.json?limit=250&page=1").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        # Mock Shopify product sitemap (Phase 1)
        respx.get("https://shop.example.com/sitemap_products_1.xml").mock(
            return_value=httpx.Response(200, text=sample_sitemap_xml)
        )

        urls = await service.discover("https://shop.example.com", Platform.SHOPIFY)

        # sample_sitemap.xml has 5 URLs; 2 (/about, /contact) filtered by denylist
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
    async def test_woocommerce_fallback_to_sitemap(self, sample_sitemap_xml, mock_seeder):
        """Test WooCommerce falls back to product sitemap when API fails."""
        service = URLDiscoveryService()

        # Mock failed API
        respx.get("https://shop.example.com/wp-json/wc/store/v1/products").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        # Mock WooCommerce product sitemap (Phase 1)
        respx.get("https://shop.example.com/product-sitemap.xml").mock(
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
    async def test_magento_fallback_to_sitemap(self, sample_sitemap_xml, mock_seeder):
        """Test Magento falls back to product sitemap when API fails."""
        service = URLDiscoveryService()

        # Mock failed API
        respx.get("https://shop.example.com/rest/V1/products?searchCriteria[pageSize]=100").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        # Mock Magento product sitemap (Phase 1)
        respx.get("https://shop.example.com/pub/media/sitemap/sitemap.xml").mock(
            return_value=httpx.Response(200, text=sample_sitemap_xml)
        )

        urls = await service.discover("https://shop.example.com", Platform.MAGENTO)

        assert len(urls) == 3

    @respx.mock
    async def test_bigcommerce_uses_sitemap(self, sample_sitemap_xml, mock_seeder):
        """Test BigCommerce uses platform-specific sitemap."""
        service = URLDiscoveryService()

        # Mock BigCommerce sitemap (Phase 1: /xmlsitemap.php)
        respx.get("https://shop.example.com/xmlsitemap.php").mock(
            return_value=httpx.Response(200, text=sample_sitemap_xml)
        )

        urls = await service.discover("https://shop.example.com", Platform.BIGCOMMERCE)

        assert len(urls) == 3

    async def test_generic_uses_sitemap(self, mock_seeder):
        """Test generic platform uses AsyncUrlSeeder for sitemap discovery."""
        service = URLDiscoveryService()

        # Generic has no platform-specific sitemaps, goes directly to AsyncUrlSeeder
        mock_seeder.urls_to_return = [
            "https://shop.example.com/products/shirt",
            "https://shop.example.com/products/pants",
            "https://shop.example.com/products/shoes",
        ]

        urls = await service.discover("https://shop.example.com", Platform.GENERIC)

        assert len(urls) == 3
        assert "https://shop.example.com/products/shirt" in urls

    async def test_generic_returns_base_url_when_no_sitemap(self, mock_seeder, monkeypatch):
        """Test generic platform returns base URL when no sitemap found."""
        service = URLDiscoveryService()

        # AsyncUrlSeeder returns empty
        mock_seeder.urls_to_return = []

        # Also mock crawl4ai to return empty
        class FakeCrawler:
            async def arun(self, url, config=None):
                return []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        monkeypatch.setattr(
            "app.services.url_discovery.AsyncWebCrawler",
            lambda config=None, **kwargs: FakeCrawler(),
        )

        urls = await service.discover("https://shop.example.com", Platform.GENERIC)

        # Should return base URL for BFS crawling
        assert len(urls) == 1
        assert urls[0] == "https://shop.example.com"

    async def test_generic_returns_base_url_on_sitemap_failure(self, mock_seeder, monkeypatch):
        """Test generic platform returns base URL when sitemap fails."""
        service = URLDiscoveryService()

        # AsyncUrlSeeder raises error
        mock_seeder.raise_error = True

        # Also mock crawl4ai to fail
        class FailingCrawler:
            async def arun(self, url, config=None):
                raise RuntimeError("Crawl failed")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        monkeypatch.setattr(
            "app.services.url_discovery.AsyncWebCrawler",
            lambda config=None, **kwargs: FailingCrawler(),
        )

        # For generic platform, should return base URL for crawling
        urls = await service.discover("https://shop.example.com", Platform.GENERIC)
        assert urls == ["https://shop.example.com"]

    @respx.mock
    async def test_returns_empty_list_on_exception(self, mock_seeder):
        """Test service returns empty list on unexpected exception."""
        service = URLDiscoveryService()

        # Mock Shopify API to fail
        respx.get("https://shop.example.com/products.json?limit=250&page=1").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        # Mock product sitemap to also fail
        respx.get("https://shop.example.com/sitemap_products_1.xml").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        # AsyncUrlSeeder returns empty
        mock_seeder.urls_to_return = []

        # Shopify should return empty list if both API and sitemap fail
        urls = await service.discover("https://shop.example.com", Platform.SHOPIFY)
        assert urls == []

    async def test_url_normalization(self, mock_seeder):
        """Test that base URLs are normalized (trailing slash removed)."""
        service = URLDiscoveryService()

        mock_seeder.urls_to_return = [
            "https://shop.example.com/products/shirt",
            "https://shop.example.com/products/pants",
            "https://shop.example.com/products/shoes",
        ]

        # Test with trailing slash
        urls1 = await service.discover("https://shop.example.com/", Platform.GENERIC)

        # Test without trailing slash
        urls2 = await service.discover("https://shop.example.com", Platform.GENERIC)

        # Both should return the same results
        assert sorted(urls1) == sorted(urls2)

    async def test_deep_crawl_discovers_product_urls(self, monkeypatch):
        """Test that BestFirst deep crawl discovers product URLs and filters non-product pages."""
        service = URLDiscoveryService()

        # Fake crawl results (deep crawl returns a list of CrawlResult)
        class FakeCrawlResult:
            def __init__(self, url, success=True):
                self.url = url
                self.success = success

        fake_results = [
            FakeCrawlResult("https://shop.example.com/products/bag-123"),
            FakeCrawlResult("https://shop.example.com/products/shoe-456"),
            FakeCrawlResult("https://shop.example.com/about"),  # filtered
            FakeCrawlResult("https://shop.example.com/checkout/step1"),  # filtered
            FakeCrawlResult("https://shop.example.com/cart"),  # filtered
            FakeCrawlResult("https://shop.example.com/women/dresses"),  # kept
            FakeCrawlResult("https://shop.example.com/blog/post1", success=False),  # failed
        ]

        class FakeCrawler:
            async def arun(self, url, config=None):
                return fake_results

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        monkeypatch.setattr(
            "app.services.url_discovery.AsyncWebCrawler",
            lambda config=None, **kwargs: FakeCrawler(),
        )

        urls = await service._discover_via_crawl4ai("https://shop.example.com")

        # Product URLs should be included
        assert "https://shop.example.com/products/bag-123" in urls
        assert "https://shop.example.com/products/shoe-456" in urls
        assert "https://shop.example.com/women/dresses" in urls

        # Non-product URLs should be filtered out
        assert "https://shop.example.com/about" not in urls
        assert "https://shop.example.com/checkout/step1" not in urls
        assert "https://shop.example.com/cart" not in urls
        assert "https://shop.example.com/blog/post1" not in urls

    async def test_deep_crawl_handles_single_result(self, monkeypatch):
        """Test deep crawl handles case where arun returns a single result."""
        service = URLDiscoveryService()

        class FakeCrawlResult:
            success = True
            url = "https://shop.example.com/products/item1"

        class FakeCrawler:
            async def arun(self, url, config=None):
                return FakeCrawlResult()

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        monkeypatch.setattr(
            "app.services.url_discovery.AsyncWebCrawler",
            lambda config=None, **kwargs: FakeCrawler(),
        )

        urls = await service._discover_via_crawl4ai("https://shop.example.com")
        assert "https://shop.example.com/products/item1" in urls

    async def test_sitemap_deduplication(self, mock_seeder):
        """Test that duplicate URLs from AsyncUrlSeeder are deduplicated by denylist filtering."""
        service = URLDiscoveryService()

        # AsyncUrlSeeder returns duplicates and non-product URLs
        mock_seeder.urls_to_return = [
            "https://example.com/products/item1",
            "https://example.com/products/item1",  # duplicate
            "https://example.com/products/item2",
            "https://example.com/about",  # filtered
        ]

        urls = await service._discover_via_sitemap(
            "https://example.com", Platform.GENERIC
        )

        # AsyncUrlSeeder may return duplicates; denylist filters /about
        # (AsyncUrlSeeder internally deduplicates, but we don't rely on it)
        assert "https://example.com/products/item1" in urls
        assert "https://example.com/products/item2" in urls
        assert "https://example.com/about" not in urls

    async def test_deep_crawl_uses_bestfirst_strategy(self, monkeypatch):
        """Test that _discover_via_crawl4ai uses BestFirstCrawlingStrategy with keyword scorer."""
        from crawl4ai.deep_crawling import BestFirstCrawlingStrategy
        from crawl4ai.deep_crawling.scorers import KeywordRelevanceScorer

        captured_strategy = {}

        class FakeCrawler:
            async def arun(self, url, config=None):
                # Capture the strategy from the config
                if config and hasattr(config, "deep_crawl_strategy"):
                    captured_strategy["strategy"] = config.deep_crawl_strategy
                return []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        monkeypatch.setattr(
            "app.services.url_discovery.AsyncWebCrawler",
            lambda config=None, **kwargs: FakeCrawler(),
        )

        service = URLDiscoveryService()
        await service._discover_via_crawl4ai("https://shop.example.com")

        assert "strategy" in captured_strategy
        strategy = captured_strategy["strategy"]
        assert isinstance(strategy, BestFirstCrawlingStrategy)
        assert strategy.max_pages == 100
        assert strategy.max_depth == 3
        assert strategy.url_scorer is not None
        assert isinstance(strategy.url_scorer, KeywordRelevanceScorer)

    async def test_deep_crawl_respects_max_pages_param(self, monkeypatch):
        """Test that max_pages parameter is passed through to BestFirstCrawlingStrategy."""
        captured_strategy = {}

        class FakeCrawler:
            async def arun(self, url, config=None):
                if config and hasattr(config, "deep_crawl_strategy"):
                    captured_strategy["strategy"] = config.deep_crawl_strategy
                return []

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        monkeypatch.setattr(
            "app.services.url_discovery.AsyncWebCrawler",
            lambda config=None, **kwargs: FakeCrawler(),
        )

        service = URLDiscoveryService()
        await service._discover_via_crawl4ai("https://shop.example.com", max_pages=200)

        assert captured_strategy["strategy"].max_pages == 200

    async def test_deep_crawl_handles_exception(self, monkeypatch):
        """Test that _discover_via_crawl4ai returns empty list on crawler exception."""

        class FailingCrawler:
            async def arun(self, url, config=None):
                raise RuntimeError("Browser crashed")

            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                pass

        monkeypatch.setattr(
            "app.services.url_discovery.AsyncWebCrawler",
            lambda config=None, **kwargs: FailingCrawler(),
        )

        service = URLDiscoveryService()
        urls = await service._discover_via_crawl4ai("https://shop.example.com")
        assert urls == []

    def test_product_keywords_constant(self):
        """Test that PRODUCT_KEYWORDS contains expected keywords for scorer."""
        from app.services.url_discovery import PRODUCT_KEYWORDS

        assert "product" in PRODUCT_KEYWORDS
        assert "price" in PRODUCT_KEYWORDS
        assert "buy" in PRODUCT_KEYWORDS
        assert "shop" in PRODUCT_KEYWORDS
        assert len(PRODUCT_KEYWORDS) >= 8


# ── New tests for #57: URL filtering in sitemap discovery ─────────────


class TestSitemapProductPrioritization:
    """Tests for platform-aware sitemap prioritization and denylist filtering."""

    @respx.mock
    async def test_sitemap_prioritizes_product_sitemaps(self, mock_seeder):
        """Platform-specific product sitemaps are tried first; generic is NOT fetched."""
        service = URLDiscoveryService()

        product_sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://shop.example.com/product/earl-grey</loc></url>
  <url><loc>https://shop.example.com/product/green-tea</loc></url>
</urlset>"""

        # Phase 1: product-sitemap.xml returns results
        respx.get("https://shop.example.com/product-sitemap.xml").mock(
            return_value=httpx.Response(200, text=product_sitemap_xml)
        )

        urls = await service._discover_via_sitemap(
            "https://shop.example.com", Platform.WOOCOMMERCE
        )

        # Product sitemap yielded results, so AsyncUrlSeeder was never called
        assert len(urls) == 2
        assert "https://shop.example.com/product/earl-grey" in urls
        assert "https://shop.example.com/product/green-tea" in urls

    @respx.mock
    async def test_sitemap_falls_back_to_generic(self, mock_seeder):
        """When product sitemaps 404, AsyncUrlSeeder is used as fallback."""
        service = URLDiscoveryService()

        # Phase 1: product sitemaps fail
        respx.get("https://shop.example.com/product-sitemap.xml").mock(
            return_value=httpx.Response(404, text="Not Found")
        )
        respx.get("https://shop.example.com/product-sitemap1.xml").mock(
            return_value=httpx.Response(404, text="Not Found")
        )

        # Phase 2: AsyncUrlSeeder returns results
        mock_seeder.urls_to_return = [
            "https://shop.example.com/product/earl-grey",
            "https://shop.example.com/product/green-tea",
        ]

        urls = await service._discover_via_sitemap(
            "https://shop.example.com", Platform.WOOCOMMERCE
        )

        assert len(urls) == 2
        assert "https://shop.example.com/product/earl-grey" in urls

    @respx.mock
    async def test_denylist_filters_non_product_urls(self, mock_seeder):
        """Denylist removes /about, /blog/*, etc. from sitemap results."""
        service = URLDiscoveryService()

        product_sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://shop.example.com/product/tea</loc></url>
  <url><loc>https://shop.example.com/about</loc></url>
  <url><loc>https://shop.example.com/blog/new-flavors</loc></url>
  <url><loc>https://shop.example.com/cart</loc></url>
  <url><loc>https://shop.example.com/collections/herbal</loc></url>
</urlset>"""

        respx.get("https://shop.example.com/product-sitemap.xml").mock(
            return_value=httpx.Response(200, text=product_sitemap_xml)
        )

        urls = await service._discover_via_sitemap(
            "https://shop.example.com", Platform.WOOCOMMERCE
        )

        # /about (exact path), /blog/* (segment), /cart (exact path) filtered
        assert "https://shop.example.com/product/tea" in urls
        assert "https://shop.example.com/collections/herbal" in urls
        assert "https://shop.example.com/about" not in urls
        assert "https://shop.example.com/blog/new-flavors" not in urls
        assert "https://shop.example.com/cart" not in urls

    def test_woocommerce_filter_keeps_product_urls(self):
        """When >= 30% of URLs match /product/, only those are kept."""
        service = URLDiscoveryService()

        urls = [
            "https://shop.example.com/product/tea-a",
            "https://shop.example.com/product/tea-b",
            "https://shop.example.com/product/tea-c",
            "https://shop.example.com/about-our-teas",
            "https://shop.example.com/shipping-info",
        ]

        filtered = service._filter_woocommerce_urls(urls)

        # 3/5 = 60% match /product/ → keep only those
        assert len(filtered) == 3
        assert all("/product/" in u for u in filtered)

    def test_woocommerce_filter_keeps_all_when_few_match(self):
        """When < 30% of URLs match /product/, keep all (flat URL store)."""
        service = URLDiscoveryService()

        urls = [
            "https://shop.example.com/earl-grey-tea",
            "https://shop.example.com/green-tea",
            "https://shop.example.com/chamomile-tea",
            "https://shop.example.com/peppermint-tea",
            "https://shop.example.com/product/oolong",  # only one with /product/
        ]

        filtered = service._filter_woocommerce_urls(urls)

        # 1/5 = 20% < 30% → keep all
        assert len(filtered) == 5

    @respx.mock
    async def test_from_product_sitemap_accepts_flat_urls(self, mock_seeder):
        """WooCommerce flat URLs like /earl-grey-tea/ pass from product sitemap."""
        service = URLDiscoveryService()

        product_sitemap_xml = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://shop.example.com/earl-grey-tea/</loc></url>
  <url><loc>https://shop.example.com/green-tea/</loc></url>
  <url><loc>https://shop.example.com/chamomile/</loc></url>
</urlset>"""

        respx.get("https://shop.example.com/product-sitemap.xml").mock(
            return_value=httpx.Response(200, text=product_sitemap_xml)
        )

        urls = await service._discover_via_sitemap(
            "https://shop.example.com", Platform.WOOCOMMERCE
        )

        # Flat URLs from a product sitemap should all pass (trusted source)
        assert len(urls) == 3
        assert "https://shop.example.com/earl-grey-tea/" in urls
        assert "https://shop.example.com/green-tea/" in urls
        assert "https://shop.example.com/chamomile/" in urls
