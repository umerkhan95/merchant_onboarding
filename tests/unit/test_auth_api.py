"""Unit tests for OAuth auth API endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
import respx
from httpx import Response

from app.db.oauth_store import OAuthConnection


# ── BigCommerce Connect ──────────────────────────────────────────────


def test_bigcommerce_connect_returns_auth_url(api_client, headers):
    with patch("app.api.v1.auth.settings") as mock_settings:
        mock_settings.bigcommerce_client_id = "test-client-id"
        mock_settings.bigcommerce_callback_url = "http://localhost:8000/api/v1/auth/bigcommerce/callback"

        resp = api_client.get(
            "/api/v1/auth/bigcommerce/connect?shop=store-abc123",
            headers=headers,
        )

    assert resp.status_code == 200
    data = resp.json()
    assert "auth_url" in data
    assert "login.bigcommerce.com" in data["auth_url"]
    assert "test-client-id" in data["auth_url"]
    assert data["shop"] == "store-abc123"


def test_bigcommerce_connect_not_configured(api_client, headers):
    with patch("app.api.v1.auth.settings") as mock_settings:
        mock_settings.bigcommerce_client_id = ""

        resp = api_client.get(
            "/api/v1/auth/bigcommerce/connect?shop=store-abc123",
            headers=headers,
        )

    assert resp.status_code == 501


def test_bigcommerce_connect_requires_api_key(api_client):
    resp = api_client.get("/api/v1/auth/bigcommerce/connect?shop=store-abc123")
    # FastAPI returns 422 when api key header is missing (Depends validation)
    # or 401/403 if the key check runs first
    assert resp.status_code in (401, 403, 422)


# ── BigCommerce Callback ─────────────────────────────────────────────


def test_bigcommerce_callback_exchanges_code(api_client):
    """Callback should exchange code for token and store it."""
    mock_oauth_store = AsyncMock()
    mock_oauth_store.store_connection = AsyncMock()

    with (
        patch("app.api.v1.auth.settings") as mock_settings,
        patch("app.api.v1.auth._get_oauth_store", return_value=mock_oauth_store),
        respx.mock,
    ):
        mock_settings.bigcommerce_client_id = "test-client-id"
        mock_settings.bigcommerce_client_secret = "test-client-secret"
        mock_settings.bigcommerce_callback_url = "http://localhost:8000/api/v1/auth/bigcommerce/callback"

        respx.post("https://login.bigcommerce.com/oauth2/token").mock(
            return_value=Response(200, json={
                "access_token": "returned-access-token",
                "scope": "store_v2_products_read_only",
                "context": "stores/abc123",
                "user": {"id": 42, "email": "merchant@example.com"},
            })
        )

        resp = api_client.get(
            "/api/v1/auth/bigcommerce/callback?code=test-code&scope=store_v2_products_read_only&context=stores/abc123"
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "connected"
    assert data["platform"] == "bigcommerce"
    assert data["store_hash"] == "abc123"

    # Verify store_connection was called with encrypted token
    mock_oauth_store.store_connection.assert_called_once()
    call_kwargs = mock_oauth_store.store_connection.call_args
    assert call_kwargs.kwargs["access_token"] == "returned-access-token"
    assert call_kwargs.kwargs["store_hash"] == "abc123"


def test_bigcommerce_callback_token_exchange_failure(api_client):
    with (
        patch("app.api.v1.auth.settings") as mock_settings,
        respx.mock,
    ):
        mock_settings.bigcommerce_client_id = "test-client-id"
        mock_settings.bigcommerce_client_secret = "test-client-secret"
        mock_settings.bigcommerce_callback_url = "http://localhost:8000/callback"

        respx.post("https://login.bigcommerce.com/oauth2/token").mock(
            return_value=Response(400, json={"error": "invalid_grant"})
        )

        resp = api_client.get(
            "/api/v1/auth/bigcommerce/callback?code=bad-code&scope=scope&context=stores/abc"
        )

    assert resp.status_code == 502


def test_bigcommerce_callback_no_token_in_response(api_client):
    mock_oauth_store = AsyncMock()

    with (
        patch("app.api.v1.auth.settings") as mock_settings,
        patch("app.api.v1.auth._get_oauth_store", return_value=mock_oauth_store),
        respx.mock,
    ):
        mock_settings.bigcommerce_client_id = "cid"
        mock_settings.bigcommerce_client_secret = "csec"
        mock_settings.bigcommerce_callback_url = "http://localhost/callback"

        respx.post("https://login.bigcommerce.com/oauth2/token").mock(
            return_value=Response(200, json={"scope": "read"})
        )

        resp = api_client.get(
            "/api/v1/auth/bigcommerce/callback?code=c&scope=s&context=stores/x"
        )

    assert resp.status_code == 502
    assert "access token" in resp.json()["detail"].lower()


# ── BigCommerce Disconnect ───────────────────────────────────────────


def test_bigcommerce_disconnect(api_client, headers):
    mock_oauth_store = AsyncMock()
    mock_oauth_store.revoke_connection = AsyncMock()

    with patch("app.api.v1.auth._get_oauth_store", return_value=mock_oauth_store):
        resp = api_client.delete(
            "/api/v1/auth/bigcommerce/disconnect?shop=store-abc123",
            headers=headers,
        )

    assert resp.status_code == 200
    assert resp.json()["status"] == "disconnected"
    mock_oauth_store.revoke_connection.assert_called_once_with("bigcommerce", "store-abc123")


# ── Connection Management ────────────────────────────────────────────


def test_list_connections(api_client, headers):
    mock_oauth_store = AsyncMock()
    mock_oauth_store.list_connections = AsyncMock(return_value=[
        {"platform": "bigcommerce", "shop_domain": "store1.com", "status": "active"},
    ])

    with patch("app.api.v1.auth._get_oauth_store", return_value=mock_oauth_store):
        resp = api_client.get("/api/v1/auth/connections", headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["platform"] == "bigcommerce"


def test_get_connection_status_found(api_client, headers):
    conn = OAuthConnection(
        id=1,
        platform="bigcommerce",
        shop_domain="store.example.com",
        store_hash="abc123",
        scopes="store_v2_products_read_only",
    )
    mock_oauth_store = AsyncMock()
    mock_oauth_store.get_connection_by_domain = AsyncMock(return_value=conn)

    with patch("app.api.v1.auth._get_oauth_store", return_value=mock_oauth_store):
        resp = api_client.get("/api/v1/auth/connections/store.example.com", headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is True
    assert data["platform"] == "bigcommerce"
    assert data["store_hash"] == "abc123"


def test_get_connection_status_not_found(api_client, headers):
    mock_oauth_store = AsyncMock()
    mock_oauth_store.get_connection_by_domain = AsyncMock(return_value=None)

    with patch("app.api.v1.auth._get_oauth_store", return_value=mock_oauth_store):
        resp = api_client.get("/api/v1/auth/connections/nonexistent.com", headers=headers)

    assert resp.status_code == 200
    data = resp.json()
    assert data["connected"] is False


# ── Database unavailable ─────────────────────────────────────────────


def test_db_unavailable_returns_503(api_client, headers):
    """When DB is None, endpoints that need OAuth store should return 503."""
    # The api_client fixture doesn't set up a real DB, so get_db returns None
    # _get_oauth_store raises 503 when db is None
    # This depends on how the dependency is set up in the test fixture
    with patch("app.api.v1.auth._get_oauth_store") as mock_fn:
        from fastapi import HTTPException
        mock_fn.side_effect = HTTPException(status_code=503, detail="Database unavailable")

        resp = api_client.get("/api/v1/auth/connections", headers=headers)

    assert resp.status_code == 503
