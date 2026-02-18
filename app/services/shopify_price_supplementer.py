"""Shopify API price supplementation service.

Supplements Schema.org-extracted products with canonical pricing from the
Shopify /products.json API when prices are missing or geo-targeted.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from app.exceptions.errors import CircuitOpenError
from app.extractors.shopify_api import ShopifyAPIExtractor

if TYPE_CHECKING:
    from app.infra.circuit_breaker import CircuitBreaker

logger = logging.getLogger(__name__)


class ShopifyPriceSupplementer:
    """Supplement Schema.org products with canonical Shopify API pricing.

    Fixes two issues for Shopify stores that fell back to Schema.org:
    1. Zero-price: JSON-LD may omit 'offers' entirely (geo-targeting/inventory).
    2. Geo-currency: JSON-LD may serve location-specific prices (e.g. EUR)
       instead of the merchant's base catalog currency.
    """

    def __init__(self, circuit_breaker: CircuitBreaker) -> None:
        self.circuit_breaker = circuit_breaker

    async def supplement(
        self, raw_products: list[dict], shop_url: str
    ) -> list[dict]:
        """Supplement products with Shopify API pricing.

        Args:
            raw_products: Products from Schema.org extraction
            shop_url: Base shop URL

        Returns:
            Same product list with zero-prices filled and geo-currencies corrected
        """
        api_products = await self._fetch_api_products(shop_url)
        if not api_products:
            return raw_products

        # Build lookups by handle and normalised title
        api_by_handle: dict[str, dict] = {}
        api_by_title: dict[str, dict] = {}
        base_currency = api_products[0].get("_shop_currency", "USD")

        for ap in api_products:
            handle = ap.get("handle", "").lower().strip()
            title = ap.get("title", "").strip().lower()
            if handle:
                api_by_handle[handle] = ap
            if title:
                api_by_title[title] = ap

        filled_count = 0
        corrected_count = 0

        for product in raw_products:
            offers = product.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if not isinstance(offers, dict):
                offers = {}

            price_raw = str(offers.get("price", "0")) if offers else "0"
            try:
                price_val = float(price_raw)
            except (ValueError, TypeError):
                price_val = 0.0

            schema_currency = (offers.get("priceCurrency") or "").upper()

            needs_price = price_val == 0
            needs_currency = bool(
                schema_currency
                and base_currency
                and schema_currency != base_currency.upper()
            )

            if not needs_price and not needs_currency:
                continue

            api_match = self._match_product(product, api_by_handle, api_by_title)
            if not api_match:
                continue

            variants = api_match.get("variants", [])
            api_price = variants[0].get("price", "0") if variants else "0"

            # Don't replace with zero from the API
            try:
                if float(api_price) == 0:
                    continue
            except (ValueError, TypeError):
                continue

            # Inject / update offers
            current_offers = product.get("offers")
            if not current_offers or (isinstance(current_offers, list) and not current_offers):
                product["offers"] = {
                    "price": api_price,
                    "priceCurrency": base_currency,
                    "availability": "https://schema.org/InStock",
                }
            elif isinstance(current_offers, dict):
                current_offers["price"] = api_price
                current_offers["priceCurrency"] = base_currency
            elif (
                isinstance(current_offers, list)
                and current_offers
                and isinstance(current_offers[0], dict)
            ):
                current_offers[0]["price"] = api_price
                current_offers[0]["priceCurrency"] = base_currency

            if needs_price:
                filled_count += 1
            if needs_currency:
                corrected_count += 1

        if filled_count or corrected_count:
            logger.info(
                "Shopify API supplementation: %d zero-price filled, %d geo-currency corrected (base: %s)",
                filled_count,
                corrected_count,
                base_currency,
            )
        return raw_products

    async def _fetch_api_products(self, shop_url: str) -> list[dict]:
        """Fetch products from Shopify API, trying alternative endpoints for headless stores."""
        shopify_extractor = ShopifyAPIExtractor()

        # Try the main URL first
        try:
            products = await self._extract_with_circuit_breaker(
                shopify_extractor, shop_url, shop_url
            )
        except Exception:
            products = []
        if products:
            return products

        # Try shop.{base_domain} for headless Shopify stores
        parsed = urlparse(shop_url)
        base_domain = parsed.netloc.lower().removeprefix("www.")
        alt_url = f"{parsed.scheme}://shop.{base_domain}"

        try:
            products = await self._extract_with_circuit_breaker(
                shopify_extractor, alt_url, shop_url
            )
        except Exception:
            products = []
        if products:
            logger.info(
                "Shopify API found at alternative endpoint %s (%d products)",
                alt_url,
                len(products),
            )
            return products

        return []

    async def _extract_with_circuit_breaker(
        self, extractor, url: str, domain: str
    ) -> list[dict]:
        """Extract products using circuit breaker for fault tolerance."""

        async def extract_fn():
            return await extractor.extract(url)

        try:
            return await self.circuit_breaker.call(domain, extract_fn)
        except CircuitOpenError:
            logger.warning("Circuit breaker OPEN for %s, skipping %s", domain, url)
            return []
        except Exception as e:
            logger.error("Extraction failed for %s: %s", url, e)
            raise

    @staticmethod
    def _match_product(
        schema_product: dict,
        api_by_handle: dict[str, dict],
        api_by_title: dict[str, dict],
    ) -> dict | None:
        """Match a Schema.org product to a Shopify API product by URL handle or title."""
        # Primary: extract handle from product URL
        product_url = schema_product.get("url", "")
        if "/products/" in product_url:
            handle = (
                product_url.split("/products/")[-1]
                .rstrip("/")
                .split("?")[0]
                .lower()
            )
            if handle and handle in api_by_handle:
                return api_by_handle[handle]

        # Fallback: exact title match (case-insensitive)
        title = schema_product.get("name", "").strip().lower()
        if title and title in api_by_title:
            return api_by_title[title]

        return None
