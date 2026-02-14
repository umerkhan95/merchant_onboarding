# Crawl4AI E-commerce Research - Complete Index

This directory contains comprehensive research and practical guides for using Crawl4AI to extract structured e-commerce product data from various platforms.

## Document Overview

### 1. **CRAWL4AI_ECOMMERCE_RESEARCH.md** (Main Reference)
**Comprehensive 50+ page research document covering:**

- **JsonCssExtractionStrategy API** - Complete schema structure, field types, nested objects, and practical examples
- **E-commerce Product Data Extraction** - Key data points, extraction techniques, dynamic content handling
- **Shopify Site Structure** - HTML patterns, CSS selectors, `/products.json` API usage with schema
- **WooCommerce Site Structure** - HTML classes, CSS patterns, REST API endpoints (`/wp-json/wc/v3/products`)
- **Generic E-commerce Patterns** - Schema.org markup, Open Graph tags, common CSS classes
- **CrawlResult Object** - All available fields and how to access extracted data
- **Link Discovery & Crawling** - Automatic link extraction, advanced link head extraction
- **Sitemap Parsing** - XML parsing, handling sitemap indexes, discovering and crawling URLs
- **Rate Limiting & Politeness** - Configuration parameters, robots.txt compliance, practical examples
- **Session Management & Anti-Detection** - Stealth mode, undetected browser, cookie management, progressive escalation
- **Complete Integration Example** - Production-ready e-commerce scraper class

**Best For:** In-depth understanding of each component and comprehensive reference

---

### 2. **CRAWL4AI_CODE_EXAMPLES.py** (Ready-to-Use Code)
**Production-ready Python code with 6 main classes:**

1. **ShopifyExtractor** - Extract from Shopify product pages and `/products.json` API
2. **WooCommerceExtractor** - Scrape and access WooCommerce REST API
3. **GenericEcommerceExtractor** - Flexible extraction with custom selectors
4. **BatchProductCrawler** - Multi-URL crawling with rate limiting
5. **SitemapProductCrawler** - Discover and crawl products from XML sitemaps

**Features:**
- Error handling and logging
- Rate limiting configuration
- Batch processing with result summaries
- Output to JSON files
- Example usage functions for each class

**Best For:** Copy-paste ready code, quick implementation

---

### 3. **CRAWL4AI_QUICK_REFERENCE.md** (Quick Lookup)
**Condensed reference guide with:**

- Quick start code snippet
- Field types cheat sheet (6 types)
- CSS selector patterns by use case
- Platform-specific quick reference (Shopify, WooCommerce, Generic)
- Configuration options summary
- Transform options
- CrawlResult fields reference
- Common patterns (dynamic content, pagination, meta tags, nested objects)
- Error handling examples
- Performance tips
- Troubleshooting table
- Common selectors by site type (Amazon, eBay, Generic)
- Installation instructions

**Best For:** Quick lookups while coding, troubleshooting

---

## Quick Start Guide

### 1. Install Crawl4AI
```bash
pip install crawl4ai
crawl4ai-setup
```

### 2. Basic Extraction
```python
import asyncio
import json
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

async def extract():
    schema = {
        "name": "Products",
        "baseSelector": ".product-card",
        "fields": [
            {"name": "title", "selector": ".title", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text"}
        ]
    }

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url="https://example.com/products",
            config=CrawlerRunConfig(
                extraction_strategy=JsonCssExtractionStrategy(schema)
            )
        )
        print(json.loads(result.extracted_content))

asyncio.run(extract())
```

### 3. Choose Your Path

**For Shopify stores:**
- Use `ShopifyExtractor` class from code examples
- Prefer `/products.json` API over scraping
- See CRAWL4AI_ECOMMERCE_RESEARCH.md Section 3

**For WooCommerce stores:**
- Use `WooCommerceExtractor` class from code examples
- Use `/wp-json/wc/v3/products` REST API when possible
- See CRAWL4AI_ECOMMERCE_RESEARCH.md Section 4

