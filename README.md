# Merchant Onboarding Pipeline

Automated product ingestion system for [OneUp.com](https://oneup.com). When a merchant signs up and provides their store URL, the system detects the e-commerce platform, discovers product URLs, extracts inventory data, and stores it in a unified format — handling millions of products across any platform.

## Architecture

```
POST /api/v1/onboard {shop_url}
        |
        v (returns 202 + job_id)
   Celery Job (or direct async fallback)
        |
        v
   PlatformDetector        -- shopify | woocommerce | magento | generic
        |
        v
   URLDiscoveryService     -- API pagination / sitemap / deep crawl
        |
        v
   Extractor (per tier)    -- API > Schema.org > OpenGraph > SmartCSS > LLM
        |
        v
   ProductNormalizer       -- unified Product schema
        |
        v
   BulkIngestor            -- staging table > COPY > ON CONFLICT upsert
        |
        v
   PostgreSQL (products)
        |
        v
   ProgressTracker > SSE > Frontend
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| API | FastAPI (Python 3.11+, async) |
| Database | PostgreSQL via asyncpg |
| Scraping | crawl4ai (LLM-free + LLM extraction) |
| Task Queue | Celery + Redis |
| Progress | Redis-backed SSE streaming |
| Frontend | Next.js 15, React 19, Tailwind CSS 4 |
| Package Mgmt | uv (backend), npm (frontend) |

## Quick Start

### Docker Compose (recommended)

```bash
# Start all services
docker compose up -d

# API: http://localhost:8000
# Frontend: http://localhost:3000
# Flower (Celery monitor): http://localhost:5555
```

### Manual Development Setup

**Prerequisites:** Python 3.11+, Node.js 18+, PostgreSQL 16, Redis 7

```bash
# 1. Backend
uv sync
cp .env.example .env  # Edit with your settings

# Start PostgreSQL
docker run -d --name merchant_pg \
  -e POSTGRES_DB=merchant_onboarding \
  -e POSTGRES_PASSWORD=postgres \
  -p 5432:5432 postgres:16-alpine

# Start the API (creates tables automatically on startup)
API_KEYS=dev-key uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# 2. Frontend
cd frontend
npm install
NEXT_PUBLIC_API_KEY=dev-key npm run dev
```

The API server initializes PostgreSQL on startup (creates the products table if it doesn't exist). If PostgreSQL is unavailable, the API runs in degraded mode without persistence.

## Extraction Tiers

The pipeline tries extraction strategies in order of reliability and speed, falling back through 5 tiers:

| Tier | Strategy | Speed | Reliability | Cost |
|------|----------|-------|-------------|------|
| 1 | **Platform API** (Shopify `/products.json`, WooCommerce Store API) | Fastest | Highest | Free |
| 2 | **Schema.org JSON-LD** (`<script type="application/ld+json">`) | Fast | High | Free |
| 3 | **OpenGraph** meta tags (`og:title`, `og:image`, `og:price:amount`) | Fast | Medium | Free |
| 4 | **Smart CSS** (LLM-generated selectors, cached per domain) | Medium | Medium | ~$0.01/domain |
| 5 | **LLM Extraction** (universal fallback via crawl4ai) | Slow | High | ~$0.01/page |

Each tier produces raw data that passes through `ProductNormalizer` into a unified schema. If a tier extracts 0 products, the pipeline falls to the next tier. Partial results from failed tiers are merged to enrich the winning tier's output.

## API Reference

All endpoints require `X-API-Key` header (except `/health`, `/readiness`, `/api/v1/ping`).

### Onboarding

```bash
# Start onboarding a store
curl -X POST http://localhost:8000/api/v1/onboard \
  -H "X-API-Key: dev-key" \
  -H "Content-Type: application/json" \
  -d '{"url": "https://gymshark.com"}'
# Returns: {"job_id": "job_xxx", "status": "queued", "progress_url": "/api/v1/onboard/job_xxx/progress"}

# Check job status
curl http://localhost:8000/api/v1/onboard/job_xxx \
  -H "X-API-Key: dev-key"

# Stream real-time progress (SSE)
curl -N http://localhost:8000/api/v1/onboard/job_xxx/progress \
  -H "X-API-Key: dev-key"
```

### Products

```bash
# List products for a shop (paginated)
curl "http://localhost:8000/api/v1/products?shop_id=https://gymshark.com/&page=1&per_page=50" \
  -H "X-API-Key: dev-key"

# Get single product
curl http://localhost:8000/api/v1/products/123 \
  -H "X-API-Key: dev-key"
```

### Analytics and Jobs

```bash
# List all jobs
curl http://localhost:8000/api/v1/jobs \
  -H "X-API-Key: dev-key"

# Get aggregated analytics
curl http://localhost:8000/api/v1/analytics \
  -H "X-API-Key: dev-key"

# API performance metrics
curl http://localhost:8000/api/v1/performance \
  -H "X-API-Key: dev-key"
```

### Dead Letter Queue

```bash
# List failed jobs
curl http://localhost:8000/api/v1/dlq \
  -H "X-API-Key: dev-key"

# Retry a failed job
curl -X POST http://localhost:8000/api/v1/dlq/job_xxx/retry \
  -H "X-API-Key: dev-key"
```

### Health

```bash
curl http://localhost:8000/health        # {"status": "healthy"}
curl http://localhost:8000/readiness     # {"ready": true, "checks": {"redis": true, "postgres": true}}
```

## Frontend

The Next.js dashboard provides 4 pages:

| Page | Path | Description |
|------|------|-------------|
| **Onboard** | `/` | Submit store URL, real-time SSE progress tracking |
| **Jobs** | `/jobs` | All jobs table with status filters, clickable product counts |
| **Products** | `/products` | Product grid by shop URL, pagination, images, prices |
| **Analytics** | `/analytics` | Aggregated metrics, tier/platform/status charts, API performance |

The frontend communicates with the API via a Next.js rewrite proxy (`/api/v1/*` -> `http://localhost:8000/api/v1/*`) configured in `next.config.ts`.

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `API_KEYS` | `""` | Comma-separated valid API keys |
| `DATABASE_URL` | `postgresql://postgres:postgres@localhost:5432/merchant_onboarding` | PostgreSQL connection string |
| `REDIS_URL` | `redis://localhost:6379/0` | Redis connection string |
| `CELERY_BROKER_URL` | `redis://localhost:6379/1` | Celery broker |
| `LLM_API_KEY` | `""` | OpenAI/Groq API key (for Tier 4-5) |
| `LLM_PROVIDER` | `openai/gpt-4o-mini` | LLM provider string |
| `MAX_CONCURRENT_BROWSERS` | `10` | Max parallel browser sessions |
| `MEMORY_THRESHOLD_PERCENT` | `70.0` | RAM threshold for backpressure |
| `NEXT_PUBLIC_API_KEY` | `""` | Frontend API key |

## Testing

```bash
# Run all unit tests
uv run pytest tests/unit/ -v

# Run specific test file
uv run pytest tests/unit/test_api.py -v

# Run with coverage
uv run pytest tests/unit/ --cov=app --cov-report=term-missing
```

## Project Structure

```
app/
  api/v1/           # Route handlers (onboarding, products, analytics, dlq)
  models/           # Pydantic models (product, job, analytics, enums)
  services/         # Business logic (pipeline, platform_detector, url_discovery, normalizer)
  extractors/       # Data extraction (shopify_api, woocommerce_api, schema_org, opengraph, css, llm, smart_css)
  infra/            # Infrastructure (rate_limiter, circuit_breaker, progress_tracker, perf_tracker)
  db/               # Database (supabase_client, bulk_ingestor, queries)
  workers/          # Celery tasks
  security/         # URL validation, HTML sanitization, API key auth
  exceptions/       # Error handlers and custom exceptions
frontend/
  src/app/          # Next.js pages (onboard, jobs, products, analytics)
  src/components/   # React components (nav, jobs-table, product-grid, charts)
  src/lib/          # Utilities (api client, types, constants)
tests/
  unit/             # Unit tests (mirrors app/ structure)
  integration/      # Integration tests
evals/              # Extraction accuracy evaluation harness
```

## Scale Design

- **Bulk ingestion**: Staging table -> COPY -> ON CONFLICT upsert (50k-100k rows/sec)
- **Backpressure**: `MemoryAdaptiveDispatcher` pauses at 70% RAM, max 10 concurrent browsers
- **Circuit breaker**: Per-domain, opens after 5 failures, 60s cooldown
- **Rate limiting**: Per-domain semaphore, per-endpoint slowapi limits
- **Idempotent**: SHA256 idempotency key prevents duplicate products on re-runs
- **Dead letter queue**: Failed URLs after max retries go to Redis DLQ for manual replay
