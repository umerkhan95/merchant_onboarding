# Merchant Onboarding System

## Project Overview

A merchant onboarding data ingestion pipeline. When a merchant signs up and enters their shop URL, the system automatically detects the e-commerce platform, discovers product URLs, and ingests the store's product inventory into a unified format for inventory management.

## Tech Stack

- **API**: FastAPI (Python 3.11+, async throughout)
- **Database**: Supabase (PostgreSQL via asyncpg for bulk ops)
- **Scraping Engine**: crawl4ai (LLM-free extraction strategies for Tiers 1-3)
- **Task Queue**: Celery + Redis (job persistence, retry, horizontal scaling)
- **Progress**: Redis-backed SSE streaming
- **Package Management**: uv
- **XML Parsing**: defusedxml (prevents XML entity expansion attacks)

## Design Principles

- **Single Responsibility Principle**: Every module does exactly one thing
- **Reusable Components**: Extractors, validators, rate limiters are standalone and composable
- **API-First Extraction**: Always prefer platform APIs over HTML scraping
- **Fail Gracefully**: Circuit breakers, dead letter queues, never crash the pipeline
- **Idempotent Ingestion**: Re-running the same shop produces no duplicates

## Architecture

```
POST /api/v1/onboard {url}
        |
        v (returns 202 + job_id)
   Celery Job (Redis broker, max_retries=3, retry_backoff=True)
        |
        v
   PlatformDetector          <- detects: shopify | woocommerce | magento | bigcommerce | generic
        |
        v
   URLDiscoveryService       <- API pagination / platform sitemaps / AsyncUrlSeeder / BestFirst crawl
        |
        v
   Extraction (tiered)       <- Tier 1: API | Tier 2: Schema.org | Tier 3: OG | fallback: CSS
        |                       (Tiers 4-5 available if LLM_API_KEY configured)
        v
   ExtractionValidator       <- quality gate + completeness check
        |
        v
   ProductNormalizer          <- maps to unified Product schema
        |
        v
   BulkIngestor              <- staging table -> COPY -> ON CONFLICT upsert
        |
        v
   ProgressTracker -> SSE -> Frontend
```

## Extraction Strategy (tiered fallback chain)

The pipeline probes each tier on a single sample URL. If the probe returns products
with quality score >= 0.3 (via QualityScorer), it commits to that tier for all URLs.
Partial results from failed probes are merged into the winning tier's output.

### Tier 1: Platform APIs (fastest, most reliable, no scraping needed)

Used when platform is detected as Shopify/WooCommerce/Magento. If the API returns
nothing, falls back to the probe chain below.

| Platform | Endpoint | Auth | Limit |
|----------|----------|------|-------|
| Shopify | `/products.json` | None | 250/request, paginate with `?page=N` |
| WooCommerce | `/wp-json/wc/store/v1/products` | None (Store API) | Variable |
| Magento 2 | `/rest/V1/products` | None (guest default) | searchCriteria |

### Tier 2: Schema.org JSON-LD

- Fetches HTML via **httpx** (no browser). Browser fallback only on HTTP 403/429/503.
- Parses `<script type="application/ld+json">` for Product objects.
- Enriches sparse JSON-LD with OpenGraph meta tags from the same page.
- Zero cost, zero browser overhead for most sites.

### Tier 3: OpenGraph meta tags

- Same httpx-first approach, browser fallback on 403/429/503 only.
- Extracts `og:title`, `og:image`, `og:price:amount`, `product:price:amount` etc.
- Zero cost.

### Tier 4: SmartCSS (requires `LLM_API_KEY` env var)

- Uses `JsonCssExtractionStrategy.generate_schema()` to auto-create CSS selectors.
- One-time LLM call per domain, cached via SchemaCache (Redis, 7-day TTL).
- Multi-sample validation: tests generated schema against 2-3 product pages.
- Robustness scoring rejects brittle selectors (nth-child-heavy schemas < 0.3 rejected).
- **Not wired in default task runner** -- only active when Pipeline receives a SmartCSSExtractor.

### Tier 5: LLM extraction (requires `LLM_API_KEY` env var)

- Uses `LLMExtractionStrategy` with `input_format="markdown"` (40-60% token reduction).
- `chunk_token_threshold=8000`, `overlap_rate=0.1`.
- Merges duplicate products from overlapping chunks via title similarity.
- **Not wired in default task runner** -- only active when Pipeline receives an LLMExtractor.

### CSS Fallback

