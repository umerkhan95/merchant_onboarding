"""Tests for extraction tier accuracy improvements.

Covers:
- JSON-LD flattener (EvalRunner._flatten_jsonld_product)
- Product region extraction (SmartCSSExtractor._extract_product_region)
- LLM schema completeness (PRODUCT_EXTRACTION_SCHEMA)
"""

from __future__ import annotations

import pytest

from app.extractors.llm_extractor import PRODUCT_EXTRACTION_SCHEMA
from app.extractors.smart_css_extractor import SmartCSSExtractor
from evals.runner import EvalRunner


class TestFlattenJsonldProduct:
    """Test EvalRunner._flatten_jsonld_product with various JSON-LD shapes."""

    def test_nested_offers_list(self):
        product = {
            "name": "Crusher ANC 2",
            "offers": [
                {"price": "149.99", "priceCurrency": "USD", "availability": "https://schema.org/InStock"},
                {"price": "139.99", "priceCurrency": "USD", "availability": "https://schema.org/InStock"},
            ],
        }
        flat = EvalRunner._flatten_jsonld_product(product)
        assert flat["title"] == "Crusher ANC 2"
        assert flat["price"] == "149.99"
        assert flat["currency"] == "USD"
        assert flat["in_stock"] == "true"

    def test_single_offer_dict(self):
        product = {
            "name": "Hesh Evo",
            "offers": {"price": "59.99", "priceCurrency": "CAD", "availability": "https://schema.org/OutOfStock"},
        }
        flat = EvalRunner._flatten_jsonld_product(product)
        assert flat["price"] == "59.99"
        assert flat["currency"] == "CAD"
        assert flat["in_stock"] == "false"

    def test_nested_brand_dict(self):
        product = {
            "name": "Icon ANC",
            "brand": {"@type": "Brand", "name": "Skullcandy"},
        }
        flat = EvalRunner._flatten_jsonld_product(product)
        assert flat["vendor"] == "Skullcandy"

    def test_string_brand(self):
        product = {
            "name": "Indy Evo",
            "brand": "Skullcandy",
        }
        flat = EvalRunner._flatten_jsonld_product(product)
        assert flat["vendor"] == "Skullcandy"

    def test_image_array(self):
        product = {
            "name": "Dime 3",
            "image": [
                "https://example.com/img1.jpg",
                "https://example.com/img2.jpg",
            ],
        }
        flat = EvalRunner._flatten_jsonld_product(product)
        assert flat["image_url"] == "https://example.com/img1.jpg"

    def test_image_string(self):
        product = {
            "name": "Push Active",
            "image": "https://example.com/main.jpg",
        }
        flat = EvalRunner._flatten_jsonld_product(product)
        assert flat["image_url"] == "https://example.com/main.jpg"

    def test_image_array_of_dicts(self):
        product = {
            "name": "Smokin Buds",
            "image": [{"url": "https://example.com/img.jpg"}],
        }
        flat = EvalRunner._flatten_jsonld_product(product)
        assert flat["image_url"] == "https://example.com/img.jpg"

    def test_missing_offers(self):
        product = {"name": "Basic Product"}
        flat = EvalRunner._flatten_jsonld_product(product)
        assert flat["title"] == "Basic Product"
        assert "price" not in flat
        assert "currency" not in flat
        assert "in_stock" not in flat

    def test_instock_availability(self):
        product = {
            "name": "Product",
            "offers": [{"price": "10", "availability": "https://schema.org/InStock"}],
        }
        flat = EvalRunner._flatten_jsonld_product(product)
        assert flat["in_stock"] == "true"

    def test_outofstock_availability(self):
        product = {
            "name": "Product",
            "offers": [{"price": "10", "availability": "https://schema.org/OutOfStock"}],
        }
        flat = EvalRunner._flatten_jsonld_product(product)
        assert flat["in_stock"] == "false"

    def test_url_and_sku_passthrough(self):
        product = {
            "name": "Product",
            "url": "https://example.com/product/123",
            "sku": "SKU-001",
        }
        flat = EvalRunner._flatten_jsonld_product(product)
        assert flat["product_url"] == "https://example.com/product/123"
        assert flat["sku"] == "SKU-001"

    def test_description_passthrough(self):
        product = {
            "name": "Product",
            "description": "A great product for everyone.",
        }
        flat = EvalRunner._flatten_jsonld_product(product)
        assert flat["description"] == "A great product for everyone."

    def test_aggregate_offer_with_nested_offers(self):
        product = {
            "name": "Product",
            "offers": {
                "@type": "AggregateOffer",
                "lowPrice": "49.99",
                "offers": [
                    {"price": "49.99", "priceCurrency": "USD", "availability": "https://schema.org/InStock"},
                ],
            },
        }
        flat = EvalRunner._flatten_jsonld_product(product)
        assert flat["price"] == "49.99"
        assert flat["currency"] == "USD"

    def test_empty_product(self):
        flat = EvalRunner._flatten_jsonld_product({})
        assert flat == {}

    def test_empty_brand_dict(self):
        product = {"name": "Product", "brand": {"@type": "Brand"}}
        flat = EvalRunner._flatten_jsonld_product(product)
        assert "vendor" not in flat

    def test_empty_brand_string(self):
        product = {"name": "Product", "brand": ""}
        flat = EvalRunner._flatten_jsonld_product(product)
        assert "vendor" not in flat


