"""String enums for merchant onboarding pipeline."""

from __future__ import annotations

from enum import StrEnum


class Platform(StrEnum):
    """Supported e-commerce platforms."""

    SHOPIFY = "shopify"
    WOOCOMMERCE = "woocommerce"
    MAGENTO = "magento"
    BIGCOMMERCE = "bigcommerce"
    GENERIC = "generic"


class JobStatus(StrEnum):
    """Job processing status."""

    QUEUED = "queued"
    DETECTING = "detecting"
    DISCOVERING = "discovering"
    EXTRACTING = "extracting"
    VERIFYING = "verifying"
    NORMALIZING = "normalizing"
    INGESTING = "ingesting"
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class ExtractionTier(StrEnum):
    """Product extraction tier/strategy."""

    API = "api"
    UNIFIED_CRAWL = "unified_crawl"
    SCHEMA_ORG = "schema_org"
    OPENGRAPH = "opengraph"
    SITEMAP_CSS = "sitemap_css"
    DEEP_CRAWL = "deep_crawl"
    SMART_CSS = "smart_css"
    BIGCOMMERCE_API = "bigcommerce_api"
    LLM = "llm"
