"""Unit tests for ShopwareAdminExtractor."""

from __future__ import annotations

import time

import pytest
import respx
from httpx import Response

from app.db.oauth_store import OAuthConnection
from app.extractors.shopware_admin_extractor import ShopwareAdminExtractor

SHOP_DOMAIN = "test-store.example.com"
SHOP_URL = f"https://{SHOP_DOMAIN}"
TOKEN_URL = f"{SHOP_URL}/api/oauth/token"
SEARCH_URL = f"{SHOP_URL}/api/search/product"

TOKEN_RESPONSE = {
    "token_type": "Bearer",
    "expires_in": 600,
    "access_token": "bearer-token-abc",
}


def _make_connection(
    access_token: str = "test-client-id",
    refresh_token: str = "test-client-secret",
    shop_domain: str = SHOP_DOMAIN,
) -> OAuthConnection:
    return OAuthConnection(
        id=1,
        platform="shopware",
        shop_domain=shop_domain,
        access_token=access_token,
        refresh_token=refresh_token,
        scopes="admin",
    )


@pytest.fixture
def connection() -> OAuthConnection:
    return _make_connection()


@pytest.fixture
def extractor(connection: OAuthConnection) -> ShopwareAdminExtractor:
    return ShopwareAdminExtractor(connection)


def _search_response(
    products: list[dict],
    total: int | None = None,
) -> dict:
    """Build a Shopware search API response envelope."""
    return {
        "total": total if total is not None else len(products),
        "data": products,
    }


SAMPLE_PRODUCT = {
    "id": "abc123",
    "name": "Test Sneaker",
    "description": "<p>A great shoe</p>",
    "productNumber": "SNKR-001",
    "manufacturerNumber": "MPN-SNKR",
    "ean": "4006381333931",
    "price": [{"gross": 79.99, "net": 67.22, "listPrice": {"gross": 99.99, "net": 84.02}}],
    "stock": 15,
    "active": True,
    "weight": 0.8,
    "cover": {
        "media": {"url": "https://cdn.example.com/cover.jpg"}
    },
    "media": [
        {"media": {"url": "https://cdn.example.com/cover.jpg"}},
        {"media": {"url": "https://cdn.example.com/side.jpg"}},
    ],
    "manufacturer": {"name": "SneakerBrand"},
    "categories": [
        {"name": "Footwear"},
        {"name": "Sports"},
    ],
    "children": [
        {
            "id": "child-1",
            "name": "Test Sneaker Blue",
            "productNumber": "SNKR-001-BLU",
            "ean": "4006381333948",
            "price": [{"gross": 79.99, "net": 67.22}],
            "stock": 8,
        }
    ],
}


# ── Constructor ──────────────────────────────────────────────────────────────


def test_requires_access_token():
    conn = OAuthConnection(
        id=1,
        platform="shopware",
        shop_domain=SHOP_DOMAIN,
        refresh_token="secret",
    )
    with pytest.raises(ValueError, match="access_token"):
        ShopwareAdminExtractor(conn)


def test_requires_refresh_token():
    conn = OAuthConnection(
        id=1,
        platform="shopware",
        shop_domain=SHOP_DOMAIN,
        access_token="client-id",
    )
    with pytest.raises(ValueError, match="refresh_token"):
        ShopwareAdminExtractor(conn)


# ── Token acquisition ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_ensure_token_acquires_bearer_token(extractor: ShopwareAdminExtractor):
    """_ensure_token() POSTs client credentials and stores token with expiry."""
    with respx.mock:
        token_route = respx.post(TOKEN_URL).mock(
            return_value=Response(200, json=TOKEN_RESPONSE)
        )
        respx.post(SEARCH_URL).mock(
            return_value=Response(200, json=_search_response([]))
        )

        result = await extractor.extract(SHOP_URL)

    assert token_route.called
    # Token should be set after extraction
    assert extractor._bearer_token == "bearer-token-abc"
    assert extractor._token_expires_at > time.monotonic()
    assert result.complete is True


@pytest.mark.asyncio
async def test_ensure_token_sets_expiry_from_expires_in(extractor: ShopwareAdminExtractor):
    """Token expiry is set to monotonic now + expires_in from the response."""
    with respx.mock:
        respx.post(TOKEN_URL).mock(
            return_value=Response(200, json={**TOKEN_RESPONSE, "expires_in": 300})
        )
        respx.post(SEARCH_URL).mock(
            return_value=Response(200, json=_search_response([]))
        )

        before = time.monotonic()
        await extractor.extract(SHOP_URL)
        after = time.monotonic()

    # Expiry should be roughly now + 300s (within a 5s window for test execution)
    assert before + 295 < extractor._token_expires_at < after + 305