If no probe passes quality threshold, falls back to hardcoded CSS schemas
(generic or platform-specific like BigCommerce). Uses crawl4ai `AsyncWebCrawler`
with `JsonCssExtractionStrategy`.

### Cross-Tier Field Merging

Products from the winning tier are enriched with fields from earlier probe results.
`_merge_tier_fields()` fills missing/empty fields from supplementary tier data
without overwriting existing values.

### Shopify API Price Supplementation

When a Shopify store falls back from API to Schema.org (headless stores),
`_supplement_shopify_prices()` fetches canonical pricing from `/products.json`
to fix zero-price and geo-currency issues. Tries `shop.{domain}` as alternative
endpoint for headless stores (Hydrogen/custom frontends).

## Platform Detection

| Check | Shopify | WooCommerce | Magento 2 | BigCommerce |
|-------|---------|-------------|-----------|-------------|
| HTTP Header | `X-ShopId` | - | `X-Magento-*` | - |
| Meta Generator | `content="Shopify"` | `content="WordPress"` | Magento comments | BigCommerce |
| Script/CDN | `cdn.shopify.com` | `/wp-content/` | `/media/catalog/` | `cdn*.bigcommerce.com` |
| CSS Classes | `shopify-section` | `woocommerce` | `catalog-product` | - |
| API Probe | `/products.json` returns JSON | `/wp-json/wc/store/v1/` responds | `/rest/V1/products` responds | - |

## URL Discovery

Three-phase strategy per platform:

1. **Platform-specific product sitemaps** (e.g. `/sitemap_products_1.xml` for Shopify)
   -- parsed with defusedxml, MAX_RESPONSE_SIZE (10MB) enforced.
2. **Generic sitemap via crawl4ai `AsyncUrlSeeder`** -- capped at `max_urls=5000`.
3. **Browser-based `BestFirstCrawlingStrategy`** -- keyword-scored crawl, max 100 pages,
   product-keyword relevance scoring, URL pattern filtering.

All results filtered through `is_non_product_url()` denylist (blog, about, cart, etc.).

## Pipeline Behavior

### Concurrency

- `_EXTRACTION_CONCURRENCY = 10` -- URLs processed in batches of 10 via `asyncio.gather`.
- Each URL gets its own circuit-breaker-wrapped `extract()` call.
- **Known limitation**: Browser-based extractors (CSS/SmartCSS/LLM) create a new
  `AsyncWebCrawler` per `extract()` call. The `extract_batch()` method reuses a single
  browser but the pipeline currently calls per-URL `extract()`, not `extract_batch()`.

### Timeouts and Safety

- **Pipeline timeout**: 30 minutes (`asyncio.wait_for`). Job marked FAILED on timeout.
- **MAX_RESPONSE_SIZE**: 10MB cap on HTTP responses (sitemaps, HTML pages). Prevents
  memory exhaustion from oversized payloads.
- **Catastrophic error rate detection**: If >80% of URLs error (min 6 attempted),
  raises `ExtractionError` to abort rather than returning empty results silently.

### Verification Pass

After extraction, `CompletenessChecker` identifies products missing price or image.
If <= 50 URLs need re-extraction, targeted passes run:
- Missing price -> Schema.org re-extraction
- Missing image -> OpenGraph re-extraction

Results merged back without overwriting existing fields.

### Job States

```
queued -> detecting -> discovering -> extracting -> verifying -> normalizing -> ingesting -> completed
                                                                                        -> needs_review
                                                                                        -> failed
```

`needs_review`: Set when no URLs discovered or extraction validation fails.

## API Endpoints

```
POST   /api/v1/onboard              -> 202 Accepted + {job_id, progress_url}
GET    /api/v1/onboard/{job_id}     -> Job status + progress
GET    /api/v1/onboard/{job_id}/progress -> SSE stream
GET    /api/v1/products?shop_id=X   -> Paginated product list
GET    /api/v1/products/{id}        -> Single product detail
GET    /api/v1/dlq                  -> Dead letter queue inspection
POST   /api/v1/dlq/{job_id}/retry   -> Replay failed job
GET    /api/v1/analytics            -> Extraction analytics
GET    /health                       -> Health check
GET    /readiness                    -> Readiness check
```

## Security

- **API Key auth**: `X-API-Key` header, verified per request
- **SSRF prevention**: URL validation (scheme allowlist, private IP blocking, port restrictions)
- **XML safety**: defusedxml blocks entity expansion attacks (Billion Laughs)
- **Response size limits**: MAX_RESPONSE_SIZE (10MB) on all fetched content
- **HTML sanitization**: bleach library before storage (prevent stored XSS)
- **Rate limiting**: slowapi (10/min standard, 2/min onboard)
- **Input validation**: Pydantic V2 with field validators
- **Defense in depth**: URL validation in both API layer and Celery task
- **Error format**: RFC 7807 Problem Details

