# Crawl4AI Quick Reference Guide

**For E-commerce Product Data Extraction**

---

## Quick Start Code

```python
import asyncio
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
import json

async def extract_products():
    schema = {
        "name": "Products",
        "baseSelector": ".product-card",
        "fields": [
            {"name": "title", "selector": ".title", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text"},
            {"name": "url", "selector": "a", "type": "attribute", "attribute": "href"}
        ]
    }

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url="https://example.com/products",
            config=CrawlerRunConfig(
                extraction_strategy=JsonCssExtractionStrategy(schema)
            )
        )

        if result.success:
            products = json.loads(result.extracted_content)
            print(json.dumps(products, indent=2))

asyncio.run(extract_products())
```

---

## Field Types Cheat Sheet

| Type | Use Case | Example |
|------|----------|---------|
| `text` | Extract element text | `{"name": "title", "selector": "h1", "type": "text"}` |
| `attribute` | Extract HTML attributes | `{"name": "url", "selector": "a", "type": "attribute", "attribute": "href"}` |
| `html` | Get full HTML block | `{"name": "content", "selector": ".description", "type": "html"}` |
| `nested` | Single sub-object | `{"name": "image", "type": "nested", "fields": [...]}` |
| `nested_list` | Array of objects | `{"name": "reviews", "type": "nested_list", "fields": [...]}` |
| `regex` | Pattern matching | `{"name": "price", "type": "regex", "pattern": r"\$(\d+)"}` |

---

## CSS Selector Patterns

### Common E-commerce Selectors

```css
/* Container */
.product-item
.product-card
[data-product-id]
article.product

/* Title */
.title
h1, h2, h3
.product-name
[data-product-title]

/* Price */
.price
[data-price]
span.price
.product-price

/* Images */
img.product-image
img[alt*="product"]
.gallery img
picture img

/* Links */
a.product-link
[href*="/product/"]
h1 a, h2 a

/* Rating */
.rating
.stars
[data-rating]
span.review-count
```

### Combining Multiple Selectors

Use commas to try multiple selectors in order:

```python
{
    "name": "title",
    "selector": "h1, h2.title, .product-title, [data-productid] .name",
    "type": "text"
}
```

---

## Platform-Specific Quick Reference

### Shopify

```python
# Option 1: Use /products.json API (Fastest)
url = "https://example.myshopify.com/products.json?limit=50&offset=0"

# Option 2: Scrape product pages
selector_map = {
    "title": "h1.product-title",
    "price": "span.price",
    "image": "img.product-photo",
    "container": "div.product-single"
}

# Available fields in API response:
# id, handle, title, body_html, vendor, product_type, created_at,
# images[], options[], variants[], tags
```

### WooCommerce

```python
# Option 1: Use REST API (Recommended)
url = "https://example.com/wp-json/wc/v3/products?page=1&per_page=100"

# Query params:
# ?page=1&per_page=100
# ?search=keyword
# ?orderby=popularity
# ?category=15
# ?on_sale=true
# ?min_price=10&max_price=100

# Option 2: Scrape product pages
selector_map = {
    "title": "h1.product_title",
    "price": ".woocommerce-Price-amount",
    "image": ".woocommerce-product-gallery img",
    "container": "article.type-product"
}

# CSS class prefixes:
# .woocommerce div.product  # Most elements
# .woocommerce-product-     # Component classes
# .wc-block-              # Block classes
```

### Generic Sites

```python
# Common patterns to try:
patterns = [
    (".product-item", ".title", ".price"),
    (".product-card", "h2", ".price"),
    ("[data-product-id]", "[data-product-name]", "[data-price]"),
    ("article.product", "h1", "span.price"),
    ("div.item", ".name, h3", ".cost, .price")
]

# Check meta tags:
# og:title, og:description, og:image
# og:price:amount, og:price:currency

# Check schema.org markup:
# script[type="application/ld+json"]
```

---

## Configuration Options

### BrowserConfig

```python
from crawl4ai import BrowserConfig

config = BrowserConfig(
    browser_type="chromium",              # chromium, firefox, webkit
    headless=True,                        # False for debugging
    enable_stealth=True,                  # Bypass bot detection
    user_agent_mode="random",             # random, fixed, or custom
    proxy_config=ProxyConfig(             # Proxy settings
        server="http://proxy:8080"
    )
)
```

### CrawlerRunConfig

```python
from crawl4ai import CrawlerRunConfig, CacheMode

config = CrawlerRunConfig(
    cache_mode=CacheMode.BYPASS,          # BYPASS, ENABLED, DISABLED
    extraction_strategy=strategy,         # Extraction method
    wait_for=".product-price",            # CSS selector to wait for
    js_code="...",                        # Execute JS before extraction
    page_timeout=20000,                   # Timeout in ms
    screenshot=True,                      # Capture screenshot
    pdf=True,                             # Generate PDF
    check_robots_txt=True,                # Respect robots.txt
    scan_full_page=True                   # Scroll entire page
)
```

### Rate Limiting & Multi-URL

```python
from crawl4ai import RateLimiter, SemaphoreDispatcher, MemoryAdaptiveDispatcher

# Rate limiter
rate_limiter = RateLimiter(
    base_delay=(2.0, 4.0),                # Random 2-4 second delay
    max_delay=30.0,                       # Max 30 second backoff
    max_retries=2,                        # Retry twice
    rate_limit_codes=[429, 503]           # Rate limit HTTP codes
)

# Fixed concurrency dispatcher
dispatcher = SemaphoreDispatcher(
    semaphore_count=3,                    # Max 3 concurrent requests
    rate_limiter=rate_limiter
)

# Adaptive dispatcher (recommended for large crawls)
dispatcher = MemoryAdaptiveDispatcher(
    memory_threshold_percent=80,          # Pause at 80% RAM
    max_semaphore_count=10,               # Max concurrency
    rate_limiter=rate_limiter
)

# Use in batch crawling
results = await crawler.arun_many(
    urls=urls,
    config=config,
    dispatcher=dispatcher
)
```

