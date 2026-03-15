"""WooCommerce Store API product extractor using /wp-json/wc/store/v1/products endpoint."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.extractors.base import BaseExtractor, ExtractorResult
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

    async def extract(self, shop_url: str) -> ExtractorResult:
        """Fetch all products from WooCommerce Store API with pagination.

        Args:
            shop_url: The WooCommerce store URL (e.g., https://example.com)

        Returns:
            ExtractorResult with products and pagination metadata
        """
        all_products: list[dict[str, Any]] = []
        base_url = shop_url.rstrip("/")
        complete = True
        error: str | None = None

        headers = {
            **DEFAULT_HEADERS,
            "User-Agent": get_default_user_agent(),
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            page = 1

            while page <= self.max_pages:
                url = f"{base_url}/wp-json/wc/store/v1/products?per_page=100&page={page}"
                logger.info("Fetching page %s from %s", page, url)

                try:
                    response = await client.get(url)

                    # Handle rate limiting (429) - retry once
                    if response.status_code == 429:
                        logger.warning("Rate limited on page %s, waiting and retrying once", page)
                        retry_after = int(response.headers.get("Retry-After", "2"))
                        await self._wait(retry_after)

                        response = await client.get(url)
                        if response.status_code == 429:
                            logger.error("Rate limited again on page %s, stopping extraction", page)
                            complete = False
                            error = f"Rate limited on page {page}"
                            break

                    # Handle 404 - Store API not available/exposed
                    if response.status_code == 404:
                        logger.warning("Store API not available at %s, returning empty list", url)
                        if not all_products:
                            complete = False
                            error = "Store API not available (404)"
                        break

                    # Handle server errors
                    if response.status_code >= 500:
                        logger.error("Server error %s on page %s, returning empty list", response.status_code, page)
                        complete = False
                        error = f"Server error {response.status_code} on page {page}"
                        break

                    if response.status_code != 200:
                        logger.warning("HTTP %s on page %s, returning what we have", response.status_code, page)
                        complete = False
                        error = f"HTTP {response.status_code} on page {page}"
                        break

                    # Parse JSON response
                    try:
                        products = response.json()
                    except Exception as e:
                        logger.error("Invalid JSON on page %s: %s, returning what we have", page, e)
                        complete = False
                        error = f"Invalid JSON on page {page}: {e}"
                        break

                    # WooCommerce Store API returns array directly (not wrapped)
                    if not isinstance(products, list):
                        logger.error("Unexpected response format on page %s, expected list", page)
                        complete = False
                        error = f"Unexpected response format on page {page}"
                        break

                    products_count = len(products)
                    logger.info("Found %s products on page %s", products_count, page)

                    if not products:
                        logger.info("No products on this page, stopping pagination")
                        break

                    all_products.extend(products)

                    # If we got less than 100 products, we've reached the end
                    if products_count < 100:
                        logger.info("Received %s < 100 products, reached last page", products_count)
                        break

                    page += 1

                except httpx.TimeoutException:
                    logger.warning(
                        "Timeout on page %d, returning %d products from %d pages (may be incomplete)",
                        page,
                        len(all_products),
                        page - 1,
                    )
                    complete = False
                    error = f"Timeout on page {page}"
                    break
                except httpx.RequestError as e:
                    logger.error("Request error on page %s: %s, returning what we have", page, e)
                    complete = False
                    error = f"Request error on page {page}: {e}"
                    break
                except Exception as e:
                    logger.error("Unexpected error on page %s: %s, returning what we have", page, e)
                    complete = False
                    error = f"Unexpected error on page {page}: {e}"
                    break

        logger.info("Extraction complete: %s total products from %s pages", len(all_products), page - 1)
        return ExtractorResult(
            products=all_products,
            complete=complete,
            error=error,
            pages_completed=page - 1 if page > 1 else (1 if all_products else 0),
        )

    async def _wait(self, seconds: int) -> None:
        """Wait for specified seconds (async-friendly).

        Args:
            seconds: Number of seconds to wait
        """
        import asyncio

        await asyncio.sleep(seconds)