## Infrastructure

### Queue: Celery + Redis
- Each onboarding job -> Celery task with `max_retries=3, retry_backoff=True`
- Workers: `--concurrency=4` (4 concurrent tasks per worker)
- Flower dashboard on port 5555

### Database: Staging Table + COPY + Upsert
- **COPY** for bulk load
- **Staging table -> ON CONFLICT** for idempotent updates
- SHA256 `idempotency_key` on product data prevents duplicates
- DB client created per Celery task, closed in `finally` block

### Resilience
- **Circuit breaker** per domain: OPEN after 5 consecutive failures, wait 60s, HALF_OPEN test
- **Rate limiter** per domain: `asyncio.Semaphore`, 5 concurrent per domain
- **Dead letter queue**: Redis-backed, manual replay via API
- **Retry**: Celery native exponential backoff with jitter
- **Note**: Circuit breaker and rate limiter are per-process (not distributed across workers)

### Progress Tracking
- Redis-backed progress store (processed/total/status/metadata)
- SSE endpoint for real-time frontend updates
- Metadata includes: platform, extraction_tier, reconciliation_report, coverage_percentage

## Project Structure

```
merchant_onboarding/
+-- CLAUDE.md
+-- app/
|   +-- main.py                        # FastAPI app factory + lifespan
|   +-- config.py                      # Settings via pydantic-settings + MAX_RESPONSE_SIZE
|   +-- api/
|   |   +-- deps.py                    # Shared deps (get_db, get_redis, verify_api_key)
|   |   +-- v1/
|   |       +-- router.py             # v1 router aggregator
|   |       +-- onboarding.py         # POST /onboard, GET /onboard/{id}, SSE progress
|   |       +-- products.py           # GET /products
|   |       +-- dlq.py                # GET /dlq, POST /dlq/{id}/retry
|   |       +-- analytics.py          # GET /analytics
|   +-- models/
|   |   +-- product.py                # Product Pydantic model (unified schema)
|   |   +-- job.py                    # OnboardingJob model (request/response/status)
|   |   +-- enums.py                  # Platform, JobStatus, ExtractionTier enums
|   |   +-- analytics.py              # Analytics response models
|   +-- services/
|   |   +-- pipeline.py               # Orchestrator: detect -> discover -> extract -> verify -> normalize -> ingest
|   |   +-- platform_detector.py      # Detects platform type from URL
|   |   +-- url_discovery.py          # Discovers product URLs (API/sitemap/crawl) + sitemap XML parsing
|   |   +-- url_filters.py            # Non-product URL denylist (is_non_product_url) + platform sitemap paths
|   |   +-- url_normalizer.py         # Shop URL normalization (scheme, trailing slash, www)
|   |   +-- product_normalizer.py     # Maps raw extracted data -> unified Product schema
|   |   +-- completeness_checker.py   # Checks product field completeness, builds re-extraction plans
|   |   +-- extraction_tracker.py     # Per-URL outcome tracking (success/empty/error/not_product)
|   |   +-- extraction_validator.py   # Validates extraction results meet quality thresholds
|   |   +-- page_validator.py         # Validates if a URL is actually a product page
|   |   +-- reconciliation_reporter.py # Generates coverage/reconciliation reports
|   +-- extractors/
|   |   +-- base.py                   # BaseExtractor ABC + ExtractionResult dataclass
|   |   +-- browser_config.py         # Browser/crawl config helpers, stealth levels, fetch_html_with_browser()
|   |   +-- shopify_api.py            # Fetches /products.json
|   |   +-- woocommerce_api.py        # Fetches WooCommerce Store API
|   |   +-- magento_api.py            # Fetches Magento REST API
|   |   +-- schema_org_extractor.py   # JSON-LD extraction (httpx first, browser fallback on 403/429/503)
|   |   +-- opengraph_extractor.py    # OG meta tags (httpx first, browser fallback on 403/429/503)
|   |   +-- css_extractor.py          # crawl4ai JsonCssExtractionStrategy with stealth escalation
|   |   +-- smart_css_extractor.py    # LLM-generated CSS selectors, cached per domain (requires LLM_API_KEY)
|   |   +-- llm_extractor.py          # Universal LLM extraction (requires LLM_API_KEY)
|   |   +-- schema_cache.py           # Redis-backed CSS schema cache per domain
|   |   +-- schemas/                  # Hardcoded CSS selector schemas per platform
|   |       +-- shopify.py
|   |       +-- woocommerce.py
|   |       +-- bigcommerce.py
|   |       +-- generic.py
|   +-- infra/
|   |   +-- circuit_breaker.py        # Per-domain circuit breaker state machine
|   |   +-- rate_limiter.py           # Per-domain asyncio.Semaphore rate limiting
|   |   +-- retry_policy.py           # Retry delay calculation (exponential backoff + jitter)
|   |   +-- progress_tracker.py       # Redis-backed progress read/write
|   |   +-- quality_scorer.py         # Scores extraction quality (field completeness)
|   |   +-- perf_middleware.py        # FastAPI performance middleware
|   |   +-- perf_tracker.py           # Performance tracking utilities
|   +-- db/
|   |   +-- supabase_client.py        # DatabaseClient (asyncpg pool init + connection)
|   |   +-- bulk_ingestor.py          # Staging table -> COPY -> upsert operations
|   |   +-- queries.py                # Raw SQL queries
|   +-- workers/
|   |   +-- celery_app.py             # Celery config + app factory
|   |   +-- tasks.py                  # Celery task: creates Pipeline with infra components, runs it
|   +-- tasks/
|   |   +-- onboarding.py             # Alternative task entry point
|   +-- security/
|   |   +-- url_validator.py          # SSRF-safe URL validation
|   |   +-- html_sanitizer.py         # HTML sanitization before storage
|   |   +-- api_key.py                # API key verification
|   +-- exceptions/
|       +-- handlers.py               # FastAPI exception handlers (RFC 7807)
|       +-- errors.py                 # Custom exceptions (CircuitOpenError, ExtractionError, SSRFError)
+-- tests/
|   +-- conftest.py
|   +-- unit/
|   |   +-- test_extractors/          # Per-extractor unit tests (all 8 extractors)
|   |   +-- test_pipeline.py          # Pipeline orchestration tests
|   |   +-- test_pipeline_eval.py     # Pipeline evaluation tests
|   |   +-- test_pipeline_verification.py
|   |   +-- test_platform_detector.py
|   |   +-- test_product_normalizer.py
|   |   +-- test_url_discovery.py
|   |   +-- test_url_filters.py
|   |   +-- test_url_normalizer.py
|   |   +-- test_url_validator.py
|   |   +-- test_quality_scorer.py
|   |   +-- test_completeness_checker.py
|   |   +-- test_extraction_tracker.py
|   |   +-- test_extraction_validator.py
|   |   +-- test_reconciliation_reporter.py
|   |   +-- test_page_validator.py
|   |   +-- test_security.py
|   |   +-- test_security_xml_size.py
|   |   +-- test_api.py
|   |   +-- test_db.py
|   |   +-- test_infra.py
|   |   +-- test_models.py
|   |   +-- test_analytics.py
|   |   +-- ... (additional test files)
|   +-- fixtures/
|       +-- shopify_products.json
|       +-- woocommerce_products.json
|       +-- magento_products.json
|       +-- sample_sitemap.xml
+-- docker-compose.yml                 # api + postgres + redis + celery_worker + flower + frontend
+-- Dockerfile
+-- pyproject.toml
+-- .env.example
+-- .gitignore
```

## Component Responsibility Map

| Component | Single Responsibility |
|-----------|----------------------|
| `PlatformDetector` | Takes a URL, returns platform enum + confidence. Nothing else. |
| `URLDiscoveryService` | Discovers product URLs: API pagination / platform sitemaps / AsyncUrlSeeder / BestFirst crawl. Also parses sitemap XML internally. |
| `ShopifyAPIExtractor` | Fetches `/products.json`, returns raw product dicts. No normalization. |
| `WooCommerceAPIExtractor` | Fetches WooCommerce Store API, returns raw dicts. No normalization. |
| `MagentoAPIExtractor` | Fetches Magento REST API, returns raw dicts. No normalization. |
| `SchemaOrgExtractor` | Fetches HTML via httpx (browser fallback on 403/429/503), parses JSON-LD. |
| `OpenGraphExtractor` | Fetches HTML via httpx (browser fallback on 403/429/503), parses OG meta tags. |
| `CSSExtractor` | Browser-based extraction via `JsonCssExtractionStrategy`. Stealth escalation. |
| `SmartCSSExtractor` | Generates CSS selectors per domain via LLM, caches, reuses. Requires LLM API key. |
| `LLMExtractor` | Universal LLM extraction via `LLMExtractionStrategy`. Requires LLM API key. |
| `SchemaCache` | Redis-backed CSS schema cache per domain (7-day TTL). |
| `ProductNormalizer` | Takes raw data from ANY extractor, returns unified `Product`. |
| `QualityScorer` | Scores extraction quality (field completeness: title, price, image, etc.). |
| `CompletenessChecker` | Identifies products missing price/image, builds re-extraction plans. |
| `ExtractionTracker` | Records per-URL extraction outcomes (success/empty/error/not_product). |
| `ExtractionValidator` | Validates overall extraction results meet quality thresholds. |
| `PageValidator` | Checks if HTML is actually a product page (prevents wasted extraction). |
| `ReconciliationReporter` | Generates coverage report (discovered vs extracted vs normalized). |
| `RateLimiter` | Per-domain asyncio.Semaphore. In-process only. |
| `CircuitBreaker` | Per-domain state machine (CLOSED/OPEN/HALF_OPEN). In-process only. |
| `RetryPolicy` | Calculates delay for attempt N. Pure function. |
| `ProgressTracker` | Reads/writes job progress + metadata to Redis. |
| `BulkIngestor` | Staging table -> COPY -> upsert. Takes Product list, writes to DB. |
| `URLValidator` | SSRF-safe URL validation (scheme, private IPs, ports). |
| `HTMLSanitizer` | Strips dangerous HTML via bleach. |
| `Pipeline` | Orchestrator ONLY. Calls components in order. Contains no business logic itself. |

