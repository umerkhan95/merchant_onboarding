"""String enums for merchant onboarding pipeline."""

from __future__ import annotations

from enum import StrEnum


class Platform(StrEnum):
    """Supported e-commerce platforms."""

    SHOPIFY = "shopify"
    WOOCOMMERCE = "woocommerce"
    MAGENTO = "magento"
    BIGCOMMERCE = "bigcommerce"
    SHOPWARE = "shopware"
    GENERIC = "generic"


class JobStatus(StrEnum):
    """Job processing status."""

    QUEUED = "queued"
    DETECTING = "detecting"
    DISCOVERING = "discovering"
    EXTRACTING = "extracting"
    VERIFYING = "verifying"
    NORMALIZING = "normalizing"
    INGESTING = "ingesting"  # Legacy — no longer emitted by pipeline
    COMPLETED = "completed"
    NEEDS_REVIEW = "needs_review"
    FAILED = "failed"


class ExtractionTier(StrEnum):
    """Product extraction tier/strategy."""

    API = "api"
    UNIFIED_CRAWL = "unified_crawl"
    SCHEMA_ORG = "schema_org"  # Legacy — no longer emitted by pipeline
    OPENGRAPH = "opengraph"  # Legacy — no longer emitted by pipeline
    SITEMAP_CSS = "sitemap_css"  # Legacy — no longer emitted by pipeline
    DEEP_CRAWL = "deep_crawl"
    SMART_CSS = "smart_css"
    BIGCOMMERCE_API = "bigcommerce_api"
    SHOPIFY_ADMIN_API = "shopify_admin_api"
    WOOCOMMERCE_API = "woocommerce_api"
    SHOPWARE_API = "shopware_api"
    MAGENTO_API = "magento_api"
    GOOGLE_FEED = "google_feed"
    LLM = "llm"
