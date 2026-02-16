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


def _make_mock_crawler(arun_return=None, arun_side_effect=None):
    """Create a mock AsyncWebCrawler context manager."""
    mock_crawler = AsyncMock()
    if arun_side_effect is not None:
        mock_crawler.arun.side_effect = arun_side_effect
    else:
        mock_crawler.arun.return_value = arun_return
    mock_crawler.__aenter__.return_value = mock_crawler
    mock_crawler.__aexit__.return_value = None
    return mock_crawler


def _make_crawl_result(success=True, html=None, extracted_content=None, error_message=None):
    """Create a mock CrawlResult."""
    result = MagicMock()
    result.success = success
    result.html = html
    result.extracted_content = extracted_content
    result.error_message = error_message
    return result


class TestSmartCSSExtractor:
    """Test suite for SmartCSSExtractor."""

    async def test_extract_with_cached_schema(self, extractor, mock_schema_cache, valid_schema):
        """Test extraction using cached schema (no LLM call)."""
        mock_schema_cache.get.return_value = valid_schema
        products = [{"title": "Product 1", "price": "$10.00"}]

        mock_crawler = _make_mock_crawler(
            arun_return=_make_crawl_result(extracted_content=json.dumps(products)),
        )

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

        # The crawler is used twice: once for _fetch_html, once for extract.
        # Both calls go through the same mock, so set up side_effect.
        fetch_result = _make_crawl_result(
            html="<html><body><div class='product'>Test</div></body></html>",
        )
        extract_result = _make_crawl_result(
            extracted_content=json.dumps(products),
        )

        mock_crawler = AsyncMock()
        mock_crawler.arun.side_effect = [fetch_result, extract_result]
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with (
            patch(
                "app.extractors.smart_css_extractor.JsonCssExtractionStrategy.generate_schema",
                return_value=valid_schema,
            ),
            patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler),
        ):
            result = await extractor.extract("https://example.com/product")

        assert len(result) == 1
        mock_schema_cache.set.assert_called_once()

    async def test_extract_returns_empty_when_schema_generation_fails(
        self, extractor, mock_schema_cache
    ):
        """Test returns empty when schema cannot be generated."""
        mock_schema_cache.get.return_value = None

        fetch_result = _make_crawl_result(html="<html></html>")
        mock_crawler = _make_mock_crawler(arun_return=fetch_result)

        with (
            patch(
                "app.extractors.smart_css_extractor.JsonCssExtractionStrategy.generate_schema",
                return_value=None,
            ),
            patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler),
        ):
            result = await extractor.extract("https://example.com/product")

        assert result == []

    async def test_extract_returns_empty_on_html_fetch_failure(
        self, extractor, mock_schema_cache
    ):
        """Test returns empty when HTML cannot be fetched."""
        mock_schema_cache.get.return_value = None

        fetch_result = _make_crawl_result(success=False, error_message="Connection refused")
        mock_crawler = _make_mock_crawler(arun_return=fetch_result)

        with patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert result == []

    async def test_invalidates_cache_on_zero_results(
        self, extractor, mock_schema_cache, valid_schema
    ):
        """Test that cached schema is invalidated when it produces 0 results."""
        mock_schema_cache.get.return_value = valid_schema

        mock_crawler = _make_mock_crawler(
            arun_return=_make_crawl_result(extracted_content=json.dumps([])),
        )

        with patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert result == []
        mock_schema_cache.invalidate.assert_called_once()

    async def test_crawl_failure(self, extractor, mock_schema_cache, valid_schema):
        """Test handling of crawl failure."""
        mock_schema_cache.get.return_value = valid_schema

        mock_crawler = _make_mock_crawler(
            arun_return=_make_crawl_result(success=False, error_message="Page load timeout"),
        )

        with patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/timeout")

        assert result == []

    async def test_no_extracted_content(self, extractor, mock_schema_cache, valid_schema):
        """Test handling when crawl returns no content."""
        mock_schema_cache.get.return_value = valid_schema

        mock_crawler = _make_mock_crawler(
            arun_return=_make_crawl_result(extracted_content=None),
        )

        with patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/empty")

        assert result == []

    async def test_invalid_json_response(self, extractor, mock_schema_cache, valid_schema):
        """Test handling of invalid JSON in crawl result."""
        mock_schema_cache.get.return_value = valid_schema

        mock_crawler = _make_mock_crawler(
            arun_return=_make_crawl_result(extracted_content="not valid json"),
        )

        with patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/bad-json")

        assert result == []

    async def test_exception_during_crawl(self, extractor, mock_schema_cache, valid_schema):
        """Test handling of exceptions during crawl."""
        mock_schema_cache.get.return_value = valid_schema

        mock_crawler = _make_mock_crawler(arun_side_effect=RuntimeError("Browser crashed"))

        with patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/crash")

        assert result == []

    async def test_dict_response_wrapped_in_list(self, extractor, mock_schema_cache, valid_schema):
        """Test dict response is wrapped into a list."""
        mock_schema_cache.get.return_value = valid_schema
        product = {"title": "Single Product", "price": "$15.00"}

        mock_crawler = _make_mock_crawler(
            arun_return=_make_crawl_result(extracted_content=json.dumps(product)),
        )

        with patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert len(result) == 1
        assert result[0]["title"] == "Single Product"

    async def test_schema_with_invalid_base_selector_rejected(
        self, extractor, mock_schema_cache
    ):
        """Test that invalid schemas (missing baseSelector) cause empty return."""
        mock_schema_cache.get.return_value = None

        fetch_result = _make_crawl_result(html="<html></html>")
        mock_crawler = _make_mock_crawler(arun_return=fetch_result)

        with (
            patch(
                "app.extractors.smart_css_extractor.JsonCssExtractionStrategy.generate_schema",
                return_value={"fields": [{"name": "title"}]},
            ),
            patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler),
        ):
            result = await extractor.extract("https://example.com/product")

        assert result == []

    def test_score_selector_robustness_attribute_selectors(self):
        """Test robustness scoring favors attribute selectors."""
        schema = {
            "baseSelector": "[data-product]",
            "fields": [
                {"selector": "[itemprop='name']"},
                {"selector": "[data-price]"},
            ],
        }
        score = SmartCSSExtractor._score_selector_robustness(schema)
        assert score == 1.0

    def test_score_selector_robustness_class_selectors(self):
        """Test robustness scoring for class selectors."""
        schema = {
            "baseSelector": ".product-card",
            "fields": [
                {"selector": ".title"},
                {"selector": ".price"},
            ],
        }
        score = SmartCSSExtractor._score_selector_robustness(schema)
        assert abs(score - 0.8) < 0.01

    def test_score_selector_robustness_nth_child_penalty(self):
        """Test robustness scoring penalizes nth-child selectors."""
        schema = {
            "baseSelector": "div:nth-child(2)",
            "fields": [
                {"selector": "span:nth-child(1)"},
                {"selector": "span:nth-child(3)"},
            ],
        }
        score = SmartCSSExtractor._score_selector_robustness(schema)
        assert abs(score - 0.2) < 0.01

    def test_score_selector_robustness_mixed(self):
        """Test robustness scoring with mixed selector types."""
        schema = {
            "baseSelector": ".product",  # 0.8
            "fields": [
                {"selector": "[data-title]"},  # 1.0
                {"selector": ".price"},  # 0.8
                {"selector": "h1"},  # 0.5
            ],
        }
        score = SmartCSSExtractor._score_selector_robustness(schema)
        expected = (0.8 + 1.0 + 0.8 + 0.5) / 4
        assert abs(score - expected) < 0.01

    async def test_validate_schema_success(self, extractor):
        """Test schema validation passes when selectors match all samples."""
        schema = {
            "baseSelector": ".product",
            "fields": [
                {"selector": ".title", "type": "text"},
                {"selector": ".price", "type": "text"},
            ],
        }
        sample_htmls = [
            '<div class="product"><h1 class="title">Product 1</h1><span class="price">$10</span></div>',
            '<div class="product"><h1 class="title">Product 2</h1><span class="price">$20</span></div>',
        ]

        result = await extractor._validate_schema(schema, sample_htmls)
        assert result is True

    async def test_validate_schema_fails_missing_base_selector(self, extractor):
        """Test schema validation fails when baseSelector matches nothing."""
        schema = {
            "baseSelector": ".nonexistent",
            "fields": [{"selector": ".title", "type": "text"}],
        }
        sample_htmls = ['<div class="product"><h1 class="title">Product 1</h1></div>']

        result = await extractor._validate_schema(schema, sample_htmls)
        assert result is False

    async def test_validate_schema_fails_missing_field_data(self, extractor):
        """Test schema validation fails when no field data can be extracted."""
        schema = {
            "baseSelector": ".product",
            "fields": [{"selector": ".missing", "type": "text"}],
        }
        sample_htmls = ['<div class="product"><h1 class="title">Product 1</h1></div>']

        result = await extractor._validate_schema(schema, sample_htmls)
        assert result is False

    async def test_validate_schema_fails_on_one_sample(self, extractor):
        """Test schema validation fails if it works on some samples but not all."""
        schema = {
            "baseSelector": ".product",
            "fields": [{"selector": ".title", "type": "text"}],
        }
        sample_htmls = [
            '<div class="product"><h1 class="title">Product 1</h1></div>',
            '<div class="item"><h1 class="heading">Product 2</h1></div>',  # Different structure
        ]

        result = await extractor._validate_schema(schema, sample_htmls)
        assert result is False

    async def test_extract_batch_with_multi_sample_validation(
        self, extractor, mock_schema_cache
    ):
        """Test extract_batch uses multi-sample validation when generating schema."""
        mock_schema_cache.get.return_value = None
        urls = [
            "https://example.com/product1",
            "https://example.com/product2",
            "https://example.com/product3",
        ]

        # Schema that matches the HTML samples
        schema = {
            "baseSelector": ".product-card",
            "fields": [
                {"selector": ".title", "type": "text"},
                {"selector": ".price", "type": "text"},
            ],
        }

        # Mock HTML fetches for schema generation - must match schema selectors
        html_samples = [
            '<div class="product-card"><h1 class="title">Product 1</h1><span class="price">$10</span></div>',
            '<div class="product-card"><h1 class="title">Product 2</h1><span class="price">$20</span></div>',
            '<div class="product-card"><h1 class="title">Product 3</h1><span class="price">$30</span></div>',
        ]

        mock_crawler = AsyncMock()
        # Fetch calls for schema generation (3 samples)
        fetch_results = [_make_crawl_result(html=html) for html in html_samples]
        # arun_many call for batch extraction
        batch_results = [
            _make_crawl_result(extracted_content=json.dumps({"title": f"Product {i}", "price": f"${i*10}"}))
            for i in range(1, 4)
        ]

        mock_crawler.arun.side_effect = fetch_results
        mock_crawler.arun_many.return_value = batch_results
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with (
            patch(
                "app.extractors.smart_css_extractor.JsonCssExtractionStrategy.generate_schema",
                return_value=schema,
            ),
            patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler),
        ):
            result = await extractor.extract_batch(urls)

        # Should have validated schema and cached it
        mock_schema_cache.set.assert_called_once()
        assert len(result) == 3

    async def test_low_robustness_schema_rejected(self, extractor, mock_schema_cache):
        """Test that schemas with very low robustness scores (< 0.3) are rejected."""
        mock_schema_cache.get.return_value = None

        # Schema with brittle nth-child selectors (scores 0.2 - below threshold)
        brittle_schema = {
            "baseSelector": "div:nth-child(2)",
            "fields": [
                {"selector": "span:nth-child(1)", "type": "text"},
                {"selector": "span:nth-child(3)", "type": "text"},
            ],
        }

        fetch_result = _make_crawl_result(html="<html><body><div>Test</div></body></html>")
        mock_crawler = _make_mock_crawler(arun_return=fetch_result)

        with (
            patch(
                "app.extractors.smart_css_extractor.JsonCssExtractionStrategy.generate_schema",
                return_value=brittle_schema,
            ),
            patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler),
        ):
            result = await extractor.extract("https://example.com/product")

        # Should reject brittle schema with score < 0.3
        assert result == []
        # Should NOT cache brittle schema
        mock_schema_cache.set.assert_not_called()

    async def test_moderate_robustness_schema_accepted(self, extractor, mock_schema_cache):
        """Test that schemas with moderate robustness scores (0.3-0.5) are accepted."""
        mock_schema_cache.get.return_value = None

        # Schema with tag-based selectors (scores 0.5 - moderate but acceptable)
        moderate_schema = {
            "baseSelector": "div",
            "fields": [
                {"selector": "h1", "type": "text"},
                {"selector": "span", "type": "text"},
            ],
        }

        products = [{"title": "Product 1", "price": "$10.00"}]

        fetch_result = _make_crawl_result(html="<html><body><div><h1>Test</h1></div></body></html>")
        extract_result = _make_crawl_result(extracted_content=json.dumps(products))

        mock_crawler = AsyncMock()
        mock_crawler.arun.side_effect = [fetch_result, extract_result]
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with (
            patch(
                "app.extractors.smart_css_extractor.JsonCssExtractionStrategy.generate_schema",
                return_value=moderate_schema,
            ),
            patch("app.extractors.smart_css_extractor.AsyncWebCrawler", return_value=mock_crawler),
        ):
            result = await extractor.extract("https://example.com/product")

        # Should accept moderate schema (0.5 >= 0.3 threshold)
        assert len(result) == 1
        assert result[0]["title"] == "Product 1"
        # Should cache the schema
        mock_schema_cache.set.assert_called_once()

    async def test_html_truncation_avoids_mid_tag_cut(self, extractor):
        """Test that HTML truncation doesn't cut mid-tag."""
        # Create HTML that's exactly at the limit with a tag at the boundary
        html = "<div class='product'>" + "x" * 150_000 + "<span>Test</span></div>"

        # Manually call _generate_schema to test truncation logic
        with patch.object(extractor, "_extract_product_region", return_value=html):
            with patch(
                "app.extractors.smart_css_extractor.JsonCssExtractionStrategy.generate_schema",
            ) as mock_generate:
                mock_generate.return_value = {
                    "baseSelector": ".product",
                    "fields": [{"selector": ".title", "type": "text"}],
                }
                await extractor._generate_schema(html)

                # Verify that generate_schema was called with truncated HTML
                called_html = mock_generate.call_args[1]["html"]
                # Should be truncated to <= 150k
                assert len(called_html) <= 150_000
                # Should not end mid-tag (should end with '>') unless the entire HTML is smaller
                if len(html) > 150_000:
                    assert called_html.endswith(">"), "HTML truncation should end at a tag boundary"

    def test_max_schema_html_bytes_constant(self):
        """Test that _MAX_SCHEMA_HTML_BYTES is set to 150KB."""
        assert SmartCSSExtractor._MAX_SCHEMA_HTML_BYTES == 150_000
