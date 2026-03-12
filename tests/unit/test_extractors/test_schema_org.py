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

        assert len(result.products) == 1
        assert result.products[0]["@type"] == "Product"
        assert result.products[0]["name"] == "Test Product"
        assert result.products[0]["sku"] == "TEST123"
        assert result.products[0]["offers"]["price"] == "29.99"

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

        assert len(result.products) == 2
        assert all(p["@type"] == "Product" for p in result.products)
        assert result.products[0]["name"] == "Product 1"
        assert result.products[1]["name"] == "Product 2"

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

        assert result.products == []

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

        assert len(result.products) == 2
        assert result.products[0]["name"] == "Product A"
        assert result.products[1]["name"] == "Product B"

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

        assert len(result.products) == 1
        assert result.products[0]["@type"] == "Product"
        assert result.products[0]["name"] == "Graph Product"

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

        assert result.products == []

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
        assert len(result.products) == 1
        assert result.products[0]["name"] == "Valid Product"

    @pytest.mark.respx(base_url="https://example.com")
    async def test_http_error(self, extractor, respx_mock):
        """Test handling of HTTP errors."""
        respx_mock.get("/404").mock(return_value=Response(404))

        result = await extractor.extract("https://example.com/404")

        assert result.products == []

    @pytest.mark.respx(base_url="https://example.com")
    async def test_network_error(self, extractor, respx_mock):
        """Test handling of network errors."""
        respx_mock.get("/error").mock(side_effect=Exception("Network error"))

        result = await extractor.extract("https://example.com/error")

        assert result.products == []

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

        assert len(result.products) == 2
        assert result.products[0]["name"] == "Product 1"
        assert result.products[1]["name"] == "Product 2"

    @pytest.mark.respx(base_url="https://example.com")
    async def test_array_type_with_product(self, extractor, respx_mock):
        """Test extraction when @type is an array containing Product."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": ["Product", "ItemPage"],
                "name": "Array Type Product",
                "sku": "ARRAY123"
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/array-type").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/array-type")

        assert len(result.products) == 1
        assert result.products[0]["name"] == "Array Type Product"
        assert result.products[0]["sku"] == "ARRAY123"

    @pytest.mark.respx(base_url="https://example.com")
    async def test_full_iri_product_type(self, extractor, respx_mock):
        """Test extraction when @type is a full IRI (https://schema.org/Product)."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "https://schema.org/Product",
                "name": "IRI Product",
                "sku": "IRI123"
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/iri-type").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/iri-type")

        assert len(result.products) == 1
        assert result.products[0]["name"] == "IRI Product"

    @pytest.mark.respx(base_url="https://example.com")
    async def test_graph_with_array_types(self, extractor, respx_mock):
        """Test extraction from @graph with array @type values."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@graph": [
                    {
                        "@type": ["WebPage", "CollectionPage"],
                        "name": "Not a product"
                    },
                    {
                        "@type": ["Product", "Offer"],
                        "name": "Graph Array Product",
                        "sku": "GRAPH_ARR123"
                    }
                ]
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        respx_mock.get("/graph-array").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/graph-array")

        assert len(result.products) == 1
        assert result.products[0]["name"] == "Graph Array Product"

    def test_extract_product_from_graph_main_entity(self, extractor):
        """ItemPage wrapping a Product via mainEntity should yield the Product."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@graph": [{
                    "@type": "ItemPage",
                    "mainEntity": {
                        "@type": "Product",
                        "name": "Widget",
                        "gtin13": "4006381333931"
                    }
                }]
            }
            </script>
        </head>
        <body></body>
        </html>
        """
        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/widget")
        assert len(products) == 1
        assert products[0]["@type"] == "Product"
        assert products[0]["name"] == "Widget"
        assert products[0]["gtin13"] == "4006381333931"

    def test_extract_product_from_graph_main_entity_of_page(self, extractor):
        """WebPage with mainEntityOfPage Product should yield the Product."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@graph": [{
                    "@type": "WebPage",
                    "mainEntityOfPage": {
                        "@type": "Product",
                        "name": "Gadget",
                        "sku": "GAD-001"
                    }
                }]
            }
            </script>
        </head>
        <body></body>
        </html>
        """
        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/gadget")
        assert len(products) == 1
        assert products[0]["@type"] == "Product"
        assert products[0]["name"] == "Gadget"
        assert products[0]["sku"] == "GAD-001"

    def test_graph_without_main_entity_still_works(self, extractor):
        """Regular @graph with direct Product items should still be extracted."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@graph": [
                    {"@type": "Organization", "name": "Acme Corp"},
                    {"@type": "Product", "name": "Direct Product", "sku": "DP-001"}
                ]
            }
            </script>
        </head>
        <body></body>
        </html>
        """
        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/direct")
        assert len(products) == 1
        assert products[0]["name"] == "Direct Product"

    @pytest.mark.respx(base_url="https://example.com")
    async def test_headers_sent(self, extractor, respx_mock):
        """Test that User-Agent and Accept-Language headers are sent."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@type": "Product",
                "name": "Header Test Product"
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        route = respx_mock.get("/headers-test").mock(return_value=Response(200, text=html))

        result = await extractor.extract("https://example.com/headers-test")

        assert len(result.products) == 1
        assert route.called

        # Verify headers were sent
        request = route.calls.last.request
        assert "User-Agent" in request.headers
        assert "Mozilla" in request.headers["User-Agent"]
        assert "Accept-Language" in request.headers
        assert "en-US" in request.headers["Accept-Language"]

    def test_pii_fields_stripped_from_products(self, extractor):
        """PII fields (review, author, aggregateRating) should be stripped."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "Product",
                "name": "Test Product",
                "sku": "SKU-PII",
                "offers": {
                    "@type": "Offer",
                    "price": "19.99",
                    "priceCurrency": "USD"
                },
                "review": {
                    "@type": "Review",
                    "author": {"@type": "Person", "name": "John Doe"},
                    "reviewBody": "Great product!"
                },
                "author": {"@type": "Person", "name": "Jane Doe"},
                "aggregateRating": {
                    "@type": "AggregateRating",
                    "ratingValue": "4.5",
                    "reviewCount": "100"
                },
                "comment": [{"text": "Nice!"}],
                "interactionStatistic": {"userInteractionCount": 500}
            }
            </script>
        </head>
        <body></body>
        </html>
        """

        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/pii")

        assert len(products) == 1
        product = products[0]
        assert product["name"] == "Test Product"
        assert product["sku"] == "SKU-PII"
        assert product["offers"]["price"] == "19.99"
        assert "review" not in product
        assert "author" not in product
        assert "aggregateRating" not in product
        assert "comment" not in product
        assert "interactionStatistic" not in product
