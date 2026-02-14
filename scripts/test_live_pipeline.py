"""Live pipeline test script — runs pipeline against real test shops.

Usage:
    uv run python scripts/test_live_pipeline.py
    uv run python scripts/test_live_pipeline.py --shop allbirds
    uv run python scripts/test_live_pipeline.py --shop allbirds --no-ingest
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import time
import uuid

import redis.asyncio as aioredis

from app.config import settings
from app.db.bulk_ingestor import BulkIngestor
from app.db.supabase_client import DatabaseClient
from app.db.queries import CREATE_PRODUCTS_TABLE
from app.infra.circuit_breaker import CircuitBreaker
from app.infra.progress_tracker import ProgressTracker
from app.infra.rate_limiter import RateLimiter
from app.services.pipeline import Pipeline

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("test_live_pipeline")

# Suppress noisy loggers
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logging.getLogger("hpack").setLevel(logging.WARNING)

# Test shops
TEST_SHOPS = {
    "allbirds": {
        "url": "https://www.allbirds.com",
        "expected_platform": "shopify",
        "description": "Shopify store (API tier)",
    },
    "ahmadtea": {
        "url": "https://www.ahmadtea.com",
        "expected_platform": "woocommerce",
        "description": "WooCommerce store (Sitemap + CSS tier)",
    },
    "magento": {
        "url": "https://magento2-demo.magebit.com",
        "expected_platform": "magento",
        "description": "Magento 2 demo (API or CSS tier)",
    },
    "bigcommerce": {
        "url": "https://iconic-electronics-demo.mybigcommerce.com",
        "expected_platform": "bigcommerce",
        "description": "BigCommerce demo (Sitemap + CSS tier)",
    },
    "etsy": {
        "url": "https://www.etsy.com",
        "expected_platform": "generic",
        "description": "Custom platform + anti-bot (Deep crawl tier)",
    },
    "ory-berlin": {
        "url": "https://ory-berlin.de",
        "expected_platform": "shopify",
        "description": "Ory Berlin Shopify store",
    },
}


async def run_single_test(
    shop_key: str,
    shop_config: dict,
    redis_client: aioredis.Redis,
    db_client: DatabaseClient | None,
) -> dict:
    """Run pipeline against a single test shop.

    Returns:
        Result dict with timing and counts.
    """
    job_id = f"test-{shop_key}-{uuid.uuid4().hex[:8]}"
    shop_url = shop_config["url"]

    logger.info(f"\n{'='*60}")
    logger.info(f"TESTING: {shop_key} — {shop_config['description']}")
    logger.info(f"URL: {shop_url}")
    logger.info(f"Job ID: {job_id}")
    logger.info(f"Expected platform: {shop_config['expected_platform']}")
    logger.info(f"{'='*60}")

    start_time = time.time()

    # Initialize infrastructure
    progress_tracker = ProgressTracker(redis_client)
    circuit_breaker = CircuitBreaker(
        threshold=settings.circuit_breaker_threshold,
        timeout=settings.circuit_breaker_timeout,
    )
    rate_limiter = RateLimiter(max_concurrent=5)

    # Initialize bulk ingestor (if db available)
    bulk_ingestor = BulkIngestor(db_client) if db_client else None

    # Create pipeline
    pipeline = Pipeline(
        progress_tracker=progress_tracker,
        circuit_breaker=circuit_breaker,
        rate_limiter=rate_limiter,
        bulk_ingestor=bulk_ingestor,
    )

    result = {
        "shop": shop_key,
        "url": shop_url,
        "expected_platform": shop_config["expected_platform"],
        "status": "unknown",
        "error": None,
    }

    try:
        pipeline_result = await pipeline.run(job_id, shop_url)
        elapsed = time.time() - start_time

        result.update({
            "status": "success",
            "platform": pipeline_result["platform"],
            "total_extracted": pipeline_result["total_extracted"],
            "total_normalized": pipeline_result["total_normalized"],
            "total_ingested": pipeline_result["total_ingested"],
            "extraction_tier": pipeline_result["extraction_tier"],
            "elapsed_seconds": round(elapsed, 2),
            "platform_match": pipeline_result["platform"] == shop_config["expected_platform"],
        })

        logger.info(f"\nRESULT for {shop_key}:")
        logger.info(f"  Platform: {pipeline_result['platform']} (expected: {shop_config['expected_platform']})")
        logger.info(f"  Extraction tier: {pipeline_result['extraction_tier']}")
        logger.info(f"  Products extracted: {pipeline_result['total_extracted']}")
        logger.info(f"  Products normalized: {pipeline_result['total_normalized']}")
        logger.info(f"  Products ingested: {pipeline_result['total_ingested']}")
        logger.info(f"  Time: {elapsed:.2f}s")

    except Exception as e:
        elapsed = time.time() - start_time
        result.update({
            "status": "failed",
            "error": str(e),
            "elapsed_seconds": round(elapsed, 2),
        })
        logger.error(f"\nFAILED for {shop_key}: {e}")

    # Check progress in Redis
    progress = await progress_tracker.get(job_id)
    if progress:
        result["final_progress"] = progress
        logger.info(f"  Final progress: {progress.get('status')} — {progress.get('current_step')}")

    return result


async def main(shop_filter: str | None = None, skip_ingest: bool = False):
    """Run pipeline tests against test shops."""
    logger.info("="*60)
    logger.info("MERCHANT ONBOARDING PIPELINE — LIVE TEST")
    logger.info("="*60)

    # Connect to Redis
    logger.info(f"\nConnecting to Redis at {settings.redis_url}...")
    redis_client = aioredis.from_url(settings.redis_url, decode_responses=False)
    try:
        await redis_client.ping()
        logger.info("Redis connected.")
    except Exception as e:
        logger.error(f"Redis connection failed: {e}")
        sys.exit(1)

    # Connect to database (optional)
    db_client = None
    if not skip_ingest:
        logger.info(f"Connecting to database at {settings.database_url}...")
        try:
            db_client = DatabaseClient(settings.database_url)
            await db_client.connect()

            # Ensure products table exists
            async with db_client.pool.acquire() as conn:
                await conn.execute(CREATE_PRODUCTS_TABLE)

            logger.info("Database connected and products table ready.")
        except Exception as e:
            logger.warning(f"Database connection failed: {e}. Continuing without ingestion.")
            db_client = None
    else:
        logger.info("Skipping database ingestion (--no-ingest flag)")

    # Filter shops
    shops_to_test = TEST_SHOPS
    if shop_filter:
        if shop_filter not in TEST_SHOPS:
            logger.error(f"Unknown shop: {shop_filter}. Available: {list(TEST_SHOPS.keys())}")
            sys.exit(1)
        shops_to_test = {shop_filter: TEST_SHOPS[shop_filter]}

    # Run tests sequentially (to avoid overwhelming targets)
    results = []
    for shop_key, shop_config in shops_to_test.items():
        result = await run_single_test(shop_key, shop_config, redis_client, db_client)
        results.append(result)

    # Print summary
    logger.info(f"\n{'='*60}")
    logger.info("TEST SUMMARY")
    logger.info(f"{'='*60}")
    logger.info(f"{'Shop':<15} {'Status':<10} {'Platform':<15} {'Extracted':<12} {'Normalized':<12} {'Ingested':<10} {'Time':<8}")
    logger.info("-" * 82)

    for r in results:
        if r["status"] == "success":
            platform_str = r.get("platform", "?")
            if not r.get("platform_match"):
                platform_str += " (!)"
            logger.info(
                f"{r['shop']:<15} {r['status']:<10} {platform_str:<15} "
                f"{r.get('total_extracted', 0):<12} {r.get('total_normalized', 0):<12} "
                f"{r.get('total_ingested', 0):<10} {r.get('elapsed_seconds', 0):<8}s"
            )
        else:
            error_short = (r.get("error") or "unknown")[:40]
            logger.info(
                f"{r['shop']:<15} {'FAILED':<10} {error_short}"
            )

    # Database totals
    if db_client:
        try:
            async with db_client.pool.acquire() as conn:
                total_count = await conn.fetchval("SELECT COUNT(*) FROM products")
                logger.info(f"\nTotal products in database: {total_count}")

                # Count by platform
                rows = await conn.fetch(
                    "SELECT platform, COUNT(*) as cnt FROM products GROUP BY platform ORDER BY cnt DESC"
                )
                for row in rows:
                    logger.info(f"  {row['platform']}: {row['cnt']} products")

                # Count by shop
                rows = await conn.fetch(
                    "SELECT shop_id, COUNT(*) as cnt FROM products GROUP BY shop_id ORDER BY cnt DESC"
                )
                for row in rows:
                    logger.info(f"  {row['shop_id']}: {row['cnt']} products")
        except Exception as e:
            logger.error(f"Failed to query database summary: {e}")

    # Cleanup
    if db_client:
        await db_client.close()
    await redis_client.aclose()

    # Exit code based on results
    failures = [r for r in results if r["status"] == "failed"]
    if failures:
        logger.warning(f"\n{len(failures)} test(s) failed.")
        return 1
    logger.info(f"\nAll {len(results)} test(s) passed!")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test pipeline against live shops")
    parser.add_argument("--shop", type=str, help="Test a single shop (allbirds, ahmadtea, magento, bigcommerce, etsy)")
    parser.add_argument("--no-ingest", action="store_true", help="Skip database ingestion")
    args = parser.parse_args()

    exit_code = asyncio.run(main(shop_filter=args.shop, skip_ingest=args.no_ingest))
    sys.exit(exit_code)
