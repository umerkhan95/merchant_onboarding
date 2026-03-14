"""Unit tests for product update API (Ticket 1), bulk update (Ticket 2),
completeness API (Ticket 4), and default condition (Ticket 9)."""

from __future__ import annotations

import io
import json
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.models.enums import Platform
from app.models.product import MerchantSettings, ProductUpdate
from app.services.product_normalizer import ProductNormalizer
from tests.conftest import MockRedis


# --- Ticket 9: Default Condition to NEW ---


class TestDefaultConditionNEW:
    """Test that normalizer defaults condition to NEW when not extracted."""

    @pytest.fixture
    def normalizer(self):
        return ProductNormalizer()

    def test_shopify_defaults_condition_to_new(self, normalizer):
        """Shopify normalizer sets condition=None, but post-normalization defaults to NEW."""
        raw = {
            "id": 123,
            "title": "Test Product",
            "body_html": "",
            "handle": "test",
            "vendor": "Brand",
            "product_type": "Shoes",
            "tags": "",
            "variants": [{"id": 1, "price": "29.99", "sku": "SKU1", "inventory_quantity": 5}],
            "images": [{"src": "https://example.com/img.jpg"}],
        }
        product = normalizer.normalize(raw, "shop1", Platform.SHOPIFY, "https://example.com")
        assert product is not None
        assert product.condition == "NEW"

    def test_woocommerce_defaults_condition_to_new(self, normalizer):
        raw = {
            "id": 456,
            "name": "WC Product",
            "prices": {"price": "1999", "regular_price": "1999", "currency_minor_unit": 2, "currency_code": "EUR"},
            "images": [{"src": "https://example.com/img.jpg"}],
            "permalink": "https://example.com/product/wc",
        }
        product = normalizer.normalize(raw, "shop1", Platform.WOOCOMMERCE, "https://example.com")
        assert product is not None
        assert product.condition == "NEW"

    def test_schema_org_preserves_existing_condition(self, normalizer):
        """When Schema.org provides a condition, it should NOT be overridden."""
        raw = {
            "name": "Used Gadget",
            "offers": {"price": "49.99", "priceCurrency": "USD", "itemCondition": "UsedCondition"},
            "image": "https://example.com/used.jpg",
            "sku": "USED-1",
        }
        product = normalizer.normalize(raw, "shop1", Platform.GENERIC, "https://example.com")
        assert product is not None
        assert product.condition == "USED"

    def test_google_feed_preserves_condition(self, normalizer):
        """Google feed condition should not be overridden."""
        raw = {
            "_source": "google_feed",
            "id": "GF-1",
            "title": "Refurb Phone",
            "price": "199.00",
            "image_link": "https://example.com/phone.jpg",
            "condition": "refurbished",
            "link": "https://example.com/phone",
        }
        product = normalizer.normalize(raw, "shop1", Platform.GENERIC, "https://example.com")
        assert product is not None
        assert product.condition == "REFURBISHED"

    def test_magento_defaults_condition_to_new(self, normalizer):
        raw = {
            "name": "Magento Product",
            "price": 79.99,
            "sku": "MAG-1",
            "custom_attributes": [
                {"attribute_code": "image", "value": "/img.jpg"},
            ],
        }
        product = normalizer.normalize(raw, "shop1", Platform.MAGENTO, "https://example.com")
        assert product is not None
        assert product.condition == "NEW"

    def test_css_generic_defaults_condition_to_new(self, normalizer):
        raw = {
            "title": "Generic Product",
            "price": "15.00",
            "image": "https://example.com/generic.jpg",
            "sku": "GEN-1",
        }
        product = normalizer.normalize(raw, "shop1", Platform.GENERIC, "https://example.com")
        assert product is not None
        assert product.condition == "NEW"


# --- Ticket 1: ProductUpdate Model ---


