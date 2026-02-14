"""Unit tests for the security layer: URL validator, HTML sanitizer, API key auth."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.security.api_key import verify_api_key
from app.security.html_sanitizer import HTMLSanitizer
from app.security.url_validator import URLValidator

# ---------------------------------------------------------------------------
# URLValidator tests
# ---------------------------------------------------------------------------


class TestURLValidatorPrivateIPs:
    """URLValidator must reject URLs that resolve to private/internal IPs."""

    @pytest.mark.parametrize(
        ("ip", "label"),
        [
            ("127.0.0.1", "loopback"),
            ("10.0.0.1", "10.x private"),
            ("169.254.169.254", "link-local / cloud metadata"),
            ("192.168.1.1", "192.168 private"),
            ("172.16.0.1", "172.16 private"),
        ],
    )
    def test_private_ip_rejected(self, ip: str, label: str) -> None:
        """Private IP {label} ({ip}) must be rejected."""
        # Patch DNS resolution so the hostname resolves to the target private IP.
        fake_addrinfo = [(2, 1, 6, "", (ip, 0))]
        with patch("app.security.url_validator.socket.getaddrinfo", return_value=fake_addrinfo):
            valid, reason = URLValidator.validate(f"https://{ip}")
            assert valid is False, f"Expected False for {label} ({ip}), got True"
            assert "private" in reason.lower() or "private" in reason


class TestURLValidatorValidURLs:
    """URLValidator must accept well-formed external URLs."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.allbirds.com",
            "https://example.com",
            "http://shop.example.org/products",
        ],
    )
    def test_valid_url_accepted(self, url: str) -> None:
        # Patch DNS to return a public IP (93.184.216.34 = example.com).
        fake_addrinfo = [(2, 1, 6, "", ("93.184.216.34", 0))]
        with patch("app.security.url_validator.socket.getaddrinfo", return_value=fake_addrinfo):
            valid, reason = URLValidator.validate(url)
            assert valid is True
            assert reason == "Valid"


class TestURLValidatorScheme:
    """URLValidator must reject non-http/https schemes."""

    @pytest.mark.parametrize("scheme", ["ftp", "file", "gopher", "data", "javascript"])
    def test_disallowed_scheme_rejected(self, scheme: str) -> None:
        valid, reason = URLValidator.validate(f"{scheme}://example.com")
        assert valid is False
        assert "not allowed" in reason.lower() or "scheme" in reason.lower()


class TestURLValidatorPorts:
    """URLValidator must block dangerous ports."""

    @pytest.mark.parametrize("port", [22, 25, 445, 3389, 5432, 27017])
    def test_dangerous_port_rejected(self, port: int) -> None:
        fake_addrinfo = [(2, 1, 6, "", ("93.184.216.34", 0))]
        with patch("app.security.url_validator.socket.getaddrinfo", return_value=fake_addrinfo):
            valid, reason = URLValidator.validate(f"https://example.com:{port}/path")
            assert valid is False
            assert "blocked" in reason.lower() or "port" in reason.lower()

    def test_standard_port_allowed(self) -> None:
        fake_addrinfo = [(2, 1, 6, "", ("93.184.216.34", 0))]
        with patch("app.security.url_validator.socket.getaddrinfo", return_value=fake_addrinfo):
            valid, _reason = URLValidator.validate("https://example.com:443/path")
            assert valid is True


class TestURLValidatorHostname:
    """URLValidator must reject URLs with empty hostnames."""

    def test_empty_hostname_rejected(self) -> None:
        valid, reason = URLValidator.validate("https:///path")
        assert valid is False
        assert "empty" in reason.lower() or "hostname" in reason.lower()


class TestURLValidatorDNSFailure:
    """URLValidator must reject URLs whose hostname cannot be resolved."""

    def test_unresolvable_hostname(self) -> None:
        import socket

        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            side_effect=socket.gaierror("Name or service not known"),
        ):
            valid, reason = URLValidator.validate("https://does-not-exist.invalid")
            assert valid is False
            assert "resolve" in reason.lower()


# ---------------------------------------------------------------------------
# HTMLSanitizer tests
# ---------------------------------------------------------------------------


class TestHTMLSanitizerScriptTags:
    """HTMLSanitizer must strip script tags and their contents."""

    def test_strips_script_tag(self) -> None:
        dirty = '<p>Hello</p><script>alert("xss")</script>'
        clean = HTMLSanitizer.sanitize(dirty)
        assert "<script" not in clean
        assert "alert" not in clean
        assert "<p>Hello</p>" in clean

    def test_strips_nested_script(self) -> None:
        dirty = '<div><script type="text/javascript">document.cookie</script></div>'
        clean = HTMLSanitizer.sanitize(dirty)
        assert "<script" not in clean
        assert "document.cookie" not in clean


