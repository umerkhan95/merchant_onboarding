"""Shared pytest fixtures for all tests."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.deps import limiter
from app.config import settings
from app.main import create_app


class MockRedis:
    """Mock Redis client that works with both sync and async contexts."""

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def hgetall(self, key: str) -> dict:
        """Mock hgetall."""
        return self._data.get(f"hash:{key}", {})

    async def hget(self, key: str, field: str) -> str | None:
        """Mock hget."""
        hash_data = self._data.get(f"hash:{key}", {})
        return hash_data.get(field)

    async def hset(self, key: str, mapping: dict | None = None, **kwargs: Any) -> int:
        """Mock hset."""
        if f"hash:{key}" not in self._data:
            self._data[f"hash:{key}"] = {}
        if mapping:
            self._data[f"hash:{key}"].update(mapping)
        if kwargs:
            self._data[f"hash:{key}"].update(kwargs)
        return 1

    async def hdel(self, key: str, *fields: str) -> int:
        """Mock hdel."""
        hash_data = self._data.get(f"hash:{key}", {})
        count = 0
        for field in fields:
            if field in hash_data:
                del hash_data[field]
                count += 1
        return count

    async def setnx(self, key: str, value: Any) -> bool:
        """Mock setnx."""
        if key not in self._data:
            self._data[key] = value
            return True
        return False

    async def get(self, key: str) -> Any:
        """Mock get."""
        return self._data.get(key)

    async def zadd(self, key: str, mapping: dict[str, float]) -> int:
        """Mock zadd."""
        if key not in self._data:
            self._data[key] = {}
        self._data[key].update(mapping)
        return len(mapping)

    async def zrangebyscore(
        self, key: str, min_score: float | str, max_score: float | str
    ) -> list:
        """Mock zrangebyscore."""
        return list(self._data.get(key, {}).keys())

    async def zremrangebyscore(
        self, key: str, min_score: float | str, max_score: float | str
    ) -> int:
        """Mock zremrangebyscore."""
        return 0

    async def expire(self, key: str, seconds: int) -> bool:
        """Mock expire."""
        return True

    async def scan(self, cursor: int = 0, match: str | None = None, count: int = 100) -> tuple[int, list[str]]:
        """Mock scan."""
        keys = []
        if match and match.startswith("progress:"):
            for k in list(self._data.keys()):
                if k.startswith("hash:progress:"):
                    keys.append(k.removeprefix("hash:"))
        return 0, keys

    async def delete(self, *keys: str) -> int:
        """Mock delete."""
        count = 0
        for key in keys:
            if f"hash:{key}" in self._data:
                del self._data[f"hash:{key}"]
                count += 1
        return count

    def set_data(self, key: str, data: dict) -> None:
        """Set mock data for testing."""
        self._data[f"hash:{key}"] = data


@pytest.fixture
def mock_redis() -> MockRedis:
    """Create a mock Redis client for testing."""
    return MockRedis()


@pytest.fixture
def valid_api_key() -> str:
    """Return a valid API key for testing."""
    return "test-api-key-12345"


@pytest.fixture
def api_client(mock_redis: MockRedis, valid_api_key: str) -> TestClient:
    """Create a FastAPI test client with mocked dependencies."""
    # Configure settings with test API key
    original_api_keys = settings.api_keys
    settings.api_keys = valid_api_key

    # Create app
    app = create_app()

    # Disable rate limiting in tests
    limiter.enabled = False

    # Override Redis dependency with mock
    app.state.redis = mock_redis

    client = TestClient(app)

    yield client

    # Cleanup: restore original settings
    settings.api_keys = original_api_keys


@pytest.fixture
def headers(valid_api_key: str) -> dict[str, str]:
    """Return headers with valid API key."""
    return {"X-API-Key": valid_api_key}
