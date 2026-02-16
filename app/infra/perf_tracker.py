from __future__ import annotations

import json
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import redis.asyncio


class PerfTracker:
    """Redis-backed performance tracker for API request metrics."""

    REQUESTS_KEY = "perf:requests"
    STARTED_AT_KEY = "perf:started_at"
    TTL_SECONDS = 3600  # 1 hour

    def __init__(self, redis_client: redis.asyncio.Redis):
        self.redis = redis_client

    async def record(
        self,
        endpoint: str,
        method: str,
        status_code: int,
        latency_ms: float,
    ) -> None:
        """Record a request metric to Redis sorted set."""
        now = time.time()

        # Initialize started_at if not exists
        await self.redis.setnx(self.STARTED_AT_KEY, int(now))

        # Create metric entry
        metric = {
            "endpoint": endpoint,
            "method": method,
            "status_code": status_code,
            "latency_ms": latency_ms,
            "ts": now,
        }

        # Add to sorted set (score = timestamp)
        await self.redis.zadd(
            self.REQUESTS_KEY,
            {json.dumps(metric): now}
        )

        # Set TTL on the sorted set
        await self.redis.expire(self.REQUESTS_KEY, self.TTL_SECONDS)

    async def get_stats(self) -> dict:
        """Get aggregated performance statistics."""
        # Cleanup old entries first
        await self.cleanup()

        # Get all metrics from the last hour
        now = time.time()
        one_hour_ago = now - self.TTL_SECONDS

        entries = await self.redis.zrangebyscore(
            self.REQUESTS_KEY,
            one_hour_ago,
            now
        )

        if not entries:
            return {
                "total_requests": 0,
                "requests_per_minute": 0.0,
                "error_rate": 0.0,
                "p50_ms": 0.0,
                "p95_ms": 0.0,
                "p99_ms": 0.0,
                "uptime_seconds": 0,
                "endpoints": [],
            }

        # Parse metrics
        metrics = [json.loads(entry) for entry in entries]
        total_requests = len(metrics)

        # Calculate error rate (4xx and 5xx)
        errors = sum(1 for m in metrics if m["status_code"] >= 400)
        error_rate = errors / total_requests if total_requests > 0 else 0.0

        # Calculate latency percentiles
        latencies = sorted(m["latency_ms"] for m in metrics)
        p50_ms = self._percentile(latencies, 50)
        p95_ms = self._percentile(latencies, 95)
        p99_ms = self._percentile(latencies, 99)

        # Calculate requests per minute
        if metrics:
            oldest_ts = min(m["ts"] for m in metrics)
            newest_ts = max(m["ts"] for m in metrics)
            time_span_minutes = (newest_ts - oldest_ts) / 60.0
            requests_per_minute = total_requests / time_span_minutes if time_span_minutes > 0 else 0.0
        else:
            requests_per_minute = 0.0

        # Calculate uptime
        started_at_str = await self.redis.get(self.STARTED_AT_KEY)
        if started_at_str:
            started_at = float(started_at_str)
            uptime_seconds = int(now - started_at)
        else:
            uptime_seconds = 0

        # Aggregate endpoint stats
        endpoint_stats = {}
        for m in metrics:
            key = f"{m['method']} {m['endpoint']}"
            if key not in endpoint_stats:
                endpoint_stats[key] = {
                    "endpoint": m["endpoint"],
                    "method": m["method"],
                    "count": 0,
                    "latencies": [],
                }
            endpoint_stats[key]["count"] += 1
            endpoint_stats[key]["latencies"].append(m["latency_ms"])

        # Calculate per-endpoint metrics
        endpoints = []
        for key, stats in endpoint_stats.items():
            latencies = sorted(stats["latencies"])
            endpoints.append({
                "endpoint": stats["endpoint"],
                "method": stats["method"],
                "count": stats["count"],
                "avg_ms": sum(latencies) / len(latencies),
                "p95_ms": self._percentile(latencies, 95),
            })

        # Sort by count and take top 10
        endpoints.sort(key=lambda x: x["count"], reverse=True)
        endpoints = endpoints[:10]

        return {
            "total_requests": total_requests,
            "requests_per_minute": round(requests_per_minute, 2),
            "error_rate": round(error_rate * 100, 2),
            "p50_ms": round(p50_ms, 2),
            "p95_ms": round(p95_ms, 2),
            "p99_ms": round(p99_ms, 2),
            "uptime_seconds": uptime_seconds,
            "endpoints": endpoints,
        }

    async def cleanup(self) -> None:
        """Remove entries older than 1 hour."""
        now = time.time()
        one_hour_ago = now - self.TTL_SECONDS

        await self.redis.zremrangebyscore(
            self.REQUESTS_KEY,
            "-inf",
            one_hour_ago
        )

    @staticmethod
    def _percentile(sorted_values: list[float], percentile: int) -> float:
        """Calculate percentile from sorted values."""
        if not sorted_values:
            return 0.0

        if len(sorted_values) == 1:
            return sorted_values[0]

        # Use nearest-rank method
        rank = (percentile / 100.0) * (len(sorted_values) - 1)
        lower = int(rank)
        upper = lower + 1

        if upper >= len(sorted_values):
            return sorted_values[-1]

        # Linear interpolation
        weight = rank - lower
        return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight
