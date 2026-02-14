"""Unit tests for SmartCSSExtractor."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.extractors.smart_css_extractor import SmartCSSExtractor


@pytest.fixture
def mock_llm_config():
    """Mock LLMConfig."""
    config = MagicMock()
    config.provider = "openai/gpt-4o-mini"
    config.api_token = "test-key"
    return config


@pytest.fixture
def mock_schema_cache():
    """Mock SchemaCache."""
    cache = AsyncMock()
    cache.get = AsyncMock(return_value=None)
    cache.set = AsyncMock()
    cache.invalidate = AsyncMock()
    return cache


@pytest.fixture
def valid_schema():
    """A valid generated CSS schema."""
    return {
        "baseSelector": ".product-card",
        "fields": [
            {"name": "title", "selector": ".title", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text"},
        ],
    }


@pytest.fixture
def extractor(mock_llm_config, mock_schema_cache):
    """SmartCSS extractor with mocked dependencies."""
    return SmartCSSExtractor(llm_config=mock_llm_config, schema_cache=mock_schema_cache)


class TestSmartCSSExtractor:
    """Test suite for SmartCSSExtractor."""

    async def test_extract_with_cached_schema(self, extractor, mock_schema_cache, valid_schema):
        """Test extraction using cached schema (no LLM call)."""
        mock_schema_cache.get.return_value = valid_schema
        products = [{"title": "Product 1", "price": "$10.00"}]

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps(products)

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert len(result) == 1
        assert result[0]["title"] == "Product 1"
        # Should NOT have called set (schema was cached)
        mock_schema_cache.set.assert_not_called()

    async def test_extract_generates_and_caches_schema(
        self, extractor, mock_schema_cache, valid_schema
    ):
        """Test that schema is generated and cached when not in cache."""
        mock_schema_cache.get.return_value = None
        products = [{"title": "Product 1", "price": "$10.00"}]

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps(products)

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with (
            patch("app.extractors.smart_css_extractor.httpx.AsyncClient") as mock_httpx,
            patch(
                "app.extractors.smart_css_extractor.JsonCssExtractionStrategy.generate_schema",
                return_value=valid_schema,
            ),
            patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler),
        ):
            # Mock httpx response
            mock_response = MagicMock()
            mock_response.text = "<html><body><div class='product'>Test</div></body></html>"
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_httpx.return_value = mock_client

            result = await extractor.extract("https://example.com/product")

        assert len(result) == 1
        mock_schema_cache.set.assert_called_once()

    async def test_extract_returns_empty_when_schema_generation_fails(
        self, extractor, mock_schema_cache
    ):
        """Test returns empty when schema cannot be generated."""
        mock_schema_cache.get.return_value = None

        with patch("app.extractors.smart_css_extractor.httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.text = "<html></html>"
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_httpx.return_value = mock_client

            with patch(
                "app.extractors.smart_css_extractor.JsonCssExtractionStrategy.generate_schema",
                return_value=None,
            ):
                result = await extractor.extract("https://example.com/product")

        assert result == []

    async def test_extract_returns_empty_on_html_fetch_failure(
        self, extractor, mock_schema_cache
    ):
        """Test returns empty when HTML cannot be fetched."""
        mock_schema_cache.get.return_value = None

        with patch("app.extractors.smart_css_extractor.httpx.AsyncClient") as mock_httpx:
            mock_client = AsyncMock()
            mock_client.get.side_effect = Exception("Connection refused")
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_httpx.return_value = mock_client

            result = await extractor.extract("https://example.com/product")

        assert result == []

    async def test_invalidates_cache_on_zero_results(
        self, extractor, mock_schema_cache, valid_schema
    ):
        """Test that cached schema is invalidated when it produces 0 results."""
        mock_schema_cache.get.return_value = valid_schema

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps([])

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert result == []
        mock_schema_cache.invalidate.assert_called_once()

    async def test_crawl_failure(self, extractor, mock_schema_cache, valid_schema):
        """Test handling of crawl failure."""
        mock_schema_cache.get.return_value = valid_schema

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error_message = "Page load timeout"
        mock_result.extracted_content = None

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/timeout")

        assert result == []

    async def test_no_extracted_content(self, extractor, mock_schema_cache, valid_schema):
        """Test handling when crawl returns no content."""
        mock_schema_cache.get.return_value = valid_schema

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = None

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/empty")

        assert result == []

    async def test_invalid_json_response(self, extractor, mock_schema_cache, valid_schema):
        """Test handling of invalid JSON in crawl result."""
        mock_schema_cache.get.return_value = valid_schema

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = "not valid json"

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/bad-json")

        assert result == []

    async def test_exception_during_crawl(self, extractor, mock_schema_cache, valid_schema):
        """Test handling of exceptions during crawl."""
        mock_schema_cache.get.return_value = valid_schema

        mock_crawler = AsyncMock()
        mock_crawler.arun.side_effect = RuntimeError("Browser crashed")
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/crash")

        assert result == []

    async def test_dict_response_wrapped_in_list(self, extractor, mock_schema_cache, valid_schema):
        """Test dict response is wrapped into a list."""
        mock_schema_cache.get.return_value = valid_schema
        product = {"title": "Single Product", "price": "$15.00"}

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps(product)

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert len(result) == 1
        assert result[0]["title"] == "Single Product"

    async def test_schema_with_invalid_base_selector_rejected(
        self, extractor, mock_schema_cache
    ):
        """Test that invalid schemas (missing baseSelector) cause empty return."""
        mock_schema_cache.get.return_value = None

        with patch("app.extractors.smart_css_extractor.httpx.AsyncClient") as mock_httpx:
            mock_response = MagicMock()
            mock_response.text = "<html></html>"
            mock_response.raise_for_status = MagicMock()

            mock_client = AsyncMock()
            mock_client.get.return_value = mock_response
            mock_client.__aenter__.return_value = mock_client
            mock_client.__aexit__.return_value = None
            mock_httpx.return_value = mock_client

            # generate_schema returns schema without baseSelector
            with patch(
                "app.extractors.smart_css_extractor.JsonCssExtractionStrategy.generate_schema",
                return_value={"fields": [{"name": "title"}]},
            ):
                result = await extractor.extract("https://example.com/product")

        assert result == []