@pytest.mark.asyncio
async def test_token_cached_across_pages(extractor: ShopwareAdminExtractor):
    """Token endpoint is called only once when token is still valid."""
    page1_products = [{"id": f"p{i}", "name": f"P{i}", "active": True, "stock": 1} for i in range(100)]
    page2_products = [{"id": "p100", "name": "P100", "active": True, "stock": 1}]

    with respx.mock:
        token_route = respx.post(TOKEN_URL).mock(
            return_value=Response(200, json=TOKEN_RESPONSE)
        )
        respx.post(SEARCH_URL).mock(
            side_effect=[
                Response(200, json=_search_response(page1_products, total=101)),
                Response(200, json=_search_response(page2_products, total=101)),
            ]
        )

        await extractor.extract(SHOP_URL)

    # Token fetched once at start plus once per page inside the loop = 3 calls total
    # (initial + page1 ensure_token + page2 ensure_token). Because the token is valid,
    # _ensure_token returns immediately after the first fetch — only 1 POST to token URL.
    assert token_route.call_count == 1


# ── Token refresh ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_expired_token_is_refreshed(extractor: ShopwareAdminExtractor):
    """If token is set but expired, _ensure_token fetches a new one."""
    # Pre-set an already-expired token
    extractor._bearer_token = "old-token"
    extractor._token_expires_at = time.monotonic() - 1  # expired

    with respx.mock:
        token_route = respx.post(TOKEN_URL).mock(
            return_value=Response(200, json=TOKEN_RESPONSE)
        )
        respx.post(SEARCH_URL).mock(
            return_value=Response(200, json=_search_response([]))
        )

        await extractor.extract(SHOP_URL)

    assert token_route.called
    assert extractor._bearer_token == "bearer-token-abc"


@pytest.mark.asyncio
async def test_token_within_buffer_is_refreshed(extractor: ShopwareAdminExtractor):
    """Token within the 30s buffer window is proactively refreshed."""
    # Set token to expire in 20s (inside the 30s _TOKEN_BUFFER)
    extractor._bearer_token = "near-expiry-token"
    extractor._token_expires_at = time.monotonic() + 20

    with respx.mock:
        token_route = respx.post(TOKEN_URL).mock(
            return_value=Response(200, json=TOKEN_RESPONSE)
        )
        respx.post(SEARCH_URL).mock(
            return_value=Response(200, json=_search_response([]))
        )

        await extractor.extract(SHOP_URL)

    # Token refreshed because now < expires_at - 30 is False
    assert token_route.called
    assert extractor._bearer_token == "bearer-token-abc"


# ── Product extraction ───────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_product_field_mapping(extractor: ShopwareAdminExtractor):
    """extract() returns correctly mapped products from Shopware API data."""
    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=Response(200, json=TOKEN_RESPONSE))
        respx.post(SEARCH_URL).mock(
            return_value=Response(200, json=_search_response([SAMPLE_PRODUCT]))
        )

        result = await extractor.extract(SHOP_URL)

    assert result.complete is True
    assert result.error is None
    assert len(result.products) == 1

    p = result.products[0]
    assert p["id"] == "abc123"
    assert p["title"] == "Test Sneaker"
    assert p["description"] == "<p>A great shoe</p>"
    assert p["handle"] == "SNKR-001"
    assert p["sku"] == "SNKR-001"
    assert p["gtin"] == "4006381333931"
    assert p["barcode"] == "4006381333931"
    assert p["mpn"] == "MPN-SNKR"
    assert p["price"] == "79.99"
    assert p["compare_at_price"] == "99.99"
    assert p["currency"] == "EUR"
    assert p["vendor"] == "SneakerBrand"
    assert p["in_stock"] is True
    assert p["image_url"] == "https://cdn.example.com/cover.jpg"
    assert p["additional_images"] == ["https://cdn.example.com/side.jpg"]
    assert p["product_url"] == f"https://{SHOP_DOMAIN}/detail/abc123"
    assert p["tags"] == ["Footwear", "Sports"]
    assert p["weight"] == 0.8
    assert p["condition"] == "New"
    assert p["_source"] == "shopware_admin_api"
    assert p["_platform"] == "shopware"


