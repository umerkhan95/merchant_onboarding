"""OpenGraph meta tags extractor."""

from __future__ import annotations

import logging

import httpx
from bs4 import BeautifulSoup

from app.config import MAX_RESPONSE_SIZE
from app.extractors.base import BaseExtractor
from app.extractors.browser_config import (
    DEFAULT_HEADERS,
    fetch_html_with_browser,
    get_default_user_agent,
)

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

        Tries httpx first (fast). Falls back to browser on HTTP errors (403, timeout)
        which indicate bot protection or JS-rendered content.

        Responses exceeding MAX_RESPONSE_SIZE are rejected to prevent memory exhaustion.

        Args:
            url: Product page URL

        Returns:
            List with single dict of extracted OG data. Empty list on error.
        """
        try:
            headers = {**DEFAULT_HEADERS, "User-Agent": get_default_user_agent()}
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0, headers=headers) as client:
                response = await client.get(url)
                response.raise_for_status()
                content_length = int(response.headers.get("content-length", 0))
                if content_length > MAX_RESPONSE_SIZE:
                    logger.warning(
                        "Response too large (%d bytes) from %s, skipping",
                        content_length,
                        url,
                    )
                    return []
                html = response.text
                if len(html) > MAX_RESPONSE_SIZE:
                    logger.warning(
                        "Response body too large (%d chars) from %s, skipping",
                        len(html),
                        url,
                    )
                    return []

            return self.extract_from_html(html, url)

        except httpx.HTTPStatusError as e:
            if e.response.status_code in (403, 429, 503):
                logger.warning("OpenGraph blocked (%d) for %s, trying browser fallback", e.response.status_code, url)
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
            logger.exception("OpenGraph extraction failed for %s: %s", url, e)
            return []
