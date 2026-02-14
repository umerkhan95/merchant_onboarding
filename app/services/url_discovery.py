"""URL discovery service for e-commerce platforms.

Uses crawl4ai for browser-based link discovery when API and sitemap strategies fail.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig

from app.models.enums import Platform
from app.services.sitemap_parser import SitemapParser

logger = logging.getLogger(__name__)

# Paths that are never product pages
NON_PRODUCT_PATHS = {
    "/", "/about", "/about-us", "/contact", "/contact-us", "/blog", "/cart",
    "/checkout", "/account", "/login", "/register", "/search", "/faq",
    "/privacy-policy", "/terms", "/terms-of-service", "/shipping", "/returns",
    "/sitemap", "/brands", "/categories", "/pages",
}


class URLDiscoveryService:
    """Discover product URLs based on e-commerce platform.

    Strategy chain: Platform API → Sitemap → crawl4ai browser crawl.
    """

    def __init__(self, timeout: float = 30.0):
        self.timeout = timeout
        self.sitemap_parser = SitemapParser(timeout=timeout)

    async def discover(self, base_url: str, platform: Platform) -> list[str]:
        """Discover product URLs based on platform.

        Returns:
            List of product URLs or API endpoints to scrape.
        """
        base_url = base_url.rstrip("/")
        logger.info(f"Discovering URLs for {base_url} (platform: {platform})")

        try:
            if platform == Platform.SHOPIFY:
                return await self._discover_shopify(base_url)
            elif platform == Platform.WOOCOMMERCE:
                return await self._discover_woocommerce(base_url)
            elif platform == Platform.MAGENTO:
                return await self._discover_magento(base_url)
            elif platform == Platform.BIGCOMMERCE:
                return await self._discover_bigcommerce(base_url)
            else:
                return await self._discover_generic(base_url)
        except Exception as e:
            logger.error(f"Error discovering URLs for {base_url}: {e}")
            return []

    # ── Platform-specific strategies ──────────────────────────────────

    async def _discover_shopify(self, base_url: str) -> list[str]:
        """Shopify: /products.json API with pagination."""
        api_url = f"{base_url}/products.json?limit=250&page=1"

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(api_url)
                response.raise_for_status()
                data = response.json()

                products = data.get("products", [])
                product_count = len(products)
                logger.info(f"Shopify first page returned {product_count} products")

                urls = [f"{base_url}/products.json?limit=250&page=1"]
                if product_count == 250:
                    for page in range(2, 11):
                        urls.append(f"{base_url}/products.json?limit=250&page={page}")
                    logger.info(f"Generated {len(urls)} Shopify API pagination URLs")

                return urls

        except httpx.HTTPStatusError as e:
            logger.warning(f"Shopify API not accessible ({e.response.status_code}), falling back to sitemap")
            return await self._discover_via_sitemap(base_url)
        except Exception as e:
            logger.error(f"Error probing Shopify API: {e}")
            return await self._discover_via_sitemap(base_url)

    async def _discover_woocommerce(self, base_url: str) -> list[str]:
        """WooCommerce: Store API → sitemap → crawl4ai."""
        api_url = f"{base_url}/wp-json/wc/store/v1/products"

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(api_url)
                response.raise_for_status()
                logger.info(f"WooCommerce Store API accessible at {api_url}")
                return [api_url]
        except Exception as e:
            logger.warning(f"WooCommerce API not accessible: {e}, falling back to sitemap")

        urls = await self._discover_via_sitemap(base_url)
        if urls:
            return urls

        logger.info(f"No sitemap products for {base_url}, falling back to crawl4ai")
        return await self._discover_via_crawl4ai(base_url)

    async def _discover_magento(self, base_url: str) -> list[str]:
        """Magento: REST API → sitemap → crawl4ai."""
        api_url = f"{base_url}/rest/V1/products?searchCriteria[pageSize]=100"

        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(api_url)
                response.raise_for_status()
                logger.info(f"Magento REST API accessible at {api_url}")
                return [api_url]
        except Exception as e:
            logger.warning(f"Magento API not accessible: {e}, falling back to sitemap")

        urls = await self._discover_via_sitemap(base_url)
        if urls:
            return urls

        logger.info(f"No sitemap products for {base_url}, falling back to crawl4ai")
        return await self._discover_via_crawl4ai(base_url)

    async def _discover_bigcommerce(self, base_url: str) -> list[str]:
        """BigCommerce: sitemap → crawl4ai (flat URL structure, no /product/ prefix)."""
        urls = await self._discover_via_sitemap(base_url)
        if urls:
            return urls

        logger.info(f"No sitemap for {base_url}, falling back to crawl4ai")
        return await self._discover_via_crawl4ai(base_url)

    async def _discover_generic(self, base_url: str) -> list[str]:
        """Generic: sitemap → crawl4ai → base URL fallback."""
        urls = await self._discover_via_sitemap(base_url)
        if urls:
            return urls

        urls = await self._discover_via_crawl4ai(base_url)
        if urls:
            return urls

        logger.info(f"No URLs discovered for {base_url}, returning base URL for crawling")
        return [base_url]

    # ── Sitemap discovery ─────────────────────────────────────────────

    async def _discover_via_sitemap(self, base_url: str) -> list[str]:
        """Try common sitemap locations to find product URLs."""
        sitemap_urls = [
            f"{base_url}/sitemap.xml",
            f"{base_url}/sitemap_index.xml",
            f"{base_url}/product-sitemap.xml",
            f"{base_url}/sitemap-products.xml",
            f"{base_url}/pub/media/sitemap/sitemap.xml",
            f"{base_url}/media/sitemap.xml",
            f"{base_url}/xmlsitemap.xml",
        ]

        all_entries = []
        for sitemap_url in sitemap_urls:
            entries = await self.sitemap_parser.parse(sitemap_url)
            if entries:
                logger.info(f"Found {len(entries)} product URLs in {sitemap_url}")
                all_entries.extend(entries)

        unique_urls = list({entry.url for entry in all_entries})
        if unique_urls:
            logger.info(f"Total unique product URLs from sitemaps: {len(unique_urls)}")
        return unique_urls

    # ── crawl4ai browser-based discovery ──────────────────────────────

    async def _discover_via_crawl4ai(self, base_url: str) -> list[str]:
        """Use crawl4ai to render the storefront and extract internal product links.

        crawl4ai handles JavaScript-rendered pages, anti-bot measures, and
        returns internal/external links from the rendered DOM.
        """
        parsed = urlparse(base_url)
        base_domain = parsed.netloc

        browser_config = BrowserConfig(headless=True, verbose=False)
        crawl_config = CrawlerRunConfig(cache_mode="bypass")

        found_urls: set[str] = set()

        try:
            async with AsyncWebCrawler(config=browser_config) as crawler:
                # Crawl the storefront homepage
                result = await crawler.arun(url=base_url, config=crawl_config)

                if not result.success:
                    logger.warning(f"crawl4ai failed for {base_url}: {result.error_message}")
                    return []

                # Extract internal links from crawl4ai result
                internal_links = result.links.get("internal", [])
                logger.info(f"crawl4ai found {len(internal_links)} internal links on {base_url}")

                for link_data in internal_links:
                    href = link_data.get("href", "") if isinstance(link_data, dict) else getattr(link_data, "href", "")
                    if not href:
                        continue

                    # Filter out non-product pages
                    link_parsed = urlparse(href)
                    path = link_parsed.path.rstrip("/")

                    # Skip empty, anchor-only, and non-product paths
                    if not path or path in NON_PRODUCT_PATHS:
                        continue

                    # Skip category-like paths (e.g., /blog/*, /categories/*)
                    if any(path.startswith(skip) for skip in ("/blog/", "/category/", "/categories/", "/brands/")):
                        continue

                    # Must be same domain
                    if link_parsed.netloc and link_parsed.netloc != base_domain:
                        continue

                    found_urls.add(href)

        except Exception as e:
            logger.error(f"crawl4ai discovery failed for {base_url}: {e}")
            return []

        if found_urls:
            logger.info(f"crawl4ai discovered {len(found_urls)} candidate product URLs")

        return list(found_urls)
