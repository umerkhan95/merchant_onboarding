"""URL discovery service for e-commerce platforms.

Uses platform-specific product sitemaps, crawl4ai AsyncUrlSeeder for generic
sitemap discovery, and BestFirstCrawlingStrategy for browser-based link
discovery when API and sitemap strategies fail.

Non-product URLs (blog posts, about pages, etc.) are filtered via a shared
denylist in ``url_filters``.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import urlparse

import defusedxml.ElementTree as ET
from defusedxml.common import DefusedXmlException
import httpx
from crawl4ai import AsyncUrlSeeder, AsyncWebCrawler, SeedingConfig
from crawl4ai.deep_crawling import (
    BestFirstCrawlingStrategy,
    DomainFilter,
    FilterChain,
    URLPatternFilter,
)
from crawl4ai.deep_crawling.scorers import KeywordRelevanceScorer

from app.config import MAX_RESPONSE_SIZE
from app.extractors.browser_config import (
    StealthLevel,
    get_browser_config,
    get_crawl_config,
    get_crawler_strategy,
)
from app.models.enums import Platform
from app.services.url_filters import (
    PLATFORM_PRODUCT_SITEMAPS,
    is_non_product_url,
)

logger = logging.getLogger(__name__)

# XML namespace used in standard sitemaps
_SITEMAP_NS = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}

# Keywords that indicate product-relevant pages (used by BestFirst scorer)
PRODUCT_KEYWORDS = [
    "product", "price", "buy", "shop", "item", "cart", "add-to-cart",
    "sku", "inventory", "catalog", "collection",
]


class URLDiscoveryService:
    """Discover product URLs based on e-commerce platform.

    Strategy chain: Platform API -> Sitemap -> crawl4ai browser crawl.
    """

    def __init__(
        self,
        timeout: float = 30.0,
        stealth_level: StealthLevel = StealthLevel.STANDARD,
        client: httpx.AsyncClient | None = None,
    ):
        self.timeout = timeout
        self.stealth_level = stealth_level
        self._client = client

    # Maximum time for URL discovery before aborting (5 minutes).
    # Generic sites using BestFirst browser crawl can hang indefinitely.
    _DISCOVERY_TIMEOUT = 300

    async def discover(self, base_url: str, platform: Platform) -> list[str]:
        """Discover product URLs based on platform.

        Applies a 5-minute timeout to prevent indefinite hangs on generic sites
        where browser-based BestFirst crawl explores deep navigation trees.

        Returns:
            List of product URLs or API endpoints to scrape.
        """
        base_url = base_url.rstrip("/")
        logger.info("Discovering URLs for %s (platform: %s)", base_url, platform)

        try:
            coro = self._discover_for_platform(base_url, platform)
            return await asyncio.wait_for(coro, timeout=self._DISCOVERY_TIMEOUT)
        except asyncio.TimeoutError:
            logger.error(
                "URL discovery timed out after %ds for %s (%s)",
                self._DISCOVERY_TIMEOUT, base_url, platform.value,
            )
            return []
        except Exception as e:
            logger.error("Error discovering URLs for %s: %s", base_url, e)
            return []

    async def _discover_for_platform(self, base_url: str, platform: Platform) -> list[str]:
        """Dispatch to platform-specific discovery strategy."""
        if platform == Platform.SHOPIFY:
            return await self._discover_shopify(base_url, platform)
        elif platform == Platform.WOOCOMMERCE:
            return await self._discover_woocommerce(base_url, platform)
        elif platform == Platform.MAGENTO:
            return await self._discover_magento(base_url, platform)
        elif platform == Platform.BIGCOMMERCE:
            return await self._discover_bigcommerce(base_url, platform)
        else:
            return await self._discover_generic(base_url, platform)

    # ── Platform-specific strategies ──────────────────────────────────

    async def _discover_shopify(self, base_url: str, platform: Platform) -> list[str]:
        """Shopify: /products.json API with pagination."""
        api_url = f"{base_url}/products.json?limit=250&page=1"

        try:
            client = self._client or httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
            try:
                response = await client.get(api_url)
                response.raise_for_status()
                data = response.json()

                products = data.get("products", [])
                product_count = len(products)
                logger.info("Shopify first page returned %d products", product_count)

                urls = [f"{base_url}/products.json?limit=250&page=1"]
                if product_count == 250:
                    for page in range(2, 11):
                        urls.append(f"{base_url}/products.json?limit=250&page={page}")
                    logger.info("Generated %d Shopify API pagination URLs", len(urls))

                return urls
            finally:
                if self._client is None:
                    await client.aclose()

        except httpx.HTTPStatusError as e:
            logger.warning(
                "Shopify API not accessible (%s), falling back to sitemap",
                e.response.status_code,
            )
            return await self._discover_via_sitemap(base_url, platform)
        except Exception as e:
            logger.error("Error probing Shopify API: %s", e)
            return await self._discover_via_sitemap(base_url, platform)

    async def _discover_woocommerce(self, base_url: str, platform: Platform) -> list[str]:
        """WooCommerce: Store API -> sitemap -> crawl4ai."""
        api_url = f"{base_url}/wp-json/wc/store/v1/products"

        try:
            client = self._client or httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
            try:
                response = await client.get(api_url)
                response.raise_for_status()
                logger.info("WooCommerce Store API accessible at %s", api_url)
                return [api_url]
            finally:
                if self._client is None:
                    await client.aclose()
        except Exception as e:
            logger.warning("WooCommerce API not accessible: %s, falling back to sitemap", e)

        urls = await self._discover_via_sitemap(base_url, platform)
        if urls:
            return self._filter_woocommerce_urls(urls)

        logger.info("No sitemap products for %s, falling back to crawl4ai", base_url)
        return await self._discover_via_crawl4ai(base_url)

    async def _discover_magento(self, base_url: str, platform: Platform) -> list[str]:
        """Magento: REST API -> sitemap -> crawl4ai."""
        api_url = f"{base_url}/rest/V1/products?searchCriteria[pageSize]=100"

        try:
            client = self._client or httpx.AsyncClient(timeout=self.timeout, follow_redirects=True)
            try:
                response = await client.get(api_url)
                response.raise_for_status()
                logger.info("Magento REST API accessible at %s", api_url)
                return [api_url]
            finally:
                if self._client is None:
                    await client.aclose()
        except Exception as e:
            logger.warning("Magento API not accessible: %s, falling back to sitemap", e)

        urls = await self._discover_via_sitemap(base_url, platform)
        if urls:
            return urls

        logger.info("No sitemap products for %s, falling back to crawl4ai", base_url)
        return await self._discover_via_crawl4ai(base_url)

    async def _discover_bigcommerce(self, base_url: str, platform: Platform) -> list[str]:
        """BigCommerce: sitemap -> crawl4ai (flat URL structure)."""
        urls = await self._discover_via_sitemap(base_url, platform)
        if urls:
            return urls

        logger.info("No sitemap for %s, falling back to crawl4ai", base_url)
        return await self._discover_via_crawl4ai(base_url)

    async def _discover_generic(self, base_url: str, platform: Platform) -> list[str]:
        """Generic: sitemap -> crawl4ai -> base URL fallback."""
        urls = await self._discover_via_sitemap(base_url, platform)
        if urls:
            return urls

        urls = await self._discover_via_crawl4ai(base_url)
        if urls:
            return urls

        logger.info("No URLs discovered for %s, returning base URL for crawling", base_url)
        return [base_url]

    # ── Sitemap discovery (3-phase) ───────────────────────────────────

    async def _discover_via_sitemap(
        self, base_url: str, platform: Platform
    ) -> list[str]:
        """Discover product URLs from sitemaps.

        Phase 1: Try platform-specific product sitemaps (e.g. product-sitemap.xml).
        Phase 2: Fall back to generic sitemap via AsyncUrlSeeder.
        Phase 3: Apply denylist filter to all results.
        """
        base_url = base_url.rstrip("/")
        domain = urlparse(base_url).netloc

        # Phase 1 -- platform-specific product sitemaps
        product_sitemap_paths = PLATFORM_PRODUCT_SITEMAPS.get(platform.value, [])
        if product_sitemap_paths:
            product_urls = await self._try_product_sitemaps(base_url, product_sitemap_paths)
            if product_urls:
                filtered = [u for u in product_urls if not is_non_product_url(u)]
                logger.info(
                    "Product sitemaps yielded %d URLs (%d after filtering)",
                    len(product_urls),
                    len(filtered),
                )
                return filtered

        # Phase 2 -- generic sitemap via AsyncUrlSeeder
        config = SeedingConfig(
            source="sitemap",
            pattern="*",
            filter_nonsense_urls=True,
            max_urls=5000,
            force=False,
        )
        urls: list[str] = []
        try:
            async with AsyncUrlSeeder() as seeder:
                results = await seeder.urls(domain, config)
            urls = [r["url"] for r in results if r.get("status") != "not_valid"]
        except Exception as e:
            logger.warning("AsyncUrlSeeder failed for %s: %s", domain, e)

        # Phase 3 -- denylist filter
        filtered = [u for u in urls if not is_non_product_url(u)]
        if filtered:
            logger.info(
                "Sitemap discovery: %d URLs, %d after filtering",
                len(urls),
                len(filtered),
            )
        return filtered

    async def _try_product_sitemaps(
        self, base_url: str, paths: list[str]
    ) -> list[str]:
        """Probe platform-specific product sitemap URLs and extract <loc> entries.

        Uses lightweight httpx + defusedxml parsing (no browser needed).
        Responses exceeding MAX_RESPONSE_SIZE are skipped to prevent memory exhaustion.
        """
        urls: list[str] = []
        client = self._client or httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=True
        )
        try:
            for path in paths:
                sitemap_url = f"{base_url}{path}"
                try:
                    resp = await client.get(sitemap_url)
                    if resp.status_code != 200:
                        continue
                    content_length = int(resp.headers.get("content-length", 0))
                    if content_length > MAX_RESPONSE_SIZE:
                        logger.warning(
                            "Sitemap response too large (%d bytes) from %s, skipping",
                            content_length,
                            sitemap_url,
                        )
                        continue
                    xml_text = resp.text
                    if len(xml_text) > MAX_RESPONSE_SIZE:
                        logger.warning(
                            "Sitemap body too large (%d chars) from %s, skipping",
                            len(xml_text),
                            sitemap_url,
                        )
                        continue
                    parsed_urls = self._parse_sitemap_xml(xml_text)
                    if parsed_urls:
                        logger.info(
                            "Found %d URLs in %s", len(parsed_urls), sitemap_url
                        )
                        urls.extend(parsed_urls)
                except Exception as e:
                    logger.debug("Failed to fetch %s: %s", sitemap_url, e)
        finally:
            if self._client is None:
                await client.aclose()
        return urls

    @staticmethod
    def _parse_sitemap_xml(xml_text: str) -> list[str]:
        """Extract all <loc> URLs from a sitemap XML string.

        Uses defusedxml to block XML entity expansion attacks (e.g. Billion Laughs).
        """
        try:
            root = ET.fromstring(xml_text)
        except DefusedXmlException as e:
            logger.warning("Rejected unsafe sitemap XML: %s", e)
            return []
        except ET.ParseError:
            return []

        urls: list[str] = []

        # Handle sitemap index (recurse not needed -- we only probe known product sitemaps)
        if root.tag.endswith("sitemapindex"):
            return []

        # Regular urlset
        loc_elements = root.findall(".//sm:url/sm:loc", _SITEMAP_NS)
        if not loc_elements:
            loc_elements = root.findall(".//url/loc")
        for loc in loc_elements:
            if loc.text:
                urls.append(loc.text.strip())
        return urls

    # ── WooCommerce URL filter ────────────────────────────────────────

    @staticmethod
    def _filter_woocommerce_urls(urls: list[str]) -> list[str]:
        """If >= 30% of URLs contain /product/, keep only those.

        WooCommerce product-sitemap.xml sometimes mixes product and non-product
        URLs.  If a clear majority match the ``/product/`` pattern we can safely
        drop the rest.  Otherwise keep everything (flat URL stores).
        """
        product_urls = [u for u in urls if "/product/" in u.lower()]
        if len(product_urls) >= len(urls) * 0.3:
            return product_urls
        return urls

    # ── crawl4ai browser-based discovery ──────────────────────────────

    async def _discover_via_crawl4ai(
        self, base_url: str, max_pages: int = 100
    ) -> list[str]:
        """Use crawl4ai BestFirstCrawlingStrategy to discover product URLs.

        Prioritizes product-like URLs via keyword scoring, filters out
        non-product pages, and crawls up to max_pages.
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
                reverse=True,
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
                if isinstance(results, list):
                    for result in results:
                        if result.success and not is_non_product_url(result.url):
                            found_urls.add(result.url)
                elif hasattr(results, "success") and results.success:
                    if not is_non_product_url(results.url):
                        found_urls.add(results.url)
        except Exception as e:
            logger.error("Deep crawl discovery failed for %s: %s", base_url, e)

        if found_urls:
            logger.info(
                "BestFirst crawl discovered %d candidate product URLs from %s",
                len(found_urls),
                base_url,
            )

        return list(found_urls)
