"""
Crawl4AI Code Snippets - Ready to Use in Merchant Onboarding Pipeline

Copy-paste these into your extractors/ and services/ modules
"""

import asyncio
import json
from typing import AsyncGenerator, List, Optional
from decimal import Decimal

from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode
from crawl4ai.extraction_strategy import (
    JsonCssExtractionStrategy,
    SchemaOrgExtractionStrategy,
    LLMExtractionStrategy,
)
from crawl4ai.deep_crawling import (
    BestFirstCrawlingStrategy,
    BFSDeepCrawlStrategy,
    DFSDeepCrawlStrategy,
)
from crawl4ai.deep_crawling.scorers import KeywordRelevanceScorer
from crawl4ai.deep_crawling.filters import URLPatternFilter, FilterChain
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher, CrawlerMonitor, DisplayMode
from crawl4ai.infra import RateLimiter


# ============================================================================
# 1. UNIVERSAL URL DISCOVERY SERVICE
# ============================================================================

async def discover_product_urls(
    shop_url: str,
    max_pages: int = 500,
    keywords: Optional[List[str]] = None,
) -> List[str]:
    """
    Auto-discover product URLs from a shop using BestFirstCrawlingStrategy.

    Handles infinite catalogs gracefully - stops at max_pages.
    Prioritizes URLs by relevance to keywords.

    Use case: Shopify, WooCommerce, Magento, custom sites with product listings

    Args:
        shop_url: Starting URL (e.g., https://shop.com/products)
        max_pages: Maximum pages to crawl (default 500 = ~5000 products)
        keywords: Words to search for (default: ['product', 'price', 'buy'])

    Returns:
        List of discovered product URLs
    """

    if keywords is None:
        keywords = ["product", "price", "add to cart", "buy", "inventory"]

    # Filter URLs to product/shop pages only
    filters = FilterChain([
        URLPatternFilter(patterns=[
            "*/products*",
            "*/product*",
            "*/shop*",
            "*/catalog*",
            "*/category*",
            "*/item*",
        ])
    ])

    # Score URLs by relevance
    scorer = KeywordRelevanceScorer(
        keywords=keywords,
        weight=0.7
    )

    # Best-first crawling strategy (recommended for product discovery)
    strategy = BestFirstCrawlingStrategy(
        max_depth=3,
        include_external=False,
        max_pages=max_pages,
        filter_chain=filters,
        url_scorer=scorer,
        score_threshold=0.2,
    )

    config = CrawlerRunConfig(
        extraction_strategy=strategy,
        wait_until="domcontentloaded",
        cache_mode=CacheMode.ENABLED,
        exclude_all_images=True,  # Speed boost
    )

    browser_config = BrowserConfig(
        headless=True,
        enable_stealth=True,
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=shop_url, config=config)

    if not result.success:
        return []

    # Extract URLs from discovered links
    discovered_urls = []
    if result.links:
        for link in result.links.get("internal", []):
            url = link.get("href", "")
            if url and any(pattern in url.lower() for pattern in [
                "product", "item", "sku", "catalog"
            ]):
                discovered_urls.append(url)

    return list(set(discovered_urls))  # Deduplicate


# ============================================================================
# 2. BATCH PRODUCT EXTRACTOR (20-100 URLs)
# ============================================================================

PRODUCT_SCHEMA = {
    "name": "ProductExtractor",
    "baseSelector": ".product, [data-product], article.product",
    "fields": [
        {"name": "id", "selector": "[data-sku], [data-product-id], [data-id]", "type": "attribute", "attribute": "data-sku"},
        {"name": "title", "selector": "h1, h2, .product-title, [data-title]", "type": "text"},
        {"name": "description", "selector": ".description, .product-description, [data-description]", "type": "text"},
        {"name": "price", "selector": ".price, [data-price], .current-price", "type": "text"},
        {"name": "compare_at_price", "selector": ".original-price, .compare-price, [data-original-price]", "type": "text"},
        {"name": "currency", "selector": ".currency, [data-currency]", "type": "text"},
        {"name": "sku", "selector": ".sku, [data-sku]", "type": "text"},
        {"name": "in_stock", "selector": ".in-stock, [data-in-stock], .availability", "type": "text"},
        {
            "name": "image",
            "type": "nested",
            "selector": "img.product-image, img[data-main], img.main",
            "fields": [
                {"name": "src", "type": "attribute", "attribute": "src"},
                {"name": "alt", "type": "attribute", "attribute": "alt"}
            ]
        },
        {
            "name": "variants",
            "type": "nested_list",
            "selector": ".variant, [data-variant], .size-option, .color-option",
            "fields": [
                {"name": "size", "selector": "[data-size]", "type": "attribute", "attribute": "data-size"},
                {"name": "color", "selector": "[data-color]", "type": "attribute", "attribute": "data-color"},
                {"name": "sku", "selector": "[data-variant-sku]", "type": "attribute", "attribute": "data-variant-sku"},
            ]
        }
    ]
}


