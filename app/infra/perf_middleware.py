from __future__ import annotations

import time

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.infra.perf_tracker import PerfTracker


class PerfMiddleware(BaseHTTPMiddleware):
    """Middleware to track API request performance metrics."""

    SKIP_PATHS = {"/health", "/readiness"}

    async def dispatch(self, request: Request, call_next) -> Response:
        # Record start time
        start_time = time.time()

        # Process request
        response = await call_next(request)

        # Calculate latency
        latency_ms = (time.time() - start_time) * 1000.0

        # Add response time header
        response.headers["X-Response-Time"] = f"{latency_ms:.2f}ms"

        # Skip tracking for health/readiness endpoints
        if request.url.path not in self.SKIP_PATHS:
            # Get Redis client from app state
            redis_client = getattr(request.app.state, "redis", None)

            if redis_client:
                # Record metrics
                tracker = PerfTracker(redis_client)
                await tracker.record(
                    endpoint=request.url.path,
                    method=request.method,
                    status_code=response.status_code,
                    latency_ms=latency_ms,
                )

        return response