**For other e-commerce sites:**
- Use `GenericEcommerceExtractor` class
- Inspect site with browser dev tools to find selectors
- See CRAWL4AI_ECOMMERCE_RESEARCH.md Section 5

### 4. Scale Your Crawling
- Use `BatchProductCrawler` for multiple URLs
- Configure rate limiting (base_delay, max_delay)
- Use `MemoryAdaptiveDispatcher` for large crawls
- See CRAWL4AI_ECOMMERCE_RESEARCH.md Section 9

---

## Research Methodology

This research was conducted across:

1. **Official Documentation**
   - [docs.crawl4ai.com](https://docs.crawl4ai.com/) - Main documentation
   - [SDK Reference](https://docs.crawl4ai.com/complete-sdk-reference/)
   - [GitHub Repository](https://github.com/unclecode/crawl4ai)

2. **Platform-Specific Docs**
   - [Shopify API Documentation](https://shopify.dev/docs/api/)
   - [WooCommerce Developer Docs](https://developer.woocommerce.com/docs/)
   - [Schema.org Product Type](https://schema.org/Product)

3. **Practical Tutorials & Guides**
   - ScrapingBee Crawl4AI Guide
   - Medium articles on web scraping
   - GitHub example repositories

4. **API Specifications**
   - Shopify `/products.json` endpoint
   - WooCommerce `/wp-json/wc/v3/products` endpoint
   - Open Graph meta tags
   - Schema.org JSON-LD markup

---

## Key Findings Summary

### JsonCssExtractionStrategy Capabilities
✓ CSS selector-based extraction without LLM costs
✓ 6 field types: text, attribute, html, nested, nested_list, regex
✓ Nested objects and arrays support
✓ Transform options: strip, lowercase, uppercase
✓ LLM-assisted schema generation available

### Platform Advantages

**Shopify:**
- ✓ `/products.json` API provides structured data (fastest)
- ✓ Limited to 250 products per request
- ✓ Missing: reviews, meta tags, SEO data
- ✓ HTML fallback for complete data extraction

**WooCommerce:**
- ✓ REST API at `/wp-json/wc/v3/products` (recommended)
- ✓ Supports filtering, pagination, sorting
- ✓ Requires REST API enabled and pretty permalinks
- ✓ HTML scraping as fallback

**Generic E-commerce:**
- ✓ Schema.org markup (JSON-LD) commonly used
- ✓ Open Graph meta tags for social sharing
- ✓ Consistent CSS class naming patterns
- ✓ Pattern-based auto-detection possible

### Anti-Detection & Rate Limiting
✓ Stealth mode via playwright-stealth
✓ Undetected browser for Cloudflare/DataDome
✓ Configurable rate limiting with exponential backoff
✓ robots.txt compliance built-in
✓ Session persistence for multi-step flows
✓ Cookie management support

### Performance Optimizations
✓ API endpoints preferred over HTML scraping
✓ Sitemap-based URL discovery (100-1000+ URLs/sec)
✓ Adaptive memory-based concurrency
✓ Fixed concurrency via semaphore
✓ URL seeding with BM25 relevance scoring
✓ Link head extraction for pre-filtering

---

## File Structure

```
/merchant_onboarding/
├── CRAWL4AI_ECOMMERCE_RESEARCH.md      # Main research (50+ pages)
├── CRAWL4AI_CODE_EXAMPLES.py           # Production code (6 classes)
├── CRAWL4AI_QUICK_REFERENCE.md         # Quick lookup guide
├── CRAWL4AI_RESEARCH_INDEX.md          # This file
└── README.md                            # Project overview (if exists)
```

---

## Common Use Cases

### Use Case 1: Extract Products from Shopify Store
1. Determine if you want product listings or single products
2. For listings: Use `/products.json` API (fastest)
3. For details: Scrape individual product pages with ShopifyExtractor
4. See: Section 3 of CRAWL4AI_ECOMMERCE_RESEARCH.md

### Use Case 2: Bulk Extract from WooCommerce
1. Check if REST API is enabled: `site.com/wp-json/wc/v3/products`
2. Use WooCommerceExtractor.extract_all_products_via_api()
3. No REST API? Fall back to HTML scraping with CSS selectors
4. See: Section 4 of CRAWL4AI_ECOMMERCE_RESEARCH.md

### Use Case 3: Monitor Product Prices
1. Build list of product URLs (from sitemap or discovery)
2. Use BatchProductCrawler with rate limiting
3. Extract price and image fields only
4. Schedule daily with cron job
5. See: SitemapProductCrawler class in CRAWL4AI_CODE_EXAMPLES.py

### Use Case 4: Scrape Unknown E-commerce Site
1. Inspect site with browser dev tools
2. Find product container selector: `.product-card`, `[data-product-id]`, etc.
3. Find selectors for: title, price, image, URL
4. Use GenericEcommerceExtractor with your selectors
5. Test on single URL before scaling to multiple
6. See: Section 5 of CRAWL4AI_ECOMMERCE_RESEARCH.md

### Use Case 5: Large-Scale Multi-Site Crawling
1. Discover product URLs (sitemap, category pages, search)
2. Configure aggressive rate limiting to be respectful
3. Use MemoryAdaptiveDispatcher for adaptive concurrency
4. Enable robots.txt checking
5. Implement error handling and retry logic
6. See: Section 9 of CRAWL4AI_ECOMMERCE_RESEARCH.md

---

## Implementation Checklist

- [ ] Install Crawl4AI: `pip install crawl4ai && crawl4ai-setup`
- [ ] Choose platform (Shopify/WooCommerce/Generic)
- [ ] Identify API endpoints or HTML selectors
- [ ] Review relevant section in CRAWL4AI_ECOMMERCE_RESEARCH.md
- [ ] Copy template from CRAWL4AI_CODE_EXAMPLES.py
- [ ] Test extraction on single URL first
- [ ] Verify extracted data matches expectations
- [ ] Configure rate limiting for politeness
- [ ] Implement error handling
- [ ] Run on sample batch (5-10 URLs)
- [ ] Monitor memory and execution time
- [ ] Scale to full URL list
- [ ] Save results to JSON/database
- [ ] Set up monitoring/alerts

---

## Troubleshooting Quick Links

| Problem | Reference |
|---------|-----------|
| "Bot detected" | CRAWL4AI_ECOMMERCE_RESEARCH.md Section 10 |
| Selectors not working | CRAWL4AI_QUICK_REFERENCE.md Troubleshooting |
| JSON parsing errors | CRAWL4AI_CODE_EXAMPLES.py error_handling |
| Rate limited (429) | CRAWL4AI_ECOMMERCE_RESEARCH.md Section 9 |
| Timeout errors | CRAWL4AI_QUICK_REFERENCE.md Configuration |
| No results extracted | CRAWL4AI_QUICK_REFERENCE.md CSS Patterns |
| Memory issues | CRAWL4AI_ECOMMERCE_RESEARCH.md Multi-URL Crawling |
| JavaScript content | CRAWL4AI_QUICK_REFERENCE.md Dynamic Content |

---

## Advanced Topics

### Schema Generation
Crawl4AI includes LLM-assisted schema generation. Provide HTML samples, get production-ready schemas with stable attribute-based selectors instead of fragile nth-child selectors.

### Link Head Extraction
Fetch metadata from discovered links and score them by:
- **Intrinsic Score** (0-10): URL structure and text quality
- **Contextual Score** (0-1): BM25 relevance to search query
- Combined score for ranking

### URL Seeding
Discover 100-1,000+ URLs per second from:
- Sitemaps (fastest)
- Common Crawl datasets
- Pattern matching with glob patterns
- BM25-based filtering by metadata

### Session Persistence
Maintain authentication state across multiple crawls:
- Cookie management
- Local storage preservation
- JavaScript session state
- Browser profile persistence

---

## Performance Benchmarks

(Indicative - varies by site and network)

| Operation | Speed | Notes |
|-----------|-------|-------|
| Shopify `/products.json` | 50-200 URLs/min | API-based, no rendering |
| WooCommerce REST API | 30-100 URLs/min | Depends on server load |
| HTML scraping | 5-30 URLs/min | Requires browser rendering |
| Sitemap parsing | 100-1000 URLs/sec | Just XML parsing, no fetch |
| Batch crawling (3 concurrent) | 5-20 URLs/min | With 2-4 second delays |

---

## Legal & Ethical Notes

Always:
- ✓ Check `robots.txt` and terms of service
- ✓ Respect `Crawl-Delay` and `Request-Rate` directives
- ✓ Use appropriate delays between requests
- ✓ Identify your crawler with a User-Agent
- ✓ Cache results to avoid redundant requests
- ✓ Don't overwhelm servers
- ✓ Provide value or compensate site owners
- ✓ Use official APIs when available

---

## Additional Resources

### Crawl4AI Ecosystem
- [Official Website](https://crawl4ai.com/)
- [Documentation](https://docs.crawl4ai.com/)
- [GitHub Repository](https://github.com/unclecode/crawl4ai)
- [Discord Community](https://discord.gg/jP8KfhDhyN)
- [PyPI Package](https://pypi.org/project/Crawl4AI/)

### E-commerce Platform APIs
- [Shopify API Reference](https://shopify.dev/docs/api/)
- [WooCommerce REST API Docs](https://developer.woocommerce.com/docs/apis/rest-api/)
- [Shopify Admin GraphQL API](https://shopify.dev/docs/api/admin-graphql)

### Web Scraping Best Practices
- [Schema.org Product Type](https://schema.org/Product)
- [Open Graph Protocol](https://ogp.me/)
- [robots.txt Standard](https://www.robotstxt.org/)
- [HTTP Status Codes](https://developer.mozilla.org/en-US/docs/Web/HTTP/Status)

### Related Tools
- [Playwright Documentation](https://playwright.dev/)
- [BeautifulSoup CSS Selectors](https://www.crummy.com/software/BeautifulSoup/bs4/doc/)
- [CSS Selector Reference](https://www.w3schools.com/cssref/selectors_class.asp)

---

## Document Metadata

- **Created:** February 2026
- **Research Date:** February 2026
- **Crawl4AI Version Covered:** 0.8.x
- **Python Version Required:** 3.8+
- **Total Pages:** 100+ (combined documents)
- **Code Examples:** 30+
- **Production Classes:** 6
- **Platform Coverage:** Shopify, WooCommerce, Generic e-commerce

---

## How to Use This Research

### If you want to...

**Understand Crawl4AI fundamentals:**
→ Start with CRAWL4AI_QUICK_REFERENCE.md, then read CRAWL4AI_ECOMMERCE_RESEARCH.md Section 1-2

**Implement Shopify extraction:**
→ Read CRAWL4AI_ECOMMERCE_RESEARCH.md Section 3, then use ShopifyExtractor from CRAWL4AI_CODE_EXAMPLES.py

**Implement WooCommerce extraction:**
→ Read CRAWL4AI_ECOMMERCE_RESEARCH.md Section 4, then use WooCommerceExtractor from CRAWL4AI_CODE_EXAMPLES.py

**Build custom extractor:**
→ Read CRAWL4AI_ECOMMERCE_RESEARCH.md Section 5-6, use GenericEcommerceExtractor as template

**Scale to production:**
→ Read CRAWL4AI_ECOMMERCE_RESEARCH.md Section 9-10, implement BatchProductCrawler with your schemas

**Troubleshoot issues:**
→ Check CRAWL4AI_QUICK_REFERENCE.md Troubleshooting section

**Find a specific API or selector pattern:**
→ Use Ctrl+F to search CRAWL4AI_QUICK_REFERENCE.md (most comprehensive index)

---

## Support & Contributions

- **Crawl4AI Issues:** [GitHub Issues](https://github.com/unclecode/crawl4ai/issues)
- **Community Help:** [Discord](https://discord.gg/jP8KfhDhyN)
- **Documentation:** [Official Docs](https://docs.crawl4ai.com/)

---

**Last Updated:** February 14, 2026
**Status:** Complete Research
**Version:** 1.0
