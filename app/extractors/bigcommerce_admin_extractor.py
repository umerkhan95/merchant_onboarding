"""BigCommerce Admin API extractor using authenticated OAuth access.

Uses the BigCommerce Catalog V3 API with an OAuth access token to extract
complete product data including UPC/GTIN, brand, variants, and images.

Requires a stored OAuth connection with access_token and store_hash.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.db.oauth_store import OAuthConnection
from app.extractors.base import BaseExtractor, ExtractorResult
from app.extractors.browser_config import DEFAULT_HEADERS, get_default_user_agent

logger = logging.getLogger(__name__)

_BC_API_HOST = "https://api.bigcommerce.com"
_PAGE_LIMIT = 250
_MAX_PAGES = 100


class BigCommerceAdminExtractor(BaseExtractor):
    """Extract products from BigCommerce stores via authenticated Admin API V3."""

    def __init__(self, connection: OAuthConnection, timeout: int = 30):
        if not connection.access_token or not connection.store_hash:
            raise ValueError("BigCommerce connection requires access_token and store_hash")
        self._access_token = connection.access_token
        self._store_hash = connection.store_hash
        self._timeout = timeout
        self._brand_cache: dict[int, str] = {}

    def _base_url(self) -> str:
        return f"{_BC_API_HOST}/stores/{self._store_hash}/v3"

    def _headers(self) -> dict[str, str]:
        return {
            "X-Auth-Token": self._access_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": get_default_user_agent(),
        }

    async def extract(self, shop_url: str) -> ExtractorResult:
        """Fetch all products from BigCommerce Catalog V3 API.

        Args:
            shop_url: The BigCommerce store URL (used for logging/context).

        Returns:
            ExtractorResult with products and pagination metadata.
        """
        all_products: list[dict[str, Any]] = []
        complete = True
        error: str | None = None

        async with httpx.AsyncClient(timeout=self._timeout, headers=self._headers()) as client:
            # Pre-fetch brand map for name resolution
            await self._load_brands(client)

            page = 1
            while page <= _MAX_PAGES:
                url = f"{self._base_url()}/catalog/products?limit={_PAGE_LIMIT}&page={page}&include=images,variants"
                logger.info("BigCommerce Admin API: fetching page %d", page)

                try:
                    resp = await client.get(url)

                    if resp.status_code == 429:
                        retry_after = int(resp.headers.get("X-Rate-Limit-Time-Reset-Ms", "2000")) / 1000
                        logger.warning("BigCommerce rate limited, waiting %.1fs", retry_after)
                        import asyncio
                        await asyncio.sleep(retry_after)
                        resp = await client.get(url)
                        if resp.status_code == 429:
                            complete = False
                            error = f"Rate limited on page {page}"
                            break

                    if resp.status_code == 401:
                        logger.error("BigCommerce OAuth token invalid/expired")
                        return ExtractorResult(products=[], complete=False, error="OAuth token invalid")

                    if resp.status_code != 200:
                        logger.error("BigCommerce API HTTP %d on page %d", resp.status_code, page)
                        complete = False
                        error = f"HTTP {resp.status_code} on page {page}"
                        break

                    data = resp.json()
                    products = data.get("data", [])
                    if not products:
                        break

                    for product in products:
                        normalized = self._normalize_product(product, shop_url)
                        all_products.append(normalized)

                    # Check pagination
                    meta = data.get("meta", {}).get("pagination", {})
                    total_pages = meta.get("total_pages", 1)
                    if page >= total_pages:
                        break

                    page += 1

                except httpx.TimeoutException:
                    logger.warning("BigCommerce API timeout on page %d", page)
                    complete = False
                    error = f"Timeout on page {page}"
                    break
                except httpx.RequestError as e:
                    logger.error("BigCommerce API request error on page %d: %s", page, e)
                    complete = False
                    error = f"Request error on page {page}: {e}"
                    break

        logger.info("BigCommerce Admin API: extracted %d products from %d pages", len(all_products), page)
        return ExtractorResult(
            products=all_products,
            complete=complete,
            error=error,
            pages_completed=page if all_products else 0,
        )

    async def _load_brands(self, client: httpx.AsyncClient) -> None:
        """Pre-fetch all brands into a local cache for name resolution."""
        try:
            page = 1
            while page <= 10:  # Brands rarely exceed 2500
                resp = await client.get(f"{self._base_url()}/catalog/brands?limit=250&page={page}")
                if resp.status_code != 200:
                    break
                data = resp.json()
                brands = data.get("data", [])
                if not brands:
                    break
                for brand in brands:
                    self._brand_cache[brand["id"]] = brand.get("name", "")
                total_pages = data.get("meta", {}).get("pagination", {}).get("total_pages", 1)
                if page >= total_pages:
                    break
                page += 1
            logger.info("BigCommerce: cached %d brands", len(self._brand_cache))
        except Exception as e:
            logger.warning("BigCommerce: failed to load brands: %s", e)

    def _normalize_product(self, product: dict, shop_url: str) -> dict:
        """Map BigCommerce product to the raw dict format expected by ProductNormalizer.

        Matches the same field names used by other extractors (Shopify, WooCommerce)
        so ProductNormalizer handles them uniformly.
        """
        # Primary image
        images = product.get("images", [])
        images_sorted = sorted(images, key=lambda i: i.get("sort_order", 0))
        primary_image = images_sorted[0].get("url_zoom", "") if images_sorted else ""
        additional_images = [img.get("url_zoom", "") for img in images_sorted[1:] if img.get("url_zoom")]

        # Brand from cache
        brand_id = product.get("brand_id", 0)
        brand_name = self._brand_cache.get(brand_id, "")

        # Variants — extract first variant's barcode if main product lacks UPC
        variants_raw = product.get("variants", [])
        first_variant = variants_raw[0] if variants_raw else {}

        upc = product.get("upc", "") or product.get("gtin", "") or first_variant.get("upc", "")

        # Build product URL
        custom_url = product.get("custom_url", {})
        url_path = custom_url.get("url", "") if isinstance(custom_url, dict) else ""
        product_url = f"{shop_url.rstrip('/')}{url_path}" if url_path else shop_url

        return {
            "id": str(product.get("id", "")),
            "title": product.get("name", ""),
            "description": product.get("description", ""),
            "handle": url_path.strip("/"),
            "vendor": brand_name,
            "product_type": product.get("type", "physical"),
            "tags": [cat.get("name", "") for cat in product.get("categories", [])],
            "price": str(product.get("price", "0")),
            "compare_at_price": str(product.get("retail_price", "")) if product.get("retail_price") else None,
            "sku": product.get("sku", "") or first_variant.get("sku", ""),
            "barcode": upc,
            "gtin": upc,
            "mpn": product.get("mpn", ""),
            "in_stock": product.get("availability") != "disabled" and product.get("inventory_level", 0) > 0,
            "image_url": primary_image,
            "additional_images": additional_images,
            "product_url": product_url,
            "variants": [
                {
                    "id": str(v.get("id", "")),
                    "title": v.get("option_values", [{}])[0].get("label", "") if v.get("option_values") else "",
                    "price": str(v.get("price", product.get("price", "0"))),
                    "sku": v.get("sku", ""),
                    "barcode": v.get("upc", ""),
                    "inventory_quantity": v.get("inventory_level", 0),
                }
                for v in variants_raw
            ],
            "weight": product.get("weight"),
            "condition": product.get("condition", "New"),
            "_source": "bigcommerce_admin_api",
            "_platform": "bigcommerce",
        }
