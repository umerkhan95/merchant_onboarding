# Crawl4AI Implementation Quick Reference

**For Merchant Onboarding Pipeline**

---

## Installation & Setup

```bash
pip install crawl4ai
crawl4ai-setup      # Validate environment
crawl4ai-doctor     # Diagnose issues
```

---

## Decision Tree: Which Crawling Approach?

```
You want to crawl:

├─ A few pages (2-10)?
│  └─ Use: arun() in loop OR arun_many() with stream=False
│     (Simple, no complex orchestration needed)
│
├─ Many URLs (20-100) from same domain?
│  └─ Use: arun_many() with MemoryAdaptiveDispatcher + streaming
│     (Efficient, reuses browser, processes as they arrive)
│
├─ Entire e-commerce catalog (100-10,000 products)?
│  ├─ Known API endpoint? → Use platform-specific extractor
│  └─ No API? → Use BestFirstCrawlingStrategy + KeywordRelevanceScorer
│     (Auto-discovers URLs, prioritizes by relevance)
│
└─ Authenticated pages or multi-step workflows?
   └─ Use: session_id across multiple arun() calls
      (Cookies preserved, sequential only, not parallel)
```

---

## Setup: One-Time Configuration

```python
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig, CacheMode

# Global browser config (reuse across all crawls)
browser_config = BrowserConfig(
    browser_type="chromium",
    headless=True,
    viewport={"width": 1920, "height": 1080},
    enable_stealth=True,  # Anti-bot
)

async with AsyncWebCrawler(config=browser_config) as crawler:
    # All crawls in this context reuse same browser
    pass
```

---

## Quick Reference: Common Patterns

### Pattern 1: Fast Extraction from 20-100 URLs (Streaming)

```python
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig, CacheMode
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher

async def crawl_many_urls(urls):
    strategy = JsonCssExtractionStrategy(schema={...})

    config = CrawlerRunConfig(
        extraction_strategy=strategy,
        wait_until="domcontentloaded",
        cache_mode=CacheMode.ENABLED,
    )

    dispatcher = MemoryAdaptiveDispatcher(
        memory_threshold_percent=75,
        max_session_permit=10,
    )

    async with AsyncWebCrawler() as crawler:
        async for result in await crawler.arun_many(
            urls=urls,
            config=config,
            dispatcher=dispatcher,
            stream=True
        ):
            if result.success:
                yield result  # Process immediately, don't buffer
```

### Pattern 2: Deep Product Discovery (Best-First)

```python
from crawl4ai.deep_crawling import BestFirstCrawlingStrategy
from crawl4ai.deep_crawling.scorers import KeywordRelevanceScorer
from crawl4ai.deep_crawling.filters import URLPatternFilter, FilterChain

strategy = BestFirstCrawlingStrategy(
    max_depth=3,
    max_pages=500,
    url_scorer=KeywordRelevanceScorer(
        keywords=["product", "price", "buy"],
        weight=0.7
    ),
    filter_chain=FilterChain([
        URLPatternFilter(patterns=["*/products/*", "*/shop/*"])
    ]),
)

config = CrawlerRunConfig(extraction_strategy=strategy)

result = await crawler.arun(url="https://shop.com", config=config)
```

### Pattern 3: Authenticated Crawling

```python
session_id = "user_session"

# Step 1: Login
await crawler.arun(
    url="https://shop.com/login",
    config=CrawlerRunConfig(
        session_id=session_id,
        javascript_code="... login script ...",
        wait_for=".dashboard",
    )
)

# Step 2: Browse (cookies still active)
result = await crawler.arun(
    url="https://shop.com/inventory",
    config=CrawlerRunConfig(
        session_id=session_id,  # Cookies preserved!
        extraction_strategy=strategy,
    )
)
```

### Pattern 4: URL-Specific Configs

```python
configs = [
    CrawlerRunConfig(
        url_matcher="*/products/*",
        extraction_strategy=JsonCssExtractionStrategy(schema=product_schema),
    ),
    CrawlerRunConfig(
        url_matcher="*/category/*",
        extraction_strategy="schema_org",
    ),
    CrawlerRunConfig(
        url_matcher=None,  # Fallback for everything else
        text_mode=True,
    ),
]

# Apply automatically based on URL
async for result in await crawler.arun_many(urls, config=configs):
    pass
```

---

## Parameter Quick Guide

### wait_until Options

| Option | Speed | Best For |
|--------|-------|----------|
| `"domcontentloaded"` | Fast ⚡ | Simple sites, product listings |
| `"networkidle"` | Slow 🐢 | SPAs, infinite scroll, dynamic content |

