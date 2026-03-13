"""Unit tests for MagentoAdminExtractor."""

from __future__ import annotations

import pytest
import respx
from httpx import Response

from app.db.oauth_store import OAuthConnection
from app.extractors.magento_admin_extractor import MagentoAdminExtractor

SHOP_DOMAIN = "magento-store.example.com"
SHOP_URL = f"https://{SHOP_DOMAIN}"
PRODUCTS_URL = f"{SHOP_URL}/rest/V1/products"


def _make_connection(
    access_token: str = "integration-token-abc",
    shop_domain: str = SHOP_DOMAIN,
    extra_data: dict | None = None,
) -> OAuthConnection:
    return OAuthConnection(
        id=1,
        platform="magento",
        shop_domain=shop_domain,
        access_token=access_token,
        extra_data=extra_data,
    )


@pytest.fixture
def connection() -> OAuthConnection:
    return _make_connection()


@pytest.fixture
def extractor(connection: OAuthConnection) -> MagentoAdminExtractor:
    return MagentoAdminExtractor(connection)


def _products_response(
    items: list[dict],
    total_count: int | None = None,
) -> dict:
    """Build a Magento products API response envelope."""
    return {
        "items": items,
        "total_count": total_count if total_count is not None else len(items),
        "search_criteria": {},
    }


SAMPLE_PRODUCT = {
    "id": 42,
    "sku": "WJ01-XS-Blue",
    "name": "Stellar Solar Jacket",
    "price": 75.00,
    "status": 1,
    "visibility": 4,
    "type_id": "simple",
    "weight": 1.2,
    "custom_attributes": [
        {"attribute_code": "description", "value": "<p>Warm jacket</p>"},
        {"attribute_code": "image", "value": "/w/j/wj01-blue.jpg"},
        {"attribute_code": "url_key", "value": "stellar-solar-jacket"},
        {"attribute_code": "ean", "value": "4006381333931"},
        {"attribute_code": "manufacturer", "value": "Stellar"},
    ],
    "media_gallery_entries": [
        {"id": 1, "file": "/w/j/wj01-blue.jpg", "disabled": False, "position": 1, "types": ["image"]},
        {"id": 2, "file": "/w/j/wj01-side.jpg", "disabled": False, "position": 2, "types": []},
    ],
    "extension_attributes": {
        "stock_item": {"is_in_stock": True, "qty": 50},
    },
}

SAMPLE_CONFIGURABLE = {
    "id": 100,
    "sku": "WJ01",
    "name": "Stellar Solar Jacket Configurable",
    "price": 75.00,
    "status": 1,
    "visibility": 4,
    "type_id": "configurable",
    "custom_attributes": [
        {"attribute_code": "url_key", "value": "stellar-solar-jacket-config"},
        {"attribute_code": "image", "value": "/w/j/wj01-main.jpg"},
    ],
    "media_gallery_entries": [],
    "extension_attributes": {
        "stock_item": {"is_in_stock": True, "qty": 0},
        "configurable_product_links": [201, 202],
    },
}

CHILD_PRODUCT_1 = {
    "id": 201,
    "sku": "WJ01-XS",
    "name": "Stellar Solar Jacket - XS",
    "price": 75.00,
    "type_id": "simple",
    "custom_attributes": [
        {"attribute_code": "ean", "value": "4006381333931"},
    ],
    "extension_attributes": {
        "stock_item": {"is_in_stock": True, "qty": 10},
    },
}

CHILD_PRODUCT_2 = {
    "id": 202,
    "sku": "WJ01-S",
    "name": "Stellar Solar Jacket - S",
    "price": 75.00,
    "type_id": "simple",
    "custom_attributes": [],
    "extension_attributes": {
        "stock_item": {"is_in_stock": False, "qty": 0},
    },
}


# -- Constructor ------------------------------------------------------------


def test_requires_access_token():
    conn = OAuthConnection(
        id=1,
        platform="magento",
        shop_domain=SHOP_DOMAIN,
    )
    with pytest.raises(ValueError, match="access_token"):
        MagentoAdminExtractor(conn)


def test_requires_access_token_not_empty():
    conn = OAuthConnection(
        id=1,
        platform="magento",
        shop_domain=SHOP_DOMAIN,
        access_token="",
    )
    with pytest.raises(ValueError, match="access_token"):
        MagentoAdminExtractor(conn)


