"""Unit tests for WooCommerce Admin REST API v3 extractor."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.oauth_store import OAuthConnection
from app.extractors.woocommerce_admin_extractor import (
    WooCommerceAdminExtractor,
    _GTIN_META_KEYS,
)


# ── Fixtures ─────────────────────────────────────────────────────────


def _make_connection(
    consumer_key: str = "ck_test_key",
    consumer_secret: str = "cs_test_secret",
    shop_domain: str = "my-store.com",
) -> OAuthConnection:
    return OAuthConnection(
        id=1,
        platform="woocommerce",
        shop_domain=shop_domain,
        consumer_key=consumer_key,
        consumer_secret=consumer_secret,
    )


def _make_product(
    product_id: int = 1,
    name: str = "Test Product",
    price: str = "29.99",
    sku: str = "SKU-001",
    meta_data: list | None = None,
    product_type: str = "simple",
    images: list | None = None,
    categories: list | None = None,
    stock_status: str = "instock",
) -> dict:
    return {
        "id": product_id,
        "name": name,
        "slug": f"test-product-{product_id}",
        "type": product_type,
        "status": "publish",
        "description": "<p>A test product.</p>",
        "short_description": "Short desc",
        "sku": sku,
        "price": price,
        "regular_price": price,
        "sale_price": "",
        "stock_status": stock_status,
        "stock_quantity": 10,
        "weight": "0.5",
        "permalink": f"https://my-store.com/product/test-product-{product_id}",
        "images": [{"id": 100, "src": "https://my-store.com/image1.jpg", "alt": "Image 1"}] if images is None else images,
        "categories": [{"id": 10, "name": "Electronics"}] if categories is None else categories,
        "tags": [{"id": 20, "name": "sale"}],
        "meta_data": meta_data or [],
        "attributes": [],
    }


# ── Constructor ──────────────────────────────────────────────────────


class TestConstructor:

    def test_requires_consumer_key(self):
        conn = _make_connection(consumer_key="")
        with pytest.raises(ValueError, match="consumer_key"):
            WooCommerceAdminExtractor(conn)

    def test_requires_consumer_secret(self):
        conn = _make_connection(consumer_secret="")
        with pytest.raises(ValueError, match="consumer_secret"):
            WooCommerceAdminExtractor(conn)

    def test_valid_connection(self):
        conn = _make_connection()
        extractor = WooCommerceAdminExtractor(conn)
        assert extractor._shop_domain == "my-store.com"
        assert extractor._consumer_key == "ck_test_key"


# ── GTIN extraction from meta_data ───────────────────────────────────


class TestExtractGtinFromMeta:

    def test_wpm_gtin_plugin(self):
        meta = [{"key": "_wpm_gtin_code", "value": "5901234123457"}]
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(meta) == "5901234123457"

    def test_ean_plugin(self):
        meta = [{"key": "_ean", "value": "4006381333931"}]
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(meta) == "4006381333931"

    def test_alg_ean_plugin(self):
        meta = [{"key": "_alg_ean", "value": "4260012345678"}]
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(meta) == "4260012345678"

    def test_barcode_plugin(self):
        meta = [{"key": "_barcode", "value": "1234567890123"}]
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(meta) == "1234567890123"

    def test_germanized_gtin(self):
        meta = [{"key": "_ts_gtin", "value": "4260012345678"}]
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(meta) == "4260012345678"

    def test_yith_barcode(self):
        meta = [{"key": "_yith_barcode_value", "value": "9780201379624"}]
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(meta) == "9780201379624"

    def test_generic_gtin_key(self):
        meta = [{"key": "gtin", "value": "4006381333931"}]
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(meta) == "4006381333931"

    def test_generic_ean_key(self):
        meta = [{"key": "ean", "value": "4006381333931"}]
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(meta) == "4006381333931"

    def test_regex_fallback_for_unknown_plugin(self):
        """Should find GTIN in unknown keys via regex pattern matching."""
        meta = [{"key": "custom_product_gtin_field", "value": "5901234123457"}]
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(meta) == "5901234123457"

    def test_regex_fallback_ean_in_key(self):
        meta = [{"key": "product_ean_code", "value": "4006381333931"}]
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(meta) == "4006381333931"

    def test_ignores_short_values(self):
        """Values with fewer than 8 digits should be rejected."""
        meta = [{"key": "_wpm_gtin_code", "value": "123"}]
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(meta) is None

    def test_empty_meta_data(self):
        assert WooCommerceAdminExtractor._extract_gtin_from_meta([]) is None

    def test_none_meta_data(self):
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(None) is None

    def test_empty_value_ignored(self):
        meta = [{"key": "_wpm_gtin_code", "value": ""}]
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(meta) is None

    def test_known_key_preferred_over_regex(self):
        """Known keys should be checked first (exact match before regex)."""
        meta = [
            {"key": "some_random_ean_field", "value": "1111111111111"},
            {"key": "_wpm_gtin_code", "value": "2222222222222"},
        ]
        # Known key _wpm_gtin_code should win (first pass)
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(meta) == "2222222222222"

    def test_private_meta_keys_skipped(self):
        """Non-GTIN private meta keys should be ignored."""
        meta = [
            {"key": "_wp_page_template", "value": "default"},
            {"key": "_edit_lock", "value": "1615000000:1"},
        ]
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(meta) is None

    def test_hwp_var_gtin(self):
        """Variation-level GTIN from HikaWP plugin."""
        meta = [{"key": "hwp_var_gtin", "value": "5901234567890"}]
        assert WooCommerceAdminExtractor._extract_gtin_from_meta(meta) == "5901234567890"


# ── Product normalization ────────────────────────────────────────────


class TestNormalizeProduct:

    def test_basic_product(self):
        conn = _make_connection()
        extractor = WooCommerceAdminExtractor(conn)
        product = _make_product()

        result = extractor._normalize_product(product, "https://my-store.com")

        assert result["id"] == "1"
        assert result["title"] == "Test Product"
        assert result["price"] == "29.99"
        assert result["sku"] == "SKU-001"
        assert result["image_url"] == "https://my-store.com/image1.jpg"
        assert result["in_stock"] is True
        assert result["categories"] == ["Electronics"]
        assert result["_source"] == "woocommerce_admin_api"
        assert result["_platform"] == "woocommerce"

    def test_product_with_gtin(self):
        conn = _make_connection()
        extractor = WooCommerceAdminExtractor(conn)
        product = _make_product(
            meta_data=[{"key": "_wpm_gtin_code", "value": "5901234123457"}]
        )

        result = extractor._normalize_product(product, "https://my-store.com")

        assert result["gtin"] == "5901234123457"
        assert result["barcode"] == "5901234123457"

    def test_product_no_images(self):
        conn = _make_connection()
        extractor = WooCommerceAdminExtractor(conn)
        product = _make_product(images=[])

        result = extractor._normalize_product(product, "https://my-store.com")

        assert result["image_url"] == ""
        assert result["additional_images"] == []

    def test_product_multiple_images(self):
        conn = _make_connection()
        extractor = WooCommerceAdminExtractor(conn)
        product = _make_product(images=[
            {"id": 1, "src": "https://my-store.com/img1.jpg", "alt": ""},
            {"id": 2, "src": "https://my-store.com/img2.jpg", "alt": ""},
            {"id": 3, "src": "https://my-store.com/img3.jpg", "alt": ""},
        ])

        result = extractor._normalize_product(product, "https://my-store.com")

        assert result["image_url"] == "https://my-store.com/img1.jpg"
        assert result["additional_images"] == [
            "https://my-store.com/img2.jpg",
            "https://my-store.com/img3.jpg",
        ]

    def test_out_of_stock(self):
        conn = _make_connection()
        extractor = WooCommerceAdminExtractor(conn)
        product = _make_product(stock_status="outofstock")

        result = extractor._normalize_product(product, "https://my-store.com")

        assert result["in_stock"] is False

    def test_sale_price_sets_compare_at(self):
        conn = _make_connection()
        extractor = WooCommerceAdminExtractor(conn)
        product = _make_product(price="19.99")
        product["regular_price"] = "29.99"
        product["sale_price"] = "19.99"

        result = extractor._normalize_product(product, "https://my-store.com")

        assert result["price"] == "19.99"
        assert result["compare_at_price"] == "29.99"

    def test_tags_extracted(self):
        conn = _make_connection()
        extractor = WooCommerceAdminExtractor(conn)
        product = _make_product()
        product["tags"] = [
            {"id": 1, "name": "Summer"},
            {"id": 2, "name": "New Arrival"},
        ]

        result = extractor._normalize_product(product, "https://my-store.com")

        assert result["tags"] == ["Summer", "New Arrival"]


# ── Extract (HTTP mocking) ───────────────────────────────────────────


class TestExtract:

    @pytest.mark.asyncio
    async def test_extract_single_page(self):
        import respx
        from httpx import Response

        conn = _make_connection()
        extractor = WooCommerceAdminExtractor(conn)

        products = [_make_product(product_id=i) for i in range(3)]

        with respx.mock:
            respx.get("https://my-store.com/wp-json/wc/v3/products").mock(
                return_value=Response(
                    200,
                    json=products,
                    headers={
                        "X-WP-Total": "3",
                        "X-WP-TotalPages": "1",
                    },
                )
            )

            result = await extractor.extract("https://my-store.com")

        assert result.product_count == 3
        assert result.complete is True
        assert result.error is None

    @pytest.mark.asyncio
    async def test_extract_multiple_pages(self):
        import respx
        from httpx import Response

        conn = _make_connection()
        extractor = WooCommerceAdminExtractor(conn)

        page1 = [_make_product(product_id=i) for i in range(100)]
        page2 = [_make_product(product_id=i) for i in range(100, 150)]

        call_count = 0

        def route_handler(request):
            nonlocal call_count
            call_count += 1
            page = int(request.url.params.get("page", "1"))
            if page == 1:
                return Response(
                    200,
                    json=page1,
                    headers={"X-WP-Total": "150", "X-WP-TotalPages": "2"},
                )
            else:
                return Response(
                    200,
                    json=page2,
                    headers={"X-WP-Total": "150", "X-WP-TotalPages": "2"},
                )

        with respx.mock:
            respx.get("https://my-store.com/wp-json/wc/v3/products").mock(
                side_effect=route_handler
            )

            result = await extractor.extract("https://my-store.com")

        assert result.product_count == 150
        assert result.complete is True

    @pytest.mark.asyncio
    async def test_extract_401_returns_error(self):
        import respx
        from httpx import Response

        conn = _make_connection()
        extractor = WooCommerceAdminExtractor(conn)

        with respx.mock:
            respx.get("https://my-store.com/wp-json/wc/v3/products").mock(
                return_value=Response(401, json={"code": "woocommerce_rest_cannot_view"})
            )

            result = await extractor.extract("https://my-store.com")

        assert result.product_count == 0
        assert result.complete is False
        assert "invalid" in result.error.lower()

    @pytest.mark.asyncio
    async def test_extract_403_returns_error(self):
        import respx
        from httpx import Response

        conn = _make_connection()
        extractor = WooCommerceAdminExtractor(conn)

        with respx.mock:
            respx.get("https://my-store.com/wp-json/wc/v3/products").mock(
                return_value=Response(403, json={"code": "woocommerce_rest_forbidden"})
            )

            result = await extractor.extract("https://my-store.com")

        assert result.product_count == 0
        assert result.complete is False
        assert "permission" in result.error.lower()

    @pytest.mark.asyncio
    async def test_extract_404_returns_error(self):
        import respx
        from httpx import Response

        conn = _make_connection()
        extractor = WooCommerceAdminExtractor(conn)

        with respx.mock:
            respx.get("https://my-store.com/wp-json/wc/v3/products").mock(
                return_value=Response(404)
            )

            result = await extractor.extract("https://my-store.com")

        assert result.product_count == 0
        assert result.complete is False
        assert "404" in result.error

    @pytest.mark.asyncio
    async def test_extract_with_gtin_in_meta(self):
        import respx
        from httpx import Response

        conn = _make_connection()
        extractor = WooCommerceAdminExtractor(conn)

        product = _make_product(
            meta_data=[{"key": "_alg_ean", "value": "4260012345678"}]
        )

        with respx.mock:
            respx.get("https://my-store.com/wp-json/wc/v3/products").mock(
                return_value=Response(
                    200,
                    json=[product],
                    headers={"X-WP-Total": "1", "X-WP-TotalPages": "1"},
                )
            )

            result = await extractor.extract("https://my-store.com")

        assert result.product_count == 1
        assert result.products[0]["gtin"] == "4260012345678"


# ── Variation fetching ───────────────────────────────────────────────


class TestVariations:

    @pytest.mark.asyncio
    async def test_variable_product_fetches_variations(self):
        import respx
        from httpx import Response

        conn = _make_connection()
        extractor = WooCommerceAdminExtractor(conn)

        parent = _make_product(product_id=1, product_type="variable")
        variations = [
            {
                "id": 101,
                "price": "19.99",
                "sku": "SKU-001-RED",
                "stock_quantity": 5,
                "attributes": [{"name": "Color", "option": "Red"}],
                "meta_data": [{"key": "_ean", "value": "4006381333931"}],
            },
            {
                "id": 102,
                "price": "19.99",
                "sku": "SKU-001-BLUE",
                "stock_quantity": 3,
                "attributes": [{"name": "Color", "option": "Blue"}],
                "meta_data": [],
            },
        ]

        with respx.mock:
            respx.get("https://my-store.com/wp-json/wc/v3/products").mock(
                return_value=Response(
                    200,
                    json=[parent],
                    headers={"X-WP-Total": "1", "X-WP-TotalPages": "1"},
                )
            )
            respx.get("https://my-store.com/wp-json/wc/v3/products/1/variations").mock(
                return_value=Response(
                    200,
                    json=variations,
                    headers={"X-WP-TotalPages": "1"},
                )
            )

            result = await extractor.extract("https://my-store.com")

        assert result.product_count == 1
        product = result.products[0]
        assert len(product["variants"]) == 2

        red_variant = product["variants"][0]
        assert red_variant["title"] == "Red"
        assert red_variant["sku"] == "SKU-001-RED"
        assert red_variant["barcode"] == "4006381333931"

        blue_variant = product["variants"][1]
        assert blue_variant["title"] == "Blue"
        assert blue_variant["barcode"] == ""


# ── Known GTIN meta keys coverage ────────────────────────────────────


class TestGtinMetaKeysCoverage:
    """Verify all documented GTIN plugin keys are in our set."""

    def test_wpm_gtin_in_known_keys(self):
        assert "_wpm_gtin_code" in _GTIN_META_KEYS

    def test_ean_in_known_keys(self):
        assert "_ean" in _GTIN_META_KEYS

    def test_alg_ean_in_known_keys(self):
        assert "_alg_ean" in _GTIN_META_KEYS

    def test_barcode_in_known_keys(self):
        assert "_barcode" in _GTIN_META_KEYS

    def test_germanized_gtin_in_known_keys(self):
        assert "_ts_gtin" in _GTIN_META_KEYS

    def test_yith_barcode_in_known_keys(self):
        assert "_yith_barcode_value" in _GTIN_META_KEYS

    def test_generic_gtin_in_known_keys(self):
        assert "gtin" in _GTIN_META_KEYS

    def test_generic_ean_in_known_keys(self):
        assert "ean" in _GTIN_META_KEYS

    def test_generic_upc_in_known_keys(self):
        assert "upc" in _GTIN_META_KEYS
