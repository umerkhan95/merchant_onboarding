"""Sitemap parser for URL discovery."""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
from dataclasses import dataclass

import httpx

logger = logging.getLogger(__name__)

# XML namespaces
SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Default URL patterns to filter for product pages
DEFAULT_PRODUCT_PATTERNS = [
    "/product",
    "/products/",
    "/shop/",
    "/p/",
    "/item/",
    "/items/",
    "/dp/",
    "/catalog/product",
    "-p-",
    "/goods/",
    "/buy/",
]


@dataclass
class SitemapEntry:
    """Represents a URL entry from a sitemap."""

    url: str
    lastmod: str | None = None
    priority: float | None = None


class SitemapParser:
    """Parse XML sitemaps to discover product URLs."""

    def __init__(
        self,
        product_patterns: list[str] | None = None,
        timeout: float = 30.0,
        max_depth: int = 3,
    ):
        """Initialize sitemap parser.

        Args:
            product_patterns: URL patterns to filter for (default: product-related paths)
            timeout: HTTP request timeout in seconds
            max_depth: Maximum recursion depth for nested sitemap indexes
        """
        self.product_patterns = product_patterns or DEFAULT_PRODUCT_PATTERNS
        self.timeout = timeout
        self.max_depth = max_depth
        self._visited_sitemaps: set[str] = set()

    async def parse(self, sitemap_url: str) -> list[SitemapEntry]:
        """Parse XML sitemap or sitemap index.

        Args:
            sitemap_url: URL of the sitemap to parse

        Returns:
            List of SitemapEntry objects filtered by product patterns.
            Returns empty list on errors.
        """
        self._visited_sitemaps.clear()
        return await self._parse_recursive(sitemap_url, depth=0)

    async def _parse_recursive(self, sitemap_url: str, depth: int = 0) -> list[SitemapEntry]:
        """Recursively parse sitemap with depth limit.

        Args:
            sitemap_url: URL of the sitemap to parse
            depth: Current recursion depth

        Returns:
            List of SitemapEntry objects
        """
        if depth > self.max_depth:
            logger.warning(f"Max recursion depth {self.max_depth} reached for sitemap: {sitemap_url}")
            return []

        if sitemap_url in self._visited_sitemaps:
            logger.debug(f"Skipping already visited sitemap: {sitemap_url}")
            return []

        self._visited_sitemaps.add(sitemap_url)

        try:
            xml_content = await self._fetch_sitemap(sitemap_url)
            if not xml_content:
                return []

            root = ET.fromstring(xml_content)

            # Check if this is a sitemap index
            if root.tag.endswith("sitemapindex"):
                return await self._parse_sitemap_index(root, depth)

            # Otherwise, parse as regular sitemap
            return self._parse_urlset(root)

        except ET.ParseError as e:
            logger.error(f"XML parse error for {sitemap_url}: {e}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error parsing sitemap {sitemap_url}: {e}")
            return []

    async def _fetch_sitemap(self, url: str) -> str | None:
        """Fetch sitemap XML content.

        Args:
            url: Sitemap URL

        Returns:
            XML content as string, or None on error
        """
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(url)
                response.raise_for_status()
                return response.text
        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error fetching sitemap {url}: {e.response.status_code}")
            return None
        except httpx.RequestError as e:
            logger.error(f"Request error fetching sitemap {url}: {e}")
            return None
        except Exception as e:
            logger.error(f"Unexpected error fetching sitemap {url}: {e}")
            return None

    async def _parse_sitemap_index(self, root: ET.Element, depth: int) -> list[SitemapEntry]:
        """Parse sitemap index and recursively fetch child sitemaps.

        Args:
            root: XML root element of sitemap index
            depth: Current recursion depth

        Returns:
            Aggregated list of SitemapEntry objects from all child sitemaps
        """
        entries = []

        # Find all <sitemap> elements
        sitemap_elements = root.findall(".//sm:sitemap", SITEMAP_NS)
        if not sitemap_elements:
            # Try without namespace
            sitemap_elements = root.findall(".//sitemap")

        logger.info(f"Found {len(sitemap_elements)} child sitemaps in index")

        for sitemap_elem in sitemap_elements:
            loc_elem = sitemap_elem.find("sm:loc", SITEMAP_NS)
            if loc_elem is None:
                loc_elem = sitemap_elem.find("loc")

            if loc_elem is not None and loc_elem.text:
                child_url = loc_elem.text.strip()
                logger.debug(f"Parsing child sitemap: {child_url}")
                child_entries = await self._parse_recursive(child_url, depth + 1)
                entries.extend(child_entries)

        return entries

    def _parse_urlset(self, root: ET.Element) -> list[SitemapEntry]:
        """Parse regular sitemap urlset.

        Args:
            root: XML root element of urlset

        Returns:
            List of SitemapEntry objects filtered by product patterns
        """
        entries = []

        # Find all <url> elements
        url_elements = root.findall(".//sm:url", SITEMAP_NS)
        if not url_elements:
            # Try without namespace
            url_elements = root.findall(".//url")

        logger.debug(f"Found {len(url_elements)} URLs in sitemap")

        for url_elem in url_elements:
            # Extract <loc>
            loc_elem = url_elem.find("sm:loc", SITEMAP_NS)
            if loc_elem is None:
                loc_elem = url_elem.find("loc")

            if loc_elem is None or not loc_elem.text:
                continue

            url = loc_elem.text.strip()

            # Filter by product patterns
            if not self._is_product_url(url):
                continue

            # Extract <lastmod>
            lastmod_elem = url_elem.find("sm:lastmod", SITEMAP_NS)
            if lastmod_elem is None:
                lastmod_elem = url_elem.find("lastmod")
            lastmod = lastmod_elem.text.strip() if lastmod_elem is not None and lastmod_elem.text else None

            # Extract <priority>
            priority_elem = url_elem.find("sm:priority", SITEMAP_NS)
            if priority_elem is None:
                priority_elem = url_elem.find("priority")

            priority = None
            if priority_elem is not None and priority_elem.text:
                try:
                    priority = float(priority_elem.text.strip())
                except ValueError:
                    priority = None

            entries.append(SitemapEntry(url=url, lastmod=lastmod, priority=priority))

        logger.info(f"Filtered {len(entries)} product URLs from sitemap")
        return entries

    def _is_product_url(self, url: str) -> bool:
        """Check if URL matches product patterns.

        Args:
            url: URL to check

        Returns:
            True if URL contains any product pattern
        """
        url_lower = url.lower()
        return any(pattern.lower() in url_lower for pattern in self.product_patterns)
