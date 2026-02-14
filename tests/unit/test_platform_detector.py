"""Unit tests for the platform detector service."""

from __future__ import annotations

import httpx
import pytest
import respx

from app.models.enums import Platform
from app.services.platform_detector import PlatformDetector

# ---------------------------------------------------------------------------
# Shopify Detection Tests
# ---------------------------------------------------------------------------


class TestShopifyDetection:
    """Test Shopify platform detection via various signals."""

    @pytest.mark.asyncio
    async def test_shopify_detection_via_header(self) -> None:
        """Shopify detected via X-ShopId header."""
        detector = PlatformDetector()

        with respx.mock:
            # Mock HEAD request with Shopify header
            respx.head("https://shop.example.com").mock(
                return_value=httpx.Response(200, headers={"X-ShopId": "12345"})
            )
            # Mock other probes
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text="<html></html>"))

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.SHOPIFY
            assert "header:x-shopify" in result.signals
            assert result.confidence > 0.0

    @pytest.mark.asyncio
    async def test_shopify_detection_via_api(self) -> None:
        """Shopify detected via /products.json API endpoint."""
        detector = PlatformDetector()

        shopify_products_response = {"products": [{"id": 1, "title": "Test Product"}]}

        with respx.mock:
            # Mock HEAD request
            respx.head("https://shop.example.com").mock(return_value=httpx.Response(200))
            # Mock Shopify API
            respx.get("https://shop.example.com/products.json").mock(
                return_value=httpx.Response(200, json=shopify_products_response)
            )
            # Mock other probes
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text="<html></html>"))

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.SHOPIFY
            assert "api:/products.json" in result.signals
            assert result.confidence > 0.0

    @pytest.mark.asyncio
    async def test_shopify_detection_via_meta_tag(self) -> None:
        """Shopify detected via meta generator tag."""
        detector = PlatformDetector()

        html_content = """
        <html>
            <head>
                <meta name="generator" content="Shopify">
            </head>
            <body></body>
        </html>
        """

        with respx.mock:
            respx.head("https://shop.example.com").mock(return_value=httpx.Response(200))
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text=html_content))

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.SHOPIFY
            assert "meta:generator=shopify" in result.signals

    @pytest.mark.asyncio
    async def test_shopify_detection_via_cdn(self) -> None:
        """Shopify detected via CDN reference."""
        detector = PlatformDetector()

        html_content = """
        <html>
            <head>
                <script src="https://cdn.shopify.com/s/files/1/theme.js"></script>
            </head>
            <body></body>
        </html>
        """

        with respx.mock:
            respx.head("https://shop.example.com").mock(return_value=httpx.Response(200))
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text=html_content))

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.SHOPIFY
            assert "cdn:cdn.shopify.com" in result.signals

    @pytest.mark.asyncio
    async def test_shopify_high_confidence_multiple_signals(self) -> None:
        """Shopify detection with multiple signals yields high confidence."""
        detector = PlatformDetector()

        shopify_products_response = {"products": []}
        html_content = """
        <html>
            <head>
                <meta name="generator" content="Shopify">
                <script src="https://cdn.shopify.com/theme.js"></script>
            </head>
        </html>
        """

        with respx.mock:
            # Mock all signals
            respx.head("https://shop.example.com").mock(
                return_value=httpx.Response(200, headers={"X-ShopId": "12345"})
            )
            respx.get("https://shop.example.com/products.json").mock(
                return_value=httpx.Response(200, json=shopify_products_response)
            )
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text=html_content))

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.SHOPIFY
            assert len(result.signals) == 4  # header, api, meta, cdn
            assert result.confidence == 1.0  # 4/4 signals


# ---------------------------------------------------------------------------
# WooCommerce Detection Tests
# ---------------------------------------------------------------------------


