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

    def test_normalize_shopify_all_variants_out_of_stock(self, normalizer):
        """Product should be out of stock if all variants have inventory_quantity=0."""
        raw = {
            "id": 999,
            "title": "Out of Stock Product",
            "handle": "out-of-stock",
            "variants": [
                {
                    "id": 1,
                    "title": "Size S",
                    "price": "19.99",
                    "inventory_quantity": 0,
                },
                {
                    "id": 2,
                    "title": "Size M",
                    "price": "19.99",
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

        assert product.in_stock is False

    def test_normalize_shopify_mixed_stock_variants(self, normalizer):
        """Product should be in stock if ANY variant has inventory > 0."""
        raw = {
            "id": 888,
            "title": "Mixed Stock Product",
            "handle": "mixed-stock",
            "variants": [
                {
                    "id": 1,
                    "title": "Size S",
                    "price": "19.99",
                    "inventory_quantity": 0,
                },
                {
                    "id": 2,
                    "title": "Size M",
                    "price": "19.99",
                    "inventory_quantity": 5,
                },
            ],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://test.com",
        )

        assert product.in_stock is True

    def test_normalize_shopify_no_inventory_tracking(self, normalizer):
        """Product should be in stock if variants have no inventory_quantity field."""
        raw = {
            "id": 777,
            "title": "No Tracking Product",
            "handle": "no-tracking",
            "variants": [
                {
                    "id": 1,
                    "title": "Default",
                    "price": "19.99",
                    # No inventory_quantity field
                },
            ],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://test.com",
        )

        assert product.in_stock is True

    def test_normalize_shopify_no_variants(self, normalizer):
        """Product with no variants should default to in stock."""
        raw = {
            "id": 666,
            "title": "No Variants Product",
            "handle": "no-variants",
            "variants": [],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://test.com",
        )

        assert product.in_stock is True

    def test_normalize_shopify_uses_shop_currency(self, normalizer):
        """Should use _shop_currency from raw data if present."""
        raw = {
            "id": 555,
            "title": "Currency Test Product",
            "handle": "currency-test",
            "variants": [
                {
                    "id": 1,
                    "title": "Default",
                    "price": "29.99",
                },
            ],
            "_shop_currency": "EUR",
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://test.com",
        )

        assert product.currency == "EUR"

    def test_normalize_shopify_defaults_to_usd_without_shop_currency(self, normalizer):
        """Should default to USD if _shop_currency not present."""
        raw = {
            "id": 444,
            "title": "Default Currency Product",
            "handle": "default-currency",
            "variants": [
                {
                    "id": 1,
                    "title": "Default",
                    "price": "29.99",
                },
            ],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://test.com",
        )

        assert product.currency == "USD"


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

    def test_normalize_schema_org_image_dict(self, normalizer):
        """Handle image as dict (ImageObject with url)."""
        raw = {
            "name": "ImageObject Product",
            "image": {"@type": "ImageObject", "url": "https://example.com/dict-image.jpg"},
            "offers": {"price": "10.00"},
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product.image_url == "https://example.com/dict-image.jpg"

    def test_normalize_schema_org_image_dict_content_url(self, normalizer):
        """Handle image as dict (ImageObject with contentUrl)."""
        raw = {
            "name": "ContentUrl Product",
            "image": {"@type": "ImageObject", "contentUrl": "https://example.com/content-image.jpg"},
            "offers": {"price": "10.00"},
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product.image_url == "https://example.com/content-image.jpg"

    def test_normalize_schema_org_image_array_of_dicts(self, normalizer):
        """Handle image as array of ImageObject dicts."""
        raw = {
            "name": "Array Dict Image Product",
            "image": [
                {"@type": "ImageObject", "url": "https://example.com/first.jpg"},
                {"@type": "ImageObject", "url": "https://example.com/second.jpg"},
            ],
            "offers": {"price": "10.00"},
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product.image_url == "https://example.com/first.jpg"

    def test_normalize_schema_org_in_stock_from_availability(self, normalizer):
        """Extract in_stock from Schema.org availability field."""
        raw = {
            "name": "In Stock Product",
            "offers": {
                "price": "49.99",
                "priceCurrency": "USD",
                "availability": "https://schema.org/InStock",
            },
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product.in_stock is True

    def test_normalize_schema_org_out_of_stock_from_availability(self, normalizer):
        """Extract out of stock from Schema.org availability field."""
        raw = {
            "name": "Out of Stock Product",
            "offers": {
                "price": "49.99",
                "priceCurrency": "USD",
                "availability": "https://schema.org/OutOfStock",
            },
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product.in_stock is False

    def test_normalize_schema_org_defaults_in_stock_without_availability(self, normalizer):
        """Default to in stock if no availability field."""
        raw = {
            "name": "No Availability Product",
            "offers": {
                "price": "49.99",
                "priceCurrency": "USD",
            },
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product.in_stock is True

    def test_normalize_schema_org_availability_array_format(self, normalizer):
        """Handle offers as array with availability."""
        raw = {
            "name": "Array Offers Product",
            "offers": [
                {
                    "price": "49.99",
                    "priceCurrency": "USD",
                    "availability": "https://schema.org/InStock",
                },
            ],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product.in_stock is True


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
        """Invalid price string → price=0, no image, no SKU → rejected as non-product."""
        raw = {"title": "Test", "price": "invalid"}

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product is None

    def test_normalize_generic_css_field_aliases(self, normalizer):
        """Generic CSS should recognize title aliases."""
        test_cases = [
            {"name": "Product Name", "price": "29.99"},
            {"product_name": "Product Name", "price": "29.99"},
            {"heading": "Product Name", "price": "29.99"},
        ]

        for raw in test_cases:
            product = normalizer.normalize(
                raw=raw,
                shop_id="test",
                platform=Platform.GENERIC,
                shop_url="https://example.com",
            )
            assert product is not None
            assert product.title == "Product Name"

    def test_normalize_generic_css_image_aliases(self, normalizer):
        """Generic CSS should recognize image field aliases."""
        test_cases = [
            {"title": "Test", "image": "https://example.com/img1.jpg"},
            {"title": "Test", "image_url": "https://example.com/img2.jpg"},
            {"title": "Test", "src": "https://example.com/img3.jpg"},
        ]

        expected_urls = [
            "https://example.com/img1.jpg",
            "https://example.com/img2.jpg",
            "https://example.com/img3.jpg",
        ]

        for raw, expected_url in zip(test_cases, expected_urls):
            product = normalizer.normalize(
                raw=raw,
                shop_id="test",
                platform=Platform.GENERIC,
                shop_url="https://example.com",
            )
            assert product.image_url == expected_url

    def test_normalize_generic_css_url_aliases(self, normalizer):
        """Generic CSS should recognize product_url aliases."""
        test_cases = [
            {"title": "Test", "price": "9.99", "product_url": "https://example.com/product1"},
            {"title": "Test", "price": "9.99", "url": "https://example.com/product2"},
            {"title": "Test", "price": "9.99", "canonical": "https://example.com/product3"},
        ]

        expected_urls = [
            "https://example.com/product1",
            "https://example.com/product2",
            "https://example.com/product3",
        ]

        for raw, expected_url in zip(test_cases, expected_urls):
            product = normalizer.normalize(
                raw=raw,
                shop_id="test",
                platform=Platform.GENERIC,
                shop_url="https://example.com",
            )
            assert product.product_url == expected_url

    def test_normalize_generic_css_fallback_to_shop_url(self, normalizer):
        """Generic CSS should fall back to shop_url if no product_url."""
        raw = {"title": "Test", "price": "29.99"}

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product.product_url == "https://example.com"

    def test_normalize_generic_css_field_priority(self, normalizer):
        """Generic CSS should prioritize first available field."""
        raw = {
            "title": "Title Field",
            "name": "Name Field",
            "product_name": "Product Name Field",
            "price": "29.99",
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product.title == "Title Field"  # title takes priority


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


class TestProductValidityGate:
    """Test _is_valid_product quality gate in normalize()."""

    def test_rejects_zero_price_no_image_no_sku(self, normalizer):
        """Blog post: price=0, no image, no SKU, no external_id → rejected."""
        raw = {"title": "Awards Blog Post", "price": "0"}

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product is None

    def test_allows_zero_price_with_image(self, normalizer):
        """Free sample with image → passes (has image)."""
        raw = {
            "title": "Free Sample",
            "price": "0",
            "image": "https://example.com/sample.jpg",
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.price == Decimal("0")
        assert product.image_url == "https://example.com/sample.jpg"

    def test_allows_zero_price_with_sku(self, normalizer):
        """Free digital download with SKU → passes."""
        raw = {"title": "Free Download", "price": "0", "sku": "FREE-DL-001"}

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.sku == "FREE-DL-001"

    def test_allows_zero_price_with_external_id(self, normalizer):
        """API product with external_id → passes even with price=0."""
        raw = {
            "id": 7891234567890,
            "title": "Shopify Zero Price Product",
            "handle": "zero-price",
            "variants": [{"id": 1, "price": "0.00"}],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.SHOPIFY,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.external_id == "7891234567890"

    def test_allows_normal_product(self, normalizer):
        """Standard product with price, image, and SKU → passes."""
        raw = {
            "title": "Normal Product",
            "price": "$29.99",
            "image": "https://example.com/img.jpg",
            "sku": "NP-001",
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.price == Decimal("29.99")


class TestGTINValidation:
    """Test _validate_gtin static method."""

    def test_validate_gtin_valid_ean13(self, normalizer):
        assert normalizer._validate_gtin("4006381333931") == "4006381333931"

    def test_validate_gtin_valid_upc_a_zero_padded(self, normalizer):
        assert normalizer._validate_gtin("012345678905") == "0012345678905"

    def test_validate_gtin_valid_gtin8(self, normalizer):
        assert normalizer._validate_gtin("96385074") == "96385074"

    def test_validate_gtin_valid_gtin14(self, normalizer):
        assert normalizer._validate_gtin("10012345678902") == "10012345678902"

    def test_validate_gtin_rejects_all_zeros(self, normalizer):
        assert normalizer._validate_gtin("0000000000000") is None
        assert normalizer._validate_gtin("000000000000") is None
        assert normalizer._validate_gtin("00000000") is None

    def test_validate_gtin_rejects_non_numeric(self, normalizer):
        assert normalizer._validate_gtin("ABC123456789") is None
        assert normalizer._validate_gtin("123-456-789") is None
        assert normalizer._validate_gtin("123 456 789") is None

    def test_validate_gtin_rejects_wrong_length(self, normalizer):
        assert normalizer._validate_gtin("1234567890") is None  # 10 digits

    def test_validate_gtin_strips_whitespace(self, normalizer):
        assert normalizer._validate_gtin("  4006381333931  ") == "4006381333931"

    def test_validate_gtin_none_returns_none(self, normalizer):
        assert normalizer._validate_gtin(None) is None

    def test_validate_gtin_empty_returns_none(self, normalizer):
        assert normalizer._validate_gtin("") is None
        assert normalizer._validate_gtin("   ") is None

    def test_validate_gtin_strips_dashes_and_spaces(self, normalizer):
        assert normalizer._validate_gtin("5901234-123457") == "5901234123457"
        assert normalizer._validate_gtin("590 1234 123457") == "5901234123457"

    def test_schema_org_gtin_from_offers(self, normalizer):
        raw = {
            "name": "Product Without Root GTIN",
            "offers": {
                "price": "19.99",
                "priceCurrency": "USD",
                "gtin13": "4006381333931",
            },
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.gtin == "4006381333931"

    def test_schema_org_mpn_from_offers(self, normalizer):
        raw = {
            "name": "Product Without Root MPN",
            "offers": {
                "price": "29.99",
                "priceCurrency": "USD",
                "mpn": "MPN-98765",
            },
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.mpn == "MPN-98765"

    def test_schema_org_product_gtin_takes_precedence(self, normalizer):
        raw = {
            "name": "Product With Both GTINs",
            "gtin13": "4006381333931",
            "offers": {
                "price": "39.99",
                "priceCurrency": "USD",
                "gtin13": "9999999999999",
            },
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.gtin == "4006381333931"


class TestAdditionalPropertyParsing:
    """Test additionalProperty fallback for GTIN/MPN in Schema.org normalization."""

    def test_schema_org_gtin_from_additional_property(self, normalizer):
        raw = {
            "name": "Widget",
            "offers": {"price": "9.99", "priceCurrency": "USD"},
            "additionalProperty": [
                {"@type": "PropertyValue", "propertyID": "gtin13", "value": "4006381333931"},
            ],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.external_id == "4006381333931"

    def test_schema_org_mpn_from_additional_property(self, normalizer):
        raw = {
            "name": "Gadget",
            "offers": {"price": "19.99", "priceCurrency": "USD"},
            "additionalProperty": [
                {"@type": "PropertyValue", "propertyID": "mpn", "value": "ABC-123"},
            ],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.sku == "ABC-123"

    def test_schema_org_direct_gtin_takes_precedence_over_additional_property(self, normalizer):
        raw = {
            "name": "Widget",
            "sku": "DIRECT-SKU",
            "offers": {"price": "9.99", "priceCurrency": "USD"},
            "additionalProperty": [
                {"@type": "PropertyValue", "propertyID": "gtin13", "value": "9999999999999"},
            ],
        }

        product = normalizer.normalize(
            raw=raw,
            shop_id="test",
            platform=Platform.GENERIC,
            shop_url="https://example.com",
        )

        assert product is not None
        assert product.external_id == "DIRECT-SKU"
        assert product.sku == "DIRECT-SKU"
