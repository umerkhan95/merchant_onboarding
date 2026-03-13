"""Onboarding API routes for merchant store processing."""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import TYPE_CHECKING, Any

import redis.asyncio
from fastapi import APIRouter, Depends, Request
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_db, get_redis, limiter, require_api_key
from app.config import settings
from app.exceptions.errors import NotFoundError
from app.infra.progress_tracker import ProgressTracker
from app.models.enums import JobStatus
from app.models.job import JobProgress, OnboardingRequest, OnboardingResponse
from app.security.url_validator import URLValidator

if TYPE_CHECKING:
    from app.db.supabase_client import DatabaseClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboard", tags=["onboarding"])


async def _run_pipeline_direct(
    job_id: str,
    shop_url: str,
    redis_client: redis.asyncio.Redis,
    db: DatabaseClient | None,
    max_urls: int | None = None,
) -> None:
    """Run the pipeline directly (no Celery) as an async background task."""
    from app.config import settings
    from app.db.bulk_ingestor import BulkIngestor
    from app.extractors.llm_extractor import LLMExtractor
    from app.extractors.schema_cache import SchemaCache
    from app.extractors.smart_css_extractor import SmartCSSExtractor
    from app.infra.circuit_breaker import CircuitBreaker
    from app.infra.rate_limiter import RateLimiter
    from app.services.pipeline import Pipeline

    tracker = ProgressTracker(redis_client)
    circuit_breaker = CircuitBreaker()
    rate_limiter = RateLimiter()
    ingestor = BulkIngestor(db) if db is not None else None

    # Initialize OAuth store if encryption key is configured
    oauth_store = None
    if settings.oauth_encryption_key and db is not None:
        from app.db.oauth_store import OAuthStore
        oauth_store = OAuthStore(db)

    # Initialize merchant profile ingestor
    profile_ingestor = None
    if db is not None:
        from app.db.merchant_profile_ingestor import MerchantProfileIngestor
        profile_ingestor = MerchantProfileIngestor(db)

    # Initialize LLM-powered extractors (Tiers 4-5) if API key is configured
    smart_css_extractor = None
    llm_extractor = None
    llm_config = settings.create_llm_config()
    if llm_config:
        schema_cache = SchemaCache(redis_client=redis_client, ttl=settings.schema_cache_ttl)
        smart_css_extractor = SmartCSSExtractor(llm_config=llm_config, schema_cache=schema_cache)
        llm_extractor = LLMExtractor(
            llm_config=llm_config,
            temperature=settings.llm_temperature,
            max_tokens=settings.llm_max_tokens,
        )

    pipeline = Pipeline(
        progress_tracker=tracker,
        circuit_breaker=circuit_breaker,
        rate_limiter=rate_limiter,
        bulk_ingestor=ingestor,
        smart_css_extractor=smart_css_extractor,
        llm_extractor=llm_extractor,
        oauth_store=oauth_store,
        profile_ingestor=profile_ingestor,
    )

    try:
        await pipeline.run(job_id=job_id, shop_url=shop_url, max_urls=max_urls)
    except Exception:
        logger.exception("Direct pipeline failed for job %s", job_id)


@router.post("", status_code=202, response_model=OnboardingResponse, dependencies=[require_api_key])
@limiter.limit(settings.rate_limit_onboard)
async def create_onboarding_job(
    request: Request,
    body: OnboardingRequest,
    redis: redis.asyncio.Redis = Depends(get_redis),
    db: DatabaseClient | None = Depends(get_db),
) -> OnboardingResponse:
    """Accept a shop URL and queue an onboarding job.

    Returns 202 Accepted with a job_id for tracking progress.
    Validates the URL against SSRF before dispatching.
    """
    # SSRF validation: resolve hostname and check for private IPs / DNS rebinding
    await URLValidator.validate_or_raise_async(str(body.url))

    job_id = f"job_{uuid.uuid4().hex[:12]}"

    tracker = ProgressTracker(redis)

    await tracker.update(
        job_id=job_id,
        processed=0,
        total=0,
        status=JobStatus.QUEUED,
        current_step="Job queued for processing",
    )
    await tracker.set_metadata(job_id, shop_url=str(body.url))

    # Try Celery first, fall back to direct execution
    dispatched = False
    try:
        from app.workers.tasks import run_onboarding_pipeline

        run_onboarding_pipeline.delay(job_id=job_id, shop_url=str(body.url), max_urls=body.max_urls)
        dispatched = True
        logger.info("Job %s dispatched to Celery", job_id)
    except Exception:
        logger.info("Celery unavailable, running pipeline directly for job %s", job_id)

    if not dispatched:
        asyncio.create_task(_run_pipeline_direct(job_id, str(body.url), redis, db, max_urls=body.max_urls))

    return OnboardingResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        progress_url=f"/api/v1/onboard/{job_id}/progress",
    )


@router.get("/{job_id}", response_model=JobProgress, dependencies=[require_api_key])
@limiter.limit(settings.rate_limit_default)
async def get_job_status(
    request: Request,
    job_id: str,
    redis: redis.asyncio.Redis = Depends(get_redis),
) -> JobProgress:
    """Get current job status and progress."""
    tracker = ProgressTracker(redis)
    progress_data = await tracker.get(job_id)

    if progress_data is None:
        raise NotFoundError(f"Job {job_id} not found")

    progress_data["job_id"] = job_id
    return JobProgress(**progress_data)


@router.get("/{job_id}/progress", dependencies=[require_api_key])
@limiter.limit(settings.rate_limit_default)
async def stream_progress(
    request: Request,
    job_id: str,
    redis: redis.asyncio.Redis = Depends(get_redis),
) -> EventSourceResponse:
    """SSE endpoint for real-time progress updates."""

    max_sse_seconds = 600  # 10 minutes max

    async def event_generator() -> Any:
        tracker = ProgressTracker(redis)
        start = time.monotonic()

        while time.monotonic() - start < max_sse_seconds:
            progress_data = await tracker.get(job_id)

            if progress_data is None:
                yield {
                    "event": "error",
                    "data": '{"error": "Job not found"}',
                }
                break

            progress_data["job_id"] = job_id
            progress = JobProgress(**progress_data)

            yield {
                "event": "progress",
                "data": progress.model_dump_json(),
            }

            if progress.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                yield {
                    "event": "done",
                    "data": progress.model_dump_json(),
                }
                break

            await asyncio.sleep(1)
        else:
            yield {
                "event": "timeout",
                "data": '{"error": "SSE stream timed out after 10 minutes"}',
            }

    return EventSourceResponse(event_generator())