class TestWooCommerceDetection:
    """Test WooCommerce platform detection."""

    @pytest.mark.asyncio
    async def test_woocommerce_detection_via_header(self) -> None:
        """WooCommerce detected via Link header with wp-json."""
        detector = PlatformDetector()

        with respx.mock:
            respx.head("https://shop.example.com").mock(
                return_value=httpx.Response(
                    200, headers={"Link": '<https://shop.example.com/wp-json/>; rel="https://api.w.org/"'}
                )
            )
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text="<html></html>"))

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.WOOCOMMERCE
            assert "header:wp-json-link" in result.signals

    @pytest.mark.asyncio
    async def test_woocommerce_detection_via_api(self) -> None:
        """WooCommerce detected via /wp-json/ endpoint."""
        detector = PlatformDetector()

        wp_json_response = {"namespaces": ["wp/v2", "wc/v3"], "routes": {}}

        with respx.mock:
            respx.head("https://shop.example.com").mock(return_value=httpx.Response(200))
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/wp-json/").mock(
                return_value=httpx.Response(200, json=wp_json_response)
            )
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text="<html></html>"))

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.WOOCOMMERCE
            assert "api:/wp-json/" in result.signals

    @pytest.mark.asyncio
    async def test_woocommerce_detection_via_meta_tag(self) -> None:
        """WooCommerce detected via WordPress meta generator."""
        detector = PlatformDetector()

        html_content = """
        <html>
            <head>
                <meta name="generator" content="WordPress 6.4">
            </head>
        </html>
        """

        with respx.mock:
            respx.head("https://shop.example.com").mock(return_value=httpx.Response(200))
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text=html_content))

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.WOOCOMMERCE
            assert "meta:generator=wordpress" in result.signals

    @pytest.mark.asyncio
    async def test_woocommerce_detection_via_plugin_path(self) -> None:
        """WooCommerce detected via plugin path in HTML."""
        detector = PlatformDetector()

        html_content = """
        <html>
            <head>
                <link rel="stylesheet" href="/wp-content/plugins/woocommerce/assets/css/style.css">
            </head>
        </html>
        """

        with respx.mock:
            respx.head("https://shop.example.com").mock(return_value=httpx.Response(200))
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text=html_content))

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.WOOCOMMERCE
            assert "cdn:woocommerce-plugin" in result.signals


# ---------------------------------------------------------------------------
# Magento Detection Tests
# ---------------------------------------------------------------------------


class TestMagentoDetection:
    """Test Magento platform detection."""

    @pytest.mark.asyncio
    async def test_magento_detection_via_header(self) -> None:
        """Magento detected via X-Magento-* headers."""
        detector = PlatformDetector()

        with respx.mock:
            respx.head("https://shop.example.com").mock(
                return_value=httpx.Response(200, headers={"X-Magento-Cache-Debug": "HIT", "X-Magento-Tags": "store"})
            )
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text="<html></html>"))

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.MAGENTO
            assert "header:x-magento" in result.signals

    @pytest.mark.asyncio
    async def test_magento_detection_via_api(self) -> None:
        """Magento detected via REST API endpoint."""
        detector = PlatformDetector()

        magento_api_response = [{"id": 1, "code": "default", "name": "Default Store View"}]

        with respx.mock:
            respx.head("https://shop.example.com").mock(return_value=httpx.Response(200))
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(
                return_value=httpx.Response(200, json=magento_api_response)
            )
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text="<html></html>"))

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.MAGENTO
            assert "api:/rest/V1/store/storeConfigs" in result.signals


# ---------------------------------------------------------------------------
# BigCommerce Detection Tests
# ---------------------------------------------------------------------------


class TestBigCommerceDetection:
    """Test BigCommerce platform detection."""

    @pytest.mark.asyncio
    async def test_bigcommerce_detection_via_meta_tag(self) -> None:
        """BigCommerce detected via meta platform tag."""
        detector = PlatformDetector()

        html_content = """
        <html>
            <head>
                <meta name="platform" content="bigcommerce.stencil">
            </head>
        </html>
        """

        with respx.mock:
            respx.head("https://shop.example.com").mock(return_value=httpx.Response(200))
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text=html_content))

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.BIGCOMMERCE
            assert "meta:platform=bigcommerce" in result.signals

    @pytest.mark.asyncio
    async def test_bigcommerce_detection_via_cdn(self) -> None:
        """BigCommerce detected via CDN reference."""
        detector = PlatformDetector()

        html_content = """
        <html>
            <head>
                <script src="https://cdn.bigcommerce.com/assets/theme.js"></script>
            </head>
        </html>
        """

        with respx.mock:
            respx.head("https://shop.example.com").mock(return_value=httpx.Response(200))
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text=html_content))

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.BIGCOMMERCE
            assert "cdn:cdn.bigcommerce.com" in result.signals


# ---------------------------------------------------------------------------
# Generic Fallback Tests
# ---------------------------------------------------------------------------


class TestGenericFallback:
    """Test generic platform fallback when no platform detected."""

    @pytest.mark.asyncio
    async def test_generic_fallback_no_signals(self) -> None:
        """Generic platform returned when no signals detected."""
        detector = PlatformDetector()

        with respx.mock:
            # All probes return empty/404
            respx.head("https://shop.example.com").mock(return_value=httpx.Response(200))
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(
                return_value=httpx.Response(200, text="<html><body>Plain HTML</body></html>")
            )

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.GENERIC
            assert "fallback:no-signals-detected" in result.signals
            assert result.confidence == 1.0  # 1/1 for fallback


# ---------------------------------------------------------------------------
# Confidence Score Tests
# ---------------------------------------------------------------------------


