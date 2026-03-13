"""Unit tests for Shopware OAuth authentication endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1.shopware_auth import _validate_sw_domain


# ── Domain validation ────────────────────────────────────────────────


class TestValidateSwDomain:
    """Tests for _validate_sw_domain helper."""

    def test_plain_domain(self):
        assert _validate_sw_domain("my-store.com") == "my-store.com"

    def test_strips_https(self):
        assert _validate_sw_domain("https://my-store.com") == "my-store.com"

    def test_strips_http(self):
        assert _validate_sw_domain("http://my-store.com") == "my-store.com"

    def test_strips_trailing_slash(self):
        assert _validate_sw_domain("my-store.com/") == "my-store.com"

    def test_lowercases(self):
        assert _validate_sw_domain("My-Store.COM") == "my-store.com"

    def test_strips_whitespace(self):
        assert _validate_sw_domain("  my-store.com  ") == "my-store.com"

    def test_subdomain(self):
        assert _validate_sw_domain("shop.example.co.uk") == "shop.example.co.uk"

    def test_empty_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_sw_domain("")
        assert exc_info.value.status_code == 400
        assert "required" in exc_info.value.detail.lower()

    def test_whitespace_only_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_sw_domain("   ")
        assert exc_info.value.status_code == 400

    def test_no_tld_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_sw_domain("localhost")
        assert exc_info.value.status_code == 400

    def test_invalid_characters_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_sw_domain("invalid domain.com")
        assert exc_info.value.status_code == 400

    def test_invalid_detail_message(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_sw_domain("not-a-domain")
        assert exc_info.value.status_code == 400
        assert "invalid" in exc_info.value.detail.lower()


# ── Connect endpoint ──────────────────────────────────────────────────


class TestShopwareConnect:
    """Tests for GET /api/v1/auth/shopware/connect."""

    def test_connect_returns_instructions(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.get(
            "/api/v1/auth/shopware/connect?shop=my-store.com",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["platform"] == "shopware"
        assert data["shop"] == "my-store.com"
        assert "instructions" in data
        assert "manual_url" in data
        assert "/api/v1/auth/shopware/manual" in data["manual_url"]

    def test_connect_instructions_mention_integration(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.get(
            "/api/v1/auth/shopware/connect?shop=my-store.com",
            headers=headers,
        )

        assert response.status_code == 200
        instructions = response.json()["instructions"]
        assert "Integration" in instructions or "integration" in instructions

    def test_connect_normalizes_domain(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.get(
            "/api/v1/auth/shopware/connect?shop=https://My-Store.com/",
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["shop"] == "my-store.com"

    def test_connect_invalid_domain_returns_400(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.get(
            "/api/v1/auth/shopware/connect?shop=not-valid",
            headers=headers,
        )

        assert response.status_code == 400

    def test_connect_without_api_key_returns_error(self, api_client: TestClient):
        response = api_client.get(
            "/api/v1/auth/shopware/connect?shop=my-store.com",
        )
        assert response.status_code in (401, 422)

    def test_connect_missing_shop_param_returns_422(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.get(
            "/api/v1/auth/shopware/connect",
            headers=headers,
        )
        assert response.status_code == 422


# ── Manual endpoint ───────────────────────────────────────────────────


class TestShopwareManual:
    """Tests for POST /api/v1/auth/shopware/manual."""

    def _mock_httpx_success(self) -> tuple[MagicMock, MagicMock]:
        """Return (mock_client_cls, mock_client) configured for successful token response."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "access_token": "sw-access-token-abc123",
            "token_type": "Bearer",
            "expires_in": 600,
        }
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_client_cls = MagicMock(return_value=mock_client)
        return mock_client_cls, mock_client

    def test_manual_success_stores_credentials(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_client_cls, _ = self._mock_httpx_success()
        mock_oauth_store = AsyncMock()

        with (
            patch("app.api.v1.shopware_auth.httpx.AsyncClient", mock_client_cls),
            patch("app.api.v1.shopware_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            response = api_client.post(
                "/api/v1/auth/shopware/manual",
                headers=headers,
                json={
                    "shop": "my-store.com",
                    "client_id": "SWIA1234567890",
                    "client_secret": "supersecret",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert data["platform"] == "shopware"
        assert data["shop"] == "my-store.com"

    def test_manual_success_calls_store_connection(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_client_cls, _ = self._mock_httpx_success()
        mock_oauth_store = AsyncMock()

        with (
            patch("app.api.v1.shopware_auth.httpx.AsyncClient", mock_client_cls),
            patch("app.api.v1.shopware_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            api_client.post(
                "/api/v1/auth/shopware/manual",
                headers=headers,
                json={
                    "shop": "my-store.com",
                    "client_id": "SWIA1234567890",
                    "client_secret": "supersecret",
                },
            )

        mock_oauth_store.store_connection.assert_called_once()
        call_kwargs = mock_oauth_store.store_connection.call_args.kwargs
        assert call_kwargs["platform"] == "shopware"
        assert call_kwargs["shop_domain"] == "my-store.com"
        assert call_kwargs["access_token"] == "SWIA1234567890"
        assert call_kwargs["refresh_token"] == "supersecret"

    def test_manual_normalizes_domain(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_client_cls, _ = self._mock_httpx_success()
        mock_oauth_store = AsyncMock()

        with (
            patch("app.api.v1.shopware_auth.httpx.AsyncClient", mock_client_cls),
            patch("app.api.v1.shopware_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            response = api_client.post(
                "/api/v1/auth/shopware/manual",
                headers=headers,
                json={
                    "shop": "https://My-Store.com/",
                    "client_id": "SWIA1234567890",
                    "client_secret": "supersecret",
                },
            )

        assert response.status_code == 200
        assert response.json()["shop"] == "my-store.com"

    def test_manual_failed_verification_returns_400(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_resp = MagicMock()
        mock_resp.status_code = 401
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.api.v1.shopware_auth.httpx.AsyncClient", MagicMock(return_value=mock_client)):
            response = api_client.post(
                "/api/v1/auth/shopware/manual",
                headers=headers,
                json={
                    "shop": "my-store.com",
                    "client_id": "bad-id",
                    "client_secret": "bad-secret",
                },
            )

        assert response.status_code == 400
        assert "credential" in response.json()["detail"].lower() or "invalid" in response.json()["detail"].lower()

    def test_manual_network_error_returns_400(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_client = AsyncMock()
        mock_client.post.side_effect = Exception("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.api.v1.shopware_auth.httpx.AsyncClient", MagicMock(return_value=mock_client)):
            response = api_client.post(
                "/api/v1/auth/shopware/manual",
                headers=headers,
                json={
                    "shop": "my-store.com",
                    "client_id": "SWIA1234567890",
                    "client_secret": "supersecret",
                },
            )

        assert response.status_code == 400

    def test_manual_invalid_domain_returns_400(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.post(
            "/api/v1/auth/shopware/manual",
            headers=headers,
            json={
                "shop": "not-a-domain",
                "client_id": "SWIA1234567890",
                "client_secret": "supersecret",
            },
        )

        assert response.status_code == 400

    def test_manual_empty_client_id_returns_400(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.post(
            "/api/v1/auth/shopware/manual",
            headers=headers,
            json={
                "shop": "my-store.com",
                "client_id": "   ",
                "client_secret": "supersecret",
            },
        )

        assert response.status_code == 400

    def test_manual_empty_client_secret_returns_400(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.post(
            "/api/v1/auth/shopware/manual",
            headers=headers,
            json={
                "shop": "my-store.com",
                "client_id": "SWIA1234567890",
                "client_secret": "   ",
            },
        )

        assert response.status_code == 400

    def test_manual_missing_fields_returns_422(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.post(
            "/api/v1/auth/shopware/manual",
            headers=headers,
            json={"shop": "my-store.com"},
        )

        assert response.status_code == 422

    def test_manual_without_api_key_returns_error(self, api_client: TestClient):
        response = api_client.post(
            "/api/v1/auth/shopware/manual",
            json={
                "shop": "my-store.com",
                "client_id": "SWIA1234567890",
                "client_secret": "supersecret",
            },
        )
        assert response.status_code in (401, 422)

    def test_manual_verifies_against_correct_endpoint(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        """Credentials should be verified by POSTing to /api/oauth/token on the store."""
        mock_client_cls, mock_client = self._mock_httpx_success()
        mock_oauth_store = AsyncMock()

        with (
            patch("app.api.v1.shopware_auth.httpx.AsyncClient", mock_client_cls),
            patch("app.api.v1.shopware_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            api_client.post(
                "/api/v1/auth/shopware/manual",
                headers=headers,
                json={
                    "shop": "my-store.com",
                    "client_id": "SWIA1234567890",
                    "client_secret": "supersecret",
                },
            )

        mock_client.post.assert_called_once()
        call_args = mock_client.post.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert "my-store.com" in url
        assert "/api/oauth/token" in url


# ── Disconnect endpoint ───────────────────────────────────────────────


class TestShopwareDisconnect:
    """Tests for DELETE /api/v1/auth/shopware/disconnect."""

    def test_disconnect_revokes_connection(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_oauth_store = AsyncMock()

        with patch("app.api.v1.shopware_auth._get_oauth_store", return_value=mock_oauth_store):
            response = api_client.delete(
                "/api/v1/auth/shopware/disconnect?shop=my-store.com",
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disconnected"
        assert data["platform"] == "shopware"
        assert data["shop"] == "my-store.com"

        mock_oauth_store.revoke_connection.assert_called_once_with("shopware", "my-store.com")

    def test_disconnect_normalizes_domain(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_oauth_store = AsyncMock()

        with patch("app.api.v1.shopware_auth._get_oauth_store", return_value=mock_oauth_store):
            response = api_client.delete(
                "/api/v1/auth/shopware/disconnect?shop=https://My-Store.com/",
                headers=headers,
            )

        assert response.status_code == 200
        assert response.json()["shop"] == "my-store.com"
        mock_oauth_store.revoke_connection.assert_called_once_with("shopware", "my-store.com")

    def test_disconnect_without_api_key_returns_error(self, api_client: TestClient):
        response = api_client.delete(
            "/api/v1/auth/shopware/disconnect?shop=my-store.com",
        )
        assert response.status_code in (401, 422)

    def test_disconnect_missing_shop_param_returns_422(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.delete(
            "/api/v1/auth/shopware/disconnect",
            headers=headers,
        )
        assert response.status_code == 422

    def test_disconnect_invalid_domain_returns_400(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.delete(
            "/api/v1/auth/shopware/disconnect?shop=not-a-domain",
            headers=headers,
        )
        assert response.status_code == 400