class TestHTMLSanitizerAllowedTags:
    """HTMLSanitizer must preserve allowed tags."""

    @pytest.mark.parametrize(
        "tag",
        ["p", "br", "strong", "em", "h1", "h2", "h3", "ul", "ol", "li", "span", "div"],
    )
    def test_allowed_tag_preserved(self, tag: str) -> None:
        html = f"text<{tag}>more" if tag == "br" else f"<{tag}>content</{tag}>"
        clean = HTMLSanitizer.sanitize(html)
        assert f"<{tag}" in clean

    def test_anchor_with_allowed_attributes(self) -> None:
        html = '<a href="https://example.com" title="Example">link</a>'
        clean = HTMLSanitizer.sanitize(html)
        assert 'href="https://example.com"' in clean
        assert 'title="Example"' in clean

    def test_anchor_strips_disallowed_attributes(self) -> None:
        html = '<a href="https://example.com" onclick="evil()">link</a>'
        clean = HTMLSanitizer.sanitize(html)
        assert "onclick" not in clean
        assert 'href="https://example.com"' in clean


class TestHTMLSanitizerEventHandlers:
    """HTMLSanitizer must strip event handler attributes."""

    @pytest.mark.parametrize(
        "handler",
        ["onclick", "onmouseover", "onload", "onerror", "onfocus"],
    )
    def test_event_handler_stripped(self, handler: str) -> None:
        html = f'<div {handler}="alert(1)">content</div>'
        clean = HTMLSanitizer.sanitize(html)
        assert handler not in clean
        assert "<div>content</div>" in clean


class TestHTMLSanitizerStyleTag:
    """HTMLSanitizer must strip style tags."""

    def test_strips_style_tag(self) -> None:
        dirty = "<style>body{display:none}</style><p>visible</p>"
        clean = HTMLSanitizer.sanitize(dirty)
        assert "<style" not in clean
        assert "<p>visible</p>" in clean


# ---------------------------------------------------------------------------
# API key auth tests
# ---------------------------------------------------------------------------


def _build_test_app() -> FastAPI:
    """Create a minimal FastAPI app with a protected endpoint."""
    test_app = FastAPI()

    @test_app.get("/protected")
    def protected(auth: dict = verify_api_key) -> dict:  # noqa: B008
        return auth

    return test_app


class TestAPIKeyAuth:
    """API key verification must accept valid keys and reject others."""

    def test_missing_key_returns_401(self) -> None:
        """Request without X-API-Key header must receive 401 or 422."""
        with patch("app.security.api_key.settings") as mock_settings:
            mock_settings.valid_api_keys = {"test-key-123"}
            from app.exceptions.errors import AuthenticationError

            with pytest.raises(AuthenticationError):
                verify_api_key(api_key="")

    def test_invalid_key_returns_401(self) -> None:
        """Request with an unknown key must raise AuthenticationError."""
        with patch("app.security.api_key.settings") as mock_settings:
            mock_settings.valid_api_keys = {"test-key-123"}
            from app.exceptions.errors import AuthenticationError

            with pytest.raises(AuthenticationError):
                verify_api_key(api_key="wrong-key")

    def test_valid_key_returns_client_info(self) -> None:
        """Request with a valid key must return client dict."""
        with patch("app.security.api_key.settings") as mock_settings:
            mock_settings.valid_api_keys = {"test-key-123"}
            result = verify_api_key(api_key="test-key-123")
            assert result == {"client": "authenticated"}

    def test_valid_key_among_multiple(self) -> None:
        """Any key in the valid set must be accepted."""
        with patch("app.security.api_key.settings") as mock_settings:
            mock_settings.valid_api_keys = {"key-a", "key-b", "key-c"}
            result = verify_api_key(api_key="key-b")
            assert result == {"client": "authenticated"}


class TestAPIKeyHTTPIntegration:
    """Integration test using FastAPI TestClient for the full HTTP cycle."""

    @staticmethod
    def _make_app() -> FastAPI:
        from fastapi import Depends

        from app.exceptions.handlers import register_exception_handlers

        app = FastAPI()

        _require_key = Depends(verify_api_key)

        @app.get("/protected")
        def protected(auth: dict = _require_key) -> dict:
            return auth

        register_exception_handlers(app)
        return app

    def test_http_missing_key_returns_422(self) -> None:
        """FastAPI returns 422 when a required header is absent."""
        with patch("app.security.api_key.settings") as mock_settings:
            mock_settings.valid_api_keys = {"test-key"}
            app = self._make_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/protected")
            # FastAPI returns 422 for missing required header
            assert resp.status_code == 422

    def test_http_invalid_key_returns_401(self) -> None:
        with patch("app.security.api_key.settings") as mock_settings:
            mock_settings.valid_api_keys = {"test-key"}
            app = self._make_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/protected", headers={"X-API-Key": "bad"})
            assert resp.status_code == 401

    def test_http_valid_key_returns_200(self) -> None:
        with patch("app.security.api_key.settings") as mock_settings:
            mock_settings.valid_api_keys = {"test-key"}
            app = self._make_app()
            client = TestClient(app, raise_server_exceptions=False)
            resp = client.get("/protected", headers={"X-API-Key": "test-key"})
            assert resp.status_code == 200
            assert resp.json() == {"client": "authenticated"}
