"""Celery task definitions for merchant onboarding pipeline."""

from __future__ import annotations

import asyncio
import json
import logging

import redis.asyncio as redis

from app.config import settings
from app.db.bulk_ingestor import BulkIngestor
from app.db.merchant_profile_ingestor import MerchantProfileIngestor
from app.db.supabase_client import DatabaseClient
from app.infra.circuit_breaker import CircuitBreaker
from app.infra.progress_tracker import ProgressTracker
from app.infra.rate_limiter import RateLimiter
from app.security.url_validator import URLValidator
from app.services.pipeline import Pipeline
from app.workers.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(bind=True, max_retries=3, retry_backoff=True)
def run_onboarding_pipeline(self, job_id: str, shop_url: str, max_urls: int | None = None, feed_url: str | None = None) -> dict:
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
        result = loop.run_until_complete(_run_pipeline(job_id, shop_url, max_urls=max_urls, feed_url=feed_url))
        logger.info(f"Onboarding task completed for job {job_id}: {result}")
        return result
    except Exception as exc:
        logger.exception(f"Onboarding task failed for job {job_id}: {exc}")
        # Write to DLQ when all retries are exhausted
        if self.request.retries >= self.max_retries:
            loop.run_until_complete(
                _write_to_dlq(shop_url, str(exc))
            )
        # Retry with exponential backoff
        raise self.retry(exc=exc) from None
    finally:
        loop.close()


async def _write_to_dlq(url: str, error: str) -> None:
    """Write a failed job to the dead letter queue with TTL."""
    import uuid

    redis_client = redis.from_url(settings.redis_url, decode_responses=False)
    try:
        dlq_key = "dlq:jobs"
        job_id = str(uuid.uuid4())
        entry = json.dumps({"url": url, "error": error})
        await redis_client.hset(dlq_key, job_id, entry)
        await redis_client.expire(dlq_key, settings.dlq_ttl_seconds)
    except Exception as e:
        logger.warning("Failed to write DLQ entry: %s", e)
    finally:
        await redis_client.aclose()


async def _run_pipeline(job_id: str, shop_url: str, max_urls: int | None = None, feed_url: str | None = None) -> dict:
    """Run the async pipeline with all infrastructure components.

    Args:
        job_id: Unique job identifier
        shop_url: Merchant shop URL to onboard

    Returns:
        Pipeline result dict

    Raises:
        SSRFError: If the shop URL fails SSRF validation.
    """
    # SSRF validation: defense-in-depth check even if the API layer already validated.
    # Celery tasks can be invoked directly (bypassing the API), so we validate here too.
    URLValidator.validate_or_raise(shop_url)

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

        # Initialize merchant profile ingestor
        profile_ingestor = MerchantProfileIngestor(db_client)

        # Initialize OAuth store if encryption key is configured
        oauth_store = None
        if settings.oauth_encryption_key:
            from app.db.oauth_store import OAuthStore
            oauth_store = OAuthStore(db_client)

        # Initialize LLM-powered extractors (Tiers 4-5) if API key is configured
        smart_css_extractor = None
        llm_extractor = None
        llm_config = settings.create_llm_config()
        if llm_config:
            from app.extractors.schema_cache import SchemaCache
            from app.extractors.smart_css_extractor import SmartCSSExtractor
            from app.extractors.llm_extractor import LLMExtractor

            schema_cache = SchemaCache(redis_client=redis_client, ttl=settings.schema_cache_ttl)
            smart_css_extractor = SmartCSSExtractor(llm_config=llm_config, schema_cache=schema_cache)
            llm_extractor = LLMExtractor(
                llm_config=llm_config,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
            )

        # Initialize LLM budget tracker when LLM extractors are active
        llm_budget = None
        if llm_config:
            from app.infra.llm_budget import LLMBudgetTracker

            llm_budget = LLMBudgetTracker(max_budget=settings.llm_budget_max)

        # Create pipeline instance
        pipeline = Pipeline(
            progress_tracker=progress_tracker,
            circuit_breaker=circuit_breaker,
            rate_limiter=rate_limiter,
            bulk_ingestor=bulk_ingestor,
            smart_css_extractor=smart_css_extractor,
            llm_extractor=llm_extractor,
            llm_budget=llm_budget,
            profile_ingestor=profile_ingestor,
            oauth_store=oauth_store,
        )

        # Run pipeline
        result = await pipeline.run(job_id, shop_url, max_urls=max_urls, feed_url=feed_url)

        return result

    finally:
        # Clean up resources
        await db_client.close()
        await redis_client.aclose()
