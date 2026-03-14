# Merchant Onboarding System

## Project Overview

A merchant onboarding data ingestion pipeline. When a merchant signs up and enters their shop URL, the system automatically detects the e-commerce platform, discovers product URLs, and ingests the store's product inventory into a unified format for inventory management.

## Tech Stack

- **API**: FastAPI (Python 3.11+, async throughout)
- **Database**: Supabase (PostgreSQL via asyncpg for bulk ops)
- **Scraping Engine**: crawl4ai (LLM-free extraction via UnifiedCrawl for Tiers 1-2)
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
   Extraction (tiered)       <- Tier 1: API | Tier 2: UnifiedCrawl | fallback: CSS
        |                       (Tiers 3-4 available if LLM_API_KEY configured)
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

### Tier 0: Google Shopping Feed (fastest path, no crawling)

When the merchant provides a `feed_url` (Google Shopping feed XML or CSV), the pipeline
skips detection, discovery, and the extraction probe chain entirely. One HTTP GET, parse
the feed, normalize, ingest. The feed contains complete product data with GTINs, prices,
images — no browser, no credentials, no rate limiting.

- **XML**: RSS 2.0 with `g:` namespace (`xmlns:g="http://base.google.com/ns/1.0"`)
- **CSV/TSV**: Google Merchant Center column headers (id, title, price, gtin, etc.)
- `GoogleFeedExtractor` parses both formats, returns raw product dicts
- `_normalize_google_feed` in ProductNormalizer maps to unified Product schema
- `g:sale_price` / `g:price` semantics: sale_price becomes price, price becomes compare_at
- defusedxml for XML parsing (security), MAX_RESPONSE_SIZE enforced
- `ExtractionTier.GOOGLE_FEED`, `Platform.GENERIC`

### Standard extraction (when no feed_url provided)

The pipeline probes each tier on a single sample URL. If the probe returns products
with quality score >= 0.3 (via QualityScorer), it commits to that tier for all URLs.
Partial results from failed probes are merged into the winning tier's output.

### Tier 1: Platform APIs (fastest, most reliable, no scraping needed)

Used when platform is detected as Shopify/WooCommerce/Magento. If the API returns
nothing, falls back to the probe chain below.

| Platform | Endpoint | Auth | Limit |
|----------|----------|------|-------|
| Shopify | `/products.json` (public) or Admin REST API (OAuth) | None / OAuth | 250/request |
| WooCommerce | `/wp-json/wc/store/v1/products` (public) or REST API v3 (OAuth) | None / HTTP Basic | 100/request |
| Magento 2 | `/rest/V1/products` | None (guest default) | searchCriteria |

**OAuth-first strategy**: For Shopify, WooCommerce, BigCommerce, and Shopware, the pipeline
checks for OAuth credentials first. If found, uses the Admin/REST API (richer data,
GTIN access). Falls back to public API, then scraping chain.

WooCommerce OAuth specifics:
- Uses WooCommerce auto-auth (`/wc-auth/v1/authorize`) — NOT standard OAuth 2.0
- WooCommerce POSTs `consumer_key` + `consumer_secret` to our callback
- All REST API v3 calls use HTTP Basic Auth (`consumer_key:consumer_secret`)
- GTIN extracted from `meta_data` array (15+ known plugin keys + regex fallback)
- Variable products require separate `/products/{id}/variations` fetch

### Tier 2: UnifiedCrawl

Single crawl that extracts from 4 layers, replacing the previous separate Schema.org
and OpenGraph probes:

1. **JSON-LD** from `result.html` (via `SchemaOrgExtractor.extract_from_html`)
2. **OG tags** from `result.metadata` (via `OpenGraphExtractor.from_metadata`)
3. **Markdown price/title** from `result.markdown` (via `MarkdownPriceExtractor` -- regex, no LLM)
4. **Best image** from `result.media` (crawl4ai scored images, no re-fetch)

Layer 1 wins; gaps filled by layers 2-4 without overwriting.

- **httpx fast path**: fetches HTML via httpx, parses JSON-LD + OG. If product has price + image,
  returns immediately (no browser). Browser only launches when price/image missing.
- **Browser path**: uses `get_browser_config()` with `scan_full_page=True`, `max_scroll_steps=20`.
  Stealth escalation via existing 3-tier system (STANDARD -> STEALTH -> UNDETECTED).
- **Batch mode**: `extract_batch()` uses `arun_many()` with `MemoryAdaptiveDispatcher`, single browser.
- Zero cost, browser overhead only when needed.

Note: `SchemaOrgExtractor` and `OpenGraphExtractor` classes still exist -- their static
parsing methods are reused by UnifiedCrawl, but their HTTP `extract(url)` methods are
no longer called by the pipeline.