class TestConfidenceScore:
    """Test confidence score calculation."""

    @pytest.mark.asyncio
    async def test_confidence_score_single_signal(self) -> None:
        """Confidence score with 1/4 signals for Shopify."""
        detector = PlatformDetector()

        with respx.mock:
            respx.head("https://shop.example.com").mock(
                return_value=httpx.Response(200, headers={"X-ShopId": "12345"})
            )
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text="<html></html>"))

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.SHOPIFY
            assert len(result.signals) == 1
            assert result.confidence == 0.25  # 1/4 signals

    @pytest.mark.asyncio
    async def test_confidence_score_half_signals(self) -> None:
        """Confidence score with 2/4 signals for Shopify."""
        detector = PlatformDetector()

        html_content = """<html><head><meta name="generator" content="Shopify"></head></html>"""

        with respx.mock:
            respx.head("https://shop.example.com").mock(
                return_value=httpx.Response(200, headers={"X-ShopId": "12345"})
            )
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text=html_content))

            result = await detector.detect("https://shop.example.com")

            assert result.platform == Platform.SHOPIFY
            assert len(result.signals) == 2
            assert result.confidence == 0.5  # 2/4 signals


# ---------------------------------------------------------------------------
# Timeout Handling Tests
# ---------------------------------------------------------------------------


class TestTimeoutHandling:
    """Test timeout handling for various probes."""

    @pytest.mark.asyncio
    async def test_timeout_on_api_probe(self) -> None:
        """Detection continues when API probe times out."""
        detector = PlatformDetector()

        html_content = """<html><head><meta name="generator" content="Shopify"></head></html>"""

        with respx.mock:
            respx.head("https://shop.example.com").mock(return_value=httpx.Response(200))
            # Simulate timeout on API probe
            respx.get("https://shop.example.com/products.json").mock(side_effect=httpx.TimeoutException("Timeout"))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text=html_content))

            result = await detector.detect("https://shop.example.com")

            # Should still detect via meta tag
            assert result.platform == Platform.SHOPIFY
            assert "meta:generator=shopify" in result.signals

    @pytest.mark.asyncio
    async def test_timeout_on_html_probe(self) -> None:
        """Detection continues when HTML probe times out."""
        detector = PlatformDetector()

        with respx.mock:
            respx.head("https://shop.example.com").mock(
                return_value=httpx.Response(200, headers={"X-ShopId": "12345"})
            )
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            # Simulate timeout on HTML probe
            respx.get("https://shop.example.com").mock(side_effect=httpx.TimeoutException("Timeout"))

            result = await detector.detect("https://shop.example.com")

            # Should still detect via header
            assert result.platform == Platform.SHOPIFY
            assert "header:x-shopify" in result.signals


# ---------------------------------------------------------------------------
# Edge Cases
# ---------------------------------------------------------------------------


class TestEdgeCases:
    """Test edge cases and error conditions."""

    @pytest.mark.asyncio
    async def test_url_with_trailing_slash(self) -> None:
        """URL with trailing slash is handled correctly."""
        detector = PlatformDetector()

        shopify_products_response = {"products": []}

        with respx.mock:
            respx.head("https://shop.example.com/").mock(return_value=httpx.Response(200))
            # API probes should use normalized URL (no trailing slash)
            respx.get("https://shop.example.com/products.json").mock(
                return_value=httpx.Response(200, json=shopify_products_response)
            )
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/").mock(return_value=httpx.Response(200, text="<html></html>"))

            result = await detector.detect("https://shop.example.com/")

            assert result.platform == Platform.SHOPIFY

    @pytest.mark.asyncio
    async def test_http_errors_handled_gracefully(self) -> None:
        """HTTP errors don't crash detection."""
        detector = PlatformDetector()

        with respx.mock:
            # Simulate server errors
            respx.head("https://shop.example.com").mock(return_value=httpx.Response(500))
            respx.get("https://shop.example.com/products.json").mock(return_value=httpx.Response(500))
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(500))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(500))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(500))

            result = await detector.detect("https://shop.example.com")

            # Should fallback to generic
            assert result.platform == Platform.GENERIC

    @pytest.mark.asyncio
    async def test_malformed_json_handled(self) -> None:
        """Malformed JSON responses don't crash detection."""
        detector = PlatformDetector()

        with respx.mock:
            respx.head("https://shop.example.com").mock(return_value=httpx.Response(200))
            # Return invalid JSON
            respx.get("https://shop.example.com/products.json").mock(
                return_value=httpx.Response(200, text="not valid json{")
            )
            respx.get("https://shop.example.com/wp-json/").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com/rest/V1/store/storeConfigs").mock(return_value=httpx.Response(404))
            respx.get("https://shop.example.com").mock(return_value=httpx.Response(200, text="<html></html>"))

            result = await detector.detect("https://shop.example.com")

            # Should fallback to generic (no valid signals)
            assert result.platform == Platform.GENERIC
