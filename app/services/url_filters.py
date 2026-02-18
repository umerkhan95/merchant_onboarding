"""Shared URL filtering constants and helpers for URL discovery.

Centralizes denylist logic, platform-specific sitemap URLs, and product
URL patterns so that url_discovery and sitemap_parser can import without
circular dependencies.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

# ── Platform-specific product sitemap paths ────────────────────────────
# Tried before the generic /sitemap.xml fallback.  If any of these return
# valid URLs we trust them (they are curated product feeds).

PLATFORM_PRODUCT_SITEMAPS: dict[str, list[str]] = {
    "shopify": ["/sitemap_products_1.xml"],
    "woocommerce": ["/product-sitemap.xml", "/product-sitemap1.xml"],
    "magento": ["/pub/media/sitemap/sitemap.xml", "/media/sitemap.xml"],
    "bigcommerce": ["/xmlsitemap.php"],
    "generic": [],
}

# ── Non-product path denylist ──────────────────────────────────────────
# Exact paths (after stripping trailing slash) that are never product pages.

NON_PRODUCT_PATHS: set[str] = {
    "/", "/about", "/about-us", "/contact", "/contact-us",
    "/blog", "/cart", "/checkout", "/account", "/login", "/register",
    "/search", "/faq", "/privacy", "/privacy-policy",
    "/terms", "/terms-of-service", "/terms-and-conditions",
    "/shipping", "/shipping-policy", "/returns", "/return-policy",
    "/refund-policy", "/sitemap", "/brands", "/categories",
    "/pages", "/wishlist", "/compare", "/basket", "/help",
    "/support", "/careers", "/press", "/newsletter",
    "/my-account", "/order-tracking", "/rewards",
}

# ── Non-product path segments ──────────────────────────────────────────
# If ANY segment of the URL path matches one of these, reject it.

NON_PRODUCT_SEGMENTS: set[str] = {
    "checkout", "basket", "cart", "login", "register", "account",
    "blog", "faq", "help", "support", "careers", "press",
    "my-account", "order-tracking", "wp-admin", "wp-includes",
    "feed", "author", "tag", "category", "wp-login.php",
    "newsletter", "unsubscribe",
}

# ── File extensions that are never product pages ───────────────────────

_NON_PRODUCT_EXTENSIONS: set[str] = {
    ".xml", ".json", ".txt", ".pdf", ".png", ".jpg", ".jpeg",
    ".gif", ".svg", ".css", ".js", ".ico", ".woff", ".woff2",
    ".ttf", ".eot", ".map", ".gz",
}

# Date-path blog pattern: /YYYY/MM/DD/slug (WordPress default permalink)
_DATE_PATH_RE = re.compile(r"/\d{4}/\d{2}/\d{2}/")


def is_non_product_url(url: str) -> bool:
    """Return True if *url* is almost certainly NOT a product page.

    Checks (in order):
    1. File extension denylist (.xml, .pdf, .png, ...)
    2. Exact path match against NON_PRODUCT_PATHS
    3. Any path segment in NON_PRODUCT_SEGMENTS
    4. Date-path blog pattern (/YYYY/MM/DD/slug)
    """
    parsed = urlparse(url)
    path = parsed.path.rstrip("/").lower()

    # 1. File extension
    dot_idx = path.rfind(".")
    if dot_idx != -1:
        ext = path[dot_idx:]
        if ext in _NON_PRODUCT_EXTENSIONS:
            return True

    # 2. Exact path match
    if path in NON_PRODUCT_PATHS or path == "":
        return True

    # 3. Segment match
    segments = set(path.strip("/").split("/"))
    if segments & NON_PRODUCT_SEGMENTS:
        return True

    # 4. Date-path blog posts (e.g. /2023/02/16/what-is-whisky/)
    if _DATE_PATH_RE.search(path):
        return True

    return False
