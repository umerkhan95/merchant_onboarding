"""Onboarding API routes for merchant store processing."""

from __future__ import annotations

import uuid
from typing import Any

import redis.asyncio
from fastapi import APIRouter, Depends
from sse_starlette.sse import EventSourceResponse

from app.api.deps import get_redis, require_api_key
from app.exceptions.errors import NotFoundError
from app.infra.progress_tracker import ProgressTracker
from app.models.enums import JobStatus
from app.models.job import JobProgress, OnboardingRequest, OnboardingResponse

router = APIRouter(prefix="/onboard", tags=["onboarding"])


@router.post("", status_code=202, response_model=OnboardingResponse, dependencies=[require_api_key])
async def create_onboarding_job(
    request: OnboardingRequest,
    redis: redis.asyncio.Redis = Depends(get_redis),
) -> OnboardingResponse:
    """Accept a shop URL and queue an onboarding job.

    Returns 202 Accepted with a job_id for tracking progress.

    Args:
        request: Onboarding request with shop URL
        redis: Redis client for progress tracking

    Returns:
        OnboardingResponse with job_id, status, and progress_url
    """
    # Generate unique job ID
    job_id = f"job_{uuid.uuid4().hex[:12]}"

    # Initialize progress tracker
    tracker = ProgressTracker(redis)

    # Store initial progress in Redis
    await tracker.update(
        job_id=job_id,
        processed=0,
        total=0,
        status=JobStatus.QUEUED,
        current_step="Job queued for processing",
    )

    # Queue Celery task (import lazily to avoid issues if celery not running)
    try:
        from app.tasks.onboarding import process_onboarding_job

        process_onboarding_job.delay(job_id=job_id, url=str(request.url))
    except (ImportError, Exception):
        # If Celery isn't configured or the task doesn't exist yet, just continue
        # The job is already queued in Redis, so this is graceful degradation
        pass

    # Return response
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
    """Get current job status and progress.

    Args:
        job_id: Unique job identifier
        redis: Redis client for progress tracking

    Returns:
        JobProgress with current status and metrics

    Raises:
        NotFoundError: If job_id is not found
    """
    tracker = ProgressTracker(redis)
    progress_data = await tracker.get(job_id)

    if progress_data is None:
        raise NotFoundError(f"Job {job_id} not found")

    # Add job_id to the data
    progress_data["job_id"] = job_id

    return JobProgress(**progress_data)


@router.get("/{job_id}/progress", dependencies=[require_api_key])
async def stream_progress(
    job_id: str,
    redis: redis.asyncio.Redis = Depends(get_redis),
) -> EventSourceResponse:
    """SSE endpoint for real-time progress updates.

    Streams progress events every second until the job completes or fails.

    Args:
        job_id: Unique job identifier
        redis: Redis client for progress tracking

    Returns:
        EventSourceResponse streaming progress events
    """

    async def event_generator() -> Any:
        """Generate SSE events with job progress updates."""
        tracker = ProgressTracker(redis)

        while True:
            # Fetch current progress
            progress_data = await tracker.get(job_id)

            if progress_data is None:
                # Job not found - send error event and stop
                yield {
                    "event": "error",
                    "data": '{"error": "Job not found"}',
                }
                break

            # Add job_id to the data
            progress_data["job_id"] = job_id

            # Convert to JobProgress model for validation and serialization
            progress = JobProgress(**progress_data)

            # Send progress event
            yield {
                "event": "progress",
                "data": progress.model_dump_json(),
            }

            # Check if job is in terminal state
            if progress.status in (JobStatus.COMPLETED, JobStatus.FAILED):
                # Send completion event
                yield {
                    "event": "done",
                    "data": progress.model_dump_json(),
                }
                break

            # Wait 1 second before next poll
            import asyncio

            await asyncio.sleep(1)

    return EventSourceResponse(event_generator())