async def extract_products_streaming(
    urls: List[str],
    max_concurrent: int = 10,
    timeout_sec: int = 15,
) -> AsyncGenerator[dict, None]:
    """
    Extract products from multiple URLs with streaming.

    Reuses single browser session across all URLs (efficient).
    Processes results immediately (60% memory savings).

    Yields results as they complete, not waiting for all.

    Args:
        urls: List of product page URLs to crawl
        max_concurrent: Maximum concurrent crawls (default 10)
        timeout_sec: Page timeout in seconds

    Yields:
        dict with keys: url, success, products, error
    """

    strategy = JsonCssExtractionStrategy(schema=PRODUCT_SCHEMA)

    config = CrawlerRunConfig(
        extraction_strategy=strategy,
        wait_until="domcontentloaded",
        cache_mode=CacheMode.ENABLED,
        page_timeout=timeout_sec * 1000,
        exclude_all_images=True,  # Speed boost
    )

    dispatcher = MemoryAdaptiveDispatcher(
        memory_threshold_percent=75,
        max_session_permit=max_concurrent,
        check_interval=0.5,
    )

    browser_config = BrowserConfig(
        headless=True,
        enable_stealth=True,
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        async for result in await crawler.arun_many(
            urls=urls,
            config=config,
            dispatcher=dispatcher,
            stream=True  # Key: process results as they arrive
        ):
            if result.success:
                try:
                    products = json.loads(result.extracted_content)
                    yield {
                        "url": result.url,
                        "success": True,
                        "products": products if isinstance(products, list) else [products],
                        "error": None,
                    }
                except json.JSONDecodeError as e:
                    yield {
                        "url": result.url,
                        "success": False,
                        "products": [],
                        "error": f"JSON decode error: {e}",
                    }
            else:
                yield {
                    "url": result.url,
                    "success": False,
                    "products": [],
                    "error": result.error_message or "Unknown error",
                }


# ============================================================================
# 3. SCHEMA.ORG FALLBACK EXTRACTOR
# ============================================================================

async def extract_with_schema_org(
    url: str,
    timeout_sec: int = 15,
) -> Optional[dict]:
    """
    Extract structured data from JSON-LD / Schema.org markup.

    Fast, free, works on ~60% of modern e-commerce sites.
    Great fallback when CSS extraction fails.

    Args:
        url: Product page URL
        timeout_sec: Page timeout

    Returns:
        Extracted structured data or None
    """

    strategy = SchemaOrgExtractionStrategy()

    config = CrawlerRunConfig(
        extraction_strategy=strategy,
        wait_until="domcontentloaded",
        cache_mode=CacheMode.ENABLED,
        page_timeout=timeout_sec * 1000,
        exclude_all_images=True,
    )

    browser_config = BrowserConfig(headless=True, enable_stealth=True)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=config)

    if result.success and result.extracted_content:
        try:
            return json.loads(result.extracted_content)
        except json.JSONDecodeError:
            return None

    return None


# ============================================================================
# 4. LLM EXTRACTION (Universal Fallback)
# ============================================================================

async def extract_with_llm(
    url: str,
    llm_provider: str = "groq",  # or "openai", "anthropic", "ollama"
    api_key: Optional[str] = None,
    timeout_sec: int = 30,
) -> Optional[dict]:
    """
    Use LLM for complex/unstructured product extraction.

    Use only when CSS and Schema.org fail!

    Cost: ~$0.01 per page with gpt-4o-mini, FREE with Groq
    Speed: 5-10 seconds per page

    Args:
        url: Product page URL
        llm_provider: "groq" (free), "openai" (paid), etc.
        api_key: API key for provider
        timeout_sec: Page timeout

    Returns:
        Extracted product data or None
    """

    from pydantic import BaseModel
    from typing import List, Optional

    class Product(BaseModel):
        title: str
        price: str
        description: Optional[str]
        sku: Optional[str]
        in_stock: Optional[bool]
        image_url: Optional[str]

    llm_config = {
        "provider": llm_provider,
        "model": "gpt-4o-mini" if llm_provider == "openai" else "mixtral-8x7b-32768",
        "api_key": api_key,
        "temperature": 0.0,
    }

    strategy = LLMExtractionStrategy(
        llm_config=llm_config,
        schema=Product.model_json_schema(),
        extraction_type="schema",
        input_format="fit_markdown",  # CRITICAL: reduces tokens 40-60%
        chunk_token_threshold=3000,
        overlap_rate=0.1,
    )

    config = CrawlerRunConfig(
        extraction_strategy=strategy,
        wait_until="networkidle",
        page_timeout=timeout_sec * 1000,
    )

    browser_config = BrowserConfig(headless=True, enable_stealth=True)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        result = await crawler.arun(url=url, config=config)

    if result.success and result.extracted_content:
        try:
            return json.loads(result.extracted_content)
        except json.JSONDecodeError:
            return None

    return None


