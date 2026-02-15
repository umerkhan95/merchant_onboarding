# Crawl4AI Deep Research: Multi-Page Crawling, Performance Optimization & Advanced Strategies

**Research Date**: February 14, 2026
**Crawl4AI Versions**: v0.7.0 - v0.8.0
**Focus**: Deep crawling, batch processing, browser pooling, session reuse, performance tuning for e-commerce

---

## Table of Contents

1. [Deep Crawling Strategies](#deep-crawling-strategies)
2. [Batch Crawling with arun_many()](#batch-crawling-with-arun_many)
3. [Browser Session Reuse & Pooling](#browser-session-reuse--pooling)
4. [CrawlerRunConfig Best Practices](#crawlerrunconfig-best-practices)
5. [Extraction Strategies Performance](#extraction-strategies-performance)
6. [Memory & Performance Optimization](#memory--performance-optimization)
7. [Complete Code Examples](#complete-code-examples)

---

## Deep Crawling Strategies

### Overview

Crawl4AI provides three deep crawling strategies for exploring websites beyond single pages with fine-tuned control:

1. **BFSDeepCrawlStrategy** - Breadth-first exploration
2. **DFSDeepCrawlStrategy** - Depth-first exploration
3. **BestFirstCrawlingStrategy** - Relevance-based (recommended)

All strategies support crash recovery with `resume_state` and progress callbacks via `on_state_change`.

### BFSDeepCrawlStrategy (Breadth-First)

**Best for**: Comprehensive coverage, all pages at each depth before descending

**Key Parameters**:
- `max_depth: int` - Levels to explore beyond starting page
- `include_external: bool` - Follow links to other domains (default: False)
- `max_pages: int` - Maximum total pages to crawl
- `score_threshold: float` - Minimum quality score (0-1) for URLs
- `filter_chain: FilterChain` - URL patterns, domain restrictions
- `resume_state: dict | None` - Crash recovery state
- `on_state_change: Callable | None` - Progress callback

**Example**:
```python
from crawl4ai.deep_crawling import BFSDeepCrawlStrategy
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

strategy = BFSDeepCrawlStrategy(
    max_depth=2,
    include_external=False,
    max_pages=50,
)

config = CrawlerRunConfig(
    extraction_strategy=strategy
)

async with AsyncWebCrawler() as crawler:
    result = await crawler.arun(
        url="https://docs.crawl4ai.com",
        config=config
    )
```

### DFSDeepCrawlStrategy (Depth-First)

**Best for**: Deep exploration of single branches, site mapping

**Key Parameters**:
- Same as BFSDeepCrawlStrategy
- Behavior: Descends as far as possible, then backtracks

**Example**:
```python
from crawl4ai.deep_crawling import DFSDeepCrawlStrategy

strategy = DFSDeepCrawlStrategy(
    max_depth=3,
    include_external=False,
    max_pages=100,
)
```

### BestFirstCrawlingStrategy (Recommended)

**Best for**: E-commerce product catalogs, large sites requiring prioritization

**Advantages**:
- Evaluates each URL using scorer criteria
- Visits high-relevance pages first
- Ideal for limited crawl budgets (max_pages)
- Handles infinite sites gracefully

**Key Parameters**:
- `url_scorer: Scorer` - Scoring function (KeywordRelevanceScorer, etc.)
- `score_threshold: float` - Only crawl URLs scoring above threshold
- `filter_chain: FilterChain` - Combined with scorer for precise targeting
- All other params same as BFS/DFS

**Example**:
```python
from crawl4ai.deep_crawling import BestFirstCrawlingStrategy
from crawl4ai.deep_crawling.scorers import KeywordRelevanceScorer

scorer = KeywordRelevanceScorer(
    keywords=["product", "price", "inventory", "add to cart"],
    weight=0.7  # Importance in overall score
)

strategy = BestFirstCrawlingStrategy(
    max_depth=2,
    include_external=False,
    max_pages=500,  # Crawl up to 500 product pages
    url_scorer=scorer,
    score_threshold=0.3,  # Only URLs scoring 0.3+ are crawled
)
```

### Filtering and Scoring

**FilterChain** - Combines multiple filters with AND/OR logic:

```python
from crawl4ai.deep_crawling.filters import (
    URLPatternFilter,
    DomainFilter,
    ContentRelevanceFilter,
    FilterChain
)

filters = FilterChain([
    URLPatternFilter(patterns=[
        "*/products/*",
        "*/category/*"
    ]),
    DomainFilter(allowed_domains=["example.com"]),
    ContentRelevanceFilter(
        target_keywords=["price", "stock", "product"],
        min_relevance=0.5
    )
])

strategy = BestFirstCrawlingStrategy(
    max_depth=2,
    filter_chain=filters,
    url_scorer=scorer,
    max_pages=500
)
```

### Crash Recovery

**Important for production**: Resume interrupted crawls

```python
# First crawl attempt
strategy = BestFirstCrawlingStrategy(
    max_depth=2,
    max_pages=1000,
)

config = CrawlerRunConfig(extraction_strategy=strategy)

async with AsyncWebCrawler() as crawler:
    result = await crawler.arun(url="https://shop.com", config=config)
    if not result.success:
        # Save state for retry
        state = strategy.get_state()  # Returns resumable state

# Later: Resume from where it stopped
resume_strategy = BestFirstCrawlingStrategy(
    max_depth=2,
    max_pages=1000,
    resume_state=state  # Pick up where we left off
)
```

### Prefetch Mode (Two-Phase Crawling)

**Use case**: Map site structure first, then selectively process pages

```python
# Phase 1: Prefetch - discover all URLs without heavy processing
prefetch_strategy = BFSDeepCrawlStrategy(
    max_depth=3,
    max_pages=10000,
    # Skip extraction, just find URLs
)

config = CrawlerRunConfig(
    extraction_strategy=prefetch_strategy,
    # Add other lightweight options
)

# Phase 2: Process discovered URLs with full extraction
# Use discovered URLs list for selective processing
```

---

## Batch Crawling with arun_many()

### Overview

`arun_many()` crawls multiple URLs concurrently with intelligent dispatcher management. Avoids spawning a new browser for each URL (unlike naive loop).

### Basic Usage

```python
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

urls = [
    "https://shop.com/products/page1",
    "https://shop.com/products/page2",
    "https://shop.com/products/page3",
]

config = CrawlerRunConfig(
    extraction_strategy="schema_org",  # or any strategy
)

async with AsyncWebCrawler() as crawler:
    # Batch mode: wait for all results
    results = await crawler.arun_many(
        urls=urls,
        config=config,
        stream=False  # Collect all before returning
    )

    for result in results:
        if result.success:
            print(f"Crawled: {result.url}")
```

### Streaming Mode (Preferred for Large Crawls)

**Benefits**:
- Process results as they arrive
- Reduces memory pressure (60% less)
- Start working with early results immediately

```python
async with AsyncWebCrawler() as crawler:
    # Stream mode: process results as they become available
    async for result in await crawler.arun_many(
        urls=urls,
        config=config,
        stream=True  # Returns async generator
    ):
        if result.success:
            # Process each result immediately
            await process_result(result)
            # Result memory released before next fetch completes
```

### URL-Specific Configuration

Different URLs may need different extraction strategies. Use `url_matcher` with glob patterns or lambdas:

```python
# Config 1: Product pages - full extraction
product_config = CrawlerRunConfig(
    url_matcher="*/products/*",  # Glob pattern
    extraction_strategy=JsonCssExtractionStrategy(schema=product_schema),
    wait_until="networkidle",
    cache_mode=CacheMode.ENABLED,
)

# Config 2: Category pages - lightweight
category_config = CrawlerRunConfig(
    url_matcher="*/category/*",
    extraction_strategy="json_css",  # Simpler schema
    wait_until="domcontentloaded",
    cache_mode=CacheMode.ENABLED,
)

# Config 3: Everything else - fallback
default_config = CrawlerRunConfig(
    url_matcher=None,  # Matches all
    extraction_strategy="schema_org",
    wait_until="domcontentloaded",
)

configs = [product_config, category_config, default_config]

async with AsyncWebCrawler() as crawler:
    async for result in await crawler.arun_many(
        urls=mixed_urls,  # Product pages, category pages, etc.
        config=configs,   # Applies matching config to each URL
        stream=True
    ):
        if result.success:
            await process_result(result)
```

**url_matcher types**:
- String glob: `"*.pdf"`, `"*/api/*"`, `"https://example.com/*"`
- Lambda function: `lambda url: 'products' in url`
- Mixed list: `["*/products/*", lambda url: 'featured' in url]` (AND logic)

---

## Browser Session Reuse & Pooling

### Session Reuse (Sequential Workflows)

**Use case**: Multi-step processes (login → browse → extract)

**IMPORTANT**: Sessions are for **sequential** workflows only, NOT parallel

```python
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig

session_id = "user_session_123"

async with AsyncWebCrawler() as crawler:
    # Step 1: Navigate to login page
    login_config = CrawlerRunConfig(
        url="https://shop.com/login",
        session_id=session_id,  # Create new session
    )
    result = await crawler.arun(config=login_config)

    # Step 2: Execute login JavaScript in same session
    login_config2 = CrawlerRunConfig(
        url="https://shop.com",  # Stay on same domain
        session_id=session_id,  # Reuse session (cookies preserved)
        javascript_code="""
            document.querySelector('[name="email"]').value = 'user@example.com';
            document.querySelector('[name="password"]').value = 'password';
            document.querySelector('button[type="submit"]').click();
            await new Promise(r => setTimeout(r, 2000));
        """,
    )
    result = await crawler.arun(config=login_config2)

    # Step 3: Browse to products (session cookies intact)
    product_config = CrawlerRunConfig(
        url="https://shop.com/products",
        session_id=session_id,  # Cookies from login still active
    )
    result = await crawler.arun(config=product_config)

    # Cleanup
    # await crawler.crawler_strategy.kill_session(session_id)
```

### Browser Pooling Architecture (v0.7.0+)

Crawl4AI implements a **3-tier browser pool**:
1. **Permanent** - Always-running browsers for high-traffic
2. **Hot** - Pre-launched, ready to use
3. **Cold** - Spun up on demand

Benefits:
- Reuses browser instances across multiple URLs
- 70% faster browser initialization (v0.7.0)
- ~150MB RAM per browser instance
- Automatic promotion/demotion based on usage

**No explicit configuration needed** - handled automatically by dispatchers

### Persistent Context (Cookies & LocalStorage)

Store authentication state across runs:

```python
from crawl4ai import AsyncWebCrawler, BrowserConfig

# First run: Login and save context
browser_config = BrowserConfig(
    use_persistent_context=True,
    user_data_dir="./browser_data"  # Stores cookies, localStorage
)

async with AsyncWebCrawler(config=browser_config) as crawler:
    # Login happens here
    result = await crawler.arun(url="https://shop.com/login")
    # Browser state saved to disk

# Second run: Context automatically restored
async with AsyncWebCrawler(config=browser_config) as crawler:
    # Cookies and localStorage restored - no re-login needed
    result = await crawler.arun(url="https://shop.com/products")
```

### Storage State Export/Import

Fastest way to reuse authentication:

```python
from crawl4ai import AsyncWebCrawler, BrowserConfig

# Export state after login
async with AsyncWebCrawler() as crawler:
    # ... login sequence ...

    # Export cookies and localStorage to file
    storage_state = await crawler.browser.context.storage_state(
        path="auth_state.json"
    )

# Import state in new crawler
browser_config = BrowserConfig(
    storage_state="auth_state.json"  # Restore cookies/localStorage
)

async with AsyncWebCrawler(config=browser_config) as crawler:
    # Already logged in, same cookies/localStorage
    result = await crawler.arun(url="https://shop.com/products")
```

---

## CrawlerRunConfig Best Practices

### Navigation Tuning

```python
config = CrawlerRunConfig(
    # FAST path (use for simple sites)
    wait_until="domcontentloaded",  # Don't wait for lazy images
    page_timeout=15000,              # 15 second timeout

    # THOROUGH path (dynamic content)
    wait_until="networkidle",        # Wait for JS to finish loading
    page_timeout=30000,              # 30 second timeout

    # Virtual scrolling (infinite scroll sites)
    enable_virtual_scroll=True,
    scroll_behavior="smooth",        # 'instant' for speed

    # Interaction timeouts
    wait_for="#load-more-btn",       # Wait for element
    delay_before_return_html=1000,   # Extra 1s for JS execution
)
```

### Performance Optimization Parameters

```python
# SPEED-FIRST configuration
fast_config = CrawlerRunConfig(
    # Navigation
    wait_until="domcontentloaded",
    page_timeout=10000,

    # Content filtering
    word_count_threshold=10,     # Skip low-content pages
    exclude_external_links=True,

    # Resource blocking
    exclude_all_images=True,     # Don't load images
    text_mode=True,              # Disable CSS, JS (3-4x faster)

    # Caching
    cache_mode=CacheMode.ENABLED,

    # Link extraction
    extract_links=False,         # Skip link extraction
)

# COMPREHENSIVE configuration
thorough_config = CrawlerRunConfig(
    # Navigation
    wait_until="networkidle",
    page_timeout=30000,

    # Content filtering
    word_count_threshold=0,      # Don't skip any content

    # Resource loading
    wait_for_images=True,        # Ensure images load

    # Link extraction
    extract_links=True,
    link_preview_config=LinkPreviewConfig(
        max_links=50,
        concurrency=10,
        score_threshold=0.3,
    ),
)
```

### Caching Strategy

```python
from crawl4ai import CacheMode

# First-time crawl: BYPASS cache (fresh data)
initial_config = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,  # Fetch from web, write to cache
)

# Repeated crawls: READ-WRITE or ENABLED
repeat_config = CrawlerRunConfig(
    cache_mode=CacheMode.ENABLED,  # Read cache if exists, update it
)

# Cache-only (no network): READ_ONLY
offline_config = CrawlerRunConfig(
    cache_mode=CacheMode.READ_ONLY,  # Only use cached data
)

# Disable caching entirely
no_cache_config = CrawlerRunConfig(
    cache_mode=CacheMode.DISABLED,  # No caching, always fetch fresh
)
```

### JavaScript & Interaction

```python
config = CrawlerRunConfig(
    # Execute JS before extraction
    javascript_code="""
        // Expand all product details
        document.querySelectorAll('.expand-btn').forEach(btn => btn.click());
        await new Promise(r => setTimeout(r, 2000));  // Wait for animation

        // Remove ads/popups
        document.querySelectorAll('.ad, .popup').forEach(el => el.remove());
    """,

    # Wait for specific element to be interactive
    wait_for="button.add-to-cart",
    delay_before_return_html=500,  # Extra delay after wait_for element appears

    # Disable iframes (speed improvement)
    extract_iframes=False,

    # Anti-bot settings
    browser_config=BrowserConfig(
        enable_stealth=True,  # Anti-detection
        headless=False,       # Some sites detect headless
    )
)
```

### Resource Blocking (Major Speed Boost)

```python
config = CrawlerRunConfig(
    # Text mode: blocks images, CSS, JS (3-4x faster)
    text_mode=True,

    # Alternative: selective blocking
    text_mode=False,
    exclude_all_images=True,           # No images
    exclude_external_links=True,       # No external domain links
    exclude_domains=["cdn.example.com"],  # Block specific domains
)
```

### Media & Screenshot

```python
config = CrawlerRunConfig(
    # Screenshots
    screenshot=True,
    screenshot_type="png",  # or "jpeg"

    # PDFs
    pdf=True,

    # Media extraction
    exclude_all_images=False,  # Include images in result.media
    exclude_external_images=True,  # Only images from main domain

    # Complete page snapshot (single file)
    capture_mhtml=True,  # Save as MHTML (offline-readable)
)
```

---

## Extraction Strategies Performance

### Strategy Comparison

| Strategy | Speed | Cost | Use Case | Reliability |
|----------|-------|------|----------|-------------|
| **JsonCssExtractionStrategy** | ⚡⚡⚡ Fast | Free | Consistent layouts | High |
| **SchemaOrgExtractionStrategy** | ⚡⚡ Fast | Free | Structured data sites | High |
| **OpenGraphExtractionStrategy** | ⚡⚡ Fast | Free | Social content | High |
| **RegexExtractionStrategy** | ⚡⚡⚡ Fast | Free | Specific patterns | High |
| **LLMExtractionStrategy** | 🐢 Slow | $ | Complex/unstructured | Flexible |

### LLM-Free: JsonCssExtractionStrategy (Recommended for e-commerce)

**Fastest & most reliable for structured data**

```python
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

# Simple product list
simple_schema = {
    "name": "ProductList",
    "baseSelector": ".product-item",
    "fields": [
        {"name": "title", "selector": "h2.product-title", "type": "text"},
        {"name": "price", "selector": ".price", "type": "text"},
        {"name": "url", "selector": "a.product-link", "type": "attribute", "attribute": "href"},
    ]
}

# Complex nested schema with variants
complex_schema = {
    "name": "ProductCatalog",
    "baseSelector": ".product",
    "fields": [
        {"name": "id", "selector": "[data-product-id]", "type": "attribute", "attribute": "data-product-id"},
        {"name": "title", "selector": "h2", "type": "text"},
        {"name": "description", "selector": ".desc", "type": "text"},
        {"name": "price", "selector": ".current-price", "type": "text"},
        {"name": "compare_at_price", "selector": ".original-price", "type": "text", "optional": True},
        {
            "name": "image",
            "type": "nested",
            "selector": "img.primary",
            "fields": [
                {"name": "src", "type": "attribute", "attribute": "src"},
                {"name": "alt", "type": "attribute", "attribute": "alt"}
            ]
        },
        {
            "name": "variants",
            "type": "nested_list",
            "selector": ".variant-option",
            "fields": [
                {"name": "size", "selector": "[data-size]", "type": "attribute", "attribute": "data-size"},
                {"name": "color", "selector": "[data-color]", "type": "attribute", "attribute": "data-color"},
                {"name": "available", "selector": ".available-badge", "type": "text"}
            ]
        },
        {
            "name": "reviews",
            "type": "nested_list",
            "selector": ".review",
            "fields": [
                {"name": "rating", "selector": ".rating", "type": "text"},
                {"name": "text", "selector": ".review-text", "type": "text"},
                {"name": "author", "selector": ".reviewer-name", "type": "text"}
            ]
        }
    ]
}

strategy = JsonCssExtractionStrategy(schema=complex_schema)

config = CrawlerRunConfig(extraction_strategy=strategy)

async with AsyncWebCrawler() as crawler:
    result = await crawler.arun(url="https://shop.com/products", config=config)
    products = json.loads(result.extracted_content)
```

### LLM-Free: RegexExtractionStrategy (Fast Patterns)

**Lightning-fast for known patterns**

```python
from crawl4ai.extraction_strategy import RegexExtractionStrategy

# Built-in patterns
strategy = RegexExtractionStrategy(
    patterns={
        "emails": RegexExtractionStrategy.Email,
        "phones": RegexExtractionStrategy.PhoneUS,
        "prices": RegexExtractionStrategy.Currency,
        "urls": RegexExtractionStrategy.URL,
        "dates": RegexExtractionStrategy.Date,
    }
)

# Custom regex
strategy = RegexExtractionStrategy(
    patterns={
        "product_ids": r"SKU-\d{4}-\d{4}",
        "percentages": r"\d+%",
    }
)
```

### LLM-Free: SchemaOrgExtractionStrategy (Structured Data)

```python
from crawl4ai.extraction_strategy import SchemaOrgExtractionStrategy

strategy = SchemaOrgExtractionStrategy()  # Auto-finds JSON-LD

config = CrawlerRunConfig(extraction_strategy=strategy)

# Extracts all structured data from <script type="application/ld+json">
```

### LLM: LLMExtractionStrategy (Universal, Flexible)

**Use when CSS selectors don't work, for complex reasoning**

```python
from crawl4ai.extraction_strategy import LLMExtractionStrategy
from crawl4ai.llm_models import LLMConfig
from pydantic import BaseModel
from typing import List

# Define desired output schema
class Product(BaseModel):
    title: str
    price: float
    in_stock: bool
    description: str
    image_url: str

class ProductList(BaseModel):
    products: List[Product]

# Configure LLM (multiple providers available)
llm_config = LLMConfig(
    provider="openai",  # or "anthropic", "groq", "ollama"
    model="gpt-4o-mini",  # $0.15 per 1M input, $0.60 per 1M output
    api_key="sk-...",
    temperature=0.0,
)

strategy = LLMExtractionStrategy(
    llm_config=llm_config,
    schema=ProductList.model_json_schema(),
    extraction_type="schema",  # Validate against Pydantic model
    input_format="fit_markdown",  # Reduces tokens 40-60% (use always!)
    chunk_token_threshold=3000,
    overlap_rate=0.1,
)

config = CrawlerRunConfig(
    extraction_strategy=strategy,
    wait_until="networkidle",
)

# Monitor token usage
strategy.show_usage()  # Print token stats
```

### Cost Optimization: Fit Markdown

**Critical for LLM extraction - reduces tokens 40-60%**

```python
# BAD - Sends full HTML
config = CrawlerRunConfig(
    extraction_strategy=LLMExtractionStrategy(
        input_format="html",  # Bloated!
    )
)

# GOOD - Sends cleaned markdown (40-60% smaller)
config = CrawlerRunConfig(
    extraction_strategy=LLMExtractionStrategy(
        input_format="fit_markdown",  # Always use this!
        chunk_token_threshold=3000,   # Auto-chunk large pages
    )
)
```

---

## Memory & Performance Optimization

### MemoryAdaptiveDispatcher

**Default dispatcher** - Manages concurrency based on system memory

```python
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher, CrawlerMonitor, DisplayMode

dispatcher = MemoryAdaptiveDispatcher(
    memory_threshold_percent=70.0,  # Throttle at 70% memory (default 90%)
    check_interval=0.5,              # Check every 0.5 seconds
    max_session_permit=20,           # Max concurrent crawls
    monitor=CrawlerMonitor(
        display_mode=DisplayMode.DETAILED  # Verbose progress
    )
)

async with AsyncWebCrawler() as crawler:
    async for result in await crawler.arun_many(
        urls=urls,
        config=CrawlerRunConfig(stream=True),
        dispatcher=dispatcher
    ):
        if result.success:
            await process_result(result)
```

### SemaphoreDispatcher (Fixed Concurrency)

**When you want precise control**

```python
from crawl4ai.async_dispatcher import SemaphoreDispatcher

dispatcher = SemaphoreDispatcher(
    semaphore_count=10,  # Max 10 concurrent crawls
    rate_limiter=RateLimiter(
        base_delay=(1.0, 2.0),  # Random delay 1-2 seconds
        max_delay=30.0,
        max_retries=3,
        rate_limit_codes=[429, 503],  # Exponential backoff on these
    )
)
```

### RateLimiter Configuration

```python
from crawl4ai.infra import RateLimiter

rate_limiter = RateLimiter(
    base_delay=(1.0, 2.0),           # Random delay 1-2 sec between requests
    max_delay=60.0,                  # Cap delay at 60 sec
    max_retries=5,                   # Retry up to 5 times
    rate_limit_codes=[429, 503],     # HTTP codes triggering backoff
    backoff_factor=2.0,              # Exponential: delay *= 2 on retry
)
```

### Streaming vs Batch

**Streaming (Recommended for large crawls)**:
- Process results as they arrive
- 60% memory reduction
- Start working immediately
- Better UX for progress tracking

```python
async for result in await crawler.arun_many(
    urls=urls,
    config=CrawlerRunConfig(stream=True),
    dispatcher=dispatcher
):
    if result.success:
        await process_result(result)  # Immediate processing
        # Memory released before next crawl completes
```

**Batch (Small/medium crawls)**:
- Simpler code
- All results in one list
- Easier error handling

```python
results = await crawler.arun_many(
    urls=urls,
    config=CrawlerRunConfig(stream=False),
    dispatcher=dispatcher
)

for result in results:
    if result.success:
        await process_result(result)
```

### Text Mode (3-4x Speed Boost)

```python
# Ultra-fast for text-only content
fast_config = CrawlerRunConfig(
    text_mode=True,  # Disables images, CSS, JS rendering
    wait_until="domcontentloaded",
)

# Equivalent manual configuration
manual_fast_config = CrawlerRunConfig(
    exclude_all_images=True,
    wait_until="domcontentloaded",
    browser_config=BrowserConfig(
        viewport={"width": 800, "height": 600}  # Smaller = faster
    )
)
```

### Caching for Repeated Crawls

```python
# First crawl
config_bypass = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,  # Fresh from web, write to cache
)

results = await crawler.arun_many(urls=urls, config=config_bypass)

# Subsequent crawls (10x faster)
config_cached = CrawlerRunConfig(
    cache_mode=CacheMode.ENABLED,  # Read from cache if available
)

results = await crawler.arun_many(urls=urls, config=config_cached)
```

### Resource Blocking

```python
config = CrawlerRunConfig(
    exclude_all_images=True,           # No images
    exclude_external_links=True,       # No external domain links
    exclude_domains=[                  # Block specific CDNs
        "cdn.example.com",
        "analytics.example.com",
    ],
)
```

---

## Complete Code Examples

### Example 1: E-commerce Product Crawler (20-100 URLs)

Crawl product pages from same domain, extract structured data, reuse browser session.

```python
import asyncio
import json
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher

# Product extraction schema
PRODUCT_SCHEMA = {
    "name": "ProductExtractor",
    "baseSelector": ".product-item",
    "fields": [
        {"name": "id", "selector": "[data-sku]", "type": "attribute", "attribute": "data-sku"},
        {"name": "title", "selector": ".product-title", "type": "text"},
        {"name": "price", "selector": ".price-current", "type": "text"},
        {"name": "compare_at_price", "selector": ".price-original", "type": "text"},
        {"name": "description", "selector": ".product-description", "type": "text"},
        {
            "name": "image",
            "type": "nested",
            "selector": "img.product-image",
            "fields": [
                {"name": "src", "type": "attribute", "attribute": "src"},
                {"name": "alt", "type": "attribute", "attribute": "alt"}
            ]
        },
        {
            "name": "variants",
            "type": "nested_list",
            "selector": ".variant",
            "fields": [
                {"name": "size", "selector": "[data-size]", "type": "attribute", "attribute": "data-size"},
                {"name": "color", "selector": "[data-color]", "type": "attribute", "attribute": "data-color"}
            ]
        }
    ]
}

async def crawl_products(product_urls: list[str]) -> list[dict]:
    """Crawl multiple product pages efficiently"""

    strategy = JsonCssExtractionStrategy(schema=PRODUCT_SCHEMA)

    config = CrawlerRunConfig(
        extraction_strategy=strategy,
        wait_until="domcontentloaded",
        cache_mode=CacheMode.ENABLED,
        exclude_all_images=False,  # Keep images for product pages
    )

    dispatcher = MemoryAdaptiveDispatcher(
        memory_threshold_percent=75,
        max_session_permit=5,  # 5 concurrent
    )

    all_products = []

    async with AsyncWebCrawler() as crawler:
        async for result in await crawler.arun_many(
            urls=product_urls,
            config=config,
            dispatcher=dispatcher,
            stream=True
        ):
            if result.success:
                products = json.loads(result.extracted_content)
                all_products.extend(products)
                print(f"Extracted {len(products)} from {result.url}")
            else:
                print(f"Failed: {result.url}")

    return all_products

# Usage
product_urls = [
    f"https://shop.com/products/item-{i}" for i in range(1, 51)
]

products = asyncio.run(crawl_products(product_urls))
```

### Example 2: Deep Crawl Product Catalog (Best-First Strategy)

Crawl entire product catalog automatically, prioritizing by relevance.

```python
import asyncio
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.deep_crawling import BestFirstCrawlingStrategy
from crawl4ai.deep_crawling.scorers import KeywordRelevanceScorer
from crawl4ai.deep_crawling.filters import URLPatternFilter, FilterChain
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

async def deep_crawl_products():
    """Auto-discover and crawl product catalog"""

    # Filter to product/category pages only
    filters = FilterChain([
        URLPatternFilter(patterns=[
            "*/products/*",
            "*/category/*",
            "*/shop/*"
        ])
    ])

    # Score URLs by relevance
    scorer = KeywordRelevanceScorer(
        keywords=["product", "price", "inventory", "add to cart", "buy"],
        weight=0.7
    )

    # Deep crawl strategy
    strategy = BestFirstCrawlingStrategy(
        max_depth=3,
        include_external=False,
        max_pages=500,
        filter_chain=filters,
        url_scorer=scorer,
        score_threshold=0.2,
    )

    # Extract products using CSS
    product_strategy = JsonCssExtractionStrategy(schema=PRODUCT_SCHEMA)

    config = CrawlerRunConfig(
        extraction_strategy=product_strategy,
        wait_until="domcontentloaded",
        cache_mode=CacheMode.ENABLED,
    )

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url="https://shop.com",
            config=config
        )

    if result.success:
        print(f"Crawled {len(result.links)} pages")
        return result.extracted_content

asyncio.run(deep_crawl_products())
```

### Example 3: Session-Based Authentication + Crawling

Multi-step workflow: login → browse → extract

```python
async def crawl_with_authentication():
    """Crawl authenticated pages (e.g., user dashboard, private inventory)"""

    session_id = "auth_session"

    config = CrawlerRunConfig(
        extraction_strategy=JsonCssExtractionStrategy(schema=PRODUCT_SCHEMA),
        wait_until="networkidle",
        session_id=session_id,
    )

    async with AsyncWebCrawler() as crawler:
        # Step 1: Login
        login_result = await crawler.arun(
            url="https://shop.com/login",
            config=CrawlerRunConfig(
                session_id=session_id,
                javascript_code="""
                    document.querySelector('input[name="email"]').value = 'user@example.com';
                    document.querySelector('input[name="password"]').value = 'password123';
                    document.querySelector('button[type="submit"]').click();
                    await new Promise(r => setTimeout(r, 3000));  // Wait for redirect
                """,
                wait_for=".dashboard",
                page_timeout=15000,
            )
        )

        # Step 2: Navigate to inventory (session cookies intact)
        inventory_result = await crawler.arun(
            url="https://shop.com/dashboard/inventory",
            config=config  # Reuse session - already logged in!
        )

        if inventory_result.success:
            products = json.loads(inventory_result.extracted_content)
            print(f"Retrieved {len(products)} inventory items")

asyncio.run(crawl_with_authentication())
```

### Example 4: Adaptive Crawling with URL-Specific Configs

Different extraction strategies for different page types.

```python
async def adaptive_multi_url_crawl():
    """Crawl different page types with optimized configs"""

    # Config 1: Product pages (full extraction)
    product_config = CrawlerRunConfig(
        url_matcher="*/products/*",
        extraction_strategy=JsonCssExtractionStrategy(schema=PRODUCT_SCHEMA),
        wait_until="networkidle",
        cache_mode=CacheMode.ENABLED,
    )

    # Config 2: Category pages (links only)
    category_config = CrawlerRunConfig(
        url_matcher="*/category/*",
        extraction_strategy="schema_org",
        wait_until="domcontentloaded",
        extract_links=True,
    )

    # Config 3: Fallback (text only)
    default_config = CrawlerRunConfig(
        url_matcher=None,  # Matches all
        text_mode=True,
        wait_until="domcontentloaded",
    )

    urls = [
        "https://shop.com/products/item-1",
        "https://shop.com/category/electronics",
        "https://shop.com/about",
    ]

    configs = [product_config, category_config, default_config]

    async with AsyncWebCrawler() as crawler:
        async for result in await crawler.arun_many(
            urls=urls,
            config=configs,  # Applies matching config to each URL
            stream=True
        ):
            if result.success:
                print(f"{result.url}: {len(result.extracted_content)} chars extracted")

asyncio.run(adaptive_multi_url_crawl())
```

### Example 5: Performance-Optimized Batch Crawl (100+ URLs)

Ultra-fast crawling with all optimizations enabled.

```python
async def fast_batch_crawl(urls: list[str]):
    """Fastest possible crawling for simple sites"""

    dispatcher = MemoryAdaptiveDispatcher(
        memory_threshold_percent=70,
        max_session_permit=20,  # Many concurrent crawls
    )

    config = CrawlerRunConfig(
        # Speed optimizations
        text_mode=True,                    # 3-4x faster
        wait_until="domcontentloaded",     # Don't wait for lazy content
        exclude_all_images=True,           # Skip images
        exclude_external_links=True,       # Skip external URLs

        # Caching
        cache_mode=CacheMode.ENABLED,

        # Timeouts
        page_timeout=10000,                # 10 second limit

        # Light extraction
        extraction_strategy="schema_org",  # Fastest free strategy
    )

    async with AsyncWebCrawler() as crawler:
        async for result in await crawler.arun_many(
            urls=urls,
            config=config,
            dispatcher=dispatcher,
            stream=True
        ):
            if result.success:
                yield result
            else:
                print(f"Failed: {result.url} - {result.error_message}")

# Usage: Stream results without loading all into memory
async for result in fast_batch_crawl(urls):
    await process_result(result)
```

---

## Summary: Recommended Patterns for Merchant Onboarding

### For URL Discovery (50-500 URLs from one domain)

Use **BestFirstCrawlingStrategy** with **KeywordRelevanceScorer**:
- Automatically finds all product URLs
- Prioritizes high-relevance pages
- Stops at max_pages limit gracefully
- Scales to large catalogs

### For Product Extraction (20-100 URLs per page)

Use **arun_many() with streaming**:
- Reuse single browser session across multiple URLs
- Process results as they arrive (60% memory savings)
- MemoryAdaptiveDispatcher handles concurrency
- RateLimiter prevents server blocking

### For Extraction Strategy (per platform)

1. **Try Tier 1** (API if available)
2. **Try Tier 2** (JsonCssExtractionStrategy with schema_org fallback)
3. **Try Tier 3** (LLMExtractionStrategy with fit_markdown)
4. **Fallback** to text-only extraction

### Performance Settings

```python
# For fast, simple sites
fast_config = CrawlerRunConfig(
    wait_until="domcontentloaded",
    cache_mode=CacheMode.ENABLED,
    exclude_all_images=True,
)

# For complex, dynamic sites
thorough_config = CrawlerRunConfig(
    wait_until="networkidle",
    cache_mode=CacheMode.ENABLED,
    wait_for_images=True,
)
```

---

## Sources

- [Deep Crawling - Crawl4AI Documentation (v0.8.x)](https://docs.crawl4ai.com/core/deep-crawling/)
- [Multi-URL Crawling - Crawl4AI Documentation (v0.8.x)](https://docs.crawl4ai.com/advanced/multi-url-crawling/)
- [AsyncWebCrawler - Crawl4AI Documentation (v0.8.x)](https://docs.crawl4ai.com/api/async-webcrawler/)
- [Browser, Crawler & LLM Config - Crawl4AI Documentation (v0.8.x)](https://docs.crawl4ai.com/core/browser-crawler-config/)
- [Session Management - Crawl4AI Documentation (v0.7.x)](https://docs.crawl4ai.com/advanced/session-management/)
- [LLM-Free Strategies - Crawl4AI Documentation (v0.8.x)](https://docs.crawl4ai.com/extraction/no-llm-strategies/)
- [LLM Strategies - Crawl4AI Documentation (v0.8.x)](https://docs.crawl4ai.com/extraction/llm-strategies/)
- [Cache Modes - Crawl4AI Documentation (v0.7.x)](https://docs.crawl4ai.com/core/cache-modes/)
- [Link & Media - Crawl4AI Documentation (v0.8.x)](https://docs.crawl4ai.com/core/link-media/)
- [Crawl4AI v0.7.0: The Adaptive Intelligence Update - Crawl4AI Documentation (v0.8.x)](https://docs.crawl4ai.com/blog/releases/0.7.0/)
- [Deep Crawl Example - GitHub](https://github.com/unclecode/crawl4ai/blob/main/docs/examples/deepcrawl_example.py)
- [GitHub - unclecode/crawl4ai](https://github.com/unclecode/crawl4ai)