@pytest.mark.asyncio
async def test_variant_children_mapped(extractor: ShopwareAdminExtractor):
    """Children (variants) are mapped with price, sku, ean, and stock."""
    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=Response(200, json=TOKEN_RESPONSE))
        respx.post(SEARCH_URL).mock(
            return_value=Response(200, json=_search_response([SAMPLE_PRODUCT]))
        )

        result = await extractor.extract(SHOP_URL)

    variants = result.products[0]["variants"]
    assert len(variants) == 1
    v = variants[0]
    assert v["variant_id"] == "child-1"
    assert v["title"] == "Test Sneaker Blue"
    assert v["sku"] == "SNKR-001-BLU"
    assert v["gtin"] == "4006381333948"
    assert v["barcode"] == "4006381333948"
    assert v["price"] == "79.99"
    assert v["in_stock"] is True


# ── Pagination ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_pagination_fetches_second_page(extractor: ShopwareAdminExtractor):
    """When total=150 and limit=100, a second page request is made."""
    page1 = [{"id": f"p{i}", "name": f"P{i}", "active": True, "stock": 1} for i in range(100)]
    page2 = [{"id": f"p{i}", "name": f"P{i}", "active": True, "stock": 1} for i in range(100, 150)]

    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=Response(200, json=TOKEN_RESPONSE))
        search_route = respx.post(SEARCH_URL).mock(
            side_effect=[
                Response(200, json=_search_response(page1, total=150)),
                Response(200, json=_search_response(page2, total=150)),
            ]
        )

        result = await extractor.extract(SHOP_URL)

    assert search_route.call_count == 2
    assert len(result.products) == 150
    assert result.complete is True
    assert result.pages_completed == 2
    assert result.pages_expected == 2


@pytest.mark.asyncio
async def test_pagination_stops_when_all_retrieved(extractor: ShopwareAdminExtractor):
    """No third request is made when cumulative count reaches total."""
    page1 = [{"id": f"p{i}", "name": f"P{i}", "active": True, "stock": 1} for i in range(100)]
    page2 = [{"id": f"p{i}", "name": f"P{i}", "active": True, "stock": 1} for i in range(100, 120)]

    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=Response(200, json=TOKEN_RESPONSE))
        search_route = respx.post(SEARCH_URL).mock(
            side_effect=[
                Response(200, json=_search_response(page1, total=120)),
                Response(200, json=_search_response(page2, total=120)),
            ]
        )

        result = await extractor.extract(SHOP_URL)

    assert search_route.call_count == 2
    assert len(result.products) == 120


# ── 401 retry ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_401_triggers_token_refresh_and_retry(extractor: ShopwareAdminExtractor):
    """First search call returning 401 causes a forced token refresh and successful retry."""
    with respx.mock:
        # Two token requests: initial + forced refresh after 401
        token_route = respx.post(TOKEN_URL).mock(
            side_effect=[
                Response(200, json=TOKEN_RESPONSE),
                Response(200, json={**TOKEN_RESPONSE, "access_token": "refreshed-token"}),
            ]
        )
        respx.post(SEARCH_URL).mock(
            side_effect=[
                Response(401, json={"errors": [{"status": 401}]}),
                Response(200, json=_search_response([SAMPLE_PRODUCT])),
            ]
        )

        result = await extractor.extract(SHOP_URL)

    assert token_route.call_count == 2
    assert len(result.products) == 1
    assert result.complete is True
    assert result.error is None


@pytest.mark.asyncio
async def test_persistent_401_returns_error(extractor: ShopwareAdminExtractor):
    """If 401 persists after token refresh, extraction returns an error result."""
    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=Response(200, json=TOKEN_RESPONSE))
        respx.post(SEARCH_URL).mock(return_value=Response(401, json={"errors": []}))

        result = await extractor.extract(SHOP_URL)

    assert result.products == []
    assert result.complete is False
    assert "credentials invalid" in result.error


# ── 429 rate limiting ────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_429_with_retry_after_waits_and_retries(
    extractor: ShopwareAdminExtractor, monkeypatch
):
    """429 response with Retry-After causes a sleep then a successful retry."""
    sleep_calls: list[float] = []

    async def mock_sleep(delay: float) -> None:
        sleep_calls.append(delay)

    monkeypatch.setattr("app.extractors.shopware_admin_extractor.asyncio.sleep", mock_sleep)

    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=Response(200, json=TOKEN_RESPONSE))
        respx.post(SEARCH_URL).mock(
            side_effect=[
                Response(429, headers={"Retry-After": "3"}, text="Too Many Requests"),
                Response(200, json=_search_response([SAMPLE_PRODUCT])),
            ]
        )

        result = await extractor.extract(SHOP_URL)

    assert sleep_calls == [3.0]
    assert len(result.products) == 1
    assert result.complete is True


