"""Tests for IdealoPWSClient."""

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.exporters.idealo_pws import IdealoPWSClient
from app.models.enums import Platform
from app.models.product import Product


def _make_product(**overrides) -> Product:
    defaults = {
        "external_id": "12345",
        "shop_id": "https://example.com",
        "platform": Platform.SHOPIFY,
        "title": "Test Product",
        "description": "A test product",
        "price": Decimal("29.99"),
        "currency": "EUR",
        "image_url": "https://example.com/img.jpg",
        "product_url": "https://example.com/products/test",
        "sku": "SKU-001",
        "in_stock": True,
    }
    defaults.update(overrides)
    return Product(**defaults)


class TestProductToOffer:
    def test_basic(self):
        client = IdealoPWSClient(
            client_id="test",
            client_secret="secret",
            shop_id="12345",
            delivery_time="1-3 days",
        )
        product = _make_product(gtin="4006381333931", vendor="Nike")
        offer = client._product_to_offer(product)

        assert offer["sku"] == "SKU-001"
        assert offer["title"] == "Test Product"
        assert offer["price"] == "29.99"
        assert offer["currency"] == "EUR"
        assert offer["brand"] == "Nike"
        assert offer["eans"] == ["4006381333931"]
        assert offer["delivery"] == "1-3 days"
        assert "https://example.com/img.jpg" in offer["imageUrls"]

    def test_with_additional_images(self):
        client = IdealoPWSClient(client_id="t", client_secret="s", shop_id="1")
        product = _make_product(
            additional_images=["https://example.com/img2.jpg"]
        )
        offer = client._product_to_offer(product)
        assert len(offer["imageUrls"]) == 2

    def test_with_category_path(self):
        client = IdealoPWSClient(client_id="t", client_secret="s", shop_id="1")
        product = _make_product(category_path=["Electronics", "Phones"])
        offer = client._product_to_offer(product)
        assert offer["categoryPath"] == ["Electronics", "Phones"]

    def test_uses_external_id_when_no_sku(self):
        client = IdealoPWSClient(client_id="t", client_secret="s", shop_id="1")
        product = _make_product(sku=None)
        offer = client._product_to_offer(product)
        assert offer["sku"] == "12345"

    def test_condition(self):
        client = IdealoPWSClient(client_id="t", client_secret="s", shop_id="1")
        product = _make_product(condition="refurbished")
        offer = client._product_to_offer(product)
        assert offer["condition"] == "REFURBISHED"

    def test_mpn(self):
        client = IdealoPWSClient(client_id="t", client_secret="s", shop_id="1")
        product = _make_product(mpn="MPN-456")
        offer = client._product_to_offer(product)
        assert offer["hans"] == ["MPN-456"]


class TestOfferUrl:
    def test_basic_url(self):
        client = IdealoPWSClient(client_id="t", client_secret="s", shop_id="12345")
        url = client._offer_url("SKU-001")
        assert url == "https://import.idealo.com/shop/12345/offer/SKU-001"

    def test_url_encodes_special_chars(self):
        client = IdealoPWSClient(client_id="t", client_secret="s", shop_id="shop/123")
        url = client._offer_url("sku with spaces")
        assert "shop%2F123" in url
        assert "sku%20with%20spaces" in url

    def test_url_encodes_path_traversal(self):
        client = IdealoPWSClient(client_id="t", client_secret="s", shop_id="12345")
        url = client._offer_url("../../../etc/passwd")
        assert "..%2F" in url


class TestPushOffers:
    @pytest.mark.asyncio
    async def test_push_skips_products_without_sku(self):
        client = IdealoPWSClient(client_id="t", client_secret="s", shop_id="1")
        product = _make_product(sku=None, external_id="")
        results = await client.push_offers([product])
        assert results["skipped"] == 1
        assert results["success"] == 0

    @pytest.mark.asyncio
    async def test_push_success(self):
        client = IdealoPWSClient(client_id="t", client_secret="s", shop_id="1")
        client._access_token = "test-token"
        client._token_expires_at = float("inf")

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()

        with patch.object(httpx.AsyncClient, "put", new_callable=AsyncMock, return_value=mock_response):
            product = _make_product()
            results = await client.push_offers([product])
            assert results["success"] == 1

    @pytest.mark.asyncio
    async def test_push_handles_http_error(self):
        client = IdealoPWSClient(client_id="t", client_secret="s", shop_id="1")
        client._access_token = "test-token"
        client._token_expires_at = float("inf")

        with patch.object(
            httpx.AsyncClient, "put",
            new_callable=AsyncMock,
            side_effect=httpx.HTTPError("connection failed"),
        ):
            product = _make_product()
            results = await client.push_offers([product])
            assert results["failed"] == 1
            assert results["success"] == 0


class TestEnsureToken:
    @pytest.mark.asyncio
    async def test_returns_cached_token(self):
        client = IdealoPWSClient(client_id="t", client_secret="s", shop_id="1")
        client._access_token = "cached-token"
        client._token_expires_at = float("inf")

        mock_client = AsyncMock()
        token = await client._ensure_token(mock_client)
        assert token == "cached-token"
        mock_client.post.assert_not_called()

    @pytest.mark.asyncio
    async def test_refreshes_expired_token(self):
        client = IdealoPWSClient(client_id="t", client_secret="s", shop_id="1")
        client._access_token = "old-token"
        client._token_expires_at = 0.0  # expired

        mock_response = MagicMock()
        mock_response.json.return_value = {"access_token": "new-token", "expires_in": 3600}
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response

        token = await client._ensure_token(mock_client)
        assert token == "new-token"
        assert client._access_token == "new-token"
        mock_client.post.assert_called_once()
