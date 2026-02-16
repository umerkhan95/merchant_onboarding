"""WooCommerce Store API product extractor using /wp-json/wc/store/v1/products endpoint."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.extractors.base import BaseExtractor
from app.extractors.browser_config import DEFAULT_HEADERS, get_default_user_agent

logger = logging.getLogger(__name__)


class WooCommerceAPIExtractor(BaseExtractor):
    """Extract products from WooCommerce stores using the Store API endpoint."""

    def __init__(self, timeout: int = 30, max_pages: int = 100):
        """Initialize the WooCommerce API extractor.

        Args:
            timeout: HTTP request timeout in seconds (default: 30)
            max_pages: Maximum number of pages to fetch (default: 100)
        """
        self.timeout = timeout
        self.max_pages = max_pages

    async def extract(self, shop_url: str) -> list[dict]:
        """Fetch all products from WooCommerce Store API with pagination.

        Args:
            shop_url: The WooCommerce store URL (e.g., https://example.com)

        Returns:
            List of raw product dicts from WooCommerce Store API
            Returns empty list on errors (404 = API not exposed, 500 = server error)
        """
        all_products: list[dict[str, Any]] = []
        base_url = shop_url.rstrip("/")

        headers = {
            **DEFAULT_HEADERS,
            "User-Agent": get_default_user_agent(),
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            page = 1

            while page <= self.max_pages:
                url = f"{base_url}/wp-json/wc/store/v1/products?per_page=100&page={page}"
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

                    # Handle 404 - Store API not available/exposed
                    if response.status_code == 404:
                        logger.warning(f"Store API not available at {url}, returning empty list")
                        break

                    # Handle server errors
                    if response.status_code >= 500:
                        logger.error(f"Server error {response.status_code} on page {page}, returning empty list")
                        break

                    if response.status_code != 200:
                        logger.warning(f"HTTP {response.status_code} on page {page}, returning what we have")
                        break

                    # Parse JSON response
                    try:
                        products = response.json()
                    except Exception as e:
                        logger.error(f"Invalid JSON on page {page}: {e}, returning what we have")
                        break

                    # WooCommerce Store API returns array directly (not wrapped)
                    if not isinstance(products, list):
                        logger.error(f"Unexpected response format on page {page}, expected list")
                        break

                    products_count = len(products)
                    logger.info(f"Found {products_count} products on page {page}")

                    if not products:
                        logger.info("No products on this page, stopping pagination")
                        break

                    all_products.extend(products)

                    # If we got less than 100 products, we've reached the end
                    if products_count < 100:
                        logger.info(f"Received {products_count} < 100 products, reached last page")
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

        logger.info(f"Extraction complete: {len(all_products)} total products from {page - 1} pages")
        return all_products

    async def _wait(self, seconds: int) -> None:
        """Wait for specified seconds (async-friendly).

        Args:
            seconds: Number of seconds to wait
        """
        import asyncio

        await asyncio.sleep(seconds)