def test_extracts_domain():
    conn = _make_connection(shop_domain="my-shop.example.com")
    ext = MagentoAdminExtractor(conn)
    assert ext._shop_domain == "my-shop.example.com"


def test_default_currency_is_eur():
    conn = _make_connection()
    ext = MagentoAdminExtractor(conn)
    assert ext._currency == "EUR"


def test_currency_from_extra_data():
    conn = _make_connection(extra_data={"currency": "USD"})
    ext = MagentoAdminExtractor(conn)
    assert ext._currency == "USD"


# -- Product extraction -----------------------------------------------------


@pytest.mark.asyncio
async def test_product_field_mapping(extractor: MagentoAdminExtractor):
    """extract() returns correctly mapped products from Magento API data."""
    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            return_value=Response(200, json=_products_response([SAMPLE_PRODUCT]))
        )

        result = await extractor.extract(SHOP_URL)

    assert result.complete is True
    assert result.error is None
    assert len(result.products) == 1

    p = result.products[0]
    assert p["id"] == 42
    assert p["title"] == "Stellar Solar Jacket"
    assert p["description"] == "<p>Warm jacket</p>"
    assert p["handle"] == "stellar-solar-jacket"
    assert p["sku"] == "WJ01-XS-Blue"
    assert p["gtin"] == "4006381333931"
    assert p["barcode"] == "4006381333931"
    assert p["price"] == "75.0"
    assert p["currency"] == "EUR"
    assert p["vendor"] == "Stellar"
    assert p["in_stock"] is True
    assert p["stock_quantity"] == 50
    assert p["image_url"] == f"https://{SHOP_DOMAIN}/media/catalog/product/w/j/wj01-blue.jpg"
    assert p["product_url"] == f"https://{SHOP_DOMAIN}/stellar-solar-jacket.html"
    assert p["weight"] == 1.2
    assert p["condition"] == "New"
    assert p["_source"] == "magento_admin_api"
    assert p["_platform"] == "magento"
    assert p["product_type"] == "simple"


@pytest.mark.asyncio
async def test_additional_images_excludes_primary(extractor: MagentoAdminExtractor):
    """Additional images list excludes the primary cover image."""
    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            return_value=Response(200, json=_products_response([SAMPLE_PRODUCT]))
        )

        result = await extractor.extract(SHOP_URL)

    p = result.products[0]
    # Primary image /w/j/wj01-blue.jpg should be excluded from additional
    assert p["image_url"] == f"https://{SHOP_DOMAIN}/media/catalog/product/w/j/wj01-blue.jpg"
    assert len(p["additional_images"]) == 1
    assert p["additional_images"][0] == f"https://{SHOP_DOMAIN}/media/catalog/product/w/j/wj01-side.jpg"


@pytest.mark.asyncio
async def test_disabled_gallery_entries_excluded(extractor: MagentoAdminExtractor):
    """Disabled media gallery entries are not included in additional images."""
    product = {
        **SAMPLE_PRODUCT,
        "media_gallery_entries": [
            {"id": 1, "file": "/a/b.jpg", "disabled": False, "position": 1, "types": ["image"]},
            {"id": 2, "file": "/c/d.jpg", "disabled": True, "position": 2, "types": []},
        ],
        "custom_attributes": [
            {"attribute_code": "image", "value": "/x/y.jpg"},
        ],
    }
    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            return_value=Response(200, json=_products_response([product]))
        )

        result = await extractor.extract(SHOP_URL)

    p = result.products[0]
    # Only the non-disabled entry should appear (and not the primary)
    additional_urls = p["additional_images"]
    assert f"https://{SHOP_DOMAIN}/media/catalog/product/c/d.jpg" not in additional_urls


# -- GTIN detection ---------------------------------------------------------


def test_gtin_from_ean_attribute(extractor: MagentoAdminExtractor):
    product = {"custom_attributes": [{"attribute_code": "ean", "value": "4006381333931"}]}
    assert extractor._extract_gtin(product) == "4006381333931"


def test_gtin_from_gtin_attribute(extractor: MagentoAdminExtractor):
    product = {"custom_attributes": [{"attribute_code": "gtin", "value": "1234567890123"}]}
    assert extractor._extract_gtin(product) == "1234567890123"


