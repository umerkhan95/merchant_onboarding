"""Unit tests for SSRF-safe URL validation.

Tests cover:
- Private/reserved IP blocking (loopback, RFC 1918, link-local, cloud metadata)
- DNS rebinding defense (hostname resolving to private IP)
- Scheme allowlist enforcement
- Blocked port enforcement
- Valid external URLs passing validation
- validate_or_raise convenience method
- Async validation variants
- Redirect validation event hook
- Integration with the onboarding API endpoint
"""

from __future__ import annotations

import socket
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.exceptions.errors import SSRFError
from app.security.url_validator import URLValidator


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _fake_addrinfo(ip: str) -> list[tuple]:
    """Build a fake getaddrinfo result that resolves to the given IP."""
    return [(2, 1, 6, "", (ip, 0))]


def _public_addrinfo() -> list[tuple]:
    """Return a fake getaddrinfo result for a public IP (93.184.216.34)."""
    return _fake_addrinfo("93.184.216.34")


# ---------------------------------------------------------------------------
# Private IP blocking
# ---------------------------------------------------------------------------


class TestPrivateIPBlocking:
    """URLValidator must reject URLs whose hostname resolves to private/reserved IPs."""

    @pytest.mark.parametrize(
        ("ip", "label"),
        [
            ("127.0.0.1", "IPv4 loopback"),
            ("127.0.0.2", "IPv4 loopback (alternate)"),
            ("10.0.0.1", "RFC 1918 10.x"),
            ("10.255.255.255", "RFC 1918 10.x boundary"),
            ("172.16.0.1", "RFC 1918 172.16.x"),
            ("172.31.255.255", "RFC 1918 172.31.x boundary"),
            ("192.168.0.1", "RFC 1918 192.168.x"),
            ("192.168.255.255", "RFC 1918 192.168.x boundary"),
            ("169.254.169.254", "cloud metadata endpoint"),
            ("169.254.0.1", "link-local"),
            ("0.0.0.0", "zero address"),
        ],
    )
    def test_private_ip_rejected(self, ip: str, label: str) -> None:
        """Private IP {label} ({ip}) must be rejected."""
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_fake_addrinfo(ip),
        ):
            valid, reason = URLValidator.validate(f"https://evil.example.com")
            assert valid is False, f"Expected False for {label} ({ip})"
            assert "private" in reason.lower()

    def test_ipv6_loopback_rejected(self) -> None:
        """IPv6 loopback (::1) must be rejected."""
        fake = [(10, 1, 6, "", ("::1", 0, 0, 0))]
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=fake,
        ):
            valid, reason = URLValidator.validate("https://evil.example.com")
            assert valid is False
            assert "private" in reason.lower()

    def test_ipv6_unique_local_rejected(self) -> None:
        """IPv6 unique local address (fc00::/7) must be rejected."""
        fake = [(10, 1, 6, "", ("fd00::1", 0, 0, 0))]
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=fake,
        ):
            valid, reason = URLValidator.validate("https://evil.example.com")
            assert valid is False
            assert "private" in reason.lower()


class TestCloudMetadataBlocking:
    """Cloud provider metadata endpoints must be blocked."""

    def test_aws_metadata_endpoint_blocked(self) -> None:
        """AWS metadata endpoint 169.254.169.254 must be blocked."""
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_fake_addrinfo("169.254.169.254"),
        ):
            valid, reason = URLValidator.validate("http://169.254.169.254/latest/meta-data/")
            assert valid is False
            assert "private" in reason.lower()

    def test_aws_metadata_via_dns_rebinding_blocked(self) -> None:
        """Hostname that resolves to 169.254.169.254 must be blocked (DNS rebinding)."""
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_fake_addrinfo("169.254.169.254"),
        ):
            valid, reason = URLValidator.validate("https://malicious-rebind.attacker.com")
            assert valid is False
            assert "private" in reason.lower()


# ---------------------------------------------------------------------------
# DNS rebinding defense
# ---------------------------------------------------------------------------