@pytest.mark.asyncio
async def test_429_default_retry_after_when_header_missing(
    extractor: ShopwareAdminExtractor, monkeypatch
):
    """When Retry-After header is absent, defaults to 5 seconds."""
    sleep_calls: list[float] = []

    async def mock_sleep(delay: float) -> None:  # must be async — asyncio.sleep is a coroutine
        sleep_calls.append(delay)

    monkeypatch.setattr("app.extractors.shopware_admin_extractor.asyncio.sleep", mock_sleep)

    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=Response(200, json=TOKEN_RESPONSE))
        respx.post(SEARCH_URL).mock(
            side_effect=[
                Response(429, text="Too Many Requests"),  # No Retry-After header
                Response(200, json=_search_response([])),
            ]
        )

        await extractor.extract(SHOP_URL)

    assert sleep_calls == [5.0]


@pytest.mark.asyncio
async def test_persistent_429_returns_error(extractor: ShopwareAdminExtractor, monkeypatch):
    """Persistent 429 after retry marks extraction incomplete with error."""
    async def _noop_sleep(_: float) -> None:
        pass

    monkeypatch.setattr("app.extractors.shopware_admin_extractor.asyncio.sleep", _noop_sleep)

    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=Response(200, json=TOKEN_RESPONSE))
        respx.post(SEARCH_URL).mock(
            return_value=Response(429, headers={"Retry-After": "1"}, text="Rate limited")
        )

        result = await extractor.extract(SHOP_URL)

    assert result.complete is False
    assert "Rate limited" in result.error


# ── Empty catalog ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_empty_catalog(extractor: ShopwareAdminExtractor):
    """Store with no products returns empty list with complete=True."""
    with respx.mock:
        respx.post(TOKEN_URL).mock(return_value=Response(200, json=TOKEN_RESPONSE))
        respx.post(SEARCH_URL).mock(
            return_value=Response(200, json=_search_response([], total=0))
        )

        result = await extractor.extract(SHOP_URL)

    assert result.products == []
    assert result.complete is True
    assert result.error is None
    assert result.pages_completed == 0


# ── Token endpoint failure ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_token_endpoint_failure_returns_error(extractor: ShopwareAdminExtractor):
    """Non-200 from token endpoint surfaces as a failed ExtractorResult."""
    with respx.mock:
        respx.post(TOKEN_URL).mock(
            return_value=Response(401, text='{"error":"invalid_client"}')
        )

        result = await extractor.extract(SHOP_URL)

    assert result.products == []
    assert result.complete is False
    assert "401" in result.error


# ── Field mapping: missing optional fields ───────────────────────────────────


def test_map_product_no_cover(extractor: ShopwareAdminExtractor):
    """Product with no cover association returns empty image_url."""
    product = {
        "id": "no-cover",
        "name": "Bare Product",
        "active": True,
        "stock": 5,
        # no 'cover' key
    }
    mapped = extractor._map_product(product, SHOP_URL)
    assert mapped["image_url"] == ""
    assert mapped["additional_images"] == []


def test_map_product_no_manufacturer(extractor: ShopwareAdminExtractor):
    """Product without manufacturer returns empty vendor string."""
    product = {
        "id": "no-vendor",
        "name": "No Brand Product",
        "active": True,
        "stock": 2,
        # no 'manufacturer' key
    }
    mapped = extractor._map_product(product, SHOP_URL)
    assert mapped["vendor"] == ""


def test_map_product_no_categories(extractor: ShopwareAdminExtractor):
    """Product without categories returns empty tags list."""
    product = {
        "id": "no-cats",
        "name": "Uncategorised",
        "active": True,
        "stock": 1,
        # no 'categories' key
    }
    mapped = extractor._map_product(product, SHOP_URL)
    assert mapped["tags"] == []


def test_map_product_no_price(extractor: ShopwareAdminExtractor):
    """Product with no price array returns empty price string."""
    product = {
        "id": "no-price",
        "name": "Free Item",
        "active": True,
        "stock": 1,
    }
    mapped = extractor._map_product(product, SHOP_URL)
    assert mapped["price"] == ""
    assert mapped["compare_at_price"] is None


