"""Unit tests for OAuthStore — encryption, CRUD operations."""

from __future__ import annotations

import json
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.db.oauth_store import OAuthConnection, OAuthStore


# ── OAuthConnection dataclass ────────────────────────────────────────


def test_oauth_connection_defaults():
    conn = OAuthConnection(id=1, platform="bigcommerce", shop_domain="store.example.com")
    assert conn.extra_data == {}
    assert conn.status == "active"
    assert conn.access_token is None


def test_oauth_connection_post_init_none_extra_data():
    conn = OAuthConnection(id=1, platform="shopify", shop_domain="s.myshopify.com", extra_data=None)
    assert conn.extra_data == {}


def test_oauth_connection_preserves_extra_data():
    conn = OAuthConnection(id=1, platform="woocommerce", shop_domain="woo.com", extra_data={"key": "val"})
    assert conn.extra_data == {"key": "val"}


# ── Fernet encryption ────────────────────────────────────────────────


# Valid Fernet key for testing (generated offline)
TEST_FERNET_KEY = "dGVzdC1rZXktMTIzNDU2Nzg5MDEyMzQ1Njc4OTAxMjM0"  # Not a real key


@pytest.fixture
def mock_db():
    """Mock DatabaseClient with a mock pool."""
    db = MagicMock()
    db.pool = MagicMock()
    conn_mock = AsyncMock()
    db.pool.acquire.return_value.__aenter__ = AsyncMock(return_value=conn_mock)
    db.pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)
    return db, conn_mock


@pytest.fixture
def oauth_store_with_encryption():
    """Create an OAuthStore with a real Fernet key for encryption tests."""
    from cryptography.fernet import Fernet
    key = Fernet.generate_key()
    db = MagicMock()
    store = OAuthStore.__new__(OAuthStore)
    store._db = db
    store._fernet = Fernet(key)
    return store


def test_encrypt_decrypt_roundtrip(oauth_store_with_encryption):
    store = oauth_store_with_encryption
    original = "super-secret-token-12345"
    encrypted = store._encrypt(original)
    assert encrypted is not None
    assert encrypted != original.encode()
    decrypted = store._decrypt(encrypted)
    assert decrypted == original


def test_encrypt_none_returns_none(oauth_store_with_encryption):
    assert oauth_store_with_encryption._encrypt(None) is None
    assert oauth_store_with_encryption._encrypt("") is None


def test_decrypt_none_returns_none(oauth_store_with_encryption):
    assert oauth_store_with_encryption._decrypt(None) is None
    assert oauth_store_with_encryption._decrypt(b"") is None


def test_decrypt_invalid_token_returns_none(oauth_store_with_encryption):
    result = oauth_store_with_encryption._decrypt(b"not-a-valid-fernet-token")
    assert result is None


def test_no_encryption_key_returns_none():
    """When OAUTH_ENCRYPTION_KEY is not set, encrypt/decrypt return None."""
    store = OAuthStore.__new__(OAuthStore)
    store._fernet = None
    assert store._encrypt("token") is None
    assert store._decrypt(b"encrypted") is None


# ── store_connection ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_store_connection(mock_db, oauth_store_with_encryption):
    db, conn_mock = mock_db
    store = oauth_store_with_encryption
    store._db = db

    await store.store_connection(
        platform="bigcommerce",
        shop_domain="store.example.com",
        access_token="my-token",
        scopes="store_v2_products_read_only",
        store_hash="abc123",
        extra_data={"user_id": 42},
    )

    conn_mock.execute.assert_called_once()
    args = conn_mock.execute.call_args[0]
    # First arg is the query, then positional params
    assert args[1] == "bigcommerce"
    assert args[2] == "store.example.com"
    # Access token should be encrypted (bytes, not the original string)
    assert isinstance(args[3], bytes)
    assert args[3] != b"my-token"