class TestDNSRebinding:
    """URLValidator must block hostnames that resolve to private IPs (DNS rebinding)."""

    def test_domain_resolving_to_loopback_blocked(self) -> None:
        """A public domain resolving to 127.0.0.1 must be rejected."""
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_fake_addrinfo("127.0.0.1"),
        ):
            valid, reason = URLValidator.validate("https://legit-looking-domain.com")
            assert valid is False
            assert "private" in reason.lower()

    def test_domain_resolving_to_internal_network_blocked(self) -> None:
        """A public domain resolving to 10.0.0.5 must be rejected."""
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_fake_addrinfo("10.0.0.5"),
        ):
            valid, reason = URLValidator.validate("https://rebinding-attack.example.com")
            assert valid is False

    def test_multiple_ips_one_private_blocked(self) -> None:
        """If any resolved IP is private, the URL must be rejected."""
        mixed_results = [
            (2, 1, 6, "", ("93.184.216.34", 0)),   # Public
            (2, 1, 6, "", ("127.0.0.1", 0)),        # Private
        ]
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=mixed_results,
        ):
            valid, reason = URLValidator.validate("https://mixed-dns.example.com")
            assert valid is False
            assert "private" in reason.lower()

    def test_dns_failure_rejected(self) -> None:
        """Unresolvable hostname must be rejected."""
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            side_effect=socket.gaierror("Name or service not known"),
        ):
            valid, reason = URLValidator.validate("https://no-such-host.invalid")
            assert valid is False
            assert "resolve" in reason.lower()


# ---------------------------------------------------------------------------
# Scheme validation
# ---------------------------------------------------------------------------


class TestSchemeValidation:
    """URLValidator must only allow http and https schemes."""

    @pytest.mark.parametrize("scheme", ["ftp", "file", "gopher", "data", "javascript", "ssh"])
    def test_disallowed_scheme_rejected(self, scheme: str) -> None:
        valid, reason = URLValidator.validate(f"{scheme}://example.com")
        assert valid is False
        assert "not allowed" in reason.lower() or "scheme" in reason.lower()

    def test_empty_scheme_rejected(self) -> None:
        valid, reason = URLValidator.validate("://example.com")
        assert valid is False

    def test_http_allowed(self) -> None:
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_public_addrinfo(),
        ):
            valid, _ = URLValidator.validate("http://example.com")
            assert valid is True

    def test_https_allowed(self) -> None:
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_public_addrinfo(),
        ):
            valid, _ = URLValidator.validate("https://example.com")
            assert valid is True


# ---------------------------------------------------------------------------
# Port validation
# ---------------------------------------------------------------------------


class TestPortValidation:
    """URLValidator must block dangerous ports."""

    @pytest.mark.parametrize("port", [22, 25, 445, 3389, 5432, 27017])
    def test_dangerous_port_rejected(self, port: int) -> None:
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_public_addrinfo(),
        ):
            valid, reason = URLValidator.validate(f"https://example.com:{port}/path")
            assert valid is False
            assert "blocked" in reason.lower() or "port" in reason.lower()

    def test_standard_https_port_allowed(self) -> None:
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_public_addrinfo(),
        ):
            valid, _ = URLValidator.validate("https://example.com:443/path")
            assert valid is True

    def test_standard_http_port_allowed(self) -> None:
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_public_addrinfo(),
        ):
            valid, _ = URLValidator.validate("http://example.com:80/path")
            assert valid is True


# ---------------------------------------------------------------------------
# Hostname validation
# ---------------------------------------------------------------------------


class TestHostnameValidation:
    """URLValidator must reject URLs with empty or missing hostnames."""

    def test_empty_hostname_rejected(self) -> None:
        valid, reason = URLValidator.validate("https:///path")
        assert valid is False
        assert "empty" in reason.lower() or "hostname" in reason.lower()

    def test_no_hostname_rejected(self) -> None:
        valid, reason = URLValidator.validate("https://")
        assert valid is False


# ---------------------------------------------------------------------------
# Valid URLs
# ---------------------------------------------------------------------------


class TestValidURLs:
    """URLValidator must accept well-formed external URLs."""

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.allbirds.com",
            "https://deathwishcoffee.com",
            "https://example.com/products",
            "http://shop.example.org/products?page=2",
            "https://www.example.co.uk/collections/all",
        ],
    )
    def test_valid_shop_url_accepted(self, url: str) -> None:
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_public_addrinfo(),
        ):
            valid, reason = URLValidator.validate(url)
            assert valid is True
            assert reason == "Valid"


