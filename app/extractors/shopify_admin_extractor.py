"""Shopify Admin REST API extractor using authenticated OAuth access.

Uses the Shopify Admin REST API with an OAuth access token to extract
complete product data including barcode (GTIN/EAN), inventory quantities,
and variant-level detail.

Requires a stored OAuth connection with access_token and shop_domain.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import httpx

from app.extractors.base import BaseExtractor, ExtractorResult
from app.extractors.browser_config import get_default_user_agent

logger = logging.getLogger(__name__)

_API_VERSION = "2024-10"
_PAGE_LIMIT = 250
_MAX_PAGES = 100
# Shopify leaky bucket: pause when usage exceeds this fraction of the limit
_RATE_LIMIT_THRESHOLD = 35


class ShopifyAdminExtractor(BaseExtractor):
    """Extract products from Shopify stores via authenticated Admin REST API."""

    def __init__(self, access_token: str, shop_domain: str, timeout: int = 30):
        """Initialize with OAuth credentials.

        Args:
            access_token: Shopify Admin API access token from OAuth flow.
            shop_domain: The myshopify domain (e.g. example.myshopify.com).
            timeout: HTTP request timeout in seconds.
        """
        if not access_token:
            raise ValueError("Shopify Admin extractor requires an access_token")
        if not shop_domain:
            raise ValueError("Shopify Admin extractor requires a shop_domain")
        self._access_token = access_token
        self._shop_domain = shop_domain.rstrip("/")
        self._timeout = timeout

    def _base_url(self) -> str:
        # Ensure domain has scheme
        domain = self._shop_domain
        if not domain.startswith("http"):
            domain = f"https://{domain}"
        return f"{domain}/admin/api/{_API_VERSION}"

    def _headers(self) -> dict[str, str]:
        return {
            "X-Shopify-Access-Token": self._access_token,
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": get_default_user_agent(),
        }

    async def extract(self, shop_url: str) -> ExtractorResult:
        """Fetch all active products from Shopify Admin REST API.

        Uses cursor-based pagination via the Link header (page_info parameter).
        Filters to active products only (status=active).

        Args:
            shop_url: The shop URL (used for logging/context, not for API calls).

        Returns:
            ExtractorResult with products and pagination metadata.
        """
        all_products: list[dict[str, Any]] = []
        complete = True
        error: str | None = None

        async with httpx.AsyncClient(
            timeout=self._timeout,
            headers=self._headers(),
            follow_redirects=True,
        ) as client:
            # First request uses the base URL with status filter
            next_url: str | None = (
                f"{self._base_url()}/products.json"
                f"?limit={_PAGE_LIMIT}&status=active"
            )
            page = 0

            while next_url and page < _MAX_PAGES:
                page += 1
                logger.info(
                    "Shopify Admin API: fetching page %d for %s",
                    page, self._shop_domain,
                )

                try:
                    resp = await client.get(next_url)

                    # Handle rate limiting
                    await self._handle_rate_limit(resp)

                    if resp.status_code == 429:
                        retry_after = float(resp.headers.get("Retry-After", "2"))
                        logger.warning(
                            "Shopify Admin rate limited, waiting %.1fs", retry_after
                        )
                        await asyncio.sleep(retry_after)
                        resp = await client.get(next_url)
                        if resp.status_code == 429:
                            complete = False
                            error = f"Rate limited on page {page}"
                            break

                    if resp.status_code == 401:
                        logger.error("Shopify OAuth token invalid/expired for %s", self._shop_domain)
                        return ExtractorResult(
                            products=[], complete=False, error="OAuth token invalid"
                        )

                    if resp.status_code == 403:
                        logger.error("Shopify OAuth token lacks required scopes for %s", self._shop_domain)
                        return ExtractorResult(
                            products=[], complete=False, error="OAuth token lacks read_products scope"
                        )

                    if resp.status_code != 200:
                        logger.error(
                            "Shopify Admin API HTTP %d on page %d",
                            resp.status_code, page,
                        )
                        complete = False
                        error = f"HTTP {resp.status_code} on page {page}"
                        break

                    data = resp.json()
                    products = data.get("products", [])
                    if not products:
                        break

                    all_products.extend(products)
                    logger.info(
                        "Shopify Admin API: page %d returned %d products (total: %d)",
                        page, len(products), len(all_products),
                    )

                    # Cursor-based pagination via Link header
                    next_url = self._parse_next_link(resp.headers.get("link", ""))

                except httpx.TimeoutException:
                    logger.warning("Shopify Admin API timeout on page %d", page)
                    complete = False
                    error = f"Timeout on page {page}"
                    break
                except httpx.RequestError as e:
                    logger.error(
                        "Shopify Admin API request error on page %d: %s", page, e
                    )
                    complete = False
                    error = f"Request error on page {page}: {e}"
                    break

        logger.info(
            "Shopify Admin API: extracted %d products from %d pages for %s",
            len(all_products), page, self._shop_domain,
        )
        return ExtractorResult(
            products=all_products,
            complete=complete,
            error=error,
            pages_completed=page if all_products else 0,
        )

    @staticmethod
    def _parse_next_link(link_header: str) -> str | None:
        """Parse the Link header for the next page URL.

        Shopify uses RFC 5988 Link headers for cursor-based pagination:
          <https://shop.myshopify.com/admin/api/2024-10/products.json?page_info=xxx&limit=250>; rel="next"

        Returns:
            The next page URL, or None if there is no next page.
        """
        if not link_header:
            return None

        for part in link_header.split(","):
            part = part.strip()
            if 'rel="next"' in part:
                # Extract URL between < and >
                start = part.find("<")
                end = part.find(">")
                if start != -1 and end != -1:
                    return part[start + 1 : end]
        return None

    @staticmethod
    async def _handle_rate_limit(resp: httpx.Response) -> None:
        """Respect Shopify's leaky bucket rate limit.

        The X-Shopify-Shop-Api-Call-Limit header looks like "32/40",
        meaning 32 of 40 bucket slots are used. When usage exceeds
        the threshold, pause briefly to let the bucket drain.
        """
        limit_header = resp.headers.get("X-Shopify-Shop-Api-Call-Limit", "")
        if "/" not in limit_header:
            return

        try:
            used_str, max_str = limit_header.split("/")
            used = int(used_str)
            max_limit = int(max_str)
        except (ValueError, TypeError):
            return

        if used >= _RATE_LIMIT_THRESHOLD:
            # Sleep proportionally to how full the bucket is
            fill_ratio = used / max_limit
            sleep_time = 1.0 if fill_ratio < 0.95 else 2.0
            logger.debug(
                "Shopify rate limit %d/%d, sleeping %.1fs",
                used, max_limit, sleep_time,
            )
            await asyncio.sleep(sleep_time)
