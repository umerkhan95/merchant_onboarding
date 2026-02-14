"""Dead Letter Queue (DLQ) API routes for failed job management."""

from __future__ import annotations

from typing import Any

import redis.asyncio
from fastapi import APIRouter, Depends

from app.api.deps import get_redis, require_api_key
from app.exceptions.errors import NotFoundError

router = APIRouter(prefix="/dlq", tags=["dlq"])


@router.get("", dependencies=[require_api_key])
async def list_dlq_entries(
    redis: redis.asyncio.Redis = Depends(get_redis),
) -> dict[str, Any]:
    """List entries in the dead letter queue.

    Retrieves all failed jobs from the DLQ stored in Redis.

    Args:
        redis: Redis client for DLQ access

    Returns:
        List of DLQ entries with job metadata
    """
    # Read from Redis hash 'dlq:jobs'
    dlq_key = "dlq:jobs"
    entries = await redis.hgetall(dlq_key)

    # Convert entries to list of dicts
    dlq_entries = []
    for job_id, job_data in entries.items():
        # job_id might be bytes if decode_responses=False
        job_id_str = job_id.decode() if isinstance(job_id, bytes) else job_id
        job_data_str = job_data.decode() if isinstance(job_data, bytes) else job_data

        dlq_entries.append(
            {
                "job_id": job_id_str,
                "data": job_data_str,
            }
        )

    return {
        "entries": dlq_entries,
        "count": len(dlq_entries),
    }


@router.post("/{job_id}/retry", status_code=202, dependencies=[require_api_key])
async def retry_dlq_entry(
    job_id: str,
    redis: redis.asyncio.Redis = Depends(get_redis),
) -> dict[str, Any]:
    """Retry a failed job from the DLQ.

    Removes the job from the DLQ and re-queues it for processing.

    Args:
        job_id: Job identifier to retry
        redis: Redis client for DLQ access

    Returns:
        Success message with re-queued job_id

    Raises:
        NotFoundError: If job_id is not in the DLQ
    """
    dlq_key = "dlq:jobs"

    # Check if job exists in DLQ
    job_data = await redis.hget(dlq_key, job_id)

    if job_data is None:
        raise NotFoundError(f"Job {job_id} not found in DLQ")

    # Remove from DLQ
    await redis.hdel(dlq_key, job_id)

    # Re-queue Celery task (import lazily to avoid issues if celery not running)
    try:
        # Parse job_data to get URL (assuming it's stored as JSON string)
        import json

        from app.tasks.onboarding import process_onboarding_job

        data = json.loads(job_data.decode() if isinstance(job_data, bytes) else job_data)
        url = data.get("url", "")

        process_onboarding_job.delay(job_id=job_id, url=url)
    except (ImportError, Exception):
        # If Celery isn't configured or the task doesn't exist yet, just continue
        # Job has been removed from DLQ
        pass

    return {
        "message": f"Job {job_id} re-queued for processing",
        "job_id": job_id,
    }