---

## Transform Options

Apply to extracted text:

```python
{
    "name": "price",
    "selector": ".price",
    "type": "text",
    "transform": "strip"        # Remove whitespace
    # Other: "lowercase", "uppercase"
}
```

---

## CrawlResult Fields

```python
result.url                  # Final URL (after redirects)
result.success              # Boolean
result.status_code          # HTTP code
result.error_message        # Error description
result.html                 # Raw HTML
result.markdown             # Markdown version
result.cleaned_html         # Sanitized HTML
result.extracted_content    # Structured data (JSON string)
result.screenshot           # Base64 image
result.pdf                  # PDF bytes
result.metadata             # Page metadata
result.links                # {"internal": [...], "external": [...]}
result.media                # {"images": [...], "videos": [...]}
result.session_id           # For session reuse
```

---

## Common Patterns

### Extract with Dynamic Content

```python
config = CrawlerRunConfig(
    wait_for=".product-price",  # Wait for element
    js_code="""
        window.scrollTo(0, document.body.scrollHeight);
        document.querySelectorAll('.expand-btn').forEach(b => b.click());
    """,
    page_timeout=15000
)
```

### Handle Pagination

```python
products = []
for page in range(1, 6):
    result = await crawler.arun(
        url=f"https://example.com/products?page={page}",
        config=config
    )
    # Process result
```

### Extract Meta Tags

```python
{
    "name": "og_title",
    "selector": 'meta[property="og:title"]',
    "type": "attribute",
    "attribute": "content"
}
```

### Extract Nested Objects

```python
{
    "name": "rating",
    "type": "nested",
    "selector": ".rating-section",
    "fields": [
        {"name": "stars", "selector": ".stars", "type": "text"},
        {"name": "count", "selector": ".count", "type": "text"}
    ]
}
```

### Extract Lists

```python
{
    "name": "reviews",
    "type": "nested_list",
    "baseSelector": ".review-item",
    "fields": [
        {"name": "author", "selector": ".author", "type": "text"},
        {"name": "rating", "selector": ".rating", "type": "text"},
        {"name": "text", "selector": ".text", "type": "text"}
    ]
}
```

---

## Error Handling

```python
result = await crawler.arun(url="https://example.com")

if not result.success:
    print(f"Error: {result.error_message}")
    print(f"Status: {result.status_code}")

if result.extracted_content:
    try:
        data = json.loads(result.extracted_content)
    except json.JSONDecodeError as e:
        print(f"JSON error: {e}")
```

---

## Performance Tips

1. **Use REST APIs when available** (Shopify, WooCommerce)
   - Much faster than scraping
   - More reliable
   - Less bandwidth

2. **Cache results**
   ```python
   config = CrawlerRunConfig(cache_mode=CacheMode.ENABLED)
   ```

3. **Use appropriate delays**
   ```python
   base_delay=(2.0, 4.0)  # 2-4 seconds between requests
   ```

4. **Limit concurrency**
   ```python
   semaphore_count=2  # Conservative for most sites
   ```

5. **Set reasonable timeouts**
   ```python
   page_timeout=15000  # 15 seconds
   ```

6. **Use session management**
   ```python
   result.session_id  # Reuse for stateful crawling
   ```

---

## Common Selectors by Site Type

### Amazon

```python
{
    "title": "span[data-a-color='base']",
    "price": ".a-price-whole",
    "rating": ".a-icon-star-small",
    "image": "#landingImage"
}
```

### eBay

```python
{
    "title": ".it-ttl",
    "price": ".vi-VR-cvipPrice",
    "rating": ".ebItemRating",
    "image": "#vi_main"
}
```

### Generic e-commerce

```python
{
    "title": "h1, h2",
    "price": ".price, [data-price], span.price",
    "image": "img[alt*='product'], img.main",
    "url": "a[href*='/product/'], a.product-link"
}
```

---

## Troubleshooting

| Problem | Solution |
|---------|----------|
| Bot detection | Enable stealth mode: `enable_stealth=True` |
| Timeout | Increase timeout: `page_timeout=30000` |
| No results | Check selector with browser dev tools, try alternate selectors |
| Rate limited | Increase delay: `base_delay=(5.0, 10.0)` |
| JavaScript content | Add `wait_for` and `js_code` options |
| Pagination | Loop through pages with page parameter |
| Images not loading | Use `scan_full_page=True` to trigger lazy loading |
| Memory issues | Use `MemoryAdaptiveDispatcher` |

---

## Resources

- [Official Docs](https://docs.crawl4ai.com/)
- [GitHub Repo](https://github.com/unclecode/crawl4ai)
- [Discord Community](https://discord.gg/jP8KfhDhyN)

---

## Installation

```bash
# Install package
pip install crawl4ai

# Setup (downloads browsers)
crawl4ai-setup

# Or with optional features
pip install 'crawl4ai[torch,transformers,opencv]'
```

---

## Schema Template

```python
schema_template = {
    "name": "ProductName",
    "baseSelector": ".container-selector",
    "fields": [
        {
            "name": "field_name",
            "selector": ".field-selector",
            "type": "text",  # text, attribute, html, nested, nested_list, regex
            # "attribute": "href",  # Required for type="attribute"
            # "pattern": r"regex",  # Required for type="regex"
            # "transform": "strip",  # Optional: strip, lowercase, uppercase
        }
    ]
}
```

---

**Last Updated:** February 2026
**Version:** Crawl4AI 0.8.x
