"""Unit tests for SchemaOrgExtractor."""

from __future__ import annotations

import pytest

from app.extractors.schema_org_extractor import SchemaOrgExtractor


class TestSchemaOrgExtractor:
    """Test suite for SchemaOrgExtractor."""

    def test_valid_product_jsonld(self):
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

        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/product")

        assert len(products) == 1
        assert products[0]["@type"] == "Product"
        assert products[0]["name"] == "Test Product"
        assert products[0]["sku"] == "TEST123"
        assert products[0]["offers"]["price"] == "29.99"

    def test_multiple_jsonld_blocks(self):
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

        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/products")

        assert len(products) == 2
        assert all(p["@type"] == "Product" for p in products)
        assert products[0]["name"] == "Product 1"
        assert products[1]["name"] == "Product 2"

    def test_no_product_type_found(self):
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

        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/company")

        assert products == []

    def test_list_of_objects(self):
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

        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/list")

        assert len(products) == 2
        assert products[0]["name"] == "Product A"
        assert products[1]["name"] == "Product B"

    def test_graph_pattern(self):
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

        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/graph")

        assert len(products) == 1
        assert products[0]["@type"] == "Product"
        assert products[0]["name"] == "Graph Product"

    def test_no_jsonld_script_tags(self):
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

        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/no-jsonld")

        assert products == []

    def test_invalid_json_in_script(self):
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

        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/invalid")

        # Should skip invalid JSON and extract valid one
        assert len(products) == 1
        assert products[0]["name"] == "Valid Product"

    def test_mixed_graph_with_products(self):
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

        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/mixed")

        assert len(products) == 2
        assert products[0]["name"] == "Product 1"
        assert products[1]["name"] == "Product 2"

    def test_array_type_with_product(self):
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

        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/array-type")

        assert len(products) == 1
        assert products[0]["name"] == "Array Type Product"
        assert products[0]["sku"] == "ARRAY123"

    def test_full_iri_product_type(self):
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

        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/iri-type")

        assert len(products) == 1
        assert products[0]["name"] == "IRI Product"

    def test_graph_with_array_types(self):
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

        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/graph-array")

        assert len(products) == 1
        assert products[0]["name"] == "Graph Array Product"

    def test_extract_product_from_graph_main_entity(self):
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

    def test_extract_product_from_graph_main_entity_of_page(self):
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

    def test_graph_without_main_entity_still_works(self):
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

    def test_product_group_pulls_variant_price(self):
        """ProductGroup with hasVariant should get first variant's offers."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "ProductGroup",
                "name": "Size Rug",
                "hasVariant": [
                    {
                        "@type": "Product",
                        "name": "Size Rug - 5x8",
                        "offers": {"@type": "Offer", "price": "299.00", "priceCurrency": "USD"}
                    },
                    {
                        "@type": "Product",
                        "name": "Size Rug - 8x10",
                        "offers": {"@type": "Offer", "price": "499.00", "priceCurrency": "USD"}
                    }
                ]
            }
            </script>
        </head>
        <body></body>
        </html>
        """
        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/rug")
        assert len(products) == 1
        assert products[0]["offers"]["price"] == "299.00"

    def test_product_group_skips_zero_price_variants(self):
        """ProductGroup should skip $0 variants and use first non-zero price."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "ProductGroup",
                "name": "Variable Product",
                "hasVariant": [
                    {
                        "@type": "Product",
                        "name": "Variant A",
                        "offers": {"@type": "Offer", "price": "0", "priceCurrency": "USD"}
                    },
                    {
                        "@type": "Product",
                        "name": "Variant B",
                        "offers": {"@type": "Offer", "price": "0.00", "priceCurrency": "USD"}
                    },
                    {
                        "@type": "Product",
                        "name": "Variant C",
                        "offers": {"@type": "Offer", "price": "149.99", "priceCurrency": "USD"}
                    }
                ]
            }
            </script>
        </head>
        <body></body>
        </html>
        """
        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/var")
        assert len(products) == 1
        assert products[0]["offers"]["price"] == "149.99"

    def test_product_group_with_existing_price_not_overwritten(self):
        """ProductGroup with its own non-zero price should not be overwritten."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "ProductGroup",
                "name": "Priced Group",
                "offers": {"@type": "Offer", "price": "59.99", "priceCurrency": "USD"},
                "hasVariant": [
                    {
                        "@type": "Product",
                        "offers": {"@type": "Offer", "price": "99.99", "priceCurrency": "USD"}
                    }
                ]
            }
            </script>
        </head>
        <body></body>
        </html>
        """
        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/priced")
        assert len(products) == 1
        assert products[0]["offers"]["price"] == "59.99"

    def test_product_group_all_zero_price_variants(self):
        """ProductGroup where all variants have $0 should not get offers set."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "ProductGroup",
                "name": "All Zero",
                "hasVariant": [
                    {"@type": "Product", "offers": {"@type": "Offer", "price": "0"}},
                    {"@type": "Product", "offers": {"@type": "Offer", "price": "0.00"}}
                ]
            }
            </script>
        </head>
        <body></body>
        </html>
        """
        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/zero")
        assert len(products) == 1
        # offers should remain None/absent since no non-zero variant found
        offers = products[0].get("offers")
        if offers:
            try:
                assert float(offers.get("price", 0)) == 0
            except (ValueError, TypeError):
                pass

    def test_product_group_variant_with_offer_list(self):
        """ProductGroup variant with offers as a list should extract non-zero price."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <script type="application/ld+json">
            {
                "@context": "https://schema.org",
                "@type": "ProductGroup",
                "name": "Multi-Offer Variant",
                "hasVariant": [
                    {
                        "@type": "Product",
                        "offers": [
                            {"@type": "Offer", "price": "0"},
                            {"@type": "Offer", "price": "79.99", "priceCurrency": "EUR"}
                        ]
                    }
                ]
            }
            </script>
        </head>
        <body></body>
        </html>
        """
        products = SchemaOrgExtractor.extract_from_html(html, "https://example.com/multi")
        assert len(products) == 1
        offers = products[0].get("offers")
        assert offers is not None
        # Should pick the non-zero offer from the list
        if isinstance(offers, list):
            assert any(o.get("price") == "79.99" for o in offers)
        else:
            assert offers.get("price") == "79.99"

    def test_has_nonzero_price_dict(self):
        """_has_nonzero_price with a dict offer."""
        assert SchemaOrgExtractor._has_nonzero_price({"price": "29.99"}) is True
        assert SchemaOrgExtractor._has_nonzero_price({"price": "0"}) is False
        assert SchemaOrgExtractor._has_nonzero_price({"price": "0.00"}) is False
        assert SchemaOrgExtractor._has_nonzero_price({}) is False
        assert SchemaOrgExtractor._has_nonzero_price(None) is False

    def test_has_nonzero_price_list(self):
        """_has_nonzero_price with a list of offers."""
        assert SchemaOrgExtractor._has_nonzero_price([
            {"price": "0"}, {"price": "49.99"}
        ]) is True
        assert SchemaOrgExtractor._has_nonzero_price([
            {"price": "0"}, {"price": "0.00"}
        ]) is False
        assert SchemaOrgExtractor._has_nonzero_price([]) is False

    def test_has_nonzero_price_non_numeric(self):
        """_has_nonzero_price with non-numeric price strings."""
        # "Contact for price" is truthy but not numeric -- should return True (bool fallback)
        assert SchemaOrgExtractor._has_nonzero_price({"price": "Contact us"}) is True
        assert SchemaOrgExtractor._has_nonzero_price({"price": ""}) is False

    def test_pii_fields_stripped_from_products(self):
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