# ============================================================================
# 5. AUTHENTICATED CRAWLING (Multi-step)
# ============================================================================

async def crawl_authenticated_products(
    login_url: str,
    email: str,
    password: str,
    product_page_url: str,
    product_schema: dict,
) -> Optional[List[dict]]:
    """
    Multi-step authenticated crawling:
    1. Navigate to login page
    2. Enter credentials
    3. Submit login
    4. Browse to authenticated page
    5. Extract products

    Session cookies preserved across steps.

    Args:
        login_url: Login page URL
        email: Login email
        password: Login password
        product_page_url: Product page accessible after login
        product_schema: CSS extraction schema

    Returns:
        List of extracted products or None
    """

    session_id = "auth_session"

    login_js = f"""
    document.querySelector('input[type="email"]').value = '{email}';
    document.querySelector('input[type="password"]').value = '{password}';
    document.querySelector('button[type="submit"]').click();
    await new Promise(r => setTimeout(r, 3000));  // Wait for login
    """

    browser_config = BrowserConfig(headless=True)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        # Step 1: Login (creates session)
        login_config = CrawlerRunConfig(
            session_id=session_id,
            javascript_code=login_js,
            wait_for=".dashboard, .authenticated, .inventory",  # Wait for success indicator
            page_timeout=15000,
        )

        login_result = await crawler.arun(url=login_url, config=login_config)

        if not login_result.success:
            return None

        # Step 2: Browse to product page (session cookies active)
        product_config = CrawlerRunConfig(
            session_id=session_id,  # Reuse session - already logged in!
            extraction_strategy=JsonCssExtractionStrategy(schema=product_schema),
            wait_until="domcontentloaded",
            page_timeout=15000,
        )

        product_result = await crawler.arun(url=product_page_url, config=product_config)

        if product_result.success:
            try:
                return json.loads(product_result.extracted_content)
            except json.JSONDecodeError:
                return None

    return None


# ============================================================================
# 6. URL-SPECIFIC CONFIG STRATEGY
# ============================================================================

async def crawl_mixed_urls(
    urls: List[str],
    discovery_config: Optional[dict] = None,
) -> AsyncGenerator[dict, None]:
    """
    Crawl different URL types with optimized configs:
    - Product pages: full extraction
    - Category pages: link extraction
    - Other: lightweight text only

    Auto-selects config based on URL pattern.

    Args:
        urls: Mixed list of URLs (products, categories, pages)
        discovery_config: Additional config options

    Yields:
        dict with url, success, content, type
    """

    # Config for product pages
    product_config = CrawlerRunConfig(
        url_matcher="*/products/*",
        extraction_strategy=JsonCssExtractionStrategy(schema=PRODUCT_SCHEMA),
        wait_until="networkidle",
        cache_mode=CacheMode.ENABLED,
    )

    # Config for category/listing pages
    category_config = CrawlerRunConfig(
        url_matcher="*/category/*",
        extraction_strategy="schema_org",
        wait_until="domcontentloaded",
        extract_links=True,
        cache_mode=CacheMode.ENABLED,
    )

    # Fallback for everything else
    default_config = CrawlerRunConfig(
        url_matcher=None,
        text_mode=True,
        wait_until="domcontentloaded",
        cache_mode=CacheMode.ENABLED,
    )

    configs = [product_config, category_config, default_config]

    dispatcher = MemoryAdaptiveDispatcher(
        memory_threshold_percent=75,
        max_session_permit=10,
    )

    browser_config = BrowserConfig(headless=True, enable_stealth=True)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        async for result in await crawler.arun_many(
            urls=urls,
            config=configs,  # Automatically matches URL to config
            dispatcher=dispatcher,
            stream=True
        ):
            if result.success:
                yield {
                    "url": result.url,
                    "success": True,
                    "content": result.extracted_content,
                    "type": "product" if "/products/" in result.url else "category",
                    "error": None,
                }
            else:
                yield {
                    "url": result.url,
                    "success": False,
                    "content": None,
                    "type": "unknown",
                    "error": result.error_message,
                }


