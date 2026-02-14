"""Unit tests for SchemaOrgExtractor."""

from __future__ import annotations

import pytest
from httpx import Response

from app.extractors.schema_org_extractor import SchemaOrgExtractor


@pytest.fixture
def extractor():
    """Create SchemaOrgExtractor instance."""
    return SchemaOrgExtractor()


class TestSchemaOrgExtractor:
    """Test suite for SchemaOrgExtractor."""

    @pytest.mark.respx(base_url="https://example.com")
    async def test_valid_product_jsonld(self, extractor, respx_mock):
        """Test extraction of valid Product JSON-LD."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Product",
                "name": "Test Product",
                "description": "A great product",
                "image": "https://example.com/image.jpg",
                "sku": "TEST123",
                "brand": {
                    "@type": "Brand",
                    "name": "TestBrand"
                },
                "offers": {
                    "@type": "Offer",
                    "price": "29.99",
                    "priceCurrency": "USD"
                }
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/product").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/product")

        assert len(result) == 1
        assert result[0]["@type"] == "Product"
        assert result[0]["name"] == "Test Product"
        assert result[0]["sku"] == "TEST123"
        assert result[0]["offers"]["price"] == "29.99"

    @pytest.mark.respx(base_url="https://example.com")
    async def test_multiple_jsonld_blocks(self, extractor, respx_mock):
        """Test extraction when multiple JSON-LD blocks exist."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "Test Org"
            }
            </script>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Product",
                "name": "Product 1",
                "sku": "SKU1"
            }
            </script>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Product",
                "name": "Product 2",
                "sku": "SKU2"
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/products").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/products")

        assert len(result) == 2
        assert all(p["@type"] == "Product" for p in result)
        assert result[0]["name"] == "Product 1"
        assert result[1]["name"] == "Product 2"

    @pytest.mark.respx(base_url="https://example.com")
    async def test_no_product_type_found(self, extractor, respx_mock):
        """Test when JSON-LD exists but no Product type."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Organization",
                "name": "Test Company"
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/company").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/company")

        assert result == []

    @pytest.mark.respx(base_url="https://example.com")
    async def test_list_of_objects(self, extractor, respx_mock):
        """Test extraction when JSON-LD contains a list of objects."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            [
                {
                    "@context": "https://schema.org",
                    "@type": "Product",
                    "name": "Product A"
                },
                {
                    "@context": "https://schema.org",
                    "@type": "Product",
                    "name": "Product B"
                }
            ]
            </script>
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/list").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/list")

        assert len(result) == 2
        assert result[0]["name"] == "Product A"
        assert result[1]["name"] == "Product B"

    @pytest.mark.respx(base_url="https://example.com")
    async def test_graph_pattern(self, extractor, respx_mock):
        """Test extraction from @graph pattern."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "Organization",
                        "name": "Test Org"
                    },
                    {
                        "@type": "Product",
                        "name": "Graph Product",
                        "sku": "GRAPH123"
                    }
                ]
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/graph").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/graph")

        assert len(result) == 1
        assert result[0]["@type"] == "Product"
        assert result[0]["name"] == "Graph Product"

    @pytest.mark.respx(base_url="https://example.com")
    async def test_no_jsonld_script_tags(self, extractor, respx_mock):
        """Test when page has no JSON-LD script tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>No JSON-LD</title>
        </head>
        <body>
            <h1>Product Page</h1>
        </body>
        </html>
        """

        respx_mock.get("/no-jsonld").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/no-jsonld")

        assert result == []

    @pytest.mark.respx(base_url="https://example.com")
    async def test_invalid_json_in_script(self, extractor, respx_mock):
        """Test handling of invalid JSON in script tag."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            { invalid json
            </script>
            <script type="application/ld+json">
            {
                "@type": "Product",
                "name": "Valid Product"
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/invalid").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/invalid")

        # Should skip invalid JSON and extract valid one
        assert len(result) == 1
        assert result[0]["name"] == "Valid Product"

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
    async def test_mixed_graph_with_products(self, extractor, respx_mock):
        """Test @graph with multiple products and other types."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": "Product",
                        "name": "Product 1"
                    },
                    {
                        "@type": "WebPage",
                        "name": "Page"
                    },
                    {
                        "@type": "Product",
                        "name": "Product 2"
                    }
                ]
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/mixed").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/mixed")

        assert len(result) == 2
        assert result[0]["name"] == "Product 1"
        assert result[1]["name"] == "Product 2"