## crawl4ai Usage

### Browser-Based Extractors (CSS, SmartCSS, LLM)

- `AsyncWebCrawler` with `async with` context manager
- `arun()` returns `CrawlResult`; always check `result.success`
- `extracted_content` is a JSON **string** -> `json.loads()`
- `extract_batch()` uses `arun_many()` with `MemoryAdaptiveDispatcher` for single-browser batch crawling
- Three-tier stealth escalation: `STANDARD -> STEALTH -> UNDETECTED`
- Browser config via `browser_config.py`: `get_browser_config()`, `get_crawl_config()`, `get_crawler_strategy()`

### HTTP-Based Extractors (Schema.org, OpenGraph)

- Use **httpx** for fast, browserless HTML fetching
- `fetch_html_with_browser()` shared helper for 403/429/503 fallback only
- No browser overhead for most sites

### LLM-Specific (Tier 4-5)

- `LLMExtractionStrategy`: `input_format="markdown"`, `chunk_token_threshold=8000`, `overlap_rate=0.1`
- `generate_schema()`: one-time LLM call, cached via SchemaCache
- Providers via LiteLLM: `openai/gpt-4o-mini` etc.
- Token tracking: `strategy.show_usage()`

### Known crawl4ai Bugs (avoid)

- `CosineStrategy` returns empty results (GitHub #1424) -- do not use
- `LLMExtractionStrategy` skipped when `cache_mode=ENABLED` (#1455) -- use `cache_mode="bypass"`
- `generate_schema()` produces brittle selectors from single samples (#1672)

## Known Limitations

1. **Per-URL browser spawning**: Pipeline calls `extract()` (new browser per URL) instead of
   `extract_batch()` (single browser for batch). Only affects CSS/SmartCSS/LLM tiers. Schema.org
   and OpenGraph use httpx, no browser. Concurrency capped at 10, so max ~10 browsers at once
   per job, not thousands.

2. **No distributed resource coordination**: Circuit breaker and rate limiter are per-process.
   Multiple Celery workers on different machines don't share state. Fine for single-node
   deployment, needs Redis-backed alternatives for multi-node.

3. **Tiers 4-5 not wired in default task**: `workers/tasks.py` creates Pipeline without
   SmartCSSExtractor or LLMExtractor. These tiers require `LLM_API_KEY` env var and
   explicit wiring in the task runner.

## Development Rules

- `async/await` everywhere -- crawl4ai, asyncpg, Redis are all async
- Every extractor implements `BaseExtractor.extract(url) -> list[dict]`
- Every component is independently testable with no side effects
- Prefer API endpoints over HTML scraping when available
- Always sanitize before DB insertion
- Log every crawl (success/failure, URL, duration, products found)
- Never store raw HTML in database

## Git Rules

- Never add `Co-Authored-By` lines or any watermarks in commit messages
- Keep commit messages concise and descriptive -- focus on what changed and why
- No emoji in commit messages