# ---------------------------------------------------------------------------
# _is_private_ip helper
# ---------------------------------------------------------------------------


class TestIsPrivateIP:
    """Direct tests for the _is_private_ip helper."""

    @pytest.mark.parametrize(
        "ip",
        ["127.0.0.1", "10.0.0.1", "172.16.0.1", "192.168.1.1", "169.254.169.254", "0.0.0.0"],
    )
    def test_private_ips_detected(self, ip: str) -> None:
        assert URLValidator._is_private_ip(ip) is True

    @pytest.mark.parametrize(
        "ip",
        ["93.184.216.34", "8.8.8.8", "1.1.1.1", "203.0.113.1"],
    )
    def test_public_ips_not_flagged(self, ip: str) -> None:
        assert URLValidator._is_private_ip(ip) is False

    def test_unparseable_ip_treated_as_private(self) -> None:
        """Unparseable IPs should fail closed (treated as private)."""
        assert URLValidator._is_private_ip("not-an-ip") is True


# ---------------------------------------------------------------------------
# validate_or_raise
# ---------------------------------------------------------------------------


class TestValidateOrRaise:
    """validate_or_raise must raise SSRFError on invalid URLs."""

    def test_raises_ssrf_error_for_private_ip(self) -> None:
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_fake_addrinfo("127.0.0.1"),
        ):
            with pytest.raises(SSRFError) as exc_info:
                URLValidator.validate_or_raise("https://evil.com")
            assert "private" in exc_info.value.detail.lower()
            assert exc_info.value.status_code == 400

    def test_raises_ssrf_error_for_bad_scheme(self) -> None:
        with pytest.raises(SSRFError) as exc_info:
            URLValidator.validate_or_raise("ftp://evil.com/file")
        assert "scheme" in exc_info.value.detail.lower() or "not allowed" in exc_info.value.detail.lower()

    def test_no_raise_for_valid_url(self) -> None:
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_public_addrinfo(),
        ):
            # Should not raise
            URLValidator.validate_or_raise("https://deathwishcoffee.com")


# ---------------------------------------------------------------------------
# Async validation
# ---------------------------------------------------------------------------


class TestAsyncValidation:
    """Async variants must behave identically to sync versions."""

    @pytest.mark.asyncio
    async def test_validate_async_rejects_private_ip(self) -> None:
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_fake_addrinfo("10.0.0.1"),
        ):
            valid, reason = await URLValidator.validate_async("https://internal.example.com")
            assert valid is False
            assert "private" in reason.lower()

    @pytest.mark.asyncio
    async def test_validate_async_accepts_public_url(self) -> None:
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_public_addrinfo(),
        ):
            valid, reason = await URLValidator.validate_async("https://example.com")
            assert valid is True

    @pytest.mark.asyncio
    async def test_validate_or_raise_async_raises(self) -> None:
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_fake_addrinfo("192.168.1.1"),
        ):
            with pytest.raises(SSRFError):
                await URLValidator.validate_or_raise_async("https://evil.com")

    @pytest.mark.asyncio
    async def test_validate_or_raise_async_no_raise_for_valid(self) -> None:
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_public_addrinfo(),
        ):
            await URLValidator.validate_or_raise_async("https://example.com")


# ---------------------------------------------------------------------------
# Redirect validation event hook
# ---------------------------------------------------------------------------