def test_map_product_no_list_price(extractor: ShopwareAdminExtractor):
    """Product with price but no listPrice returns None for compare_at_price."""
    product = {
        "id": "no-list",
        "name": "Regular Priced",
        "active": True,
        "stock": 3,
        "price": [{"gross": 49.99, "net": 42.0}],
    }
    mapped = extractor._map_product(product, SHOP_URL)
    assert mapped["price"] == "49.99"
    assert mapped["compare_at_price"] is None


def test_map_product_out_of_stock(extractor: ShopwareAdminExtractor):
    """Product with stock=0 is marked out of stock."""
    product = {
        "id": "oos",
        "name": "Out of Stock Item",
        "active": True,
        "stock": 0,
    }
    mapped = extractor._map_product(product, SHOP_URL)
    assert mapped["in_stock"] is False


def test_map_product_inactive(extractor: ShopwareAdminExtractor):
    """Inactive product with stock is still marked out of stock."""
    product = {
        "id": "inactive",
        "name": "Inactive Item",
        "active": False,
        "stock": 10,
    }
    mapped = extractor._map_product(product, SHOP_URL)
    assert mapped["in_stock"] is False


def test_map_product_ean_propagated_to_gtin_and_barcode(extractor: ShopwareAdminExtractor):
    """EAN field is mapped to both gtin and barcode for downstream compatibility."""
    product = {
        "id": "with-ean",
        "name": "EAN Product",
        "active": True,
        "stock": 1,
        "ean": "5901234123457",
    }
    mapped = extractor._map_product(product, SHOP_URL)
    assert mapped["gtin"] == "5901234123457"
    assert mapped["barcode"] == "5901234123457"


def test_map_product_product_url_built_from_domain(extractor: ShopwareAdminExtractor):
    """Product URL is constructed from shop domain and product ID."""
    product = {"id": "abc-uuid", "name": "URL Test", "active": True, "stock": 1}
    mapped = extractor._map_product(product, SHOP_URL)
    assert mapped["product_url"] == f"https://{SHOP_DOMAIN}/detail/abc-uuid"


def test_map_variants_with_children(extractor: ShopwareAdminExtractor):
    """_map_variants correctly maps child product fields."""
    children = [
        {
            "id": "v1",
            "name": "Size S",
            "productNumber": "PROD-S",
            "ean": "1234567890123",
            "price": [{"gross": 29.99}],
            "stock": 5,
        },
        {
            "id": "v2",
            "productNumber": "PROD-M",
            # no name — should fall back to productNumber
            "price": [{"gross": 29.99}],
            "stock": 0,
        },
    ]
    variants = extractor._map_variants(children)
    assert len(variants) == 2

    assert variants[0]["variant_id"] == "v1"
    assert variants[0]["title"] == "Size S"
    assert variants[0]["sku"] == "PROD-S"
    assert variants[0]["gtin"] == "1234567890123"
    assert variants[0]["price"] == "29.99"
    assert variants[0]["in_stock"] is True

    assert variants[1]["variant_id"] == "v2"
    assert variants[1]["title"] == "PROD-M"  # fallback to productNumber
    assert variants[1]["in_stock"] is False


def test_map_variants_empty(extractor: ShopwareAdminExtractor):
    """_map_variants returns empty list when no children are present."""
    assert extractor._map_variants([]) == []


# ── Search body ──────────────────────────────────────────────────────────────


def test_build_search_body_structure():
    """_build_search_body returns the expected Criteria API structure."""
    body = ShopwareAdminExtractor._build_search_body(1)
    assert body["page"] == 1
    assert body["limit"] == 100
    assert body["total-count-mode"] == 1
    # Only active parent products
    filters = body["filter"]
    active_filter = next(f for f in filters if f["field"] == "active")
    parent_filter = next(f for f in filters if f["field"] == "parentId")
    assert active_filter["value"] is True
    assert parent_filter["value"] is None
    # Key associations requested
    assert "cover" in body["associations"]
    assert "manufacturer" in body["associations"]
    assert "categories" in body["associations"]
    assert "children" in body["associations"]


def test_build_search_body_page_number():
    """_build_search_body sets the correct page for each call."""
    assert ShopwareAdminExtractor._build_search_body(3)["page"] == 3
