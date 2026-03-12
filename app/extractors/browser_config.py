"""Shared browser configuration for crawl4ai-based extractors.

Provides three anti-bot tiers:
  - STANDARD: Basic headless browser, fast, for sites with no bot protection.
  - STEALTH:  enable_stealth patches (webdriver flag removal, fingerprint spoofing),
              realistic viewport, and randomised user agent. Handles Shopify, basic
              Cloudflare challenge pages.
  - UNDETECTED: crawl4ai UndetectedAdapter with deep-level browser patches.
                Handles Cloudflare Turnstile, DataDome, PerimeterX. Slower startup.

Usage:
    browser_config = get_browser_config(StealthLevel.STEALTH)
    crawl_config   = get_crawl_config()  # or get_crawl_config(stealth_level=...)
"""

from __future__ import annotations

import logging
import random
from enum import Enum
from crawl4ai import BrowserConfig, CacheMode, CrawlerRunConfig, UndetectedAdapter
from crawl4ai.async_crawler_strategy import AsyncPlaywrightCrawlerStrategy

logger = logging.getLogger(__name__)


# ── Constants ─────────────────────────────────────────────────────────

# JS condition that returns true when product content is likely rendered.
# Covers: Schema.org Product markup, common CSS classes, data attributes, and
# Next.js/React hydration markers. No broad h1 fallback (fires on every page).
PRODUCT_WAIT_CONDITION = (
    'js:() => {'
    '  const hasProduct = !!(document.querySelector("[itemtype*=Product]") || '
    '    document.querySelector("[itemtype*=product]") || '
    '    document.querySelector(".product") || '
    '    document.querySelector("[data-product]") || '
    '    document.querySelector("[data-product-id]") || '
    '    document.querySelectorAll("[class*=product]").length > 0 || '
    '    document.querySelector("[data-testid*=product]") || '
    '    document.querySelector("script[type=\\"application/ld+json\\"]"));'
    '  if (!hasProduct) return false;'
    '  const priceEl = document.querySelector("[data-price], .price, .product-price, '
    '    [class*=price], [itemprop=price], [data-product-price]");'
    '  if (priceEl) return !!(priceEl.textContent && priceEl.textContent.trim().match(/\\d/));'
    '  const jsonLd = document.querySelector("script[type=\\"application/ld+json\\"]");'
    '  if (jsonLd) { try { const d = JSON.parse(jsonLd.textContent);'
    '    const hasPrice = JSON.stringify(d).match(/"price"\\s*:\\s*"?[\\d.]+/);'
    '    if (hasPrice) return true; } catch(e) {} }'
    '  return false;'
    '}'
)

DEFAULT_PAGE_TIMEOUT = 30000
DEFAULT_DELAY_BEFORE_RETURN = 3.0

# Realistic desktop user agents (Chrome 131 on macOS/Windows/Linux — updated Feb 2026)
_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
]

