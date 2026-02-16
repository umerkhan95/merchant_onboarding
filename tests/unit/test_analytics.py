"""Tests for ProgressTracker extensions and analytics endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from app.infra.progress_tracker import ProgressTracker


# --------------- ProgressTracker unit tests ---------------


@pytest.fixture
def mock_redis():
    """Create a mock Redis client backed by a dict to simulate hash ops."""
    store: dict[str, dict[str, str]] = {}
    r = AsyncMock()

    async def hset(key, mapping=None, **kwargs):
        if key not in store:
            store[key] = {}
        if mapping:
            store[key].update({str(k): str(v) for k, v in mapping.items()})

    async def hgetall(key):
        return store.get(key, {})

    async def expire(key, ttl):
        pass

    async def scan(cursor=0, match=None, count=100):
        keys = [k for k in store if k.startswith(match.replace("*", ""))] if match else list(store)
        return (0, keys)

    async def delete(key):
        store.pop(key, None)

    r.hset = AsyncMock(side_effect=hset)
    r.hgetall = AsyncMock(side_effect=hgetall)
    r.expire = AsyncMock(side_effect=expire)
    r.scan = AsyncMock(side_effect=scan)
    r.delete = AsyncMock(side_effect=delete)
    r._store = store
    return r


@pytest.fixture
def tracker(mock_redis):
    return ProgressTracker(mock_redis)


@pytest.mark.asyncio
async def test_set_metadata_stores_fields(tracker, mock_redis):
    await tracker.update("j1", 0, 0, "queued", "waiting")
    await tracker.set_metadata("j1", shop_url="https://example.com", platform="shopify")

    data = await tracker.get("j1")
    assert data is not None
    assert data["shop_url"] == "https://example.com"
    assert data["platform"] == "shopify"
    assert data["status"] == "queued"


@pytest.mark.asyncio
async def test_set_metadata_noop_when_empty(tracker, mock_redis):
    await tracker.set_metadata("j2")
    mock_redis.hset.assert_not_awaited


@pytest.mark.asyncio
async def test_products_count_parsed_as_int(tracker):
    await tracker.update("j3", 10, 100, "completed", "done")
    await tracker.set_metadata("j3", products_count=42)

    data = await tracker.get("j3")
    assert data is not None
    assert data["products_count"] == 42
    assert isinstance(data["products_count"], int)


@pytest.mark.asyncio
async def test_list_all_jobs(tracker):
    await tracker.update("j4", 0, 0, "queued", "waiting")
    await tracker.set_metadata("j4", shop_url="https://a.com")
    await tracker.update("j5", 10, 10, "completed", "done")
    await tracker.set_metadata("j5", shop_url="https://b.com")

    jobs = await tracker.list_all_jobs()
    assert len(jobs) == 2
    ids = {j["job_id"] for j in jobs}
    assert ids == {"j4", "j5"}


@pytest.mark.asyncio
async def test_ttl_is_seven_days(tracker):
    assert tracker.ttl_seconds == 604800


# --------------- Analytics endpoint tests ---------------


# --------------- Analytics endpoint tests ---------------

# These tests use the shared api_client and headers fixtures from conftest.py.
# The conftest MockRedis doesn't support scan(), so we need a custom fixture.


@pytest.fixture
def analytics_client():
    """Create a test client with AsyncMock Redis that supports scan()."""
    from app.config import settings
    from app.main import create_app

    original_api_keys = settings.api_keys
    settings.api_keys = "test-key"

    application = create_app()

    mock_redis = AsyncMock()
    mock_redis.hgetall = AsyncMock(return_value={})
    mock_redis.scan = AsyncMock(return_value=(0, []))

    application.state.redis = mock_redis
    client = TestClient(application)

    yield client, mock_redis

    settings.api_keys = original_api_keys


def test_jobs_endpoint_returns_empty(analytics_client):
    client, _ = analytics_client
    resp = client.get("/api/v1/jobs", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 0
    assert data["jobs"] == []


def test_analytics_endpoint_returns_empty(analytics_client):
    client, _ = analytics_client
    resp = client.get("/api/v1/analytics", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_jobs"] == 0
    assert data["total_products"] == 0
    assert data["success_rate"] == 0.0


def test_jobs_endpoint_with_status_filter(analytics_client):
    client, mock_redis = analytics_client

    async def scan_mock(cursor=0, match=None, count=100):
        return (0, ["progress:j1", "progress:j2"])

    async def hgetall_mock(key):
        if key == "progress:j1":
            return {"status": "completed", "processed": "10", "total": "10",
                    "percentage": "100", "current_step": "done", "shop_url": "https://a.com"}
        if key == "progress:j2":
            return {"status": "failed", "processed": "0", "total": "5",
                    "percentage": "0", "current_step": "err", "error": "boom"}
        return {}

    mock_redis.scan = AsyncMock(side_effect=scan_mock)
    mock_redis.hgetall = AsyncMock(side_effect=hgetall_mock)

    resp = client.get("/api/v1/jobs?status=completed", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 1
    assert data["jobs"][0]["status"] == "completed"


def test_analytics_aggregation(analytics_client):
    client, mock_redis = analytics_client

    async def scan_mock(cursor=0, match=None, count=100):
        return (0, ["progress:j1", "progress:j2"])

    async def hgetall_mock(key):
        if key == "progress:j1":
            return {
                "status": "completed", "processed": "10", "total": "10",
                "percentage": "100", "current_step": "done",
                "platform": "shopify", "extraction_tier": "api",
                "products_count": "25",
                "started_at": "2026-02-16T10:00:00+00:00",
                "completed_at": "2026-02-16T10:01:00+00:00",
            }
        if key == "progress:j2":
            return {
                "status": "failed", "processed": "0", "total": "5",
                "percentage": "0", "current_step": "err",
                "platform": "woocommerce", "products_count": "0",
            }
        return {}

    mock_redis.scan = AsyncMock(side_effect=scan_mock)
    mock_redis.hgetall = AsyncMock(side_effect=hgetall_mock)

    resp = client.get("/api/v1/analytics", headers={"X-API-Key": "test-key"})
    assert resp.status_code == 200
    data = resp.json()
    assert data["total_jobs"] == 2
    assert data["total_products"] == 25
    assert data["success_rate"] == 50.0
    assert data["avg_duration_seconds"] == 60.0
    assert len(data["jobs_by_status"]) == 2
    assert len(data["jobs_by_platform"]) == 2
