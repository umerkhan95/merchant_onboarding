"""Schema.org JSON-LD structured data extractor."""

from __future__ import annotations

import json
import logging

import httpx
from bs4 import BeautifulSoup

from app.extractors.base import BaseExtractor
from app.extractors.browser_config import (
    DEFAULT_HEADERS,
    get_default_user_agent,
    fetch_html_with_browser,
)

logger = logging.getLogger(__name__)


class SchemaOrgExtractor(BaseExtractor):
    """Extract JSON-LD structured data from <script type='application/ld+json'> tags."""

    @staticmethod
    def _is_product_type(type_value) -> bool:
        """Check if JSON-LD @type indicates a Product (handles arrays and IRIs)."""
        if isinstance(type_value, str):
            return "Product" in type_value
        if isinstance(type_value, list):
            return any("Product" in str(t) for t in type_value)
        return False

    @staticmethod
    def extract_from_html(html: str, url: str) -> list[dict]:
        """Extract JSON-LD from raw HTML content.

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

        except Exception as e:
            logger.exception("Schema.org extraction failed for %s: %s", url, e)
            return []

    async def extract(self, url: str) -> list[dict]:
        """Extract JSON-LD structured data from page.

        Tries httpx first (fast). Falls back to browser on HTTP errors (403, timeout)
        which indicate bot protection or JS-rendered content.

        Args:
            url: Product page URL

        Returns:
            List of raw Product JSON-LD dicts. Empty list on error or if no Product found.
        """
        try:
            headers = {**DEFAULT_HEADERS, "User-Agent": get_default_user_agent()}
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, headers=headers) as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text

            return self.extract_from_html(html, url)

        except httpx.HTTPStatusError as e:
            if e.response.status_code in (403, 429, 503):
                logger.warning("Schema.org blocked (%d) for %s, trying browser fallback", e.response.status_code, url)
                html = await fetch_html_with_browser(url)
                if html:
                    return self.extract_from_html(html, url)
            else:
                logger.error("HTTP %d fetching %s", e.response.status_code, url)
            return []
        except httpx.RequestError as e:
            logger.error("Request error fetching %s: %s", url, e)
            return []
        except Exception as e:
            logger.exception("Schema.org extraction failed for %s: %s", url, e)
            return []
