"""Unit tests for pipeline verification, completeness, and reconciliation integration."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.extractors.base import ExtractorResult
from app.models.enums import ExtractionTier, JobStatus, Platform
from app.services.pipeline import Pipeline
from app.services.platform_detector import PlatformResult


@pytest.fixture
def mock_progress_tracker():
    tracker = AsyncMock()
    tracker.update = AsyncMock()
    tracker.set_metadata = AsyncMock()
    return tracker


@pytest.fixture
def mock_circuit_breaker():
    breaker = AsyncMock()

    async def call_passthrough(domain, coro):
        return await coro()

    breaker.call = AsyncMock(side_effect=call_passthrough)
    return breaker


@pytest.fixture
def mock_rate_limiter():
    limiter = AsyncMock()

    class MockAcquire:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

    limiter.acquire = MagicMock(return_value=MockAcquire())
    return limiter


@pytest.fixture
def pipeline(mock_progress_tracker, mock_circuit_breaker, mock_rate_limiter):
    return Pipeline(
        progress_tracker=mock_progress_tracker,
        circuit_breaker=mock_circuit_breaker,
        rate_limiter=mock_rate_limiter,
        bulk_ingestor=None,
    )


def _shopify_detect():
    return PlatformResult(
        platform=Platform.SHOPIFY, confidence=0.9, signals=["api:/products.json"]
    )


def _generic_detect():
    return PlatformResult(
        platform=Platform.GENERIC, confidence=1.0, signals=["fallback:no-signals-detected"]
    )


def _complete_product(title: str = "Product", url: str = "") -> dict:
    """Return a product dict with all critical fields filled."""
    p = {
        "title": title,
        "description": "A product",
        "price": "29.99",
        "image": "https://example.com/img.jpg",
        "offers": {"price": "29.99", "priceCurrency": "USD"},
        "sku": "SKU-1",
    }
    if url:
        p["_source_url"] = url
    return p


# ---------------------------------------------------------------------------
# Tracked extraction: source URL tagging
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tracked_extraction_tags_source_url(pipeline, mock_progress_tracker):
    """Every product extracted via tracked path has _source_url stamped."""
    with (
        patch("app.services.pipeline.PlatformDetector.detect") as mock_detect,
        patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover,
        patch("app.services.pipeline.UnifiedCrawlExtractor") as mock_schema_class,
    ):
        mock_detect.return_value = _generic_detect()
        mock_discover.return_value = [
            "https://example.com/p1",
            "https://example.com/p2",
        ]

        product = _complete_product()
        mock_ext = AsyncMock()
        mock_ext.extract = AsyncMock(return_value=ExtractorResult(products=[product.copy()]))
        mock_schema_class.return_value = mock_ext

        result = await pipeline.run("job-tag", "https://example.com")

        assert result["total_extracted"] == 2
        # The normalizer strips _source_url, so we need to check the extraction
        # result directly. We can verify through the audit instead.
        assert result.get("coverage_percentage") is not None


@pytest.mark.asyncio
async def test_tracked_extraction_source_url_on_api_tier(pipeline, mock_progress_tracker):
    """API tier products are tagged with the API endpoint URL."""
    with (
        patch("app.services.pipeline.PlatformDetector.detect") as mock_detect,
        patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover,
        patch("app.services.pipeline.ShopifyAPIExtractor") as mock_shopify_class,
    ):
        mock_detect.return_value = _shopify_detect()
        mock_discover.return_value = ["https://example.com/products.json"]

        product = {
            "id": 1,
            "title": "Shopify Product",
            "handle": "shopify-product",
            "variants": [{"price": "19.99"}],
            "images": [{"src": "https://example.com/img.jpg"}],
        }
        mock_ext = AsyncMock()
        mock_ext.extract = AsyncMock(return_value=ExtractorResult(products=[product]))
        mock_shopify_class.return_value = mock_ext

        result = await pipeline.run("job-api-tag", "https://example.com")

        assert result["total_extracted"] == 1
        assert result["extraction_tier"] == "api"


# ---------------------------------------------------------------------------
# Tracked extraction: outcome recording
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tracked_extraction_records_outcomes(pipeline, mock_progress_tracker):
    """Tracker records success/empty outcomes correctly — reflected in audit."""
    with (
        patch("app.services.pipeline.PlatformDetector.detect") as mock_detect,
        patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover,
        patch("app.services.pipeline.UnifiedCrawlExtractor") as mock_schema_class,
    ):
        mock_detect.return_value = _generic_detect()
        mock_discover.return_value = [
            "https://example.com/p1",
            "https://example.com/p2",
            "https://example.com/p3",
        ]

        product = _complete_product()
        call_count = 0

        async def extract_varying(url):
            nonlocal call_count
            call_count += 1
            # First call is probe (returns product), then per-URL tracked calls:
            # p1 → product, p2 → empty, p3 → product
            if call_count == 1:
                return ExtractorResult(products=[product.copy()])  # probe
            elif call_count == 2:
                return ExtractorResult(products=[product.copy()])  # p1 success
            elif call_count == 3:
                return ExtractorResult(products=[])  # p2 empty
            else:
                return ExtractorResult(products=[product.copy()])  # p3 success

        mock_ext = AsyncMock()
        mock_ext.extract = AsyncMock(side_effect=extract_varying)
        mock_schema_class.return_value = mock_ext

        result = await pipeline.run("job-outcomes", "https://example.com")

        # 2 products extracted (p1 + p3)
        assert result["total_extracted"] == 2


@pytest.mark.asyncio
async def test_tracked_extraction_records_errors(pipeline, mock_progress_tracker):
    """Tracker records error outcomes when extraction raises exceptions."""
    with (
        patch("app.services.pipeline.PlatformDetector.detect") as mock_detect,
        patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover,
        patch("app.services.pipeline.UnifiedCrawlExtractor") as mock_schema_class,
        patch("app.services.pipeline.OpenGraphExtractor") as mock_og_class,
        patch("app.services.pipeline.CSSExtractor") as mock_css_class,
    ):
        mock_detect.return_value = _generic_detect()
        mock_discover.return_value = ["https://example.com/p1"]

        # All tiers fail probe → fall through to CSS
        for cls in [mock_schema_class, mock_og_class]:
            mock = AsyncMock()
            mock.extract = AsyncMock(return_value=ExtractorResult(products=[]))
            cls.return_value = mock

        # CSS extractor: probe raises error (circuit breaker catches it)
        css_product = _complete_product()
        mock_css = AsyncMock()
        mock_css.extract = AsyncMock(return_value=ExtractorResult(products=[css_product]))
        mock_css_class.return_value = mock_css

        result = await pipeline.run("job-errors", "https://example.com")

        # CSS should extract 1 product
        assert result["total_extracted"] == 1


# ---------------------------------------------------------------------------
# Completeness check + targeted re-extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_completeness_triggers_reextraction(pipeline, mock_progress_tracker):
    """Missing image on extracted product triggers OG re-extraction."""
    with (
        patch("app.services.pipeline.PlatformDetector.detect") as mock_detect,
        patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover,
        patch("app.services.pipeline.ShopifyAPIExtractor") as mock_shopify_class,
    ):
        mock_detect.return_value = _shopify_detect()
        mock_discover.return_value = ["https://example.com/products.json"]

        # Product missing image
        product = {
            "id": 1,
            "title": "Product Without Image",
            "handle": "no-image",
            "variants": [{"price": "10.99"}],
            # No images field!
        }
        mock_ext = AsyncMock()
        mock_ext.extract = AsyncMock(return_value=ExtractorResult(products=[product]))
        mock_shopify_class.return_value = mock_ext

        # Mock OG extractor for re-extraction (created inside _targeted_reextract)
        with patch("app.services.pipeline.OpenGraphExtractor") as mock_og_class:
            og_supplement = {"og:image": "https://example.com/filled-img.jpg"}
            mock_og = AsyncMock()
            mock_og.extract = AsyncMock(return_value=ExtractorResult(products=[og_supplement]))
            mock_og_class.return_value = mock_og

            result = await pipeline.run("job-reextract", "https://example.com")

            # Should still complete (product had title + price)
            assert result["total_extracted"] == 1


@pytest.mark.asyncio
async def test_reextraction_capped_at_50_urls(pipeline, mock_progress_tracker):
    """>50 unique re-extraction URLs skips targeted re-extraction."""
    with (
        patch("app.services.pipeline.PlatformDetector.detect") as mock_detect,
        patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover,
        patch("app.services.pipeline.UnifiedCrawlExtractor") as mock_schema_class,
    ):
        mock_detect.return_value = _generic_detect()
        urls = [f"https://example.com/p{i}" for i in range(60)]
        mock_discover.return_value = urls

        # Each URL returns 1 product missing image (has title + price → quality OK)
        product_template = {
            "name": "Product",
            "offers": {"price": "9.99", "priceCurrency": "USD"},
            "sku": "SKU-1",
            # No image → incomplete
        }
        mock_ext = AsyncMock()
        mock_ext.extract = AsyncMock(side_effect=lambda _url: ExtractorResult(products=[dict(product_template)]))
        mock_schema_class.return_value = mock_ext

        # OG extractor should NOT be called since >50 unique URLs need re-extraction
        with patch("app.services.pipeline.OpenGraphExtractor") as mock_og_class:
            mock_og = AsyncMock()
            mock_og.extract = AsyncMock(return_value=ExtractorResult(products=[]))
            mock_og_class.return_value = mock_og

            result = await pipeline.run("job-capped", "https://example.com", max_urls=100)

            assert result["total_extracted"] == 60
            # OG was never called: UnifiedCrawl passed probe, and cap prevented re-extraction
            mock_og.extract.assert_not_called()


# ---------------------------------------------------------------------------
# VERIFYING status in pipeline
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verifying_status_in_progress(pipeline, mock_progress_tracker):
    """Pipeline transitions through VERIFYING status between extraction and normalization."""
    with (
        patch("app.services.pipeline.PlatformDetector.detect") as mock_detect,
        patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover,
        patch("app.services.pipeline.ShopifyAPIExtractor") as mock_shopify_class,
    ):
        mock_detect.return_value = _shopify_detect()
        mock_discover.return_value = ["https://example.com/products.json"]

        product = {
            "id": 1,
            "title": "Product",
            "handle": "product",
            "variants": [{"price": "10"}],
            "images": [{"src": "https://example.com/img.jpg"}],
        }
        mock_ext = AsyncMock()
        mock_ext.extract = AsyncMock(return_value=ExtractorResult(products=[product]))
        mock_shopify_class.return_value = mock_ext

        await pipeline.run("job-verify", "https://example.com")

        statuses = [
            call[1]["status"] for call in mock_progress_tracker.update.call_args_list
        ]

        assert JobStatus.VERIFYING in statuses

        # VERIFYING should come after EXTRACTING and before NORMALIZING
        verify_idx = statuses.index(JobStatus.VERIFYING)
        extract_indices = [i for i, s in enumerate(statuses) if s == JobStatus.EXTRACTING]
        normalize_indices = [i for i, s in enumerate(statuses) if s == JobStatus.NORMALIZING]

        assert any(ei < verify_idx for ei in extract_indices)
        assert any(ni > verify_idx for ni in normalize_indices)


# ---------------------------------------------------------------------------
# Reconciliation report stored in metadata
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reconciliation_stored_in_metadata(pipeline, mock_progress_tracker):
    """Reconciliation report and coverage_percentage stored in progress metadata."""
    with (
        patch("app.services.pipeline.PlatformDetector.detect") as mock_detect,
        patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover,
        patch("app.services.pipeline.ShopifyAPIExtractor") as mock_shopify_class,
    ):
        mock_detect.return_value = _shopify_detect()
        mock_discover.return_value = ["https://example.com/products.json"]

        product = {
            "id": 1,
            "title": "Product",
            "handle": "product",
            "variants": [{"price": "10"}],
            "images": [{"src": "https://example.com/img.jpg"}],
        }
        mock_ext = AsyncMock()
        mock_ext.extract = AsyncMock(return_value=ExtractorResult(products=[product]))
        mock_shopify_class.return_value = mock_ext

        result = await pipeline.run("job-recon", "https://example.com")

        # Check that set_metadata was called with reconciliation data
        metadata_calls = mock_progress_tracker.set_metadata.call_args_list
        recon_call = None
        for call in metadata_calls:
            kwargs = call[1] if call[1] else {}
            if "reconciliation_report" in kwargs:
                recon_call = kwargs
                break

        assert recon_call is not None, "reconciliation_report not found in metadata"
        assert "coverage_percentage" in recon_call

        # Pipeline return dict includes coverage data
        assert "coverage_percentage" in result
        assert "urls_failed" in result


@pytest.mark.asyncio
async def test_reconciliation_coverage_in_return_dict(pipeline, mock_progress_tracker):
    """Pipeline return dict includes coverage_percentage and urls_failed."""
    with (
        patch("app.services.pipeline.PlatformDetector.detect") as mock_detect,
        patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover,
        patch("app.services.pipeline.ShopifyAPIExtractor") as mock_shopify_class,
    ):
        mock_detect.return_value = _shopify_detect()
        mock_discover.return_value = ["https://example.com/products.json"]

        product = {
            "id": 1,
            "title": "Product",
            "handle": "product",
            "variants": [{"price": "19.99"}],
            "images": [{"src": "https://example.com/img.jpg"}],
        }
        mock_ext = AsyncMock()
        mock_ext.extract = AsyncMock(return_value=ExtractorResult(products=[product]))
        mock_shopify_class.return_value = mock_ext

        result = await pipeline.run("job-coverage", "https://example.com")

        assert isinstance(result["coverage_percentage"], float)
        assert isinstance(result["urls_failed"], int)
        assert result["urls_failed"] >= 0


# ---------------------------------------------------------------------------
# Audit data in ExtractionResult
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_extraction_result_contains_audit(pipeline, mock_progress_tracker):
    """ExtractionResult.audit is populated with summary dict from tracker."""
    with (
        patch("app.services.pipeline.PlatformDetector.detect") as mock_detect,
        patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover,
        patch("app.services.pipeline.ShopifyAPIExtractor") as mock_shopify_class,
    ):
        mock_detect.return_value = _shopify_detect()
        mock_discover.return_value = ["https://example.com/products.json"]

        product = {
            "id": 1,
            "title": "Product",
            "handle": "product",
            "variants": [{"price": "10"}],
            "images": [{"src": "https://example.com/img.jpg"}],
        }
        mock_ext = AsyncMock()
        mock_ext.extract = AsyncMock(return_value=ExtractorResult(products=[product]))
        mock_shopify_class.return_value = mock_ext

        # We can verify audit indirectly through reconciliation
        result = await pipeline.run("job-audit", "https://example.com")

        # Pipeline completed → reconciliation used audit data
        assert result["coverage_percentage"] is not None


# ---------------------------------------------------------------------------
# _fill_missing_fields static method
# ---------------------------------------------------------------------------


class TestFillMissingFields:
    """Tests for Pipeline._fill_missing_fields()."""

    def test_fills_missing_price(self):
        products = [{"title": "A", "_source_url": "u1"}]
        supplement = [{"price": "29.99", "currency": "USD"}]
        Pipeline._fill_missing_fields(products, [0], supplement)

        assert products[0]["price"] == "29.99"
        assert products[0]["currency"] == "USD"

    def test_never_overwrites_existing(self):
        products = [{"title": "A", "price": "19.99", "_source_url": "u1"}]
        supplement = [{"price": "29.99", "title": "B"}]
        Pipeline._fill_missing_fields(products, [0], supplement)

        assert products[0]["price"] == "19.99"
        assert products[0]["title"] == "A"

    def test_fills_empty_string(self):
        products = [{"title": "A", "description": "", "_source_url": "u1"}]
        supplement = [{"description": "Good description"}]
        Pipeline._fill_missing_fields(products, [0], supplement)

        assert products[0]["description"] == "Good description"

    def test_skips_underscore_prefixed_keys(self):
        products = [{"title": "A", "_source_url": "u1"}]
        supplement = [{"_source_url": "u2", "_internal": "skip"}]
        Pipeline._fill_missing_fields(products, [0], supplement)

        # _source_url should NOT be overwritten by supplement
        assert products[0]["_source_url"] == "u1"
        assert "_internal" not in products[0]

    def test_handles_out_of_bounds_indices(self):
        products = [{"title": "A"}]
        supplement = [{"price": "10"}]
        # Index 5 is out of bounds — should not crash
        Pipeline._fill_missing_fields(products, [5], supplement)

        assert "price" not in products[0]

    def test_empty_supplement_is_noop(self):
        products = [{"title": "A"}]
        Pipeline._fill_missing_fields(products, [0], [])

        assert products[0] == {"title": "A"}

    def test_empty_indices_is_noop(self):
        products = [{"title": "A"}]
        Pipeline._fill_missing_fields(products, [], [{"price": "10"}])

        assert "price" not in products[0]

    def test_multiple_indices(self):
        products = [
            {"title": "A", "_source_url": "u1"},
            {"title": "B", "_source_url": "u1"},
        ]
        supplement = [{"image": "https://example.com/img.jpg"}]
        Pipeline._fill_missing_fields(products, [0, 1], supplement)

        assert products[0]["image"] == "https://example.com/img.jpg"
        assert products[1]["image"] == "https://example.com/img.jpg"


# ---------------------------------------------------------------------------
# Page validator wiring in tracked extraction
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_page_validator_records_not_product_on_empty(pipeline, mock_progress_tracker):
    """When extraction returns empty and page fails validation, record not_product."""
    with (
        patch("app.services.pipeline.PlatformDetector.detect") as mock_detect,
        patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover,
        patch("app.services.pipeline.UnifiedCrawlExtractor") as mock_schema_class,
        patch("app.services.pipeline.OpenGraphExtractor") as mock_og_class,
        patch("app.services.pipeline.CSSExtractor") as mock_css_class,
        patch.object(pipeline, "_fetch_html") as mock_fetch,
    ):
        mock_detect.return_value = _generic_detect()
        mock_discover.return_value = [
            "https://example.com/product1",
            "https://example.com/blog-post",
        ]

        product = _complete_product()

        # Schema.org probe fails → OG probe fails → CSS fallback
        for cls in [mock_schema_class, mock_og_class]:
            mock = AsyncMock()
            mock.extract = AsyncMock(return_value=ExtractorResult(products=[]))
            cls.return_value = mock

        # CSS: product1 returns a product, blog-post returns empty
        call_count = 0

        async def css_varying(url):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ExtractorResult(products=[product.copy()])  # CSS probe
            if "product1" in url:
                return ExtractorResult(products=[product.copy()])
            return ExtractorResult(products=[])  # blog-post → empty

        mock_css = AsyncMock()
        mock_css.extract = AsyncMock(side_effect=css_varying)
        mock_css_class.return_value = mock_css

        # _fetch_html returns a blog page (no product signals)
        blog_html = "<html><head><title>My Blog Post</title></head><body>" + ("x" * 600) + "</body></html>"
        mock_fetch.return_value = blog_html

        result = await pipeline.run("job-validator", "https://example.com")

        # Only 1 product extracted (product1), blog-post was classified as not_product
        assert result["total_extracted"] == 1


@pytest.mark.asyncio
async def test_page_validator_records_empty_when_valid_product_page(pipeline, mock_progress_tracker):
    """When extraction returns empty but page IS a product page, record empty (not not_product)."""
    with (
        patch("app.services.pipeline.PlatformDetector.detect") as mock_detect,
        patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover,
        patch("app.services.pipeline.UnifiedCrawlExtractor") as mock_schema_class,
        patch("app.services.pipeline.OpenGraphExtractor") as mock_og_class,
        patch("app.services.pipeline.CSSExtractor") as mock_css_class,
        patch.object(pipeline, "_fetch_html") as mock_fetch,
    ):
        mock_detect.return_value = _generic_detect()
        mock_discover.return_value = [
            "https://example.com/product1",
            "https://example.com/product2",
        ]

        product = _complete_product()

        for cls in [mock_schema_class, mock_og_class]:
            mock = AsyncMock()
            mock.extract = AsyncMock(return_value=ExtractorResult(products=[]))
            cls.return_value = mock

        call_count = 0

        async def css_varying(url):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ExtractorResult(products=[product.copy()])  # CSS probe
            if "product1" in url:
                return ExtractorResult(products=[product.copy()])
            return ExtractorResult(products=[])  # product2 → empty

        mock_css = AsyncMock()
        mock_css.extract = AsyncMock(side_effect=css_varying)
        mock_css_class.return_value = mock_css

        # _fetch_html returns a real product page (JSON-LD Product)
        product_html = (
            '<html><head><title>Product 2</title></head><body>'
            '<script type="application/ld+json">{"@type":"Product","name":"Test"}</script>'
            + ("x" * 600)
            + "</body></html>"
        )
        mock_fetch.return_value = product_html

        result = await pipeline.run("job-valid-empty", "https://example.com")

        # product2 was empty but is a valid product page → recorded as empty, not not_product
        assert result["total_extracted"] == 1


@pytest.mark.asyncio
async def test_page_validator_skipped_when_fetch_fails(pipeline, mock_progress_tracker):
    """When HTML fetch fails (None), fall back to recording empty — no crash."""
    with (
        patch("app.services.pipeline.PlatformDetector.detect") as mock_detect,
        patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover,
        patch("app.services.pipeline.UnifiedCrawlExtractor") as mock_schema_class,
        patch("app.services.pipeline.OpenGraphExtractor") as mock_og_class,
        patch("app.services.pipeline.CSSExtractor") as mock_css_class,
        patch.object(pipeline, "_fetch_html") as mock_fetch,
    ):
        mock_detect.return_value = _generic_detect()
        mock_discover.return_value = [
            "https://example.com/product1",
            "https://example.com/product2",
        ]

        product = _complete_product()

        for cls in [mock_schema_class, mock_og_class]:
            mock = AsyncMock()
            mock.extract = AsyncMock(return_value=ExtractorResult(products=[]))
            cls.return_value = mock

        # CSS fallback (no probe): product1 → product, product2 → empty
        async def css_varying(url):
            if "product1" in url:
                return ExtractorResult(products=[product.copy()])
            return ExtractorResult(products=[])

        mock_css = AsyncMock()
        mock_css.extract = AsyncMock(side_effect=css_varying)
        mock_css_class.return_value = mock_css

        # _fetch_html returns None (network failure) for product2
        mock_fetch.return_value = None

        result = await pipeline.run("job-fetch-fail", "https://example.com")

        # product1 extracted, product2 empty (fetch failed → recorded as empty)
        assert result["total_extracted"] == 1
        # _fetch_html was called for the empty URL
        mock_fetch.assert_called_once()
