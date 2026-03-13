"""Unit tests for Magento OAuth authentication endpoints."""

from __future__ import annotations

import base64
import hashlib
import hmac
import time
from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.api.v1.magento_auth import (
    _build_oauth1_header,
    _extract_domain_from_url,
    _pending_nonces,
    _percent_encode,
    _validate_magento_domain,
)


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


# -- Domain extraction from URL -----------------------------------------------


class TestExtractDomainFromUrl:
    """Tests for _extract_domain_from_url helper."""

    def test_full_url(self):
        assert _extract_domain_from_url("https://my-store.com/some/path") == "my-store.com"

    def test_url_with_port(self):
        # Port stays in domain string -- domain validation is separate
        assert _extract_domain_from_url("https://my-store.com:443/path") == "my-store.com:443"

    def test_bare_domain(self):
        assert _extract_domain_from_url("my-store.com") == "my-store.com"

    def test_strips_query_and_fragment(self):
        assert _extract_domain_from_url("https://store.com?q=1#frag") == "store.com"


# -- OAuth 1.0a signature -----------------------------------------------------


class TestOAuth1Signature:
    """Tests for _build_oauth1_header and _percent_encode."""

    def test_percent_encode_simple(self):
        assert _percent_encode("hello") == "hello"

    def test_percent_encode_special_chars(self):
        assert _percent_encode("hello world") == "hello%20world"
        assert _percent_encode("a&b=c") == "a%26b%3Dc"

    def test_percent_encode_preserves_unreserved(self):
        # RFC 3986 unreserved: ALPHA, DIGIT, '-', '.', '_', '~'
        assert _percent_encode("a-b_c.d~e") == "a-b_c.d~e"

    def test_header_starts_with_oauth(self):
        header = _build_oauth1_header(
            method="POST",
            url="https://store.com/oauth/token/request",
            consumer_key="ck123",
            consumer_secret="cs456",
        )
        assert header.startswith("OAuth ")

    def test_header_contains_required_params(self):
        header = _build_oauth1_header(
            method="POST",
            url="https://store.com/oauth/token/request",
            consumer_key="ck123",
            consumer_secret="cs456",
        )
        assert 'oauth_consumer_key="ck123"' in header
        assert "oauth_nonce=" in header
        assert 'oauth_signature_method="HMAC-SHA256"' in header
        assert "oauth_timestamp=" in header
        assert 'oauth_version="1.0"' in header
        assert "oauth_signature=" in header

    def test_header_includes_token_when_provided(self):
        header = _build_oauth1_header(
            method="POST",
            url="https://store.com/oauth/token/access",
            consumer_key="ck123",
            consumer_secret="cs456",
            token="req_token",
            token_secret="req_secret",
            verifier="v789",
        )
        assert 'oauth_token="req_token"' in header
        assert 'oauth_verifier="v789"' in header

    def test_header_excludes_token_when_empty(self):
        header = _build_oauth1_header(
            method="POST",
            url="https://store.com/oauth/token/request",
            consumer_key="ck123",
            consumer_secret="cs456",
        )
        assert "oauth_token=" not in header
        assert "oauth_verifier=" not in header

    def test_nonce_is_unique_each_call(self):
        h1 = _build_oauth1_header("POST", "https://x.com", "k", "s")
        h2 = _build_oauth1_header("POST", "https://x.com", "k", "s")
        # Extract nonce values
        import re
        nonce1 = re.search(r'oauth_nonce="([^"]+)"', h1).group(1)
        nonce2 = re.search(r'oauth_nonce="([^"]+)"', h2).group(1)
        assert nonce1 != nonce2

    def test_timestamp_is_current_epoch(self):
        import re
        before = int(time.time())
        header = _build_oauth1_header("POST", "https://x.com", "k", "s")
        after = int(time.time())
        ts = int(re.search(r'oauth_timestamp="(\d+)"', header).group(1))
        assert before <= ts <= after

    def test_signature_is_valid_base64(self):
        import re
        header = _build_oauth1_header("POST", "https://x.com/path", "k", "s")
        sig = re.search(r'oauth_signature="([^"]+)"', header).group(1)
        # The signature is percent-encoded in the header; decode it first
        from urllib.parse import unquote
        decoded_sig = unquote(sig)
        # Should be valid base64
        raw = base64.b64decode(decoded_sig)
        assert len(raw) == 32  # SHA-256 produces 32 bytes


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

    def test_connect_returns_structured_instructions(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.get(
            "/api/v1/auth/magento/connect?shop=my-store.com",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        instructions = data["instructions"]
        assert isinstance(instructions, list)
        assert len(instructions) >= 5
        assert instructions[0]["step"] == 1
        assert "text" in instructions[0]
        # Should mention Integration somewhere in the steps
        all_text = " ".join(step["text"] for step in instructions)
        assert "integration" in all_text.lower()

    def test_connect_returns_admin_url(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.get(
            "/api/v1/auth/magento/connect?shop=my-store.com",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["admin_url"] == "https://my-store.com/admin"

    def test_connect_returns_callback_and_identity_urls(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        response = api_client.get(
            "/api/v1/auth/magento/connect?shop=my-store.com",
            headers=headers,
        )

        assert response.status_code == 200
        data = response.json()
        # These fields should always be present (may be empty if not configured)
        assert "callback_url" in data
        assert "identity_url" in data

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


class TestMagentoConnectUpdated:
    """Tests for updated /connect with nonce registration and URLs."""

    def test_connect_registers_domain_in_nonce_store(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        _pending_nonces.clear()
        api_client.get(
            "/api/v1/auth/magento/connect?shop=my-store.com",
            headers=headers,
        )
        assert "magento:my-store.com" in _pending_nonces

    def test_connect_returns_callback_url_from_settings(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        with patch("app.api.v1.magento_auth.settings") as mock_settings:
            mock_settings.magento_callback_url = "https://example.com/api/v1/auth/magento/callback"
            mock_settings.magento_identity_url = "https://example.com/api/v1/auth/magento/identity"
            response = api_client.get(
                "/api/v1/auth/magento/connect?shop=my-store.com",
                headers=headers,
            )
        data = response.json()
        assert data["callback_url"] == "https://example.com/api/v1/auth/magento/callback"
        assert data["identity_url"] == "https://example.com/api/v1/auth/magento/identity"

    def test_connect_instructions_mention_callback_url(
        self, api_client: TestClient, headers: dict[str, str]
    ):
        with patch("app.api.v1.magento_auth.settings") as mock_settings:
            mock_settings.magento_callback_url = "https://example.com/callback"
            mock_settings.magento_identity_url = "https://example.com/identity"
            response = api_client.get(
                "/api/v1/auth/magento/connect?shop=my-store.com",
                headers=headers,
            )
        instructions = response.json()["instructions"]
        all_text = " ".join(step["text"] for step in instructions)
        assert "Callback URL" in all_text
        assert "Identity Link URL" in all_text


# -- Callback endpoint --------------------------------------------------------


class TestMagentoCallback:
    """Tests for POST /api/v1/auth/magento/callback."""

    CALLBACK_FORM = {
        "oauth_consumer_key": "consumer_key_123",
        "oauth_consumer_secret": "consumer_secret_456",
        "oauth_verifier": "verifier_789",
        "store_base_url": "https://my-store.com",
    }

    def _register_nonce(self, domain: str = "my-store.com"):
        """Pre-register domain in nonce store (simulates /connect call)."""
        _pending_nonces[f"magento:{domain}"] = domain

    def test_callback_success(
        self, api_client: TestClient
    ):
        """Full successful callback flow: token exchange + verification + storage."""
        self._register_nonce()
        mock_oauth_store = AsyncMock()

        with (
            patch(
                "app.api.v1.magento_auth._exchange_magento_tokens",
                return_value={"access_token": "at_abc", "access_token_secret": "ats_def"},
            ),
            patch(
                "app.api.v1.magento_auth._verify_magento_token",
                return_value=STORE_CONFIGS_RESPONSE,
            ),
            patch("app.api.v1.magento_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            response = api_client.post(
                "/api/v1/auth/magento/callback",
                data=self.CALLBACK_FORM,
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "connected"
        assert data["platform"] == "magento"
        assert data["shop"] == "my-store.com"

    def test_callback_stores_all_credentials(
        self, api_client: TestClient
    ):
        """Verify all credentials are stored correctly in OAuthStore."""
        self._register_nonce()
        mock_oauth_store = AsyncMock()

        with (
            patch(
                "app.api.v1.magento_auth._exchange_magento_tokens",
                return_value={"access_token": "at_abc", "access_token_secret": "ats_def"},
            ),
            patch(
                "app.api.v1.magento_auth._verify_magento_token",
                return_value=STORE_CONFIGS_RESPONSE,
            ),
            patch("app.api.v1.magento_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            api_client.post(
                "/api/v1/auth/magento/callback",
                data=self.CALLBACK_FORM,
            )

        mock_oauth_store.store_connection.assert_called_once()
        kwargs = mock_oauth_store.store_connection.call_args.kwargs
        assert kwargs["platform"] == "magento"
        assert kwargs["shop_domain"] == "my-store.com"
        assert kwargs["access_token"] == "at_abc"
        assert kwargs["access_token_secret"] == "ats_def"
        assert kwargs["scopes"] == "catalog"
        extra = kwargs["extra_data"]
        assert extra["api_type"] == "oauth1"
        assert extra["consumer_key"] == "consumer_key_123"
        assert extra["consumer_secret"] == "consumer_secret_456"
        assert "verified_at" in extra

    def test_callback_extracts_currency(
        self, api_client: TestClient
    ):
        """Currency should be extracted from storeConfigs."""
        self._register_nonce()
        mock_oauth_store = AsyncMock()

        with (
            patch(
                "app.api.v1.magento_auth._exchange_magento_tokens",
                return_value={"access_token": "at", "access_token_secret": "ats"},
            ),
            patch(
                "app.api.v1.magento_auth._verify_magento_token",
                return_value=STORE_CONFIGS_RESPONSE,
            ),
            patch("app.api.v1.magento_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            api_client.post(
                "/api/v1/auth/magento/callback",
                data=self.CALLBACK_FORM,
            )

        extra = mock_oauth_store.store_connection.call_args.kwargs["extra_data"]
        assert extra["currency"] == "EUR"

    def test_callback_missing_consumer_key_returns_400(
        self, api_client: TestClient
    ):
        form = {**self.CALLBACK_FORM}
        del form["oauth_consumer_key"]
        response = api_client.post("/api/v1/auth/magento/callback", data=form)
        assert response.status_code == 400
        assert "missing" in response.json()["detail"].lower()

    def test_callback_missing_verifier_returns_400(
        self, api_client: TestClient
    ):
        form = {**self.CALLBACK_FORM}
        del form["oauth_verifier"]
        response = api_client.post("/api/v1/auth/magento/callback", data=form)
        assert response.status_code == 400

    def test_callback_missing_store_base_url_returns_400(
        self, api_client: TestClient
    ):
        form = {**self.CALLBACK_FORM}
        del form["store_base_url"]
        response = api_client.post("/api/v1/auth/magento/callback", data=form)
        assert response.status_code == 400
        assert "store_base_url" in response.json()["detail"]

    def test_callback_unknown_domain_returns_403(
        self, api_client: TestClient
    ):
        """Domain not registered via /connect should be rejected."""
        _pending_nonces.clear()
        response = api_client.post(
            "/api/v1/auth/magento/callback",
            data=self.CALLBACK_FORM,
        )
        assert response.status_code == 403
        assert "unknown domain" in response.json()["detail"].lower()

    def test_callback_token_exchange_failure_returns_502(
        self, api_client: TestClient
    ):
        """If request token or access token exchange fails, return 502."""
        self._register_nonce()

        with patch(
            "app.api.v1.magento_auth._exchange_magento_tokens",
            return_value=None,
        ):
            response = api_client.post(
                "/api/v1/auth/magento/callback",
                data=self.CALLBACK_FORM,
            )

        assert response.status_code == 502
        assert "exchange" in response.json()["detail"].lower()

    def test_callback_verification_failure_returns_400(
        self, api_client: TestClient
    ):
        """If token works for exchange but fails storeConfigs verification."""
        self._register_nonce()

        with (
            patch(
                "app.api.v1.magento_auth._exchange_magento_tokens",
                return_value={"access_token": "at", "access_token_secret": "ats"},
            ),
            patch(
                "app.api.v1.magento_auth._verify_magento_token",
                return_value=None,
            ),
        ):
            response = api_client.post(
                "/api/v1/auth/magento/callback",
                data=self.CALLBACK_FORM,
            )

        assert response.status_code == 400
        assert "verification failed" in response.json()["detail"].lower()

    def test_callback_extracts_domain_from_url_correctly(
        self, api_client: TestClient
    ):
        """Domain should be extracted from store_base_url properly."""
        self._register_nonce("shop.example.com")
        mock_oauth_store = AsyncMock()

        form = {
            **self.CALLBACK_FORM,
            "store_base_url": "https://shop.example.com/magento",
        }

        with (
            patch(
                "app.api.v1.magento_auth._exchange_magento_tokens",
                return_value={"access_token": "at", "access_token_secret": "ats"},
            ),
            patch(
                "app.api.v1.magento_auth._verify_magento_token",
                return_value=STORE_CONFIGS_RESPONSE,
            ),
            patch("app.api.v1.magento_auth._get_oauth_store", return_value=mock_oauth_store),
        ):
            response = api_client.post(
                "/api/v1/auth/magento/callback",
                data=form,
            )

        assert response.status_code == 200
        assert response.json()["shop"] == "shop.example.com"

    def test_callback_does_not_require_api_key(
        self, api_client: TestClient
    ):
        """Callback is called by Magento, not our frontend -- no API key needed."""
        self._register_nonce()

        with (
            patch(
                "app.api.v1.magento_auth._exchange_magento_tokens",
                return_value={"access_token": "at", "access_token_secret": "ats"},
            ),
            patch(
                "app.api.v1.magento_auth._verify_magento_token",
                return_value=STORE_CONFIGS_RESPONSE,
            ),
            patch("app.api.v1.magento_auth._get_oauth_store", return_value=AsyncMock()),
        ):
            # No headers (no API key)
            response = api_client.post(
                "/api/v1/auth/magento/callback",
                data=self.CALLBACK_FORM,
            )

        assert response.status_code == 200


# -- Identity endpoint --------------------------------------------------------


class TestMagentoIdentity:
    """Tests for GET /api/v1/auth/magento/identity."""

    def test_identity_returns_200(self, api_client: TestClient):
        response = api_client.get("/api/v1/auth/magento/identity")
        assert response.status_code == 200

    def test_identity_returns_html(self, api_client: TestClient):
        response = api_client.get("/api/v1/auth/magento/identity")
        assert "text/html" in response.headers.get("content-type", "")
        assert "Identity" in response.text or "identity" in response.text

    def test_identity_does_not_require_api_key(self, api_client: TestClient):
        # No API key header
        response = api_client.get("/api/v1/auth/magento/identity")
        assert response.status_code == 200


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