class TestProductUpdateModel:
    """Test ProductUpdate Pydantic model validation."""

    def test_valid_update_gtin(self):
        update = ProductUpdate(gtin="4006381333931")
        assert update.gtin == "4006381333931"

    def test_valid_update_condition_new(self):
        update = ProductUpdate(condition="new")
        assert update.condition == "NEW"

    def test_valid_update_condition_refurbished(self):
        update = ProductUpdate(condition="REFURBISHED")
        assert update.condition == "REFURBISHED"

    def test_valid_update_condition_used(self):
        update = ProductUpdate(condition="used")
        assert update.condition == "USED"

    def test_invalid_condition_raises(self):
        with pytest.raises(ValueError, match="condition must be one of"):
            ProductUpdate(condition="broken")

    def test_partial_update_only_brand(self):
        update = ProductUpdate(brand="Acme Corp")
        data = update.model_dump(exclude_none=True)
        assert data == {"brand": "Acme Corp"}
        assert "gtin" not in data

    def test_empty_update_dumps_empty(self):
        update = ProductUpdate()
        data = update.model_dump(exclude_none=True)
        assert data == {}

    def test_category_path_list(self):
        update = ProductUpdate(category_path=["Electronics", "Phones"])
        assert update.category_path == ["Electronics", "Phones"]


# --- Ticket 3: MerchantSettings Model ---


class TestMerchantSettingsModel:
    """Test MerchantSettings model."""

    def test_defaults(self):
        ms = MerchantSettings(shop_id="https://example.com")
        assert ms.delivery_time == ""
        assert ms.delivery_costs == ""
        assert ms.payment_costs == ""
        assert ms.brand_fallback == ""
        assert ms.default_condition == "NEW"

    def test_full_settings(self):
        ms = MerchantSettings(
            shop_id="https://example.com",
            delivery_time="1-3 working days",
            delivery_costs="DHL:4.95;DPD:5.95",
            payment_costs="PayPal:0.35;Klarna:0.00",
            brand_fallback="MyBrand",
            default_condition="NEW",
        )
        assert ms.delivery_costs == "DHL:4.95;DPD:5.95"


# --- API Endpoint Tests (using TestClient + mocked DB) ---


class MockConnection:
    """Mock asyncpg connection for testing."""

    def __init__(self, data: dict | None = None, rows: list | None = None):
        self._data = data
        self._rows = rows or []

    async def fetchrow(self, query, *args):
        return self._data

    async def fetch(self, query, *args):
        if "UPDATE" in query:
            return self._rows
        return self._rows

    async def fetchval(self, query, *args):
        return len(self._rows) if self._rows else 0


class MockPool:
    """Mock asyncpg pool."""

    def __init__(self, conn: MockConnection):
        self._conn = conn

    def acquire(self):
        return MockPoolContext(self._conn)


class MockPoolContext:
    def __init__(self, conn):
        self._conn = conn

    async def __aenter__(self):
        return self._conn

    async def __aexit__(self, *args):
        pass


class MockDB:
    """Mock DatabaseClient."""

    def __init__(self, conn: MockConnection):
        self.pool = MockPool(conn)


def _make_product_row(
    product_id=1, title="Test Product", price=29.99, gtin=None, vendor=None,
    sku="SKU-1", external_id="EXT-1", condition="NEW", image_url="https://img.jpg",
    product_url="https://example.com/product", mpn=None, description="A product",
    category_path="[]", shop_id="https://example.com", platform="shopify",
):
    """Create a mock product row dict that looks like asyncpg Record."""
    return {
        "id": product_id,
        "external_id": external_id,
        "shop_id": shop_id,
        "platform": platform,
        "title": title,
        "description": description,
        "price": Decimal(str(price)),
        "compare_at_price": None,
        "currency": "EUR",
        "image_url": image_url,
        "product_url": product_url,
        "sku": sku,
        "gtin": gtin,
        "mpn": mpn,
        "vendor": vendor,
        "product_type": None,
        "in_stock": True,
        "condition": condition,
        "variants": "[]",
        "tags": "[]",
        "additional_images": "[]",
        "category_path": category_path,
        "raw_data": "{}",
        "scraped_at": "2026-03-14T00:00:00+00:00",
        "idempotency_key": "abc123",
        "created_at": "2026-03-14T00:00:00+00:00",
        "updated_at": "2026-03-14T00:00:00+00:00",
        "retention_expires_at": None,
    }


