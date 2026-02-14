"""Unit tests for CSSExtractor."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.extractors.css_extractor import CSSExtractor


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
