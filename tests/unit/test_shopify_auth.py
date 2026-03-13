"""Unit tests for Shopify OAuth authentication endpoints."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1.shopify_auth import (
    _pending_nonces,
    _validate_shop_domain,
    _verify_shopify_hmac,
)


# ── HMAC verification ────────────────────────────────────────────────


class TestVerifyShopifyHmac:
    """Tests for _verify_shopify_hmac helper."""

    def test_valid_hmac(self):
        import hashlib
        import hmac as _hmac

        secret = "test-secret"
        params = {"code": "abc123", "shop": "example.myshopify.com", "state": "nonce1"}
        # Build expected message
        message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        expected_hmac = _hmac.new(
            secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
        ).hexdigest()

        query = {**params, "hmac": expected_hmac}
        assert _verify_shopify_hmac(query, secret) is True

    def test_invalid_hmac(self):
        params = {
            "code": "abc123",
            "shop": "example.myshopify.com",
            "state": "nonce1",
            "hmac": "deadbeef0000",
        }
        assert _verify_shopify_hmac(params, "test-secret") is False

    def test_missing_hmac(self):
        params = {"code": "abc123", "shop": "example.myshopify.com"}
        assert _verify_shopify_hmac(params, "test-secret") is False

    def test_empty_hmac(self):
        params = {"code": "abc123", "hmac": ""}
        assert _verify_shopify_hmac(params, "test-secret") is False

    def test_hmac_excluded_from_message(self):
        """The 'hmac' param itself must not be part of the signed message."""
        import hashlib
        import hmac as _hmac

        secret = "s3cret"
        params = {"code": "x", "shop": "store.myshopify.com"}
        message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        computed = _hmac.new(
            secret.encode(), message.encode(), hashlib.sha256
        ).hexdigest()

        # Include hmac in query — should still validate
        query = {**params, "hmac": computed}
        assert _verify_shopify_hmac(query, secret) is True


# ── Shop domain validation ───────────────────────────────────────────


class TestValidateShopDomain:
    """Tests for _validate_shop_domain helper."""

    def test_plain_domain(self):
        assert _validate_shop_domain("example.myshopify.com") == "example.myshopify.com"

    def test_strips_https(self):
        assert _validate_shop_domain("https://example.myshopify.com") == "example.myshopify.com"

    def test_strips_http(self):
        assert _validate_shop_domain("http://example.myshopify.com") == "example.myshopify.com"

    def test_strips_trailing_slash(self):
        assert _validate_shop_domain("example.myshopify.com/") == "example.myshopify.com"

    def test_lowercases(self):
        assert _validate_shop_domain("Example.MyShopify.Com") == "example.myshopify.com"

    def test_strips_whitespace(self):
        assert _validate_shop_domain("  example.myshopify.com  ") == "example.myshopify.com"

    def test_empty_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_shop_domain("")
        assert exc_info.value.status_code == 400

    def test_spaces_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_shop_domain("invalid domain.com")
        assert exc_info.value.status_code == 400

    def test_tabs_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            _validate_shop_domain("invalid\tdomain.com")
        assert exc_info.value.status_code == 400


# ── Connect endpoint ─────────────────────────────────────────────────


class TestShopifyConnect:
    """Tests for GET /api/v1/auth/shopify/connect."""

    def test_connect_returns_auth_url(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        with patch("app.api.v1.shopify_auth.settings") as mock_settings:
            mock_settings.shopify_client_id = "test-client-id"
            mock_settings.shopify_callback_url = "http://localhost:8000/api/v1/auth/shopify/callback"

            response = api_client.get(
                "/api/v1/auth/shopify/connect?shop=example.myshopify.com",
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert "auth_url" in data
        assert "example.myshopify.com" in data["auth_url"]
        assert "client_id=test-client-id" in data["auth_url"]
        assert "scope=read_products" in data["auth_url"]
        assert data["shop"] == "example.myshopify.com"

    def test_connect_generates_nonce(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        _pending_nonces.clear()

        with patch("app.api.v1.shopify_auth.settings") as mock_settings:
            mock_settings.shopify_client_id = "test-client-id"
            mock_settings.shopify_callback_url = "http://localhost:8000/api/v1/auth/shopify/callback"

            response = api_client.get(
                "/api/v1/auth/shopify/connect?shop=example.myshopify.com",
                headers=headers,
            )

        assert response.status_code == 200
        # A nonce should have been stored
        assert len(_pending_nonces) == 1
        nonce = list(_pending_nonces.keys())[0]
        assert _pending_nonces[nonce] == "example.myshopify.com"

        # The auth URL should contain the nonce as state
        data = response.json()
        assert f"state={nonce}" in data["auth_url"]

    def test_connect_missing_credentials_returns_501(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        with patch("app.api.v1.shopify_auth.settings") as mock_settings:
            mock_settings.shopify_client_id = ""

            response = api_client.get(
                "/api/v1/auth/shopify/connect?shop=example.myshopify.com",
                headers=headers,
            )

        assert response.status_code == 501

    def test_connect_without_api_key_returns_error(
        self, api_client: TestClient
    ):
        response = api_client.get(
            "/api/v1/auth/shopify/connect?shop=example.myshopify.com",
        )
        # Should fail auth (422 missing header or 401 invalid key)
        assert response.status_code in (401, 422)

    def test_connect_normalizes_domain(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        with patch("app.api.v1.shopify_auth.settings") as mock_settings:
            mock_settings.shopify_client_id = "test-client-id"
            mock_settings.shopify_callback_url = "http://localhost:8000/api/v1/auth/shopify/callback"

            response = api_client.get(
                "/api/v1/auth/shopify/connect?shop=https://Example.MyShopify.com/",
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["shop"] == "example.myshopify.com"


# ── Callback endpoint ────────────────────────────────────────────────


class TestShopifyCallback:
    """Tests for GET /api/v1/auth/shopify/callback."""

    def _build_valid_callback_params(self, nonce: str, secret: str) -> dict[str, str]:
        """Build callback query params with a valid HMAC."""
        import hashlib
        import hmac as _hmac

        params = {
            "code": "auth_code_123",
            "shop": "example.myshopify.com",
            "state": nonce,
        }
        message = "&".join(f"{k}={v}" for k, v in sorted(params.items()))
        computed_hmac = _hmac.new(
            secret.encode("utf-8"), message.encode("utf-8"), hashlib.sha256
        ).hexdigest()
        params["hmac"] = computed_hmac
        return params

    def test_callback_validates_hmac_and_stores_token(
        self, api_client: TestClient
    ):
        nonce = "test-nonce-abc"
        secret = "test-client-secret"
        _pending_nonces[nonce] = "example.myshopify.com"

        params = self._build_valid_callback_params(nonce, secret)

        mock_oauth_store = AsyncMock()

        with (
            patch("app.api.v1.shopify_auth.settings") as mock_settings,
            patch("app.api.v1.shopify_auth.httpx.AsyncClient") as mock_client_cls,
            patch("app.api.v1.shopify_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            mock_settings.shopify_client_id = "test-client-id"
            mock_settings.shopify_client_secret = secret

            # Mock the token exchange HTTP call
            # Use MagicMock for response since httpx Response.json() is sync
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {
                "access_token": "shpat_returned_token",
                "scope": "read_products",
            }
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            query_string = "&".join(f"{k}={v}" for k, v in params.items())
            response = api_client.get(f"/api/v1/auth/shopify/callback?{query_string}")

        assert response.status_code == 200
        assert "connected successfully" in response.text.lower() or "Connected" in response.text

        # Token should have been stored
        mock_oauth_store.store_connection.assert_called_once_with(
            platform="shopify",
            shop_domain="example.myshopify.com",
            access_token="shpat_returned_token",
            scopes="read_products",
        )

    def test_callback_invalid_hmac_returns_403(
        self, api_client: TestClient
    ):
        nonce = "test-nonce-hmac-fail"
        _pending_nonces[nonce] = "example.myshopify.com"

        params = {
            "code": "auth_code_123",
            "shop": "example.myshopify.com",
            "state": nonce,
            "hmac": "invalid_hmac_value",
        }

        with patch("app.api.v1.shopify_auth.settings") as mock_settings:
            mock_settings.shopify_client_id = "test-client-id"
            mock_settings.shopify_client_secret = "test-secret"

            query_string = "&".join(f"{k}={v}" for k, v in params.items())
            response = api_client.get(f"/api/v1/auth/shopify/callback?{query_string}")

        assert response.status_code == 403

    def test_callback_invalid_state_returns_403(
        self, api_client: TestClient
    ):
        secret = "test-secret"
        # Use a nonce that is NOT in _pending_nonces
        unknown_nonce = "unknown-nonce-xyz"
        _pending_nonces.pop(unknown_nonce, None)  # Ensure not present

        params = self._build_valid_callback_params(unknown_nonce, secret)

        with patch("app.api.v1.shopify_auth.settings") as mock_settings:
            mock_settings.shopify_client_id = "test-client-id"
            mock_settings.shopify_client_secret = secret

            query_string = "&".join(f"{k}={v}" for k, v in params.items())
            response = api_client.get(f"/api/v1/auth/shopify/callback?{query_string}")

        assert response.status_code == 403

    def test_callback_token_exchange_failure_returns_502(
        self, api_client: TestClient
    ):
        nonce = "test-nonce-502"
        secret = "test-secret"
        _pending_nonces[nonce] = "example.myshopify.com"

        params = self._build_valid_callback_params(nonce, secret)

        with (
            patch("app.api.v1.shopify_auth.settings") as mock_settings,
            patch("app.api.v1.shopify_auth.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.shopify_client_id = "test-client-id"
            mock_settings.shopify_client_secret = secret

            # Mock a failed token exchange
            mock_resp = MagicMock()
            mock_resp.status_code = 400
            mock_resp.text = "Bad Request"
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            query_string = "&".join(f"{k}={v}" for k, v in params.items())
            response = api_client.get(f"/api/v1/auth/shopify/callback?{query_string}")

        assert response.status_code == 502

    def test_callback_no_access_token_in_response_returns_502(
        self, api_client: TestClient
    ):
        nonce = "test-nonce-no-token"
        secret = "test-secret"
        _pending_nonces[nonce] = "example.myshopify.com"

        params = self._build_valid_callback_params(nonce, secret)

        with (
            patch("app.api.v1.shopify_auth.settings") as mock_settings,
            patch("app.api.v1.shopify_auth.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_settings.shopify_client_id = "test-client-id"
            mock_settings.shopify_client_secret = secret

            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = {"scope": "read_products"}  # No access_token
            mock_client = AsyncMock()
            mock_client.post.return_value = mock_resp
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            query_string = "&".join(f"{k}={v}" for k, v in params.items())
            response = api_client.get(f"/api/v1/auth/shopify/callback?{query_string}")

        assert response.status_code == 502

    def test_callback_missing_credentials_returns_501(
        self, api_client: TestClient
    ):
        with patch("app.api.v1.shopify_auth.settings") as mock_settings:
            mock_settings.shopify_client_id = ""
            mock_settings.shopify_client_secret = ""

            response = api_client.get(
                "/api/v1/auth/shopify/callback?code=x&shop=example.myshopify.com&state=n&hmac=h"
            )

        assert response.status_code == 501


# ── Disconnect endpoint ──────────────────────────────────────────────


class TestShopifyDisconnect:
    """Tests for DELETE /api/v1/auth/shopify/disconnect."""

    def test_disconnect_revokes_connection(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_oauth_store = AsyncMock()

        with patch("app.api.v1.shopify_auth._get_oauth_store", return_value=mock_oauth_store):
            response = api_client.delete(
                "/api/v1/auth/shopify/disconnect?shop=example.myshopify.com",
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "disconnected"
        assert data["platform"] == "shopify"
        assert data["shop"] == "example.myshopify.com"

        mock_oauth_store.revoke_connection.assert_called_once_with(
            "shopify", "example.myshopify.com"
        )

    def test_disconnect_normalizes_domain(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        mock_oauth_store = AsyncMock()

        with patch("app.api.v1.shopify_auth._get_oauth_store", return_value=mock_oauth_store):
            response = api_client.delete(
                "/api/v1/auth/shopify/disconnect?shop=https://Example.MyShopify.com/",
                headers=headers,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["shop"] == "example.myshopify.com"

    def test_disconnect_without_api_key_returns_error(
        self, api_client: TestClient
    ):
        response = api_client.delete(
            "/api/v1/auth/shopify/disconnect?shop=example.myshopify.com",
        )
        assert response.status_code in (401, 422)
