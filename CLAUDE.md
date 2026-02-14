# Merchant Onboarding System - OneUp.com

## Project Overview

A merchant onboarding data ingestion pipeline for OneUp.com. When a merchant signs up and enters their shop URL, the system automatically detects the e-commerce platform, discovers product URLs, and ingests the store's product inventory into a unified format for OneUp's inventory management system.

Must handle millions of products without breaking. Must work regardless of platform.

## Tech Stack

- **API**: FastAPI (Python 3.11+, async throughout)
- **Database**: Supabase (PostgreSQL via asyncpg for bulk ops)
- **Scraping Engine**: crawl4ai (LLM-free extraction strategies only)
- **Task Queue**: Celery + Redis (job persistence, retry, horizontal scaling)
- **Progress**: Redis-backed SSE streaming
- **Package Management**: uv

## Design Principles

- **Single Responsibility Principle**: Every module does exactly one thing
- **Reusable Components**: Extractors, validators, rate limiters are standalone and composable
- **API-First Extraction**: Always prefer platform APIs over HTML scraping
- **Fail Gracefully**: Circuit breakers, dead letter queues, never crash the pipeline
- **Idempotent Ingestion**: Re-running the same shop produces no duplicates

## Architecture

```
POST /api/v1/onboard {shop_url}
        │
        ▼ (returns 202 + job_id)
   ┌─────────────┐
   │  Celery Job  │ ◄── Redis broker
   └──────┬──────┘
          │
          ▼
   PlatformDetector          ← detects: shopify | woocommerce | magento | generic
          │
          ▼
   URLDiscoveryService       ← finds all product URLs (API pagination / sitemap / crawl)
          │
          ▼
   Extractor (per platform)  ← extracts raw product data
          │
          ▼
   ProductNormalizer          ← maps to unified schema
          │
          ▼
   BulkIngestor              ← staging table → COPY → ON CONFLICT upsert
          │
          ▼
   Supabase (products table)
          │
          ▼
   ProgressTracker → SSE → Frontend
```

## Extraction Strategy (3 tiers)

### Tier 1: Platform APIs (fastest, most reliable, no scraping needed)
| Platform | Endpoint | Auth | Limit |
|----------|----------|------|-------|
| Shopify | `/products.json` | None | 250/request |
| WooCommerce | `/wp-json/wc/store/v1/products` | None (Store API) | Variable |
| Magento 2 | `/rest/V1/products` | None (guest default) | searchCriteria |

### Tier 2: Sitemap → crawl4ai CSS extraction
- Parse `/sitemap.xml` for product URLs (100-1000+ URLs/sec)
- Crawl each product page with `JsonCssExtractionStrategy`
- Platform-specific CSS schemas (BigCommerce, Squarespace, PrestaShop, etc.)

### Tier 3: Deep crawl (last resort for sites without API or sitemap)
- Schema.org JSON-LD from `<script type="application/ld+json">`
- OpenGraph meta tags (`og:title`, `og:image`, `og:price:amount`)
- CSS heuristic selectors with fallback chains
- BFS link discovery from homepage

## Platform Detection (priority order)

| Check | Shopify | WooCommerce | Magento 2 |
|-------|---------|-------------|-----------|
| HTTP Header | `X-ShopId` | - | `X-Magento-*` |
| Meta Generator | `content="Shopify"` | `content="WordPress"` | Magento comments |
| Script/CDN | `cdn.shopify.com` | `/wp-content/` | `/media/catalog/` |
| CSS Classes | `shopify-section` | `woocommerce` | `catalog-product` |
| API Probe | `/products.json` returns JSON | `/wp-json/wc/store/v1/` responds | `/rest/V1/products` responds |

## Scale Strategy (millions of products)

### Queue: Celery + Redis
- Each onboarding job → Celery task
- Workers scale horizontally: `--scale celery_worker=N`
- Task persistence survives app restarts
- Flower dashboard for monitoring

### Database: Staging Table + COPY + Upsert
- **COPY** for initial bulk load (50k-100k rows/sec)
- **Staging table → ON CONFLICT** for idempotent updates (5-10x faster than direct upsert)
- Batch size: 500-1000 rows per insert
- SHA256 `idempotency_key` on product data prevents duplicates

### Memory: Backpressure + Streaming
- crawl4ai `stream=True` (async generator, 60% less memory)
- `MemoryAdaptiveDispatcher` pauses at 70% RAM
- Max 10-15 concurrent browser sessions
- Process each batch immediately, never accumulate full result set
- Force `gc.collect()` between batches

### Resilience
- **Circuit breaker** per domain: OPEN after 5 consecutive failures, wait 60s, test with HALF_OPEN
- **Rate limiter** per domain: asyncio.Semaphore, configurable per platform
- **Dead letter queue**: Failed URLs after max retries → Redis DLQ → manual replay via API
- **Retry**: Exponential backoff with jitter (Celery native: `retry_backoff=True`)

