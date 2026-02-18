"""Schema.org JSON-LD structured data extractor."""

from __future__ import annotations

import json
import logging

import httpx
from bs4 import BeautifulSoup

from app.config import MAX_RESPONSE_SIZE
from app.extractors.base import BaseExtractor, ExtractorResult
from app.extractors.browser_config import (
    DEFAULT_HEADERS,
    fetch_html_with_browser,
    get_default_user_agent,
)

logger = logging.getLogger(__name__)


class SchemaOrgExtractor(BaseExtractor):
    """Extract JSON-LD structured data from <script type='application/ld+json'> tags."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client

    @staticmethod
    def _is_product_type(type_value) -> bool:
        """Check if JSON-LD @type indicates a Product (handles arrays and IRIs)."""
        if isinstance(type_value, str):
            return "Product" in type_value
        if isinstance(type_value, list):
            return any("Product" in str(t) for t in type_value)
        return False

    @staticmethod
    def _extract_og_meta(soup: BeautifulSoup) -> dict[str, str]:
        """Extract OpenGraph meta tags from page as a fallback data source.

        Returns:
            Dict of OG properties (e.g., {"og:image": "https://...", "og:title": "..."})
        """
        og_data: dict[str, str] = {}
        for meta in soup.find_all("meta", attrs={"property": True}):
            prop = meta.get("property", "")
            content = meta.get("content", "")
            if prop.startswith("og:") and content:
                og_data[prop] = content.strip()
        return og_data

    @staticmethod
    def extract_from_html(html: str, url: str) -> list[dict]:
        """Extract JSON-LD from raw HTML content.

        Enriches sparse JSON-LD products with OpenGraph meta tags from the same
        page. This handles sites (like Bombas) that embed minimal JSON-LD stubs
        on some pages but still include og:image and other OG tags.

        Args:
            html: Raw HTML content
            url: URL for logging purposes

        Returns:
            List of raw Product JSON-LD dicts. Empty list on error or if no Product found.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")
            script_tags = soup.find_all("script", type="application/ld+json")

            if not script_tags:
                logger.debug("No JSON-LD script tags found on %s", url)
                return []

            products = []

            for script in script_tags:
                try:
                    data = json.loads(script.string)

                    # Handle single object
                    if isinstance(data, dict):
                        if SchemaOrgExtractor._is_product_type(data.get("@type")):
                            products.append(data)
                        # Handle @graph array (common pattern)
                        elif "@graph" in data and isinstance(data["@graph"], list):
                            for item in data["@graph"]:
                                if isinstance(item, dict) and SchemaOrgExtractor._is_product_type(item.get("@type")):
                                    products.append(item)

                    # Handle array of objects
                    elif isinstance(data, list):
                        for item in data:
                            if isinstance(item, dict) and SchemaOrgExtractor._is_product_type(item.get("@type")):
                                products.append(item)

                except json.JSONDecodeError as e:
                    logger.warning("Failed to parse JSON-LD from %s: %s", url, e)
                    continue
                except Exception as e:
                    logger.warning("Error processing JSON-LD script from %s: %s", url, e)
                    continue

            if not products:
                logger.debug("No Product objects found in JSON-LD on %s", url)
                return products

            # Enrich sparse JSON-LD with OG meta tags from the same page
            og_data = SchemaOrgExtractor._extract_og_meta(soup)
            if og_data:
                for product in products:
                    # Fill missing image from og:image
                    if not product.get("image") and og_data.get("og:image"):
                        product["og:image"] = og_data["og:image"]
                    # Fill missing URL from og:url
                    if not product.get("url") and og_data.get("og:url"):
                        product["url"] = og_data["og:url"]
                    # Fill missing description from og:description
                    if not product.get("description") and og_data.get("og:description"):
                        product["description"] = og_data["og:description"]

            return products

        except Exception as e:
            logger.exception("Schema.org extraction failed for %s: %s", url, e)
            return []

    async def extract(self, url: str, html: str | None = None) -> ExtractorResult:
        """Extract JSON-LD structured data from page.

        When pre-fetched HTML is provided, skips the HTTP fetch entirely and parses
        the given HTML directly. Otherwise, tries httpx first (fast) and falls back
        to browser on HTTP errors (403, timeout) indicating bot protection.

        Responses exceeding MAX_RESPONSE_SIZE are rejected to prevent memory exhaustion.

        Args:
            url: Product page URL
            html: Optional pre-fetched HTML content (skips HTTP fetch when provided)

        Returns:
            ExtractorResult with Product JSON-LD dicts.
        """
        if html is not None:
            products = self.extract_from_html(html, url)
            return ExtractorResult(products=products)

        try:
            headers = {**DEFAULT_HEADERS, "User-Agent": get_default_user_agent()}
            client = self._client or httpx.AsyncClient(
                follow_redirects=True, timeout=30.0, headers=headers
            )
            try:
                response = await client.get(url)
                response.raise_for_status()
                content_length = int(response.headers.get("content-length", 0))
                if content_length > MAX_RESPONSE_SIZE:
                    logger.warning(
                        "Response too large (%d bytes) from %s, skipping",
                        content_length,
                        url,
                    )
                    return ExtractorResult(products=[], complete=False, error=f"Response too large ({content_length} bytes)")
                html = response.text
                if len(html) > MAX_RESPONSE_SIZE:
                    logger.warning(
                        "Response body too large (%d chars) from %s, skipping",
                        len(html),
                        url,
                    )
                    return ExtractorResult(products=[], complete=False, error=f"Response body too large ({len(html)} chars)")
            finally:
                if self._client is None:
                    await client.aclose()

            products = self.extract_from_html(html, url)
            return ExtractorResult(products=products)

        except httpx.HTTPStatusError as e:
            if e.response.status_code in (403, 429, 503):
                logger.warning("Schema.org blocked (%d) for %s, trying browser fallback", e.response.status_code, url)
                html = await fetch_html_with_browser(url)
                if html:
                    products = self.extract_from_html(html, url)
                    return ExtractorResult(products=products)
            else:
                logger.error("HTTP %d fetching %s", e.response.status_code, url)
            return ExtractorResult(products=[], complete=False, error=f"HTTP {e.response.status_code}")
        except httpx.RequestError as e:
            logger.error("Request error fetching %s: %s", url, e)
            return ExtractorResult(products=[], complete=False, error=f"Request error: {e}")
        except Exception as e:
            logger.exception("Schema.org extraction failed for %s: %s", url, e)
            return ExtractorResult(products=[], complete=False, error=str(e))
