"""Magento 2 API product extractor using REST API endpoint."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.extractors.base import BaseExtractor
from app.extractors.browser_config import DEFAULT_HEADERS, get_default_user_agent

logger = logging.getLogger(__name__)


class MagentoAPIExtractor(BaseExtractor):
    """Extract products from Magento 2 stores using the REST API endpoint."""

    def __init__(self, timeout: int = 30, page_size: int = 100):
        """Initialize the Magento API extractor.

        Args:
            timeout: HTTP request timeout in seconds (default: 30)
            page_size: Number of products per page (default: 100)
        """
        self.timeout = timeout
        self.page_size = page_size

    async def extract(self, shop_url: str) -> list[dict]:
        """Fetch all products from Magento 2 REST API with pagination.

        Args:
            shop_url: The Magento store URL (e.g., https://example.com)

        Returns:
            List of raw product dicts from Magento API
            Returns empty list on errors
        """
        all_products: list[dict[str, Any]] = []
        base_url = shop_url.rstrip("/")
        current_page = 1

        headers = {
            **DEFAULT_HEADERS,
            "User-Agent": get_default_user_agent(),
            "Accept": "application/json",
        }

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers=headers) as client:
            while True:
                url = (
                    f"{base_url}/rest/V1/products?"
                    f"searchCriteria[pageSize]={self.page_size}&"
                    f"searchCriteria[currentPage]={current_page}"
                )
                logger.info(f"Fetching page {current_page} from {url}")

                try:
                    response = await client.get(url)

                    # Handle 404 - API not available or not exposed
                    if response.status_code == 404:
                        logger.warning(f"Received 404 for {url}, API not available")
                        break

                    # Handle rate limiting (429)
                    if response.status_code == 429:
                        logger.warning(f"Rate limited on page {current_page}, stopping extraction")
                        break

                    # Handle server errors
                    if response.status_code >= 500:
                        logger.error(
                            f"Server error {response.status_code} on page {current_page}, stopping extraction"
                        )
                        break

                    # Handle other errors
                    if response.status_code != 200:
                        logger.warning(
                            f"HTTP {response.status_code} on page {current_page}, returning what we have"
                        )
                        break

                    # Parse JSON response
                    try:
                        data = response.json()
                    except Exception as e:
                        logger.error(f"Invalid JSON on page {current_page}: {e}, returning what we have")
                        break

                    # Extract products and total count from response
                    products = data.get("items", [])
                    total_count = data.get("total_count", 0)
                    products_count = len(products)

                    logger.info(
                        f"Found {products_count} products on page {current_page}, "
                        f"total in catalog: {total_count}"
                    )

                    if not products:
                        logger.info("No products on this page, stopping pagination")
                        break

                    all_products.extend(products)

                    # Check if we've fetched all products
                    if len(all_products) >= total_count:
                        logger.info(f"Fetched all {len(all_products)} products (total: {total_count})")
                        break

                    current_page += 1

                except httpx.TimeoutException:
                    logger.error(f"Timeout on page {current_page}, returning what we have")
                    break
                except httpx.RequestError as e:
                    logger.error(f"Request error on page {current_page}: {e}, returning what we have")
                    break
                except Exception as e:
                    logger.error(f"Unexpected error on page {current_page}: {e}, returning what we have")
                    break

        logger.info(
            f"Extraction complete: {len(all_products)} total products from {current_page} pages"
        )
        return all_products
