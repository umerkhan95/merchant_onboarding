"""OpenGraph meta tags extractor."""

from __future__ import annotations

import logging

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


class OpenGraphExtractor:
    """Extract OpenGraph meta tags from HTML.

    The ``extract(url)`` instance method has been removed -- pipeline and
    UnifiedCrawl call the static methods directly (``extract_from_html``,
    ``from_metadata``).
    """

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

