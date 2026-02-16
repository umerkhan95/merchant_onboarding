"""Job request and response Pydantic models."""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

from pydantic import BaseModel, Field, HttpUrl, field_validator

from app.models.enums import JobStatus


class OnboardingRequest(BaseModel):
    """Onboarding job creation request."""

    url: HttpUrl = Field(..., description="Store URL to onboard")

    @field_validator("url")
    @classmethod
    def validate_url_security(cls, v: HttpUrl) -> HttpUrl:
        """Validate URL is safe: reject private IPs and non-HTTP(S) schemes."""
        parsed = urlparse(str(v))

        # Validate scheme is HTTP or HTTPS (HttpUrl already enforces this, but double-check)
        if parsed.scheme not in ("http", "https"):
            raise ValueError(f"Only HTTP(S) URLs are allowed, got: {parsed.scheme}")

        # Extract hostname
        hostname = parsed.hostname
        if not hostname:
            raise ValueError("URL must contain a valid hostname")

        # Additional security: reject localhost domains (before IP check)
        localhost_patterns = ["localhost", "127.", "::1", "0.0.0.0"]
        if any(pattern in hostname.lower() for pattern in localhost_patterns):
            raise ValueError(f"Localhost addresses are not allowed: {hostname}")

        # Check if hostname is a private/reserved IP address
        try:
            ip = ipaddress.ip_address(hostname)
            # is_global returns False for private/reserved IPs
            if not ip.is_global:
                raise ValueError(
                    f"Private/reserved IP addresses are not allowed: {hostname}"
                )
        except ValueError as e:
            # If it's our custom ValueError about private IPs, re-raise it
            if "Private/reserved IP addresses are not allowed" in str(e):
                raise
            # Otherwise, it's not an IP address (likely a domain name), which is fine
            pass

        return v

    model_config = {
        "json_schema_extra": {
            "examples": [
                {"url": "https://example-store.myshopify.com"},
                {"url": "https://www.boutique-example.com"},
            ]
        }
    }


class OnboardingResponse(BaseModel):
    """Onboarding job creation response."""

    job_id: str = Field(..., description="Unique job identifier")
    status: JobStatus = Field(..., description="Current job status")
    progress_url: str = Field(..., description="URL to track job progress")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "job_123abc",
                    "status": "queued",
                    "progress_url": "/api/v1/jobs/job_123abc/progress",
                }
            ]
        }
    }


class JobProgress(BaseModel):
    """Job progress information."""

    job_id: str = Field(..., description="Unique job identifier")
    processed: int = Field(..., ge=0, description="Number of products processed")
    total: int = Field(..., ge=0, description="Total number of products")
    percentage: float = Field(..., ge=0.0, le=100.0, description="Progress percentage")
    status: JobStatus = Field(..., description="Current job status")
    current_step: str = Field(..., description="Current processing step description")
    error: str | None = Field(None, description="Error message if status is failed")
    shop_url: str | None = Field(None, description="Shop URL being processed")
    platform: str | None = Field(None, description="Detected platform")
    extraction_tier: str | None = Field(None, description="Extraction tier used")
    products_count: int | None = Field(None, description="Total products ingested")
    started_at: str | None = Field(None, description="ISO timestamp when job started")
    completed_at: str | None = Field(None, description="ISO timestamp when job completed")

    @field_validator("percentage", mode="before")
    @classmethod
    def compute_percentage(cls, v: float | None, info) -> float:
        """Compute percentage from processed/total if not provided."""
        # If percentage is explicitly provided, use it
        if v is not None:
            return v

        # Otherwise compute from processed and total
        data = info.data
        processed = data.get("processed", 0)
        total = data.get("total", 0)

        if total == 0:
            return 0.0

        return round((processed / total) * 100, 2)

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "job_id": "job_123abc",
                    "processed": 45,
                    "total": 100,
                    "percentage": 45.0,
                    "status": "extracting",
                    "current_step": "Extracting products from sitemap",
                    "error": None,
                }
            ]
        }
    }
