"""Analytics and job listing Pydantic models."""

from __future__ import annotations

from pydantic import BaseModel, Field


class JobSummary(BaseModel):
    """Summary of a single job for listing."""

    job_id: str
    shop_url: str | None = None
    platform: str | None = None
    status: str = ""
    extraction_tier: str | None = None
    products_count: int = 0
    started_at: str | None = None
    completed_at: str | None = None
    current_step: str = ""
    error: str | None = None


class JobListResponse(BaseModel):
    """Response for GET /api/v1/jobs."""

    jobs: list[JobSummary]
    total: int = Field(description="Total number of jobs")


class StatusCount(BaseModel):
    status: str
    count: int


class PlatformCount(BaseModel):
    platform: str
    count: int


class TierCount(BaseModel):
    tier: str
    count: int


class AnalyticsSummary(BaseModel):
    """Aggregated analytics response."""

    total_jobs: int = 0
    total_products: int = 0
    success_rate: float = Field(0.0, description="Percentage of completed jobs")
    avg_duration_seconds: float | None = Field(None, description="Average job duration in seconds")
    jobs_by_status: list[StatusCount] = []
    jobs_by_platform: list[PlatformCount] = []
    jobs_by_tier: list[TierCount] = []


class TierPerf(BaseModel):
    """Performance stats for a single extraction tier."""

    tier: str
    jobs: int
    avg_duration_seconds: float
    avg_products: float
    products_per_second: float


class CrawlJobPerf(BaseModel):
    """Performance of a single completed crawl job."""

    job_id: str
    shop_url: str
    platform: str
    tier: str
    products: int
    duration_seconds: float
    products_per_second: float


class CrawlerStats(BaseModel):
    """Crawler performance statistics."""

    by_tier: list[TierPerf] = []
    recent_crawls: list[CrawlJobPerf] = []
    total_crawl_time_seconds: float = 0.0
    avg_products_per_second: float = 0.0
