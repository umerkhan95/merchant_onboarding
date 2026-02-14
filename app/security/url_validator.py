"""SSRF-safe URL validation."""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


class URLValidator:
    """Validates URLs to prevent SSRF attacks.

    Checks scheme, hostname resolution against private IP ranges,
    and blocks dangerous ports.
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
        ipaddress.IPv4Network("169.254.0.0/16"),
        ipaddress.IPv6Network("::1/128"),
        ipaddress.IPv6Network("fc00::/7"),
    )

    @staticmethod
    def validate(url: str) -> tuple[bool, str]:
        """Validate a URL for safe external requests.

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

        # Resolve hostname and check against private IP ranges
        try:
            addr_infos = socket.getaddrinfo(hostname, None, proto=socket.IPPROTO_TCP)
        except socket.gaierror:
            return False, f"Could not resolve hostname '{hostname}'"

        for _family, _type, _proto, _canonname, sockaddr in addr_infos:
            ip_str = sockaddr[0]
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                return False, f"Invalid IP address '{ip_str}' resolved from hostname"

            for network in URLValidator._PRIVATE_NETWORKS:
                if ip in network:
                    return False, f"Hostname resolves to private IP {ip_str}"

        return True, "Valid"
