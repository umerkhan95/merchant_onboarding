"""Onboarding API routes for merchant store processing."""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import TYPE_CHECKING, Any

import redis.asyncio
from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_db, get_redis, require_api_key
from app.exceptions.errors import NotFoundError
from app.infra.progress_tracker import ProgressTracker
from app.models.enums import JobStatus
from app.models.job import JobProgress, OnboardingRequest, OnboardingResponse

if TYPE_CHECKING:
    from app.db.supabase_client import DatabaseClient

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/onboard", tags=["onboarding"])


async def _run_pipeline_direct(
    job_id: str,
    shop_url: str,
    redis_client: redis.asyncio.Redis,
    db: DatabaseClient | None,
) -> None:
    """Run the pipeline directly (no Celery) as an async background task."""
    from app.db.bulk_ingestor import BulkIngestor
    from app.infra.circuit_breaker import CircuitBreaker
    from app.infra.rate_limiter import RateLimiter
    from app.services.pipeline import Pipeline

    tracker = ProgressTracker(redis_client)
    circuit_breaker = CircuitBreaker()
    rate_limiter = RateLimiter()
    ingestor = BulkIngestor(db) if db is not None else None

    pipeline = Pipeline(
        progress_tracker=tracker,
        circuit_breaker=circuit_breaker,
        rate_limiter=rate_limiter,
        bulk_ingestor=ingestor,
    )

    try:
        await pipeline.run(job_id=job_id, shop_url=shop_url)
    except Exception:
        logger.exception("Direct pipeline failed for job %s", job_id)


@router.post("", status_code=202, response_model=OnboardingResponse, dependencies=[require_api_key])
async def create_onboarding_job(
    request: OnboardingRequest,
    redis: redis.asyncio.Redis = Depends(get_redis),
    db: DatabaseClient | None = Depends(get_db),
) -> OnboardingResponse:
    """Accept a shop URL and queue an onboarding job.

    Returns 202 Accepted with a job_id for tracking progress.
    """
    job_id = f"job_{uuid.uuid4().hex[:12]}"

    tracker = ProgressTracker(redis)

    await tracker.update(
        job_id=job_id,
        processed=0,
        total=0,
        status=JobStatus.QUEUED,
        current_step="Job queued for processing",
    )
    await tracker.set_metadata(job_id, shop_url=str(request.url))

    # Try Celery first, fall back to direct execution
    dispatched = False
    try:
        from app.workers.tasks import run_onboarding_pipeline

        run_onboarding_pipeline.delay(job_id=job_id, url=str(request.url))
        dispatched = True
        logger.info("Job %s dispatched to Celery", job_id)
    except Exception:
        logger.info("Celery unavailable, running pipeline directly for job %s", job_id)

    if not dispatched:
        asyncio.create_task(_run_pipeline_direct(job_id, str(request.url), redis, db))

    return OnboardingResponse(
        job_id=job_id,
        status=JobStatus.QUEUED,
        progress_url=f"/api/v1/onboard/{job_id}/progress",
    )


@router.get("/{job_id}", response_model=JobProgress, dependencies=[require_api_key])
async def get_job_status(
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
async def stream_progress(
    job_id: str,
    redis: redis.asyncio.Redis = Depends(get_redis),
) -> EventSourceResponse:
    """SSE endpoint for real-time progress updates."""

    async def event_generator() -> Any:
        tracker = ProgressTracker(redis)

        while True:
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

    return EventSourceResponse(event_generator())
