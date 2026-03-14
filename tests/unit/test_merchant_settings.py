"""Unit tests for merchant settings API (Ticket 3) and export validation (Ticket 8)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from tests.conftest import MockRedis


def _make_settings_row(
    shop_id="https://example.com",
    delivery_time="1-3 working days",
    delivery_costs="4.95",
    payment_costs="0.00",
    brand_fallback="MyBrand",
    default_condition="NEW",
):
    return {
        "id": 1,
        "shop_id": shop_id,
        "delivery_time": delivery_time,
        "delivery_costs": delivery_costs,
        "payment_costs": payment_costs,
        "brand_fallback": brand_fallback,
        "default_condition": default_condition,
        "created_at": "2026-03-14T00:00:00+00:00",
        "updated_at": "2026-03-14T00:00:00+00:00",
    }


def _make_mock_db(fetchrow_return=None, fetch_return=None, fetchval_return=None):
    mock_conn = AsyncMock()
    mock_conn.fetchrow = AsyncMock(return_value=fetchrow_return)
    mock_conn.fetch = AsyncMock(return_value=fetch_return or [])
    mock_conn.fetchval = AsyncMock(return_value=fetchval_return)

    mock_pool = MagicMock()
    mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
    mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

    mock_db = MagicMock()
    mock_db.pool = mock_pool
    return mock_db


class TestGetMerchantSettings:
    """Test GET /api/v1/merchants/settings endpoint."""

    def test_get_settings_found(self, api_client: TestClient, headers: dict):
        """Returns stored settings when they exist."""
        mock_db = _make_mock_db(fetchrow_return=_make_settings_row())
        api_client.app.state.db = mock_db

        response = api_client.get(
            "/api/v1/merchants/settings?shop_id=https://example.com",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["settings"] is not None
        assert data["settings"]["delivery_time"] == "1-3 working days"
        assert data["settings"]["delivery_costs"] == "4.95"

    def test_get_settings_not_found(self, api_client: TestClient, headers: dict):
        """Returns null settings when none exist."""
        mock_db = _make_mock_db(fetchrow_return=None)
        api_client.app.state.db = mock_db

        response = api_client.get(
            "/api/v1/merchants/settings?shop_id=https://example.com",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["settings"] is None

    def test_get_settings_no_db(self, api_client: TestClient, headers: dict):
        """Returns null settings when DB unavailable."""
        api_client.app.state.db = None

        response = api_client.get(
            "/api/v1/merchants/settings?shop_id=https://example.com",
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["settings"] is None

    def test_get_settings_no_auth(self, api_client: TestClient):
        """Returns error without API key."""
        response = api_client.get(
            "/api/v1/merchants/settings?shop_id=https://example.com",
        )
        assert response.status_code in (401, 422)


class TestPutMerchantSettings:
    """Test PUT /api/v1/merchants/settings endpoint."""

    def test_put_settings_creates_new(self, api_client: TestClient, headers: dict):
        """Creates settings when none exist."""
        mock_db = _make_mock_db(fetchrow_return=_make_settings_row())
        api_client.app.state.db = mock_db

        response = api_client.put(
            "/api/v1/merchants/settings?shop_id=https://example.com",
            json={
                "delivery_time": "1-3 working days",
                "delivery_costs": "4.95",
                "payment_costs": "0.00",
                "brand_fallback": "MyBrand",
                "default_condition": "NEW",
            },
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["settings"]["delivery_time"] == "1-3 working days"

    def test_put_settings_no_db_returns_503(self, api_client: TestClient, headers: dict):
        """Returns 503 when DB unavailable."""
        api_client.app.state.db = None

        response = api_client.put(
            "/api/v1/merchants/settings?shop_id=https://example.com",
            json={"delivery_time": "1-3 working days"},
            headers=headers,
        )
        assert response.status_code == 503

    def test_put_settings_defaults(self, api_client: TestClient, headers: dict):
        """Empty body uses defaults."""
        mock_db = _make_mock_db(fetchrow_return=_make_settings_row(
            delivery_time="", delivery_costs="", payment_costs="",
        ))
        api_client.app.state.db = mock_db

        response = api_client.put(
            "/api/v1/merchants/settings?shop_id=https://example.com",
            json={},
            headers=headers,
        )
        assert response.status_code == 200


# --- Ticket 8: Export Validation Gate ---


def _make_product_row_for_export(
    product_id=1, sku="SKU-1", vendor="Brand", gtin="4006381333931",
):
    return {
        "id": product_id,
        "external_id": "EXT-1",
        "shop_id": "https://example.com",
        "platform": "shopify",
        "title": "Test Product",
        "description": "A product",
        "price": Decimal("29.99"),
        "compare_at_price": None,
        "currency": "EUR",
        "image_url": "https://img.jpg",
        "product_url": "https://example.com/p",
        "sku": sku,
        "gtin": gtin,
        "mpn": None,
        "vendor": vendor,
        "product_type": None,
        "in_stock": True,
        "condition": "NEW",
        "variants": "[]",
        "tags": "[]",
        "additional_images": "[]",
        "category_path": "[]",
        "raw_data": "{}",
        "scraped_at": "2026-03-14T00:00:00+00:00",
        "idempotency_key": "abc",
        "created_at": "2026-03-14T00:00:00+00:00",
        "updated_at": "2026-03-14T00:00:00+00:00",
        "retention_expires_at": None,
    }


class TestExportValidation:
    """Test GET /api/v1/exports/idealo/validate endpoint."""

    def test_validate_ready(self, api_client: TestClient, headers: dict):
        """Validation returns ready when settings + products are complete."""
        settings_row = _make_settings_row()
        product_rows = [_make_product_row_for_export()]

        # Need two fetchrow calls (one for settings, one for products)
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=settings_row)
        mock_conn.fetch = AsyncMock(return_value=product_rows)

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.pool = mock_pool
        api_client.app.state.db = mock_db

        response = api_client.get(
            "/api/v1/exports/idealo/validate?shop_id=https://example.com",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True
        assert data["issue_count"] == 0

    def test_validate_missing_settings(self, api_client: TestClient, headers: dict):
        """Validation fails when merchant settings not configured."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)
        mock_conn.fetch = AsyncMock(return_value=[_make_product_row_for_export()])

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.pool = mock_pool
        api_client.app.state.db = mock_db

        response = api_client.get(
            "/api/v1/exports/idealo/validate?shop_id=https://example.com",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is False
        assert data["issue_count"] > 0

    def test_validate_no_products(self, api_client: TestClient, headers: dict):
        """Validation fails when no products found."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=_make_settings_row())
        mock_conn.fetch = AsyncMock(return_value=[])

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.pool = mock_pool
        api_client.app.state.db = mock_db

        response = api_client.get(
            "/api/v1/exports/idealo/validate?shop_id=https://example.com",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is False
        assert any("No products" in i for i in data["issues"])

    def test_validate_missing_brands_as_warning(self, api_client: TestClient, headers: dict):
        """Products missing brand show as warnings, not blockers."""
        settings_row = _make_settings_row()
        product_rows = [_make_product_row_for_export(vendor=None)]

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=settings_row)
        mock_conn.fetch = AsyncMock(return_value=product_rows)

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.pool = mock_pool
        api_client.app.state.db = mock_db

        response = api_client.get(
            "/api/v1/exports/idealo/validate?shop_id=https://example.com",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["ready"] is True  # brand is a warning, not a blocker
        assert data["warning_count"] > 0


class TestExportWithStoredSettings:
    """Test that CSV export uses stored merchant settings."""

    def test_export_uses_stored_settings(self, api_client: TestClient, headers: dict):
        """Export reads delivery/costs from merchant_settings table."""
        settings_row = _make_settings_row(
            delivery_time="2-5 days",
            delivery_costs="5.99",
            payment_costs="0.50",
        )
        product_rows = [_make_product_row_for_export()]

        # fetchrow returns settings first, then used by _fetch_all_products via fetch
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=settings_row)
        mock_conn.fetch = AsyncMock(return_value=product_rows)

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.pool = mock_pool
        api_client.app.state.db = mock_db

        response = api_client.get(
            "/api/v1/exports/idealo/csv?shop_id=https://example.com",
            headers=headers,
        )
        assert response.status_code == 200
        assert "text/csv" in response.headers["content-type"]
        csv_text = response.text
        # Should contain our stored delivery time
        assert "2-5 days" in csv_text
        assert "5.99" in csv_text

    def test_export_query_params_override_stored(self, api_client: TestClient, headers: dict):
        """Query params override stored settings."""
        settings_row = _make_settings_row(delivery_time="2-5 days")
        product_rows = [_make_product_row_for_export()]

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=settings_row)
        mock_conn.fetch = AsyncMock(return_value=product_rows)

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.pool = mock_pool
        api_client.app.state.db = mock_db

        response = api_client.get(
            "/api/v1/exports/idealo/csv?shop_id=https://example.com&delivery_time=OVERRIDE",
            headers=headers,
        )
        assert response.status_code == 200
        assert "OVERRIDE" in response.text
        # Should NOT contain stored value
        assert "2-5 days" not in response.text