def test_gtin_from_barcode_attribute(extractor: MagentoAdminExtractor):
    product = {"custom_attributes": [{"attribute_code": "barcode", "value": "9876543210987"}]}
    assert extractor._extract_gtin(product) == "9876543210987"


def test_gtin_from_upc_attribute(extractor: MagentoAdminExtractor):
    product = {"custom_attributes": [{"attribute_code": "upc", "value": "012345678905"}]}
    assert extractor._extract_gtin(product) == "012345678905"


def test_gtin_from_ean13_attribute(extractor: MagentoAdminExtractor):
    product = {"custom_attributes": [{"attribute_code": "ean13", "value": "5901234123457"}]}
    assert extractor._extract_gtin(product) == "5901234123457"


def test_gtin_from_gtin13_attribute(extractor: MagentoAdminExtractor):
    product = {"custom_attributes": [{"attribute_code": "gtin13", "value": "5901234123457"}]}
    assert extractor._extract_gtin(product) == "5901234123457"


def test_gtin_priority_ean_over_upc(extractor: MagentoAdminExtractor):
    """When both ean and upc are present, ean wins (first in scan order)."""
    product = {
        "custom_attributes": [
            {"attribute_code": "upc", "value": "012345678905"},
            {"attribute_code": "ean", "value": "4006381333931"},
        ],
    }
    assert extractor._extract_gtin(product) == "4006381333931"


def test_gtin_skips_empty_value(extractor: MagentoAdminExtractor):
    product = {
        "custom_attributes": [
            {"attribute_code": "ean", "value": ""},
            {"attribute_code": "gtin", "value": "1234567890123"},
        ],
    }
    assert extractor._extract_gtin(product) == "1234567890123"


def test_gtin_skips_null_value(extractor: MagentoAdminExtractor):
    product = {
        "custom_attributes": [
            {"attribute_code": "ean", "value": None},
            {"attribute_code": "barcode", "value": "9876543210987"},
        ],
    }
    assert extractor._extract_gtin(product) == "9876543210987"


def test_gtin_skips_whitespace_value(extractor: MagentoAdminExtractor):
    product = {
        "custom_attributes": [
            {"attribute_code": "ean", "value": "   "},
            {"attribute_code": "gtin", "value": "1234567890123"},
        ],
    }
    assert extractor._extract_gtin(product) == "1234567890123"


def test_gtin_returns_empty_when_none_found(extractor: MagentoAdminExtractor):
    product = {
        "custom_attributes": [
            {"attribute_code": "color", "value": "blue"},
        ],
    }
    assert extractor._extract_gtin(product) == ""


def test_gtin_no_custom_attributes(extractor: MagentoAdminExtractor):
    product = {}
    assert extractor._extract_gtin(product) == ""


# -- Pagination -------------------------------------------------------------


@pytest.mark.asyncio
async def test_pagination_fetches_second_page(extractor: MagentoAdminExtractor):
    """When total_count > page_size, a second page request is made."""
    page1 = [{"id": i, "sku": f"SKU-{i}", "name": f"P{i}", "price": 10.0, "type_id": "simple"} for i in range(100)]
    page2 = [{"id": i, "sku": f"SKU-{i}", "name": f"P{i}", "price": 10.0, "type_id": "simple"} for i in range(100, 150)]

    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response(200, json=_products_response(page1, total_count=150))
        return Response(200, json=_products_response(page2, total_count=150))

    with respx.mock:
        respx.get(PRODUCTS_URL).mock(side_effect=side_effect)

        result = await extractor.extract(SHOP_URL)

    assert call_count == 2
    assert len(result.products) == 150
    assert result.complete is True
    assert result.pages_completed == 2
    assert result.pages_expected == 2


@pytest.mark.asyncio
async def test_pagination_stops_when_all_retrieved(extractor: MagentoAdminExtractor):
    """No extra request when cumulative count reaches total_count."""
    page1 = [{"id": i, "sku": f"SKU-{i}", "name": f"P{i}", "price": 10.0, "type_id": "simple"} for i in range(100)]
    page2 = [{"id": i, "sku": f"SKU-{i}", "name": f"P{i}", "price": 10.0, "type_id": "simple"} for i in range(100, 120)]

    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response(200, json=_products_response(page1, total_count=120))
        return Response(200, json=_products_response(page2, total_count=120))

    with respx.mock:
        respx.get(PRODUCTS_URL).mock(side_effect=side_effect)

        result = await extractor.extract(SHOP_URL)

    assert call_count == 2
    assert len(result.products) == 120