class TestPatchProductEndpoint:
    """Test PATCH /api/v1/products/{id} endpoint."""

    def test_patch_product_updates_gtin(self, api_client: TestClient, headers: dict):
        """PATCH with valid GTIN updates the product."""
        updated_row = _make_product_row(gtin="4006381333931")

        mock_conn = MockConnection(data=updated_row)
        mock_db = MockDB(mock_conn)

        with patch("app.api.v1.products.get_db", return_value=mock_db):
            api_client.app.state.db = mock_db
            response = api_client.patch(
                "/api/v1/products/1",
                json={"gtin": "4006381333931"},
                headers=headers,
            )

        assert response.status_code == 200
        assert response.json()["gtin"] == "4006381333931"

    def test_patch_product_invalid_gtin_returns_422(self, api_client: TestClient, headers: dict):
        """PATCH with invalid GTIN returns 422."""
        mock_db = MockDB(MockConnection(data=_make_product_row()))
        api_client.app.state.db = mock_db

        response = api_client.patch(
            "/api/v1/products/1",
            json={"gtin": "INVALID"},
            headers=headers,
        )
        assert response.status_code == 422

    def test_patch_product_invalid_condition_returns_422(self, api_client: TestClient, headers: dict):
        """PATCH with invalid condition returns 422."""
        response = api_client.patch(
            "/api/v1/products/1",
            json={"condition": "BROKEN"},
            headers=headers,
        )
        assert response.status_code == 422

    def test_patch_product_empty_body_returns_422(self, api_client: TestClient, headers: dict):
        """PATCH with no fields returns 422."""
        mock_db = MockDB(MockConnection(data=_make_product_row()))
        api_client.app.state.db = mock_db

        response = api_client.patch(
            "/api/v1/products/1",
            json={},
            headers=headers,
        )
        assert response.status_code == 422

    def test_patch_product_brand_maps_to_vendor(self, api_client: TestClient, headers: dict):
        """PATCH with brand field maps to vendor column."""
        updated_row = _make_product_row(vendor="New Brand")
        mock_db = MockDB(MockConnection(data=updated_row))
        api_client.app.state.db = mock_db

        response = api_client.patch(
            "/api/v1/products/1",
            json={"brand": "New Brand"},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["vendor"] == "New Brand"

    def test_patch_product_not_found_returns_404(self, api_client: TestClient, headers: dict):
        """PATCH on non-existent product returns 404."""
        mock_db = MockDB(MockConnection(data=None))
        api_client.app.state.db = mock_db

        response = api_client.patch(
            "/api/v1/products/99999",
            json={"brand": "Test"},
            headers=headers,
        )
        assert response.status_code == 404

    def test_patch_product_no_auth_returns_error(self, api_client: TestClient):
        """PATCH without API key returns auth or validation error."""
        response = api_client.patch(
            "/api/v1/products/1",
            json={"brand": "Test"},
        )
        assert response.status_code in (401, 422)

    def test_patch_product_condition_new(self, api_client: TestClient, headers: dict):
        """PATCH condition to NEW."""
        updated_row = _make_product_row(condition="NEW")
        mock_db = MockDB(MockConnection(data=updated_row))
        api_client.app.state.db = mock_db

        response = api_client.patch(
            "/api/v1/products/1",
            json={"condition": "NEW"},
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["condition"] == "NEW"

    def test_patch_product_category_path(self, api_client: TestClient, headers: dict):
        """PATCH category_path as list."""
        updated_row = _make_product_row(category_path='["Electronics", "Phones"]')
        mock_db = MockDB(MockConnection(data=updated_row))
        api_client.app.state.db = mock_db

        response = api_client.patch(
            "/api/v1/products/1",
            json={"category_path": ["Electronics", "Phones"]},
            headers=headers,
        )
        assert response.status_code == 200


# --- Ticket 4: Completeness Endpoint ---


class TestCompletenessEndpoint:
    """Test GET /api/v1/products/completeness endpoint."""

    def test_completeness_returns_scores(self, api_client: TestClient, headers: dict):
        """Completeness endpoint returns per-product scores and summary."""
        product_rows = [
            _make_product_row(product_id=1, gtin="4006381333931", vendor="Brand A"),
            _make_product_row(product_id=2, gtin=None, vendor=None, sku=None),
        ]
        stats_row = {
            "total": 2,
            "has_gtin": 1,
            "has_brand": 1,
            "has_mpn": 0,
            "has_condition": 2,
            "has_image": 2,
            "has_description": 2,
            "has_category": 0,
        }

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=product_rows)
        mock_conn.fetchrow = AsyncMock(return_value=stats_row)

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.pool = mock_pool
        api_client.app.state.db = mock_db

        response = api_client.get(
            "/api/v1/products/completeness?shop_id=https://example.com",
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert "products" in data
        assert "summary" in data
        assert len(data["products"]) == 2

        # First product has gtin+brand — should be more complete
        p1 = data["products"][0]
        assert p1["id"] == 1
        assert p1["score"] > 0

        # Second product is missing gtin+brand+sku
        p2 = data["products"][1]
        assert len(p2["missing_fields"]) > len(p1["missing_fields"])

    def test_completeness_no_db_returns_empty(self, api_client: TestClient, headers: dict):
        """Completeness endpoint without DB returns empty."""
        api_client.app.state.db = None
        response = api_client.get(
            "/api/v1/products/completeness?shop_id=https://example.com",
            headers=headers,
        )
        assert response.status_code == 200
        assert response.json()["products"] == []


# --- Ticket 2: Bulk Update Endpoint ---


class TestBulkUpdateEndpoint:
    """Test POST /api/v1/products/bulk-update endpoint."""

    def test_bulk_update_csv_valid(self, api_client: TestClient, headers: dict):
        """Bulk update with valid CSV updates products."""
        csv_content = "sku,gtin,brand\nSKU-1,4006381333931,NewBrand\n"

        # Mock DB to return matched rows
        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[{"id": 1}])

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.pool = mock_pool
        api_client.app.state.db = mock_db

        response = api_client.post(
            "/api/v1/products/bulk-update?shop_id=https://example.com",
            files={"file": ("products.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["matched"] >= 0
        assert "updated" in data
        assert "not_found" in data
        assert "invalid" in data

    def test_bulk_update_csv_no_header_returns_422(self, api_client: TestClient, headers: dict):
        """Bulk update with empty CSV returns 422."""
        mock_db = MagicMock()
        api_client.app.state.db = mock_db

        response = api_client.post(
            "/api/v1/products/bulk-update?shop_id=https://example.com",
            files={"file": ("empty.csv", io.BytesIO(b""), "text/csv")},
            headers=headers,
        )
        assert response.status_code == 422

    def test_bulk_update_csv_missing_match_column_returns_422(self, api_client: TestClient, headers: dict):
        """Bulk update CSV without sku/external_id column returns 422."""
        csv_content = "name,gtin\nProduct,4006381333931\n"
        mock_db = MagicMock()
        api_client.app.state.db = mock_db

        response = api_client.post(
            "/api/v1/products/bulk-update?shop_id=https://example.com",
            files={"file": ("bad.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            headers=headers,
        )
        assert response.status_code == 422

    def test_bulk_update_csv_invalid_gtin_counted(self, api_client: TestClient, headers: dict):
        """Rows with invalid GTINs are counted as invalid."""
        csv_content = "sku,gtin\nSKU-1,INVALID\nSKU-2,4006381333931\n"

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[{"id": 2}])

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.pool = mock_pool
        api_client.app.state.db = mock_db

        response = api_client.post(
            "/api/v1/products/bulk-update?shop_id=https://example.com",
            files={"file": ("mixed.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["invalid"] == 1

    def test_bulk_update_external_id_column(self, api_client: TestClient, headers: dict):
        """Bulk update using external_id as match column."""
        csv_content = "external_id,brand\nEXT-1,BrandX\n"

        mock_conn = AsyncMock()
        mock_conn.fetch = AsyncMock(return_value=[{"id": 1}])

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.pool = mock_pool
        api_client.app.state.db = mock_db

        response = api_client.post(
            "/api/v1/products/bulk-update?shop_id=https://example.com",
            files={"file": ("ext.csv", io.BytesIO(csv_content.encode()), "text/csv")},
            headers=headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["matched"] >= 0
