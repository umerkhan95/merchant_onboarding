"""Shopify API product extractor using /products.json endpoint."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class ShopifyAPIExtractor(BaseExtractor):
    """Extract products from Shopify stores using the /products.json API endpoint."""

    def __init__(self, timeout: int = 30, max_pages: int = 100):
        """Initialize the Shopify API extractor.

        Args:
            timeout: HTTP request timeout in seconds (default: 30)
            max_pages: Maximum number of pages to fetch (default: 100)
        """
        self.timeout = timeout
        self.max_pages = max_pages

    async def extract(self, shop_url: str) -> list[dict]:
        """Fetch all products from /products.json with pagination.

        Args:
            shop_url: The Shopify store URL (e.g., https://example.myshopify.com)

        Returns:
            List of raw product dicts from Shopify API
            Returns empty list on errors
        """
        all_products: list[dict[str, Any]] = []
        base_url = shop_url.rstrip("/")
        shop_currency: str | None = None

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            page = 1

            while page <= self.max_pages:
                url = f"{base_url}/products.json?limit=250&page={page}"
                logger.info(f"Fetching page {page} from {url}")

                try:
                    response = await client.get(url)

                    # Handle rate limiting (429) - retry once
                    if response.status_code == 429:
                        logger.warning(f"Rate limited on page {page}, waiting and retrying once")
                        retry_after = int(response.headers.get("Retry-After", "2"))
                        await self._wait(retry_after)

                        response = await client.get(url)
                        if response.status_code == 429:
                            logger.error(f"Rate limited again on page {page}, stopping extraction")
                            break

                    # Handle 404 - shop not found or no products
                    if response.status_code == 404:
                        logger.warning(f"Received 404 for {url}, no products found")
                        break

                    # Handle other errors
                    if response.status_code >= 500:
                        logger.error(f"Server error {response.status_code} on page {page}, stopping extraction")
                        break

                    if response.status_code != 200:
                        logger.warning(f"HTTP {response.status_code} on page {page}, returning what we have")
                        break

                    # Parse JSON response
                    try:
                        data = response.json()
                    except Exception as e:
                        logger.error(f"Invalid JSON on page {page}: {e}, returning what we have")
                        break

                    # Grab shop currency from cart_currency cookie (first response)
                    if shop_currency is None:
                        shop_currency = response.cookies.get("cart_currency")
                        if shop_currency:
                            logger.info(f"Detected shop currency: {shop_currency}")

                    # Extract products from response
                    products = data.get("products", [])
                    products_count = len(products)
                    logger.info(f"Found {products_count} products on page {page}")

                    if not products:
                        logger.info("No products on this page, stopping pagination")
                        break

                    all_products.extend(products)

                    # If we got less than 250 products, we've reached the end
                    if products_count < 250:
                        logger.info(f"Received {products_count} < 250 products, reached last page")
                        break

                    page += 1

                except httpx.TimeoutException:
                    logger.error(f"Timeout on page {page}, returning what we have")
                    break
                except httpx.RequestError as e:
                    logger.error(f"Request error on page {page}: {e}, returning what we have")
                    break
                except Exception as e:
                    logger.error(f"Unexpected error on page {page}: {e}, returning what we have")
                    break

        # Inject shop currency into each product (from cart_currency cookie)
        if shop_currency:
            for product in all_products:
                product["_shop_currency"] = shop_currency

        logger.info(f"Extraction complete: {len(all_products)} total products from {page - 1} pages")
        return all_products

    async def _wait(self, seconds: int) -> None:
        """Wait for specified seconds (async-friendly).

        Args:
            seconds: Number of seconds to wait
        """
        import asyncio

        await asyncio.sleep(seconds)
