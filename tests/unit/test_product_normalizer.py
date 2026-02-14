"""Unit tests for ProductNormalizer."""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.models.enums import Platform
from app.services.product_normalizer import ProductNormalizer


@pytest.fixture
def normalizer():
    """Create ProductNormalizer instance."""
    return ProductNormalizer()


class TestShopifyNormalization:
    """Test Shopify product normalization."""

    def test_normalize_shopify_complete(self, normalizer):
        """Normalize complete Shopify raw data to valid Product."""
        raw = {
            "id": 7891234567890,
            "title": "Premium Cotton T-Shirt",
            "body_html": "<p>High-quality cotton t-shirt</p>",
            "handle": "premium-cotton-tshirt",
            "vendor": "Brand Co",
            "product_type": "Apparel",
            "tags": "cotton, premium, bestseller",
            "variants": [
                {
                    "id": 12345,
                    "title": "Small / Red",
                    "price": "29.99",
                    "compare_at_price": "39.99",
                    "sku": "SHIRT-SM-RED",
                    "inventory_quantity": 10,
                },
                {
                    "id": 12346,
                    "title": "Medium / Blue",
                    "price": "29.99",
                    "sku": "SHIRT-MD-BLUE",
                    "inventory_quantity": 5,
                },
            ],
            "images": [
                {"src": "https://example.com/images/shirt.jpg"},
            ],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="mystore",
            platform=Platform.SHOPIFY,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.external_id == "7891234567890"
        assert product.shop_id == "mystore"
        assert product.platform == Platform.SHOPIFY
        assert product.title == "Premium Cotton T-Shirt"
        assert product.description == "<p>High-quality cotton t-shirt</p>"
        assert product.price == Decimal("29.99")
        assert product.compare_at_price == Decimal("39.99")
        assert product.currency == "USD"
        assert product.image_url == "https://example.com/images/shirt.jpg"
        assert product.product_url == "https://example.com/products/premium-cotton-tshirt"
        assert product.sku == "SHIRT-SM-RED"
        assert product.vendor == "Brand Co"
        assert product.product_type == "Apparel"
        assert product.in_stock is True
        assert len(product.variants) == 2
        assert product.tags == ["cotton", "premium", "bestseller"]
        assert product.raw_data == raw
        assert product.idempotency_key != ""

    def test_normalize_shopify_variants(self, normalizer):
        """Verify Shopify variants are correctly mapped."""
        raw = {
            "id": 111,
            "title": "Test Product",
            "handle": "test",
            "variants": [
                {
                    "id": 1,
                    "title": "Variant 1",
                    "price": "10.00",
                    "sku": "SKU1",
                    "inventory_quantity": 5,
                },
                {
                    "id": 2,
                    "title": "Variant 2",
                    "price": "15.00",
                    "sku": "SKU2",
                    "inventory_quantity": 0,
                },
            ],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://test.com",
        )

        assert len(product.variants) == 2
        assert product.variants[0].variant_id == "1"
        assert product.variants[0].title == "Variant 1"
        assert product.variants[0].price == Decimal("10.00")
        assert product.variants[0].sku == "SKU1"
        assert product.variants[0].in_stock is True
        assert product.variants[1].in_stock is False

    def test_normalize_shopify_tags_as_list(self, normalizer):
        """Handle Shopify tags as list."""
        raw = {
            "id": 123,
            "title": "Test",
            "handle": "test",
            "tags": ["tag1", "tag2", "tag3"],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://test.com",
        )

        assert product.tags == ["tag1", "tag2", "tag3"]

    def test_normalize_shopify_missing_optional_fields(self, normalizer):
        """Handle missing optional fields gracefully."""
        raw = {
            "id": 123,
            "title": "Minimal Product",
            "handle": "minimal",
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://test.com",
        )

        assert product is not None
        assert product.title == "Minimal Product"
        assert product.price == Decimal("0")
        assert product.compare_at_price is None
        assert product.image_url == ""
        assert product.sku is None
        assert product.vendor is None
        assert product.product_type is None
        assert len(product.variants) == 0
        assert product.tags == []

    def test_normalize_shopify_sanitizes_html(self, normalizer):
        """Sanitize HTML descriptions."""
        raw = {
            "id": 123,
            "title": "Test",
            "handle": "test",
            "body_html": "<script>alert('xss')</script><p>Safe content</p>",
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://test.com",
        )

        assert "<script>" not in product.description
        assert "alert" not in product.description
        assert "<p>Safe content</p>" in product.description

    def test_normalize_shopify_empty_title_returns_none(self, normalizer):
        """Return None for empty title."""
        raw = {
            "id": 123,
            "title": "",
            "handle": "test",
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://test.com",
        )

        assert product is None


class TestWooCommerceNormalization:
    """Test WooCommerce product normalization."""

    def test_normalize_woocommerce_complete(self, normalizer):
        """Normalize complete WooCommerce raw data to valid Product."""
        raw = {
            "id": 456,
            "name": "Wireless Headphones",
            "description": "<p>Premium wireless headphones with noise cancellation</p>",
            "permalink": "https://example.com/product/wireless-headphones",
            "prices": {
                "price": "7999",  # $79.99 in cents
                "regular_price": "9999",  # $99.99
                "currency_code": "USD",
                "currency_minor_unit": 2,
            },
            "images": [
                {"src": "https://example.com/headphones.jpg"},
            ],
            "tags": [
                {"name": "electronics"},
                {"name": "audio"},
            ],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="woostore",
            platform=Platform.WOOCOMMERCE,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.external_id == "456"
        assert product.shop_id == "woostore"
        assert product.platform == Platform.WOOCOMMERCE
        assert product.title == "Wireless Headphones"
        assert product.price == Decimal("79.99")
        assert product.compare_at_price == Decimal("99.99")
        assert product.currency == "USD"
        assert product.image_url == "https://example.com/headphones.jpg"
        assert product.product_url == "https://example.com/product/wireless-headphones"
        assert product.sku is None
        assert product.tags == ["electronics", "audio"]

    def test_normalize_woocommerce_minor_unit_conversion(self, normalizer):
        """Verify WooCommerce minor_unit price conversion."""
        raw = {
            "id": 789,
            "name": "Test Product",
            "prices": {
                "price": "12345",  # 123.45 with minor_unit=2
                "currency_code": "EUR",
                "currency_minor_unit": 2,
            },
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.WOOCOMMERCE,
            shop_url="https://test.com",
        )

        assert product.price == Decimal("123.45")
        assert product.currency == "EUR"

    def test_normalize_woocommerce_zero_minor_unit(self, normalizer):
        """Handle zero decimal places (e.g., JPY)."""
        raw = {
            "id": 999,
            "name": "Product in JPY",
            "prices": {
                "price": "5000",  # 5000 yen (no decimals)
                "currency_code": "JPY",
                "currency_minor_unit": 0,
            },
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.WOOCOMMERCE,
            shop_url="https://test.com",
        )

        assert product.price == Decimal("5000")

    def test_normalize_woocommerce_same_regular_price(self, normalizer):
        """Don't set compare_at_price if same as price."""
        raw = {
            "id": 555,
            "name": "No Discount Product",
            "prices": {
                "price": "2999",
                "regular_price": "2999",
                "currency_code": "USD",
                "currency_minor_unit": 2,
            },
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.WOOCOMMERCE,
            shop_url="https://test.com",
        )

        assert product.price == Decimal("29.99")
        assert product.compare_at_price is None


class TestMagentoNormalization:
    """Test Magento product normalization."""

    def test_normalize_magento_complete(self, normalizer):
        """Normalize complete Magento raw data to valid Product."""
        raw = {
            "id": 123,
            "sku": "MAG-PROD-001",
            "name": "Magento Product",
            "price": 49.99,
            "custom_attributes": [
                {"attribute_code": "description", "value": "<p>Product description</p>"},
                {"attribute_code": "image", "value": "/m/a/magento-product.jpg"},
                {"attribute_code": "url_key", "value": "magento-product"},
            ],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="magentostore",
            platform=Platform.MAGENTO,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.external_id == "MAG-PROD-001"
        assert product.title == "Magento Product"
        assert product.price == Decimal("49.99")
        assert product.image_url == "https://example.com/media/catalog/product/m/a/magento-product.jpg"
        assert product.product_url == "https://example.com/magento-product.html"
        assert product.sku == "MAG-PROD-001"

    def test_normalize_magento_custom_attributes_extraction(self, normalizer):
        """Verify custom_attributes extraction."""
        raw = {
            "id": 456,
            "name": "Test",
            "price": 10,
            "custom_attributes": [
                {"attribute_code": "description", "value": "Description text"},
                {"attribute_code": "image", "value": "/i/m/image.jpg"},
                {"attribute_code": "url_key", "value": "test-url"},
                {"attribute_code": "other", "value": "ignored"},
            ],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.MAGENTO,
            shop_url="https://test.com",
        )

        assert "Description text" in product.description
        assert product.image_url == "https://test.com/media/catalog/product/i/m/image.jpg"
        assert product.product_url == "https://test.com/test-url.html"

    def test_normalize_magento_missing_custom_attributes(self, normalizer):
        """Handle missing custom_attributes."""
        raw = {
            "id": 789,
            "sku": "TEST-SKU",
            "name": "Minimal Magento Product",
            "price": 25.00,
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.MAGENTO,
            shop_url="https://test.com",
        )

        assert product is not None
        assert product.description == ""
        assert product.image_url == ""
        assert product.product_url == "https://test.com"


class TestSchemaOrgNormalization:
    """Test Schema.org JSON-LD normalization."""

    def test_normalize_schema_org_complete(self, normalizer):
        """Normalize Schema.org JSON-LD format."""
        raw = {
            "name": "Schema.org Product",
            "description": "Product with structured data",
            "sku": "SCHEMA-001",
            "image": "https://example.com/image.jpg",
            "url": "https://example.com/product",
            "brand": {"name": "Brand Name"},
            "offers": {
                "price": "99.99",
                "priceCurrency": "USD",
            },
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.title == "Schema.org Product"
        assert product.price == Decimal("99.99")
        assert product.currency == "USD"
        assert product.image_url == "https://example.com/image.jpg"
        assert product.product_url == "https://example.com/product"
        assert product.sku == "SCHEMA-001"
        assert product.vendor == "Brand Name"

    def test_normalize_schema_org_offers_array(self, normalizer):
        """Handle offers as array."""
        raw = {
            "name": "Multi-Offer Product",
            "offers": [
                {"price": "49.99", "priceCurrency": "USD"},
                {"price": "44.99", "priceCurrency": "USD"},
            ],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product.price == Decimal("49.99")

    def test_normalize_schema_org_image_array(self, normalizer):
        """Handle image as array."""
        raw = {
            "name": "Multi-Image Product",
            "image": [
                "https://example.com/image1.jpg",
                "https://example.com/image2.jpg",
            ],
            "offers": {"price": "10.00"},
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product.image_url == "https://example.com/image1.jpg"


class TestOpenGraphNormalization:
    """Test OpenGraph meta tags normalization."""

    def test_normalize_opengraph_complete(self, normalizer):
        """Normalize OpenGraph format."""
        raw = {
            "og:title": "OpenGraph Product",
            "og:description": "Product with OG tags",
            "og:image": "https://example.com/og-image.jpg",
            "og:url": "https://example.com/og-product",
            "og:price:amount": "79.99",
            "og:price:currency": "EUR",
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.title == "OpenGraph Product"
        assert product.price == Decimal("79.99")
        assert product.currency == "EUR"
        assert product.image_url == "https://example.com/og-image.jpg"
        assert product.product_url == "https://example.com/og-product"

    def test_normalize_opengraph_product_prefix(self, normalizer):
        """Handle product: prefix in OG tags."""
        raw = {
            "og:title": "Product Title",
            "product:price:amount": "59.99",
            "product:price:currency": "GBP",
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product.price == Decimal("59.99")
        assert product.currency == "GBP"


class TestGenericCSSNormalization:
    """Test generic CSS-extracted fields normalization."""

    def test_normalize_generic_css_complete(self, normalizer):
        """Normalize generic CSS-extracted fields."""
        raw = {
            "title": "Generic Product",
            "description": "<div>Generic description</div>",
            "price": "$29.99",
            "image": "https://example.com/generic.jpg",
            "sku": "GEN-001",
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.title == "Generic Product"
        assert product.price == Decimal("29.99")
        assert product.image_url == "https://example.com/generic.jpg"
        assert product.sku == "GEN-001"

    def test_normalize_generic_css_price_parsing(self, normalizer):
        """Parse various price formats."""
        test_cases = [
            ("$99.99", Decimal("99.99")),
            ("€49,99", Decimal("49.99")),
            ("£19.95", Decimal("19.95")),
            ("25.50", Decimal("25.50")),
            ("1,299.99", Decimal("1299.99")),
        ]

        for price_str, expected in test_cases:
            raw = {"title": "Test", "price": price_str}
            product = normalizer.normalize(
                raw=raw,
                shop_id="test",
                platform=Platform.GENERIC,
                shop_url="https://example.com",
            )
            assert product.price == expected, f"Failed for {price_str}"

    def test_normalize_generic_css_invalid_price(self, normalizer):
        """Handle invalid price gracefully."""
        raw = {"title": "Test", "price": "invalid"}

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product.price == Decimal("0")


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_returns_none_for_empty_title(self, normalizer):
        """Return None for empty title across all platforms."""
        platforms_and_raw = [
            (Platform.SHOPIFY, {"id": 1, "title": ""}),
            (Platform.WOOCOMMERCE, {"id": 1, "name": ""}),
            (Platform.MAGENTO, {"id": 1, "name": ""}),
            (Platform.GENERIC, {"title": ""}),
        ]

        for platform, raw in platforms_and_raw:
            product = normalizer.normalize(
                raw=raw,
                shop_id="test",
                platform=platform,
                shop_url="https://test.com",
            )
            assert product is None

    def test_sanitizes_html_descriptions(self, normalizer):
        """Sanitize HTML descriptions across all platforms."""
        malicious_html = "<script>alert('xss')</script><p>Safe</p>"

        test_cases = [
            (Platform.SHOPIFY, {"id": 1, "title": "Test", "body_html": malicious_html}),
            (Platform.WOOCOMMERCE, {"id": 1, "name": "Test", "description": malicious_html}),
            (
                Platform.MAGENTO,
                {
                    "id": 1,
                    "name": "Test",
                    "price": 10,
                    "custom_attributes": [{"attribute_code": "description", "value": malicious_html}],
                },
            ),
        ]

        for platform, raw in test_cases:
            product = normalizer.normalize(
                raw=raw,
                shop_id="test",
                platform=platform,
                shop_url="https://test.com",
            )
            assert "<script>" not in product.description
            assert "alert" not in product.description

    def test_idempotency_key_computed(self, normalizer):
        """Verify idempotency key is computed."""
        raw = {"id": 123, "title": "Test", "handle": "test"}

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://test.com",
        )

        assert product.idempotency_key != ""
        assert len(product.idempotency_key) == 64  # SHA256 hex digest

    def test_decimal_price_parsing_from_string(self, normalizer):
        """Parse Decimal prices from string values."""
        raw = {
            "id": 123,
            "title": "Test",
            "variants": [{"price": "29.99"}],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://test.com",
        )

        assert isinstance(product.price, Decimal)
        assert product.price == Decimal("29.99")

    def test_handles_missing_optional_fields(self, normalizer):
        """Handle missing optional fields gracefully."""
        raw = {"id": 123, "title": "Minimal", "handle": "minimal"}

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://test.com",
        )

        assert product.vendor is None
        assert product.product_type is None
        assert product.sku is None
        assert product.compare_at_price is None
        assert len(product.variants) == 0
        assert len(product.tags) == 0

    def test_shop_url_trailing_slash_handling(self, normalizer):
        """Handle shop URLs with/without trailing slash."""
        raw = {"id": 123, "title": "Test", "handle": "test"}

        product1 = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://test.com/",  # With trailing slash
        )

        product2 = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://test.com",  # Without trailing slash
        )

        assert product1.product_url == "https://test.com/products/test"
        assert product2.product_url == "https://test.com/products/test"
