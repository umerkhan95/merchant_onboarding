"""Unit tests for SchemaCache."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from app.extractors.schema_cache import SchemaCache


@pytest.fixture
def mock_redis():
    """Mock async Redis client."""
    return AsyncMock()


@pytest.fixture
def schema_cache(mock_redis):
    """Schema cache with mocked Redis."""
    return SchemaCache(redis_client=mock_redis, ttl=3600)


@pytest.fixture
def valid_schema():
    """A valid CSS extraction schema."""
    return {
        "baseSelector": ".product-card",
        "fields": [
            {"name": "title", "selector": ".title", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text"},
        ],
    }


class TestNormalizeDomain:
    """Test domain normalization logic."""

    def test_strips_scheme(self):
        assert SchemaCache._normalize_domain("https://example.com/page") == "example.com"

    def test_strips_www(self):
        assert SchemaCache._normalize_domain("https://www.example.com/page") == "example.com"

    def test_strips_port(self):
        assert SchemaCache._normalize_domain("https://example.com:8080/page") == "example.com"

    def test_lowercases(self):
        assert SchemaCache._normalize_domain("https://EXAMPLE.COM/page") == "example.com"

    def test_full_normalization(self):
        assert SchemaCache._normalize_domain("https://www.SHOP.COM:443/products/1") == "shop.com"


class TestSchemaCache:
    """Test suite for SchemaCache."""

    async def test_get_cache_hit(self, schema_cache, mock_redis, valid_schema):
        """Test successful cache retrieval."""
        mock_redis.get.return_value = json.dumps(valid_schema).encode()

        result = await schema_cache.get("https://www.example.com/product/1")

        assert result == valid_schema
        mock_redis.get.assert_called_once_with("schema_cache:example.com")

    async def test_get_cache_miss(self, schema_cache, mock_redis):
        """Test cache miss returns None."""
        mock_redis.get.return_value = None

        result = await schema_cache.get("https://example.com/product/1")

        assert result is None

    async def test_get_redis_error(self, schema_cache, mock_redis):
        """Test graceful handling of Redis errors on get."""
        mock_redis.get.side_effect = ConnectionError("Redis down")

        result = await schema_cache.get("https://example.com/product/1")

        assert result is None

    async def test_set_valid_schema(self, schema_cache, mock_redis, valid_schema):
        """Test caching a valid schema."""
        await schema_cache.set("https://www.example.com/product/1", valid_schema)

        mock_redis.set.assert_called_once_with(
            "schema_cache:example.com",
            json.dumps(valid_schema),
            ex=3600,
        )

    async def test_set_rejects_missing_base_selector(self, schema_cache, mock_redis):
        """Test that schemas without baseSelector are rejected."""
        invalid_schema = {"fields": [{"name": "title"}]}

        await schema_cache.set("https://example.com", invalid_schema)

        mock_redis.set.assert_not_called()

    async def test_set_rejects_missing_fields(self, schema_cache, mock_redis):
        """Test that schemas without fields are rejected."""
        invalid_schema = {"baseSelector": ".product"}

        await schema_cache.set("https://example.com", invalid_schema)

        mock_redis.set.assert_not_called()

    async def test_set_redis_error(self, schema_cache, mock_redis, valid_schema):
        """Test graceful handling of Redis errors on set."""
        mock_redis.set.side_effect = ConnectionError("Redis down")

        # Should not raise
        await schema_cache.set("https://example.com/product/1", valid_schema)

    async def test_invalidate(self, schema_cache, mock_redis):
        """Test schema invalidation."""
        await schema_cache.invalidate("https://www.example.com/product/1")

        mock_redis.delete.assert_called_once_with("schema_cache:example.com")

    async def test_invalidate_redis_error(self, schema_cache, mock_redis):
        """Test graceful handling of Redis errors on invalidate."""
        mock_redis.delete.side_effect = ConnectionError("Redis down")

        # Should not raise
        await schema_cache.invalidate("https://example.com/product/1")

    async def test_same_domain_different_paths_share_cache(self, schema_cache, mock_redis, valid_schema):
        """Test that different paths on the same domain use the same cache key."""
        mock_redis.get.return_value = json.dumps(valid_schema).encode()

        await schema_cache.get("https://example.com/product/1")
        await schema_cache.get("https://example.com/product/2")

        # Both calls should use the same key
        calls = mock_redis.get.call_args_list
        assert calls[0][0][0] == "schema_cache:example.com"
        assert calls[1][0][0] == "schema_cache:example.com"