**Recommendation**: Start with `"domcontentloaded"`, upgrade to `"networkidle"` if data incomplete.

### Extraction Strategies

| Strategy | Speed | Cost | Best For |
|----------|-------|------|----------|
| `JsonCssExtractionStrategy` | ⚡⚡⚡ | Free | Structured layouts |
| `SchemaOrgExtractionStrategy` | ⚡⚡ | Free | Pages with JSON-LD |
| `"schema_org"` (auto) | ⚡⚡ | Free | Quick extraction |
| `LLMExtractionStrategy` | 🐢 | $ | Complex/messy HTML |

**Recommendation**:
1. Try `JsonCssExtractionStrategy` with CSS selectors first
2. Fall back to `"schema_org"` if no CSS schema available
3. Use `LLMExtractionStrategy` only if others fail (cost: ~$0.01/page)

### CacheMode Options

| Mode | Read Cache | Write Cache | Use For |
|------|------------|-------------|---------|
| `ENABLED` | ✅ | ✅ | Repeated crawls (10x faster) |
| `BYPASS` | ❌ | ✅ | Fresh data, seed cache |
| `READ_ONLY` | ✅ | ❌ | Offline mode |
| `DISABLED` | ❌ | ❌ | Always fresh, never cache |

**Recommendation**: Use `BYPASS` on first run, then `ENABLED` for repeats.

---

## Performance Tuning Checklist

### For Speed (3-4x faster)

```python
config = CrawlerRunConfig(
    text_mode=True,                  # ← Single biggest boost
    wait_until="domcontentloaded",
    exclude_all_images=True,
    cache_mode=CacheMode.ENABLED,
    page_timeout=10000,              # 10 sec limit
)
```

### For Reliability (catches dynamic content)

```python
config = CrawlerRunConfig(
    wait_until="networkidle",        # Wait for JS to finish
    wait_for_images=True,            # Ensure media loads
    page_timeout=30000,              # 30 sec timeout
    delay_before_return_html=1000,   # Extra 1s for JS
)
```

### For Memory (large crawls)

```python
dispatcher = MemoryAdaptiveDispatcher(
    memory_threshold_percent=70,     # Throttle at 70% RAM
    max_session_permit=10,           # Limit concurrent
    check_interval=0.5,              # Check frequently
)

# AND use streaming!
async for result in await crawler.arun_many(
    urls=urls,
    stream=True,  # Process immediately, don't buffer
):
    pass
```

---

## Extraction Schema Builder (CSS)

### Simple Schema

```python
schema = {
    "name": "ProductList",
    "baseSelector": ".product",  # Container for each item
    "fields": [
        {"name": "title", "selector": "h2", "type": "text"},
        {"name": "price", "selector": ".price", "type": "text"},
        {"name": "url", "selector": "a", "type": "attribute", "attribute": "href"},
    ]
}
```

### Nested Schema (Variants, Reviews, Images)

```python
schema = {
    "name": "ProductDetail",
    "baseSelector": ".product",
    "fields": [
        {"name": "title", "selector": "h1", "type": "text"},
        {
            "name": "primary_image",
            "type": "nested",
            "selector": "img.main-image",
            "fields": [
                {"name": "src", "type": "attribute", "attribute": "src"},
                {"name": "alt", "type": "attribute", "attribute": "alt"}
            ]
        },
        {
            "name": "variants",  # List of variants
            "type": "nested_list",
            "selector": ".size-option",
            "fields": [
                {"name": "size", "selector": "[data-size]", "type": "attribute", "attribute": "data-size"},
                {"name": "available", "selector": ".available", "type": "text"}
            ]
        },
        {
            "name": "reviews",   # List of reviews
            "type": "nested_list",
            "selector": ".review",
            "fields": [
                {"name": "rating", "selector": ".stars", "type": "text"},
                {"name": "text", "selector": ".review-text", "type": "text"}
            ]
        }
    ]
}
```

### Tips

- Use multiple selector fallbacks: `"h1, .product-title, [data-name]"`
- Test selectors in browser DevTools before using
- `nested` for single object, `nested_list` for arrays
- Use `type="attribute"` for `href`, `src`, `data-*` attributes

---

## Error Handling Patterns

### Try-Catch for Single URL

```python
try:
    result = await crawler.arun(url=url, config=config)
    if not result.success:
        logger.error(f"Crawl failed: {result.error_message}")
        return None
    return result
except Exception as e:
    logger.error(f"Exception during crawl: {e}")
    return None
```