### Progress Tracking
- Redis-backed progress store (processed/total/status)
- SSE endpoint: `GET /api/v1/onboard/{job_id}/progress`
- States: `queued → detecting → discovering → extracting → normalizing → ingesting → completed | failed`

## API Design

### Endpoints
```
POST   /api/v1/onboard              → 202 Accepted + {job_id, progress_url}
GET    /api/v1/onboard/{job_id}     → Job status + progress
GET    /api/v1/onboard/{job_id}/progress → SSE stream
GET    /api/v1/products?shop_id=X   → Paginated product list
GET    /api/v1/products/{id}        → Single product detail
GET    /api/v1/dlq                  → Dead letter queue inspection
POST   /api/v1/dlq/{job_id}/retry   → Replay failed job
GET    /health                       → Health check
GET    /readiness                    → Readiness check
```

### Security
- **API Key auth**: `X-API-Key` header, verify per request
- **SSRF prevention**: URL validation (scheme, hostname, private IP ranges, blocked ports)
- **HTML sanitization**: bleach library before storage (prevent stored XSS)
- **Rate limiting**: slowapi (10/min standard, 2/min bulk)
- **Input validation**: Pydantic V2 with field validators
- **Error format**: RFC 7807 Problem Details

## Project Structure (SRP)

```
merchant_onboarding/
├── CLAUDE.md
├── research/                          # Reference docs (not deployed)
│
├── app/
│   ├── main.py                        # FastAPI app factory + lifespan
│   ├── config.py                      # Settings via pydantic-settings
│   │
│   ├── api/
│   │   ├── deps.py                    # Shared dependencies (get_db, get_redis, verify_api_key)
│   │   └── v1/
│   │       ├── router.py             # v1 router aggregator
│   │       ├── onboarding.py         # POST /onboard, GET /onboard/{id}, SSE progress
│   │       ├── products.py           # GET /products
│   │       └── dlq.py                # GET /dlq, POST /dlq/{id}/retry
│   │
│   ├── models/
│   │   ├── product.py                # Product Pydantic model (unified schema)
│   │   ├── job.py                    # OnboardingJob model (request/response/status)
│   │   └── enums.py                  # Platform, JobStatus, ExtractionTier enums
│   │
│   ├── services/
│   │   ├── pipeline.py               # Orchestrator: ties detection → discovery → extraction → ingestion
│   │   ├── platform_detector.py      # ONLY detects platform type from URL
│   │   ├── url_discovery.py          # ONLY discovers product URLs (API pagination, sitemap, crawl)
│   │   ├── sitemap_parser.py         # ONLY parses sitemap.xml → list of URLs
│   │   └── product_normalizer.py     # ONLY maps raw extracted data → unified Product schema
│   │
│   ├── extractors/
│   │   ├── base.py                   # Abstract BaseExtractor interface
│   │   ├── shopify_api.py            # ONLY fetches from /products.json
│   │   ├── woocommerce_api.py        # ONLY fetches from /wp-json/wc/store/v1/products
│   │   ├── magento_api.py            # ONLY fetches from /rest/V1/products
│   │   ├── css_extractor.py          # ONLY extracts via crawl4ai JsonCssExtractionStrategy
│   │   ├── schema_org_extractor.py   # ONLY extracts JSON-LD structured data
│   │   ├── opengraph_extractor.py    # ONLY extracts OG meta tags
│   │   └── schemas/                  # CSS selector schemas per platform
│   │       ├── shopify.py
│   │       ├── woocommerce.py
│   │       ├── bigcommerce.py
│   │       └── generic.py
│   │
│   ├── infra/
│   │   ├── rate_limiter.py           # ONLY per-domain rate limiting (asyncio.Semaphore)
│   │   ├── circuit_breaker.py        # ONLY circuit breaker state machine
│   │   ├── retry_policy.py           # ONLY retry delay calculation (exponential backoff + jitter)
│   │   └── progress_tracker.py       # ONLY Redis-backed progress read/write
│   │
│   ├── db/
│   │   ├── supabase_client.py        # ONLY Supabase client initialization + connection
│   │   ├── bulk_ingestor.py          # ONLY staging table → COPY → upsert operations
│   │   └── queries.py                # ONLY raw SQL queries (no logic)
│   │
│   ├── workers/
│   │   ├── celery_app.py             # Celery config + app factory
│   │   └── tasks.py                  # Celery task definitions (thin wrappers around services)
│   │
│   ├── security/
│   │   ├── url_validator.py          # ONLY SSRF-safe URL validation
│   │   ├── html_sanitizer.py         # ONLY HTML sanitization before storage
│   │   └── api_key.py                # ONLY API key verification
│   │
│   └── exceptions/
│       ├── handlers.py               # FastAPI exception handlers (RFC 7807)
│       └── errors.py                 # Custom exception classes
│
├── tests/
│   ├── unit/
│   │   ├── test_platform_detector.py
│   │   ├── test_product_normalizer.py
│   │   ├── test_url_validator.py
│   │   ├── test_circuit_breaker.py
│   │   └── test_extractors/
│   ├── integration/
│   │   ├── test_pipeline.py
│   │   ├── test_bulk_ingestor.py
│   │   └── test_api.py
│   └── fixtures/
│       ├── shopify_products.json
│       ├── woocommerce_products.json
│       └── sample_html/
│
├── docker-compose.yml                 # FastAPI + Redis + Celery workers + Flower
├── Dockerfile
├── pyproject.toml
├── .env.example
└── .gitignore
```

