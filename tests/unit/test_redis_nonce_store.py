"""Tests for Redis-backed nonce store."""

import pytest
import fakeredis.aioredis

from app.security.redis_nonce_store import RedisNonceStore


@pytest.fixture
def redis_client():
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def store(redis_client):
    return RedisNonceStore(redis_client, ttl=10)


@pytest.mark.asyncio
async def test_set_and_get(store):
    await store.set("nonce1", "value1")
    result = await store.get("nonce1")
    assert result == "value1"


@pytest.mark.asyncio
async def test_contains(store):
    assert not await store.contains("missing")
    await store.set("present", "yes")
    assert await store.contains("present")


@pytest.mark.asyncio
async def test_pop_consumes(store):
    await store.set("nonce2", {"shop": "example.com"})
    result = await store.pop("nonce2")
    assert result == {"shop": "example.com"}
    # Second pop returns None
    assert await store.pop("nonce2") is None


@pytest.mark.asyncio
async def test_pop_missing(store):
    assert await store.pop("nonexistent") is None


@pytest.mark.asyncio
async def test_delete(store):
    await store.set("del-me", "val")
    await store.delete("del-me")
    assert not await store.contains("del-me")


@pytest.mark.asyncio
async def test_string_value(store):
    await store.set("str-nonce", "plain-string")
    result = await store.get("str-nonce")
    assert result == "plain-string"
