"""OpenGraph meta tags extractor."""

from __future__ import annotations

import logging

import httpx
from bs4 import BeautifulSoup

from app.extractors.base import BaseExtractor

logger = logging.getLogger(__name__)


class OpenGraphExtractor(BaseExtractor):
    """Extract OpenGraph meta tags from HTML."""

    @staticmethod
    def extract_from_html(html: str, url: str) -> list[dict]:
        """Extract OpenGraph tags from raw HTML content.

        Args:
            html: Raw HTML content
            url: URL for logging purposes

        Returns:
            List with single dict of extracted OG data. Empty list on error.
        """
        try:
            soup = BeautifulSoup(html, "html.parser")

            # Find all meta tags with property starting with "og:" or "product:"
            og_tags = soup.find_all("meta", property=lambda x: x and (x.startswith("og:") or x.startswith("product:")))

            if not og_tags:
                logger.debug("No OpenGraph tags found on %s", url)
                return []

            og_data = {}

            for tag in og_tags:
                property_name = tag.get("property", "")
                content = tag.get("content", "")

                if property_name and content:
                    # Store with property name as key
                    og_data[property_name] = content

            if not og_data:
                logger.debug("No valid OpenGraph data extracted from %s", url)
                return []

            return [og_data]

        except Exception as e:
            logger.exception("OpenGraph extraction failed for %s: %s", url, e)
            return []

    async def extract(self, url: str) -> list[dict]:
        """Extract OpenGraph meta tags from page.

        Args:
            url: Product page URL

        Returns:
            List with single dict of extracted OG data. Empty list on error.
        """
        try:
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                response = await client.get(url)
                response.raise_for_status()
                html = response.text

            return self.extract_from_html(html, url)

        except httpx.HTTPStatusError as e:
            logger.error("HTTP error fetching %s: %s", url, e)
            return []
        except httpx.RequestError as e:
            logger.error("Request error fetching %s: %s", url, e)
            return []
        except Exception as e:
            logger.exception("OpenGraph extraction failed for %s: %s", url, e)
            return []
