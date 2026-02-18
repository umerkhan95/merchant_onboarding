"""Tests for defusedxml XML bomb protection and HTTP response size limits.

Covers:
- defusedxml blocks XML bombs (Billion Laughs / entity expansion attacks)
- Oversized sitemap responses are rejected in URLDiscoveryService
- Oversized HTML responses are rejected in SchemaOrgExtractor, OpenGraphExtractor,
  Pipeline._fetch_html, and PlatformDetector._probe_html_content
"""

from __future__ import annotations

import pytest
import httpx
import respx

from app.config import MAX_RESPONSE_SIZE
from app.services.url_discovery import URLDiscoveryService
from app.extractors.schema_org_extractor import SchemaOrgExtractor
from app.extractors.opengraph_extractor import OpenGraphExtractor


# ── Helpers ───────────────────────────────────────────────────────────

# A classic "Billion Laughs" XML entity expansion bomb.
# defusedxml must raise an exception rather than recursively expanding entities.
BILLION_LAUGHS_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE bomb [
  <!ENTITY lol "lol">
  <!ENTITY lol2 "&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;&lol;">
  <!ENTITY lol3 "&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;&lol2;">
  <!ENTITY lol4 "&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;&lol3;">
  <!ENTITY lol5 "&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;&lol4;">
]>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/products/&lol5;</loc></url>
</urlset>
"""

# A well-formed sitemap used to confirm normal parsing still works
VALID_SITEMAP_XML = """\
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://example.com/products/shirt</loc></url>
  <url><loc>https://example.com/products/pants</loc></url>
</urlset>
"""

# Minimal valid HTML with a Schema.org JSON-LD block
VALID_PRODUCT_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "Product",
    "name": "Test Product",
    "offers": {"@type": "Offer", "price": "9.99", "priceCurrency": "USD"}
  }
  </script>
</head>
<body></body>
</html>
"""

# Minimal HTML with OpenGraph tags
VALID_OG_HTML = """\
<!DOCTYPE html>
<html>
<head>
  <meta property="og:title" content="Test Product" />
  <meta property="og:type" content="product" />
  <meta property="og:url" content="https://example.com/products/test" />
  <meta property="og:image" content="https://example.com/img/test.jpg" />
</head>
<body></body>
</html>
"""


# ── defusedxml XML bomb protection ────────────────────────────────────


class TestDefusedXmlBombProtection:
    """Verify that defusedxml blocks XML entity expansion attacks."""

    def test_defusedxml_blocks_billion_laughs(self):
        """_parse_sitemap_xml must return [] (not hang/crash) for a Billion Laughs bomb."""
        result = URLDiscoveryService._parse_sitemap_xml(BILLION_LAUGHS_XML)
        # defusedxml raises DTDForbidden (a DefusedXmlException/ValueError), which
        # _parse_sitemap_xml catches and returns an empty list.
        assert result == []

    def test_defusedxml_allows_valid_xml(self):
        """Normal sitemap XML must still parse correctly after the defusedxml swap."""
        result = URLDiscoveryService._parse_sitemap_xml(VALID_SITEMAP_XML)
        assert len(result) == 2
        assert "https://example.com/products/shirt" in result
        assert "https://example.com/products/pants" in result

    def test_defusedxml_returns_empty_on_malformed_xml(self):
        """Malformed XML must return [] without raising."""
        result = URLDiscoveryService._parse_sitemap_xml("not xml at all <<>>")
        assert result == []

    def test_defusedxml_returns_empty_on_empty_string(self):
        """Empty string must return [] without raising."""
        result = URLDiscoveryService._parse_sitemap_xml("")
        assert result == []


# ── URLDiscoveryService response size limits ──────────────────────────