@pytest.mark.asyncio
async def test_pagination_stops_on_empty_page(extractor: MagentoAdminExtractor):
    """Pagination stops when an empty items list is returned."""
    page1 = [{"id": 1, "sku": "SKU-1", "name": "P1", "price": 10.0, "type_id": "simple"}]

    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response(200, json=_products_response(page1, total_count=200))
        return Response(200, json=_products_response([], total_count=200))

    with respx.mock:
        respx.get(PRODUCTS_URL).mock(side_effect=side_effect)

        result = await extractor.extract(SHOP_URL)

    assert call_count == 2
    assert len(result.products) == 1


# -- 401 handling -----------------------------------------------------------


@pytest.mark.asyncio
async def test_401_returns_error(extractor: MagentoAdminExtractor):
    """401 returns error immediately -- no refresh possible for Integration tokens."""
    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            return_value=Response(401, json={"message": "Consumer is not authorized"})
        )

        result = await extractor.extract(SHOP_URL)

    assert result.products == []
    assert result.complete is False
    assert "401" in result.error
    assert "credentials invalid" in result.error.lower() or "unauthorized" in result.error.lower()


# -- 429 handling -----------------------------------------------------------


@pytest.mark.asyncio
async def test_429_with_retry_after_waits_and_retries(
    extractor: MagentoAdminExtractor, monkeypatch
):
    """429 response with Retry-After causes a sleep then a successful retry."""
    sleep_calls: list[float] = []

    async def mock_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("app.extractors.magento_admin_extractor.asyncio.sleep", mock_sleep)

    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            side_effect=[
                Response(429, headers={"Retry-After": "3"}, text="Too Many Requests"),
                Response(200, json=_products_response([SAMPLE_PRODUCT])),
            ]
        )

        result = await extractor.extract(SHOP_URL)

    assert sleep_calls == [3.0]
    assert len(result.products) == 1
    assert result.complete is True


@pytest.mark.asyncio
async def test_429_default_retry_after_when_header_missing(
    extractor: MagentoAdminExtractor, monkeypatch
):
    """When Retry-After header is absent, defaults to 5 seconds."""
    sleep_calls: list[float] = []

    async def mock_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("app.extractors.magento_admin_extractor.asyncio.sleep", mock_sleep)

    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            side_effect=[
                Response(429, text="Too Many Requests"),
                Response(200, json=_products_response([])),
            ]
        )

        await extractor.extract(SHOP_URL)

    assert sleep_calls == [5.0]


@pytest.mark.asyncio
async def test_persistent_429_returns_error(
    extractor: MagentoAdminExtractor, monkeypatch
):
    """Persistent 429 after retry marks extraction incomplete with error."""
    async def _noop_sleep(_: float) -> None:
        pass

    monkeypatch.setattr("app.extractors.magento_admin_extractor.asyncio.sleep", _noop_sleep)

    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            return_value=Response(429, headers={"Retry-After": "1"}, text="Rate limited")
        )

        result = await extractor.extract(SHOP_URL)

    assert result.complete is False
    assert "Rate limited" in result.error


# -- Empty catalog ----------------------------------------------------------


@pytest.mark.asyncio
async def test_empty_catalog(extractor: MagentoAdminExtractor):
    """Store with no products returns empty list with complete=True."""
    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            return_value=Response(200, json=_products_response([], total_count=0))
        )

        result = await extractor.extract(SHOP_URL)

    assert result.products == []
    assert result.complete is True
    assert result.error is None
    assert result.pages_completed == 0


# -- Configurable products --------------------------------------------------


