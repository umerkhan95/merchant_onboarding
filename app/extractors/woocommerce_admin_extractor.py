"""WooCommerce REST API v3 extractor using authenticated access.

Uses the WooCommerce REST API v3 with consumer_key/consumer_secret
(HTTP Basic Auth) to extract complete product data including meta_data
where GTIN/EAN plugins store barcode information.

Requires a stored OAuth connection with consumer_key and consumer_secret.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from app.db.oauth_store import OAuthConnection
from app.extractors.base import BaseExtractor, ExtractorResult
from app.extractors.browser_config import get_default_user_agent

logger = logging.getLogger(__name__)

_API_VERSION = "wc/v3"
_PAGE_LIMIT = 100  # WooCommerce REST API max is 100 per page
_MAX_PAGES = 100

# Common meta_data keys where GTIN/EAN plugins store barcode data.
# Each WooCommerce GTIN plugin uses its own key — we check all known ones.
_GTIN_META_KEYS = frozenset({
    # WooCommerce UPC, EAN, and ISBN plugin
    "_wpm_gtin_code",
    # EAN for WooCommerce (WPFactory/Algoritmika)
    "_alg_ean",
    "_ean",
    # Product GTIN (EAN, UPC, ISBN) for WooCommerce
    "hwp_product_gtin",
    "hwp_var_gtin",
    # YITH WooCommerce Barcodes plugin
    "_yith_barcode_value",
    # WooCommerce Barcode and ISBN plugin
    "_barcode",
    # Germanized for WooCommerce (common in DE market)
    "_ts_gtin",
    "_gtin",
    # Generic keys some themes/plugins use
    "gtin",
    "ean",
    "upc",
    "barcode",
    "isbn",
    "_upc",
    "_isbn",
})

# Regex pattern to match GTIN-like meta keys not in our explicit set
_GTIN_KEY_PATTERN = re.compile(r"(gtin|ean|upc|barcode|isbn)", re.IGNORECASE)


class WooCommerceAdminExtractor(BaseExtractor):
    """Extract products from WooCommerce stores via authenticated REST API v3."""

    def __init__(self, connection: OAuthConnection, timeout: int = 30):
        """Initialize with OAuth connection credentials.

        Args:
            connection: OAuthConnection with consumer_key and consumer_secret.
            timeout: HTTP request timeout in seconds.
        """
        if not connection.consumer_key or not connection.consumer_secret:
            raise ValueError("WooCommerce connection requires consumer_key and consumer_secret")
        self._consumer_key = connection.consumer_key
        self._consumer_secret = connection.consumer_secret
        self._shop_domain = connection.shop_domain
        self._timeout = timeout

    def _base_url(self) -> str:
        return f"https://{self._shop_domain}/wp-json/{_API_VERSION}"

    def _auth(self) -> tuple[str, str]:
        """HTTP Basic Auth tuple (consumer_key, consumer_secret)."""
        return (self._consumer_key, self._consumer_secret)

    async def extract(self, shop_url: str) -> ExtractorResult:
        """Fetch all products from WooCommerce REST API v3.

        Uses page-based pagination with X-WP-Total and X-WP-TotalPages headers.
        Fetches variations for variable products separately.

        Args:
            shop_url: The shop URL (used for product URL construction).

        Returns:
            ExtractorResult with products and pagination metadata.
        """
        all_products: list[dict[str, Any]] = []
        complete = True
        error: str | None = None
        total_pages: int | None = None

        async with httpx.AsyncClient(
            timeout=self._timeout,
            auth=self._auth(),
            headers={
                "Accept": "application/json",
                "User-Agent": get_default_user_agent(),
            },
            follow_redirects=True,
        ) as client:
            page = 1

            while page <= _MAX_PAGES:
                url = f"{self._base_url()}/products"
                params = {
                    "per_page": _PAGE_LIMIT,
                    "page": page,
                    "status": "publish",
                }
                logger.info(
                    "WooCommerce REST API: fetching page %d for %s",
                    page, self._shop_domain,
                )

                try:
                    resp = await client.get(url, params=params)

                    # Handle rate limiting (WordPress rate limit headers)
                    if resp.status_code == 429:
                        retry_after = float(resp.headers.get("Retry-After", "2"))
                        logger.warning(
                            "WooCommerce rate limited, waiting %.1fs", retry_after
                        )
                        await asyncio.sleep(retry_after)
                        resp = await client.get(url, params=params)
                        if resp.status_code == 429:
                            complete = False
                            error = f"Rate limited on page {page}"
                            break

                    if resp.status_code == 401:
                        logger.error(
                            "WooCommerce credentials invalid for %s",
                            self._shop_domain,
                        )
                        return ExtractorResult(
                            products=[], complete=False, error="API credentials invalid"
                        )

                    if resp.status_code == 403:
                        logger.error(
                            "WooCommerce credentials lack required permissions for %s",
                            self._shop_domain,
                        )
                        return ExtractorResult(
                            products=[],
                            complete=False,
                            error="API credentials lack read permission",
                        )

                    if resp.status_code == 404:
                        logger.error(
                            "WooCommerce REST API not available at %s (404)",
                            self._shop_domain,
                        )
                        return ExtractorResult(
                            products=[],
                            complete=False,
                            error="REST API not available (404) — permalinks may be set to Plain",
                        )

                    if resp.status_code != 200:
                        logger.error(
                            "WooCommerce REST API HTTP %d on page %d",
                            resp.status_code, page,
                        )
                        complete = False
                        error = f"HTTP {resp.status_code} on page {page}"
                        break

                    # Parse pagination headers
                    if total_pages is None:
                        total_pages = int(resp.headers.get("X-WP-TotalPages", "1"))

                    data = resp.json()
                    if not isinstance(data, list) or not data:
                        break

                    # Normalize each product
                    for product in data:
                        normalized = self._normalize_product(product, shop_url)

                        # Fetch variations for variable products
                        if product.get("type") == "variable":
                            variations = await self._fetch_variations(
                                client, product["id"], shop_url
                            )
                            if variations:
                                normalized["variants"] = variations

                        all_products.append(normalized)

                    logger.info(
                        "WooCommerce REST API: page %d returned %d products (total: %d)",
                        page, len(data), len(all_products),
                    )

                    if page >= (total_pages or 1):
                        break

                    page += 1

                except httpx.TimeoutException:
                    logger.warning("WooCommerce REST API timeout on page %d", page)
                    complete = False
                    error = f"Timeout on page {page}"
                    break
                except httpx.RequestError as e:
                    logger.error(
                        "WooCommerce REST API request error on page %d: %s", page, e
                    )
                    complete = False
                    error = f"Request error on page {page}: {e}"
                    break

        logger.info(
            "WooCommerce REST API: extracted %d products from %d pages for %s",
            len(all_products), page, self._shop_domain,
        )
        return ExtractorResult(
            products=all_products,
            complete=complete,
            error=error,
            pages_completed=page if all_products else 0,
            pages_expected=total_pages,
        )

    async def _fetch_variations(
        self, client: httpx.AsyncClient, product_id: int, shop_url: str
    ) -> list[dict]:
        """Fetch all variations for a variable product.

        WooCommerce REST API v3 does not include variations inline —
        they must be fetched separately via /products/{id}/variations.

        Args:
            client: Active httpx client with auth configured.
            product_id: The parent product ID.
            shop_url: Base shop URL for product URL construction.

        Returns:
            List of normalized variant dicts.
        """
        variants: list[dict] = []
        page = 1

        while page <= 10:  # Safety cap: 10 pages * 100 = 1000 variations max
            try:
                resp = await client.get(
                    f"{self._base_url()}/products/{product_id}/variations",
                    params={"per_page": _PAGE_LIMIT, "page": page},
                )
                if resp.status_code != 200:
                    break

                data = resp.json()
                if not isinstance(data, list) or not data:
                    break

                for v in data:
                    gtin = self._extract_gtin_from_meta(v.get("meta_data", []))
                    variants.append({
                        "id": str(v.get("id", "")),
                        "title": " / ".join(
                            attr.get("option", "")
                            for attr in v.get("attributes", [])
                        ),
                        "price": str(v.get("price", "")),
                        "sku": v.get("sku", ""),
                        "barcode": gtin or "",
                        "inventory_quantity": v.get("stock_quantity") or 0,
                    })

                total_pages = int(resp.headers.get("X-WP-TotalPages", "1"))
                if page >= total_pages:
                    break
                page += 1

            except Exception as e:
                logger.debug(
                    "Failed to fetch variations for product %d: %s", product_id, e
                )
                break

        return variants

    def _normalize_product(self, product: dict, shop_url: str) -> dict:
        """Map WooCommerce REST API v3 product to raw dict for ProductNormalizer.

        Matches field names used by other extractors so ProductNormalizer
        handles them uniformly.
        """
        # Primary image
        images = product.get("images", [])
        primary_image = images[0].get("src", "") if images else ""
        additional_images = [img.get("src", "") for img in images[1:] if img.get("src")]

        # Extract GTIN from meta_data
        gtin = self._extract_gtin_from_meta(product.get("meta_data", []))

        # Categories
        categories = product.get("categories", [])
        category_names = [c.get("name", "") for c in categories if c.get("name")]

        # Build product URL
        permalink = product.get("permalink", "")
        product_url = permalink if permalink else shop_url

        # Stock status
        in_stock = product.get("stock_status", "instock") == "instock"

        # Variants for variable products (populated later by _fetch_variations)
        # For simple products, treat as single variant
        variants = []

        return {
            "id": str(product.get("id", "")),
            "title": product.get("name", ""),
            "description": product.get("description", ""),
            "handle": product.get("slug", ""),
            "vendor": "",  # WooCommerce REST API has no vendor/brand field
            "product_type": product.get("type", "simple"),
            "tags": [t.get("name", "") for t in product.get("tags", []) if t.get("name")],
            "price": str(product.get("price", "")),
            "compare_at_price": str(product.get("regular_price", "")) if product.get("sale_price") else None,
            "sku": product.get("sku", ""),
            "barcode": gtin or "",
            "gtin": gtin or "",
            "mpn": "",
            "in_stock": in_stock,
            "image_url": primary_image,
            "additional_images": additional_images,
            "product_url": product_url,
            "variants": variants,
            "weight": product.get("weight", ""),
            "condition": "New",
            "categories": category_names,
            "_source": "woocommerce_admin_api",
            "_platform": "woocommerce",
        }

    @staticmethod
    def _extract_gtin_from_meta(meta_data: list[dict]) -> str | None:
        """Extract GTIN/EAN/UPC from WooCommerce meta_data array.

        Scans meta_data for known GTIN plugin keys, then falls back to
        regex matching for unknown plugin keys that contain gtin/ean/upc/barcode.

        Args:
            meta_data: List of {"id": int, "key": str, "value": str} dicts.

        Returns:
            GTIN string if found, None otherwise.
        """
        if not meta_data:
            return None

        # First pass: check known plugin keys (exact match, fast)
        for meta in meta_data:
            key = meta.get("key", "")
            value = meta.get("value", "")
            if key in _GTIN_META_KEYS and value and str(value).strip():
                val = str(value).strip()
                # Basic sanity: GTIN should be mostly digits
                digits = "".join(c for c in val if c.isdigit())
                if len(digits) >= 8:
                    return val

        # Second pass: regex match for unknown plugin keys
        for meta in meta_data:
            key = meta.get("key", "")
            value = meta.get("value", "")
            if not key or not value:
                continue
            if _GTIN_KEY_PATTERN.search(key):
                val = str(value).strip()
                digits = "".join(c for c in val if c.isdigit())
                if len(digits) >= 8:
                    return val

        return None
