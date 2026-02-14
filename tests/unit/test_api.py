"""Unit tests for API endpoints."""

from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient

from app.models.enums import JobStatus
from tests.conftest import MockRedis


class TestHealthEndpoints:
    """Tests for health check endpoints (no auth required)."""

    def test_health_endpoint_returns_healthy(self, api_client: TestClient) -> None:
        """GET /health returns healthy status without authentication."""
        response = api_client.get("/health")
        assert response.status_code == 200
        assert response.json() == {"status": "healthy"}

    def test_readiness_endpoint_returns_ready(self, api_client: TestClient) -> None:
        """GET /readiness returns ready status without authentication."""
        response = api_client.get("/readiness")
        assert response.status_code == 200
        assert response.json() == {"ready": True}


class TestOnboardingEndpoint:
    """Tests for POST /api/v1/onboard endpoint."""

    def test_create_onboarding_job_valid_url_returns_202(
        self,
        api_client: TestClient,
        headers: dict[str, str],
        mock_redis: MockRedis,
    ) -> None:
        """POST /api/v1/onboard with valid URL returns 202 and job_id."""
        # Mock the Celery task import to avoid ImportError
        with patch("app.tasks.onboarding.process_onboarding_job"):
            response = api_client.post(
                "/api/v1/onboard",
                json={"url": "https://example-store.myshopify.com"},
                headers=headers,
            )

        assert response.status_code == 202
        data = response.json()

        # Verify response structure
        assert "job_id" in data
        assert data["job_id"].startswith("job_")
        assert data["status"] == JobStatus.QUEUED
        assert data["progress_url"] == f"/api/v1/onboard/{data['job_id']}/progress"

    def test_create_onboarding_job_invalid_url_returns_422(
        self,
        api_client: TestClient,
        headers: dict[str, str],
    ) -> None:
        """POST /api/v1/onboard with invalid URL returns 422."""
        response = api_client.post(
            "/api/v1/onboard",
            json={"url": "not-a-valid-url"},
            headers=headers,
        )

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_create_onboarding_job_private_ip_rejected(
        self,
        api_client: TestClient,
        headers: dict[str, str],
    ) -> None:
        """POST /api/v1/onboard with private IP URL returns 422."""
        response = api_client.post(
            "/api/v1/onboard",
            json={"url": "http://127.0.0.1:8000"},
            headers=headers,
        )

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_create_onboarding_job_localhost_rejected(
        self,
        api_client: TestClient,
        headers: dict[str, str],
    ) -> None:
        """POST /api/v1/onboard with localhost URL returns 422."""
        response = api_client.post(
            "/api/v1/onboard",
            json={"url": "http://localhost:3000"},
            headers=headers,
        )

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_create_onboarding_job_without_api_key_returns_422(
        self,
        api_client: TestClient,
    ) -> None:
        """POST /api/v1/onboard without API key returns 422 (missing header)."""
        response = api_client.post(
            "/api/v1/onboard",
            json={"url": "https://example-store.myshopify.com"},
        )

        assert response.status_code == 422
        data = response.json()
        assert "detail" in data

    def test_create_onboarding_job_invalid_api_key_returns_401(
        self,
        api_client: TestClient,
    ) -> None:
        """POST /api/v1/onboard with invalid API key returns 401."""
        response = api_client.post(
            "/api/v1/onboard",
            json={"url": "https://example-store.myshopify.com"},
            headers={"X-API-Key": "invalid-key"},
        )

        assert response.status_code == 401


class TestJobStatusEndpoint:
    """Tests for GET /api/v1/onboard/{job_id} endpoint."""

    def test_get_job_status_returns_progress(
        self,
        api_client: TestClient,
        headers: dict[str, str],
        mock_redis: MockRedis,
    ) -> None:
        """GET /api/v1/onboard/{job_id} returns job progress."""
        # Set up mock Redis data
        mock_redis.set_data(
            "progress:job_abc123",
            {
                "processed": "10",
                "total": "100",
                "percentage": "10.0",
                "status": JobStatus.EXTRACTING,
                "current_step": "Extracting products",
            },
        )

        response = api_client.get("/api/v1/onboard/job_abc123", headers=headers)

        assert response.status_code == 200
        data = response.json()

        assert data["job_id"] == "job_abc123"
        assert data["processed"] == 10
        assert data["total"] == 100
        assert data["percentage"] == 10.0
        assert data["status"] == JobStatus.EXTRACTING
        assert data["current_step"] == "Extracting products"
        assert data["error"] is None

    def test_get_job_status_unknown_id_returns_404(
        self,
        api_client: TestClient,
        headers: dict[str, str],
        mock_redis: MockRedis,
    ) -> None:
        """GET /api/v1/onboard/{job_id} with unknown ID returns 404."""
        # Don't set up any data for this job (it won't be found)
        response = api_client.get("/api/v1/onboard/unknown_job", headers=headers)

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_get_job_status_without_api_key_returns_422(
        self,
        api_client: TestClient,
    ) -> None:
        """GET /api/v1/onboard/{job_id} without API key returns 422 (missing header)."""
        response = api_client.get("/api/v1/onboard/job_abc123")
        assert response.status_code == 422