# ── get_connection ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_connection_found(mock_db, oauth_store_with_encryption):
    db, conn_mock = mock_db
    store = oauth_store_with_encryption
    store._db = db

    # Encrypt a token to simulate what's in DB
    encrypted_token = store._encrypt("stored-token")

    conn_mock.fetchrow.return_value = {
        "id": 1,
        "platform": "bigcommerce",
        "shop_domain": "store.example.com",
        "access_token_encrypted": encrypted_token,
        "refresh_token_encrypted": None,
        "token_expires_at": None,
        "scopes": "store_v2_products_read_only",
        "consumer_key_encrypted": None,
        "consumer_secret_encrypted": None,
        "access_token_secret_encrypted": None,
        "store_hash": "abc123",
        "extra_data": json.dumps({"user_id": 42}),
        "connected_at": datetime(2026, 3, 12),
        "last_used_at": None,
        "status": "active",
    }

    result = await store.get_connection("bigcommerce", "store.example.com")

    assert result is not None
    assert result.platform == "bigcommerce"
    assert result.access_token == "stored-token"
    assert result.store_hash == "abc123"
    assert result.extra_data == {"user_id": 42}


@pytest.mark.asyncio
async def test_get_connection_not_found(mock_db, oauth_store_with_encryption):
    db, conn_mock = mock_db
    store = oauth_store_with_encryption
    store._db = db
    conn_mock.fetchrow.return_value = None

    result = await store.get_connection("bigcommerce", "nonexistent.com")
    assert result is None


# ── list_connections ─────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_list_connections(mock_db, oauth_store_with_encryption):
    db, conn_mock = mock_db
    store = oauth_store_with_encryption
    store._db = db

    conn_mock.fetch.return_value = [
        {"platform": "bigcommerce", "shop_domain": "store1.com", "status": "active"},
        {"platform": "shopify", "shop_domain": "store2.myshopify.com", "status": "active"},
    ]

    result = await store.list_connections()
    assert len(result) == 2
    assert result[0]["platform"] == "bigcommerce"
    assert result[1]["platform"] == "shopify"


# ── revoke_connection ────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_revoke_connection(mock_db, oauth_store_with_encryption):
    db, conn_mock = mock_db
    store = oauth_store_with_encryption
    store._db = db

    await store.revoke_connection("bigcommerce", "store.example.com")
    conn_mock.execute.assert_called_once()
    args = conn_mock.execute.call_args[0]
    assert args[1] == "bigcommerce"
    assert args[2] == "store.example.com"


# ── _row_to_connection edge cases ────────────────────────────────────


def test_row_to_connection_invalid_json_extra_data(oauth_store_with_encryption):
    store = oauth_store_with_encryption
    row = {
        "id": 1,
        "platform": "test",
        "shop_domain": "test.com",
        "access_token_encrypted": None,
        "refresh_token_encrypted": None,
        "token_expires_at": None,
        "scopes": None,
        "consumer_key_encrypted": None,
        "consumer_secret_encrypted": None,
        "access_token_secret_encrypted": None,
        "store_hash": None,
        "extra_data": "not-valid-json{",
        "connected_at": None,
        "last_used_at": None,
        "status": "active",
    }
    conn = store._row_to_connection(row)
    assert conn.extra_data == {}


def test_row_to_connection_dict_extra_data(oauth_store_with_encryption):
    """When extra_data is already a dict (not a string), it should be preserved."""
    store = oauth_store_with_encryption
    row = {
        "id": 1,
        "platform": "test",
        "shop_domain": "test.com",
        "access_token_encrypted": None,
        "refresh_token_encrypted": None,
        "token_expires_at": None,
        "scopes": None,
        "consumer_key_encrypted": None,
        "consumer_secret_encrypted": None,
        "access_token_secret_encrypted": None,
        "store_hash": None,
        "extra_data": {"already": "parsed"},
        "connected_at": None,
        "last_used_at": None,
        "status": "active",
    }
    conn = store._row_to_connection(row)
    assert conn.extra_data == {"already": "parsed"}
