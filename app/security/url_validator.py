"""SSRF-safe URL validation.

Provides synchronous and async URL validation that checks:
- Scheme allowlist (http/https only)
- Blocked ports (SSH, SMTP, SMB, RDP, PostgreSQL, MongoDB)
- DNS resolution against private/internal IP ranges (prevents DNS rebinding)
- Cloud metadata endpoint protection (169.254.169.254)
- httpx redirect event hook for safe outbound HTTP requests
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from functools import partial
from urllib.parse import urlparse

from app.exceptions.errors import SSRFError

logger = logging.getLogger(__name__)


class URLValidator:
    """Validates URLs to prevent SSRF attacks.

    Checks scheme, hostname resolution against private IP ranges,
    and blocks dangerous ports. Performs DNS resolution to catch DNS
    rebinding attacks where a hostname initially resolves to a public
    IP but later resolves to a private IP.
    """

    _ALLOWED_SCHEMES: frozenset[str] = frozenset({"http", "https"})

    _BLOCKED_PORTS: frozenset[int] = frozenset({
        22,     # SSH
        25,     # SMTP
        445,    # SMB
        3389,   # RDP
        5432,   # PostgreSQL
        27017,  # MongoDB
    })

    _PRIVATE_NETWORKS: tuple[ipaddress.IPv4Network | ipaddress.IPv6Network, ...] = (
        ipaddress.IPv4Network("127.0.0.0/8"),
        ipaddress.IPv4Network("10.0.0.0/8"),
        ipaddress.IPv4Network("172.16.0.0/12"),
        ipaddress.IPv4Network("192.168.0.0/16"),
        ipaddress.IPv4Network("169.254.0.0/16"),  # Link-local + cloud metadata
        ipaddress.IPv4Network("0.0.0.0/8"),        # "This" network
        ipaddress.IPv6Network("::1/128"),
        ipaddress.IPv6Network("fc00::/7"),          # Unique local addresses
        ipaddress.IPv6Network("fe80::/10"),         # Link-local
    )

    @staticmethod
    def _is_private_ip(ip_str: str) -> bool:
        """Check if an IP address string falls within any private/reserved network.

        Args:
            ip_str: IP address as a string.

        Returns:
            True if the IP is private/reserved, False otherwise.
        """
        try:
            ip = ipaddress.ip_address(ip_str)
        except ValueError:
            return True  # Treat unparseable IPs as private (fail closed)

        for network in URLValidator._PRIVATE_NETWORKS:
            if ip in network:
                return True
        return False

    @staticmethod
    def validate(url: str) -> tuple[bool, str]:
        """Validate a URL for safe external requests (synchronous).

        Resolves the hostname via DNS and checks all resolved IPs against
        private network ranges. This catches DNS rebinding attacks where
        a domain resolves to an internal IP at request time.

        Args:
            url: The URL string to validate.

        Returns:
            A tuple of (is_valid, reason). ``(True, "Valid")`` when the URL
            passes all checks, or ``(False, "<reason>")`` otherwise.
        """
        try:
            parsed = urlparse(url)
        except Exception:
            return False, "Malformed URL"

        # Scheme check
        if parsed.scheme not in URLValidator._ALLOWED_SCHEMES:
            return False, f"Scheme '{parsed.scheme}' is not allowed; only http/https permitted"

        # Hostname must not be empty
        hostname = parsed.hostname
        if not hostname:
            return False, "Hostname is empty"

        # Port check
        port = parsed.port
        if port is not None and port in URLValidator._BLOCKED_PORTS:
            return False, f"Port {port} is blocked"

        # Resolve hostname and check against private IP ranges (DNS rebinding defense)
        try:
            addr_infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            return False, f"Could not resolve hostname '{hostname}'"

        for _family, _type, _proto, _canonname, sockaddr in addr_infos:
            ip_str = sockaddr[0]
            if URLValidator._is_private_ip(ip_str):
                return False, f"Hostname resolves to private IP {ip_str}"

        return True, "Valid"

    @staticmethod
    async def validate_async(url: str) -> tuple[bool, str]:
        """Async version of validate that runs DNS resolution in a thread pool.

        Identical checks to ``validate()`` but non-blocking for async code.

        Args:
            url: The URL string to validate.

        Returns:
            A tuple of (is_valid, reason).
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, partial(URLValidator.validate, url))

    @staticmethod
    def validate_or_raise(url: str) -> None:
        """Validate a URL and raise SSRFError if it fails.

        Convenience method for use at API boundaries where we want to
        immediately reject unsafe URLs.

        Args:
            url: The URL string to validate.

        Raises:
            SSRFError: If the URL fails validation.
        """
        is_valid, reason = URLValidator.validate(url)
        if not is_valid:
            logger.warning("SSRF validation failed for URL %s: %s", url, reason)
            raise SSRFError(detail=f"URL validation failed: {reason}")

    @staticmethod
    async def validate_or_raise_async(url: str) -> None:
        """Async version of validate_or_raise.

        Args:
            url: The URL string to validate.

        Raises:
            SSRFError: If the URL fails validation.
        """
        is_valid, reason = await URLValidator.validate_async(url)
        if not is_valid:
            logger.warning("SSRF validation failed for URL %s: %s", url, reason)
            raise SSRFError(detail=f"URL validation failed: {reason}")

    @staticmethod
    def validate_redirect(response: object) -> None:
        """httpx event hook that validates redirect targets against SSRF.

        Use this as an ``event_hooks={"response": [URLValidator.validate_redirect]}``
        callback on httpx clients. When a redirect response (3xx) is received,
        the ``Location`` header is validated before the client follows it.

        Args:
            response: httpx Response object.

        Raises:
            SSRFError: If the redirect target resolves to a private IP.
        """
        # Only check redirect responses
        status_code = getattr(response, "status_code", 0)
        if not (300 <= status_code < 400):
            return

        headers = getattr(response, "headers", {})
        location = headers.get("location", "")
        if not location:
            return

        # Resolve relative redirects against the request URL
        request = getattr(response, "request", None)
        if request is not None and not location.startswith(("http://", "https://")):
            base_url = str(request.url)
            parsed_base = urlparse(base_url)
            location = f"{parsed_base.scheme}://{parsed_base.netloc}{location}"

        is_valid, reason = URLValidator.validate(location)
        if not is_valid:
            logger.warning(
                "SSRF: Blocked redirect to %s: %s", location, reason
            )
            raise SSRFError(
                detail=f"Redirect target validation failed: {reason}"
            )
