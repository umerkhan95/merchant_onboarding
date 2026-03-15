"""Unit tests for CSSExtractor."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.extractors.css_extractor import CSSExtractor
from app.extractors.browser_config import StealthLevel


@pytest.fixture
def sample_schema():
    """Sample CSS extraction schema."""
    return {
        "name": "Test Product",
        "baseSelector": ".product",
        "fields": [
            {"name": "title", "selector": ".title", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text"},
        ],
    }


@pytest.fixture
def sample_product_data():
    """Sample product data that would be extracted."""
    return {"title": "Test Product", "price": "$19.99"}


class TestCSSExtractor:
    """Test suite for CSSExtractor."""

    @pytest.fixture(autouse=True)
    def _patch_browser_config(self):
        """Patch get_browser_config and get_crawler_strategy to avoid crawl4ai compat issues."""
        with patch("app.extractors.css_extractor.get_browser_config", return_value=MagicMock()), \
             patch("app.extractors.css_extractor.get_crawler_strategy", return_value=None), \
             patch("app.extractors.css_extractor.get_crawl_config", return_value=MagicMock()):
            yield

    async def test_successful_extraction(self, sample_schema, sample_product_data):
        """Test successful product extraction."""
        extractor = CSSExtractor(sample_schema)

        # Mock the crawler result
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps(sample_product_data)
        mock_result.error_message = None

        # Mock AsyncWebCrawler
        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert result.products == [sample_product_data]
        mock_crawler.arun.assert_called_once()

    async def test_extraction_with_list_response(self, sample_schema):
        """Test extraction when response is a list of products."""
        extractor = CSSExtractor(sample_schema)

        products = [
            {"title": "Product 1", "price": "$10.00"},
            {"title": "Product 2", "price": "$20.00"},
        ]

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps(products)

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/products")

        assert result.products == products
        assert len(result.products) == 2

    async def test_crawl_failure(self, sample_schema):
        """Test handling of crawl failure."""
        extractor = CSSExtractor(sample_schema)

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error_message = "Page not found"
        mock_result.extracted_content = None

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/404")

        assert result.products == []
        assert result.complete is False

    async def test_no_extracted_content(self, sample_schema):
        """Test handling when no content is extracted."""
        extractor = CSSExtractor(sample_schema)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = None

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/empty")

        assert result.products == []
        assert result.complete is False

    async def test_invalid_json_in_extracted_content(self, sample_schema):
        """Test handling of invalid JSON in extracted_content."""
        extractor = CSSExtractor(sample_schema)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = "invalid json {{"

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/bad-json")

        assert result.products == []
        assert result.complete is False

    async def test_empty_dict_response(self, sample_schema):
        """Test handling when extracted data is an empty dict."""
        extractor = CSSExtractor(sample_schema)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps({})

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/empty-dict")

        assert result.products == []
        assert result.complete is False

    async def test_empty_list_response(self, sample_schema):
        """Test handling when extracted data is an empty list."""
        extractor = CSSExtractor(sample_schema)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps([])

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/empty-list")

        assert result.products == []
        assert result.complete is False

    async def test_unexpected_data_type(self, sample_schema):
        """Test handling when extracted data is neither dict nor list."""
        extractor = CSSExtractor(sample_schema)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps("unexpected string")

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/unexpected")

        assert result.products == []
        assert result.complete is False

    async def test_exception_during_crawl(self, sample_schema):
        """Test handling of exceptions during crawl."""
        extractor = CSSExtractor(sample_schema)

        mock_crawler = AsyncMock()
        mock_crawler.arun.side_effect = RuntimeError("Network error")
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/error")

        assert result.products == []
        assert result.complete is False


class TestCSSExtractorEscalation:
    """Test stealth level escalation logic.

    After #154, extract() creates ONE browser and retries with different
    CrawlerRunConfig params. Tests mock at the crawler.arun level and
    track how many calls (escalation steps) happen.
    """

    @pytest.fixture(autouse=True)
    def _patch_browser_config(self):
        """Patch get_browser_config and get_crawler_strategy to avoid crawl4ai compat issues."""
        with patch("app.extractors.css_extractor.get_browser_config", return_value=MagicMock()), \
             patch("app.extractors.css_extractor.get_crawler_strategy", return_value=None), \
             patch("app.extractors.css_extractor.get_crawl_config", return_value=MagicMock()):
            yield

    @pytest.fixture
    def schema(self):
        """Sample CSS extraction schema for escalation tests."""
        return {
            "baseSelector": ".product",
            "fields": [
                {"name": "title", "selector": "h1", "type": "text"},
                {"name": "price", "selector": ".price", "type": "text"},
            ],
        }

    @pytest.fixture
    def sample_products(self):
        """Sample extracted product data."""
        return [
            {"title": "Test Product", "price": "$99.99"},
            {"title": "Another Product", "price": "$149.99"},
        ]

    def _make_result(self, products=None):
        """Create a mock crawl result."""
        result = MagicMock()
        if products:
            result.success = True
            result.extracted_content = json.dumps(products)
            result.error_message = None
        else:
            result.success = True
            result.extracted_content = json.dumps([])
            result.error_message = None
        return result

    def _make_failed_result(self):
        """Create a mock failed crawl result."""
        result = MagicMock()
        result.success = False
        result.extracted_content = None
        result.error_message = "blocked"
        return result

    async def test_extract_returns_products_at_standard(self, schema, sample_products):
        """When first arun returns products, no escalation happens."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.STANDARD)

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = self._make_result(sample_products)
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert result.products == sample_products
        mock_crawler.arun.assert_called_once()

    async def test_extract_escalates_to_stealth(self, schema, sample_products):
        """When STANDARD returns [], escalates to STEALTH which returns products."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.STANDARD)

        mock_crawler = AsyncMock()
        mock_crawler.arun.side_effect = [
            self._make_result(),         # STANDARD: empty
            self._make_result(sample_products),  # STEALTH: products
        ]
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert result.products == sample_products
        assert mock_crawler.arun.call_count == 2

    async def test_extract_escalates_to_undetected(self, schema, sample_products):
        """When STANDARD and STEALTH return [], escalates to UNDETECTED."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.STANDARD)

        mock_crawler = AsyncMock()
        mock_crawler.arun.side_effect = [
            self._make_result(),          # STANDARD: empty
            self._make_result(),          # STEALTH: empty
            self._make_result(sample_products),  # UNDETECTED: products
        ]
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert result.products == sample_products
        assert mock_crawler.arun.call_count == 3

    async def test_extract_returns_empty_after_all_levels(self, schema):
        """When all levels return [], returns []."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.STANDARD)

        mock_crawler = AsyncMock()
        mock_crawler.arun.side_effect = [
            self._make_result(),  # STANDARD: empty
            self._make_result(),  # STEALTH: empty
            self._make_result(),  # UNDETECTED: empty
        ]
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert result.products == []
        assert result.complete is False
        assert mock_crawler.arun.call_count == 3

    async def test_extract_starts_at_configured_level(self, schema, sample_products):
        """When initialized with STEALTH, skips STANDARD (only 2 levels to try)."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.STEALTH)

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = self._make_result(sample_products)
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert result.products == sample_products
        mock_crawler.arun.assert_called_once()

    async def test_extract_starts_at_undetected(self, schema, sample_products):
        """When initialized with UNDETECTED, only 1 level to try."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.UNDETECTED)

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = self._make_result(sample_products)
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert result.products == sample_products
        mock_crawler.arun.assert_called_once()

    async def test_extract_escalates_from_stealth_to_undetected(self, schema, sample_products):
        """When initialized with STEALTH and it fails, escalates to UNDETECTED only."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.STEALTH)

        mock_crawler = AsyncMock()
        mock_crawler.arun.side_effect = [
            self._make_result(),          # STEALTH: empty
            self._make_result(sample_products),  # UNDETECTED: products
        ]
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert result.products == sample_products
        assert mock_crawler.arun.call_count == 2

    async def test_extract_undetected_cannot_escalate(self, schema):
        """When initialized with UNDETECTED and it fails, returns empty (no escalation)."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.UNDETECTED)

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = self._make_result()  # empty
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert result.products == []
        assert result.complete is False
        mock_crawler.arun.assert_called_once()

    def test_escalation_order(self):
        """Verify _ESCALATION_ORDER class constant is correct."""
        assert CSSExtractor._ESCALATION_ORDER == [
            StealthLevel.STANDARD,
            StealthLevel.STEALTH,
            StealthLevel.UNDETECTED,
        ]

    def test_escalation_order_is_complete(self):
        """Verify _ESCALATION_ORDER includes all stealth levels."""
        # Get all stealth levels from the enum
        all_levels = list(StealthLevel)
        escalation_order = CSSExtractor._ESCALATION_ORDER

        # All levels should be in escalation order
        assert set(escalation_order) == set(all_levels)

    def test_escalation_order_is_progressive(self):
        """Verify _ESCALATION_ORDER goes from least to most stealthy."""
        order = CSSExtractor._ESCALATION_ORDER
        assert order[0] == StealthLevel.STANDARD
        assert order[1] == StealthLevel.STEALTH
        assert order[2] == StealthLevel.UNDETECTED


class TestCSSExtractorInitialization:
    """Test CSSExtractor initialization and configuration."""

    def test_init_with_default_stealth_level(self, sample_schema):
        """CSSExtractor defaults to STANDARD stealth level."""
        extractor = CSSExtractor(sample_schema)
        assert extractor.stealth_level == StealthLevel.STANDARD

    def test_init_with_custom_stealth_level(self, sample_schema):
        """CSSExtractor accepts custom stealth level."""
        extractor = CSSExtractor(sample_schema, stealth_level=StealthLevel.STEALTH)
        assert extractor.stealth_level == StealthLevel.STEALTH

    def test_init_stores_schema(self, sample_schema):
        """CSSExtractor stores provided schema."""
        extractor = CSSExtractor(sample_schema)
        assert extractor.schema == sample_schema


class TestCSSExtractorEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.fixture(autouse=True)
    def _patch_browser_config(self):
        """Patch get_browser_config and get_crawler_strategy to avoid crawl4ai compat issues."""
        with patch("app.extractors.css_extractor.get_browser_config", return_value=MagicMock()), \
             patch("app.extractors.css_extractor.get_crawler_strategy", return_value=None), \
             patch("app.extractors.css_extractor.get_crawl_config", return_value=MagicMock()):
            yield

    @pytest.fixture
    def schema(self):
        """Sample CSS extraction schema for edge case tests."""
        return {
            "baseSelector": ".product",
            "fields": [
                {"name": "title", "selector": "h1", "type": "text"},
            ],
        }

    async def test_extract_with_empty_url(self, schema):
        """Extract with empty URL should still attempt crawling."""
        extractor = CSSExtractor(schema)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps([])
        mock_result.error_message = None

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("")

        assert result.products == []
        mock_crawler.arun.assert_called()

    async def test_extract_with_failed_results_exhausts_levels(self, schema):
        """When all arun calls return empty, exhausts all levels."""
        extractor = CSSExtractor(schema)

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps([])
        mock_result.error_message = None

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert result.products == []
        assert result.complete is False
        assert mock_crawler.arun.call_count == 3

    async def test_extract_stops_at_first_truthy_result(self, schema, sample_product_data):
        """Escalation stops at first truthy result, even if just one product."""
        extractor = CSSExtractor(schema)

        empty_result = MagicMock()
        empty_result.success = True
        empty_result.extracted_content = json.dumps([])
        empty_result.error_message = None

        product_result = MagicMock()
        product_result.success = True
        product_result.extracted_content = json.dumps([sample_product_data])
        product_result.error_message = None

        mock_crawler = AsyncMock()
        mock_crawler.arun.side_effect = [empty_result, product_result]
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert result.products == [sample_product_data]
        # Should stop at STEALTH (doesn't try UNDETECTED)
        assert mock_crawler.arun.call_count == 2