class TestURLDiscoverySizeLimits:
    """Verify that oversized sitemap responses are rejected before XML parsing."""

    @respx.mock
    async def test_rejects_oversized_sitemap_by_content_length_header(self):
        """A sitemap with Content-Length > MAX_RESPONSE_SIZE is silently skipped."""
        service = URLDiscoveryService()

        oversized_length = MAX_RESPONSE_SIZE + 1
        respx.get("https://shop.example.com/sitemap_products_1.xml").mock(
            return_value=httpx.Response(
                200,
                text=VALID_SITEMAP_XML,
                headers={"content-length": str(oversized_length)},
            )
        )

        urls = await service._try_product_sitemaps(
            "https://shop.example.com", ["/sitemap_products_1.xml"]
        )
        # Oversized response rejected — no URLs extracted
        assert urls == []

    @respx.mock
    async def test_rejects_oversized_sitemap_by_body_length(self):
        """A sitemap whose body exceeds MAX_RESPONSE_SIZE (even without Content-Length) is skipped."""
        service = URLDiscoveryService()

        # Body exceeds limit; no Content-Length header set
        oversized_body = "x" * (MAX_RESPONSE_SIZE + 1)
        respx.get("https://shop.example.com/sitemap_products_1.xml").mock(
            return_value=httpx.Response(200, text=oversized_body)
        )

        urls = await service._try_product_sitemaps(
            "https://shop.example.com", ["/sitemap_products_1.xml"]
        )
        assert urls == []

    @respx.mock
    async def test_accepts_normal_sitemap_response(self):
        """A sitemap well within the size limit is parsed normally."""
        service = URLDiscoveryService()

        respx.get("https://shop.example.com/sitemap_products_1.xml").mock(
            return_value=httpx.Response(200, text=VALID_SITEMAP_XML)
        )

        urls = await service._try_product_sitemaps(
            "https://shop.example.com", ["/sitemap_products_1.xml"]
        )
        assert len(urls) == 2
        assert "https://example.com/products/shirt" in urls


# ── SchemaOrgExtractor response size limits ───────────────────────────


class TestSchemaOrgExtractorSizeLimits:
    """Verify that SchemaOrgExtractor.extract() rejects oversized HTTP responses."""

    @respx.mock
    async def test_rejects_response_by_content_length_header(self):
        """extract() returns [] when Content-Length exceeds MAX_RESPONSE_SIZE."""
        extractor = SchemaOrgExtractor()
        oversized_length = MAX_RESPONSE_SIZE + 1

        respx.get("https://example.com/products/item").mock(
            return_value=httpx.Response(
                200,
                text=VALID_PRODUCT_HTML,
                headers={"content-length": str(oversized_length)},
            )
        )

        result = await extractor.extract("https://example.com/products/item")
        assert result == []

    @respx.mock
    async def test_rejects_response_by_body_length(self):
        """extract() returns [] when the actual body exceeds MAX_RESPONSE_SIZE."""
        extractor = SchemaOrgExtractor()

        oversized_body = "x" * (MAX_RESPONSE_SIZE + 1)
        respx.get("https://example.com/products/item").mock(
            return_value=httpx.Response(200, text=oversized_body)
        )

        result = await extractor.extract("https://example.com/products/item")
        assert result == []

    @respx.mock
    async def test_accepts_normal_response(self):
        """extract() works normally for responses within the size limit."""
        extractor = SchemaOrgExtractor()

        respx.get("https://example.com/products/item").mock(
            return_value=httpx.Response(200, text=VALID_PRODUCT_HTML)
        )

        result = await extractor.extract("https://example.com/products/item")
        assert len(result) == 1
        assert result[0]["name"] == "Test Product"


# ── OpenGraphExtractor response size limits ───────────────────────────


class TestOpenGraphExtractorSizeLimits:
    """Verify that OpenGraphExtractor.extract() rejects oversized HTTP responses."""

    @respx.mock
    async def test_rejects_response_by_content_length_header(self):
        """extract() returns [] when Content-Length exceeds MAX_RESPONSE_SIZE."""
        extractor = OpenGraphExtractor()
        oversized_length = MAX_RESPONSE_SIZE + 1

        respx.get("https://example.com/products/item").mock(
            return_value=httpx.Response(
                200,
                text=VALID_OG_HTML,
                headers={"content-length": str(oversized_length)},
            )
        )

        result = await extractor.extract("https://example.com/products/item")
        assert result == []

    @respx.mock
    async def test_rejects_response_by_body_length(self):
        """extract() returns [] when the actual body exceeds MAX_RESPONSE_SIZE."""
        extractor = OpenGraphExtractor()

        oversized_body = "x" * (MAX_RESPONSE_SIZE + 1)
        respx.get("https://example.com/products/item").mock(
            return_value=httpx.Response(200, text=oversized_body)
        )

        result = await extractor.extract("https://example.com/products/item")
        assert result == []

    @respx.mock
    async def test_accepts_normal_response(self):
        """extract() works normally for responses within the size limit."""
        extractor = OpenGraphExtractor()

        respx.get("https://example.com/products/item").mock(
            return_value=httpx.Response(200, text=VALID_OG_HTML)
        )

        result = await extractor.extract("https://example.com/products/item")
        assert len(result) == 1
        assert result[0]["og:title"] == "Test Product"


# ── Pipeline._fetch_html response size limits ─────────────────────────


