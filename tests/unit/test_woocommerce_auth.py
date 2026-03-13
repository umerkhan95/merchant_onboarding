"""Unit tests for WooCommerce OAuth authentication endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1.woocommerce_auth import (
    _pending_nonces,
    _validate_wc_domain,
)


# ── Domain validation ────────────────────────────────────────────────


class TestValidateWcDomain:
    """Tests for _validate_wc_domain helper."""

    def test_plain_domain(self):
        assert _validate_wc_domain("my-store.com") == "my-store.com"

    def test_subdomain(self):
        assert _validate_wc_domain("shop.example.com") == "shop.example.com"

    def test_strips_https(self):
        assert _validate_wc_domain("https://my-store.com") == "my-store.com"

    def test_strips_http(self):
        assert _validate_wc_domain("http://my-store.com") == "my-store.com"

    def test_strips_trailing_slash(self):
        assert _validate_wc_domain("my-store.com/") == "my-store.com"

    def test_lowercases(self):
        assert _validate_wc_domain("My-Store.COM") == "my-store.com"

    def test_strips_whitespace(self):
        assert _validate_wc_domain("  my-store.com  ") == "my-store.com"

    def test_empty_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_wc_domain("")
        assert exc_info.value.status_code == 400

    def test_no_tld_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_wc_domain("localhost")
        assert exc_info.value.status_code == 400

    def test_ip_address_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_wc_domain("192.168.1.1")
        assert exc_info.value.status_code == 400

    def test_spaces_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_wc_domain("invalid domain.com")
        assert exc_info.value.status_code == 400

    def test_german_domain(self):
        assert _validate_wc_domain("mein-shop.de") == "mein-shop.de"

    def test_co_uk_domain(self):
        assert _validate_wc_domain("shop.co.uk") == "shop.co.uk"


# ── Connect endpoint ─────────────────────────────────────────────────


class TestWooCommerceConnect:
    """Tests for GET /api/v1/auth/woocommerce/connect."""

    def test_connect_returns_auth_url(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        with patch("app.api.v1.woocommerce_auth.settings") as mock_settings:
            mock_settings.woocommerce_callback_url = "https://example.com/callback"
            mock_settings.woocommerce_return_url = "https://example.com/return"
            mock_settings.woocommerce_app_name = "Test App"

            response = api_client.get(
                "/api/v1/auth/woocommerce/connect?shop=my-store.com",
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert "auth_url" in data
        assert "my-store.com/wc-auth/v1/authorize" in data["auth_url"]
        assert "app_name=Test+App" in data["auth_url"]
        assert "scope=read" in data["auth_url"]
        assert data["shop"] == "my-store.com"

    def test_connect_generates_nonce(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        _pending_nonces.clear()

        with patch("app.api.v1.woocommerce_auth.settings") as mock_settings:
            mock_settings.woocommerce_callback_url = "https://example.com/callback"
            mock_settings.woocommerce_return_url = "https://example.com/return"
            mock_settings.woocommerce_app_name = "Test App"

            response = api_client.get(
                "/api/v1/auth/woocommerce/connect?shop=my-store.com",
                headers=headers,
            )

        assert response.status_code == 200
        assert len(_pending_nonces) == 1
        nonce = list(_pending_nonces.keys())[0]
        assert _pending_nonces[nonce] == "my-store.com"

        # The auth URL should contain the nonce as user_id
        data = response.json()
        assert f"user_id={nonce}" in data["auth_url"]

    def test_connect_not_configured_returns_501(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        with patch("app.api.v1.woocommerce_auth.settings") as mock_settings:
            mock_settings.woocommerce_callback_url = ""

            response = api_client.get(
                "/api/v1/auth/woocommerce/connect?shop=my-store.com",
                headers=headers,
            )

        assert response.status_code == 501

    def test_connect_normalizes_domain(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        with patch("app.api.v1.woocommerce_auth.settings") as mock_settings:
            mock_settings.woocommerce_callback_url = "https://example.com/callback"
            mock_settings.woocommerce_return_url = "https://example.com/return"
            mock_settings.woocommerce_app_name = "Test App"

            response = api_client.get(
                "/api/v1/auth/woocommerce/connect?shop=https://My-Store.COM/",
                headers=headers,
            )

        assert response.status_code == 200
        assert response.json()["shop"] == "my-store.com"

    def test_connect_requires_api_key(self, api_client: TestClient):
        response = api_client.get(
            "/api/v1/auth/woocommerce/connect?shop=my-store.com",
        )
        assert response.status_code in (401, 422)


# ── Callback endpoint ────────────────────────────────────────────────


class TestWooCommerceCallback:
    """Tests for POST /api/v1/auth/woocommerce/callback."""

    def test_callback_stores_credentials(self, api_client: TestClient):
        nonce = "test-nonce-wc"
        _pending_nonces[nonce] = "my-store.com"

        mock_oauth_store = AsyncMock()

        with (
            patch("app.api.v1.woocommerce_auth._get_oauth_store", return_value=mock_oauth_store),
            patch("app.api.v1.woocommerce_auth._verify_wc_credentials", return_value=True),
        ):
            response = api_client.post(
                "/api/v1/auth/woocommerce/callback",
                json={
                    "key_id": 1,
                    "user_id": nonce,
                    "consumer_key": "ck_test_key_123",
                    "consumer_secret": "cs_test_secret_456",
                    "key_permissions": "read",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert data["platform"] == "woocommerce"
        assert data["shop"] == "my-store.com"

        mock_oauth_store.store_connection.assert_called_once_with(
            platform="woocommerce",
            shop_domain="my-store.com",
            consumer_key="ck_test_key_123",
            consumer_secret="cs_test_secret_456",
            scopes="read",
        )

    def test_callback_invalid_nonce_returns_403(self, api_client: TestClient):
        _pending_nonces.clear()

        with patch("app.api.v1.woocommerce_auth._verify_wc_credentials", return_value=True):
            response = api_client.post(
                "/api/v1/auth/woocommerce/callback",
                json={
                    "key_id": 1,
                    "user_id": "unknown-nonce",
                    "consumer_key": "ck_test",
                    "consumer_secret": "cs_test",
                    "key_permissions": "read",
                },
            )

        assert response.status_code == 403

    def test_callback_missing_credentials_returns_400(self, api_client: TestClient):
        nonce = "test-nonce-missing"
        _pending_nonces[nonce] = "my-store.com"

        response = api_client.post(
            "/api/v1/auth/woocommerce/callback",
            json={
                "key_id": 1,
                "user_id": nonce,
                "consumer_key": "",
                "consumer_secret": "",
                "key_permissions": "read",
            },
        )

        assert response.status_code == 400

    def test_callback_invalid_key_format_returns_400(self, api_client: TestClient):
        nonce = "test-nonce-format"
        _pending_nonces[nonce] = "my-store.com"

        response = api_client.post(
            "/api/v1/auth/woocommerce/callback",
            json={
                "key_id": 1,
                "user_id": nonce,
                "consumer_key": "invalid_key",
                "consumer_secret": "cs_valid",
                "key_permissions": "read",
            },
        )

        assert response.status_code == 400

    def test_callback_verification_failure_returns_502(self, api_client: TestClient):
        nonce = "test-nonce-verify-fail"
        _pending_nonces[nonce] = "my-store.com"

        with patch("app.api.v1.woocommerce_auth._verify_wc_credentials", return_value=False):
            response = api_client.post(
                "/api/v1/auth/woocommerce/callback",
                json={
                    "key_id": 1,
                    "user_id": nonce,
                    "consumer_key": "ck_test_key",
                    "consumer_secret": "cs_test_secret",
                    "key_permissions": "read",
                },
            )

        assert response.status_code == 502

    def test_callback_consumes_nonce(self, api_client: TestClient):
        """Nonce should be consumed after callback to prevent replay."""
        nonce = "test-nonce-consumed"
        _pending_nonces[nonce] = "my-store.com"

        mock_oauth_store = AsyncMock()

        with (
            patch("app.api.v1.woocommerce_auth._get_oauth_store", return_value=mock_oauth_store),
            patch("app.api.v1.woocommerce_auth._verify_wc_credentials", return_value=True),
        ):
            response = api_client.post(
                "/api/v1/auth/woocommerce/callback",
                json={
                    "key_id": 1,
                    "user_id": nonce,
                    "consumer_key": "ck_test",
                    "consumer_secret": "cs_test",
                    "key_permissions": "read",
                },
            )

        assert response.status_code == 200
        # Nonce should be consumed
        assert nonce not in _pending_nonces


# ── Return endpoint ──────────────────────────────────────────────────


class TestWooCommerceReturn:
    """Tests for GET /api/v1/auth/woocommerce/return."""

    def test_return_success_page(self, api_client: TestClient):
        response = api_client.get(
            "/api/v1/auth/woocommerce/return?success=1&user_id=test-nonce",
        )

        assert response.status_code == 200
        assert "connected successfully" in response.text.lower()
        assert "woocommerce_oauth_complete" in response.text

    def test_return_failure_page(self, api_client: TestClient):
        response = api_client.get(
            "/api/v1/auth/woocommerce/return?success=0&user_id=test-nonce",
        )

        assert response.status_code == 200
        assert "not completed" in response.text.lower()

    def test_return_no_params(self, api_client: TestClient):
        response = api_client.get("/api/v1/auth/woocommerce/return")

        assert response.status_code == 200
        # No success param → failure page
        assert "not completed" in response.text.lower()


# ── Manual key input ─────────────────────────────────────────────────


class TestWooCommerceManual:
    """Tests for POST /api/v1/auth/woocommerce/manual."""

    def test_manual_stores_valid_credentials(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_oauth_store = AsyncMock()

        with (
            patch("app.api.v1.woocommerce_auth._get_oauth_store", return_value=mock_oauth_store),
            patch("app.api.v1.woocommerce_auth._verify_wc_credentials", return_value=True),
        ):
            response = api_client.post(
                "/api/v1/auth/woocommerce/manual",
                headers=headers,
                json={
                    "shop": "my-store.com",
                    "consumer_key": "ck_abc123",
                    "consumer_secret": "cs_xyz789",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert data["platform"] == "woocommerce"

        mock_oauth_store.store_connection.assert_called_once_with(
            platform="woocommerce",
            shop_domain="my-store.com",
            consumer_key="ck_abc123",
            consumer_secret="cs_xyz789",
            scopes="read",
        )

    def test_manual_invalid_key_format_returns_400(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.post(
            "/api/v1/auth/woocommerce/manual",
            headers=headers,
            json={
                "shop": "my-store.com",
                "consumer_key": "invalid_key",
                "consumer_secret": "cs_valid",
            },
        )

        assert response.status_code == 400

    def test_manual_verification_failure_returns_400(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        with patch("app.api.v1.woocommerce_auth._verify_wc_credentials", return_value=False):
            response = api_client.post(
                "/api/v1/auth/woocommerce/manual",
                headers=headers,
                json={
                    "shop": "my-store.com",
                    "consumer_key": "ck_abc123",
                    "consumer_secret": "cs_xyz789",
                },
            )

        assert response.status_code == 400

    def test_manual_requires_api_key(self, api_client: TestClient):
        response = api_client.post(
            "/api/v1/auth/woocommerce/manual",
            json={
                "shop": "my-store.com",
                "consumer_key": "ck_abc",
                "consumer_secret": "cs_xyz",
            },
        )
        assert response.status_code in (401, 422)


# ── Disconnect endpoint ──────────────────────────────────────────────


class TestWooCommerceDisconnect:
    """Tests for DELETE /api/v1/auth/woocommerce/disconnect."""

    def test_disconnect_revokes_connection(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_oauth_store = AsyncMock()

        with patch("app.api.v1.woocommerce_auth._get_oauth_store", return_value=mock_oauth_store):
            response = api_client.delete(
                "/api/v1/auth/woocommerce/disconnect?shop=my-store.com",
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disconnected"
        assert data["platform"] == "woocommerce"

        mock_oauth_store.revoke_connection.assert_called_once_with(
            "woocommerce", "my-store.com"
        )

    def test_disconnect_requires_api_key(self, api_client: TestClient):
        response = api_client.delete(
            "/api/v1/auth/woocommerce/disconnect?shop=my-store.com",
        )
        assert response.status_code in (401, 422)
