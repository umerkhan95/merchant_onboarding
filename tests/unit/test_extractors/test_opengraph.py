"""Unit tests for OpenGraphExtractor."""

from __future__ import annotations

import pytest
from httpx import Response

from app.extractors.opengraph_extractor import OpenGraphExtractor


@pytest.fixture
def extractor():
    """Create OpenGraphExtractor instance."""
    return OpenGraphExtractor()


class TestOpenGraphExtractor:
    """Test suite for OpenGraphExtractor."""

    @pytest.mark.respx(base_url="https://example.com")
    async def test_full_og_tags(self, extractor, respx_mock):
        """Test extraction of full OpenGraph tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="Amazing Product">
            <meta property="og:description" content="Best product ever">
            <meta property="og:image" content="https://example.com/image.jpg">
            <meta property="og:url" content="https://example.com/product">
            <meta property="og:price:amount" content="29.99">
            <meta property="og:price:currency" content="USD">
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/product").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/product")

        assert len(result) == 1
        og_data = result[0]
        assert og_data["og:title"] == "Amazing Product"
        assert og_data["og:description"] == "Best product ever"
        assert og_data["og:image"] == "https://example.com/image.jpg"
        assert og_data["og:price:amount"] == "29.99"
        assert og_data["og:price:currency"] == "USD"

    @pytest.mark.respx(base_url="https://example.com")
    async def test_partial_og_tags(self, extractor, respx_mock):
        """Test extraction when only some OG tags are present."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="Minimal Product">
            <meta property="og:image" content="https://example.com/img.jpg">
            <meta name="description" content="This is not OG">
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/minimal").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/minimal")

        assert len(result) == 1
        og_data = result[0]
        assert og_data["og:title"] == "Minimal Product"
        assert og_data["og:image"] == "https://example.com/img.jpg"
        assert "og:description" not in og_data

    @pytest.mark.respx(base_url="https://example.com")
    async def test_no_og_tags(self, extractor, respx_mock):
        """Test when page has no OpenGraph tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Regular Page</title>
            <meta name="description" content="Not OpenGraph">
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/no-og").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/no-og")

        assert result == []

    @pytest.mark.respx(base_url="https://example.com")
    async def test_product_price_tags(self, extractor, respx_mock):
        """Test extraction of product:price tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="Product">
            <meta property="product:price:amount" content="49.99">
            <meta property="product:price:currency" content="EUR">
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/product-price").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/product-price")

        assert len(result) == 1
        og_data = result[0]
        assert og_data["product:price:amount"] == "49.99"
        assert og_data["product:price:currency"] == "EUR"

    @pytest.mark.respx(base_url="https://example.com")
    async def test_empty_content_tags(self, extractor, respx_mock):
        """Test handling of OG tags with empty content."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="">
            <meta property="og:description" content="Valid description">
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/empty-content").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/empty-content")

        # Should skip empty content tags and only extract valid ones
        assert len(result) == 1
        og_data = result[0]
        assert "og:title" not in og_data  # Empty content is skipped
        assert og_data["og:description"] == "Valid description"
        assert len(og_data) == 1

    @pytest.mark.respx(base_url="https://example.com")
    async def test_mixed_og_and_product_tags(self, extractor, respx_mock):
        """Test extraction of both og: and product: prefixed tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="Mixed Product">
            <meta property="og:type" content="product">
            <meta property="product:price:amount" content="99.99">
            <meta property="product:availability" content="in stock">
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/mixed").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/mixed")

        assert len(result) == 1
        og_data = result[0]
        assert og_data["og:title"] == "Mixed Product"
        assert og_data["product:price:amount"] == "99.99"
        assert og_data["product:availability"] == "in stock"

    @pytest.mark.respx(base_url="https://example.com")
    async def test_http_error(self, extractor, respx_mock):
        """Test handling of HTTP errors."""
        respx_mock.get("/404").mock(return_value=Response(404))

        result = await extractor.extract("https://example.com/404")

        assert result == []

    @pytest.mark.respx(base_url="https://example.com")
    async def test_network_error(self, extractor, respx_mock):
        """Test handling of network errors."""
        respx_mock.get("/error").mock(side_effect=Exception("Network error"))

        result = await extractor.extract("https://example.com/error")

        assert result == []

    @pytest.mark.respx(base_url="https://example.com")
    async def test_malformed_meta_tags(self, extractor, respx_mock):
        """Test handling of malformed meta tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title">
            <meta content="No property">
            <meta property="og:description" content="Valid">
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/malformed").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/malformed")

        assert len(result) == 1
        og_data = result[0]
        # Should only extract valid tag
        assert og_data["og:description"] == "Valid"
        assert len(og_data) == 1

    @pytest.mark.respx(base_url="https://example.com")
    async def test_redirects(self, extractor, respx_mock):
        """Test that redirects are followed."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="Redirected Product">
        </head>
        <body></body>
        </html>
        """

        # Mock redirect chain
        respx_mock.get("/redirect").mock(
            return_value=Response(301, headers={"Location": "https://example.com/final"})
        )
        respx_mock.get("/final").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/redirect")

        assert len(result) == 1
        assert result[0]["og:title"] == "Redirected Product"

    @pytest.mark.respx(base_url="https://example.com")
    async def test_all_common_og_tags(self, extractor, respx_mock):
        """Test extraction of all commonly used OG tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="Complete Product">
            <meta property="og:type" content="product">
            <meta property="og:url" content="https://example.com/complete">
            <meta property="og:image" content="https://example.com/img.jpg">
            <meta property="og:description" content="Complete description">
            <meta property="og:site_name" content="Example Store">
            <meta property="og:price:amount" content="199.99">
            <meta property="og:price:currency" content="GBP">
            <meta property="product:price:amount" content="199.99">
            <meta property="product:condition" content="new">
            <meta property="product:availability" content="in stock">
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/complete").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/complete")

        assert len(result) == 1
        og_data = result[0]
        assert len(og_data) == 11
        assert og_data["og:title"] == "Complete Product"
        assert og_data["og:type"] == "product"
        assert og_data["product:condition"] == "new"

    @pytest.mark.respx(base_url="https://example.com")
    async def test_headers_sent(self, extractor, respx_mock):
        """Test that User-Agent and Accept-Language headers are sent."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="Header Test Product">
        </head>
        <body></body>
        </html>
        """

        route = respx_mock.get("/headers-test").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/headers-test")

        assert len(result) == 1
        assert route.called

        # Verify headers were sent
        request = route.calls.last.request
        assert "User-Agent" in request.headers
        assert "Mozilla" in request.headers["User-Agent"]
        assert "Accept-Language" in request.headers
        assert "en-US" in request.headers["Accept-Language"]
