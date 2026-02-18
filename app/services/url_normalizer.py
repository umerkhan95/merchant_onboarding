"""URL normalization for canonical shop_id generation.

Ensures the same store always gets the same shop_id regardless of how the
user types the URL (trailing slashes, case, default ports, fragments).
"""

from __future__ import annotations

from urllib.parse import urlparse, urlunparse


def normalize_shop_url(url: str) -> str:
    """Normalize a shop URL to a canonical form for use as shop_id.

    Rules:
        1. Lowercase the scheme and hostname
        2. Strip trailing slashes from the path
        3. Remove default ports (80 for http, 443 for https)
        4. Remove fragments (#...)
        5. Keep www. prefix (stripping it is too aggressive)

    Args:
        url: Raw shop URL as provided by the user.

    Returns:
        Canonical URL string suitable for use as a unique shop_id.
    """
    parsed = urlparse(url)

    scheme = parsed.scheme.lower()
    hostname = (parsed.hostname or "").lower()

    # Remove default ports
    port = parsed.port
    if (scheme == "https" and port == 443) or (scheme == "http" and port == 80):
        port = None

    netloc = hostname
    if port:
        netloc = f"{hostname}:{port}"

    # Strip trailing slashes from path
    path = parsed.path.rstrip("/")

    # Drop fragment, keep query
    return urlunparse((scheme, netloc, path, parsed.params, parsed.query, ""))
