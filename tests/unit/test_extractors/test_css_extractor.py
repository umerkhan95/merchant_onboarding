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

        assert result == [sample_product_data]
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

        assert result == products
        assert len(result) == 2

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

        assert result == []

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

        assert result == []

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

        assert result == []

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

        assert result == []

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

        assert result == []

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

        assert result == []

    async def test_exception_during_crawl(self, sample_schema):
        """Test handling of exceptions during crawl."""
        extractor = CSSExtractor(sample_schema)

        mock_crawler = AsyncMock()
        mock_crawler.arun.side_effect = RuntimeError("Network error")
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/error")

        assert result == []


class TestCSSExtractorEscalation:
    """Test stealth level escalation logic."""

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

    async def test_extract_returns_products_at_standard(self, schema, sample_products):
        """When _crawl_single returns products at STANDARD, no escalation happens."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.STANDARD)

        with patch.object(extractor, "_crawl_single", new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = sample_products

            result = await extractor.extract("https://example.com/product")

            assert result == sample_products
            # Should only be called once at STANDARD level
            mock_crawl.assert_called_once_with("https://example.com/product", StealthLevel.STANDARD)

    async def test_extract_escalates_to_stealth(self, schema, sample_products):
        """When STANDARD returns [], escalates to STEALTH which returns products."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.STANDARD)

        with patch.object(extractor, "_crawl_single", new_callable=AsyncMock) as mock_crawl:
            # STANDARD returns empty, STEALTH returns products
            mock_crawl.side_effect = [[], sample_products]

            result = await extractor.extract("https://example.com/product")

            assert result == sample_products
            # Should be called twice: STANDARD then STEALTH
            assert mock_crawl.call_count == 2
            calls = mock_crawl.call_args_list
            assert calls[0][0] == ("https://example.com/product", StealthLevel.STANDARD)
            assert calls[1][0] == ("https://example.com/product", StealthLevel.STEALTH)

    async def test_extract_escalates_to_undetected(self, schema, sample_products):
        """When STANDARD and STEALTH return [], escalates to UNDETECTED."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.STANDARD)

        with patch.object(extractor, "_crawl_single", new_callable=AsyncMock) as mock_crawl:
            # STANDARD and STEALTH return empty, UNDETECTED returns products
            mock_crawl.side_effect = [[], [], sample_products]

            result = await extractor.extract("https://example.com/product")

            assert result == sample_products
            # Should be called three times: STANDARD → STEALTH → UNDETECTED
            assert mock_crawl.call_count == 3
            calls = mock_crawl.call_args_list
            assert calls[0][0] == ("https://example.com/product", StealthLevel.STANDARD)
            assert calls[1][0] == ("https://example.com/product", StealthLevel.STEALTH)
            assert calls[2][0] == ("https://example.com/product", StealthLevel.UNDETECTED)

    async def test_extract_returns_empty_after_all_levels(self, schema):
        """When all levels return [], returns []."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.STANDARD)

        with patch.object(extractor, "_crawl_single", new_callable=AsyncMock) as mock_crawl:
            # All levels return empty
            mock_crawl.side_effect = [[], [], []]

            result = await extractor.extract("https://example.com/product")

            assert result == []
            # Should have tried all three levels
            assert mock_crawl.call_count == 3
            calls = mock_crawl.call_args_list
            assert calls[0][0] == ("https://example.com/product", StealthLevel.STANDARD)
            assert calls[1][0] == ("https://example.com/product", StealthLevel.STEALTH)
            assert calls[2][0] == ("https://example.com/product", StealthLevel.UNDETECTED)

    async def test_extract_starts_at_configured_level(self, schema, sample_products):
        """When initialized with STEALTH, skips STANDARD."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.STEALTH)

        with patch.object(extractor, "_crawl_single", new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = sample_products

            result = await extractor.extract("https://example.com/product")

            assert result == sample_products
            # Should only be called once at STEALTH level (skips STANDARD)
            mock_crawl.assert_called_once_with("https://example.com/product", StealthLevel.STEALTH)

    async def test_extract_starts_at_undetected(self, schema, sample_products):
        """When initialized with UNDETECTED, skips STANDARD and STEALTH."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.UNDETECTED)

        with patch.object(extractor, "_crawl_single", new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = sample_products

            result = await extractor.extract("https://example.com/product")

            assert result == sample_products
            # Should only be called once at UNDETECTED level (skips STANDARD and STEALTH)
            mock_crawl.assert_called_once_with("https://example.com/product", StealthLevel.UNDETECTED)

    async def test_extract_escalates_from_stealth_to_undetected(self, schema, sample_products):
        """When initialized with STEALTH and it fails, escalates to UNDETECTED only."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.STEALTH)

        with patch.object(extractor, "_crawl_single", new_callable=AsyncMock) as mock_crawl:
            # STEALTH returns empty, UNDETECTED returns products
            mock_crawl.side_effect = [[], sample_products]

            result = await extractor.extract("https://example.com/product")

            assert result == sample_products
            # Should be called twice: STEALTH then UNDETECTED (skips STANDARD)
            assert mock_crawl.call_count == 2
            calls = mock_crawl.call_args_list
            assert calls[0][0] == ("https://example.com/product", StealthLevel.STEALTH)
            assert calls[1][0] == ("https://example.com/product", StealthLevel.UNDETECTED)

    async def test_extract_undetected_cannot_escalate(self, schema):
        """When initialized with UNDETECTED and it fails, returns empty (no escalation)."""
        extractor = CSSExtractor(schema, stealth_level=StealthLevel.UNDETECTED)

        with patch.object(extractor, "_crawl_single", new_callable=AsyncMock) as mock_crawl:
            # UNDETECTED returns empty
            mock_crawl.return_value = []

            result = await extractor.extract("https://example.com/product")

            assert result == []
            # Should only be called once (no escalation possible)
            mock_crawl.assert_called_once_with("https://example.com/product", StealthLevel.UNDETECTED)

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
        """Extract with empty URL should be passed to _crawl_single."""
        extractor = CSSExtractor(schema)

        with patch.object(extractor, "_crawl_single", new_callable=AsyncMock) as mock_crawl:
            mock_crawl.return_value = []

            result = await extractor.extract("")

            assert result == []
            # Should still attempt the call (URL validation happens in _crawl_single)
            mock_crawl.assert_called()

    async def test_extract_with_none_products(self, schema):
        """When _crawl_single returns None, treats as empty."""
        extractor = CSSExtractor(schema)

        with patch.object(extractor, "_crawl_single", new_callable=AsyncMock) as mock_crawl:
            # Return None instead of empty list
            mock_crawl.side_effect = [None, None, None]

            result = await extractor.extract("https://example.com/product")

            # None is falsy, so escalation continues and returns []
            assert result == []
            assert mock_crawl.call_count == 3

    async def test_extract_stops_at_first_truthy_result(self, schema, sample_product_data):
        """Escalation stops at first truthy result, even if just one product."""
        extractor = CSSExtractor(schema)

        with patch.object(extractor, "_crawl_single", new_callable=AsyncMock) as mock_crawl:
            # STANDARD fails, STEALTH returns single product
            single_product = [sample_product_data]
            mock_crawl.side_effect = [[], single_product]

            result = await extractor.extract("https://example.com/product")

            assert result == single_product
            # Should stop at STEALTH (doesn't try UNDETECTED)
            assert mock_crawl.call_count == 2
