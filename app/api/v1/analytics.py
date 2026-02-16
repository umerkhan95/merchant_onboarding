"""Analytics and job listing endpoints."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

import redis.asyncio
from fastapi import APIRouter, Depends, Query

from app.api.deps import get_db, get_redis, require_api_key
from app.db.queries import COUNT_ALL_PRODUCTS
from app.infra.perf_tracker import PerfTracker
from app.infra.progress_tracker import ProgressTracker
from app.models.analytics import (
    AnalyticsSummary,
    CrawlJobPerf,
    CrawlerStats,
    JobListResponse,
    JobSummary,
    PlatformCount,
    StatusCount,
    TierCount,
    TierPerf,
)

if TYPE_CHECKING:
    from app.db.supabase_client import DatabaseClient

logger = logging.getLogger(__name__)

router = APIRouter(tags=["analytics"])


@router.get("/jobs", response_model=JobListResponse, dependencies=[require_api_key])
async def list_jobs(
    status: str | None = Query(None, description="Filter by job status"),
    redis_client: redis.asyncio.Redis = Depends(get_redis),
) -> JobListResponse:
    """List all tracked jobs, sorted by started_at descending."""
    tracker = ProgressTracker(redis_client)
    all_jobs = await tracker.list_all_jobs()

    summaries = [
        JobSummary(
            job_id=j.get("job_id", ""),
            shop_url=j.get("shop_url"),
            platform=j.get("platform"),
            status=j.get("status", ""),
            extraction_tier=j.get("extraction_tier"),
            products_count=j.get("products_count", 0) if isinstance(j.get("products_count"), int) else 0,
            started_at=j.get("started_at"),
            completed_at=j.get("completed_at"),
            current_step=j.get("current_step", ""),
            error=j.get("error"),
        )
        for j in all_jobs
    ]

    if status:
        summaries = [s for s in summaries if s.status == status]

    # Sort by started_at descending (None values last)
    summaries.sort(key=lambda s: s.started_at or "", reverse=True)

    return JobListResponse(jobs=summaries, total=len(summaries))


@router.get("/analytics", response_model=AnalyticsSummary, dependencies=[require_api_key])
async def get_analytics(
    redis_client: redis.asyncio.Redis = Depends(get_redis),
    db: DatabaseClient | None = Depends(get_db),
) -> AnalyticsSummary:
    """Aggregate analytics from all tracked jobs."""
    tracker = ProgressTracker(redis_client)
    all_jobs = await tracker.list_all_jobs()

    total_jobs = len(all_jobs)
    if total_jobs == 0:
        return AnalyticsSummary()

    total_products = 0
    completed_count = 0
    durations: list[float] = []
    status_counts: dict[str, int] = {}
    platform_counts: dict[str, int] = {}
    tier_counts: dict[str, int] = {}

    for j in all_jobs:
        # Products
        pc = j.get("products_count", 0)
        total_products += pc if isinstance(pc, int) else 0

        # Status
        st = j.get("status", "unknown")
        status_counts[st] = status_counts.get(st, 0) + 1
        if st == "completed":
            completed_count += 1

        # Platform
        plat = j.get("platform")
        if plat:
            platform_counts[plat] = platform_counts.get(plat, 0) + 1

        # Tier
        tier = j.get("extraction_tier")
        if tier:
            tier_counts[tier] = tier_counts.get(tier, 0) + 1

        # Duration
        started = j.get("started_at")
        ended = j.get("completed_at")
        if started and ended:
            try:
                t0 = datetime.fromisoformat(started)
                t1 = datetime.fromisoformat(ended)
                durations.append((t1 - t0).total_seconds())
            except (ValueError, TypeError):
                pass

    # Override total_products with real DB count if available
    if db is not None:
        try:
            async with db.pool.acquire() as conn:
                db_count = await conn.fetchval(COUNT_ALL_PRODUCTS)
            if db_count is not None:
                total_products = db_count
        except Exception:
            logger.warning("Failed to query DB product count, using Redis estimate")

    success_rate = round((completed_count / total_jobs) * 100, 1) if total_jobs else 0.0
    avg_duration = round(sum(durations) / len(durations), 1) if durations else None

    return AnalyticsSummary(
        total_jobs=total_jobs,
        total_products=total_products,
        success_rate=success_rate,
        avg_duration_seconds=avg_duration,
        jobs_by_status=[StatusCount(status=k, count=v) for k, v in status_counts.items()],
        jobs_by_platform=[PlatformCount(platform=k, count=v) for k, v in platform_counts.items()],
        jobs_by_tier=[TierCount(tier=k, count=v) for k, v in tier_counts.items()],
    )


@router.get("/performance", dependencies=[require_api_key])
async def get_performance(
    redis_client: redis.asyncio.Redis = Depends(get_redis),
) -> dict:
    """Get API request performance metrics (latency, throughput, errors)."""
    tracker = PerfTracker(redis_client)
    return await tracker.get_stats()


@router.get("/crawler-stats", response_model=CrawlerStats, dependencies=[require_api_key])
async def get_crawler_stats(
    redis_client: redis.asyncio.Redis = Depends(get_redis),
) -> CrawlerStats:
    """Get crawler/extraction performance statistics."""
    tracker = ProgressTracker(redis_client)
    all_jobs = await tracker.list_all_jobs()

    # Only completed jobs with timing data
    completed_jobs: list[dict] = []
    for j in all_jobs:
        started = j.get("started_at")
        ended = j.get("completed_at")
        if j.get("status") == "completed" and started and ended:
            try:
                t0 = datetime.fromisoformat(started)
                t1 = datetime.fromisoformat(ended)
                duration = (t1 - t0).total_seconds()
                if duration > 0:
                    j["_duration"] = duration
                    completed_jobs.append(j)
            except (ValueError, TypeError):
                pass

    if not completed_jobs:
        return CrawlerStats()

    # Aggregate by tier
    tier_data: dict[str, dict] = {}
    total_crawl_time = 0.0
    total_products_all = 0

    for j in completed_jobs:
        tier = j.get("extraction_tier", "unknown")
        duration = j["_duration"]
        products = j.get("products_count", 0) if isinstance(j.get("products_count"), int) else 0
        total_crawl_time += duration
        total_products_all += products

        if tier not in tier_data:
            tier_data[tier] = {"durations": [], "products": []}
        tier_data[tier]["durations"].append(duration)
        tier_data[tier]["products"].append(products)

    by_tier = []
    for tier, data in tier_data.items():
        avg_dur = sum(data["durations"]) / len(data["durations"])
        avg_prod = sum(data["products"]) / len(data["products"])
        pps = sum(data["products"]) / sum(data["durations"]) if sum(data["durations"]) > 0 else 0
        by_tier.append(TierPerf(
            tier=tier,
            jobs=len(data["durations"]),
            avg_duration_seconds=round(avg_dur, 1),
            avg_products=round(avg_prod, 1),
            products_per_second=round(pps, 2),
        ))
    by_tier.sort(key=lambda t: t.products_per_second, reverse=True)

    # Recent crawls (last 10 by completion time)
    completed_jobs.sort(
        key=lambda j: j.get("completed_at", ""),
        reverse=True,
    )
    recent = []
    for j in completed_jobs[:10]:
        products = j.get("products_count", 0) if isinstance(j.get("products_count"), int) else 0
        duration = j["_duration"]
        recent.append(CrawlJobPerf(
            job_id=j.get("job_id", ""),
            shop_url=j.get("shop_url", ""),
            platform=j.get("platform", "unknown"),
            tier=j.get("extraction_tier", "unknown"),
            products=products,
            duration_seconds=round(duration, 1),
            products_per_second=round(products / duration, 2) if duration > 0 else 0,
        ))

    avg_pps = total_products_all / total_crawl_time if total_crawl_time > 0 else 0

    return CrawlerStats(
        by_tier=by_tier,
        recent_crawls=recent,
        total_crawl_time_seconds=round(total_crawl_time, 1),
        avg_products_per_second=round(avg_pps, 2),
    )