### Tier 3: SmartCSS (requires `LLM_API_KEY` env var)

- Uses `JsonCssExtractionStrategy.generate_schema()` to auto-create CSS selectors.
- One-time LLM call per domain, cached via SchemaCache (Redis, 7-day TTL).
- Multi-sample validation: tests generated schema against 2-3 product pages.
- Robustness scoring rejects brittle selectors (nth-child-heavy schemas < 0.3 rejected).
- **Not wired in default task runner** -- only active when Pipeline receives a SmartCSSExtractor.

### Tier 4: LLM extraction (requires `LLM_API_KEY` env var)

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
without overwriting existing values. `_fill_missing_fields()` protects API-sourced
products (`_source` containing "admin_api") by only filling image-related fields
during re-extraction — prevents homepage data from overwriting correct API titles/prices.

### Shopify API Price Supplementation

When a Shopify store falls back from API to UnifiedCrawl (headless stores),
`_supplement_shopify_prices()` fetches canonical pricing from `/products.json`
to fix zero-price and geo-currency issues. Tries `shop.{domain}` as alternative
endpoint for headless stores (Hydrogen/custom frontends).

## Platform Detection

| Check | Shopify | WooCommerce | Magento 2 | BigCommerce | Shopware 6 |
|-------|---------|-------------|-----------|-------------|------------|
| HTTP Header | `X-ShopId` | - | `X-Magento-*` | - | `sw-version-id` |
| Meta Generator | `content="Shopify"` | `content="WordPress"` | Magento comments | BigCommerce | `content="Shopware"` |
| Script/CDN | `cdn.shopify.com` | `/wp-content/` | `/media/catalog/` | `cdn*.bigcommerce.com` | `/bundles/storefront/` |
| CSS Classes | `shopify-section` | `woocommerce` | `catalog-product` | - | - |
| API Probe | `/products.json` returns JSON | `/wp-json/wc/store/v1/` responds | `/rest/V1/store/storeConfigs` responds | - | `/api/_info/config` responds |

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
If <= 50 URLs need re-extraction, targeted passes run via UnifiedCrawl
(or Schema.org/OpenGraph static parsers for specific field gaps).
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
POST   /api/v1/onboard              -> 202 Accepted + {job_id, progress_url} (accepts url OR feed_url)
GET    /api/v1/onboard/{job_id}     -> Job status + progress
GET    /api/v1/onboard/{job_id}/progress -> SSE stream
GET    /api/v1/products?shop_id=X   -> Paginated product list
GET    /api/v1/products/{id}        -> Single product detail
GET    /api/v1/dlq                  -> Dead letter queue inspection
POST   /api/v1/dlq/{job_id}/retry   -> Replay failed job
GET    /api/v1/analytics            -> Extraction analytics
GET    /api/v1/exports/idealo/csv   -> Idealo CSV feed export
GET    /api/v1/auth/bigcommerce/connect?shop=X -> Initiate BigCommerce OAuth
GET    /api/v1/auth/bigcommerce/callback       -> BigCommerce OAuth callback
DELETE /api/v1/auth/bigcommerce/disconnect?shop=X -> Revoke BigCommerce connection
GET    /api/v1/auth/shopify/connect?shop=X -> Initiate Shopify OAuth
GET    /api/v1/auth/shopify/callback       -> Shopify OAuth callback (HMAC validated)
DELETE /api/v1/auth/shopify/disconnect?shop=X -> Revoke Shopify connection
GET    /api/v1/auth/woocommerce/connect?shop=X -> Initiate WooCommerce auto-auth
POST   /api/v1/auth/woocommerce/callback       -> WooCommerce key callback (POST, not GET)
GET    /api/v1/auth/woocommerce/return          -> WooCommerce post-auth landing page
POST   /api/v1/auth/woocommerce/manual          -> Manual consumer key/secret input
DELETE /api/v1/auth/woocommerce/disconnect?shop=X -> Revoke WooCommerce connection
GET    /api/v1/auth/shopware/connect?shop=X -> Instructions for Shopware Integration setup
POST   /api/v1/auth/shopware/manual          -> Submit Shopware client_id + client_secret
DELETE /api/v1/auth/shopware/disconnect?shop=X -> Revoke Shopware connection
GET    /api/v1/auth/magento/connect?shop=X -> Initiate Magento OAuth 1.0a Integration setup
POST   /api/v1/auth/magento/callback       -> Magento OAuth 1.0a callback (token exchange, no API key)
GET    /api/v1/auth/magento/identity        -> Magento identity verification (HTML, no API key)
POST   /api/v1/auth/magento/manual          -> Submit Magento access_token (manual fallback)
DELETE /api/v1/auth/magento/disconnect?shop=X -> Revoke Magento connection
GET    /api/v1/auth/connections     -> List all OAuth connections
GET    /api/v1/auth/connections/{domain} -> Connection status for a shop
PATCH  /api/v1/products/{id}        -> Update product fields (gtin, brand, condition, etc.)
POST   /api/v1/products/bulk-update -> CSV upload for bulk GTIN/brand/MPN updates
GET    /api/v1/products/completeness -> Per-product completeness scores + shop summary
GET    /api/v1/merchants/settings   -> Get stored merchant settings (delivery, costs)
PUT    /api/v1/merchants/settings   -> Create/update merchant settings
GET    /api/v1/exports/idealo/validate -> Pre-export validation check
GET    /health                       -> Health check
GET    /readiness                    -> Readiness check
```

## Security

- **API Key auth**: `X-API-Key` header, verified per request
- **OAuth token encryption**: Fernet symmetric encryption at rest for stored OAuth tokens
- **OAuth CSRF protection**: TTLNonceStore with 10-minute expiry for all OAuth flows
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
- SHA256 `idempotency_key` on stable identifiers (external_id|platform|shop_id|sku) prevents duplicates
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
|   |       +-- exports.py           # GET /exports/idealo/csv, GET /exports/idealo/validate
|   |       +-- auth.py              # OAuth endpoints (BigCommerce + Shopify + WooCommerce + Shopware + Magento connect/callback/disconnect, connections)
|   |       +-- magento_auth.py     # Magento 2 OAuth 1.0a callback flow + manual token entry
|       +-- shopware_auth.py    # Shopware 6 OAuth (manual client_credentials entry)
|   |       +-- shopify_auth.py      # Shopify OAuth sub-router (HMAC-SHA256, CSRF nonce, strict domain validation)
|   |       +-- woocommerce_auth.py  # WooCommerce auto-auth sub-router (key exchange, CSRF nonce, credential verification)
|   +-- models/
|   |   +-- product.py                # Product, ProductUpdate, MerchantSettings Pydantic models
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
|   +-- exporters/
|   |   +-- idealo_csv.py             # Idealo CSV/TSV feed exporter
|   |   +-- idealo_pws.py             # Idealo PWS 2.0 REST API client
|   +-- extractors/
|   |   +-- base.py                   # BaseExtractor ABC + ExtractionResult dataclass
|   |   +-- browser_config.py         # Browser/crawl config helpers, stealth levels, fetch_html_with_browser()
|   |   +-- shopify_api.py            # Fetches /products.json (public, unauthenticated)
|   |   +-- shopify_admin_extractor.py # Shopify Admin REST API via OAuth (GTIN/barcode first-class)
|   |   +-- woocommerce_api.py        # Fetches WooCommerce Store API (public, unauthenticated)
|   |   +-- woocommerce_admin_extractor.py # WooCommerce REST API v3 via OAuth (GTIN from meta_data, variations)
|   |   +-- magento_api.py            # Fetches Magento REST API (public, unauthenticated)
|   |   +-- magento_admin_extractor.py # Magento 2 Admin API via Integration token (EAN from custom attributes)
|   |   +-- bigcommerce_admin_extractor.py # BigCommerce Admin API V3 via OAuth (GTIN/UPC first-class)
|   |   +-- shopware_admin_extractor.py # Shopware 6 Admin API via OAuth client_credentials (EAN first-class, 10min token refresh)
|   |   +-- google_feed_extractor.py   # Google Shopping feed parser (XML RSS 2.0 + CSV/TSV)
|   |   +-- unified_crawl_extractor.py # Single crawl: JSON-LD + OG + markdown price + media (replaces separate Schema.org/OG probes)
|   |   +-- markdown_price_extractor.py # Regex-based price/title extraction from rendered markdown
|   |   +-- schema_org_extractor.py   # JSON-LD parsing (static methods reused by UnifiedCrawl)
|   |   +-- opengraph_extractor.py    # OG meta tag parsing (static methods reused by UnifiedCrawl)
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
|   |   +-- oauth_store.py            # Encrypted OAuth token storage (Fernet + asyncpg)
|   +-- workers/
|   |   +-- celery_app.py             # Celery config + app factory
|   |   +-- tasks.py                  # Celery task: creates Pipeline with infra components, runs it
|   +-- tasks/
|   |   +-- onboarding.py             # Alternative task entry point
|   +-- security/
|   |   +-- url_validator.py          # SSRF-safe URL validation
|   |   +-- html_sanitizer.py         # HTML sanitization before storage
|   |   +-- api_key.py                # API key verification
|   |   +-- nonce_store.py            # TTL-expiring nonce store for OAuth CSRF
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
| `ShopifyAPIExtractor` | Fetches public `/products.json`, returns raw product dicts. No normalization. |
| `ShopifyAdminExtractor` | Fetches Shopify Admin REST API via OAuth. Cursor-based pagination, barcode/GTIN on variants. |
| `WooCommerceAPIExtractor` | Fetches WooCommerce Store API (public), returns raw dicts. No normalization. |
| `WooCommerceAdminExtractor` | Fetches WooCommerce REST API v3 via OAuth. GTIN from meta_data (15+ plugin keys). Variable product variations. |
| `MagentoAPIExtractor` | Fetches Magento REST API (public, unauthenticated), returns raw dicts. No normalization. |
| `MagentoAdminExtractor` | Fetches Magento 2 Admin API via Integration token. EAN/GTIN from custom attributes. Pagination via searchCriteria. |
| `BigCommerceAdminExtractor` | Fetches BigCommerce Admin API V3 via OAuth. UPC/GTIN first-class. Brand resolution via cache. |
| `ShopwareAdminExtractor` | Fetches Shopware 6 Admin API via client_credentials. EAN first-class. Auto-refreshes 10min bearer tokens. |
| `OAuthStore` | Encrypted OAuth token CRUD (Fernet). Supports OAuth 2.0 + 1.0a fields. |
| `GoogleFeedExtractor` | Parses Google Shopping feed URL (XML or CSV/TSV). One HTTP GET, no browser. |
| `UnifiedCrawlExtractor` | Single crawl extracting JSON-LD + OG + markdown price + media. httpx fast path, browser fallback. |
| `MarkdownPriceExtractor` | Regex-based price/title/currency extraction from rendered markdown. No LLM. |
| `SchemaOrgExtractor` | JSON-LD parsing. Static methods reused by UnifiedCrawl; `extract(url)` no longer called by pipeline. |
| `OpenGraphExtractor` | OG meta tag parsing. Static methods reused by UnifiedCrawl; `extract(url)` no longer called by pipeline. |
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
| `IdealoCSVExporter` | Converts Product list to idealo-compatible TSV feed. No DB access. |
| `IdealoPWSClient` | Pushes offers to idealo PWS 2.0 REST API. OAuth2 auth, rate-aware. |
| `ProductUpdate` | Pydantic model for partial product updates (GTIN, brand, condition, category, description). |
| `MerchantSettings` | Pydantic model for persistent delivery/shipping/payment settings per shop. |

## crawl4ai Usage

### Browser-Based Extractors (CSS, SmartCSS, LLM)

- `AsyncWebCrawler` with `async with` context manager
- `arun()` returns `CrawlResult`; always check `result.success`
- `extracted_content` is a JSON **string** -> `json.loads()`
- `extract_batch()` uses `arun_many()` with `MemoryAdaptiveDispatcher` for single-browser batch crawling
- Three-tier stealth escalation: `STANDARD -> STEALTH -> UNDETECTED`
- Browser config via `browser_config.py`: `get_browser_config()`, `get_crawl_config()`, `get_crawler_strategy()`

### UnifiedCrawl Extractor

- httpx fast path: fetches HTML, parses JSON-LD + OG. Returns immediately if price + image found.
- Browser fallback: launches only when structured data is incomplete (missing price/image).
- Reuses `SchemaOrgExtractor.extract_from_html()` and `OpenGraphExtractor.from_metadata()` as static parsers.
- `MarkdownPriceExtractor` extracts price/title from `result.markdown` via regex (no LLM).
- `result.media` provides scored images (crawl4ai 0-8 scoring, threshold 2).
- `extract_batch()` uses `arun_many()` with `MemoryAdaptiveDispatcher` for single-browser batching.
- `fetch_html_with_browser()` shared helper for browser fallback.

### LLM-Specific (Tier 3-4)

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
   `extract_batch()` (single browser for batch). Only affects CSS/SmartCSS/LLM tiers. UnifiedCrawl
   uses httpx fast path (no browser) for most sites. Concurrency capped at 10.

2. **No distributed resource coordination**: Circuit breaker and rate limiter are per-process.
   Multiple Celery workers on different machines don't share state. Fine for single-node
   deployment, needs Redis-backed alternatives for multi-node.

3. **Tiers 3-4 not wired in default task**: `workers/tasks.py` creates Pipeline without
   SmartCSSExtractor or LLMExtractor. These tiers require `LLM_API_KEY` env var and
   explicit wiring in the task runner.

## Testing Rules

- **Crawl limit for testing**: Only crawl 10-20 product URLs max during testing. Never more.
  This prevents traffic spikes on target stores and avoids anti-bot blocks.
- Use `max_urls=10` when calling the pipeline for test runs.

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
