"""Platform detection service for e-commerce platforms.

Detects platform using multiple strategies:
1. HTTP header probes (fastest)
2. API endpoint probes
3. HTML meta tag analysis
4. CDN/script source analysis
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

from app.config import MAX_RESPONSE_SIZE
from app.models.enums import Platform

logger = logging.getLogger(__name__)

# Detection timeouts
PROBE_TIMEOUT = 10.0  # per probe
TOTAL_TIMEOUT = 30.0  # overall detection timeout


@dataclass
class PlatformResult:
    """Result of platform detection."""

    platform: Platform
    confidence: float  # 0.0-1.0
    signals: list[str] = field(default_factory=list)  # detection signals found
    html: str | None = None  # cached homepage HTML for merchant profile extraction


class PlatformDetector:
    """Detects e-commerce platform using multiple detection strategies."""

    # Max possible signals for confidence calculation
    MAX_SIGNALS = {
        Platform.SHOPIFY: 4,  # header, api, meta, cdn
        Platform.WOOCOMMERCE: 4,  # header, api, meta, cdn
        Platform.MAGENTO: 3,  # header, api, meta
        Platform.BIGCOMMERCE: 3,  # meta, cdn, scripts
        Platform.SHOPWARE: 4,  # header, api, meta, cdn
        Platform.GENERIC: 1,  # fallback always has 1 signal
    }

    def __init__(self, client: httpx.AsyncClient | None = None):
        """Initialize detector with optional httpx client.

        Args:
            client: Optional httpx.AsyncClient. If None, creates a new client per detection.
        """
        self._client = client
        self._cached_html: str | None = None

    async def detect(self, url: str) -> PlatformResult:
        """Detect platform for the given URL.

        Args:
            url: The merchant's website URL

        Returns:
            PlatformResult with detected platform, confidence score, and signals
        """
        start_time = time.time()
        logger.info("Starting platform detection for %s", url)

        signals: dict[Platform, list[str]] = {
            Platform.SHOPIFY: [],
            Platform.WOOCOMMERCE: [],
            Platform.MAGENTO: [],
            Platform.BIGCOMMERCE: [],
            Platform.SHOPWARE: [],
        }

        # Use provided client or create a new one
        client = self._client or httpx.AsyncClient(
            timeout=httpx.Timeout(PROBE_TIMEOUT),
            follow_redirects=True,
            headers={"User-Agent": "Mozilla/5.0 (compatible; MerchantBot/1.0)"},
        )

        try:
            # Run all detection strategies with overall timeout
            async with asyncio.timeout(TOTAL_TIMEOUT):
                # Step 1: HTTP Header Probes (fastest)
                await self._probe_headers(client, url, signals)

                # Step 2: API Endpoint Probes (fast)
                await self._probe_api_endpoints(client, url, signals)

                # Step 3: HTML Meta Tag & CDN Analysis (requires one page load)
                await self._probe_html_content(client, url, signals)

        except TimeoutError:
            logger.warning("Platform detection timed out after %ss for %s", TOTAL_TIMEOUT, url)
        except Exception as e:
            logger.error("Error during platform detection for %s: %s", url, e)
        finally:
            # Close client if we created it
            if self._client is None:
                await client.aclose()

        # Determine platform with highest signal count
        platform, platform_signals = self._determine_platform(signals)

        # Calculate confidence score
        max_signals = self.MAX_SIGNALS.get(platform, 1)
        confidence = min(len(platform_signals) / max_signals, 1.0)

        elapsed = time.time() - start_time
        logger.info(
            "Platform detection complete for %s: %s (confidence: %.2f, signals: %d, time: %.2fs)",
            url, platform, confidence, len(platform_signals), elapsed,
        )

        return PlatformResult(platform=platform, confidence=confidence, signals=platform_signals, html=self._cached_html)

    async def _probe_headers(
        self, client: httpx.AsyncClient, url: str, signals: dict[Platform, list[str]]
    ) -> None:
        """Probe HTTP headers for platform-specific headers.

        Args:
            client: HTTP client
            url: Target URL
            signals: Dictionary to accumulate detection signals
        """
        try:
            logger.debug("Probing headers for %s", url)
            start = time.time()
            response = await client.head(url)
            elapsed = time.time() - start

            headers = response.headers

            # Shopify headers
            if "x-shopid" in headers or "x-shopify-stage" in headers:
                signals[Platform.SHOPIFY].append("header:x-shopify")
                logger.debug("Found Shopify header in %.2fs", elapsed)

            # Magento headers
            if any(key.lower().startswith("x-magento") for key in headers):
                signals[Platform.MAGENTO].append("header:x-magento")
                logger.debug("Found Magento header in %.2fs", elapsed)

            # WordPress/WooCommerce headers (Link header with wp-json)
            link_header = headers.get("link", "")
            if "wp-json" in link_header.lower() and "api.w.org" in link_header.lower():
                signals[Platform.WOOCOMMERCE].append("header:wp-json-link")
                logger.debug("Found WooCommerce header in %.2fs", elapsed)

            # Shopware headers
            headers_lower = {k.lower(): v for k, v in headers.items()}
            if "sw-version-id" in headers_lower or "sw-context-token" in headers_lower:
                signals[Platform.SHOPWARE].append("header:shopware")
                logger.debug("Found Shopware header in %.2fs", elapsed)

        except httpx.TimeoutException:
            logger.debug("Header probe timed out for %s", url)
        except Exception as e:
            logger.debug("Header probe failed for %s: %s", url, e)

    async def _probe_api_endpoints(
        self, client: httpx.AsyncClient, url: str, signals: dict[Platform, list[str]]
    ) -> None:
        """Probe known API endpoints for each platform.

        Args:
            client: HTTP client
            url: Target URL
            signals: Dictionary to accumulate detection signals
        """
        # Normalize URL (remove trailing slash)
        base_url = url.rstrip("/")

        # Run probes in parallel
        await asyncio.gather(
            self._probe_shopify_api(client, base_url, signals),
            self._probe_woocommerce_api(client, base_url, signals),
            self._probe_magento_api(client, base_url, signals),
            self._probe_shopware_api_endpoint(client, base_url, signals),
            return_exceptions=True,
        )

    async def _probe_shopify_api(
        self, client: httpx.AsyncClient, base_url: str, signals: dict[Platform, list[str]]
    ) -> None:
        """Probe Shopify /products.json endpoint."""
        try:
            logger.debug("Probing Shopify API for %s", base_url)
            start = time.time()
            response = await client.get(f"{base_url}/products.json", timeout=PROBE_TIMEOUT)
            elapsed = time.time() - start

            if response.status_code == 200:
                data = response.json()
                if "products" in data:
                    signals[Platform.SHOPIFY].append("api:/products.json")
                    logger.debug("Found Shopify API endpoint in %.2fs", elapsed)

        except httpx.TimeoutException:
            logger.debug("Shopify API probe timed out for %s", base_url)
        except Exception as e:
            logger.debug("Shopify API probe failed for %s: %s", base_url, e)

    async def _probe_woocommerce_api(
        self, client: httpx.AsyncClient, base_url: str, signals: dict[Platform, list[str]]
    ) -> None:
        """Probe WooCommerce /wp-json/ endpoint."""
        try:
            logger.debug("Probing WooCommerce API for %s", base_url)
            start = time.time()
            response = await client.get(f"{base_url}/wp-json/", timeout=PROBE_TIMEOUT)
            elapsed = time.time() - start

            if response.status_code == 200:
                data = response.json()
                # WordPress REST API returns namespaces array
                if "namespaces" in data:
                    signals[Platform.WOOCOMMERCE].append("api:/wp-json/")
                    logger.debug("Found WooCommerce API endpoint in %.2fs", elapsed)

        except httpx.TimeoutException:
            logger.debug("WooCommerce API probe timed out for %s", base_url)
        except Exception as e:
            logger.debug("WooCommerce API probe failed for %s: %s", base_url, e)

    async def _probe_magento_api(
        self, client: httpx.AsyncClient, base_url: str, signals: dict[Platform, list[str]]
    ) -> None:
        """Probe Magento /rest/V1/store/storeConfigs endpoint."""
        try:
            logger.debug("Probing Magento API for %s", base_url)
            start = time.time()
            response = await client.get(f"{base_url}/rest/V1/store/storeConfigs", timeout=PROBE_TIMEOUT)
            elapsed = time.time() - start

            if response.status_code == 200:
                data = response.json()
                # Magento returns array of store configs
                if isinstance(data, list) and len(data) > 0:
                    signals[Platform.MAGENTO].append("api:/rest/V1/store/storeConfigs")
                    logger.debug("Found Magento API endpoint in %.2fs", elapsed)

        except httpx.TimeoutException:
            logger.debug("Magento API probe timed out for %s", base_url)
        except Exception as e:
            logger.debug("Magento API probe failed for %s: %s", base_url, e)

    async def _probe_shopware_api_endpoint(
        self, client: httpx.AsyncClient, base_url: str, signals: dict[Platform, list[str]]
    ) -> None:
        """Probe Shopware 6 /api/_info/config endpoint (no auth required)."""
        try:
            logger.debug("Probing Shopware API for %s", base_url)
            start = time.time()
            response = await client.get(f"{base_url}/api/_info/config", timeout=PROBE_TIMEOUT)
            elapsed = time.time() - start

            if response.status_code == 200:
                signals[Platform.SHOPWARE].append("api:/api/_info/config")
                logger.debug("Found Shopware API endpoint in %.2fs", elapsed)

        except httpx.TimeoutException:
            logger.debug("Shopware API probe timed out for %s", base_url)
        except Exception as e:
            logger.debug("Shopware API probe failed for %s: %s", base_url, e)

    async def _probe_html_content(
        self, client: httpx.AsyncClient, url: str, signals: dict[Platform, list[str]]
    ) -> None:
        """Analyze HTML content for meta tags and CDN sources.

        Responses exceeding MAX_RESPONSE_SIZE are skipped to prevent memory exhaustion.

        Args:
            client: HTTP client
            url: Target URL
            signals: Dictionary to accumulate detection signals
        """
        try:
            logger.debug("Probing HTML content for %s", url)
            start = time.time()
            response = await client.get(url, timeout=PROBE_TIMEOUT)
            elapsed = time.time() - start

            if response.status_code != 200:
                logger.debug("HTML probe returned status %s for %s", response.status_code, url)
                return

            content_length = int(response.headers.get("content-length", 0))
            if content_length > MAX_RESPONSE_SIZE:
                logger.warning(
                    "HTML probe response too large (%d bytes) from %s, skipping",
                    content_length,
                    url,
                )
                return

            raw_html = response.text
            if len(raw_html) > MAX_RESPONSE_SIZE:
                logger.warning(
                    "HTML probe body too large (%d chars) from %s, skipping",
                    len(raw_html),
                    url,
                )
                return

            self._cached_html = raw_html
            html = raw_html.lower()

            # Meta tag detection
            self._analyze_meta_tags(html, signals)

            # CDN/Script source detection
            self._analyze_cdn_sources(html, signals)

            logger.debug("HTML content analyzed in %.2fs", elapsed)

        except httpx.TimeoutException:
            logger.debug("HTML probe timed out for %s", url)
        except Exception as e:
            logger.debug("HTML probe failed for %s: %s", url, e)

    def _analyze_meta_tags(self, html: str, signals: dict[Platform, list[str]]) -> None:
        """Extract platform information from meta tags.

        Args:
            html: Lowercase HTML content
            signals: Dictionary to accumulate detection signals
        """
        # Shopify meta tag
        if re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']shopify', html):
            signals[Platform.SHOPIFY].append("meta:generator=shopify")
            logger.debug("Found Shopify meta generator tag")

        # WordPress meta tag (indicates WooCommerce possibility)
        if re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\']wordpress', html):
            signals[Platform.WOOCOMMERCE].append("meta:generator=wordpress")
            logger.debug("Found WordPress meta generator tag")

        # BigCommerce meta tag
        if re.search(r'<meta[^>]+name=["\']platform["\'][^>]+content=["\']bigcommerce', html):
            signals[Platform.BIGCOMMERCE].append("meta:platform=bigcommerce")
            logger.debug("Found BigCommerce meta platform tag")

        # Shopware meta generator tag (case-insensitive match for "Shopware")
        if re.search(r'<meta[^>]+name=["\']generator["\'][^>]+content=["\'][^"\']*[Ss]hopware', html, re.IGNORECASE):
            signals[Platform.SHOPWARE].append("meta:generator=shopware")
            logger.debug("Found Shopware meta generator tag")

    def _analyze_cdn_sources(self, html: str, signals: dict[Platform, list[str]]) -> None:
        """Analyze CDN and script sources for platform indicators.

        Args:
            html: Lowercase HTML content
            signals: Dictionary to accumulate detection signals
        """
        # Shopify CDN
        if "cdn.shopify.com" in html:
            signals[Platform.SHOPIFY].append("cdn:cdn.shopify.com")
            logger.debug("Found Shopify CDN reference")

        # BigCommerce CDN
        if "cdn.bigcommerce.com" in html or "cdn11.bigcommerce.com" in html:
            signals[Platform.BIGCOMMERCE].append("cdn:cdn.bigcommerce.com")
            logger.debug("Found BigCommerce CDN reference")

        # WooCommerce plugin path
        if "/wp-content/plugins/woocommerce/" in html:
            signals[Platform.WOOCOMMERCE].append("cdn:woocommerce-plugin")
            logger.debug("Found WooCommerce plugin reference")

        # Shopware 6 storefront bundle path / JS identifier
        if "/bundles/storefront/" in html or "shopware-storefront" in html:
            signals[Platform.SHOPWARE].append("cdn:shopware_storefront")
            logger.debug("Found Shopware storefront reference")

    def _determine_platform(self, signals: dict[Platform, list[str]]) -> tuple[Platform, list[str]]:
        """Determine the most likely platform based on collected signals.

        Args:
            signals: Dictionary of signals for each platform

        Returns:
            Tuple of (platform, signals_list)
        """
        # Find platform with most signals
        platform_counts = {plat: len(sigs) for plat, sigs in signals.items()}

        # Get platform with highest count
        max_count = max(platform_counts.values()) if platform_counts else 0

        if max_count == 0:
            # No signals found, return generic
            logger.debug("No platform signals found, defaulting to GENERIC")
            return Platform.GENERIC, ["fallback:no-signals-detected"]

        # Return platform with most signals
        for platform, count in platform_counts.items():
            if count == max_count:
                logger.debug("Platform %s selected with %s signals", platform, count)
                return platform, signals[platform]

        # Fallback (should never reach here)
        return Platform.GENERIC, ["fallback:unexpected-path"]