# Default HTTP headers applied to ALL stealth levels — prevents geo-redirects
# and ensures servers return English content.  Reused by httpx-based extractors
# (schema_org, opengraph) via ``DEFAULT_HEADERS``.
DEFAULT_HEADERS: dict[str, str] = {
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def get_default_user_agent() -> str:
    """Return a random User-Agent from the pool (for httpx-based extractors)."""
    return random.choice(_USER_AGENTS)


# ── Stealth levels ────────────────────────────────────────────────────

class StealthLevel(str, Enum):
    """Anti-bot protection tier for browser-based crawling."""

    STANDARD = "standard"
    STEALTH = "stealth"
    UNDETECTED = "undetected"


# ── Browser config factories ──────────────────────────────────────────

def get_browser_config(
    stealth_level: StealthLevel = StealthLevel.STANDARD,
    headless: bool = True,
    text_mode: bool = False,
) -> BrowserConfig:
    """Create a BrowserConfig for the requested anti-bot tier.

    Args:
        stealth_level: Protection tier (STANDARD, STEALTH, or UNDETECTED).
        headless: Run browser headless. Set False for UNDETECTED if needed.
        text_mode: If True, adds ``--disable-javascript`` to Chromium launch args.
                   Default is **False** because most e-commerce sites are SPAs that
                   require JavaScript to render product data.

    Returns:
        Configured BrowserConfig instance.
    """
    ua = random.choice(_USER_AGENTS)
    headers = {**DEFAULT_HEADERS, "User-Agent": ua}

    if stealth_level == StealthLevel.STANDARD:
        return BrowserConfig(
            headless=headless,
            verbose=False,
            text_mode=text_mode,
            user_agent=ua,
            headers=headers,
        )

    if stealth_level == StealthLevel.STEALTH:
        return BrowserConfig(
            headless=headless,
            verbose=False,
            text_mode=text_mode,
            enable_stealth=True,
            user_agent=ua,
            viewport_width=1920,
            viewport_height=1080,
            headers=headers,
        )

    # UNDETECTED — stealth + UndetectedAdapter (set via crawler_strategy)
    return BrowserConfig(
        headless=headless,
        verbose=False,
        text_mode=text_mode,
        enable_stealth=True,
        user_agent=ua,
        viewport_width=1920,
        viewport_height=1080,
        headers=headers,
    )


def get_crawler_strategy(
    stealth_level: StealthLevel,
    browser_config: BrowserConfig | None = None,
) -> AsyncPlaywrightCrawlerStrategy | None:
    """Create a crawler strategy with UndetectedAdapter if needed.

    Only returns a strategy for UNDETECTED level. STANDARD and STEALTH
    use the default strategy (pass None to AsyncWebCrawler).

    Args:
        stealth_level: Protection tier.
        browser_config: BrowserConfig to attach to the strategy.

    Returns:
        AsyncPlaywrightCrawlerStrategy with UndetectedAdapter, or None.
    """
    if stealth_level != StealthLevel.UNDETECTED:
        return None

    if browser_config is None:
        browser_config = get_browser_config(stealth_level)

    adapter = UndetectedAdapter()
    logger.info("Using UndetectedAdapter for enhanced anti-bot bypassing")
    return AsyncPlaywrightCrawlerStrategy(
        browser_config=browser_config,
        browser_adapter=adapter,
    )


def get_crawl_config(
    stealth_level: StealthLevel = StealthLevel.STANDARD,
    extraction_strategy=None,
    markdown_generator=None,
    deep_crawl_strategy=None,
    wait_until: str = "domcontentloaded",
    wait_for: str | None = PRODUCT_WAIT_CONDITION,
    page_timeout: int = DEFAULT_PAGE_TIMEOUT,
    delay_before_return_html: float = DEFAULT_DELAY_BEFORE_RETURN,
    scan_full_page: bool = True,
    remove_overlay_elements: bool = True,
    scroll_delay: float = 0.5,
    check_robots_txt: bool = True,
) -> CrawlerRunConfig:
    """Create a CrawlerRunConfig with anti-bot settings for the requested tier.

    STEALTH and UNDETECTED tiers add simulate_user and magic flags for
    human-like page interaction (random mouse movements, scroll, delays).

    Args:
        stealth_level: Protection tier.
        extraction_strategy: crawl4ai extraction strategy.
        markdown_generator: crawl4ai markdown generator.
        deep_crawl_strategy: Deep crawl strategy (BestFirst, etc).
        wait_until: Playwright load state to wait for.
        wait_for: JS condition to wait for after page load.
        page_timeout: Page navigation timeout in ms.
        delay_before_return_html: Delay in seconds before capturing HTML.
        scan_full_page: Scroll the full page to trigger lazy-loaded content.
        remove_overlay_elements: Remove cookie banners, modals, overlays.
        scroll_delay: Delay in seconds between scroll steps.
        check_robots_txt: Whether to respect robots.txt directives.

    Returns:
        Configured CrawlerRunConfig.
    """
    use_anti_bot = stealth_level in (StealthLevel.STEALTH, StealthLevel.UNDETECTED)

    # Anti-bot sites need longer timeouts for challenge pages.
    if use_anti_bot and page_timeout == DEFAULT_PAGE_TIMEOUT:
        page_timeout = 60000

    # Extra delay for anti-bot challenge resolution.
    if use_anti_bot and delay_before_return_html == DEFAULT_DELAY_BEFORE_RETURN:
        delay_before_return_html = 4.0

    return CrawlerRunConfig(
        extraction_strategy=extraction_strategy,
        markdown_generator=markdown_generator,
        deep_crawl_strategy=deep_crawl_strategy,
        cache_mode=CacheMode.BYPASS,
        wait_until=wait_until,
        wait_for=wait_for,
        wait_for_images=True,
        page_timeout=page_timeout,
        delay_before_return_html=delay_before_return_html,
        simulate_user=use_anti_bot,
        magic=use_anti_bot,
        override_navigator=use_anti_bot,
        scan_full_page=scan_full_page,
        max_scroll_steps=20,
        remove_overlay_elements=remove_overlay_elements,
        scroll_delay=scroll_delay,
        check_robots_txt=check_robots_txt,
        locale="en-US",
    )


async def fetch_html_with_browser(
    url: str,
    stealth_level: StealthLevel = StealthLevel.STEALTH,
) -> str | None:
    """Fetch page HTML using crawl4ai browser (for bot-protected or JS-rendered sites).

    Returns HTML string on success, None on failure.
    """
    from crawl4ai import AsyncWebCrawler

    try:
        browser_config = get_browser_config(stealth_level)
        crawl_config = get_crawl_config(stealth_level=stealth_level)
        crawler_strategy = get_crawler_strategy(stealth_level, browser_config)

        async with AsyncWebCrawler(
            config=browser_config,
            crawler_strategy=crawler_strategy,
        ) as crawler:
            result = await crawler.arun(url=url, config=crawl_config)
            if result.success and result.html:
                return result.html
            logger.warning("Browser fetch failed for %s: %s", url, getattr(result, 'error_message', 'unknown'))
            return None
    except Exception as e:
        logger.error("Browser fetch error for %s: %s", url, e)
        return None
