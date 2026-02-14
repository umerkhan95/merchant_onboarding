"""Celery task definitions for merchant onboarding pipeline."""

from __future__ import annotations

import asyncio
import logging

import redis.asyncio as redis

from app.config import settings
from app.db.bulk_ingestor import BulkIngestor
from app.db.supabase_client import DatabaseClient
from app.infra.circuit_breaker import CircuitBreaker
from app.infra.progress_tracker import ProgressTracker
from app.infra.rate_limiter import RateLimiter
from app.services.pipeline import Pipeline
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, retry_backoff=True)
def run_onboarding_pipeline(self, job_id: str, shop_url: str) -> dict:
    """Celery task that runs the async pipeline.

    Args:
        self: Celery task instance (bound)
        job_id: Unique job identifier
        shop_url: Merchant shop URL to onboard

    Returns:
        Pipeline result dict with platform, counts, and extraction tier

    Raises:
        Exception: Re-raises exceptions from pipeline after retries
    """
    logger.info(f"Starting onboarding task for job {job_id}, shop URL: {shop_url}")

    # Create event loop and run pipeline
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)

    try:
        result = loop.run_until_complete(_run_pipeline(job_id, shop_url))
        logger.info(f"Onboarding task completed for job {job_id}: {result}")
        return result
    except Exception as exc:
        logger.exception(f"Onboarding task failed for job {job_id}: {exc}")
        # Retry with exponential backoff
        raise self.retry(exc=exc) from None
    finally:
        loop.close()


async def _run_pipeline(job_id: str, shop_url: str) -> dict:
    """Run the async pipeline with all infrastructure components.

    Args:
        job_id: Unique job identifier
        shop_url: Merchant shop URL to onboard

    Returns:
        Pipeline result dict
    """
    # Initialize Redis client
    redis_client = redis.from_url(settings.redis_url, decode_responses=False)

    # Initialize database client
    db_client = DatabaseClient(settings.database_url)
    await db_client.connect()

    try:
        # Initialize infrastructure components
        progress_tracker = ProgressTracker(redis_client)
        circuit_breaker = CircuitBreaker(
            threshold=settings.circuit_breaker_threshold,
            timeout=settings.circuit_breaker_timeout,
        )
        rate_limiter = RateLimiter(max_concurrent=5)

        # Initialize bulk ingestor
        bulk_ingestor = BulkIngestor(db_client)

        # Create pipeline instance
        pipeline = Pipeline(
            progress_tracker=progress_tracker,
            circuit_breaker=circuit_breaker,
            rate_limiter=rate_limiter,
            bulk_ingestor=bulk_ingestor,
        )

        # Run pipeline
        result = await pipeline.run(job_id, shop_url)

        return result

    finally:
        # Clean up resources
        await db_client.close()
        await redis_client.aclose()