## Unified Product Schema

```python
class Product(BaseModel):
    external_id: str              # Platform-specific product ID
    shop_id: str                  # The merchant's shop identifier
    platform: Platform            # shopify | woocommerce | magento | generic
    title: str
    description: str              # Plain text (sanitized)
    price: Decimal
    compare_at_price: Decimal | None
    currency: str                 # ISO 4217
    image_url: str                # Primary product image
    product_url: str              # Full canonical URL
    sku: str | None
    vendor: str | None
    product_type: str | None
    in_stock: bool
    variants: list[Variant]
    tags: list[str]
    raw_data: dict                # Original extracted data (for debugging)
    scraped_at: datetime
    idempotency_key: str          # SHA256 of normalized data
```

## Component Responsibility Map

| Component | Single Responsibility |
|-----------|----------------------|
| `PlatformDetector` | Takes a URL, returns platform enum. Nothing else. |
| `SitemapParser` | Takes a sitemap URL, returns list of product URLs. Nothing else. |
| `URLDiscoveryService` | Coordinates API pagination OR sitemap OR crawl to produce URL list. |
| `ShopifyAPIExtractor` | Fetches `/products.json`, returns raw product dicts. No normalization. |
| `WooCommerceAPIExtractor` | Fetches WooCommerce Store API, returns raw dicts. No normalization. |
| `MagentoAPIExtractor` | Fetches Magento REST API, returns raw dicts. No normalization. |
| `CSSExtractor` | Takes URL + CSS schema, returns raw extracted data via crawl4ai. |
| `SchemaOrgExtractor` | Parses JSON-LD from HTML, returns structured dict. |
| `OpenGraphExtractor` | Parses OG meta tags from HTML, returns dict. |
| `ProductNormalizer` | Takes raw data from ANY extractor, returns unified `Product`. |
| `RateLimiter` | Per-domain semaphore. `await limiter.acquire(domain)`. |
| `CircuitBreaker` | Per-domain state machine. Wraps any async call. |
| `RetryPolicy` | Calculates delay for attempt N. Pure function. |
| `ProgressTracker` | Reads/writes job progress to Redis. |
| `BulkIngestor` | Staging table → COPY → upsert. Takes Product list, writes to DB. |
| `URLValidator` | Validates URL safety (SSRF). Returns bool + reason. |
| `HTMLSanitizer` | Strips dangerous HTML. Input → sanitized output. |
| `Pipeline` | Orchestrator ONLY. Calls components in order. Contains no business logic itself. |

## crawl4ai Notes

- `AsyncWebCrawler` with `async with` context manager
- `arun()` returns `CrawlResult`; always check `result.success`
- `extracted_content` is a JSON **string** → `json.loads()`
- `arun_many()` with `stream=True` returns `AsyncGenerator`, NOT a list
- CSS selectors support comma fallbacks: `"h1, .product-title, [itemprop='name']"`
- Field types: `text`, `attribute`, `html`, `nested`, `nested_list`, `regex`
- `MemoryAdaptiveDispatcher(memory_threshold_percent=70)` for parallel crawling
- `BrowserConfig(enable_stealth=True)` for anti-bot
- Per browser instance: ~150MB RAM
- Shopify `/products.json` max 250/request, paginate with `?page=N`
- WooCommerce Store API is public (no auth), REST v3 API requires auth

## Development Rules

- `async/await` everywhere — crawl4ai, asyncpg, Redis are all async
- Every extractor implements `BaseExtractor.extract(url) → list[dict]`
- Every component is independently testable with no side effects
- Prefer API endpoints over HTML scraping when available
- Always sanitize before DB insertion
- Log every crawl (success/failure, URL, duration, products found)
- Never store raw HTML in database
- Tests must cover: extractors (unit), pipeline (integration), API (e2e)
