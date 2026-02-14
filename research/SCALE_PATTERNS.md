# Scale Patterns for Millions of Products

## Queue Architecture: Celery + Redis
- Celery is non-negotiable for production scraping pipelines
- Survives app restarts, built-in retry with exponential backoff
- Horizontal scaling via `--scale celery_worker=N`
- Flower dashboard for monitoring

## Database Bulk Insert Strategy
- **COPY** (50k-100k rows/sec): For initial loads
- **Staging table + COPY + ON CONFLICT** (5-10x faster than direct upsert): For idempotent updates
- **Batch INSERT**: 500-1000 row batches as fallback
- Never single-row INSERT in a loop

## Idempotency
- SHA256 hash of product data as `idempotency_key`
- `ON CONFLICT (idempotency_key) DO UPDATE SET ... WHERE data_changed`
- Only updates if actual data differs

## Backpressure
- Bounded queues (deque with maxlen)
- Process and discard each batch immediately
- Never accumulate full result set in memory
- crawl4ai `stream=True` for async generator instead of list

## Circuit Breaker (per domain)
- CLOSED → OPEN after 5 consecutive failures
- OPEN for 60 seconds (reject all requests to that domain)
- HALF_OPEN: test with 2 requests, close if both succeed
- Prevents hammering failing sites

## Rate Limiting (per domain)
- asyncio.Semaphore per domain
- Configurable rates per platform (Shopify API: generous, custom sites: conservative)
- Default: 1 req/sec per domain

## Dead Letter Queue
- Failed URLs after max retries go to Redis DLQ
- Manual inspection and replay via API endpoint
- 30-day TTL on DLQ entries

## Progress Tracking
- Redis-backed progress store
- SSE (Server-Sent Events) for real-time streaming to frontend
- Job states: queued → processing → completed/failed

## Memory Management (crawl4ai)
- MemoryAdaptiveDispatcher: pause at 70% RAM
- Max 10-15 concurrent browser sessions
- Batch URLs in groups of 50
- Force garbage collection between batches
- Single browser instance: ~150MB; 10 concurrent: ~1.5-2GB