class TestPipelineFetchHtmlSizeLimits:
    """Verify that Pipeline._fetch_html() rejects oversized responses."""

    @pytest.fixture
    def pipeline(self):
        """Minimal Pipeline instance with stub infrastructure."""
        from unittest.mock import AsyncMock, MagicMock
        from app.services.pipeline import Pipeline

        progress = MagicMock()
        progress.update = AsyncMock()
        progress.set_metadata = AsyncMock()
        circuit_breaker = MagicMock()
        rate_limiter = MagicMock()
        return Pipeline(
            progress_tracker=progress,
            circuit_breaker=circuit_breaker,
            rate_limiter=rate_limiter,
        )

    @respx.mock
    async def test_rejects_response_by_content_length_header(self, pipeline):
        """_fetch_html returns None when Content-Length exceeds MAX_RESPONSE_SIZE."""
        oversized_length = MAX_RESPONSE_SIZE + 1

        respx.get("https://example.com/products/item").mock(
            return_value=httpx.Response(
                200,
                text="<html><body>Hello</body></html>",
                headers={"content-length": str(oversized_length)},
            )
        )

        result = await pipeline._fetch_html("https://example.com/products/item")
        assert result is None

    @respx.mock
    async def test_rejects_response_by_body_length(self, pipeline):
        """_fetch_html returns None when the body exceeds MAX_RESPONSE_SIZE."""
        oversized_body = "x" * (MAX_RESPONSE_SIZE + 1)

        respx.get("https://example.com/products/item").mock(
            return_value=httpx.Response(200, text=oversized_body)
        )

        result = await pipeline._fetch_html("https://example.com/products/item")
        assert result is None

    @respx.mock
    async def test_accepts_normal_response(self, pipeline):
        """_fetch_html returns HTML for responses within the size limit."""
        html = "<html><body>Hello</body></html>"

        respx.get("https://example.com/products/item").mock(
            return_value=httpx.Response(200, text=html)
        )

        result = await pipeline._fetch_html("https://example.com/products/item")
        assert result == html


# ── PlatformDetector._probe_html_content size limits ─────────────────


class TestPlatformDetectorSizeLimits:
    """Verify that PlatformDetector skips oversized HTML probe responses."""

    @respx.mock
    async def test_skips_detection_when_content_length_too_large(self):
        """Platform detection returns GENERIC when HTML probe is oversized (Content-Length)."""
        from app.services.platform_detector import PlatformDetector
        from app.models.enums import Platform

        detector = PlatformDetector()
        oversized_length = MAX_RESPONSE_SIZE + 1

        # HEAD probe — OK
        respx.head("https://example.com").mock(return_value=httpx.Response(200))
        # API probes — all 404
        respx.get("https://example.com/products.json").mock(
            return_value=httpx.Response(404)
        )
        respx.get("https://example.com/wp-json/").mock(
            return_value=httpx.Response(404)
        )
        respx.get("https://example.com/rest/V1/store/storeConfigs").mock(
            return_value=httpx.Response(404)
        )
        # HTML probe — oversized
        respx.get("https://example.com").mock(
            return_value=httpx.Response(
                200,
                text="<html></html>",
                headers={"content-length": str(oversized_length)},
            )
        )

        result = await detector.detect("https://example.com")

        # No platform signals from HTML analysis — falls back to GENERIC
        assert result.platform == Platform.GENERIC

    @respx.mock
    async def test_skips_detection_when_body_too_large(self):
        """Platform detection returns GENERIC when HTML probe body is oversized."""
        from app.services.platform_detector import PlatformDetector
        from app.models.enums import Platform

        detector = PlatformDetector()
        oversized_body = "x" * (MAX_RESPONSE_SIZE + 1)

        respx.head("https://example.com").mock(return_value=httpx.Response(200))
        respx.get("https://example.com/products.json").mock(
            return_value=httpx.Response(404)
        )
        respx.get("https://example.com/wp-json/").mock(
            return_value=httpx.Response(404)
        )
        respx.get("https://example.com/rest/V1/store/storeConfigs").mock(
            return_value=httpx.Response(404)
        )
        respx.get("https://example.com").mock(
            return_value=httpx.Response(200, text=oversized_body)
        )

        result = await detector.detect("https://example.com")
        assert result.platform == Platform.GENERIC


# ── MAX_RESPONSE_SIZE constant sanity check ───────────────────────────


class TestMaxResponseSizeConstant:
    """Ensure the constant has the expected value and is accessible."""

    def test_constant_is_10mb(self):
        assert MAX_RESPONSE_SIZE == 10 * 1024 * 1024

    def test_constant_importable_from_config(self):
        from app.config import MAX_RESPONSE_SIZE as MRS
        assert MRS > 0
