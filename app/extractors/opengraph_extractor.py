"""OpenGraph meta tags extractor."""

from __future__ import annotations

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


class OpenGraphExtractor(BaseExtractor):
    """Extract OpenGraph meta tags from HTML."""

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client

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

    @staticmethod
    def from_metadata(metadata: dict) -> list[dict]:
        """Build OG data from crawl4ai CrawlResult.metadata (avoids re-fetching).

        crawl4ai's extract_metadata_using_lxml() extracts all og:* tags into
        the metadata dict. This method filters for OG keys and returns them
        in the same format as extract_from_html().

        Note: product:* namespace tags are NOT extracted by crawl4ai — use the
        standalone extract() path for those.

        Args:
            metadata: Dict from CrawlResult.metadata

        Returns:
            List with single dict of OG data, or empty list if no OG keys found.
        """
        if not metadata:
            return []

        og_data = {
            k: v for k, v in metadata.items()
            if isinstance(k, str) and k.startswith("og:") and v
        }
        return [og_data] if og_data else []

    async def extract(self, url: str, html: str | None = None) -> ExtractorResult:
        """Extract OpenGraph meta tags from page.

        When pre-fetched HTML is provided, skips the HTTP fetch entirely and parses
        the given HTML directly. Otherwise, tries httpx first (fast) and falls back
        to browser on HTTP errors (403, timeout) indicating bot protection.

        Responses exceeding MAX_RESPONSE_SIZE are rejected to prevent memory exhaustion.

        Args:
            url: Product page URL
            html: Optional pre-fetched HTML content (skips HTTP fetch when provided)

        Returns:
            ExtractorResult with OG data dict.
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
                logger.warning("OpenGraph blocked (%d) for %s, trying browser fallback", e.response.status_code, url)
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
            logger.exception("OpenGraph extraction failed for %s: %s", url, e)
            return ExtractorResult(products=[], complete=False, error=str(e))