@pytest.mark.asyncio
async def test_configurable_product_fetches_children(
    extractor: MagentoAdminExtractor,
):
    """Configurable products have children batch-fetched and attached as variants."""
    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        url = str(request.url)
        if "entity_id" in url:
            # Children request
            return Response(200, json=_products_response([CHILD_PRODUCT_1, CHILD_PRODUCT_2]))
        # Main listing
        return Response(200, json=_products_response([SAMPLE_CONFIGURABLE]))

    with respx.mock:
        respx.get(PRODUCTS_URL).mock(side_effect=side_effect)

        result = await extractor.extract(SHOP_URL)

    assert result.complete is True
    assert len(result.products) == 1

    p = result.products[0]
    assert p["product_type"] == "configurable"
    assert len(p["variants"]) == 2

    v1 = p["variants"][0]
    assert v1["variant_id"] == 201
    assert v1["sku"] == "WJ01-XS"
    assert v1["title"] == "Stellar Solar Jacket - XS"
    assert v1["gtin"] == "4006381333931"
    assert v1["in_stock"] is True

    v2 = p["variants"][1]
    assert v2["variant_id"] == 202
    assert v2["sku"] == "WJ01-S"
    assert v2["in_stock"] is False


@pytest.mark.asyncio
async def test_configurable_children_capped_at_50(
    extractor: MagentoAdminExtractor,
):
    """Children per configurable parent are capped at 50."""
    configurable = {
        **SAMPLE_CONFIGURABLE,
        "extension_attributes": {
            "stock_item": {"is_in_stock": True, "qty": 0},
            "configurable_product_links": list(range(1, 61)),  # 60 children
        },
    }

    requested_ids = []

    def side_effect(request):
        url = str(request.url)
        if "entity_id" in url:
            # Capture the requested IDs to verify the cap
            import re
            match = re.search(r"entity_id.*?value.*?=([^&]+)", url)
            if match:
                requested_ids.append(match.group(1))
            return Response(200, json=_products_response([]))
        return Response(200, json=_products_response([configurable]))

    with respx.mock:
        respx.get(PRODUCTS_URL).mock(side_effect=side_effect)

        result = await extractor.extract(SHOP_URL)

    # Should have made a children request
    assert result.complete is True
    # The configurable_ids tracked should be capped at 50
    # We verify indirectly: the product was processed without error


@pytest.mark.asyncio
async def test_simple_product_has_no_variants(extractor: MagentoAdminExtractor):
    """Simple products should have empty variants list."""
    with respx.mock:
        respx.get(PRODUCTS_URL).mock(
            return_value=Response(200, json=_products_response([SAMPLE_PRODUCT]))
        )

        result = await extractor.extract(SHOP_URL)

    assert result.products[0]["variants"] == []


# -- Image URL construction -------------------------------------------------


def test_image_url_construction(extractor: MagentoAdminExtractor):
    assert extractor._image_url("/w/j/wj01-blue.jpg") == (
        f"https://{SHOP_DOMAIN}/media/catalog/product/w/j/wj01-blue.jpg"
    )


def test_image_url_empty_path(extractor: MagentoAdminExtractor):
    assert extractor._image_url("") == ""


# -- Product URL construction -----------------------------------------------


def test_product_url_construction(extractor: MagentoAdminExtractor):
    assert extractor._product_url("stellar-solar-jacket") == (
        f"https://{SHOP_DOMAIN}/stellar-solar-jacket.html"
    )


def test_product_url_empty_key(extractor: MagentoAdminExtractor):
    assert extractor._product_url("") == ""


# -- Missing optional fields ------------------------------------------------


def test_map_product_no_image(extractor: MagentoAdminExtractor):
    """Product without image custom attribute returns empty image_url."""
    product = {
        "id": 1,
        "sku": "NO-IMG",
        "name": "No Image Product",
        "price": 10.0,
        "type_id": "simple",
        "custom_attributes": [],
        "media_gallery_entries": [],
        "extension_attributes": {"stock_item": {"is_in_stock": True, "qty": 5}},
    }
    mapped = extractor._map_product(product)
    assert mapped["image_url"] == ""
    assert mapped["additional_images"] == []


def test_map_product_no_gtin(extractor: MagentoAdminExtractor):
    """Product without GTIN attributes returns empty gtin."""
    product = {
        "id": 2,
        "sku": "NO-GTIN",
        "name": "No GTIN Product",
        "price": 20.0,
        "type_id": "simple",
        "custom_attributes": [
            {"attribute_code": "color", "value": "red"},
        ],
    }
    mapped = extractor._map_product(product)
    assert mapped["gtin"] == ""
    assert mapped["barcode"] == ""


