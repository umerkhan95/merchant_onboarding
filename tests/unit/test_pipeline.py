"""Unit tests for pipeline orchestrator."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.models.enums import JobStatus, Platform
from app.services.pipeline import Pipeline
from app.services.platform_detector import PlatformResult


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
                    return_value=[
                        {
                            "id": 123,
                            "title": "Test Product",
                            "handle": "test-product",
                            "body_html": "<p>Description</p>",
                            "variants": [{"id": 456, "price": "19.99"}],
                            "images": [{"src": "https://example.com/image.jpg"}],
                        }
                    ]
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
                    return_value=[
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
                    ]
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
                mock_extractor = AsyncMock()
                # First call returns data (probe), subsequent calls also return data
                mock_extractor.extract = AsyncMock(
                    return_value=[
                        {
                            "name": "Schema.org Product",
                            "description": "Product description",
                            "offers": {"price": "49.99", "priceCurrency": "USD"},
                            "image": "https://example.com/image.jpg",
                            "sku": "SKU123",
                        }
                    ]
                )
                mock_extractor_class.return_value = mock_extractor

                result = await pipeline.run("job-789", "https://example.com")

                assert result["platform"] == "generic"
                assert result["total_extracted"] == 2  # 2 URLs
                assert result["extraction_tier"] == "sitemap_css"


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
    """Test pipeline handles extraction failure gracefully."""
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

                # Circuit breaker will catch the error and return empty list
                result = await pipeline.run("job-error", "https://example.com")

                # Should complete but with 0 products
                assert result["total_extracted"] == 0
                assert result["total_normalized"] == 0


@pytest.mark.asyncio
async def test_pipeline_no_urls_discovered(pipeline, mock_progress_tracker):
    """Test pipeline when no URLs are discovered."""
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

            # Should complete successfully
            last_call = mock_progress_tracker.update.call_args_list[-1]
            assert last_call[1]["status"] == JobStatus.COMPLETED


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
                    return_value=[
                        {
                            "id": 1,
                            "title": "Product",
                            "handle": "product",
                            "variants": [{"price": "10"}],
                        }
                    ]
                )
                mock_extractor_class.return_value = mock_extractor

                await pipeline.run("job-progress", "https://example.com")

                # Extract all status values from calls
                statuses = [
                    call[1]["status"] for call in mock_progress_tracker.update.call_args_list
                ]

                # Verify we went through all steps
                assert JobStatus.DETECTING in statuses
                assert JobStatus.DISCOVERING in statuses
                assert JobStatus.EXTRACTING in statuses
                assert JobStatus.NORMALIZING in statuses
                assert JobStatus.INGESTING in statuses
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
                    return_value=[
                        {
                            "id": 1,
                            "title": "Product",
                            "handle": "product",
                            "variants": [{"price": "10"}],
                        }
                    ]
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
                    return_value=[
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
                    ]
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
                mock_schema.extract = AsyncMock(return_value=[])
                mock_schema_class.return_value = mock_schema

                mock_og = AsyncMock()
                mock_og.extract = AsyncMock(return_value=[])
                mock_og_class.return_value = mock_og

                mock_css = AsyncMock()
                mock_css.extract = AsyncMock(
                    return_value=[
                        {
                            "title": "BigCommerce Product",
                            "price": "$29.99",
                            "description": "Product description",
                            "image": "https://example.com/image.jpg",
                            "sku": "BC-123",
                        }
                    ]
                )
                mock_css_class.return_value = mock_css

                result = await pipeline.run("job-bigcommerce", "https://example.com")

                assert result["platform"] == "bigcommerce"
                assert result["total_extracted"] == 2  # 2 URLs
                assert result["extraction_tier"] == "deep_crawl"
