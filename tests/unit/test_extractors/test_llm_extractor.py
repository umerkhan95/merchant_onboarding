"""Unit tests for LLMExtractor."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.extractors.llm_extractor import LLMExtractor


@pytest.fixture
def mock_llm_config():
    """Mock LLMConfig."""
    config = MagicMock()
    config.provider = "openai/gpt-4o-mini"
    config.api_token = "test-key"
    return config


@pytest.fixture
def extractor(mock_llm_config):
    """LLM extractor with mocked config."""
    return LLMExtractor(llm_config=mock_llm_config)


class TestLLMExtractor:
    """Test suite for LLMExtractor."""

    async def test_successful_extraction_single_product(self, extractor):
        """Test extracting a single product."""
        product = {"title": "Test Product", "price": "$29.99", "in_stock": True}

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps([product])

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.llm_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert len(result) == 1
        assert result[0]["title"] == "Test Product"

    async def test_successful_extraction_multiple_products(self, extractor):
        """Test extracting multiple products."""
        products = [
            {"title": "Product 1", "price": "$10.00"},
            {"title": "Product 2", "price": "$20.00"},
            {"title": "Product 3", "price": "$30.00"},
        ]

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps(products)

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.llm_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/products")

        assert len(result) == 3

    async def test_filters_products_without_title(self, extractor):
        """Test that products without title field are filtered out."""
        products = [
            {"title": "Valid Product", "price": "$10.00"},
            {"price": "$20.00"},  # No title
            {"title": "", "price": "$30.00"},  # Empty title passes (falsy but present)
        ]

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps(products)

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.llm_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/products")

        # Only products with "title" key are kept
        assert len(result) == 1
        assert result[0]["title"] == "Valid Product"

    async def test_dict_response_with_title(self, extractor):
        """Test handling of single dict response (not in array)."""
        product = {"title": "Single Product", "price": "$29.99"}

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps(product)

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.llm_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert len(result) == 1
        assert result[0]["title"] == "Single Product"

    async def test_dict_response_without_title(self, extractor):
        """Test dict response without title returns empty."""
        product = {"price": "$29.99", "description": "No title"}

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps(product)

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.llm_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert result == []

    async def test_crawl_failure(self, extractor):
        """Test handling of crawl failure."""
        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error_message = "Page load timeout"
        mock_result.extracted_content = None

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.llm_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/404")

        assert result == []

    async def test_no_extracted_content(self, extractor):
        """Test handling when no content is extracted."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = None

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.llm_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/empty")

        assert result == []

    async def test_invalid_json_response(self, extractor):
        """Test handling of invalid JSON in response."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = "not valid json {{"

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.llm_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/bad-json")

        assert result == []

    async def test_unexpected_data_type(self, extractor):
        """Test handling of unexpected data type (not dict or list)."""
        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps("just a string")

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.llm_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/unexpected")

        assert result == []

    async def test_exception_during_crawl(self, extractor):
        """Test handling of exceptions during crawl."""
        mock_crawler = AsyncMock()
        mock_crawler.arun.side_effect = RuntimeError("Network error")
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.llm_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/error")

        assert result == []

    async def test_custom_temperature_and_max_tokens(self, mock_llm_config):
        """Test that custom temperature and max_tokens are passed through."""
        extractor = LLMExtractor(
            llm_config=mock_llm_config,
            temperature=0.5,
            max_tokens=8000,
        )

        assert extractor.temperature == 0.5
        assert extractor.max_tokens == 8000

    async def test_filters_non_dict_items_in_list(self, extractor):
        """Test that non-dict items in list response are filtered."""
        mixed = [
            {"title": "Valid", "price": "$10"},
            "not a dict",
            42,
            None,
            {"title": "Also Valid", "price": "$20"},
        ]

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps(mixed)

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.llm_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/mixed")

        assert len(result) == 2
        assert result[0]["title"] == "Valid"
        assert result[1]["title"] == "Also Valid"

    def test_markdown_generator_no_pruning_filter(self, extractor):
        """Test that markdown generator does NOT use PruningContentFilter.

        PruningContentFilter aggressively strips product content, producing
        empty fit_markdown on most e-commerce sites. Regular markdown with
        chunking is more reliable for LLM extraction.
        """
        markdown_gen = extractor._create_markdown_generator()
        assert markdown_gen.content_filter is None


class TestMergeChunkProducts:
    """Tests for _merge_chunk_products — merging partial products from chunks."""

    def test_single_product_unchanged(self):
        """Single product list passes through unchanged."""
        products = [{"title": "Shoes", "price": "$100"}]
        result = LLMExtractor._merge_chunk_products(products)
        assert result == products

    def test_empty_list(self):
        """Empty list returns empty."""
        assert LLMExtractor._merge_chunk_products([]) == []

    def test_merges_exact_title_match(self):
        """Products with identical titles are merged."""
        products = [
            {"title": "Men's Tree Runners", "price": "$100"},
            {"title": "Men's Tree Runners", "description": "Lightweight shoes", "image_url": "https://img.jpg"},
        ]
        result = LLMExtractor._merge_chunk_products(products)
        assert len(result) == 1
        assert result[0]["title"] == "Men's Tree Runners"
        assert result[0]["price"] == "$100"
        assert result[0]["description"] == "Lightweight shoes"
        assert result[0]["image_url"] == "https://img.jpg"

    def test_merges_prefix_titles(self):
        """Product with title that is a prefix of another gets merged."""
        products = [
            {"title": "Men's Tree Runners", "price": "$100"},
            {"title": "Men's Tree Runners - Allbirds Edition", "vendor": "Allbirds"},
        ]
        result = LLMExtractor._merge_chunk_products(products)
        assert len(result) == 1
        assert result[0]["price"] == "$100"
        assert result[0]["vendor"] == "Allbirds"

    def test_merges_similar_titles(self):
        """Products with >0.7 SequenceMatcher ratio are merged."""
        products = [
            {"title": "Men's Tree Runners", "price": "$100"},
            {"title": "Mens Tree Runner", "currency": "USD"},
        ]
        result = LLMExtractor._merge_chunk_products(products)
        assert len(result) == 1
        assert result[0]["price"] == "$100"
        assert result[0]["currency"] == "USD"

    def test_does_not_merge_different_products(self):
        """Products with different titles stay separate."""
        products = [
            {"title": "Men's Tree Runners", "price": "$100"},
            {"title": "Women's Wool Loungers", "price": "$120"},
        ]
        result = LLMExtractor._merge_chunk_products(products)
        assert len(result) == 2

    def test_first_value_wins(self):
        """When both chunks have a field, the first value is kept."""
        products = [
            {"title": "Shoes", "price": "$100", "vendor": "Allbirds"},
            {"title": "Shoes", "price": "$95", "vendor": ""},
        ]
        result = LLMExtractor._merge_chunk_products(products)
        assert len(result) == 1
        assert result[0]["price"] == "$100"
        assert result[0]["vendor"] == "Allbirds"

    def test_merges_three_chunks(self):
        """Three chunks of the same product merge into one."""
        products = [
            {"title": "Headphones", "price": "$299"},
            {"title": "Headphones", "description": "Noise cancelling"},
            {"title": "Headphones", "vendor": "Sony", "in_stock": True},
        ]
        result = LLMExtractor._merge_chunk_products(products)
        assert len(result) == 1
        assert result[0]["price"] == "$299"
        assert result[0]["description"] == "Noise cancelling"
        assert result[0]["vendor"] == "Sony"
        assert result[0]["in_stock"] is True

    async def test_extract_merges_chunk_duplicates(self, extractor):
        """Full extract() call merges chunk duplicates."""
        # Simulate chunking producing 3 partial products from one page
        chunk_products = [
            {"title": "Test Product", "price": "$50"},
            {"title": "Test Product", "description": "Great product", "vendor": "TestBrand"},
            {"title": "Test Product", "image_url": "https://img.jpg"},
        ]

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.extracted_content = json.dumps(chunk_products)

        mock_crawler = AsyncMock()
        mock_crawler.arun.return_value = mock_result
        mock_crawler.__aenter__.return_value = mock_crawler
        mock_crawler.__aexit__.return_value = None

        with patch("app.extractors.llm_extractor.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract("https://example.com/product")

        assert len(result) == 1
        assert result[0]["title"] == "Test Product"
        assert result[0]["price"] == "$50"
        assert result[0]["description"] == "Great product"
        assert result[0]["vendor"] == "TestBrand"
        assert result[0]["image_url"] == "https://img.jpg"
