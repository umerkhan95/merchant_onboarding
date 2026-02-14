# Crawl4AI Deep Research: E-commerce Product Data Extraction

**Date:** February 14, 2026
**Focus:** Structured extraction strategies, platform-specific patterns, and advanced configuration for e-commerce scraping

---

## Table of Contents

1. [JsonCssExtractionStrategy API](#1-jsoncssextractionstrategy-api)
2. [E-commerce Product Data Extraction](#2-e-commerce-product-data-extraction)
3. [Shopify Site Structure](#3-shopify-site-structure)
4. [WooCommerce Site Structure](#4-woocommerce-site-structure)
5. [Generic E-commerce Patterns](#5-generic-e-commerce-patterns)
6. [CrawlResult Object](#6-crawlresult-object)
7. [Link Discovery and Crawling](#7-link-discovery-and-crawling)
8. [Sitemap Parsing](#8-sitemap-parsing)
9. [Rate Limiting and Politeness](#9-rate-limiting-and-politeness)
10. [Session Management and Anti-Detection](#10-session-management-and-anti-detection)

---

## 1. JsonCssExtractionStrategy API

### Overview

`JsonCssExtractionStrategy` is Crawl4AI's primary LLM-free extraction method using CSS selectors to parse HTML and extract structured JSON data. It's ideal for consistent, repeated page structures and avoids API calls/GPU overhead while preventing hallucination errors.

### Core Schema Structure

```python
schema = {
    "name": "SchemaName",                    # Identifier for the schema
    "baseSelector": "div.product-card",     # CSS selector for container elements
    "fields": [                             # Array of field definitions
        {
            "name": "title",
            "selector": "h2.product-title",
            "type": "text",                 # Options: text, attribute, html, nested, nested_list, regex
            "transform": "strip"            # Optional: lowercase, uppercase, strip
        },
        {
            "name": "link",
            "selector": "a.product-link",
            "type": "attribute",
            "attribute": "href"             # Required for type="attribute"
        }
    ]
}
```

### Field Type System

| Type | Purpose | Example |
|------|---------|---------|
| `text` | Extract element text content | `{"name": "title", "selector": "h2", "type": "text"}` |
| `attribute` | Extract HTML attribute values | `{"name": "url", "selector": "a", "type": "attribute", "attribute": "href"}` |
| `html` | Extract complete HTML block | `{"name": "content", "selector": ".description", "type": "html"}` |
| `nested` | Extract single sub-object | See nested objects section |
| `nested_list` | Extract array of sub-objects | See nested objects section |
| `regex` | Pattern-based extraction | `{"name": "price", "type": "regex", "pattern": r"\$(\d+\.\d{2})"}` |

### Nested Objects

Extract hierarchical data with sub-fields:

```python
{
    "name": "metadata",
    "type": "nested",
    "fields": [
        {"name": "author", "selector": ".author", "type": "text"},
        {"name": "date", "selector": ".date", "type": "text"},
        {
            "name": "image",
            "type": "nested",
            "selector": "img.product-img",
            "fields": [
                {"name": "src", "type": "attribute", "attribute": "src"},
                {"name": "alt", "type": "attribute", "attribute": "alt"}
            ]
        }
    ]
}
```

### Nested Lists

Extract arrays of repeated objects:

```python
{
    "name": "reviews",
    "type": "nested_list",
    "baseSelector": "div.review",
    "fields": [
        {"name": "author", "selector": ".reviewer-name", "type": "text"},
        {"name": "rating", "selector": ".rating", "type": "text"},
        {"name": "text", "selector": ".review-text", "type": "text"}
    ]
}
```

### Transform Options

Applied to extracted text:

```python
{
    "name": "price",
    "selector": ".price",
    "type": "text",
    "transform": "strip"        # Remove whitespace
    # Other options: "lowercase", "uppercase"
}
```

### Complete Product List Example

```python
schema = {
    "name": "Product List",
    "baseSelector": "div.product-item",
    "fields": [
        {"name": "id", "selector": "div", "type": "attribute", "attribute": "data-product-id"},
        {"name": "title", "selector": "h2.product-title", "type": "text"},
        {"name": "price", "selector": "span.price", "type": "text", "transform": "strip"},
        {
            "name": "image",
            "type": "nested",
            "selector": "img.main-image",
            "fields": [
                {"name": "src", "type": "attribute", "attribute": "src"},
                {"name": "alt", "type": "attribute", "attribute": "alt"}
            ]
        },
        {"name": "url", "selector": "a.product-link", "type": "attribute", "attribute": "href"},
        {"name": "in_stock", "selector": ".stock-status", "type": "text"},
        {
            "name": "rating",
            "type": "nested",
            "selector": "div.rating",
            "fields": [
                {"name": "stars", "selector": ".stars", "type": "text"},
                {"name": "count", "selector": ".review-count", "type": "text"}
            ]
        }
    ]
}
```

### Usage in Code

```python
import asyncio
import json
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

async def extract_products():
    schema = {...}  # Your schema definition

    extraction_strategy = JsonCssExtractionStrategy(schema, verbose=True)

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url="https://example.com/products",
            config=CrawlerRunConfig(
                extraction_strategy=extraction_strategy,
                cache_mode="bypass"
            )
        )

        if result.success:
            products = json.loads(result.extracted_content)
            print(json.dumps(products, indent=2))
```

---

## 2. E-commerce Product Data Extraction

### Key Data Points to Extract

| Field | Type | CSS Selector Pattern | Notes |
|-------|------|---------------------|-------|
| Product Title | text | `h1.title`, `h2.product-name`, `[data-productid] .name` | Often in H1/H2 tags |
| Price | text | `span.price`, `.product-price`, `[data-price]` | May need regex to clean |
| Original Price | text | `.original-price`, `.rrp-price`, `.was-price` | For discount calculation |
| Description | html | `.product-description`, `.details`, `[data-description]` | May need HTML type |
| Main Image | attribute | `img.main-image`, `.product-photo img:first`, `picture img` | Get src attribute |
| Gallery Images | nested_list | `.gallery img`, `.thumbnail`, `[data-src]` | Multiple images |
| SKU/Product ID | attribute | `[data-sku]`, `.sku`, `input[name="sku"]` | For inventory tracking |
| Stock Status | text | `.stock-status`, `.availability`, `[data-stock]` | In stock/out of stock |
| Rating | text | `span.rating`, `.stars`, `[data-rating]` | Star count |
| Review Count | text | `.review-count`, `span.reviews`, `[data-reviews]` | Number of reviews |
| Categories | text | `.breadcrumb`, `.category`, `[data-category]` | Hierarchy of categories |
| Variants | nested_list | `select.variant`, `.option`, `.color-selector` | Size, color, etc. |

### Dynamic Content Handling

For pages loading content via JavaScript:

```python
async def extract_with_javascript():
    schema = {...}

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url="https://example.com/product",
            config=CrawlerRunConfig(
                extraction_strategy=JsonCssExtractionStrategy(schema),
                wait_for=".product-price",          # Wait for element to appear
                js_code="""
                    // Scroll to load images
                    window.scrollTo(0, document.body.scrollHeight);
                    // Expand hidden sections
                    document.querySelectorAll('.expand-btn').forEach(btn => btn.click());
                """,
                page_timeout=10000                  # 10 seconds
            )
        )
```

### Handling Pagination

For product listing pages with multiple pages:

```python
async def extract_with_pagination():
    all_products = []

    for page in range(1, 6):  # Pages 1-5
        schema = {
            "name": "Products",
            "baseSelector": ".product-item",
            "fields": [
                {"name": "title", "selector": ".title", "type": "text"},
                {"name": "price", "selector": ".price", "type": "text"},
                # ... other fields
            ]
        }

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(
                url=f"https://example.com/products?page={page}",
                config=CrawlerRunConfig(
                    extraction_strategy=JsonCssExtractionStrategy(schema)
                )
            )

            if result.success:
                page_products = json.loads(result.extracted_content)
                all_products.extend(page_products)

    return all_products
```

---

## 3. Shopify Site Structure

### Shopify Architecture Overview

Shopify stores use a sophisticated theme system built on:
- **Liquid**: Template language for dynamic content
- **JSON Templates**: Section and theme configuration
- **JavaScript**: Client-side interactions
- **REST APIs**: Backend data access

### HTML Structure Pattern

Shopify wraps sections in structured divs:

```html
<div id="my-section-id" class="shopify-section">
    <!-- Section content -->
</div>
```

### Product Page Structure

Key HTML patterns on Shopify product pages:

```html
<!-- Product Container -->
<div class="product-single" data-product-id="123456">

    <!-- Gallery -->
    <div class="product-gallery">
        <img class="product-photo" src="..." alt="...">
    </div>

    <!-- Product Info -->
    <div class="product-info">
        <h1 class="product-title">Product Name</h1>

        <!-- Price -->
        <div class="product-price">
            <span class="price">$99.99</span>
            <span class="original-price">$149.99</span>
        </div>

        <!-- Rating -->
        <div class="rating">
            <span class="stars">4.5</span>
            <span class="review-count">(123)</span>
        </div>

        <!-- Variants -->
        <form class="product-form">
            <select name="id">
                <option value="123" data-sku="SKU123">Color: Red</option>
                <option value="124" data-sku="SKU124">Color: Blue</option>
            </select>
        </form>

        <!-- Description -->
        <div class="product-description">
            Description content
        </div>
    </div>
</div>
```

### CSS Selector Strategy for Shopify

```python
shopify_product_schema = {
    "name": "Shopify Product",
    "baseSelector": "div.product-single",
    "fields": [
        {"name": "product_id", "selector": "div", "type": "attribute", "attribute": "data-product-id"},
        {"name": "title", "selector": "h1.product-title", "type": "text"},
        {"name": "price", "selector": "span.price", "type": "text", "transform": "strip"},
        {"name": "original_price", "selector": "span.original-price", "type": "text", "transform": "strip"},
        {
            "name": "gallery",
            "type": "nested_list",
            "baseSelector": "img.product-photo",
            "fields": [
                {"name": "src", "type": "attribute", "attribute": "src"},
                {"name": "alt", "type": "attribute", "attribute": "alt"}
            ]
        },
        {
            "name": "rating",
            "type": "nested",
            "selector": "div.rating",
            "fields": [
                {"name": "stars", "selector": ".stars", "type": "text"},
                {"name": "count", "selector": ".review-count", "type": "text"}
            ]
        },
        {"name": "description", "selector": "div.product-description", "type": "html"},
        {
            "name": "variants",
            "type": "nested_list",
            "baseSelector": "select[name='id'] option",
            "fields": [
                {"name": "variant_id", "selector": "", "type": "attribute", "attribute": "value"},
                {"name": "sku", "selector": "", "type": "attribute", "attribute": "data-sku"},
                {"name": "label", "selector": "", "type": "text"}
            ]
        }
    ]
}
```

### Accessing Shopify's /products.json Endpoint

Every Shopify store exposes a JSON API endpoint:

```python
async def get_shopify_products_json():
    """Fetch products directly from Shopify's JSON API"""

    async with AsyncWebCrawler() as crawler:
        # Base endpoint - returns first 250 products
        result = await crawler.arun(
            url="https://example-store.myshopify.com/products.json"
        )

        # For pagination, use limit and offset
        result = await crawler.arun(
            url="https://example-store.myshopify.com/products.json?limit=50&offset=0"
        )

        if result.success:
            data = json.loads(result.markdown)
            products = data.get("products", [])
```

### /products.json Response Structure

```json
{
  "products": [
    {
      "id": 123456,
      "handle": "product-slug",
      "title": "Product Name",
      "body_html": "<p>Description</p>",
      "vendor": "Brand Name",
      "product_type": "Category",
      "created_at": "2024-01-01T00:00:00Z",
      "published_at": "2024-01-01T00:00:00Z",
      "updated_at": "2024-01-01T00:00:00Z",
      "tags": ["tag1", "tag2"],
      "status": "active",
      "published_scope": "web",
      "template_suffix": null,
      "images": [
        {
          "id": 789,
          "product_id": 123456,
          "position": 1,
          "created_at": "2024-01-01T00:00:00Z",
          "updated_at": "2024-01-01T00:00:00Z",
          "alt": "Product image",
          "width": 1000,
          "height": 1000,
          "src": "https://cdn.shopify.com/...",
          "variant_ids": []
        }
      ],
      "options": [
        {"name": "Color", "id": 1, "values": ["Red", "Blue"]},
        {"name": "Size", "id": 2, "values": ["S", "M", "L"]}
      ],
      "variants": [
        {
          "id": 456789,
          "product_id": 123456,
          "title": "Red / S",
          "price": "99.99",
          "sku": "SKU123",
          "position": 1,
          "inventory_policy": "deny",
          "compare_at_price": "149.99",
          "option1": "Red",
          "option2": "S",
          "created_at": "2024-01-01T00:00:00Z",
          "updated_at": "2024-01-01T00:00:00Z"
        }
      ]
    }
  ]
}
```

### Note on /products.json Limitations

- Does NOT include meta tags or SEO data
- Does NOT include reviews or ratings
- Limited to 250 products per request
- No detailed customer data

For complete metadata and SEO data, you must crawl individual product pages.

---

## 4. WooCommerce Site Structure

### HTML Structure Pattern

WooCommerce uses standardized template files and classes:

```html
<!-- Product Container -->
<article class="post type-product" id="product-123">

    <!-- Product Images -->
    <div class="product-images">
        <figure class="woocommerce-product-gallery">
            <img class="wp-post-image" src="..." alt="...">
        </figure>
    </div>

    <!-- Product Summary -->
    <div class="summary entry-summary">
        <h1 class="product_title entry-title">Product Name</h1>

        <!-- Price -->
        <div class="price">
            <span class="woocommerce-Price-amount">$99.99</span>
            <del aria-hidden="true">$149.99</del>
        </div>

        <!-- Rating -->
        <div class="woocommerce-product-rating">
            <div class="star-rating">★★★★☆</div>
            <span class="woocommerce-review-link">(123 ratings)</span>
        </div>

        <!-- Description -->
        <div class="woocommerce-product-details__short-description">
            Description content
        </div>

        <!-- Variants -->
        <table class="variations">
            <tr>
                <td class="label">
                    <label for="size">Size</label>
                </td>
                <td class="value">
                    <select id="size" name="attribute_size">
                        <option>S</option>
                        <option>M</option>
                    </select>
                </td>
            </tr>
        </table>

        <!-- Add to Cart -->
        <form class="cart" action="..." method="post">
            <button type="submit" class="button single_add_to_cart_button">
                Add to cart
            </button>
        </form>
    </div>
</article>
```

### Common WooCommerce CSS Classes

| Element | Class | Selector |
|---------|-------|----------|
| Product container | `post type-product` | `article.type-product` |
| Product title | `product_title` | `.product_title` |
| Price container | `price` | `.woocommerce div.product .price` |
| Current price | `woocommerce-Price-amount` | `.woocommerce-Price-amount` |
| Original price (strikethrough) | `(del)` | `.woocommerce del` |
| Rating | `star-rating` | `.woocommerce-product-rating .star-rating` |
| Review count | `woocommerce-review-link` | `.woocommerce-review-link` |
| Short description | `woocommerce-product-details__short-description` | `.woocommerce-product-details__short-description` |
| Gallery | `woocommerce-product-gallery` | `.woocommerce-product-gallery` |
| Variants | `variations` | `table.variations` |
| Add to cart button | `single_add_to_cart_button` | `.single_add_to_cart_button` |

### CSS Selector Strategy for WooCommerce

```python
woocommerce_product_schema = {
    "name": "WooCommerce Product",
    "baseSelector": "article.type-product",
    "fields": [
        {
            "name": "product_id",
            "selector": "",
            "type": "attribute",
            "attribute": "id",
            "pattern": r"product-(\d+)"  # Extract ID from "product-123"
        },
        {"name": "title", "selector": "h1.product_title", "type": "text"},
        {"name": "price", "selector": ".woocommerce-Price-amount", "type": "text", "transform": "strip"},
        {"name": "original_price", "selector": "del", "type": "text", "transform": "strip"},
        {
            "name": "rating",
            "type": "nested",
            "selector": ".woocommerce-product-rating",
            "fields": [
                {"name": "stars", "selector": ".star-rating", "type": "text"},
                {"name": "count", "selector": ".woocommerce-review-link", "type": "text"}
            ]
        },
        {"name": "description", "selector": ".woocommerce-product-details__short-description", "type": "html"},
        {
            "name": "gallery",
            "type": "nested_list",
            "baseSelector": ".woocommerce-product-gallery img",
            "fields": [
                {"name": "src", "type": "attribute", "attribute": "src"},
                {"name": "alt", "type": "attribute", "attribute": "alt"}
            ]
        },
        {
            "name": "variants",
            "type": "nested_list",
            "baseSelector": "table.variations tr",
            "fields": [
                {"name": "attribute", "selector": "label", "type": "text"},
                {"name": "value", "selector": "select option:selected", "type": "text"}
            ]
        },
        {"name": "sku", "selector": ".sku", "type": "text"},
        {"name": "stock_status", "selector": ".stock", "type": "text"}
    ]
}
```

### WooCommerce REST API Endpoint

Access product data directly via `/wp-json/wc/v3/products`:

```python
async def get_woocommerce_products():
    """Fetch products from WooCommerce REST API"""

    async with AsyncWebCrawler() as crawler:
        # List products
        result = await crawler.arun(
            url="https://example.com/wp-json/wc/v3/products"
        )

        # With pagination
        result = await crawler.arun(
            url="https://example.com/wp-json/wc/v3/products?page=1&per_page=100"
        )

        # With filters
        result = await crawler.arun(
            url="https://example.com/wp-json/wc/v3/products?search=keyword&orderby=popularity"
        )
```

### REST API Requirements

- **URL Format**: `https://example.com/wp-json/wc/v3/products`
- **WooCommerce Version**: 2.6+
- **WordPress Version**: 4.4+
- **Permalinks**: Must enable pretty permalinks in Settings
- **Authentication**: Optional for public stores, Basic Auth for protected content

### Query Parameters

| Parameter | Values | Example |
|-----------|--------|---------|
| `page` | Integer | `?page=1` |
| `per_page` | 1-100 | `?per_page=50` |
| `search` | String | `?search=laptop` |
| `orderby` | date, title, popularity, rating, id | `?orderby=popularity` |
| `order` | asc, desc | `?order=desc` |
| `status` | publish, draft, pending, private, trash | `?status=publish` |
| `category` | Category ID | `?category=15` |
| `tag` | Tag ID | `?tag=22` |
| `on_sale` | true, false | `?on_sale=true` |
| `min_price` | Float | `?min_price=10` |
| `max_price` | Float | `?max_price=100` |

---

## 5. Generic E-commerce Patterns

### Schema.org Product Markup

Most e-commerce sites use structured data (JSON-LD):

```html
<script type="application/ld+json">
{
  "@context": "https://schema.org/",
  "@type": "Product",
  "name": "Executive Anvil",
  "image": "https://example.com/photos/1x1/photo.jpg",
  "description": "Sleek and powerful",
  "brand": {
    "@type": "Brand",
    "name": "ACME"
  },
  "aggregateRating": {
    "@type": "AggregateRating",
    "ratingValue": "4.4",
    "ratingCount": "89",
    "bestRating": "5",
    "worstRating": "1"
  },
  "offers": {
    "@type": "Offer",
    "url": "https://example.com/anvil",
    "priceCurrency": "USD",
    "price": "119.99",
    "priceValidUntil": "2025-12-31",
    "availability": "InStock",
    "seller": {
      "@type": "Organization",
      "name": "ACME Store"
    }
  }
}
</script>
```

### Extracting Schema.org Data

```python
import json
from crawl4ai import AsyncWebCrawler

async def extract_schema_markup():
    """Extract schema.org data from page"""

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url="https://example.com/product",
            js_code="""
            return JSON.parse(
                document.querySelector('script[type="application/ld+json"]').textContent
            );
            """
        )
```

### Open Graph Tags

Meta tags for social sharing:

```html
<head>
    <meta property="og:title" content="Product Name">
    <meta property="og:description" content="Product description">
    <meta property="og:image" content="https://example.com/image.jpg">
    <meta property="og:price:amount" content="99.99">
    <meta property="og:price:currency" content="USD">
    <meta property="og:product:availability" content="in stock">
</head>
```

### Extracting Open Graph Tags

```python
schema = {
    "name": "Page Metadata",
    "baseSelector": "head",
    "fields": [
        {
            "name": "og_title",
            "selector": 'meta[property="og:title"]',
            "type": "attribute",
            "attribute": "content"
        },
        {
            "name": "og_description",
            "selector": 'meta[property="og:description"]',
            "type": "attribute",
            "attribute": "content"
        },
        {
            "name": "og_image",
            "selector": 'meta[property="og:image"]',
            "type": "attribute",
            "attribute": "content"
        },
        {
            "name": "price",
            "selector": 'meta[property="og:price:amount"]',
            "type": "attribute",
            "attribute": "content"
        },
        {
            "name": "currency",
            "selector": 'meta[property="og:price:currency"]',
            "type": "attribute",
            "attribute": "content"
        }
    ]
}
```

### Common E-commerce Pattern Classes

Modern e-commerce sites use predictable naming:

| Platform/Framework | Container | Title | Price | Image |
|------------------|-----------|-------|-------|-------|
| Generic | `.product`, `.item` | `.title`, `.name` | `.price` | `img[alt*="product"]` |
| Bootstrap | `.card`, `.product-card` | `.card-title` | `.card-text .price` | `.card-img-top` |
| Tailwind | `[class*="product"]` | `[class*="title"]` | `[class*="price"]` | `[alt*="product"]` |
| React | `data-product-id`, `data-testid` | Similar patterns | Similar patterns | Similar patterns |

### Pattern Detection Strategy

```python
# Try multiple selectors in order of likelihood
selectors_by_priority = {
    "title": [
        "h1", "h2.title", ".product-title", "[data-product-title]",
        ".product-name", "span[itemprop='name']"
    ],
    "price": [
        ".price", "[data-price]", ".product-price",
        "span[itemprop='price']", ".sale-price"
    ],
    "image": [
        "img.product-image", "img[alt*='product']",
        ".product-image img", "picture img"
    ]
}

def build_flexible_schema(container_selector):
    """Build schema that tries multiple selectors"""
    return {
        "name": "Flexible Product",
        "baseSelector": container_selector,
        "fields": [
            {
                "name": "title",
                "selector": "h1, h2.title, .product-title, [data-product-title]",
                "type": "text"
            },
            {
                "name": "price",
                "selector": ".price, [data-price], span[itemprop='price']",
                "type": "text"
            }
        ]
    }
```

---

## 6. CrawlResult Object

### Overview

The `CrawlResult` object contains comprehensive crawl output organized into multiple categories:

### Basic Information Fields

```python
result.url                  # Final crawled URL (after redirects)
result.success              # Boolean indicating successful completion
result.status_code          # HTTP response code (200, 404, etc.)
result.error_message        # Failure description if applicable
result.session_id           # Browser context identifier for session reuse
```

### Content Fields

```python
result.html                 # Original unmodified HTML
result.cleaned_html         # Sanitized version with scripts/styles removed
result.markdown             # Markdown conversion with citations
result.extracted_content    # Structured output from extraction strategies (JSON string)
```

### Accessing Extracted Data

```python
import json
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

async def process_extraction():
    schema = {...}

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url="https://example.com/product",
            config=CrawlerRunConfig(
                extraction_strategy=JsonCssExtractionStrategy(schema)
            )
        )

        # Access extracted JSON
        if result.success and result.extracted_content:
            data = json.loads(result.extracted_content)
            print(f"Extracted {len(data)} products")

            # Access specific fields
            for product in data:
                print(f"Title: {product.get('title')}")
                print(f"Price: {product.get('price')}")
```

### Media & Navigation Fields

```python
result.media                # Dictionary with images, videos, audio
result.links                # Links organized by internal/external
```

### Accessing Links and Media

```python
# Access internal and external links
internal_links = result.links.get("internal", [])
external_links = result.links.get("external", [])

for link in internal_links:
    print(f"URL: {link['href']}")
    print(f"Text: {link['text']}")
    print(f"Title: {link.get('title')}")

# Access media
images = result.media.get("images", [])
for image in images:
    print(f"Source: {image['src']}")
    print(f"Alt: {image.get('alt')}")
    print(f"Relevance: {image.get('relevance_score')}")
```

### Additional Capture Options

```python
result.screenshot           # Base64-encoded page image
result.pdf                  # Raw PDF bytes
result.mhtml                # Complete page snapshot in MIME HTML format
result.downloaded_files     # List of locally saved file paths
result.metadata             # Page-level info (title, description, OG data)
```

### Accessing Metadata

```python
# Page metadata automatically extracted
metadata = result.metadata

if metadata:
    print(f"Title: {metadata.get('title')}")
    print(f"Description: {metadata.get('description')}")
    print(f"OG Image: {metadata.get('og_image')}")
    print(f"Favicon: {metadata.get('favicon')}")
```

### Advanced Monitoring Fields

```python
result.network_requests     # Captured HTTP traffic
result.console_messages     # Browser console output
result.dispatch_result      # Concurrency metrics
```

### Complete CrawlResult Usage Example

```python
import json
from crawl4ai import AsyncWebCrawler, CrawlerRunConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy

async def comprehensive_crawl():
    schema = {
        "name": "Product",
        "baseSelector": ".product",
        "fields": [
            {"name": "title", "selector": ".title", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text"}
        ]
    }

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url="https://example.com/products",
            config=CrawlerRunConfig(
                extraction_strategy=JsonCssExtractionStrategy(schema),
                screenshot=True,
                cache_mode="bypass"
            )
        )

        # Check success
        if not result.success:
            print(f"Error: {result.error_message}")
            return

        # Extract structured data
        products = json.loads(result.extracted_content)
        print(f"Found {len(products)} products")

        # Get metadata
        print(f"Page title: {result.metadata.get('title')}")

        # Get links for next pages
        links = result.links.get("internal", [])
        next_page_links = [l for l in links if "page=" in l.get("href", "")]

        # Get images from gallery
        images = result.media.get("images", [])
        print(f"Found {len(images)} images")

        # Access raw HTML if needed
        if "specific-pattern" in result.html:
            print("Found specific HTML pattern")
```

---

## 7. Link Discovery and Crawling

### Automatic Link Extraction

Crawl4AI automatically discovers and categorizes links:

```python
from crawl4ai import AsyncWebCrawler

async def discover_links():
    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(url="https://example.com")

        # Access discovered links
        internal = result.links.get("internal", [])
        external = result.links.get("external", [])

        print(f"Internal links: {len(internal)}")
        print(f"External links: {len(external)}")

        for link in internal:
            print(f"  {link['text']} -> {link['href']}")
```

### Link Head Extraction (Advanced)

Fetch metadata from linked pages and score them:

```python
from crawl4ai import AsyncWebCrawler, LinkPreviewConfig

async def extract_with_link_preview():
    from crawl4ai import CrawlerRunConfig

    config = CrawlerRunConfig(
        link_preview_config=LinkPreviewConfig(
            max_links=50,                    # Maximum links to process
            max_concurrency=5,               # Parallel requests
            score_threshold=0.5,             # Minimum relevance score
            search_query="product"           # For contextual scoring
        )
    )

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url="https://example.com/category",
            config=config
        )

        # Links include relevance scores
        for link in result.links.get("internal", []):
            print(f"URL: {link['href']}")
            print(f"Score: {link.get('score', 0)}")
            print(f"Text: {link['text']}")
```

### Product URL Discovery from Category Pages

```python
async def discover_product_urls():
    """Find all product URLs from category page"""

    schema = {
        "name": "ProductLinks",
        "baseSelector": "a.product-link, a[href*='/product/']",
        "fields": [
            {"name": "url", "selector": "", "type": "attribute", "attribute": "href"},
            {"name": "title", "selector": "", "type": "text"}
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
            links = json.loads(result.extracted_content)
            product_urls = [
                link.get("url") for link in links
                if link.get("url") and link.get("url").startswith("/")
            ]
            return product_urls
```

### Recursive Crawling for Product Lists

```python
from collections import deque

async def crawl_all_products(start_url, max_depth=3):
    """Crawl category and product pages recursively"""

    visited = set()
    to_visit = deque([(start_url, 0)])  # (url, depth)
    all_products = []

    schema = {
        "name": "Product",
        "baseSelector": ".product-item",
        "fields": [
            {"name": "title", "selector": ".title", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text"},
            {"name": "url", "selector": "a", "type": "attribute", "attribute": "href"}
        ]
    }

    async with AsyncWebCrawler() as crawler:
        while to_visit:
            url, depth = to_visit.popleft()

            if url in visited or depth > max_depth:
                continue

            visited.add(url)
            print(f"Crawling: {url} (depth: {depth})")

            result = await crawler.arun(
                url=url,
                config=CrawlerRunConfig(
                    extraction_strategy=JsonCssExtractionStrategy(schema)
                )
            )

            if result.success:
                data = json.loads(result.extracted_content)
                all_products.extend(data)

                # Find next page links
                for link in result.links.get("internal", []):
                    href = link.get("href", "")
                    if "page=" in href and href not in visited:
                        to_visit.append((href, depth + 1))

    return all_products
```

---

## 8. Sitemap Parsing

### URL Seeding with Sitemaps

Discover URLs from `sitemap.xml` before crawling:

```python
from crawl4ai import AsyncUrlSeeder

async def discover_from_sitemap():
    """Discover URLs from sitemap"""

    seeder = AsyncUrlSeeder(
        source="sitemap+cc",  # sitemap + Common Crawl
        domain="example.com"
    )

    # Get discovered URLs
    urls = await seeder.fetch_urls(
        limit=1000,                         # Max URLs
        pattern="*/products/*",              # URL pattern
        metadata=True                       # Extract metadata
    )

    print(f"Discovered {len(urls)} URLs")
    for url_data in urls:
        print(f"URL: {url_data['url']}")
        print(f"Title: {url_data.get('title')}")
        print(f"Relevance: {url_data.get('relevance_score')}")
```

### Direct Sitemap Parsing

```python
import xml.etree.ElementTree as ET
from crawl4ai import AsyncWebCrawler

async def parse_sitemap():
    """Parse XML sitemap directly"""

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url="https://example.com/sitemap.xml"
        )

        if result.success:
            # Parse XML
            root = ET.fromstring(result.html)

            # Define namespace
            namespace = {
                'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'
            }

            # Extract URLs
            urls = []
            for url_element in root.findall('.//sm:loc', namespace):
                url = url_element.text
                if url:
                    urls.append(url)

            print(f"Found {len(urls)} URLs in sitemap")
            return urls
```

### Handling Sitemap Indexes

For large sites with multiple sitemaps:

```python
async def parse_sitemap_index():
    """Parse sitemap index and all sub-sitemaps"""

    all_urls = []

    async with AsyncWebCrawler() as crawler:
        # Fetch main sitemap index
        index_result = await crawler.arun(
            url="https://example.com/sitemap_index.xml"
        )

        if index_result.success:
            root = ET.fromstring(index_result.html)
            namespace = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

            # Get all sitemap URLs
            sitemap_urls = [
                elem.text
                for elem in root.findall('.//sm:loc', namespace)
            ]

            # Process each sitemap
            for sitemap_url in sitemap_urls:
                sitemap_result = await crawler.arun(url=sitemap_url)

                if sitemap_result.success:
                    root = ET.fromstring(sitemap_result.html)
                    urls = [
                        elem.text
                        for elem in root.findall('.//sm:loc', namespace)
                    ]
                    all_urls.extend(urls)
                    print(f"Processed {sitemap_url}: {len(urls)} URLs")

    return all_urls
```

### Crawling URLs from Sitemap

```python
async def crawl_sitemap_urls():
    """Discover URLs and crawl them"""

    # Parse sitemap
    urls = await parse_sitemap()

    # Filter for product pages
    product_urls = [
        url for url in urls
        if "/product/" in url or "/products/" in url
    ]

    print(f"Found {len(product_urls)} product URLs")

    # Crawl each product
    all_products = []

    schema = {
        "name": "Product",
        "baseSelector": ".product-single",
        "fields": [
            {"name": "title", "selector": ".title", "type": "text"},
            {"name": "price", "selector": ".price", "type": "text"}
        ]
    }

    async with AsyncWebCrawler() as crawler:
        for url in product_urls[:100]:  # Limit to first 100
            result = await crawler.arun(
                url=url,
                config=CrawlerRunConfig(
                    extraction_strategy=JsonCssExtractionStrategy(schema)
                )
            )

            if result.success:
                product = json.loads(result.extracted_content)
                all_products.extend(product)

    return all_products
```

---

## 9. Rate Limiting and Politeness

### Configuration Overview

Crawl4AI provides multiple mechanisms for polite, rate-limited crawling:

### Rate Limiter Configuration

```python
from crawl4ai import RateLimiter, SemaphoreDispatcher

rate_limiter = RateLimiter(
    base_delay=(2.0, 5.0),              # Random delay between 2-5 seconds
    max_delay=60.0,                     # Maximum delay for backoff
    max_retries=3,                      # Retry 3 times on rate limit
    rate_limit_codes=[429, 503, 504]    # HTTP codes triggering backoff
)
```

### Rate Limiter Parameters Explained

| Parameter | Type | Default | Purpose |
|-----------|------|---------|---------|
| `base_delay` | Tuple[float, float] | (1.0, 3.0) | Random delay in seconds between requests |
| `max_delay` | float | 60.0 | Maximum backoff delay when rate-limited |
| `max_retries` | int | 3 | Number of retries on rate-limit responses |
| `rate_limit_codes` | List[int] | [429, 503] | HTTP codes triggering rate-limit logic |

### Dispatcher Configuration

```python
from crawl4ai import SemaphoreDispatcher, MemoryAdaptiveDispatcher, BrowserConfig, CrawlerRunConfig

# Option 1: Fixed Concurrency
dispatcher = SemaphoreDispatcher(
    semaphore_count=5,                  # Maximum 5 parallel requests
    rate_limiter=rate_limiter
)

# Option 2: Adaptive Concurrency (Recommended for large crawls)
dispatcher = MemoryAdaptiveDispatcher(
    memory_threshold_percent=80,        # Pause at 80% memory usage
    max_semaphore_count=10,             # Maximum concurrent tasks
    rate_limiter=rate_limiter
)
```

### Multi-URL Crawling with Rate Limiting

```python
async def crawl_multiple_urls_politely():
    """Crawl multiple URLs with rate limiting"""

    urls = [
        "https://example.com/product/1",
        "https://example.com/product/2",
        # ... more URLs
    ]

    rate_limiter = RateLimiter(
        base_delay=(3.0, 7.0),           # 3-7 seconds between requests
        max_delay=30.0
    )

    dispatcher = SemaphoreDispatcher(
        semaphore_count=3,               # Max 3 concurrent requests
        rate_limiter=rate_limiter
    )

    schema = {...}

    async with AsyncWebCrawler() as crawler:
        results = await crawler.arun_many(
            urls=urls,
            config=CrawlerRunConfig(
                extraction_strategy=JsonCssExtractionStrategy(schema),
                cache_mode="bypass"
            ),
            dispatcher=dispatcher
        )

        for result in results:
            if result.success:
                print(f"Crawled: {result.url}")
```

### robots.txt Compliance

```python
from crawl4ai import BrowserConfig, CrawlerRunConfig

config = CrawlerRunConfig(
    check_robots_txt=True,              # Respect robots.txt
    cache_mode="bypass"
)

browser_config = BrowserConfig(
    headless=True
)

async with AsyncWebCrawler(config=browser_config) as crawler:
    result = await crawler.arun(
        url="https://example.com/products",
        config=config
    )
```

### Practical Rate Limiting Example

```python
async def crawl_with_politeness():
    """Best practices for polite, rate-limited crawling"""

    rate_limiter = RateLimiter(
        base_delay=(2.0, 4.0),           # 2-4 second random delay
        max_delay=20.0,                  # Max 20 second backoff
        max_retries=2,                   # Retry twice
        rate_limit_codes=[429, 503]      # Standard rate limit codes
    )

    dispatcher = SemaphoreDispatcher(
        semaphore_count=2,               # Conservative: 2 concurrent requests
        rate_limiter=rate_limiter
    )

    browser_config = BrowserConfig(
        user_agent_mode="random"         # Randomize user agent
    )

    config = CrawlerRunConfig(
        check_robots_txt=True,           # Respect robots.txt
        cache_mode="bypass",
        page_timeout=15000               # 15 second timeout
    )

    urls = ["https://example.com/product/1", "https://example.com/product/2"]

    async with AsyncWebCrawler(config=browser_config) as crawler:
        results = await crawler.arun_many(
            urls=urls,
            config=config,
            dispatcher=dispatcher
        )

        for result in results:
            if result.success:
                print(f"Successfully crawled: {result.url}")
            else:
                print(f"Failed: {result.url} - {result.error_message}")
```

---

## 10. Session Management and Anti-Detection

### Stealth Mode Configuration

Crawl4AI uses Playwright's stealth plugin to avoid bot detection:

```python
from crawl4ai import BrowserConfig, AsyncWebCrawler

browser_config = BrowserConfig(
    enable_stealth=True,                # Enable stealth mode
    headless=False,                     # Avoid headless detection
    user_agent_mode="random"            # Randomize user agent
)

async with AsyncWebCrawler(config=browser_config) as crawler:
    result = await crawler.arun(
        url="https://protected-site.com"
    )
```

### Undetected Browser for Advanced Sites

For sophisticated bot detection (Cloudflare, DataDome):

```python
from crawl4ai import UndetectedAdapter, AsyncPlaywrightCrawlerStrategy

# Use undetected adapter
adapter = UndetectedAdapter()

strategy = AsyncPlaywrightCrawlerStrategy(
    browser_config=browser_config,
    browser_adapter=adapter
)
```

### Session Persistence

Create persistent browser sessions:

```python
from crawl4ai import BrowserConfig, CrawlerRunConfig

browser_config = BrowserConfig(
    headless=False
)

config = CrawlerRunConfig(
    # Session data persists between crawls
    cache_mode="bypass"
)

# First crawl - login
async with AsyncWebCrawler(config=browser_config) as crawler:
    result = await crawler.arun(
        url="https://example.com/login",
        config=config,
        js_code="""
        // Auto-login script
        document.querySelector('#email').value = 'user@example.com';
        document.querySelector('#password').value = 'password';
        document.querySelector('#login-btn').click();
        """
    )
```

### Cookie Management

```python
from crawl4ai import BrowserConfig, CrawlerRunConfig

browser_config = BrowserConfig(
    cookies=[
        {
            "name": "session_id",
            "value": "abc123",
            "domain": "example.com",
            "path": "/"
        },
        {
            "name": "user_token",
            "value": "xyz789",
            "domain": "example.com",
            "path": "/"
        }
    ]
)

async with AsyncWebCrawler(config=browser_config) as crawler:
    result = await crawler.arun(
        url="https://example.com/protected"
    )
```

### Anti-Detection Best Practices

```python
from crawl4ai import BrowserConfig, CrawlerRunConfig

# Best practices for avoiding detection
browser_config = BrowserConfig(
    enable_stealth=True,                # Enable stealth mode
    headless=False,                     # Never use headless
    user_agent_mode="random",           # Random user agent
    viewport_width=1920,                # Realistic viewport
    viewport_height=1080,
    accept_insecure_certs=True
)

config = CrawlerRunConfig(
    wait_for=".main-content",           # Wait for content
    page_timeout=20000,                 # Longer timeout
    delay=2000                          # Add delay before extraction
)

async with AsyncWebCrawler(config=browser_config) as crawler:
    result = await crawler.arun(
        url="https://anti-bot-site.com",
        config=config
    )
```

### Handling JavaScript Challenges

```python
async def handle_javascript_site():
    """Handle sites requiring JavaScript execution"""

    config = CrawlerRunConfig(
        js_code="""
        // Wait for dynamic content
        async function waitForElement(selector, timeout = 5000) {
            const start = Date.now();
            while (!document.querySelector(selector)) {
                if (Date.now() - start > timeout) throw new Error('Timeout');
                await new Promise(r => setTimeout(r, 100));
            }
        }

        await waitForElement('.product-price');
        """,
        wait_for=".product-price",
        page_timeout=30000
    )

    async with AsyncWebCrawler() as crawler:
        result = await crawler.arun(
            url="https://js-heavy-site.com",
            config=config
        )
```

### Progressive Escalation Strategy

```python
async def handle_protected_site():
    """Progressive approach to bypassing protection"""

    # Step 1: Try basic crawling
    try:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun("https://protected.com")
            if result.success:
                return result
    except:
        pass

    # Step 2: Add stealth mode
    try:
        browser_config = BrowserConfig(enable_stealth=True)
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await crawler.arun("https://protected.com")
            if result.success:
                return result
    except:
        pass

    # Step 3: Add undetected browser
    try:
        adapter = UndetectedAdapter()
        browser_config = BrowserConfig(enable_stealth=True, headless=False)
        # ... use adapter with strategy
    except:
        pass

    # Step 4: Give up or use proxy/VPN
    raise Exception("Site cannot be crawled")
```

---

## Integration Example: Complete E-commerce Scraper

Here's a complete, production-ready example:

```python
import asyncio
import json
from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
from crawl4ai.extraction_strategy import JsonCssExtractionStrategy
from crawl4ai import RateLimiter, SemaphoreDispatcher

class EcommerceScraper:
    def __init__(self, base_url: str, site_type: str = "generic"):
        self.base_url = base_url
        self.site_type = site_type
        self.rate_limiter = RateLimiter(
            base_delay=(2.0, 4.0),
            max_delay=30.0,
            max_retries=2
        )
        self.dispatcher = SemaphoreDispatcher(
            semaphore_count=3,
            rate_limiter=self.rate_limiter
        )

    def get_product_schema(self):
        """Get appropriate schema for site type"""

        schemas = {
            "shopify": {
                "name": "Shopify Product",
                "baseSelector": "div.product-single",
                "fields": [
                    {"name": "product_id", "selector": "div", "type": "attribute", "attribute": "data-product-id"},
                    {"name": "title", "selector": "h1.product-title", "type": "text"},
                    {"name": "price", "selector": "span.price", "type": "text", "transform": "strip"},
                    {"name": "url", "selector": "a.product-link", "type": "attribute", "attribute": "href"}
                ]
            },
            "woocommerce": {
                "name": "WooCommerce Product",
                "baseSelector": "article.type-product",
                "fields": [
                    {"name": "title", "selector": "h1.product_title", "type": "text"},
                    {"name": "price", "selector": ".woocommerce-Price-amount", "type": "text"},
                    {"name": "url", "selector": "a.product-link", "type": "attribute", "attribute": "href"}
                ]
            },
            "generic": {
                "name": "Generic Product",
                "baseSelector": ".product-item, .product-card",
                "fields": [
                    {"name": "title", "selector": ".title, h2, h3", "type": "text"},
                    {"name": "price", "selector": ".price, [data-price]", "type": "text"},
                    {"name": "url", "selector": "a", "type": "attribute", "attribute": "href"}
                ]
            }
        }

        return schemas.get(self.site_type, schemas["generic"])

    async def crawl_products(self, urls: list):
        """Crawl multiple product URLs"""

        schema = self.get_product_schema()
        browser_config = BrowserConfig(
            enable_stealth=True,
            user_agent_mode="random"
        )

        config = CrawlerRunConfig(
            extraction_strategy=JsonCssExtractionStrategy(schema),
            check_robots_txt=True,
            cache_mode="bypass"
        )

        all_products = []

        async with AsyncWebCrawler(config=browser_config) as crawler:
            results = await crawler.arun_many(
                urls=urls,
                config=config,
                dispatcher=self.dispatcher
            )

            for result in results:
                if result.success and result.extracted_content:
                    try:
                        products = json.loads(result.extracted_content)
                        all_products.extend(products)
                        print(f"✓ {result.url}: {len(products)} products")
                    except json.JSONDecodeError:
                        print(f"✗ {result.url}: JSON decode error")
                else:
                    print(f"✗ {result.url}: {result.error_message}")

        return all_products

    async def scrape_full_catalog(self, start_url: str):
        """Scrape entire product catalog"""

        # 1. Get URLs from sitemap
        urls = await self._get_urls_from_sitemap(f"{self.base_url}/sitemap.xml")

        # 2. Filter product URLs
        product_urls = [
            url for url in urls
            if "/product/" in url or "/products/" in url
        ]

        print(f"Found {len(product_urls)} product URLs")

        # 3. Crawl all products
        products = await self.crawl_products(product_urls[:500])  # Limit for demo

        # 4. Save results
        with open("products.json", "w") as f:
            json.dump(products, f, indent=2)

        print(f"Saved {len(products)} products")

        return products

    async def _get_urls_from_sitemap(self, sitemap_url: str):
        """Extract URLs from sitemap.xml"""

        import xml.etree.ElementTree as ET

        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=sitemap_url)

            if result.success:
                root = ET.fromstring(result.html)
                namespace = {'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

                urls = [
                    elem.text
                    for elem in root.findall('.//sm:loc', namespace)
                ]

                return urls

        return []

# Usage
async def main():
    scraper = EcommerceScraper(
        base_url="https://example-store.com",
        site_type="shopify"
    )

    product_urls = [
        "https://example-store.com/products/item-1",
        "https://example-store.com/products/item-2"
    ]

    products = await scraper.crawl_products(product_urls)

    print(f"Scraped {len(products)} products")
    print(json.dumps(products[:2], indent=2))

if __name__ == "__main__":
    asyncio.run(main())
```

---

## References

### Official Documentation

- [Crawl4AI Official Docs](https://docs.crawl4ai.com/)
- [LLM-Free Strategies](https://docs.crawl4ai.com/extraction/no-llm-strategies/)
- [Complete SDK Reference](https://docs.crawl4ai.com/complete-sdk-reference/)
- [Browser, Crawler & LLM Config](https://docs.crawl4ai.com/core/browser-crawler-config/)
- [Multi-URL Crawling](https://docs.crawl4ai.com/advanced/multi-url-crawling/)
- [Undetected Browser](https://docs.crawl4ai.com/advanced/undetected-browser/)
- [URL Seeding](https://docs.crawl4ai.com/core/url-seeding/)
- [Link & Media Extraction](https://docs.crawl4ai.com/core/link-media/)

### Platform-Specific Docs

- [Shopify Product API](https://shopify.dev/docs/api/ajax/reference/product)
- [Shopify JSON Templates](https://shopify.dev/docs/storefronts/themes/architecture/templates/json-templates)
- [WooCommerce REST API](https://developer.woocommerce.com/docs/apis/rest-api/)
- [WooCommerce Products Endpoint](https://developer.woocommerce.com/docs/apis/store-api/resources-endpoints/products/)

### E-commerce Standards

- [Schema.org Product](https://schema.org/Product)
- [Open Graph Meta Tags](https://www.opengraph.io/)

### Related Resources

- [Crawl4AI GitHub Repository](https://github.com/unclecode/crawl4ai)
- [Crawl4AI: Hands-on Guide (ScrapingBee)](https://www.scrapingbee.com/blog/crawl4ai/)
- [Crawl4AI Tutorial (APIdog)](https://apidog.com/blog/crawl4ai-tutorial/)

---

**Document Version:** 1.0
**Last Updated:** February 14, 2026
**Crawl4AI Version Covered:** 0.8.x
