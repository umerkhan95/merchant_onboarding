"""Unit tests for Magento OAuth authentication endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1.magento_auth import _validate_magento_domain


STORE_CONFIGS_RESPONSE = [
    {
        "id": 1,
        "code": "default",
        "website_id": 1,
        "locale": "en_US",
        "base_currency_code": "EUR",
        "default_display_currency_code": "EUR",
        "weight_unit": "kgs",
    }
]


# -- Domain validation --------------------------------------------------------


class TestValidateMagentoDomain:
    """Tests for _validate_magento_domain helper."""

    def test_plain_domain(self):
        assert _validate_magento_domain("my-store.com") == "my-store.com"

    def test_strips_https(self):
        assert _validate_magento_domain("https://my-store.com") == "my-store.com"

    def test_strips_http(self):
        assert _validate_magento_domain("http://my-store.com") == "my-store.com"

    def test_strips_trailing_slash(self):
        assert _validate_magento_domain("my-store.com/") == "my-store.com"

    def test_lowercases(self):
        assert _validate_magento_domain("My-Store.COM") == "my-store.com"

    def test_strips_whitespace(self):
        assert _validate_magento_domain("  my-store.com  ") == "my-store.com"

    def test_subdomain(self):
        assert _validate_magento_domain("shop.example.co.uk") == "shop.example.co.uk"

    def test_hyphenated_domain(self):
        assert _validate_magento_domain("my-cool-store.com") == "my-cool-store.com"

    def test_empty_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_magento_domain("")
        assert exc_info.value.status_code == 400
        assert "required" in exc_info.value.detail.lower()

    def test_whitespace_only_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_magento_domain("   ")
        assert exc_info.value.status_code == 400

    def test_no_tld_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_magento_domain("localhost")
        assert exc_info.value.status_code == 400

    def test_invalid_characters_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_magento_domain("invalid domain.com")
        assert exc_info.value.status_code == 400

    def test_invalid_detail_message(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_magento_domain("not-a-domain")
        assert exc_info.value.status_code == 400
        assert "invalid" in exc_info.value.detail.lower()


# -- Connect endpoint ---------------------------------------------------------


class TestMagentoConnect:
    """Tests for GET /api/v1/auth/magento/connect."""

    def test_connect_returns_instructions(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.get(
            "/api/v1/auth/magento/connect?shop=my-store.com",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["platform"] == "magento"
        assert data["shop"] == "my-store.com"
        assert "instructions" in data
        assert "manual_url" in data
        assert "/api/v1/auth/magento/manual" in data["manual_url"]

    def test_connect_instructions_mention_integration(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.get(
            "/api/v1/auth/magento/connect?shop=my-store.com",
            headers=headers,
        )

        assert response.status_code == 200
        instructions = response.json()["instructions"]
        assert "Integration" in instructions or "integration" in instructions

    def test_connect_normalizes_domain(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.get(
            "/api/v1/auth/magento/connect?shop=https://My-Store.com/",
            headers=headers,
        )

        assert response.status_code == 200
        assert response.json()["shop"] == "my-store.com"

    def test_connect_invalid_domain_returns_400(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.get(
            "/api/v1/auth/magento/connect?shop=not-valid",
            headers=headers,
        )

        assert response.status_code == 400

    def test_connect_without_api_key_returns_error(self, api_client: TestClient):
        response = api_client.get(
            "/api/v1/auth/magento/connect?shop=my-store.com",
        )
        assert response.status_code in (401, 422)

    def test_connect_missing_shop_param_returns_422(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.get(
            "/api/v1/auth/magento/connect",
            headers=headers,
        )
        assert response.status_code == 422


# -- Manual endpoint -----------------------------------------------------------


class TestMagentoManual:
    """Tests for POST /api/v1/auth/magento/manual."""

    def _mock_httpx_success(self) -> tuple[MagicMock, MagicMock]:
        """Return (mock_client_cls, mock_client) configured for successful storeConfigs response."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = STORE_CONFIGS_RESPONSE
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_client_cls = MagicMock(return_value=mock_client)
        return mock_client_cls, mock_client

    def test_manual_success_stores_token(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_client_cls, _ = self._mock_httpx_success()
        mock_oauth_store = AsyncMock()

        with (
            patch("app.api.v1.magento_auth.httpx.AsyncClient", mock_client_cls),
            patch("app.api.v1.magento_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            response = api_client.post(
                "/api/v1/auth/magento/manual",
                headers=headers,
                json={
                    "shop": "my-store.com",
                    "access_token": "mag-token-abc123",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert data["platform"] == "magento"
        assert data["shop"] == "my-store.com"

    def test_manual_success_calls_store_connection(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_client_cls, _ = self._mock_httpx_success()
        mock_oauth_store = AsyncMock()

        with (
            patch("app.api.v1.magento_auth.httpx.AsyncClient", mock_client_cls),
            patch("app.api.v1.magento_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            api_client.post(
                "/api/v1/auth/magento/manual",
                headers=headers,
                json={
                    "shop": "my-store.com",
                    "access_token": "mag-token-abc123",
                },
            )

        mock_oauth_store.store_connection.assert_called_once()
        call_kwargs = mock_oauth_store.store_connection.call_args.kwargs
        assert call_kwargs["platform"] == "magento"
        assert call_kwargs["shop_domain"] == "my-store.com"
        assert call_kwargs["access_token"] == "mag-token-abc123"
        assert call_kwargs["refresh_token"] is None
        assert call_kwargs["scopes"] == "catalog"

    def test_manual_extracts_currency_from_store_configs(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_client_cls, _ = self._mock_httpx_success()
        mock_oauth_store = AsyncMock()

        with (
            patch("app.api.v1.magento_auth.httpx.AsyncClient", mock_client_cls),
            patch("app.api.v1.magento_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            api_client.post(
                "/api/v1/auth/magento/manual",
                headers=headers,
                json={
                    "shop": "my-store.com",
                    "access_token": "mag-token-abc123",
                },
            )

        call_kwargs = mock_oauth_store.store_connection.call_args.kwargs
        extra_data = call_kwargs["extra_data"]
        assert extra_data["currency"] == "EUR"
        assert extra_data["api_type"] == "integration"
        assert "verified_at" in extra_data

    def test_manual_handles_store_configs_without_currency(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        """storeConfigs might not include base_currency_code."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = [{"id": 1, "code": "default"}]
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls = MagicMock(return_value=mock_client)

        mock_oauth_store = AsyncMock()

        with (
            patch("app.api.v1.magento_auth.httpx.AsyncClient", mock_client_cls),
            patch("app.api.v1.magento_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            response = api_client.post(
                "/api/v1/auth/magento/manual",
                headers=headers,
                json={
                    "shop": "my-store.com",
                    "access_token": "mag-token-abc123",
                },
            )

        assert response.status_code == 200
        call_kwargs = mock_oauth_store.store_connection.call_args.kwargs
        assert call_kwargs["extra_data"]["currency"] is None

    def test_manual_handles_empty_store_configs(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        """storeConfigs might return an empty list."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = []
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls = MagicMock(return_value=mock_client)

        mock_oauth_store = AsyncMock()

        with (
            patch("app.api.v1.magento_auth.httpx.AsyncClient", mock_client_cls),
            patch("app.api.v1.magento_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            response = api_client.post(
                "/api/v1/auth/magento/manual",
                headers=headers,
                json={
                    "shop": "my-store.com",
                    "access_token": "mag-token-abc123",
                },
            )

        assert response.status_code == 200
        call_kwargs = mock_oauth_store.store_connection.call_args.kwargs
        assert call_kwargs["extra_data"]["currency"] is None

    def test_manual_normalizes_domain(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_client_cls, _ = self._mock_httpx_success()
        mock_oauth_store = AsyncMock()

        with (
            patch("app.api.v1.magento_auth.httpx.AsyncClient", mock_client_cls),
            patch("app.api.v1.magento_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            response = api_client.post(
                "/api/v1/auth/magento/manual",
                headers=headers,
                json={
                    "shop": "https://My-Store.com/",
                    "access_token": "mag-token-abc123",
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
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.api.v1.magento_auth.httpx.AsyncClient", MagicMock(return_value=mock_client)):
            response = api_client.post(
                "/api/v1/auth/magento/manual",
                headers=headers,
                json={
                    "shop": "my-store.com",
                    "access_token": "bad-token",
                },
            )

        assert response.status_code == 400
        assert "invalid" in response.json()["detail"].lower() or "access token" in response.json()["detail"].lower()

    def test_manual_network_error_returns_400(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("app.api.v1.magento_auth.httpx.AsyncClient", MagicMock(return_value=mock_client)):
            response = api_client.post(
                "/api/v1/auth/magento/manual",
                headers=headers,
                json={
                    "shop": "my-store.com",
                    "access_token": "mag-token-abc123",
                },
            )

        assert response.status_code == 400

    def test_manual_invalid_domain_returns_400(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.post(
            "/api/v1/auth/magento/manual",
            headers=headers,
            json={
                "shop": "not-a-domain",
                "access_token": "mag-token-abc123",
            },
        )

        assert response.status_code == 400

    def test_manual_empty_access_token_returns_400(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.post(
            "/api/v1/auth/magento/manual",
            headers=headers,
            json={
                "shop": "my-store.com",
                "access_token": "   ",
            },
        )

        assert response.status_code == 400

    def test_manual_empty_shop_returns_400(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.post(
            "/api/v1/auth/magento/manual",
            headers=headers,
            json={
                "shop": "",
                "access_token": "mag-token-abc123",
            },
        )

        assert response.status_code == 400

    def test_manual_missing_fields_returns_422(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.post(
            "/api/v1/auth/magento/manual",
            headers=headers,
            json={"shop": "my-store.com"},
        )

        assert response.status_code == 422

    def test_manual_without_api_key_returns_error(self, api_client: TestClient):
        response = api_client.post(
            "/api/v1/auth/magento/manual",
            json={
                "shop": "my-store.com",
                "access_token": "mag-token-abc123",
            },
        )
        assert response.status_code in (401, 422)

    def test_manual_verifies_against_correct_endpoint(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        """Token should be verified by GETting /rest/V1/store/storeConfigs on the store."""
        mock_client_cls, mock_client = self._mock_httpx_success()
        mock_oauth_store = AsyncMock()

        with (
            patch("app.api.v1.magento_auth.httpx.AsyncClient", mock_client_cls),
            patch("app.api.v1.magento_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            api_client.post(
                "/api/v1/auth/magento/manual",
                headers=headers,
                json={
                    "shop": "my-store.com",
                    "access_token": "mag-token-abc123",
                },
            )

        mock_client.get.assert_called_once()
        call_args = mock_client.get.call_args
        url = call_args.args[0] if call_args.args else call_args.kwargs.get("url", "")
        assert "my-store.com" in url
        assert "/rest/V1/store/storeConfigs" in url


# -- Disconnect endpoint -------------------------------------------------------


class TestMagentoDisconnect:
    """Tests for DELETE /api/v1/auth/magento/disconnect."""

    def test_disconnect_revokes_connection(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_oauth_store = AsyncMock()

        with patch("app.api.v1.magento_auth._get_oauth_store", return_value=mock_oauth_store):
            response = api_client.delete(
                "/api/v1/auth/magento/disconnect?shop=my-store.com",
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disconnected"
        assert data["platform"] == "magento"
        assert data["shop"] == "my-store.com"

        mock_oauth_store.revoke_connection.assert_called_once_with("magento", "my-store.com")

    def test_disconnect_normalizes_domain(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_oauth_store = AsyncMock()

        with patch("app.api.v1.magento_auth._get_oauth_store", return_value=mock_oauth_store):
            response = api_client.delete(
                "/api/v1/auth/magento/disconnect?shop=https://My-Store.com/",
                headers=headers,
            )

        assert response.status_code == 200
        assert response.json()["shop"] == "my-store.com"
        mock_oauth_store.revoke_connection.assert_called_once_with("magento", "my-store.com")

    def test_disconnect_without_api_key_returns_error(self, api_client: TestClient):
        response = api_client.delete(
            "/api/v1/auth/magento/disconnect?shop=my-store.com",
        )
        assert response.status_code in (401, 422)

    def test_disconnect_missing_shop_param_returns_422(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.delete(
            "/api/v1/auth/magento/disconnect",
            headers=headers,
        )
        assert response.status_code == 422

    def test_disconnect_invalid_domain_returns_400(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.delete(
            "/api/v1/auth/magento/disconnect?shop=not-a-domain",
            headers=headers,
        )
        assert response.status_code == 400
