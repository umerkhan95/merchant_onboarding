# Merchant Onboarding Pipeline

Automated e-commerce product ingestion for [idealo](https://www.idealo.de). Paste a store URL, get a complete product catalog exported as an idealo-ready feed. Supports 5 platforms via OAuth APIs, Google Shopping feed import, and intelligent scraping fallback.

**Turns 11-30 days of manual idealo onboarding into 5 minutes.**

## Architecture

```
                         ┌──────────────────────┐
                         │  idealo Merchant      │
                         │  Portal (Next.js)     │
                         │  Port 3002            │
                         └─────────┬────────────┘
                                   │
                    ┌──────────────▼──────────────┐
                    │   FastAPI (Port 8000)        │
                    │   JWT + API Key Auth (RBAC)  │
                    │   SecurityHeaders Middleware │
                    └──────────────┬──────────────┘
                                   │
              ┌────────────────────▼─────────────────────┐
              │              Celery + Redis               │
              │   (job queue, progress tracking, SSE)     │
              └────────────────────┬─────────────────────┘
                                   │
    ┌──────────────────────────────▼───────────────────────────────┐
    │                      Pipeline Orchestrator                   │
    │                                                              │
    │  1. PlatformDetector ─── shopify│woo│magento│bigcommerce     │
    │                                  │shopware│generic           │
    │                                                              │
    │  2. URLDiscoveryService ── API pagination / sitemaps /       │
    │                            BestFirst crawl (prefetch mode)   │
    │                                                              │
    │  3. Extraction (tiered fallback chain):                      │
    │     ┌─────────────────────────────────────────────────────┐  │
    │     │ Tier 0: Google Shopping Feed (XML/CSV, no crawling) │  │
    │     │ Tier 1: Platform Admin APIs (OAuth) ◄── preferred   │  │
    │     │ Tier 1: Platform Public APIs (no auth)              │  │
    │     │ Tier 2: UnifiedCrawl (JSON-LD+OG+markdown+media)    │  │
    │     │ Tier 3: SmartCSS (LLM-generated selectors, cached)  │  │
    │     │ Tier 4: LLM Extraction (universal fallback)         │  │
    │     │ Fallback: Hardcoded CSS schemas per platform        │  │
    │     └─────────────────────────────────────────────────────┘  │
    │                                                              │
    │  4. ExtractionValidator ── quality gate (score >= 0.3)       │
    │  5. ProductNormalizer ── unified Product schema              │
    │  6. BulkIngestor ── staging table → COPY → ON CONFLICT       │
    │  7. idealo CSV/TSV Export + PWS 2.0 API                      │
    └──────────────────────────────────────────────────────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │  PostgreSQL (Supabase)       │
                    │  12 tables, RBAC, encrypted  │
                    │  OAuth tokens (Fernet)       │
                    └──────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI (Python 3.11+, fully async) |
| Auth | JWT (HS256) + per-merchant API keys + RBAC (3 roles, 14 permissions) |
| Database | PostgreSQL via asyncpg (Supabase) |
| Scraping | crawl4ai (LLM-free extraction, stealth escalation, PruningContentFilter) |
| Task Queue | Celery + Redis (retry, backoff, DLQ) |
| Progress | Redis-backed SSE streaming |
| Merchant Portal | Next.js 16, React 19, Tailwind CSS 4 (port 3002) |
| Admin Dashboard | Next.js 15, React 19, Tailwind CSS 4 (port 3001) |
| Package Mgmt | uv (backend), npm (frontend) |

## Quick Start

### Prerequisites

- Python 3.11+
- Node.js 18+
- Docker (for PostgreSQL + Redis via Supabase)
- Redis 7

### 1. Backend Setup

```bash
# Clone and install
git clone https://github.com/umerkhan95/merchant_onboarding.git
cd merchant_onboarding
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your settings (see Environment Variables below)

# Start Supabase (PostgreSQL + Redis)
# If using Supabase CLI:
supabase start
# Or Docker:
docker compose up -d postgres redis

# Start the API server (creates all tables on startup)
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Start Celery worker (optional, for async job processing)
uv run celery -A app.workers.celery_app worker --concurrency=4 --loglevel=info

# Start Flower (optional, Celery monitoring)
uv run celery -A app.workers.celery_app flower --port=5555
```

### 2. Merchant Portal (idealo Frontend)

```bash
cd ../idealo-merchant-portal
npm install
npm run dev
# Open http://localhost:3002
```

### 3. Admin Dashboard (optional)

```bash
cd frontend
npm install
npm run dev -- -p 3001
# Open http://localhost:3001
```

### 4. Verify

```bash
# Health check
curl http://localhost:8000/health

# Readiness (checks Redis + Postgres)
curl http://localhost:8000/readiness

# Register a merchant account
curl -X POST http://localhost:8000/api/v1/auth/merchant/register \
  -H "Content-Type: application/json" \
  -d '{"email": "you@example.com", "password": "SecureP@ss123"}'

# Onboard a store (with legacy API key)
curl -X POST http://localhost:8000/api/v1/onboard \
  -H "X-API-Key: dev-key-1" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://deathwishcoffee.com"}'
```

## OAuth Platform Setup

The pipeline prefers OAuth Admin APIs over scraping — richer data, GTIN/barcode access, no anti-bot issues. All 5 major e-commerce platforms are supported.

### Prerequisites (all platforms)

Generate an encryption key for secure token storage:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Add to .env as OAUTH_ENCRYPTION_KEY=<generated-key>
```

### Shopify

1. Create a [Shopify Partner](https://partners.shopify.com/) app
2. Set **App URL** to your domain, **Redirect URL** to `{YOUR_DOMAIN}/api/v1/auth/shopify/callback`
3. Request scope: `read_products`
4. Add to `.env`:
   ```
   SHOPIFY_CLIENT_ID=your-client-id
   SHOPIFY_CLIENT_SECRET=your-client-secret
   SHOPIFY_CALLBACK_URL=https://your-domain.com/api/v1/auth/shopify/callback
   ```
5. Connect via merchant portal or API:
   ```bash
   curl "http://localhost:8000/api/v1/auth/shopify/connect?shop=mystore.myshopify.com" \
     -H "X-API-Key: dev-key-1"
   # Redirects merchant to Shopify OAuth consent screen
   ```

### WooCommerce

WooCommerce uses auto-auth (not standard OAuth 2.0) — the merchant is redirected to their WooCommerce admin to approve read-only API access. Consumer key/secret are POSTed back to your callback.

1. Add to `.env`:
   ```
   WOOCOMMERCE_APP_NAME=Your App Name
   WOOCOMMERCE_CALLBACK_URL=https://your-domain.com/api/v1/auth/woocommerce/callback
   WOOCOMMERCE_RETURN_URL=https://your-domain.com/api/v1/auth/woocommerce/return
   ```
2. Connect:
   ```bash
   curl "http://localhost:8000/api/v1/auth/woocommerce/connect?shop=example-store.com" \
     -H "X-API-Key: dev-key-1"
   ```
3. **Manual fallback** (if auto-auth fails): Merchant can paste consumer key/secret from WooCommerce Settings > Advanced > REST API:
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/woocommerce/manual \
     -H "X-API-Key: dev-key-1" \
     -H "Content-Type: application/json" \
     -d '{"shop": "example-store.com", "consumer_key": "ck_...", "consumer_secret": "cs_..."}'
   ```

### BigCommerce

1. Create a [BigCommerce Developer](https://developer.bigcommerce.com/) app (Draft status works for testing)
2. Set **Auth Callback URL** to `{YOUR_DOMAIN}/api/v1/auth/bigcommerce/callback`
3. Required scopes: `store_v2_products_read_only`
4. Add to `.env`:
   ```
   BIGCOMMERCE_CLIENT_ID=your-client-id
   BIGCOMMERCE_CLIENT_SECRET=your-client-secret
   BIGCOMMERCE_CALLBACK_URL=https://your-domain.com/api/v1/auth/bigcommerce/callback
   ```
5. Connect:
   ```bash
   curl "http://localhost:8000/api/v1/auth/bigcommerce/connect?shop=store-hash.mybigcommerce.com" \
     -H "X-API-Key: dev-key-1"
   ```

Note: BigCommerce tokens never expire — simplest OAuth of all platforms.

### Shopware 6

Shopware uses client credentials (not authorization code). The merchant creates an Integration in their admin panel and provides the credentials.

1. Add to `.env`:
   ```
   SHOPWARE_APP_NAME=Your App Name
   ```
2. Get setup instructions:
   ```bash
   curl "http://localhost:8000/api/v1/auth/shopware/connect?shop=my-store.com" \
     -H "X-API-Key: dev-key-1"
   # Returns HTML instructions for the merchant
   ```
3. Merchant creates Integration in Shopware Admin > Settings > System > Integrations, then submits credentials:
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/shopware/manual \
     -H "X-API-Key: dev-key-1" \
     -H "Content-Type: application/json" \
     -d '{"shop": "my-store.com", "client_id": "...", "client_secret": "..."}'
   ```

Note: Shopware bearer tokens expire every 10 minutes — the extractor auto-refreshes 30 seconds before expiry.

### Magento 2

Magento uses OAuth 1.0a. The merchant creates an Integration in their Magento admin, which triggers a callback to your server for token exchange.

1. Add to `.env`:
   ```
   MAGENTO_CALLBACK_URL=https://your-domain.com/api/v1/auth/magento/callback
   MAGENTO_IDENTITY_URL=https://your-domain.com/api/v1/auth/magento/identity
   ```
2. Initiate connection:
   ```bash
   curl "http://localhost:8000/api/v1/auth/magento/connect?shop=magento-store.com" \
     -H "X-API-Key: dev-key-1"
   # Returns setup instructions
   ```
3. Merchant creates Integration in Magento Admin > System > Integrations with your callback/identity URLs. On activation, Magento POSTs consumer credentials and the token exchange happens automatically.
4. **Manual fallback**: Merchant can paste an access token directly:
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/magento/manual \
     -H "X-API-Key: dev-key-1" \
     -H "Content-Type: application/json" \
     -d '{"shop": "magento-store.com", "access_token": "..."}'
   ```

### Managing Connections

```bash
# List all OAuth connections
curl http://localhost:8000/api/v1/auth/connections \
  -H "X-API-Key: dev-key-1"

# Check connection status for a specific store
curl http://localhost:8000/api/v1/auth/connections/example-store.com \
  -H "X-API-Key: dev-key-1"

# Disconnect a platform
curl -X DELETE "http://localhost:8000/api/v1/auth/shopify/disconnect?shop=mystore.myshopify.com" \
  -H "X-API-Key: dev-key-1"
```

## Authentication

The API supports three auth methods (checked in order):

### 1. JWT Bearer Token (recommended for frontends)

```bash
# Register
curl -X POST http://localhost:8000/api/v1/auth/merchant/register \
  -H "Content-Type: application/json" \
  -d '{"email": "merchant@example.com", "password": "SecureP@ss123"}'
# Returns: {"access_token": "eyJ...", "merchant_id": "uuid", "token_type": "bearer"}
# Sets httpOnly refresh_token cookie

# Login
curl -X POST http://localhost:8000/api/v1/auth/merchant/login \
  -H "Content-Type: application/json" \
  -d '{"email": "merchant@example.com", "password": "SecureP@ss123"}'

# Use JWT
curl http://localhost:8000/api/v1/auth/merchant/sessions \
  -H "Authorization: Bearer eyJ..."

# Refresh (uses httpOnly cookie)
curl -X POST http://localhost:8000/api/v1/auth/merchant/refresh \
  -b cookies.txt

# Logout
curl -X POST http://localhost:8000/api/v1/auth/merchant/logout -b cookies.txt

# Logout all sessions
curl -X POST http://localhost:8000/api/v1/auth/merchant/logout-all \
  -H "Authorization: Bearer eyJ..."
```

### 2. Per-Merchant API Keys (for integrations)

```bash
# Create an API key (requires JWT auth)
curl -X POST http://localhost:8000/api/v1/auth/merchant/api-keys \
  -H "Authorization: Bearer eyJ..." \
  -H "Content-Type: application/json" \
  -d '{"name": "my-integration", "scopes": "products:read,exports:read"}'
# Returns: {"key": "mk_...", "id": "uuid", ...}

# Use the key
curl http://localhost:8000/api/v1/products?shop_id=example.com \
  -H "X-API-Key: mk_..."

# List keys
curl http://localhost:8000/api/v1/auth/merchant/api-keys \
  -H "Authorization: Bearer eyJ..."

# Revoke a key
curl -X DELETE http://localhost:8000/api/v1/auth/merchant/api-keys/{key_id} \
  -H "Authorization: Bearer eyJ..."
```

### 3. Legacy API Keys (backward compatible)

```bash
curl http://localhost:8000/api/v1/products?shop_id=example.com \
  -H "X-API-Key: dev-key-1"
```

### Security Features

- **Account lockout**: 5 failed login attempts → 15-minute lockout
- **Refresh token rotation**: Family-based replay detection (reused token → entire family revoked)
- **RBAC**: 3 roles (admin/merchant/viewer), 14 permissions, scope enforcement on API keys
- **Audit log**: Every auth event recorded (login, register, key creation, etc.)
- **Security headers**: X-Frame-Options: DENY, X-Content-Type-Options: nosniff, X-XSS-Protection
- **Email encryption**: Fernet at rest, SHA-256 hash for lookup
- **SSRF prevention**: URL validation (scheme allowlist, private IP blocking, port restrictions)

## Extraction Tiers

| Tier | Strategy | Speed | Reliability | Cost |
|------|----------|-------|-------------|------|
| 0 | **Google Shopping Feed** (XML/CSV import, no crawling) | Instant | Highest | Free |
| 1 | **Platform Admin APIs** (Shopify/WooCommerce/Magento/BigCommerce/Shopware via OAuth) | Fastest | Highest | Free |
| 1 | **Platform Public APIs** (unauthenticated, limited data) | Fast | High | Free |
| 2 | **UnifiedCrawl** — JSON-LD + OG tags + markdown prices + scored images | Fast | High | Free |
| 3 | **SmartCSS** — LLM-generated CSS selectors, cached per domain (7-day TTL) | Medium | Medium | ~$0.01/domain |
| 4 | **LLM Extraction** — universal fallback via crawl4ai LLMExtractionStrategy | Slow | High | ~$0.01/page |

The pipeline probes each tier on a single URL. If quality score >= 0.3, it commits to that tier for all URLs. Partial results from failed probes enrich the winning tier's output.

### crawl4ai Features Used

- **PruningContentFilter** for clean markdown extraction
- **GeolocationConfig** (Berlin) for correct EUR pricing
- **Cookie consent dismissal** via `js_code` (OneTrust, Cookiebot, German buttons)
- **Stealth escalation** (STANDARD → STEALTH → UNDETECTED) with single browser reuse
- **Session-based "Load More"** handling for paginated product listings
- **BestFirstCrawlingStrategy** with prefetch mode for fast URL discovery
- **MemoryAdaptiveDispatcher** for backpressure-aware batch crawling
- **ContentTypeFilter** to auto-reject non-HTML URLs

## idealo Integration

### CSV Feed Export

```bash
# Validate export readiness
curl "http://localhost:8000/api/v1/exports/idealo/validate?shop_id=example.com" \
  -H "X-API-Key: dev-key-1"

# Download idealo TSV feed
curl "http://localhost:8000/api/v1/exports/idealo/csv?shop_id=example.com" \
  -H "X-API-Key: dev-key-1" -o products.tsv
```

### Google Shopping Feed Import

```bash
curl -X POST http://localhost:8000/api/v1/onboard \
  -H "X-API-Key: dev-key-1" \
  -H "Content-Type: application/json" \
  -d '{"feed_url": "https://example.com/google-shopping-feed.xml"}'
```

Supports RSS 2.0 XML (`xmlns:g="http://base.google.com/ns/1.0"`) and CSV/TSV Google Merchant Center formats. Skips platform detection, URL discovery, and extraction entirely.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| **Security** | | |
| `API_KEYS` | `""` | Comma-separated legacy API keys |
| `JWT_SECRET_KEY` | `change-me-in-production` | JWT signing key (HS256) |
| `JWT_ACCESS_EXPIRY_MINUTES` | `15` | Access token lifetime |
| `JWT_REFRESH_EXPIRY_DAYS` | `30` | Refresh token lifetime |
| `OAUTH_ENCRYPTION_KEY` | `""` | Fernet key for encrypting OAuth tokens + emails |
| **Database** | | |
| `DATABASE_URL` | `postgresql://...` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Celery broker |
| **Crawling** | | |
| `CRAWL_LOCALE` | `de-DE` | Browser locale for geo-pricing |
| `CRAWL_TIMEZONE` | `Europe/Berlin` | Browser timezone |
| `MAX_CONCURRENT_BROWSERS` | `10` | Max parallel browser sessions |
| `MEMORY_THRESHOLD_PERCENT` | `70.0` | RAM threshold for backpressure |
| **LLM** (optional, Tier 3-4) | | |
| `LLM_API_KEY` | `""` | OpenAI/Groq API key |
| `LLM_PROVIDER` | `openai/gpt-4o-mini` | LLM provider |
| **OAuth** (per platform) | | |
| `SHOPIFY_CLIENT_ID` / `_SECRET` / `_CALLBACK_URL` | | Shopify app credentials |
| `BIGCOMMERCE_CLIENT_ID` / `_SECRET` / `_CALLBACK_URL` | | BigCommerce app credentials |
| `WOOCOMMERCE_CALLBACK_URL` / `_RETURN_URL` | | WooCommerce auto-auth URLs |
| `MAGENTO_CALLBACK_URL` / `_IDENTITY_URL` | | Magento OAuth 1.0a URLs |
| `SHOPWARE_APP_NAME` | | Shopware integration name |

## Testing

```bash
# Run all unit tests (1650 tests)
uv run pytest tests/unit/ -q

# Run specific extractor tests
uv run pytest tests/unit/test_extractors/ -v

# Run auth tests
uv run pytest tests/unit/test_merchant_auth.py tests/unit/test_jwt_handler.py tests/unit/test_password.py -v

# Run with coverage
uv run pytest tests/unit/ --cov=app --cov-report=term-missing
```

## Project Structure

```
app/
  api/v1/             # Route handlers
    onboarding.py      # POST /onboard, GET /onboard/{id}, SSE progress
    products.py        # CRUD products, bulk update, completeness
    merchant_auth.py   # Register, login, refresh, logout, API keys
    auth.py            # OAuth connect/callback/disconnect (5 platforms)
    exports.py         # idealo CSV/TSV export, validation
    analytics.py       # Extraction analytics
    dlq.py             # Dead letter queue
  models/              # Pydantic models (Product, Job, Analytics)
  services/            # Business logic
    pipeline.py         # Orchestrator (detect → discover → extract → normalize → ingest)
    platform_detector.py # Detects Shopify/WooCommerce/Magento/BigCommerce/Shopware
    url_discovery.py     # API pagination / sitemaps / BestFirst crawl
    product_normalizer.py # Maps raw data → unified Product schema
  extractors/          # Data extraction (10 extractors)
    shopify_api.py / shopify_admin_extractor.py
    woocommerce_api.py / woocommerce_admin_extractor.py
    magento_api.py / magento_admin_extractor.py
    bigcommerce_admin_extractor.py
    shopware_admin_extractor.py
    google_feed_extractor.py
    unified_crawl_extractor.py  # JSON-LD + OG + markdown + media
    css_extractor.py / smart_css_extractor.py / llm_extractor.py
  db/
    supabase_client.py   # asyncpg connection pool
    bulk_ingestor.py     # Staging → COPY → upsert
    oauth_store.py       # Fernet-encrypted OAuth token CRUD
    merchant_store.py    # Accounts, API keys, refresh tokens, audit log
  security/
    jwt_handler.py       # JWT create/verify (HS256, 15min)
    password.py          # bcrypt hash/verify
    redis_nonce_store.py # Redis-backed CSRF nonces
    url_validator.py     # SSRF prevention
  infra/
    circuit_breaker.py   # Per-domain (5 failures → 60s cooldown)
    rate_limiter.py      # Per-domain asyncio.Semaphore
    progress_tracker.py  # Redis-backed job progress
    security_headers.py  # X-Frame-Options, CSP, etc.
  exporters/
    idealo_csv.py        # idealo TSV feed exporter
    idealo_pws.py        # idealo PWS 2.0 REST API client
  workers/
    celery_app.py        # Celery config
    tasks.py             # Async onboarding task

idealo-merchant-portal/  # Merchant-facing UI (separate repo)
  src/app/
    page.tsx              # Onboard (5 OAuth connect buttons + manual URL + feed import)
    products/page.tsx     # Product grid with edit modal, GTIN management
    settings/page.tsx     # Delivery, costs, payment config
    connections/page.tsx  # OAuth connection management

frontend/               # Admin dashboard
  src/app/
    page.tsx              # Onboard store
    jobs/page.tsx         # Job tracking
    products/page.tsx     # Product browser
    analytics/page.tsx    # Metrics & charts
    settings/page.tsx     # Merchant settings
    stores/page.tsx       # Store profiles

tests/                  # 1650 unit tests
evals/                  # Extraction accuracy evaluation harness
```

## Scale Design

- **Bulk ingestion**: Staging table → COPY → ON CONFLICT upsert (50k-100k rows/sec)
- **Backpressure**: `MemoryAdaptiveDispatcher` pauses at 70% RAM, max 10 concurrent browsers
- **Circuit breaker**: Per-domain, opens after 5 failures, 60s cooldown
- **Rate limiting**: Per-domain semaphore, per-endpoint slowapi limits (10/min standard, 2/min onboard)
- **Idempotent**: SHA256 idempotency key prevents duplicate products on re-runs
- **Dead letter queue**: Failed URLs after max retries go to Redis DLQ for manual replay
- **Stealth reuse**: Single browser instance across stealth escalation levels
- **Session-based extraction**: Persistent browser sessions for Load More button handling

## License

Private repository. All rights reserved.