### Streaming Error Handling

```python
failed_urls = []

async for result in await crawler.arun_many(urls, config=config, stream=True):
    if result.success:
        await process_result(result)
    else:
        failed_urls.append((result.url, result.error_message))
        logger.error(f"Failed: {result.url}")

# Retry failed URLs later
if failed_urls:
    logger.info(f"Retrying {len(failed_urls)} failed URLs...")
    retry_urls = [url for url, _ in failed_urls]
    # Can retry with different config or strategy
```

---

## Migration from Old Code

### Old (v0.6)

```python
from crawl4ai import AsyncWebCrawler

crawler = AsyncWebCrawler()
result = await crawler.arun(url)
await crawler.close()
```

### New (v0.7+)

```python
from crawl4ai import AsyncWebCrawler

async with AsyncWebCrawler() as crawler:
    result = await crawler.arun(url)
    # Auto-closes, no manual cleanup
```

### Cache Migration

**Old**:
```python
config = CrawlerRunConfig(bypass_cache=True)
```

**New**:
```python
from crawl4ai import CacheMode

config = CrawlerRunConfig(cache_mode=CacheMode.BYPASS)
```

---

## Resource Limits (Self-Hosting)

For Docker deployment:

```python
from crawl4ai.async_dispatcher import MemoryAdaptiveDispatcher

# Conservative: 500MB RAM, 5 concurrent crawls
dispatcher = MemoryAdaptiveDispatcher(
    memory_threshold_percent=70,
    max_session_permit=5,
    check_interval=1.0,
)

# Aggressive: 4GB RAM, 20 concurrent
dispatcher = MemoryAdaptiveDispatcher(
    memory_threshold_percent=80,
    max_session_permit=20,
    check_interval=0.5,
)
```

**Memory per browser**: ~150MB
**Total limit**: Set `memory_threshold_percent` to trigger throttling

---

## Debugging Tips

### Check Extraction Schema

```python
# Test schema on single page first
config = CrawlerRunConfig(
    extraction_strategy=JsonCssExtractionStrategy(schema=my_schema),
    verbose=True,
)

result = await crawler.arun(url=test_url, config=config)
print(result.extracted_content)  # See what was extracted
```

### Monitor Progress

```python
from crawl4ai.async_dispatcher import CrawlerMonitor, DisplayMode

monitor = CrawlerMonitor(display_mode=DisplayMode.DETAILED)

dispatcher = MemoryAdaptiveDispatcher(monitor=monitor)
# Prints real-time stats: URLs processed, memory, time
```

### View Network Requests

```python
result = await crawler.arun(url=url, config=config)
print(result.network_log)  # All network requests made
```

### Capture Screenshots

```python
config = CrawlerRunConfig(
    screenshot=True,
    screenshot_type="png",
)

result = await crawler.arun(url=url, config=config)
with open("screenshot.png", "wb") as f:
    f.write(result.screenshot)  # Binary image data
```

---

## Common Issues & Solutions

| Issue | Cause | Solution |
|-------|-------|----------|
| Timeout errors | Page too slow | Increase `page_timeout`, use `wait_until="networkidle"` |
| Empty extracted_content | Wrong selectors | Validate CSS selectors in DevTools |
| Memory spike | Too many concurrent crawls | Reduce `max_session_permit`, use smaller batches |
| Extraction incomplete | Content loaded by JS | Use `wait_for` element or increase `delay_before_return_html` |
| Cache not working | Cache not enabled | Set `cache_mode=CacheMode.ENABLED` explicitly |
| Blocked by server | Rate limiting | Add `RateLimiter` with delays, respect robots.txt |
| Session lost | Wrong session_id | Reuse exact same `session_id` string |

---

## Performance Benchmarks (v0.7.0)

Compared to v0.5.0:

- Browser startup: **70% faster**
- Page loading: **40% faster**
- CSS extraction: **3x faster**
- Memory usage: **60% reduction** (with streaming)
- Concurrent crawls: **5x improvement**

**Real-world**: 1000 product pages on modern hardware:
- Without streaming: ~2 minutes, ~1.2GB RAM
- With streaming + memory tuning: ~1 minute, ~200MB RAM

---

## References

For full documentation, visit:
- [Crawl4AI Docs](https://docs.crawl4ai.com/)
- [GitHub Repository](https://github.com/unclecode/crawl4ai)
- [API Reference](https://docs.crawl4ai.com/complete-sdk-reference/)
