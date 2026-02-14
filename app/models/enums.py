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
    NORMALIZING = "normalizing"
    INGESTING = "ingesting"
    COMPLETED = "completed"
    FAILED = "failed"


class ExtractionTier(StrEnum):
    """Product extraction tier/strategy."""

    API = "api"
    SITEMAP_CSS = "sitemap_css"
    DEEP_CRAWL = "deep_crawl"
