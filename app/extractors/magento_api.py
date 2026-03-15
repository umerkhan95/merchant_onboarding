"""Magento 2 API product extractor using REST API endpoint."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.extractors.base import BaseExtractor, ExtractorResult
from app.extractors.browser_config import DEFAULT_HEADERS, get_default_user_agent

logger = logging.getLogger(__name__)


class MagentoAPIExtractor(BaseExtractor):
    """Extract products from Magento 2 stores using the REST API endpoint."""

    def __init__(self, timeout: int = 30, page_size: int = 100, max_pages: int = 100):
        """Initialize the Magento API extractor.

        Args:
            timeout: HTTP request timeout in seconds (default: 30)
            page_size: Number of products per page (default: 100)
            max_pages: Maximum number of pages to fetch (default: 100)
        """
        self.timeout = timeout
        self.page_size = page_size
        self.max_pages = max_pages

    async def extract(self, shop_url: str) -> ExtractorResult:
        """Fetch all products from Magento 2 REST API with pagination.

        Args:
            shop_url: The Magento store URL (e.g., https://example.com)

        Returns:
            ExtractorResult with products and pagination metadata
        """
        all_products: list[dict[str, Any]] = []
        base_url = shop_url.rstrip("/")
        current_page = 1
        complete = True
        error: str | None = None
        total_count: int = 0
        import math

        headers = {
            **DEFAULT_HEADERS,
            "User-Agent": get_default_user_agent(),
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            while current_page <= self.max_pages:
                url = (
                    f"{base_url}/rest/V1/products?"
                    f"searchCriteria[pageSize]={self.page_size}&"
                    f"searchCriteria[currentPage]={current_page}"
                )
                logger.info("Fetching page %s from %s", current_page, url)

                try:
                    response = await client.get(url)

                    # Handle 404 - API not available or not exposed
                    if response.status_code == 404:
                        logger.warning("Received 404 for %s, API not available", url)
                        if not all_products:
                            complete = False
                            error = "API not available (404)"
                        break

                    # Handle rate limiting (429)
                    if response.status_code == 429:
                        logger.warning("Rate limited on page %s, stopping extraction", current_page)
                        complete = False
                        error = f"Rate limited on page {current_page}"
                        break

                    # Handle server errors
                    if response.status_code >= 500:
                        logger.error(
                            "Server error %d on page %d, stopping extraction",
                            response.status_code, current_page,
                        )
                        complete = False
                        error = f"Server error {response.status_code} on page {current_page}"
                        break

                    # Handle other errors
                    if response.status_code != 200:
                        logger.warning(
                            "HTTP %d on page %d, returning what we have",
                            response.status_code, current_page,
                        )
                        complete = False
                        error = f"HTTP {response.status_code} on page {current_page}"
                        break

                    # Parse JSON response
                    try:
                        data = response.json()
                    except Exception as e:
                        logger.error("Invalid JSON on page %s: %s, returning what we have", current_page, e)
                        complete = False
                        error = f"Invalid JSON on page {current_page}: {e}"
                        break

                    # Extract products and total count from response
                    products = data.get("items", [])
                    total_count = data.get("total_count", 0)
                    products_count = len(products)

                    logger.info(
                        "Found %d products on page %d, total in catalog: %d",
                        products_count, current_page, total_count,
                    )

                    if not products:
                        logger.info("No products on this page, stopping pagination")
                        break

                    all_products.extend(products)

                    # Check if we've fetched all products
                    if len(all_products) >= total_count:
                        logger.info("Fetched all %s products (total: %s)", len(all_products), total_count)
                        break

                    current_page += 1

                except httpx.TimeoutException:
                    logger.warning(
                        "Timeout on page %d, returning %d products from %d pages (may be incomplete)",
                        current_page,
                        len(all_products),
                        current_page - 1,
                    )
                    complete = False
                    error = f"Timeout on page {current_page}"
                    break
                except httpx.RequestError as e:
                    logger.error("Request error on page %s: %s, returning what we have", current_page, e)
                    complete = False
                    error = f"Request error on page {current_page}: {e}"
                    break
                except Exception as e:
                    logger.error("Unexpected error on page %s: %s, returning what we have", current_page, e)
                    complete = False
                    error = f"Unexpected error on page {current_page}: {e}"
                    break

        if current_page > self.max_pages:
            logger.warning(
                "Reached max_pages limit (%d), stopping pagination with %d products (may be incomplete)",
                self.max_pages,
                len(all_products),
            )
            complete = False
            error = f"Reached max_pages limit ({self.max_pages})"

        pages_expected = (
            math.ceil(total_count / self.page_size) if total_count else None
        )

        logger.info(
            "Extraction complete: %d total products from %d pages",
            len(all_products), current_page,
        )
        return ExtractorResult(
            products=all_products,
            complete=complete,
            error=error,
            pages_completed=current_page - 1 if current_page > 1 else (1 if all_products else 0),
            pages_expected=pages_expected,
        )