class TestProductsEndpoint:
    """Tests for /api/v1/products endpoints."""

    def test_list_products_returns_paginated_response(
        self,
        api_client: TestClient,
        headers: dict[str, str],
    ) -> None:
        """GET /api/v1/products?shop_id=test returns paginated response."""
        response = api_client.get(
            "/api/v1/products?shop_id=test_shop&page=1&per_page=50",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()

        # Verify pagination structure (placeholder implementation)
        assert "data" in data
        assert "pagination" in data
        assert "shop_id" in data
        assert data["shop_id"] == "test_shop"
        assert data["pagination"]["page"] == 1
        assert data["pagination"]["per_page"] == 50
        assert data["pagination"]["total"] == 0
        assert data["pagination"]["total_pages"] == 0

    def test_list_products_default_pagination(
        self,
        api_client: TestClient,
        headers: dict[str, str],
    ) -> None:
        """GET /api/v1/products uses default pagination values."""
        response = api_client.get("/api/v1/products?shop_id=test", headers=headers)

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["page"] == 1
        assert data["pagination"]["per_page"] == 50

    def test_list_products_custom_pagination(
        self,
        api_client: TestClient,
        headers: dict[str, str],
    ) -> None:
        """GET /api/v1/products respects custom pagination parameters."""
        response = api_client.get(
            "/api/v1/products?shop_id=test&page=2&per_page=25",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["pagination"]["page"] == 2
        assert data["pagination"]["per_page"] == 25

    def test_list_products_validates_per_page_max(
        self,
        api_client: TestClient,
        headers: dict[str, str],
    ) -> None:
        """GET /api/v1/products rejects per_page > 100."""
        response = api_client.get(
            "/api/v1/products?shop_id=test&per_page=150",
            headers=headers,
        )

        assert response.status_code == 422

    def test_list_products_without_api_key_returns_422(
        self,
        api_client: TestClient,
    ) -> None:
        """GET /api/v1/products without API key returns 422 (missing header)."""
        response = api_client.get("/api/v1/products?shop_id=test")
        assert response.status_code == 422

    def test_get_product_returns_404(
        self,
        api_client: TestClient,
        headers: dict[str, str],
    ) -> None:
        """GET /api/v1/products/{product_id} returns 404 (placeholder)."""
        response = api_client.get("/api/v1/products/12345", headers=headers)

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_get_product_without_api_key_returns_422(
        self,
        api_client: TestClient,
    ) -> None:
        """GET /api/v1/products/{product_id} without API key returns 422 (missing header)."""
        response = api_client.get("/api/v1/products/12345")
        assert response.status_code == 422


class TestDLQEndpoint:
    """Tests for /api/v1/dlq endpoints."""

    def test_list_dlq_entries_returns_list(
        self,
        api_client: TestClient,
        headers: dict[str, str],
        mock_redis: MockRedis,
    ) -> None:
        """GET /api/v1/dlq returns list of DLQ entries."""
        # Set up mock DLQ data
        mock_redis.set_data(
            "dlq:jobs",
            {
                "job_123": '{"url": "https://example.com", "error": "Extraction failed"}',
                "job_456": '{"url": "https://test.com", "error": "Timeout"}',
            },
        )

        response = api_client.get("/api/v1/dlq", headers=headers)

        assert response.status_code == 200
        data = response.json()

        assert "entries" in data
        assert "count" in data
        assert data["count"] == 2
        assert len(data["entries"]) == 2

    def test_list_dlq_entries_empty(
        self,
        api_client: TestClient,
        headers: dict[str, str],
        mock_redis: MockRedis,
    ) -> None:
        """GET /api/v1/dlq returns empty list when DLQ is empty."""
        # Don't set up any DLQ data
        response = api_client.get("/api/v1/dlq", headers=headers)

        assert response.status_code == 200
        data = response.json()

        assert data["entries"] == []
        assert data["count"] == 0

    def test_list_dlq_without_api_key_returns_422(
        self,
        api_client: TestClient,
    ) -> None:
        """GET /api/v1/dlq without API key returns 422 (missing header)."""
        response = api_client.get("/api/v1/dlq")
        assert response.status_code == 422

    def test_retry_dlq_entry_success(
        self,
        api_client: TestClient,
        headers: dict[str, str],
        mock_redis: MockRedis,
    ) -> None:
        """POST /api/v1/dlq/{job_id}/retry successfully re-queues job."""
        # Set up mock DLQ data
        job_data = '{"url": "https://example.com", "error": "Previous failure"}'
        mock_redis.set_data("dlq:jobs", {"job_123": job_data})

        with patch("app.tasks.onboarding.process_onboarding_job"):
            response = api_client.post("/api/v1/dlq/job_123/retry", headers=headers)

        assert response.status_code == 202
        data = response.json()

        assert "message" in data
        assert "job_id" in data
        assert data["job_id"] == "job_123"

    def test_retry_dlq_entry_not_found(
        self,
        api_client: TestClient,
        headers: dict[str, str],
        mock_redis: MockRedis,
    ) -> None:
        """POST /api/v1/dlq/{job_id}/retry returns 404 if job not in DLQ."""
        # Don't set up any DLQ data for this job
        response = api_client.post("/api/v1/dlq/unknown_job/retry", headers=headers)

        assert response.status_code == 404
        data = response.json()
        assert "detail" in data

    def test_retry_dlq_without_api_key_returns_422(
        self,
        api_client: TestClient,
    ) -> None:
        """POST /api/v1/dlq/{job_id}/retry without API key returns 422 (missing header)."""
        response = api_client.post("/api/v1/dlq/job_123/retry")
        assert response.status_code == 422


class TestPingEndpoint:
    """Tests for utility endpoints."""

    def test_ping_endpoint(self, api_client: TestClient) -> None:
        """GET /api/v1/ping returns pong (no auth required for backward compatibility)."""
        response = api_client.get("/api/v1/ping")
        assert response.status_code == 200
        assert response.json() == {"pong": True}
