"""Tests for UnifiedCrawlExtractor."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.extractors.unified_crawl_extractor import (
    UnifiedCrawlExtractor,
    _deduplicate_products,
    _extract_best_image,
    _fill_gaps_from_markdown,
    _fill_gaps_from_og,
    _get_price,
    _has_product_signal,
    _merge_og,
)


# ── Fake CrawlResult for testing ──────────────────────────────────────


@dataclass
class FakeMarkdownResult:
    """Mimics crawl4ai MarkdownGenerationResult (>=0.6)."""

    raw_markdown: str = ""
    fit_markdown: str = ""


@dataclass
class FakeCrawlResult:
    """Mimics crawl4ai CrawlResult for unit tests.

    markdown can be a plain string (old crawl4ai) or a FakeMarkdownResult
    object (new crawl4ai >=0.6) to test both code paths.
    """

    success: bool = True
    url: str = "https://example.com/product"
    html: str = ""
    markdown: str | FakeMarkdownResult = ""
    metadata: dict = field(default_factory=dict)
    media: dict = field(default_factory=dict)
    error_message: str = ""


# ── Helper function tests ──────────────────────────────────────────────


class TestGetPrice:
    def test_direct_price(self):
        assert _get_price({"price": "49.99"}) == "49.99"

    def test_offers_dict(self):
        assert _get_price({"offers": {"price": "29.99"}}) == "29.99"

    def test_offers_list(self):
        assert _get_price({"offers": [{"price": "19.99"}]}) == "19.99"

    def test_og_price(self):
        assert _get_price({"og:price:amount": "39.99"}) == "39.99"

    def test_product_price(self):
        assert _get_price({"product:price:amount": "59.99"}) == "59.99"

    def test_zero_price_is_none(self):
        assert _get_price({"price": "0"}) is None

    def test_empty_price_is_none(self):
        assert _get_price({"price": ""}) is None

    def test_no_price(self):
        assert _get_price({"name": "Product"}) is None


class TestFillGapsFromOg:
    def test_fills_missing_title(self):
        product = {"name": ""}
        _fill_gaps_from_og(product, {"og:title": "OG Title"})
        assert product.get("name") == "OG Title"

    def test_no_overwrite(self):
        product = {"name": "Existing"}
        _fill_gaps_from_og(product, {"og:title": "OG Title"})
        assert product["name"] == "Existing"

    def test_fills_image(self):
        product = {}
        _fill_gaps_from_og(product, {"og:image": "https://img.jpg"})
        assert product.get("og:image") == "https://img.jpg"

    def test_fills_price(self):
        product = {}
        _fill_gaps_from_og(product, {"og:price:amount": "49.99"})
        assert product.get("og:price:amount") == "49.99"


class TestFillGapsFromMarkdown:
    def test_fills_price(self):
        product = {}
        _fill_gaps_from_markdown(product, {"price": "29.99", "currency": "USD"})
        assert product["price"] == "29.99"
        assert product["priceCurrency"] == "USD"

    def test_no_overwrite_existing_price(self):
        product = {"price": "19.99"}
        _fill_gaps_from_markdown(product, {"price": "29.99"})
        assert product["price"] == "19.99"

    def test_fills_name(self):
        product = {}
        _fill_gaps_from_markdown(product, {"name": "Coffee Beans"})
        assert product["name"] == "Coffee Beans"

    def test_no_overwrite_og_title(self):
        product = {"og:title": "OG Name"}
        _fill_gaps_from_markdown(product, {"name": "MD Name"})
        assert "name" not in product


class TestExtractBestImage:
    def test_picks_highest_score(self):
        media = {"images": [
            {"src": "low.jpg", "score": 2},
            {"src": "high.jpg", "score": 8},
            {"src": "mid.jpg", "score": 5},
        ]}
        assert _extract_best_image(media) == "high.jpg"

    def test_returns_first_if_no_high_score(self):
        media = {"images": [
            {"src": "only.jpg", "score": 1},
        ]}
        assert _extract_best_image(media) == "only.jpg"

    def test_empty_media(self):
        assert _extract_best_image({}) is None
        assert _extract_best_image({"images": []}) is None

    def test_list_format(self):
        media = [{"src": "img.jpg", "score": 5}]
        assert _extract_best_image(media) == "img.jpg"

    def test_skips_no_src(self):
        media = {"images": [{"score": 10}, {"src": "valid.jpg", "score": 3}]}
        assert _extract_best_image(media) == "valid.jpg"


class TestMergeOg:
    def test_meta_only(self):
        result = _merge_og([{"og:title": "T"}], [])
        assert result == {"og:title": "T"}

    def test_html_only(self):
        result = _merge_og([], [{"product:price:amount": "9.99"}])
        assert result == {"product:price:amount": "9.99"}

    def test_html_fills_gaps(self):
        result = _merge_og(
            [{"og:title": "T"}],
            [{"og:title": "Other", "product:price:amount": "19.99"}],
        )
        assert result["og:title"] == "T"
        assert result["product:price:amount"] == "19.99"


# ── CrawlResult extraction tests ──────────────────────────────────────


class TestExtractFromCrawlResult:
    """Test the static _extract_from_crawl_result method."""

    def test_jsonld_primary(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "name": "Coffee", "offers": {"price": "24.99"}, "image": "coffee.jpg"}
        </script>
        </head><body></body></html>
        """
        result = FakeCrawlResult(html=html, url="https://shop.com/coffee")
        products = UnifiedCrawlExtractor._extract_from_crawl_result(result, result.url)
        assert len(products) == 1
        assert products[0]["name"] == "Coffee"

    def test_og_fallback_when_no_jsonld(self):
        html = """
        <html><head>
        <meta property="og:title" content="Tea Set" />
        <meta property="og:image" content="tea.jpg" />
        <meta property="product:price:amount" content="39.99" />
        </head><body></body></html>
        """
        result = FakeCrawlResult(html=html, url="https://shop.com/tea")
        products = UnifiedCrawlExtractor._extract_from_crawl_result(result, result.url)
        assert len(products) == 1
        assert products[0].get("og:title") == "Tea Set"

    def test_markdown_fills_missing_price(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "name": "Widget", "image": "widget.jpg"}
        </script>
        </head><body></body></html>
        """
        result = FakeCrawlResult(
            html=html,
            markdown="# Widget\n\n$49.99\n\nGreat widget.",
            url="https://shop.com/widget",
        )
        products = UnifiedCrawlExtractor._extract_from_crawl_result(result, result.url)
        assert len(products) == 1
        assert products[0].get("price") == "49.99"

    def test_media_fills_missing_image(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "name": "Gadget", "offers": {"price": "99.00"}}
        </script>
        </head><body></body></html>
        """
        result = FakeCrawlResult(
            html=html,
            media={"images": [{"src": "https://cdn.com/gadget.jpg", "score": 7}]},
            url="https://shop.com/gadget",
        )
        products = UnifiedCrawlExtractor._extract_from_crawl_result(result, result.url)
        assert len(products) == 1
        assert products[0].get("og:image") == "https://cdn.com/gadget.jpg"

    def test_markdown_only_fallback(self):
        """When no structured data exists, markdown price + title still works."""
        result = FakeCrawlResult(
            html="<html><body><h1>Candle</h1><p>$14.99</p></body></html>",
            markdown="# Candle\n\n$14.99\n\nHandmade soy candle.",
            media={"images": [{"src": "candle.jpg", "score": 5}]},
            url="https://shop.com/candle",
        )
        products = UnifiedCrawlExtractor._extract_from_crawl_result(result, result.url)
        assert len(products) == 1
        assert products[0].get("name") == "Candle"
        assert products[0].get("price") == "14.99"

    def test_fit_markdown_preferred(self):
        """fit_markdown from MarkdownGenerationResult object is preferred."""
        result = FakeCrawlResult(
            html="<html><body></body></html>",
            markdown=FakeMarkdownResult(
                raw_markdown="Nav junk\n\n# Product\n\n$9.99",
                fit_markdown="# Product\n\n$9.99",
            ),
            url="https://shop.com/p",
        )
        products = UnifiedCrawlExtractor._extract_from_crawl_result(result, result.url)
        assert len(products) == 1

    def test_empty_result(self):
        result = FakeCrawlResult(html="<html><body>404</body></html>")
        products = UnifiedCrawlExtractor._extract_from_crawl_result(result, result.url)
        assert products == []

    def test_og_metadata_enriches_jsonld(self):
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "name": "Mug", "offers": {"price": "12.00"}}
        </script>
        </head><body></body></html>
        """
        result = FakeCrawlResult(
            html=html,
            metadata={"og:image": "https://cdn.com/mug.jpg"},
            url="https://shop.com/mug",
        )
        products = UnifiedCrawlExtractor._extract_from_crawl_result(result, result.url)
        assert len(products) == 1
        assert products[0].get("og:image") == "https://cdn.com/mug.jpg"

    def test_european_price_from_markdown(self):
        result = FakeCrawlResult(
            html="<html><body></body></html>",
            markdown="# Espresso Machine\n\n€1.299,90",
            url="https://shop.de/espresso",
        )
        products = UnifiedCrawlExtractor._extract_from_crawl_result(result, result.url)
        assert len(products) == 1
        assert products[0].get("price") == "1299.90"
        assert products[0].get("priceCurrency") == "EUR"

    def test_graph_jsonld_with_nested_product(self):
        """Yoast SEO pattern: @graph with WebPage wrapping mainEntity Product."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@graph": [
            {"@type": "WebPage", "mainEntity": {"@type": "Product", "name": "Shoes", "offers": {"price": "89.00"}, "image": "shoes.jpg"}}
        ]}
        </script>
        </head><body></body></html>
        """
        result = FakeCrawlResult(html=html, url="https://shop.com/shoes")
        products = UnifiedCrawlExtractor._extract_from_crawl_result(result, result.url)
        assert len(products) == 1
        assert products[0]["name"] == "Shoes"


# ── Deduplication tests ───────────────────────────────────────────────


class TestDeduplicateProducts:
    """Test _deduplicate_products()."""

    def test_no_duplicates(self):
        products = [
            {"name": "Product A", "offers": {"price": "10.00"}},
            {"name": "Product B", "offers": {"price": "20.00"}},
        ]
        result = _deduplicate_products(products)
        assert len(result) == 2

    def test_exact_duplicates_removed(self):
        products = [
            {"name": "Coffee Mug", "offers": {"price": "14.99"}, "image": "mug.jpg"},
            {"name": "Coffee Mug", "offers": {"price": "14.99"}},
        ]
        result = _deduplicate_products(products)
        assert len(result) == 1
        assert result[0].get("image") == "mug.jpg"

    def test_keeps_more_complete_record(self):
        sparse = {"name": "Widget", "offers": {"price": "9.99"}}
        complete = {"name": "Widget", "offers": {"price": "9.99"}, "image": "w.jpg", "brand": "Acme"}
        result = _deduplicate_products([sparse, complete])
        assert len(result) == 1
        assert result[0].get("brand") == "Acme"

    def test_different_prices_not_deduped(self):
        products = [
            {"name": "Shirt", "offers": {"price": "29.99"}},
            {"name": "Shirt", "offers": {"price": "39.99"}},
        ]
        result = _deduplicate_products(products)
        assert len(result) == 2

    def test_single_product_passthrough(self):
        products = [{"name": "Solo", "offers": {"price": "5.00"}}]
        result = _deduplicate_products(products)
        assert len(result) == 1

    def test_empty_list(self):
        assert _deduplicate_products([]) == []

    def test_graph_plus_standalone_dedup(self):
        """Simulates @graph + standalone JSON-LD producing the same product."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@graph": [{"@type": "Product", "name": "Mug", "offers": {"price": "12.00"}, "image": "mug.jpg"}]}
        </script>
        <script type="application/ld+json">
        {"@type": "Product", "name": "Mug", "offers": {"price": "12.00"}}
        </script>
        </head><body></body></html>
        """
        result = FakeCrawlResult(html=html, url="https://shop.com/mug")
        products = UnifiedCrawlExtractor._extract_from_crawl_result(result, result.url)
        assert len(products) == 1
        assert products[0]["name"] == "Mug"


# ── Product signal validation tests ──────────────────────────────────


class TestHasProductSignal:
    """Test _has_product_signal — prevents blog/collection pages as products."""

    def test_og_product_type(self):
        og = {"og:type": "product", "og:title": "Blog Post"}
        assert _has_product_signal({}, og) is True

    def test_og_price_amount(self):
        product = {"og:price:amount": "29.99"}
        assert _has_product_signal(product, {}) is True

    def test_product_price_amount(self):
        product = {"product:price:amount": "19.99"}
        assert _has_product_signal(product, {}) is True

    def test_markdown_price(self):
        product = {"price": "49.99"}
        assert _has_product_signal(product, {}) is True

    def test_og_title_only_rejected(self):
        """Blog page with just og:title + og:image should be rejected."""
        product = {"og:title": "How to Brew Tea", "og:image": "tea.jpg"}
        og = {"og:title": "How to Brew Tea", "og:image": "tea.jpg"}
        assert _has_product_signal(product, og) is False

    def test_zero_price_rejected(self):
        product = {"og:price:amount": "0"}
        assert _has_product_signal(product, {}) is False

    def test_empty_price_rejected(self):
        product = {"og:price:amount": ""}
        assert _has_product_signal(product, {}) is False

    def test_blog_page_not_extracted(self):
        """End-to-end: blog page with OG tags produces no products."""
        html = """
        <html><head>
        <meta property="og:title" content="How to Brew the Perfect Cup of Tea" />
        <meta property="og:image" content="https://example.com/tea.jpg" />
        <meta property="og:description" content="A guide to brewing tea." />
        </head><body><h1>How to Brew the Perfect Cup of Tea</h1></body></html>
        """
        result = FakeCrawlResult(html=html, url="https://shop.com/how-to-brew")
        products = UnifiedCrawlExtractor._extract_from_crawl_result(result, result.url)
        assert len(products) == 0

    def test_product_page_with_og_price_extracted(self):
        """Product page with OG price tags is accepted."""
        html = """
        <html><head>
        <meta property="og:title" content="Earl Grey Tea" />
        <meta property="og:image" content="https://example.com/earl-grey.jpg" />
        <meta property="product:price:amount" content="12.99" />
        <meta property="product:price:currency" content="GBP" />
        </head><body></body></html>
        """
        result = FakeCrawlResult(html=html, url="https://shop.com/earl-grey")
        products = UnifiedCrawlExtractor._extract_from_crawl_result(result, result.url)
        assert len(products) == 1
        assert products[0].get("product:price:amount") == "12.99"


# ── extract() method tests ─────────────────────────────────────────────


class TestExtract:
    """Test the async extract() method with mocked HTTP/browser."""

    @pytest.mark.asyncio
    async def test_httpx_fast_path_complete(self):
        """When httpx returns JSON-LD with price + image, no browser needed."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "name": "Hat", "offers": {"price": "25.00"}, "image": "hat.jpg"}
        </script>
        </head><body></body></html>
        """
        extractor = UnifiedCrawlExtractor()
        with patch.object(extractor, "_fetch_html_httpx", return_value=html):
            with patch.object(extractor, "_extract_with_browser") as mock_browser:
                result = await extractor.extract("https://shop.com/hat")
                assert len(result.products) == 1
                assert result.products[0]["name"] == "Hat"
                mock_browser.assert_not_called()

    @pytest.mark.asyncio
    async def test_httpx_incomplete_triggers_browser(self):
        """Missing price in httpx result triggers browser fallback."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "name": "Lamp", "image": "lamp.jpg"}
        </script>
        </head><body></body></html>
        """
        browser_products = [{"name": "Lamp", "price": "45.00", "image": "lamp.jpg"}]

        extractor = UnifiedCrawlExtractor()
        with patch.object(extractor, "_fetch_html_httpx", return_value=html):
            with patch.object(extractor, "_extract_with_browser", return_value=browser_products):
                result = await extractor.extract("https://shop.com/lamp")
                assert len(result.products) == 1
                assert result.products[0]["price"] == "45.00"

    @pytest.mark.asyncio
    async def test_httpx_fails_falls_to_browser(self):
        """When httpx returns None (blocked), browser takes over."""
        browser_products = [{"name": "Ring", "price": "199.00", "image": "ring.jpg"}]

        extractor = UnifiedCrawlExtractor()
        with patch.object(extractor, "_fetch_html_httpx", return_value=None):
            with patch.object(extractor, "_extract_with_browser", return_value=browser_products):
                result = await extractor.extract("https://shop.com/ring")
                assert len(result.products) == 1
                assert result.products[0]["name"] == "Ring"

    @pytest.mark.asyncio
    async def test_both_fail_returns_empty(self):
        extractor = UnifiedCrawlExtractor()
        with patch.object(extractor, "_fetch_html_httpx", return_value=None):
            with patch.object(extractor, "_extract_with_browser", return_value=[]):
                result = await extractor.extract("https://shop.com/gone")
                assert result.products == []

    @pytest.mark.asyncio
    async def test_httpx_partial_returned_when_browser_fails(self):
        """If httpx has partial data and browser fails, return partial."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "name": "Book", "image": "book.jpg"}
        </script>
        </head><body></body></html>
        """
        extractor = UnifiedCrawlExtractor()
        with patch.object(extractor, "_fetch_html_httpx", return_value=html):
            with patch.object(extractor, "_extract_with_browser", return_value=[]):
                result = await extractor.extract("https://shop.com/book")
                assert len(result.products) == 1
                assert result.products[0]["name"] == "Book"


# ── extract_batch() tests ─────────────────────────────────────────────


class TestExtractBatch:
    @pytest.fixture(autouse=True)
    def _patch_browser_config(self):
        """Patch browser config factories to avoid crawl4ai compat issues."""
        with patch("app.extractors.unified_crawl_extractor.get_browser_config", return_value=MagicMock()), \
             patch("app.extractors.unified_crawl_extractor.get_crawler_strategy", return_value=None), \
             patch("app.extractors.unified_crawl_extractor.get_crawl_config", return_value=MagicMock()):
            yield

    @pytest.mark.asyncio
    async def test_empty_urls(self):
        extractor = UnifiedCrawlExtractor()
        result = await extractor.extract_batch([])
        assert result.products == []
        assert result.complete

    @pytest.mark.asyncio
    async def test_batch_extracts_from_results(self):
        """Mock arun_many to return fake CrawlResults."""
        html_template = """
        <html><head>
        <script type="application/ld+json">
        {{"@type": "Product", "name": "Product {i}", "offers": {{"price": "{price}"}}, "image": "p{i}.jpg"}}
        </script>
        </head><body></body></html>
        """
        fake_results = []
        for i in range(3):
            r = FakeCrawlResult(
                html=html_template.format(i=i, price=f"{10 + i}.99"),
                url=f"https://shop.com/p{i}",
            )
            fake_results.append(r)

        mock_crawler = AsyncMock()
        mock_crawler.arun_many = AsyncMock(return_value=fake_results)
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        extractor = UnifiedCrawlExtractor()
        with patch("crawl4ai.AsyncWebCrawler", return_value=mock_crawler):
            result = await extractor.extract_batch([
                "https://shop.com/p0",
                "https://shop.com/p1",
                "https://shop.com/p2",
            ])

        assert len(result.products) == 3
        assert result.complete


# ── has_price_and_image tests ──────────────────────────────────────────


class TestHasPriceAndImage:
    def test_complete(self):
        product = {"price": "10.00", "image": "img.jpg"}
        assert UnifiedCrawlExtractor._has_price_and_image(product) is True

    def test_missing_price(self):
        product = {"image": "img.jpg"}
        assert UnifiedCrawlExtractor._has_price_and_image(product) is False

    def test_missing_image(self):
        product = {"price": "10.00"}
        assert UnifiedCrawlExtractor._has_price_and_image(product) is False

    def test_og_image_counts(self):
        product = {"price": "10.00", "og:image": "img.jpg"}
        assert UnifiedCrawlExtractor._has_price_and_image(product) is True

    def test_offers_price_counts(self):
        product = {"offers": {"price": "10.00"}, "image": "img.jpg"}
        assert UnifiedCrawlExtractor._has_price_and_image(product) is True


# ── _extract_with_browser() single-browser tests (#154) ──────────────


class TestExtractWithBrowserSingleBrowser:
    """Verify _extract_with_browser creates ONE browser and retries with different configs."""

    @pytest.fixture(autouse=True)
    def _patch_browser_config(self):
        """Patch browser config factories to avoid crawl4ai compat issues."""
        with patch("app.extractors.unified_crawl_extractor.get_browser_config", return_value=MagicMock()), \
             patch("app.extractors.unified_crawl_extractor.get_crawler_strategy", return_value=None), \
             patch("app.extractors.unified_crawl_extractor.get_crawl_config", return_value=MagicMock()):
            yield

    @pytest.mark.asyncio
    async def test_single_browser_instance(self):
        """Only one AsyncWebCrawler context manager is created, not one per level."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "name": "Shoe", "offers": {"price": "59.00"}, "image": "shoe.jpg"}
        </script>
        </head><body></body></html>
        """
        # First arun returns failure, second returns success
        fail_result = FakeCrawlResult(success=False, error_message="blocked")
        ok_result = FakeCrawlResult(html=html, url="https://shop.com/shoe")

        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(side_effect=[fail_result, ok_result])
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        extractor = UnifiedCrawlExtractor()
        with patch("crawl4ai.AsyncWebCrawler", return_value=mock_crawler) as mock_cls:
            products = await extractor._extract_with_browser("https://shop.com/shoe")

        assert len(products) == 1
        assert products[0]["name"] == "Shoe"
        # Only ONE AsyncWebCrawler instance created
        mock_cls.assert_called_once()
        # arun called twice (escalation from STANDARD to STEALTH)
        assert mock_crawler.arun.call_count == 2

    @pytest.mark.asyncio
    async def test_returns_empty_when_all_levels_fail(self):
        """When all stealth levels fail, returns empty list."""
        fail_result = FakeCrawlResult(success=False, error_message="blocked")

        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=fail_result)
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        extractor = UnifiedCrawlExtractor()
        with patch("crawl4ai.AsyncWebCrawler", return_value=mock_crawler):
            products = await extractor._extract_with_browser("https://shop.com/gone")

        assert products == []
        # All 3 levels attempted
        assert mock_crawler.arun.call_count == 3

    @pytest.mark.asyncio
    async def test_stops_at_first_successful_extraction(self):
        """Stops escalation as soon as products are extracted."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "name": "Hat", "offers": {"price": "25.00"}, "image": "hat.jpg"}
        </script>
        </head><body></body></html>
        """
        ok_result = FakeCrawlResult(html=html, url="https://shop.com/hat")

        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=ok_result)
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        extractor = UnifiedCrawlExtractor()
        with patch("crawl4ai.AsyncWebCrawler", return_value=mock_crawler):
            products = await extractor._extract_with_browser("https://shop.com/hat")

        assert len(products) == 1
        # Stopped at first level (STANDARD)
        assert mock_crawler.arun.call_count == 1


# ── _extract_with_load_more() tests (#150) ───────────────────────────


class TestExtractWithLoadMore:
    """Test session-based Load More button handling."""

    @pytest.fixture(autouse=True)
    def _patch_browser_config(self):
        """Patch browser config factories to avoid crawl4ai compat issues."""
        mock_config = MagicMock()
        with patch("app.extractors.unified_crawl_extractor.get_browser_config", return_value=mock_config), \
             patch("app.extractors.unified_crawl_extractor.get_crawler_strategy", return_value=None), \
             patch("app.extractors.unified_crawl_extractor.get_crawl_config", return_value=MagicMock()):
            yield

    @pytest.mark.asyncio
    async def test_initial_load_returns_products(self):
        """When initial load has products and no load-more works, returns initial products."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "name": "Coffee", "offers": {"price": "15.00"}, "image": "coffee.jpg"}
        </script>
        </head><body></body></html>
        """
        initial_result = FakeCrawlResult(html=html, url="https://shop.com/products")
        # Subsequent clicks return same count (no new products)
        click_result = FakeCrawlResult(html=html, url="https://shop.com/products")

        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(side_effect=[initial_result, click_result])
        mock_crawler.kill_session = AsyncMock()
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        extractor = UnifiedCrawlExtractor()
        with patch("crawl4ai.AsyncWebCrawler", return_value=mock_crawler):
            products = await extractor._extract_with_load_more("https://shop.com/products")

        assert len(products) == 1
        assert products[0]["name"] == "Coffee"
        mock_crawler.kill_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_load_more_accumulates_products(self):
        """Each click reveals more products — method continues clicking."""
        def make_html(count):
            items = []
            for i in range(count):
                items.append(
                    f'{{"@type": "Product", "name": "P{i}", "sku": "sku{i}", '
                    f'"offers": {{"price": "{10 + i}.00"}}, "image": "p{i}.jpg"}}'
                )
            return (
                '<html><head><script type="application/ld+json">'
                f'[{",".join(items)}]'
                '</script></head><body></body></html>'
            )

        initial_result = FakeCrawlResult(html=make_html(2), url="https://shop.com/products")
        click1_result = FakeCrawlResult(html=make_html(4), url="https://shop.com/products")
        click2_result = FakeCrawlResult(html=make_html(6), url="https://shop.com/products")
        # Third click returns same count — stops
        click3_result = FakeCrawlResult(html=make_html(6), url="https://shop.com/products")

        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(
            side_effect=[initial_result, click1_result, click2_result, click3_result]
        )
        mock_crawler.kill_session = AsyncMock()
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        extractor = UnifiedCrawlExtractor()
        with patch("crawl4ai.AsyncWebCrawler", return_value=mock_crawler):
            products = await extractor._extract_with_load_more("https://shop.com/products")

        assert len(products) == 6
        mock_crawler.kill_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_initial_failure_returns_empty(self):
        """When initial page load fails, returns empty list."""
        fail_result = FakeCrawlResult(success=False, error_message="timeout")

        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(return_value=fail_result)
        mock_crawler.kill_session = AsyncMock()
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        extractor = UnifiedCrawlExtractor()
        with patch("crawl4ai.AsyncWebCrawler", return_value=mock_crawler):
            products = await extractor._extract_with_load_more("https://shop.com/products")

        assert products == []

    @pytest.mark.asyncio
    async def test_session_cleanup_on_error(self):
        """Session is cleaned up even if an error occurs during load-more clicks."""
        html = """
        <html><head>
        <script type="application/ld+json">
        {"@type": "Product", "name": "Item", "offers": {"price": "10.00"}, "image": "item.jpg"}
        </script>
        </head><body></body></html>
        """
        initial_result = FakeCrawlResult(html=html, url="https://shop.com/products")

        mock_crawler = AsyncMock()
        # Initial load succeeds, then subsequent click raises exception
        mock_crawler.arun = AsyncMock(side_effect=[initial_result, RuntimeError("browser crash")])
        mock_crawler.kill_session = AsyncMock()
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        extractor = UnifiedCrawlExtractor()
        with patch("crawl4ai.AsyncWebCrawler", return_value=mock_crawler):
            products = await extractor._extract_with_load_more("https://shop.com/products")

        # Should return the initial products despite the error
        assert len(products) == 1
        mock_crawler.kill_session.assert_called_once()

    @pytest.mark.asyncio
    async def test_max_clicks_respected(self):
        """Does not click more than _MAX_LOAD_MORE_CLICKS times."""
        def make_html(count):
            items = []
            for i in range(count):
                items.append(
                    f'{{"@type": "Product", "name": "P{i}", "sku": "sku{i}", '
                    f'"offers": {{"price": "{10 + i}.00"}}, "image": "p{i}.jpg"}}'
                )
            return (
                '<html><head><script type="application/ld+json">'
                f'[{",".join(items)}]'
                '</script></head><body></body></html>'
            )

        # Each click adds 1 more product — would go forever without the limit
        results = [FakeCrawlResult(html=make_html(i + 1), url="https://shop.com/p") for i in range(12)]

        mock_crawler = AsyncMock()
        mock_crawler.arun = AsyncMock(side_effect=results)
        mock_crawler.kill_session = AsyncMock()
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)

        extractor = UnifiedCrawlExtractor()
        with patch("crawl4ai.AsyncWebCrawler", return_value=mock_crawler):
            products = await extractor._extract_with_load_more("https://shop.com/p")

        # 1 initial + 10 clicks = 11 arun calls max
        assert mock_crawler.arun.call_count <= 11
        mock_crawler.kill_session.assert_called_once()

    def test_load_more_selectors_defined(self):
        """Verify load-more selectors list is populated."""
        assert len(UnifiedCrawlExtractor._LOAD_MORE_SELECTORS) > 0

    def test_max_load_more_clicks_is_10(self):
        """Verify max clicks constant is 10."""
        assert UnifiedCrawlExtractor._MAX_LOAD_MORE_CLICKS == 10