# ============================================================================
# 7. PERFORMANCE-OPTIMIZED FAST CRAWL
# ============================================================================

async def fast_batch_crawl(
    urls: List[str],
    max_concurrent: int = 20,
) -> AsyncGenerator[dict, None]:
    """
    Fastest possible crawling for simple sites.

    Optimizations:
    - text_mode=True (3-4x faster)
    - No image loading
    - Fast wait_until
    - Aggressive caching
    - High concurrency

    Args:
        urls: URLs to crawl
        max_concurrent: Max concurrent crawls

    Yields:
        dict with url, success, content
    """

    config = CrawlerRunConfig(
        # Speed optimizations
        text_mode=True,                    # 3-4x faster!
        wait_until="domcontentloaded",
        exclude_all_images=True,
        exclude_external_links=True,

        # Content
        extraction_strategy="schema_org",

        # Caching
        cache_mode=CacheMode.ENABLED,

        # Timeouts
        page_timeout=8000,  # 8 second limit
    )

    dispatcher = MemoryAdaptiveDispatcher(
        memory_threshold_percent=70,
        max_session_permit=max_concurrent,
        check_interval=0.25,
    )

    browser_config = BrowserConfig(
        headless=True,
        enable_stealth=True,
        viewport={"width": 800, "height": 600},  # Smaller = faster
    )

    async with AsyncWebCrawler(config=browser_config) as crawler:
        async for result in await crawler.arun_many(
            urls=urls,
            config=config,
            dispatcher=dispatcher,
            stream=True
        ):
            if result.success:
                yield {
                    "url": result.url,
                    "success": True,
                    "content": result.extracted_content,
                }
            else:
                yield {
                    "url": result.url,
                    "success": False,
                    "content": None,
                    "error": result.error_message,
                }


# ============================================================================
# 8. RESILIENT CRAWLER WITH RATE LIMITING
# ============================================================================

async def resilient_crawl(
    urls: List[str],
    base_delay: tuple = (1.0, 3.0),  # Random 1-3 seconds
    max_retries: int = 3,
) -> AsyncGenerator[dict, None]:
    """
    Rate-limited crawling with exponential backoff.

    - Respects robots.txt
    - Delays between requests per domain
    - Retries on 429/503 errors
    - Exponential backoff

    Args:
        urls: URLs to crawl
        base_delay: (min, max) seconds between requests
        max_retries: Retry count for rate limit errors

    Yields:
        Crawl results
    """

    rate_limiter = RateLimiter(
        base_delay=base_delay,
        max_delay=60.0,
        max_retries=max_retries,
        rate_limit_codes=[429, 503],  # Codes triggering backoff
    )

    config = CrawlerRunConfig(
        extraction_strategy="schema_org",
        wait_until="domcontentloaded",
        cache_mode=CacheMode.ENABLED,
        respect_robots_txt=True,  # Crawl responsibly
    )

    dispatcher = MemoryAdaptiveDispatcher(
        memory_threshold_percent=75,
        max_session_permit=5,  # Conservative
    )

    # Attach rate limiter to dispatcher
    dispatcher.rate_limiter = rate_limiter

    browser_config = BrowserConfig(headless=True, enable_stealth=True)

    async with AsyncWebCrawler(config=browser_config) as crawler:
        async for result in await crawler.arun_many(
            urls=urls,
            config=config,
            dispatcher=dispatcher,
            stream=True
        ):
            yield result


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

async def main():
    """Example usage of crawl4ai patterns"""

    # Example 1: Discover product URLs
    print("Discovering product URLs...")
    urls = await discover_product_urls(
        shop_url="https://example-shop.com/products",
        max_pages=100,
    )
    print(f"Found {len(urls)} product URLs")

    # Example 2: Extract products with streaming
    print("\nExtracting products...")
    async for result in extract_products_streaming(urls[:10]):
        if result["success"]:
            print(f"  {result['url']}: {len(result['products'])} products")
        else:
            print(f"  {result['url']}: {result['error']}")

    # Example 3: Fast crawl
    print("\nFast crawling...")
    async for result in fast_batch_crawl(urls[:5]):
        if result["success"]:
            print(f"  {result['url']}: Success")
        else:
            print(f"  {result['url']}: {result['error']}")


if __name__ == "__main__":
    asyncio.run(main())