class TestRedirectValidation:
    """validate_redirect must block redirects to private IPs."""

    @staticmethod
    def _make_response(status_code: int, location: str, request_url: str = "https://example.com") -> SimpleNamespace:
        """Build a fake httpx-like response for testing the event hook."""
        return SimpleNamespace(
            status_code=status_code,
            headers={"location": location},
            request=SimpleNamespace(url=request_url),
        )

    def test_redirect_to_private_ip_blocked(self) -> None:
        """Redirect to a URL resolving to 127.0.0.1 must raise SSRFError."""
        resp = self._make_response(302, "http://internal.local/secret")
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_fake_addrinfo("127.0.0.1"),
        ):
            with pytest.raises(SSRFError):
                URLValidator.validate_redirect(resp)

    def test_redirect_to_metadata_endpoint_blocked(self) -> None:
        """Redirect to cloud metadata endpoint must raise SSRFError."""
        resp = self._make_response(301, "http://169.254.169.254/latest/meta-data/")
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_fake_addrinfo("169.254.169.254"),
        ):
            with pytest.raises(SSRFError):
                URLValidator.validate_redirect(resp)

    def test_redirect_to_public_url_allowed(self) -> None:
        """Redirect to a public URL must not raise."""
        resp = self._make_response(302, "https://new-location.example.com/products")
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_public_addrinfo(),
        ):
            # Should not raise
            URLValidator.validate_redirect(resp)

    def test_non_redirect_response_ignored(self) -> None:
        """Non-redirect (200) responses must be silently ignored."""
        resp = self._make_response(200, "http://evil.internal/")
        # Should not raise even though location points to something potentially bad
        URLValidator.validate_redirect(resp)

    def test_relative_redirect_resolved(self) -> None:
        """Relative redirect paths must be resolved against the request URL."""
        resp = self._make_response(302, "/admin/internal", request_url="https://shop.example.com/products")
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_public_addrinfo(),
        ):
            # Should not raise — relative path on a public domain
            URLValidator.validate_redirect(resp)

    def test_relative_redirect_to_private_blocked(self) -> None:
        """Relative redirect on a domain resolving to private IP must be blocked."""
        resp = self._make_response(302, "/internal", request_url="https://evil-domain.com/start")
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_fake_addrinfo("10.0.0.5"),
        ):
            with pytest.raises(SSRFError):
                URLValidator.validate_redirect(resp)

    def test_redirect_with_empty_location_ignored(self) -> None:
        """Redirect with no Location header must be silently ignored."""
        resp = SimpleNamespace(
            status_code=302,
            headers={},
            request=SimpleNamespace(url="https://example.com"),
        )
        # Should not raise
        URLValidator.validate_redirect(resp)


# ---------------------------------------------------------------------------
# Onboarding API endpoint integration
# ---------------------------------------------------------------------------


class TestOnboardingSSRFIntegration:
    """SSRF validation must be enforced at the onboarding API endpoint."""

    def test_private_ip_url_rejected_at_api(
        self,
        api_client,
        headers: dict[str, str],
    ) -> None:
        """POST /api/v1/onboard with a private IP URL returns 400 or 422."""
        # Patch DNS so example URL resolves to private IP (simulating DNS rebinding)
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_fake_addrinfo("10.0.0.1"),
        ):
            response = api_client.post(
                "/api/v1/onboard",
                json={"url": "https://evil-rebind.example.com"},
                headers=headers,
            )
        # Should be blocked — either 400 (SSRFError) or 422 (Pydantic validation)
        assert response.status_code in (400, 422)

    def test_cloud_metadata_url_rejected_at_api(
        self,
        api_client,
        headers: dict[str, str],
    ) -> None:
        """POST /api/v1/onboard targeting cloud metadata must be blocked."""
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_fake_addrinfo("169.254.169.254"),
        ):
            response = api_client.post(
                "/api/v1/onboard",
                json={"url": "https://metadata-steal.attacker.com"},
                headers=headers,
            )
        assert response.status_code in (400, 422)

    def test_valid_url_passes_ssrf_check_at_api(
        self,
        api_client,
        headers: dict[str, str],
    ) -> None:
        """POST /api/v1/onboard with a valid public URL passes SSRF check."""
        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_public_addrinfo(),
        ), patch("app.workers.tasks.run_onboarding_pipeline"):
            response = api_client.post(
                "/api/v1/onboard",
                json={"url": "https://deathwishcoffee.com"},
                headers=headers,
            )
        assert response.status_code == 202


# ---------------------------------------------------------------------------
# Celery task SSRF validation
# ---------------------------------------------------------------------------


class TestCeleryTaskSSRFValidation:
    """SSRF validation in the Celery task entry point (defense in depth)."""

    def test_task_rejects_private_ip_url(self) -> None:
        """_run_pipeline must raise SSRFError for URLs resolving to private IPs."""
        from app.workers.tasks import _run_pipeline

        with patch(
            "app.security.url_validator.socket.getaddrinfo",
            return_value=_fake_addrinfo("127.0.0.1"),
        ):
            with pytest.raises(SSRFError):
                import asyncio
                asyncio.get_event_loop().run_until_complete(
                    _run_pipeline("job_test123", "https://evil-internal.com")
                )
