from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

import redis.asyncio as redis

# Jobs stuck in these states for longer than STALE_TIMEOUT are marked failed
_TERMINAL_STATES = {"completed", "failed"}
_STALE_TIMEOUT_SECONDS = 30 * 60  # 30 minutes


class ProgressTracker:
    """Track job progress in Redis.

    Stores progress information as Redis hashes with TTL for temporary storage.
    """

    def __init__(self, redis_client: redis.Redis) -> None:
        """Initialize progress tracker.

        Args:
            redis_client: Async Redis client instance
        """
        self.redis = redis_client
        self.ttl_seconds = 604800  # 7 days

    def _get_key(self, job_id: str) -> str:
        """Get Redis key for job progress.

        Args:
            job_id: Unique job identifier

        Returns:
            Redis key for the job
        """
        return f"progress:{job_id}"

    async def update(
        self,
        job_id: str,
        processed: int,
        total: int,
        status: str,
        current_step: str,
        error: str | None = None,
    ) -> None:
        """Update job progress in Redis.

        Args:
            job_id: Unique job identifier
            processed: Number of items processed so far
            total: Total number of items to process
            status: Current job status (e.g., "processing", "completed", "failed")
            current_step: Description of current processing step
            error: Error message if status is "failed" (optional)

        Example:
            await tracker.update(
                job_id="job-123",
                processed=50,
                total=100,
                status="processing",
                current_step="Extracting product data",
            )
        """
        key = self._get_key(job_id)

        # Calculate progress percentage
        percentage = (processed / total * 100) if total > 0 else 0

        # Build progress data
        progress_data: dict[str, str | int | float] = {
            "processed": processed,
            "total": total,
            "percentage": round(percentage, 2),
            "status": status,
            "current_step": current_step,
        }

        if error is not None:
            progress_data["error"] = error

        # Store as Redis hash
        await self.redis.hset(key, mapping=progress_data)  # type: ignore

        # Set TTL
        await self.redis.expire(key, self.ttl_seconds)

    async def get(self, job_id: str) -> dict[str, Any] | None:
        """Retrieve job progress from Redis.

        Args:
            job_id: Unique job identifier

        Returns:
            Dict with progress data or None if not found

        Example:
            progress = await tracker.get("job-123")
            if progress:
                print(f"Progress: {progress['percentage']}%")
        """
        key = self._get_key(job_id)

        # Get all hash fields
        data = await self.redis.hgetall(key)

        if not data:
            return None

        # Convert bytes to strings and parse numeric values
        result: dict[str, Any] = {}
        for field, value in data.items():
            field_str = field.decode() if isinstance(field, bytes) else field
            value_str = value.decode() if isinstance(value, bytes) else value

            # Parse numeric fields
            if field_str in ("processed", "total", "products_count"):
                try:
                    result[field_str] = int(value_str)
                except (ValueError, TypeError):
                    result[field_str] = 0
            elif field_str in ("percentage", "coverage_percentage"):
                try:
                    result[field_str] = float(value_str)
                except (ValueError, TypeError):
                    result[field_str] = 0.0
            elif field_str in ("recent_products", "extraction_audit", "reconciliation_report"):
                try:
                    result[field_str] = json.loads(value_str)
                except (json.JSONDecodeError, TypeError):
                    result[field_str] = None
            else:
                result[field_str] = value_str

        return result

    async def set_metadata(self, job_id: str, **fields: str | int | float) -> None:
        """Store persistent metadata fields on a job hash.

        Separate from update() so existing progress calls are untouched.

        Args:
            job_id: Unique job identifier
            **fields: Metadata key-value pairs (e.g. shop_url, platform, started_at)
        """
        if not fields:
            return
        key = self._get_key(job_id)
        await self.redis.hset(key, mapping=fields)  # type: ignore
        await self.redis.expire(key, self.ttl_seconds)

    async def list_all_jobs(self) -> list[dict[str, Any]]:
        """List all tracked jobs by scanning progress:* keys.

        Automatically marks stale jobs (stuck in non-terminal states
        for longer than 30 minutes) as failed before returning.

        Returns:
            List of job dicts (each includes job_id extracted from key)
        """
        jobs: list[dict[str, Any]] = []
        cursor: int = 0
        while True:
            cursor, keys = await self.redis.scan(cursor=cursor, match="progress:*", count=100)
            for key in keys:
                key_str = key.decode() if isinstance(key, bytes) else key
                job_id = key_str.removeprefix("progress:")
                data = await self.get(job_id)
                if data:
                    data["job_id"] = job_id
                    jobs.append(data)
            if cursor == 0:
                break

        # Mark stale jobs as failed
        now = datetime.now(timezone.utc)
        for job in jobs:
            status = job.get("status", "")
            if status in _TERMINAL_STATES:
                continue
            started = job.get("started_at")
            if not started:
                # No started_at means very old job — mark as failed
                await self._mark_stale(job["job_id"])
                job["status"] = "failed"
                job["error"] = "Stale: no start time recorded"
                continue
            try:
                started_dt = datetime.fromisoformat(started)
                if started_dt.tzinfo is None:
                    started_dt = started_dt.replace(tzinfo=timezone.utc)
                age = (now - started_dt).total_seconds()
                if age > _STALE_TIMEOUT_SECONDS:
                    await self._mark_stale(job["job_id"])
                    job["status"] = "failed"
                    job["error"] = f"Stale: stuck for {int(age // 60)} minutes"
            except (ValueError, TypeError):
                pass

        return jobs

    async def _mark_stale(self, job_id: str) -> None:
        """Mark a stale job as failed in Redis."""
        key = self._get_key(job_id)
        await self.redis.hset(key, mapping={  # type: ignore
            "status": "failed",
            "error": "Pipeline interrupted — job timed out",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        })

    async def delete(self, job_id: str) -> None:
        """Delete job progress from Redis.

        Args:
            job_id: Unique job identifier
        """
        key = self._get_key(job_id)
        await self.redis.delete(key)
