"""Tests for merchant profile and GDPR data erasure API endpoints."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from app.api.deps import limiter
from app.config import settings
from app.main import create_app
from tests.conftest import MockRedis


@pytest.fixture
def client():
    """Create a test client."""
    app = create_app()
    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def gdpr_mock_redis():
    """Create a mock Redis client with scan support for GDPR tests."""
    return MockRedis()


@pytest.fixture
def mock_db():
    """Create a mock DatabaseClient."""
    return MagicMock()


@pytest.fixture
def gdpr_client(gdpr_mock_redis, mock_db):
    """Create a test client with GDPR-capable mock Redis."""
    original_api_keys = settings.api_keys
    settings.api_keys = "test-api-key-12345"

    app = create_app()
    limiter.enabled = False
    app.state.redis = gdpr_mock_redis
    app.state.db = mock_db

    client = TestClient(app)
    yield client

    settings.api_keys = original_api_keys


@pytest.fixture
def gdpr_headers():
    """Return headers with valid API key for GDPR tests."""
    return {"X-API-Key": "test-api-key-12345"}


class TestGetMerchantProfile:
    """Tests for GET /api/v1/merchants/profile."""

    def test_profile_not_found_returns_404(self, gdpr_client, gdpr_headers):
        """Test 404 when profile doesn't exist."""
        with patch(
            "app.db.merchant_profile_ingestor.MerchantProfileIngestor.get",
            new_callable=AsyncMock,
            return_value=None,
        ):
            response = gdpr_client.get(
                "/api/v1/merchants/profile",
                params={"shop_id": "https://nonexistent.com"},
                headers=gdpr_headers,
            )
            assert response.status_code == 404

    def test_profile_found_returns_data(self, gdpr_client, gdpr_headers):
        """Test successful profile retrieval."""
        mock_profile = {
            "shop_id": "https://example.com",
            "company_name": "Test Store",
            "contact": json.dumps({"emails": ["test@example.com"], "phones": []}),
            "social_links": json.dumps({"facebook": "https://facebook.com/test"}),
            "analytics_tags": json.dumps([{"provider": "ga4", "tag_id": "G-123"}]),
            "pages_crawled": json.dumps(["https://example.com"]),
        }

        with patch(
            "app.db.merchant_profile_ingestor.MerchantProfileIngestor.get",
            new_callable=AsyncMock,
            return_value=mock_profile,
        ):
            response = gdpr_client.get(
                "/api/v1/merchants/profile",
                params={"shop_id": "https://example.com"},
                headers=gdpr_headers,
            )
            assert response.status_code == 200
            data = response.json()
            assert data["company_name"] == "Test Store"
            assert isinstance(data["contact"], dict)


class TestDeleteMerchantData:
    """Tests for DELETE /api/v1/merchants/{shop_id} (GDPR erasure)."""

    def test_delete_returns_correct_counts(self, gdpr_client, gdpr_headers):
        """DELETE endpoint returns correct deletion counts from DB."""
        mock_db_result = {"products_deleted": 42, "profiles_deleted": 1}

        with patch(
            "app.api.v1.merchants.BulkIngestor.delete_merchant_data",
            new_callable=AsyncMock,
            return_value=mock_db_result,
        ):
            response = gdpr_client.delete(
                "/api/v1/merchants/https://example.com",
                headers=gdpr_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["products_deleted"] == 42
        assert data["profiles_deleted"] == 1
        assert "shop_id" in data
        assert "redis_keys_deleted" in data

    def test_delete_with_no_data_returns_zeros(self, gdpr_client, gdpr_headers):
        """DELETE with no existing data returns zero counts."""
        mock_db_result = {"products_deleted": 0, "profiles_deleted": 0}

        with patch(
            "app.api.v1.merchants.BulkIngestor.delete_merchant_data",
            new_callable=AsyncMock,
            return_value=mock_db_result,
        ):
            response = gdpr_client.delete(
                "/api/v1/merchants/https://empty-store.com",
                headers=gdpr_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["products_deleted"] == 0
        assert data["profiles_deleted"] == 0
        assert data["redis_keys_deleted"] == 0

    def test_delete_cleans_up_redis_progress_keys(
        self, gdpr_client, gdpr_headers, gdpr_mock_redis
    ):
        """DELETE removes matching Redis progress keys."""
        # Seed a progress key that matches the shop being deleted
        gdpr_mock_redis.set_data(
            "progress:job_123",
            {"shop_url": "https://example.com", "status": "completed"},
        )

        mock_db_result = {"products_deleted": 0, "profiles_deleted": 0}

        with patch(
            "app.api.v1.merchants.BulkIngestor.delete_merchant_data",
            new_callable=AsyncMock,
            return_value=mock_db_result,
        ):
            response = gdpr_client.delete(
                "/api/v1/merchants/https://example.com",
                headers=gdpr_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["redis_keys_deleted"] >= 1

    def test_delete_cleans_up_dlq_entries(
        self, gdpr_client, gdpr_headers, gdpr_mock_redis
    ):
        """DELETE removes matching DLQ entries from Redis."""
        # Seed a DLQ entry containing the shop URL
        dlq_data = json.dumps({"shop_url": "https://target-store.com", "error": "timeout"})
        gdpr_mock_redis._data["hash:dlq:jobs"] = {"job_456": dlq_data}

        mock_db_result = {"products_deleted": 5, "profiles_deleted": 1}

        with patch(
            "app.api.v1.merchants.BulkIngestor.delete_merchant_data",
            new_callable=AsyncMock,
            return_value=mock_db_result,
        ):
            response = gdpr_client.delete(
                "/api/v1/merchants/https://target-store.com",
                headers=gdpr_headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["redis_keys_deleted"] >= 1

    def test_delete_without_db_still_cleans_redis(
        self, gdpr_mock_redis, gdpr_headers
    ):
        """DELETE works even when DB is unavailable (returns zeros for DB counts)."""
        original_api_keys = settings.api_keys
        settings.api_keys = "test-api-key-12345"

        app = create_app()
        limiter.enabled = False
        app.state.redis = gdpr_mock_redis
        # Deliberately do NOT set app.state.db so get_db returns None

        no_db_client = TestClient(app)

        response = no_db_client.delete(
            "/api/v1/merchants/https://example.com",
            headers=gdpr_headers,
        )

        settings.api_keys = original_api_keys

        assert response.status_code == 200
        data = response.json()
        assert data["products_deleted"] == 0
        assert data["profiles_deleted"] == 0
