"""URL discovery service for e-commerce platforms.

Uses crawl4ai for browser-based link discovery when API and sitemap strategies fail.
BestFirstCrawlingStrategy prioritizes product-like URLs via keyword scoring.
"""

from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx
from crawl4ai import AsyncWebCrawler
from crawl4ai.deep_crawling import BestFirstCrawlingStrategy, FilterChain, DomainFilter, URLPatternFilter
from crawl4ai.deep_crawling.scorers import KeywordRelevanceScorer

from app.extractors.browser_config import (
    StealthLevel,
    get_browser_config,
    get_crawl_config,
    get_crawler_strategy,
)
from app.models.enums import Platform
from app.services.sitemap_parser import SitemapParser

logger = logging.getLogger(__name__)

# Paths that are never product pages
NON_PRODUCT_PATHS = {
    "/", "/about", "/about-us", "/contact", "/contact-us", "/blog", "/cart",
    "/checkout", "/account", "/login", "/register", "/search", "/faq",
    "/privacy-policy", "/terms", "/terms-of-service", "/shipping", "/returns",
    "/sitemap", "/brands", "/categories", "/pages", "/wishlist", "/compare",
    "/basket", "/help", "/support", "/careers", "/press",
}

# Path segments that indicate non-product pages
NON_PRODUCT_SEGMENTS = {
    "checkout", "basket", "cart", "login", "register", "account",
    "blog", "faq", "help", "support", "careers", "press",
}

# Keywords that indicate product-relevant pages (used by BestFirst scorer)
PRODUCT_KEYWORDS = [
    "product", "price", "buy", "shop", "item", "cart", "add-to-cart",
    "sku", "inventory", "catalog", "collection",
]


class URLDiscoveryService:
    """Discover product URLs based on e-commerce platform.

    Strategy chain: Platform API → Sitemap → crawl4ai browser crawl.
    """

    def __init__(self, timeout: float = 30.0, stealth_level: StealthLevel = StealthLevel.STANDARD):
        self.timeout = timeout
        self.stealth_level = stealth_level
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

    async def _discover_via_crawl4ai(
        self, base_url: str, max_pages: int = 100
    ) -> list[str]:
        """Use crawl4ai BestFirstCrawlingStrategy to discover product URLs.

        Prioritizes product-like URLs via keyword scoring, filters out
        non-product pages, and crawls up to max_pages. BestFirst uses a
        priority queue so the most product-relevant URLs are visited first.

        Args:
            base_url: Shop base URL to start crawling from.
            max_pages: Maximum pages to visit (default 100).
        """
        parsed = urlparse(base_url)
        domain = parsed.netloc

        filter_chain = FilterChain([
            DomainFilter(allowed_domains=[domain]),
            URLPatternFilter(
                patterns=[
                    "*/cart*", "*/checkout*", "*/account*", "*/login*",
                    "*/register*", "*/search*", "*/blog/*", "*/faq*",
                    "*/privacy*", "*/terms*", "*/sitemap*", "*/basket*",
                    "*/help*", "*/support*", "*/careers*", "*/press*",
                    "*/wishlist*", "*/compare*",
                ],
                reverse=True,  # Exclude these patterns
            ),
        ])

        scorer = KeywordRelevanceScorer(
            keywords=PRODUCT_KEYWORDS,
            weight=0.7,
        )

        strategy = BestFirstCrawlingStrategy(
            max_depth=3,
            max_pages=max_pages,
            filter_chain=filter_chain,
            url_scorer=scorer,
            include_external=False,
        )

        browser_config = get_browser_config(self.stealth_level)
        crawl_config = get_crawl_config(
            stealth_level=self.stealth_level,
            deep_crawl_strategy=strategy,
            wait_until="domcontentloaded",
            wait_for=None,
        )

        found_urls: set[str] = set()
        try:
            crawler_strategy = get_crawler_strategy(self.stealth_level, browser_config)
            async with AsyncWebCrawler(
                config=browser_config,
                crawler_strategy=crawler_strategy,
            ) as crawler:
                results = await crawler.arun(url=base_url, config=crawl_config)
                # Deep crawl returns a list of CrawlResult
                if isinstance(results, list):
                    for result in results:
                        if result.success:
                            url = result.url
                            url_parsed = urlparse(url)
                            path = url_parsed.path.rstrip("/")
                            if path in NON_PRODUCT_PATHS:
                                continue
                            path_parts = set(path.strip("/").split("/"))
                            if path_parts & NON_PRODUCT_SEGMENTS:
                                continue
                            found_urls.add(url)
                elif hasattr(results, "success") and results.success:
                    found_urls.add(results.url)
        except Exception as e:
            logger.error("Deep crawl discovery failed for %s: %s", base_url, e)

        if found_urls:
            logger.info(
                "BestFirst crawl discovered %d candidate product URLs from %s",
                len(found_urls), base_url,
            )

        return list(found_urls)