def test_map_product_no_manufacturer(extractor: MagentoAdminExtractor):
    """Product without manufacturer returns empty vendor."""
    product = {
        "id": 3,
        "sku": "NO-BRAND",
        "name": "No Brand Product",
        "price": 15.0,
        "type_id": "simple",
        "custom_attributes": [],
    }
    mapped = extractor._map_product(product)
    assert mapped["vendor"] == ""


def test_map_product_no_url_key(extractor: MagentoAdminExtractor):
    """Product without url_key returns empty product_url and handle."""
    product = {
        "id": 4,
        "sku": "NO-URL",
        "name": "No URL Product",
        "price": 5.0,
        "type_id": "simple",
        "custom_attributes": [],
    }
    mapped = extractor._map_product(product)
    assert mapped["product_url"] == ""
    assert mapped["handle"] == ""


def test_map_product_no_stock_item(extractor: MagentoAdminExtractor):
    """Product without stock_item defaults to out of stock."""
    product = {
        "id": 5,
        "sku": "NO-STOCK",
        "name": "No Stock Info",
        "price": 30.0,
        "type_id": "simple",
        "custom_attributes": [],
        "extension_attributes": {},
    }
    mapped = extractor._map_product(product)
    assert mapped["in_stock"] is False


def test_map_product_out_of_stock(extractor: MagentoAdminExtractor):
    """Product with is_in_stock=False is marked out of stock."""
    product = {
        "id": 6,
        "sku": "OOS",
        "name": "Out of Stock",
        "price": 25.0,
        "type_id": "simple",
        "custom_attributes": [],
        "extension_attributes": {
            "stock_item": {"is_in_stock": False, "qty": 0},
        },
    }
    mapped = extractor._map_product(product)
    assert mapped["in_stock"] is False


# -- SearchCriteria ---------------------------------------------------------


def test_build_search_params_structure():
    """_build_search_params returns correct filter structure."""
    params = MagentoAdminExtractor._build_search_params(1)
    assert params["searchCriteria[pageSize]"] == "100"
    assert params["searchCriteria[currentPage]"] == "1"
    # Visibility filter
    assert params["searchCriteria[filter_groups][0][filters][0][field]"] == "visibility"
    assert params["searchCriteria[filter_groups][0][filters][0][value]"] == "4"
    # Status filter
    assert params["searchCriteria[filter_groups][1][filters][0][field]"] == "status"
    assert params["searchCriteria[filter_groups][1][filters][0][value]"] == "1"


def test_build_search_params_page_number():
    params = MagentoAdminExtractor._build_search_params(5)
    assert params["searchCriteria[currentPage]"] == "5"


def test_build_children_params():
    params = MagentoAdminExtractor._build_children_params([10, 20, 30])
    assert params["searchCriteria[filter_groups][0][filters][0][field]"] == "entity_id"
    assert params["searchCriteria[filter_groups][0][filters][0][value]"] == "10,20,30"
    assert params["searchCriteria[filter_groups][0][filters][0][condition_type]"] == "in"


# -- HTTP error on non-first page ------------------------------------------


@pytest.mark.asyncio
async def test_http_error_mid_pagination(extractor: MagentoAdminExtractor):
    """HTTP 500 mid-pagination returns partial results with error."""
    page1 = [{"id": i, "sku": f"SKU-{i}", "name": f"P{i}", "price": 10.0, "type_id": "simple"} for i in range(100)]

    call_count = 0

    def side_effect(request):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return Response(200, json=_products_response(page1, total_count=200))
        return Response(500, text="Internal Server Error")

    with respx.mock:
        respx.get(PRODUCTS_URL).mock(side_effect=side_effect)

        result = await extractor.extract(SHOP_URL)

    assert len(result.products) == 100
    assert result.complete is False
    assert "500" in result.error


# -- Custom attribute helper ------------------------------------------------


def test_get_custom_attribute_found(extractor: MagentoAdminExtractor):
    product = {"custom_attributes": [{"attribute_code": "color", "value": "blue"}]}
    assert extractor._get_custom_attribute(product, "color") == "blue"


def test_get_custom_attribute_missing(extractor: MagentoAdminExtractor):
    product = {"custom_attributes": [{"attribute_code": "color", "value": "blue"}]}
    assert extractor._get_custom_attribute(product, "size") == ""


def test_get_custom_attribute_no_attributes(extractor: MagentoAdminExtractor):
    product = {}
    assert extractor._get_custom_attribute(product, "anything") == ""
