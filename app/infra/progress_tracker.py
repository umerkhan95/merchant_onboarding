from __future__ import annotations

from typing import Any

import redis.asyncio as redis


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
        self.ttl_seconds = 86400  # 24 hours

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
            if field_str in ("processed", "total"):
                result[field_str] = int(value_str)
            elif field_str == "percentage":
                result[field_str] = float(value_str)
            else:
                result[field_str] = value_str

        return result

    async def delete(self, job_id: str) -> None:
        """Delete job progress from Redis.

        Args:
            job_id: Unique job identifier
        """
        key = self._get_key(job_id)
        await self.redis.delete(key)
