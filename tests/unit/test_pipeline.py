"""Unit tests for pipeline orchestrator."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.extractors.base import ExtractorResult
from app.extractors.css_extractor import CSSExtractor
from app.models.enums import JobStatus, Platform
from app.services.pipeline import Pipeline
from app.services.platform_detector import PlatformResult
from app.services.shopify_price_supplementer import ShopifyPriceSupplementer


@pytest.fixture
def mock_progress_tracker():
    """Mock progress tracker."""
    tracker = AsyncMock()
    tracker.update = AsyncMock()
    return tracker


@pytest.fixture
def mock_circuit_breaker():
    """Mock circuit breaker."""
    breaker = AsyncMock()

    async def call_passthrough(domain, coro):
        return await coro()

    breaker.call = AsyncMock(side_effect=call_passthrough)
    return breaker


@pytest.fixture
def mock_rate_limiter():
    """Mock rate limiter."""
    limiter = AsyncMock()

    class MockAcquire:
        async def __aenter__(self):
            return None

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return None

    limiter.acquire = MagicMock(return_value=MockAcquire())
    return limiter


@pytest.fixture
def mock_bulk_ingestor():
    """Mock bulk ingestor."""
    ingestor = AsyncMock()
    ingestor.ingest = AsyncMock(return_value=10)
    return ingestor


@pytest.fixture
def pipeline(mock_progress_tracker, mock_circuit_breaker, mock_rate_limiter, mock_bulk_ingestor):
    """Create pipeline with mocked dependencies."""
    return Pipeline(
        progress_tracker=mock_progress_tracker,
        circuit_breaker=mock_circuit_breaker,
        rate_limiter=mock_rate_limiter,
        bulk_ingestor=mock_bulk_ingestor,
    )


@pytest.fixture
def pipeline_no_ingestor(mock_progress_tracker, mock_circuit_breaker, mock_rate_limiter):
    """Create pipeline without bulk ingestor (for testing without DB)."""
    return Pipeline(
        progress_tracker=mock_progress_tracker,
        circuit_breaker=mock_circuit_breaker,
        rate_limiter=mock_rate_limiter,
        bulk_ingestor=None,
    )


@pytest.mark.asyncio
async def test_pipeline_shopify_happy_path(pipeline, mock_progress_tracker):
    """Test full pipeline happy path with Shopify."""
    # Mock platform detection
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.SHOPIFY,
            confidence=0.9,
            signals=["api:/products.json"],
        )

        # Mock URL discovery
        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = ["https://example.com/products.json"]

            # Mock extractor
            with patch("app.services.pipeline.ShopifyAPIExtractor") as mock_extractor_class:
                mock_extractor = AsyncMock()
                mock_extractor.extract = AsyncMock(
                    return_value=ExtractorResult(products=[
                        {
                            "id": 123,
                            "title": "Test Product",
                            "handle": "test-product",
                            "body_html": "<p>Description</p>",
                            "variants": [{"id": 456, "price": "19.99"}],
                            "images": [{"src": "https://example.com/image.jpg"}],
                        }
                    ])
                )
                mock_extractor_class.return_value = mock_extractor

                # Run pipeline
                result = await pipeline.run("job-123", "https://example.com")

                # Assertions
                assert result["platform"] == "shopify"
                assert result["total_extracted"] == 1
                assert result["total_normalized"] == 1
                assert result["total_ingested"] == 10
                assert result["extraction_tier"] == "api"

                # Verify progress updates
                assert mock_progress_tracker.update.call_count >= 5
                # First call should be detecting
                first_call = mock_progress_tracker.update.call_args_list[0]
                assert first_call[1]["status"] == JobStatus.DETECTING
                # Last call should be completed
                last_call = mock_progress_tracker.update.call_args_list[-1]
                assert last_call[1]["status"] == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_pipeline_woocommerce(pipeline, mock_progress_tracker):
    """Test pipeline with WooCommerce platform."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.WOOCOMMERCE,
            confidence=0.85,
            signals=["api:/wp-json/"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = ["https://example.com/wp-json/wc/store/v1/products"]

            with patch("app.services.pipeline.WooCommerceAPIExtractor") as mock_extractor_class:
                mock_extractor = AsyncMock()
                mock_extractor.extract = AsyncMock(
                    return_value=ExtractorResult(products=[
                        {
                            "id": 789,
                            "name": "WooCommerce Product",
                            "permalink": "https://example.com/product/test",
                            "prices": {
                                "price": "2999",
                                "currency_code": "USD",
                                "currency_minor_unit": 2,
                            },
                            "images": [{"src": "https://example.com/woo-image.jpg"}],
                            "description": "Product description",
                            "tags": [],
                        }
                    ])
                )
                mock_extractor_class.return_value = mock_extractor

                result = await pipeline.run("job-456", "https://example.com")

                assert result["platform"] == "woocommerce"
                assert result["total_extracted"] == 1
                assert result["total_normalized"] == 1
                assert result["extraction_tier"] == "api"


@pytest.mark.asyncio
async def test_pipeline_generic_schema_org_fallback(pipeline, mock_progress_tracker):
    """Test pipeline with generic platform using Schema.org fallback."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.GENERIC,
            confidence=1.0,
            signals=["fallback:no-signals-detected"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = [
                "https://example.com/product1",
                "https://example.com/product2",
            ]

            with patch("app.services.pipeline.SchemaOrgExtractor") as mock_extractor_class:
                product_data = {
                    "name": "Schema.org Product",
                    "description": "Product description",
                    "offers": {"price": "49.99", "priceCurrency": "USD"},
                    "image": "https://example.com/image.jpg",
                    "sku": "SKU123",
                }
                mock_extractor = AsyncMock()
                # extract() used for probe call
                mock_extractor.extract = AsyncMock(return_value=ExtractorResult(products=[product_data]))
                # extract_batch() used for full extraction
                mock_extractor.extract_batch = AsyncMock(
                    return_value=ExtractorResult(products=[product_data, product_data])
                )
                mock_extractor_class.return_value = mock_extractor

                result = await pipeline.run("job-789", "https://example.com")

                assert result["platform"] == "generic"
                assert result["total_extracted"] == 2  # 2 URLs
                assert result["extraction_tier"] == "schema_org"


@pytest.mark.asyncio
async def test_pipeline_detection_failure(pipeline, mock_progress_tracker):
    """Test pipeline handles detection failure gracefully."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.side_effect = Exception("Detection failed")

        with pytest.raises(Exception, match="Detection failed"):
            await pipeline.run("job-error", "https://example.com")

        # Verify progress was updated with failed status
        last_call = mock_progress_tracker.update.call_args_list[-1]
        assert last_call[1]["status"] == JobStatus.FAILED
        assert "Detection failed" in last_call[1]["error"]


@pytest.mark.asyncio
async def test_pipeline_extraction_failure(pipeline, mock_progress_tracker):
    """Test pipeline handles extraction failure — exception propagates and marks FAILED."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.SHOPIFY,
            confidence=0.9,
            signals=["api:/products.json"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = ["https://example.com/products.json"]

            with patch("app.services.pipeline.ShopifyAPIExtractor") as mock_extractor_class:
                mock_extractor = AsyncMock()
                mock_extractor.extract = AsyncMock(side_effect=Exception("Extraction failed"))
                mock_extractor_class.return_value = mock_extractor

                # Non-CircuitOpenError exceptions now propagate (not swallowed)
                with pytest.raises(Exception, match="Extraction failed"):
                    await pipeline.run("job-error", "https://example.com")

                # Status should be FAILED
                last_call = mock_progress_tracker.update.call_args_list[-1]
                assert last_call[1]["status"] == JobStatus.FAILED
                assert "Extraction failed" in last_call[1]["error"]


@pytest.mark.asyncio
async def test_pipeline_no_urls_discovered(pipeline, mock_progress_tracker):
    """Test pipeline when no URLs discovered — triggers needs_review."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.SHOPIFY,
            confidence=0.9,
            signals=["api:/products.json"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = []

            result = await pipeline.run("job-no-urls", "https://example.com")

            assert result["total_extracted"] == 0
            assert result["total_normalized"] == 0
            assert result["total_ingested"] == 0
            assert result["needs_review"] is True
            assert result["review_reason"] == "no_urls_discovered"

            # Status should be NEEDS_REVIEW, not silently COMPLETED
            last_call = mock_progress_tracker.update.call_args_list[-1]
            assert last_call[1]["status"] == JobStatus.NEEDS_REVIEW


@pytest.mark.asyncio
async def test_pipeline_progress_updates_at_each_step(pipeline, mock_progress_tracker):
    """Test that pipeline updates progress at each step."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.SHOPIFY,
            confidence=0.9,
            signals=["api:/products.json"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = ["https://example.com/products.json"]

            with patch("app.services.pipeline.ShopifyAPIExtractor") as mock_extractor_class:
                mock_extractor = AsyncMock()
                mock_extractor.extract = AsyncMock(
                    return_value=ExtractorResult(products=[
                        {
                            "id": 1,
                            "title": "Product",
                            "handle": "product",
                            "variants": [{"price": "10"}],
                        }
                    ])
                )
                mock_extractor_class.return_value = mock_extractor

                await pipeline.run("job-progress", "https://example.com")

                # Extract all status values from calls
                statuses = [
                    call[1]["status"] for call in mock_progress_tracker.update.call_args_list
                ]

                # Verify we went through all steps
                # Note: INGESTING is no longer a separate step — ingestion
                # happens inline during NORMALIZING batches for memory efficiency
                assert JobStatus.DETECTING in statuses
                assert JobStatus.DISCOVERING in statuses
                assert JobStatus.EXTRACTING in statuses
                assert JobStatus.NORMALIZING in statuses
                assert JobStatus.COMPLETED in statuses


@pytest.mark.asyncio
async def test_pipeline_without_bulk_ingestor(pipeline_no_ingestor, mock_progress_tracker):
    """Test pipeline works without bulk ingestor (for testing without DB)."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.SHOPIFY,
            confidence=0.9,
            signals=["api:/products.json"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = ["https://example.com/products.json"]

            with patch("app.services.pipeline.ShopifyAPIExtractor") as mock_extractor_class:
                mock_extractor = AsyncMock()
                mock_extractor.extract = AsyncMock(
                    return_value=ExtractorResult(products=[
                        {
                            "id": 1,
                            "title": "Product",
                            "handle": "product",
                            "variants": [{"price": "10"}],
                        }
                    ])
                )
                mock_extractor_class.return_value = mock_extractor

                result = await pipeline_no_ingestor.run("job-no-db", "https://example.com")

                # Should extract and normalize but not ingest
                assert result["total_extracted"] == 1
                assert result["total_normalized"] == 1
                assert result["total_ingested"] == 0

                # Should complete successfully
                last_call = mock_progress_tracker.update.call_args_list[-1]
                assert last_call[1]["status"] == JobStatus.COMPLETED


@pytest.mark.asyncio
async def test_pipeline_magento_extraction(pipeline, mock_progress_tracker):
    """Test pipeline with Magento platform."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.MAGENTO,
            confidence=0.8,
            signals=["api:/rest/V1/store/storeConfigs"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = ["https://example.com/rest/V1/products"]

            with patch("app.services.pipeline.MagentoAPIExtractor") as mock_extractor_class:
                mock_extractor = AsyncMock()
                mock_extractor.extract = AsyncMock(
                    return_value=ExtractorResult(products=[
                        {
                            "id": 1,
                            "name": "Magento Product",
                            "sku": "MAG-123",
                            "price": 99.99,
                            "custom_attributes": [
                                {"attribute_code": "description", "value": "Test description"},
                                {"attribute_code": "image", "value": "/path/to/image.jpg"},
                                {"attribute_code": "url_key", "value": "magento-product"},
                            ],
                        }
                    ])
                )
                mock_extractor_class.return_value = mock_extractor

                result = await pipeline.run("job-magento", "https://example.com")

                assert result["platform"] == "magento"
                assert result["total_extracted"] == 1
                assert result["extraction_tier"] == "api"


@pytest.mark.asyncio
async def test_pipeline_bigcommerce_css_extraction(pipeline, mock_progress_tracker):
    """Test pipeline with BigCommerce using CSS extraction via fallback chain."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.BIGCOMMERCE,
            confidence=0.9,
            signals=["cdn:cdn.bigcommerce.com"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = [
                "https://example.com/product1",
                "https://example.com/product2",
            ]

            # BigCommerce now goes through fallback chain: Schema.org → OG → CSS
            # Mock Schema.org to return empty (no structured data)
            with (
                patch("app.services.pipeline.SchemaOrgExtractor") as mock_schema_class,
                patch("app.services.pipeline.OpenGraphExtractor") as mock_og_class,
                patch("app.services.pipeline.CSSExtractor") as mock_css_class,
            ):
                mock_schema = AsyncMock()
                mock_schema.extract = AsyncMock(return_value=ExtractorResult(products=[]))
                mock_schema_class.return_value = mock_schema

                mock_og = AsyncMock()
                mock_og.extract = AsyncMock(return_value=ExtractorResult(products=[]))
                mock_og_class.return_value = mock_og

                bc_product = {
                    "title": "BigCommerce Product",
                    "price": "$29.99",
                    "description": "Product description",
                    "image": "https://example.com/image.jpg",
                    "sku": "BC-123",
                }
                mock_css = AsyncMock()
                mock_css.extract = AsyncMock(return_value=ExtractorResult(products=[bc_product]))
                mock_css.extract_batch = AsyncMock(
                    return_value=ExtractorResult(products=[bc_product, bc_product])
                )
                mock_css_class.return_value = mock_css

                result = await pipeline.run("job-bigcommerce", "https://example.com")

                assert result["platform"] == "bigcommerce"
                assert result["total_extracted"] == 2  # 2 URLs
                assert result["extraction_tier"] == "deep_crawl"


@pytest.mark.asyncio
async def test_pipeline_skips_low_quality_probe(pipeline, mock_progress_tracker):
    """Test that fallback chain skips tiers where probe quality is too low."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.GENERIC,
            confidence=1.0,
            signals=["fallback:no-signals-detected"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = [
                "https://example.com/product1",
                "https://example.com/product2",
            ]

            with (
                patch("app.services.pipeline.SchemaOrgExtractor") as mock_schema_class,
                patch("app.services.pipeline.OpenGraphExtractor") as mock_og_class,
                patch("app.services.pipeline.CSSExtractor") as mock_css_class,
            ):
                # Schema.org returns products without titles (quality = 0.0)
                mock_schema = AsyncMock()
                mock_schema.extract = AsyncMock(return_value=ExtractorResult(products=[{"price": "$10"}]))
                mock_schema_class.return_value = mock_schema

                # OG returns good products (quality > 0.3)
                og_product = {
                    "og:title": "Good Product",
                    "og:description": "A product",
                    "og:image": "https://example.com/img.jpg",
                }
                mock_og = AsyncMock()
                mock_og.extract = AsyncMock(return_value=ExtractorResult(products=[og_product]))
                mock_og.extract_batch = AsyncMock(
                    return_value=ExtractorResult(products=[og_product, og_product])
                )
                mock_og_class.return_value = mock_og

                mock_css = AsyncMock()
                mock_css_class.return_value = mock_css

                result = await pipeline.run("job-quality-gate", "https://example.com")

                # Should have used OG tier (Schema.org was skipped due to low quality)
                assert result["extraction_tier"] == "opengraph"
                assert result["total_extracted"] == 2

                # Schema.org extractor should have been called only once (probe)
                assert mock_schema.extract.call_count == 1
                # OG: 1 probe + 2 per-URL tracked extraction calls
                assert mock_og.extract.call_count == 3


@pytest.mark.asyncio
async def test_pipeline_needs_review_on_zero_products_after_extraction(
    pipeline, mock_progress_tracker
):
    """Test pipeline marks needs_review when URLs exist but extraction finds 0 products."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.GENERIC,
            confidence=1.0,
            signals=["fallback:no-signals-detected"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = ["https://example.com/product1"]

            # All extractors return empty
            with (
                patch("app.services.pipeline.SchemaOrgExtractor") as mock_schema_class,
                patch("app.services.pipeline.OpenGraphExtractor") as mock_og_class,
                patch("app.services.pipeline.CSSExtractor") as mock_css_class,
            ):
                for mock_class in [mock_schema_class, mock_og_class, mock_css_class]:
                    mock_ext = AsyncMock()
                    mock_ext.extract = AsyncMock(return_value=ExtractorResult(products=[]))
                    mock_ext.extract_batch = AsyncMock(return_value=ExtractorResult(products=[]))
                    mock_class.return_value = mock_ext

                result = await pipeline.run("job-zero-products", "https://example.com")

                assert result["needs_review"] is True
                assert result["review_reason"] == "zero_products"
                assert result["total_extracted"] == 0

                last_call = mock_progress_tracker.update.call_args_list[-1]
                assert last_call[1]["status"] == JobStatus.NEEDS_REVIEW


@pytest.mark.asyncio
async def test_pipeline_uses_tracked_extraction_for_full_extraction(
    pipeline, mock_progress_tracker
):
    """Test that tracked extraction calls extract() per URL for outcome tracking."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.GENERIC,
            confidence=1.0,
            signals=["fallback:no-signals-detected"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = [
                "https://example.com/product1",
                "https://example.com/product2",
                "https://example.com/product3",
            ]

            product_data = {
                "name": "Batch Product",
                "description": "Product",
                "offers": {"price": "10.00", "priceCurrency": "USD"},
                "image": "https://example.com/img.jpg",
                "sku": "BATCH-1",
            }

            with patch("app.services.pipeline.SchemaOrgExtractor") as mock_schema_class:
                mock_extractor = AsyncMock()
                mock_extractor.extract = AsyncMock(return_value=ExtractorResult(products=[product_data]))
                mock_schema_class.return_value = mock_extractor

                result = await pipeline.run("job-tracked", "https://example.com")

                assert result["total_extracted"] == 3
                # extract() called: 1 probe + 3 per-URL tracked calls
                assert mock_extractor.extract.call_count == 4


@pytest.mark.asyncio
async def test_pipeline_shopify_fallback_on_empty_api_response(pipeline, mock_progress_tracker):
    """Test Shopify falls back to extraction chain when API returns 0 products."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.SHOPIFY,
            confidence=0.9,
            signals=["api:/products.json"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = [
                "https://example.com/product1",
                "https://example.com/product2",
            ]

            # Shopify API returns empty
            with patch("app.services.pipeline.ShopifyAPIExtractor") as mock_shopify_class, \
                 patch("app.services.shopify_price_supplementer.ShopifyAPIExtractor", mock_shopify_class):
                mock_shopify = AsyncMock()
                mock_shopify.extract = AsyncMock(return_value=ExtractorResult(products=[]))
                mock_shopify_class.return_value = mock_shopify

                # Schema.org returns good data as fallback
                with patch("app.services.pipeline.SchemaOrgExtractor") as mock_schema_class:
                    product_data = {
                        "name": "Fallback Product",
                        "description": "Product from fallback",
                        "offers": {"price": "29.99", "priceCurrency": "USD"},
                        "image": "https://example.com/img.jpg",
                        "sku": "FALL-1",
                    }
                    mock_schema = AsyncMock()
                    mock_schema.extract = AsyncMock(return_value=ExtractorResult(products=[product_data]))
                    mock_schema.extract_batch = AsyncMock(
                        return_value=ExtractorResult(products=[product_data, product_data])
                    )
                    mock_schema_class.return_value = mock_schema

                    result = await pipeline.run("job-shopify-fallback", "https://example.com")

                    # Should have fallen back to Schema.org tier
                    assert result["platform"] == "shopify"
                    assert result["total_extracted"] == 2
                    assert result["extraction_tier"] == "schema_org"

                    # Shopify API: 1 initial + 2 supplementation attempts (main + shop.{domain})
                    assert mock_shopify.extract.call_count == 3
                    # Schema.org: 1 probe + 2 per-URL tracked calls
                    assert mock_schema.extract.call_count == 3


@pytest.mark.asyncio
async def test_pipeline_opengraph_tier_correct(pipeline, mock_progress_tracker):
    """Test that OpenGraph extraction returns correct ExtractionTier.OPENGRAPH."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.GENERIC,
            confidence=1.0,
            signals=["fallback:no-signals-detected"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = ["https://example.com/product1"]

            # Schema.org returns empty, OpenGraph succeeds
            with (
                patch("app.services.pipeline.SchemaOrgExtractor") as mock_schema_class,
                patch("app.services.pipeline.OpenGraphExtractor") as mock_og_class,
            ):
                mock_schema = AsyncMock()
                mock_schema.extract = AsyncMock(return_value=ExtractorResult(products=[]))
                mock_schema_class.return_value = mock_schema

                og_product = {
                    "og:title": "OpenGraph Product",
                    "og:description": "OG description",
                    "og:image": "https://example.com/og.jpg",
                    "og:price:amount": "19.99",
                }
                mock_og = AsyncMock()
                mock_og.extract = AsyncMock(return_value=ExtractorResult(products=[og_product]))
                mock_og.extract_batch = AsyncMock(return_value=ExtractorResult(products=[og_product]))
                mock_og_class.return_value = mock_og

                result = await pipeline.run("job-og-tier", "https://example.com")

                assert result["extraction_tier"] == "opengraph"
                assert result["total_extracted"] == 1


@pytest.mark.asyncio
async def test_pipeline_logs_warnings_when_smart_css_and_llm_not_configured(
    pipeline, mock_progress_tracker, caplog
):
    """Test that pipeline logs warnings when SmartCSS and LLM extractors are not configured."""
    import logging
    caplog.set_level(logging.WARNING)

    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.GENERIC,
            confidence=1.0,
            signals=["fallback:no-signals-detected"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = ["https://example.com/product1"]

            # All extractors return empty except hardcoded CSS
            with (
                patch("app.services.pipeline.SchemaOrgExtractor") as mock_schema_class,
                patch("app.services.pipeline.OpenGraphExtractor") as mock_og_class,
                patch("app.services.pipeline.CSSExtractor") as mock_css_class,
            ):
                for mock_class in [mock_schema_class, mock_og_class]:
                    mock_ext = AsyncMock()
                    mock_ext.extract = AsyncMock(return_value=ExtractorResult(products=[]))
                    mock_class.return_value = mock_ext

                # CSS returns data so we don't trigger needs_review
                css_product = {
                    "title": "CSS Product",
                    "price": "$10",
                    "description": "CSS extracted",
                }
                mock_css = AsyncMock()
                mock_css.extract = AsyncMock(return_value=ExtractorResult(products=[css_product]))
                mock_css_class.return_value = mock_css

                await pipeline.run("job-warnings", "https://example.com")

                # Check that warnings were logged
                warnings = [rec.message for rec in caplog.records if rec.levelname == "WARNING"]
                assert any("SmartCSS extractor not configured" in w for w in warnings)
                assert any("LLM extractor not configured" in w for w in warnings)


@pytest.mark.asyncio
async def test_pipeline_shopify_no_fallback_when_api_has_products(pipeline, mock_progress_tracker):
    """Test Shopify does NOT fall back when API returns products successfully."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.SHOPIFY,
            confidence=0.9,
            signals=["api:/products.json"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = [
                "https://example.com/product1",
                "https://example.com/product2",
            ]

            # Shopify API returns complete products (price + image present)
            with patch("app.services.pipeline.ShopifyAPIExtractor") as mock_shopify_class:
                shopify_product = {
                    "id": 123,
                    "title": "API Product",
                    "handle": "api-product",
                    "price": "10.99",
                    "image": "https://example.com/img.jpg",
                    "variants": [{"price": "10.99"}],
                    "images": [{"src": "https://example.com/img.jpg"}],
                }
                mock_shopify = AsyncMock()
                mock_shopify.extract = AsyncMock(return_value=ExtractorResult(products=[shopify_product]))
                mock_shopify_class.return_value = mock_shopify

                result = await pipeline.run("job-shopify-no-fallback", "https://example.com")

                # Should use API tier only
                assert result["platform"] == "shopify"
                assert result["total_extracted"] == 1
                assert result["extraction_tier"] == "api"

                # Shopify API should have been used
                assert mock_shopify.extract.call_count == 1


@pytest.mark.asyncio
async def test_merge_tier_fields_fills_gaps():
    """Test that _merge_tier_fields fills missing fields from supplementary data."""
    primary = [{"title": "Product A", "price": "29.99"}]
    supplementary = [{"image": "https://example.com/img.jpg", "sku": "SKU-123"}]

    result = Pipeline._merge_tier_fields(primary, supplementary)

    assert len(result) == 1
    assert result[0]["title"] == "Product A"
    assert result[0]["price"] == "29.99"
    assert result[0]["image"] == "https://example.com/img.jpg"
    assert result[0]["sku"] == "SKU-123"


@pytest.mark.asyncio
async def test_merge_tier_fields_never_overwrites():
    """Test that _merge_tier_fields never overwrites existing primary values."""
    primary = [{"title": "Primary Title", "price": "29.99"}]
    supplementary = [{"title": "Supplementary Title", "price": "19.99", "sku": "SKU-123"}]

    result = Pipeline._merge_tier_fields(primary, supplementary)

    assert result[0]["title"] == "Primary Title"
    assert result[0]["price"] == "29.99"
    assert result[0]["sku"] == "SKU-123"


@pytest.mark.asyncio
async def test_merge_tier_fields_empty_supplementary():
    """Test that empty supplementary returns primary unchanged."""
    primary = [{"title": "Product A", "price": "29.99"}]

    result = Pipeline._merge_tier_fields(primary, [])

    assert result == primary


@pytest.mark.asyncio
async def test_merge_tier_fields_empty_primary():
    """Test that empty primary returns empty."""
    supplementary = [{"title": "Product A", "price": "29.99"}]

    result = Pipeline._merge_tier_fields([], supplementary)

    assert result == []


@pytest.mark.asyncio
async def test_merge_tier_fields_fills_empty_strings():
    """Test that empty string values in primary are filled from supplementary."""
    primary = [{"title": "Product A", "description": "", "price": "29.99"}]
    supplementary = [{"description": "Good description", "vendor": "Acme"}]

    result = Pipeline._merge_tier_fields(primary, supplementary)

    assert result[0]["description"] == "Good description"
    assert result[0]["vendor"] == "Acme"
    assert result[0]["title"] == "Product A"


@pytest.mark.asyncio
async def test_merge_tier_fields_skips_empty_supplementary_values():
    """Test that empty/None supplementary values are not merged."""
    primary = [{"title": "Product A"}]
    supplementary = [{"description": "", "sku": None, "vendor": "   ", "image": "https://img.jpg"}]

    result = Pipeline._merge_tier_fields(primary, supplementary)

    assert "description" not in result[0]
    assert "sku" not in result[0]
    assert "vendor" not in result[0]
    assert result[0]["image"] == "https://img.jpg"


@pytest.mark.asyncio
async def test_pipeline_merges_partial_probes(pipeline, mock_progress_tracker):
    """Test that pipeline merges partial probe data from failed tiers into winning tier."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.GENERIC,
            confidence=1.0,
            signals=["fallback:no-signals-detected"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = ["https://example.com/product1"]

            with (
                patch("app.services.pipeline.SchemaOrgExtractor") as mock_schema_class,
                patch("app.services.pipeline.OpenGraphExtractor") as mock_og_class,
            ):
                # Schema.org returns partial data (no title → quality 0.0, fails probe)
                schema_product = {
                    "offers": {"price": "19.99", "priceCurrency": "USD"},
                    "image": "https://example.com/schema-img.jpg",
                }
                mock_schema = AsyncMock()
                mock_schema.extract = AsyncMock(return_value=ExtractorResult(products=[schema_product]))
                mock_schema_class.return_value = mock_schema

                # OG returns good data (has title → passes quality gate)
                og_product = {
                    "og:title": "Product",
                    "og:description": "Desc",
                    "og:image": "https://example.com/og-img.jpg",
                }
                mock_og = AsyncMock()
                mock_og.extract = AsyncMock(return_value=ExtractorResult(products=[og_product]))
                # extract_batch returns same product — should get merged with Schema.org partial
                mock_og.extract_batch = AsyncMock(return_value=ExtractorResult(products=[og_product.copy()]))
                mock_og_class.return_value = mock_og

                result = await pipeline.run("job-merge", "https://example.com")

                # OG should win as primary tier
                assert result["extraction_tier"] == "opengraph"
                assert result["total_extracted"] == 1


# ── Shopify API price supplementation tests ──────────────────────────


class TestMatchShopifyProduct:
    """Unit tests for ShopifyPriceSupplementer._match_product()."""

    def test_match_by_url_handle(self):
        """Match Schema.org product to Shopify API product via URL handle."""
        schema = {"name": "Sock Pack", "url": "https://bombas.com/products/sock-4-pack"}
        api_by_handle = {"sock-4-pack": {"handle": "sock-4-pack", "title": "Sock Pack"}}

        result = ShopifyPriceSupplementer._match_product(schema, api_by_handle, {})

        assert result is not None
        assert result["handle"] == "sock-4-pack"

    def test_match_by_title_fallback(self):
        """Fall back to title match when URL has no /products/ segment."""
        schema = {"name": "Sock Pack", "url": "https://bombas.com/sock-pack"}
        api_by_title = {"sock pack": {"handle": "sock-4-pack", "title": "Sock Pack"}}

        result = ShopifyPriceSupplementer._match_product(schema, {}, api_by_title)

        assert result is not None
        assert result["handle"] == "sock-4-pack"

    def test_no_match_returns_none(self):
        """Return None when no match is found."""
        schema = {"name": "Unknown Product", "url": "https://example.com/products/xyz"}
        api_by_handle = {"sock-4-pack": {"handle": "sock-4-pack"}}
        api_by_title = {"sock pack": {"handle": "sock-4-pack"}}

        result = ShopifyPriceSupplementer._match_product(schema, api_by_handle, api_by_title)

        assert result is None

    def test_handle_with_query_params(self):
        """Handle extraction ignores query parameters."""
        schema = {"name": "Shirt", "url": "https://example.com/products/cool-shirt?variant=123"}
        api_by_handle = {"cool-shirt": {"handle": "cool-shirt", "title": "Shirt"}}

        result = ShopifyPriceSupplementer._match_product(schema, api_by_handle, {})

        assert result is not None
        assert result["handle"] == "cool-shirt"

    def test_handle_with_trailing_slash(self):
        """Handle extraction ignores trailing slashes."""
        schema = {"name": "Shirt", "url": "https://example.com/products/cool-shirt/"}
        api_by_handle = {"cool-shirt": {"handle": "cool-shirt", "title": "Shirt"}}

        result = ShopifyPriceSupplementer._match_product(schema, api_by_handle, {})

        assert result is not None

    def test_title_match_case_insensitive(self):
        """Title matching is case-insensitive."""
        schema = {"name": "  Men's QUARTER Top Sock  ", "url": ""}
        api_by_title = {"men's quarter top sock": {"handle": "sock", "title": "Men's Quarter Top Sock"}}

        result = ShopifyPriceSupplementer._match_product(schema, {}, api_by_title)

        assert result is not None


@pytest.mark.asyncio
async def test_supplement_fills_zero_price(mock_circuit_breaker):
    """Zero-price Schema.org products get prices filled from Shopify API."""
    raw_products = [
        {
            "name": "Sock 4-Pack",
            "url": "https://example.com/products/sock-4-pack",
            "@type": "Product",
            # No "offers" key — normalizer would default price to 0
        },
        {
            "name": "T-Shirt",
            "url": "https://example.com/products/t-shirt",
            "@type": "Product",
            "offers": {"price": "28.00", "priceCurrency": "USD"},
        },
    ]

    api_products = [
        {
            "handle": "sock-4-pack",
            "title": "Sock 4-Pack",
            "variants": [{"price": "16.00"}],
            "_shop_currency": "USD",
        },
        {
            "handle": "t-shirt",
            "title": "T-Shirt",
            "variants": [{"price": "32.00"}],
            "_shop_currency": "USD",
        },
    ]

    with patch("app.services.shopify_price_supplementer.ShopifyAPIExtractor") as mock_class:
        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value=ExtractorResult(products=api_products))
        mock_class.return_value = mock_extractor

        supplementer = ShopifyPriceSupplementer(mock_circuit_breaker)
        result = await supplementer.supplement(
            raw_products, "https://example.com"
        )

    # Zero-price product should now have offers with API price
    assert result[0]["offers"]["price"] == "16.00"
    assert result[0]["offers"]["priceCurrency"] == "USD"

    # Already-priced product with matching currency should be untouched
    assert result[1]["offers"]["price"] == "28.00"
    assert result[1]["offers"]["priceCurrency"] == "USD"


@pytest.mark.asyncio
async def test_supplement_corrects_geo_currency(mock_circuit_breaker):
    """Products with geo-targeted currency get corrected to base catalog currency."""
    raw_products = [
        {
            "name": "Hoodie",
            "url": "https://example.com/products/hoodie",
            "offers": {"price": "65.00", "priceCurrency": "EUR"},
        },
        {
            "name": "Sock Pack",
            "url": "https://example.com/products/sock-pack",
            # No offers — zero-price, triggers API fetch
        },
    ]

    api_products = [
        {
            "handle": "hoodie",
            "title": "Hoodie",
            "variants": [{"price": "58.00"}],
            "_shop_currency": "USD",
        },
        {
            "handle": "sock-pack",
            "title": "Sock Pack",
            "variants": [{"price": "16.00"}],
            "_shop_currency": "USD",
        },
    ]

    with patch("app.services.shopify_price_supplementer.ShopifyAPIExtractor") as mock_class:
        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value=ExtractorResult(products=api_products))
        mock_class.return_value = mock_extractor

        supplementer = ShopifyPriceSupplementer(mock_circuit_breaker)
        result = await supplementer.supplement(
            raw_products, "https://example.com"
        )

    # EUR product should be corrected to USD with API price
    assert result[0]["offers"]["price"] == "58.00"
    assert result[0]["offers"]["priceCurrency"] == "USD"

    # Zero-price product should be filled from API
    assert result[1]["offers"]["price"] == "16.00"
    assert result[1]["offers"]["priceCurrency"] == "USD"


@pytest.mark.asyncio
async def test_supplement_no_op_when_api_returns_empty(mock_circuit_breaker):
    """Supplementation is a no-op when Shopify API returns 0 products."""
    raw_products = [
        {
            "name": "Sock",
            "url": "https://example.com/products/sock",
            "@type": "Product",
            # No offers — zero-price
        },
    ]

    with patch("app.services.shopify_price_supplementer.ShopifyAPIExtractor") as mock_class:
        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value=ExtractorResult(products=[]))
        mock_class.return_value = mock_extractor

        supplementer = ShopifyPriceSupplementer(mock_circuit_breaker)
        result = await supplementer.supplement(
            raw_products, "https://example.com"
        )

    # Product should be unchanged (no offers added)
    assert "offers" not in result[0]


@pytest.mark.asyncio
async def test_supplement_no_op_when_all_prices_valid(mock_circuit_breaker):
    """No supplementation needed when all products have valid prices and correct currency."""
    raw_products = [
        {
            "name": "Shirt",
            "url": "https://example.com/products/shirt",
            "offers": {"price": "29.99", "priceCurrency": "USD"},
        },
    ]

    api_products = [
        {
            "handle": "shirt",
            "title": "Shirt",
            "variants": [{"price": "29.99"}],
            "_shop_currency": "USD",
        },
    ]

    with patch("app.services.shopify_price_supplementer.ShopifyAPIExtractor") as mock_class:
        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value=ExtractorResult(products=api_products))
        mock_class.return_value = mock_extractor

        supplementer = ShopifyPriceSupplementer(mock_circuit_breaker)
        result = await supplementer.supplement(
            raw_products, "https://example.com"
        )

    # Price and currency should be unchanged
    assert result[0]["offers"]["price"] == "29.99"
    assert result[0]["offers"]["priceCurrency"] == "USD"


@pytest.mark.asyncio
async def test_supplement_tries_alternative_url(mock_circuit_breaker):
    """Supplementation tries shop.{domain} when main URL API returns empty."""
    raw_products = [
        {
            "name": "Sock",
            "url": "https://bombas.com/products/sock",
            # No offers
        },
    ]

    api_products = [
        {
            "handle": "sock",
            "title": "Sock",
            "variants": [{"price": "12.00"}],
            "_shop_currency": "USD",
        },
    ]

    with patch("app.services.shopify_price_supplementer.ShopifyAPIExtractor") as mock_class:
        mock_extractor = AsyncMock()
        # First call (main URL) → empty, second call (shop.bombas.com) → products
        mock_extractor.extract = AsyncMock(side_effect=[
            ExtractorResult(products=[]),
            ExtractorResult(products=api_products),
        ])
        mock_class.return_value = mock_extractor

        supplementer = ShopifyPriceSupplementer(mock_circuit_breaker)
        result = await supplementer.supplement(
            raw_products, "https://bombas.com"
        )

    # Should have filled from the alternative URL
    assert result[0]["offers"]["price"] == "12.00"
    assert result[0]["offers"]["priceCurrency"] == "USD"

    # Verify both URLs were tried
    assert mock_extractor.extract.call_count == 2
    calls = mock_extractor.extract.call_args_list
    assert "bombas.com" in calls[0][0][0]
    assert "shop.bombas.com" in calls[1][0][0]


@pytest.mark.asyncio
async def test_supplement_handles_offers_as_list(mock_circuit_breaker):
    """Supplementation works when Schema.org 'offers' is a list (not dict)."""
    raw_products = [
        {
            "name": "Multi Offer",
            "url": "https://example.com/products/multi",
            "offers": [{"price": "0", "priceCurrency": "USD"}],
        },
    ]

    api_products = [
        {
            "handle": "multi",
            "title": "Multi Offer",
            "variants": [{"price": "25.00"}],
            "_shop_currency": "USD",
        },
    ]

    with patch("app.services.shopify_price_supplementer.ShopifyAPIExtractor") as mock_class:
        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value=ExtractorResult(products=api_products))
        mock_class.return_value = mock_extractor

        supplementer = ShopifyPriceSupplementer(mock_circuit_breaker)
        result = await supplementer.supplement(
            raw_products, "https://example.com"
        )

    # List-format offers should be updated in place
    assert result[0]["offers"][0]["price"] == "25.00"
    assert result[0]["offers"][0]["priceCurrency"] == "USD"


@pytest.mark.asyncio
async def test_supplement_does_not_overwrite_with_api_zero_price(mock_circuit_breaker):
    """Don't replace Schema.org price with API price if API price is also 0."""
    raw_products = [
        {
            "name": "Discontinued",
            "url": "https://example.com/products/discontinued",
            # No offers
        },
    ]

    api_products = [
        {
            "handle": "discontinued",
            "title": "Discontinued",
            "variants": [{"price": "0"}],
            "_shop_currency": "USD",
        },
    ]

    with patch("app.services.shopify_price_supplementer.ShopifyAPIExtractor") as mock_class:
        mock_extractor = AsyncMock()
        mock_extractor.extract = AsyncMock(return_value=ExtractorResult(products=api_products))
        mock_class.return_value = mock_extractor

        supplementer = ShopifyPriceSupplementer(mock_circuit_breaker)
        result = await supplementer.supplement(
            raw_products, "https://example.com"
        )

    # Should NOT inject zero-price offers from API
    assert "offers" not in result[0]


@pytest.mark.asyncio
async def test_pipeline_shopify_fallback_triggers_supplementation(
    pipeline, mock_progress_tracker
):
    """Full pipeline: Shopify API → 0, Schema.org wins, supplementation fills prices."""
    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = PlatformResult(
            platform=Platform.SHOPIFY,
            confidence=0.9,
            signals=["api:/products.json"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = [
                "https://example.com/products/sock",
                "https://example.com/products/shirt",
            ]

            with patch("app.services.pipeline.ShopifyAPIExtractor") as mock_shopify_class, \
                 patch("app.services.shopify_price_supplementer.ShopifyAPIExtractor", mock_shopify_class):
                api_products = [
                    {
                        "handle": "sock",
                        "title": "Sock",
                        "variants": [{"price": "12.00"}],
                        "_shop_currency": "USD",
                    },
                    {
                        "handle": "shirt",
                        "title": "Shirt",
                        "variants": [{"price": "25.00"}],
                        "_shop_currency": "USD",
                    },
                ]

                mock_shopify = AsyncMock()
                # Calls: 1) initial API try→empty, 2) supplement main→empty, 3) supplement alt→products
                mock_shopify.extract = AsyncMock(side_effect=[
                    ExtractorResult(products=[]),
                    ExtractorResult(products=[]),
                    ExtractorResult(products=api_products),
                ])
                mock_shopify_class.return_value = mock_shopify

                # Schema.org returns products but with zero prices (no offers)
                with patch("app.services.pipeline.SchemaOrgExtractor") as mock_schema_class:
                    schema_product_sock = {
                        "name": "Sock",
                        "@type": "Product",
                        "url": "https://example.com/products/sock",
                        "image": "https://example.com/sock.jpg",
                        "description": "A sock",
                    }
                    schema_product_shirt = {
                        "name": "Shirt",
                        "@type": "Product",
                        "url": "https://example.com/products/shirt",
                        "image": "https://example.com/shirt.jpg",
                        "description": "A shirt",
                        "offers": {"price": "30.00", "priceCurrency": "EUR"},
                    }

                    mock_schema = AsyncMock()
                    mock_schema.extract = AsyncMock(
                        side_effect=[
                            ExtractorResult(products=[schema_product_sock]),  # probe
                            ExtractorResult(products=[schema_product_sock]),  # URL 1
                            ExtractorResult(products=[schema_product_shirt]),  # URL 2
                        ]
                    )
                    mock_schema_class.return_value = mock_schema

                    result = await pipeline.run(
                        "job-supplement", "https://example.com"
                    )

                    assert result["platform"] == "shopify"
                    assert result["extraction_tier"] == "schema_org"
                    assert result["total_normalized"] == 2


# ── Issue #66: CircuitOpenError handling ──────────────────────────────────────


@pytest.mark.asyncio
async def test_circuit_open_error_returns_empty_not_raises(pipeline, mock_progress_tracker):
    """CircuitOpenError in _extract_with_circuit_breaker logs WARNING and returns []."""
    from app.exceptions.errors import CircuitOpenError

    extractor = AsyncMock()
    extractor.extract = AsyncMock(return_value=ExtractorResult(products=[{"title": "x"}]))

    # Make circuit_breaker.call raise CircuitOpenError
    pipeline.circuit_breaker.call = AsyncMock(
        side_effect=CircuitOpenError("example.com")
    )

    result = await pipeline._extract_with_circuit_breaker(
        extractor, "https://example.com/product", "example.com"
    )

    # Must return [] without propagating the exception
    assert result == []


@pytest.mark.asyncio
async def test_circuit_open_error_logged_at_warning_not_error(
    pipeline, mock_progress_tracker, caplog
):
    """CircuitOpenError must be logged at WARNING level, not ERROR."""
    import logging
    from app.exceptions.errors import CircuitOpenError

    caplog.set_level(logging.WARNING)

    extractor = AsyncMock()
    pipeline.circuit_breaker.call = AsyncMock(
        side_effect=CircuitOpenError("example.com")
    )

    await pipeline._extract_with_circuit_breaker(
        extractor, "https://example.com/product", "example.com"
    )

    # Should be WARNING, not ERROR
    warnings = [r for r in caplog.records if r.levelname == "WARNING"]
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert any("Circuit breaker OPEN" in r.message or "Circuit" in r.message for r in warnings)
    assert not any("Circuit breaker OPEN" in r.message for r in errors)


@pytest.mark.asyncio
async def test_non_circuit_error_propagates_from_extract_with_circuit_breaker(pipeline):
    """Non-CircuitOpenError exceptions should propagate from _extract_with_circuit_breaker."""
    extractor = AsyncMock()

    async def call_passthrough(domain, coro):
        return await coro()

    pipeline.circuit_breaker.call = AsyncMock(side_effect=call_passthrough)
    extractor.extract = AsyncMock(side_effect=ValueError("bad extractor"))

    with pytest.raises(ValueError, match="bad extractor"):
        await pipeline._extract_with_circuit_breaker(
            extractor, "https://example.com/product", "example.com"
        )


@pytest.mark.asyncio
async def test_circuit_open_in_tracked_extraction_counts_as_skip_not_error(
    pipeline, mock_progress_tracker
):
    """CircuitOpenError in _extract_from_urls_tracked is a skip, not recorded as error."""
    from app.exceptions.errors import CircuitOpenError
    from app.services.extraction_tracker import ExtractionTracker

    tracker = ExtractionTracker()
    extractor = AsyncMock()

    # All circuit_breaker.call raises CircuitOpenError
    pipeline.circuit_breaker.call = AsyncMock(
        side_effect=CircuitOpenError("example.com")
    )

    urls = [f"https://example.com/product-{i}" for i in range(3)]
    result = await pipeline._extract_from_urls_tracked(
        extractor, urls, "example.com", "job-123", tracker
    )

    # Returns empty (skipped), not error
    assert result == []

    # ExtractionTracker should have 0 error records (circuit-open = skip)
    audit = tracker.build_audit()
    assert audit.urls_errored == 0


# ── Issue #67: Catastrophic error rate detection ──────────────────────────────


@pytest.mark.asyncio
async def test_catastrophic_error_rate_raises_extraction_error(
    pipeline, mock_progress_tracker
):
    """_extract_from_urls_tracked raises ExtractionError when >80% of URLs fail."""
    from app.exceptions.errors import ExtractionError
    from app.services.extraction_tracker import ExtractionTracker

    tracker = ExtractionTracker()
    extractor = AsyncMock()

    async def passthrough(domain, coro):
        return await coro()

    pipeline.circuit_breaker.call = AsyncMock(side_effect=passthrough)
    # All extractions fail with an exception
    extractor.extract = AsyncMock(side_effect=RuntimeError("Connection refused"))

    # 9 URLs -- all fail => 100% error rate > 80%
    urls = [f"https://example.com/product-{i}" for i in range(9)]

    with pytest.raises(ExtractionError, match="Catastrophic error rate"):
        await pipeline._extract_from_urls_tracked(
            extractor, urls, "example.com", "job-123", tracker
        )


@pytest.mark.asyncio
async def test_catastrophic_error_rate_not_raised_below_threshold(
    pipeline, mock_progress_tracker
):
    """Error rate <= 80% does not raise ExtractionError."""
    from app.exceptions.errors import ExtractionError
    from app.services.extraction_tracker import ExtractionTracker

    tracker = ExtractionTracker()
    extractor = AsyncMock()

    call_count = 0

    async def passthrough(domain, coro):
        return await coro()

    pipeline.circuit_breaker.call = AsyncMock(side_effect=passthrough)

    async def partial_fail(url):
        nonlocal call_count
        call_count += 1
        # 4 out of 10 fail (~40% error rate)
        if call_count <= 4:
            raise RuntimeError("fail")
        return ExtractorResult(products=[{"title": "ok", "offers": {"price": "10"}}])

    extractor.extract = AsyncMock(side_effect=partial_fail)

    urls = [f"https://example.com/product-{i}" for i in range(10)]

    # Should not raise ExtractionError
    result = await pipeline._extract_from_urls_tracked(
        extractor, urls, "example.com", "job-123", tracker
    )
    # 6 successful extractions, each returning 1 product
    assert len(result) == 6


@pytest.mark.asyncio
async def test_catastrophic_error_rate_not_raised_with_5_or_fewer_urls(
    pipeline, mock_progress_tracker
):
    """With 5 or fewer URLs, error rate check is not applied (insufficient sample)."""
    from app.exceptions.errors import ExtractionError
    from app.services.extraction_tracker import ExtractionTracker

    tracker = ExtractionTracker()
    extractor = AsyncMock()

    async def passthrough(domain, coro):
        return await coro()

    pipeline.circuit_breaker.call = AsyncMock(side_effect=passthrough)
    extractor.extract = AsyncMock(side_effect=RuntimeError("fail"))

    # Only 5 URLs -- all fail but check requires >5 to trigger
    urls = [f"https://example.com/product-{i}" for i in range(5)]

    # Should NOT raise even with 100% failure rate
    result = await pipeline._extract_from_urls_tracked(
        extractor, urls, "example.com", "job-123", tracker
    )
    assert result == []


# ── Timeout preserves progress counts ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_timeout_preserves_existing_progress_counts(pipeline, mock_progress_tracker):
    """On pipeline timeout, progress update uses actual processed/total from Redis."""
    # Mock progress.get to return existing progress state
    mock_progress_tracker.get = AsyncMock(
        return_value={"processed": 42, "total": 100}
    )

    async def slow_inner(job_id, shop_url):
        await asyncio.sleep(999)

    pipeline._run_inner = slow_inner

    with pytest.raises(asyncio.TimeoutError):
        await pipeline.run("job-timeout", "https://example.com", timeout=0.01)

    # Find the FAILED status update call
    failed_calls = [
        call for call in mock_progress_tracker.update.call_args_list
        if call[1].get("status") == JobStatus.FAILED
    ]
    assert failed_calls, "Expected a FAILED status update"

    failed_call = failed_calls[-1]
    # Progress counts should be preserved from Redis, not reset to 0
    assert failed_call[1]["processed"] == 42
    assert failed_call[1]["total"] == 100
    assert "timed out" in failed_call[1]["current_step"].lower()


@pytest.mark.asyncio
async def test_timeout_uses_zero_counts_when_no_prior_progress(pipeline, mock_progress_tracker):
    """On timeout with no prior progress data (get returns None), defaults to 0."""
    mock_progress_tracker.get = AsyncMock(return_value=None)

    async def slow_inner(job_id, shop_url):
        await asyncio.sleep(999)

    pipeline._run_inner = slow_inner

    with pytest.raises(asyncio.TimeoutError):
        await pipeline.run("job-timeout-no-prior", "https://example.com", timeout=0.01)

    failed_calls = [
        call for call in mock_progress_tracker.update.call_args_list
        if call[1].get("status") == JobStatus.FAILED
    ]
    assert failed_calls
    failed_call = failed_calls[-1]
    assert failed_call[1]["processed"] == 0
    assert failed_call[1]["total"] == 0


# ── Normalization drop rate logging ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_normalization_drop_rate_warning_logged(pipeline, mock_progress_tracker, caplog):
    """Warning is logged when normalization drops products."""
    import logging
    caplog.set_level(logging.WARNING)

    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = MagicMock(
            platform=Platform.SHOPIFY,
            confidence=0.9,
            signals=["api:/products.json"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = ["https://example.com/products.json"]

            with patch("app.services.pipeline.ShopifyAPIExtractor") as mock_shopify_class:
                # Return 5 raw products
                raw = [
                    {"id": i, "title": f"Product {i}", "handle": f"prod-{i}",
                     "variants": [{"price": "10"}]}
                    for i in range(5)
                ]
                mock_shopify = AsyncMock()
                mock_shopify.extract = AsyncMock(return_value=ExtractorResult(products=raw))
                mock_shopify_class.return_value = mock_shopify

                # Normalizer drops all but 1 (80% drop rate > 50%)
                original_normalize = pipeline.normalizer.normalize
                call_idx = 0

                def drop_most(raw, shop_id, platform, shop_url):
                    nonlocal call_idx
                    call_idx += 1
                    # Return None for 4 out of 5 products (drop 80%)
                    if call_idx > 1:
                        return None
                    return original_normalize(raw, shop_id=shop_id, platform=platform, shop_url=shop_url)

                pipeline.normalizer.normalize = drop_most

                await pipeline.run("job-drop-rate", "https://example.com")

                # Warning about drop rate should be logged
                warnings = [r.message for r in caplog.records if r.levelname == "WARNING"]
                assert any("drop" in w.lower() or "dropped" in w.lower() for w in warnings)


@pytest.mark.asyncio
async def test_normalization_drop_rate_error_logged_above_50_percent(
    pipeline, mock_progress_tracker, caplog
):
    """Error is logged when normalization drop rate exceeds 50%."""
    import logging
    caplog.set_level(logging.ERROR)

    with patch("app.services.pipeline.PlatformDetector.detect") as mock_detect:
        mock_detect.return_value = MagicMock(
            platform=Platform.SHOPIFY,
            confidence=0.9,
            signals=["api:/products.json"],
        )

        with patch("app.services.pipeline.URLDiscoveryService.discover") as mock_discover:
            mock_discover.return_value = ["https://example.com/products.json"]

            with patch("app.services.pipeline.ShopifyAPIExtractor") as mock_shopify_class:
                raw = [
                    {"id": i, "title": f"Product {i}", "handle": f"prod-{i}",
                     "variants": [{"price": "10"}]}
                    for i in range(10)
                ]
                mock_shopify = AsyncMock()
                mock_shopify.extract = AsyncMock(return_value=ExtractorResult(products=raw))
                mock_shopify_class.return_value = mock_shopify

                # Normalizer drops 9 out of 10 (90% drop rate)
                call_idx = 0

                def drop_most(raw, shop_id, platform, shop_url):
                    nonlocal call_idx
                    call_idx += 1
                    if call_idx > 1:
                        return None
                    from app.models.product import Product
                    from app.models.enums import Platform as PlatformEnum
                    from decimal import Decimal
                    from datetime import datetime, timezone
                    import hashlib, json
                    return Product(
                        external_id=str(raw.get("id", "1")),
                        shop_id=shop_id,
                        platform=platform,
                        title=raw.get("title", "Test"),
                        description="test",
                        price=Decimal("10.00"),
                        currency="USD",
                        image_url="https://example.com/img.jpg",
                        product_url="https://example.com/product",
                        in_stock=True,
                        variants=[],
                        tags=[],
                        raw_data=raw,
                        scraped_at=datetime.now(timezone.utc),
                        idempotency_key=hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest(),
                    )

                pipeline.normalizer.normalize = drop_most

                await pipeline.run("job-high-drop", "https://example.com")

                # Error log about >50% drop rate should be present
                errors = [r.message for r in caplog.records if r.levelname == "ERROR"]
                assert any("50%" in e or "mismatch" in e.lower() or "drop" in e.lower() for e in errors)


# ── _urls_still_missing_price tests ──────────────────────────────────────


class TestUrlsStillMissingPrice:
    """Tests for Pipeline._urls_still_missing_price."""

    def test_all_prices_filled(self):
        """URLs where products have valid prices are excluded."""
        products = [
            {"_source_url": "https://shop.com/a", "price": "19.99"},
            {"_source_url": "https://shop.com/b", "price": "29.99"},
        ]
        url_to_idx = {"https://shop.com/a": [0], "https://shop.com/b": [1]}
        result = Pipeline._urls_still_missing_price(
            products, ["https://shop.com/a", "https://shop.com/b"], url_to_idx
        )
        assert result == []

    def test_zero_price_still_missing(self):
        """Products with price=0 are treated as missing."""
        products = [
            {"_source_url": "https://shop.com/a", "price": "0"},
        ]
        url_to_idx = {"https://shop.com/a": [0]}
        result = Pipeline._urls_still_missing_price(
            products, ["https://shop.com/a"], url_to_idx
        )
        assert result == ["https://shop.com/a"]

    def test_no_price_field_missing(self):
        """Products without any price field are treated as missing."""
        products = [
            {"_source_url": "https://shop.com/a", "title": "No Price Product"},
        ]
        url_to_idx = {"https://shop.com/a": [0]}
        result = Pipeline._urls_still_missing_price(
            products, ["https://shop.com/a"], url_to_idx
        )
        assert result == ["https://shop.com/a"]

    def test_offers_dict_with_zero_price(self):
        """Products with offers.price=0 are treated as missing."""
        products = [
            {"_source_url": "https://shop.com/a", "offers": {"price": "0.00"}},
        ]
        url_to_idx = {"https://shop.com/a": [0]}
        result = Pipeline._urls_still_missing_price(
            products, ["https://shop.com/a"], url_to_idx
        )
        assert result == ["https://shop.com/a"]

    def test_offers_dict_with_valid_price(self):
        """Products with offers.price>0 are not missing."""
        products = [
            {"_source_url": "https://shop.com/a", "offers": {"price": "14.50"}},
        ]
        url_to_idx = {"https://shop.com/a": [0]}
        result = Pipeline._urls_still_missing_price(
            products, ["https://shop.com/a"], url_to_idx
        )
        assert result == []

    def test_mixed_urls(self):
        """Only URLs still missing prices are returned."""
        products = [
            {"_source_url": "https://shop.com/a", "price": "19.99"},
            {"_source_url": "https://shop.com/b", "price": "0"},
            {"_source_url": "https://shop.com/c", "title": "No price at all"},
        ]
        url_to_idx = {
            "https://shop.com/a": [0],
            "https://shop.com/b": [1],
            "https://shop.com/c": [2],
        }
        result = Pipeline._urls_still_missing_price(
            products,
            ["https://shop.com/a", "https://shop.com/b", "https://shop.com/c"],
            url_to_idx,
        )
        assert "https://shop.com/a" not in result
        assert "https://shop.com/b" in result
        assert "https://shop.com/c" in result

    def test_numeric_price_zero(self):
        """Numeric 0 price is treated as missing."""
        products = [
            {"_source_url": "https://shop.com/a", "price": 0},
        ]
        url_to_idx = {"https://shop.com/a": [0]}
        result = Pipeline._urls_still_missing_price(
            products, ["https://shop.com/a"], url_to_idx
        )
        assert result == ["https://shop.com/a"]

    def test_numeric_price_nonzero(self):
        """Numeric non-zero price is not missing."""
        products = [
            {"_source_url": "https://shop.com/a", "price": 12.50},
        ]
        url_to_idx = {"https://shop.com/a": [0]}
        result = Pipeline._urls_still_missing_price(
            products, ["https://shop.com/a"], url_to_idx
        )
        assert result == []

    def test_empty_candidate_urls(self):
        """Empty candidate list returns empty."""
        assert Pipeline._urls_still_missing_price([], [], {}) == []


# ── _browser_price_reextract tests ───────────────────────────────────────


class TestBrowserPriceReextract:
    """Tests for Pipeline._browser_price_reextract."""

    @pytest.fixture
    def pipeline(self, mock_progress_tracker, mock_circuit_breaker, mock_rate_limiter):
        return Pipeline(
            progress_tracker=mock_progress_tracker,
            circuit_breaker=mock_circuit_breaker,
            rate_limiter=mock_rate_limiter,
        )

    async def test_fills_missing_price_from_browser(self, pipeline):
        """Browser CSS extraction fills missing price field."""
        products = [
            {"_source_url": "https://shop.com/a", "title": "Tea"},
        ]
        url_to_indices = {"https://shop.com/a": [0]}

        mock_result = ExtractorResult(
            products=[{"price": "$4.99", "title": "Tea"}]
        )

        with patch.object(CSSExtractor, "extract", new_callable=AsyncMock, return_value=mock_result):
            await pipeline._browser_price_reextract(
                products, ["https://shop.com/a"], url_to_indices, "https://shop.com"
            )

        assert products[0]["price"] == "$4.99"

    async def test_does_not_overwrite_existing_title(self, pipeline):
        """Browser CSS extraction does not overwrite existing non-empty fields."""
        products = [
            {"_source_url": "https://shop.com/a", "title": "My Tea"},
        ]
        url_to_indices = {"https://shop.com/a": [0]}

        mock_result = ExtractorResult(
            products=[{"price": "$4.99", "title": "Different Tea"}]
        )

        with patch.object(CSSExtractor, "extract", new_callable=AsyncMock, return_value=mock_result):
            await pipeline._browser_price_reextract(
                products, ["https://shop.com/a"], url_to_indices, "https://shop.com"
            )

        # Price filled, but title was NOT overwritten (it had a truthy value)
        assert products[0]["price"] == "$4.99"
        assert products[0]["title"] == "My Tea"

    async def test_handles_extraction_failure(self, pipeline):
        """Browser CSS extraction failure does not crash — products unchanged."""
        products = [
            {"_source_url": "https://shop.com/a", "title": "Tea"},
        ]
        url_to_indices = {"https://shop.com/a": [0]}

        with patch.object(CSSExtractor, "extract", new_callable=AsyncMock, side_effect=Exception("Browser crashed")):
            await pipeline._browser_price_reextract(
                products, ["https://shop.com/a"], url_to_indices, "https://shop.com"
            )

        # Product unchanged — no crash
        assert "price" not in products[0]


@pytest.mark.asyncio
async def test_pipeline_http_client_none_does_not_crash_finally(pipeline):
    """If an exception occurs before _http_client is created, finally block must not crash.

    Before the fix, the finally block called `await self._http_client.aclose()`
    unconditionally — when _http_client was still None, this raised AttributeError
    and swallowed the original exception.
    """
    assert pipeline._http_client is None  # Not yet created

    with patch("app.services.pipeline.normalize_shop_url", side_effect=ValueError("bad url")):
        # The original ValueError must propagate, NOT an AttributeError from aclose()
        with pytest.raises(ValueError, match="bad url"):
            await pipeline.run("job-err", "not-a-url")

    # _http_client should still be None (never created)
    assert pipeline._http_client is None
    async def test_handles_empty_result(self, pipeline):
        """Browser CSS extraction returning empty products does not crash."""
        products = [
            {"_source_url": "https://shop.com/a", "title": "Tea"},
        ]
        url_to_indices = {"https://shop.com/a": [0]}

        mock_result = ExtractorResult(products=[])

        with patch.object(CSSExtractor, "extract", new_callable=AsyncMock, return_value=mock_result):
            await pipeline._browser_price_reextract(
                products, ["https://shop.com/a"], url_to_indices, "https://shop.com"
            )

        assert "price" not in products[0]