class TestExtractProductRegionStripping:
    """Test that _extract_product_region removes non-structural elements (script, style, etc).

    These tests validate the tag-stripping behaviour that is part of _extract_product_region,
    which replaced the standalone _strip_html helper.
    """

    def test_removes_script_tags(self):
        html = '<html><body><main><script>var x = 1;</script><div>Content</div></main></body></html>'
        result = SmartCSSExtractor._extract_product_region(html)
        assert "<script" not in result
        assert "var x = 1" not in result
        assert "Content" in result

    def test_removes_style_tags(self):
        html = '<html><body><main><style>.foo { color: red; }</style><p>Text</p></main></body></html>'
        result = SmartCSSExtractor._extract_product_region(html)
        assert "<style" not in result
        assert "color: red" not in result
        assert "<p>Text</p>" in result

    def test_removes_svg_tags(self):
        html = '<html><body><main><svg><path d="M0 0"/></svg><span>Hello</span></main></body></html>'
        result = SmartCSSExtractor._extract_product_region(html)
        assert "<svg" not in result
        assert "<span>Hello</span>" in result

    def test_removes_noscript_tags(self):
        html = '<html><body><main><noscript>Enable JS</noscript><div>Main</div></main></body></html>'
        result = SmartCSSExtractor._extract_product_region(html)
        assert "<noscript" not in result
        assert "<div>Main</div>" in result

    def test_removes_iframe_tags(self):
        html = '<html><body><main><iframe src="https://ads.example.com"></iframe><article>Content</article></main></body></html>'
        result = SmartCSSExtractor._extract_product_region(html)
        assert "<iframe" not in result
        assert "<article>Content</article>" in result

    def test_removes_html_comments(self):
        html = '<html><body><main><!-- This is a comment --><div>Visible</div></main></body></html>'
        result = SmartCSSExtractor._extract_product_region(html)
        assert "<!--" not in result
        assert "This is a comment" not in result
        assert "<div>Visible</div>" in result

    def test_preserves_product_elements(self):
        html = (
            '<html><body><main>'
            '<div class="product"><h1>Title</h1>'
            '<span class="price">$29.99</span></div>'
            '</main></body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        assert "Title" in result
        assert "$29.99" in result

    def test_removes_multiple_script_tags(self):
        html = (
            '<html><body><main>'
            '<script>alert(1)</script>'
            '<div>A</div>'
            '<script type="application/json">{"key": "val"}</script>'
            '<div>B</div>'
            '</main></body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        assert "<script" not in result
        assert "<div>A</div>" in result
        assert "<div>B</div>" in result


class TestExtractProductRegion:
    """Test SmartCSSExtractor._extract_product_region isolates product content."""

    def test_finds_main_element(self):
        html = (
            '<html><body>'
            '<header><nav>Menu</nav></header>'
            '<main><div class="product-card"><h1>Product</h1>'
            '<span class="price">$29.99</span></div></main>'
            '<footer>Copyright</footer>'
            '</body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        assert "<h1>Product</h1>" in result
        assert "$29.99" in result
        assert "<header" not in result
        assert "<footer" not in result
        assert "<nav" not in result

    def test_finds_product_class(self):
        html = (
            '<html><body>'
            '<header>Header</header>'
            '<div class="product"><h2>Widget</h2><p>$10</p></div>'
            '<footer>Footer</footer>'
            '</body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        assert "Widget" in result
        assert "$10" in result
        assert "<header" not in result

    def test_finds_product_info_wrapper(self):
        html = (
            '<html><body>'
            '<nav>Nav</nav>'
            '<div class="product">'
            '<div class="media-gallery">' + ("X" * 500) + '</div>'
            '<div class="product__info-wrapper">'
            '<h1>Gadget</h1><span class="price">$25</span>'
            '</div></div>'
            '</body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        assert "Gadget" in result
        assert "$25" in result
        assert "<nav" not in result

    def test_finds_product_detail_class(self):
        html = (
            '<html><body>'
            '<aside>Sidebar</aside>'
            '<section class="product-detail"><h1>Item</h1><span>$50</span></section>'
            '</body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        assert "Item" in result
        assert "<aside" not in result

    def test_finds_product_single_class(self):
        html = (
            '<html><body>'
            '<header>Header</header>'
            '<div class="product-single"><h1>Shoe</h1></div>'
            '</body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        assert "Shoe" in result
        assert "<header" not in result

    def test_falls_back_to_body_when_no_container(self):
        html = (
            '<html><body>'
            '<div class="random"><h1>Product</h1></div>'
            '</body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        # Should still contain the content (from body fallback)
        assert "Product" in result

    def test_removes_scripts_and_styles(self):
        html = (
            '<html><body>'
            '<script>var x = 1;</script>'
            '<style>.foo{color:red}</style>'
            '<main><div class="product">Content</div></main>'
            '</body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        assert "<script" not in result
        assert "<style" not in result
        assert "Content" in result

    def test_removes_header_footer_nav_aside(self):
        html = (
            '<html><body>'
            '<header><div class="logo">Logo</div></header>'
            '<nav><a href="/">Home</a></nav>'
            '<aside><div>Sidebar widget</div></aside>'
            '<main><div class="product"><h1>Main Product</h1></div></main>'
            '<footer><p>Copyright 2024</p></footer>'
            '</body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        assert "Main Product" in result
        assert "Logo" not in result
        assert "Home" not in result
        assert "Sidebar widget" not in result
        assert "Copyright 2024" not in result

    def test_removes_html_comments(self):
        html = (
            '<html><body>'
            '<!-- Shopify analytics -->'
            '<main><div class="product">Content</div></main>'
            '</body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        assert "<!--" not in result
        assert "Shopify analytics" not in result
        assert "Content" in result

    def test_skips_tiny_container(self):
        """Container with <200 chars should be skipped."""
        html = (
            '<html><body>'
            '<div class="product">X</div>'
            '<main><div class="real-content">' + ("A" * 300) + '</div></main>'
            '</body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        # .product is too small (<200 chars), should use <main> instead
        assert "A" * 300 in result

    def test_preserves_product_css_classes(self):
        html = (
            '<html><body>'
            '<main>'
            '<div class="product-card" data-variant-id="123">'
            '<h1 class="product-title">Cool Widget</h1>'
            '<span class="product-price" data-price="2999">$29.99</span>'
            '</div>'
            '</main>'
            '</body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        assert 'class="product-card"' in result
        assert 'data-variant-id="123"' in result
        assert 'class="product-title"' in result
        assert 'class="product-price"' in result


    def test_removes_variant_radios(self):
        html = (
            '<html><body><main>'
            '<div class="product"><h1>Product</h1>'
            '<variant-radios class="no-js-hidden">'
            '<fieldset><legend>Color</legend>'
            '<input type="radio" value="Red"/>'
            '<input type="radio" value="Blue"/>'
            '</fieldset></variant-radios>'
            '</div></main></body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        assert "Product" in result
        assert "<variant-radios" not in result
        assert "Red" not in result

    def test_removes_variant_selects(self):
        html = (
            '<html><body><main>'
            '<div class="product"><h1>Product</h1>'
            '<variant-selects><select><option>S</option></select></variant-selects>'
            '</div></main></body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        assert "Product" in result
        assert "<variant-selects" not in result

    def test_removes_review_widgets(self):
        html = (
            '<html><body><main>'
            '<div class="product"><h1>Product</h1></div>'
            '<div class="yotpo-widget">4.5 stars</div>'
            '</main></body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        assert "Product" in result
        assert "yotpo" not in result
        assert "4.5 stars" not in result

    def test_removes_gallery_and_slider(self):
        html = (
            '<html><body><main>'
            '<div class="product__info-wrapper"><h1>Product</h1></div>'
            '<ul class="media-list slider">' + ("img " * 100) + '</ul>'
            '</main></body></html>'
        )
        result = SmartCSSExtractor._extract_product_region(html)
        assert "Product" in result
        assert "media-list" not in result


class TestLLMSchemaCompleteness:
    """Verify LLM extraction schema contains all required fields."""

    def test_schema_has_vendor(self):
        assert "vendor" in PRODUCT_EXTRACTION_SCHEMA["properties"]

    def test_schema_has_product_url(self):
        assert "product_url" in PRODUCT_EXTRACTION_SCHEMA["properties"]

    def test_schema_has_product_type(self):
        assert "product_type" in PRODUCT_EXTRACTION_SCHEMA["properties"]

    def test_schema_has_all_core_fields(self):
        expected_fields = {
            "title", "price", "description", "image_url", "sku",
            "currency", "in_stock", "vendor", "product_url", "product_type",
        }
        actual_fields = set(PRODUCT_EXTRACTION_SCHEMA["properties"].keys())
        assert expected_fields == actual_fields

    def test_title_is_only_required_field(self):
        assert PRODUCT_EXTRACTION_SCHEMA["required"] == ["title"]
