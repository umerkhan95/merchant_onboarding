"""Pipeline orchestrator for merchant onboarding process.

Orchestrates the complete onboarding flow: detection → discovery → extraction → normalization → ingestion.
Contains NO business logic itself - only calls components in order.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.extractors.base import ExtractionResult
from app.extractors.css_extractor import CSSExtractor
from app.extractors.magento_api import MagentoAPIExtractor
from app.extractors.opengraph_extractor import OpenGraphExtractor
from app.extractors.schema_org_extractor import SchemaOrgExtractor
from app.extractors.schemas.bigcommerce import BIGCOMMERCE_SCHEMA
from app.extractors.schemas.generic import GENERIC_SCHEMA
from app.extractors.shopify_api import ShopifyAPIExtractor
from app.extractors.woocommerce_api import WooCommerceAPIExtractor
from app.infra.quality_scorer import QualityScorer
from app.models.enums import ExtractionTier, JobStatus, Platform
from app.services.extraction_validator import ExtractionValidator
from app.services.platform_detector import PlatformDetector
from app.services.product_normalizer import ProductNormalizer
from app.services.url_discovery import URLDiscoveryService

if TYPE_CHECKING:
    from app.db.bulk_ingestor import BulkIngestor
    from app.extractors.llm_extractor import LLMExtractor
    from app.extractors.smart_css_extractor import SmartCSSExtractor
    from app.infra.circuit_breaker import CircuitBreaker
    from app.infra.progress_tracker import ProgressTracker
    from app.infra.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)


class Pipeline:
    """Orchestrator ONLY. Calls components in order. Contains no business logic itself."""

    def __init__(
        self,
        progress_tracker: ProgressTracker,
        circuit_breaker: CircuitBreaker,
        rate_limiter: RateLimiter,
        bulk_ingestor: BulkIngestor | None = None,
        smart_css_extractor: SmartCSSExtractor | None = None,
        llm_extractor: LLMExtractor | None = None,
    ):
        """Initialize pipeline with infrastructure components.

        Args:
            progress_tracker: Redis-backed progress tracker
            circuit_breaker: Circuit breaker for fault tolerance
            rate_limiter: Per-domain rate limiter
            bulk_ingestor: Optional bulk ingestor for database operations
            smart_css_extractor: Optional auto-generating CSS extractor (Tier 4)
            llm_extractor: Optional universal LLM extractor (Tier 5)
        """
        self.detector = PlatformDetector()
        self.discovery = URLDiscoveryService()
        self.normalizer = ProductNormalizer()
        self.quality_scorer = QualityScorer()
        self.validator = ExtractionValidator()
        self.progress = progress_tracker
        self.circuit_breaker = circuit_breaker
        self.rate_limiter = rate_limiter
        self.ingestor = bulk_ingestor
        self.smart_css = smart_css_extractor
        self.llm_extractor = llm_extractor

    async def run(self, job_id: str, shop_url: str) -> dict:
        """Run the full pipeline: detect → discover → extract → normalize → ingest.

        Args:
            job_id: Unique job identifier for progress tracking
            shop_url: Merchant shop URL to onboard

        Returns:
            Summary dict with platform, counts, and extraction tier

        Example:
            {
                "platform": "shopify",
                "total_extracted": 150,
                "total_normalized": 148,
                "total_ingested": 148,
                "extraction_tier": "api"
            }
        """
        logger.info(f"Starting pipeline for job {job_id}, shop URL: {shop_url}")

        try:
            # Step 1: Detect platform
            await self.progress.update(
                job_id=job_id,
                processed=0,
                total=0,
                status=JobStatus.DETECTING,
                current_step="Detecting e-commerce platform",
            )

            platform_result = await self.detector.detect(shop_url)
            platform = platform_result.platform
            logger.info(
                f"Platform detected: {platform} (confidence: {platform_result.confidence:.2f})"
            )

            # Step 2: Discover product URLs
            await self.progress.update(
                job_id=job_id,
                processed=0,
                total=0,
                status=JobStatus.DISCOVERING,
                current_step=f"Discovering product URLs for {platform}",
            )

            urls = await self.discovery.discover(shop_url, platform)
            logger.info(f"Discovered {len(urls)} URLs for extraction")

            if not urls:
                logger.warning(f"No URLs discovered for {shop_url}")
                await self.progress.update(
                    job_id=job_id,
                    processed=0,
                    total=0,
                    status=JobStatus.NEEDS_REVIEW,
                    current_step="No product URLs discovered — needs manual review",
                )
                return {
                    "platform": platform.value,
                    "total_extracted": 0,
                    "total_normalized": 0,
                    "total_ingested": 0,
                    "extraction_tier": ExtractionTier.API.value,
                    "needs_review": True,
                    "review_reason": "no_urls_discovered",
                }

            # Step 3: Extract products
            await self.progress.update(
                job_id=job_id,
                processed=0,
                total=len(urls),
                status=JobStatus.EXTRACTING,
                current_step=f"Extracting products from {len(urls)} URLs",
            )

            extraction_result = await self._extract_products(
                shop_url, platform, urls, job_id
            )
            logger.info(
                f"Extracted {extraction_result.product_count} raw products "
                f"(tier: {extraction_result.tier}, quality: {extraction_result.quality_score:.2f})"
            )

            # Step 3b: Validate extraction results
            validation = self.validator.validate(extraction_result)
            if not validation:
                logger.warning(
                    f"Extraction validation failed for {shop_url}: {validation.reason} — {validation.message}"
                )
                await self.progress.update(
                    job_id=job_id,
                    processed=0,
                    total=len(urls),
                    status=JobStatus.NEEDS_REVIEW,
                    current_step=f"Extraction needs review: {validation.message}",
                )
                return {
                    "platform": platform.value,
                    "total_extracted": extraction_result.product_count,
                    "total_normalized": 0,
                    "total_ingested": 0,
                    "extraction_tier": extraction_result.tier.value,
                    "needs_review": True,
                    "review_reason": validation.reason,
                }

            raw_products = extraction_result.products
            extraction_tier = extraction_result.tier

            # Step 4: Normalize products
            await self.progress.update(
                job_id=job_id,
                processed=0,
                total=len(raw_products),
                status=JobStatus.NORMALIZING,
                current_step=f"Normalizing {len(raw_products)} products",
            )

            normalized_products = []
            for i, raw in enumerate(raw_products):
                product = self.normalizer.normalize(
                    raw=raw,
                    shop_id=shop_url,
                    platform=platform,
                    shop_url=shop_url,
                )
                if product:
                    normalized_products.append(product)

                # Update progress every 10 products
                if (i + 1) % 10 == 0:
                    await self.progress.update(
                        job_id=job_id,
                        processed=i + 1,
                        total=len(raw_products),
                        status=JobStatus.NORMALIZING,
                        current_step=f"Normalized {i + 1}/{len(raw_products)} products",
                    )

            logger.info(f"Normalized {len(normalized_products)} products")

            # Step 5: Ingest products (if ingestor available)
            total_ingested = 0
            if self.ingestor and normalized_products:
                await self.progress.update(
                    job_id=job_id,
                    processed=0,
                    total=len(normalized_products),
                    status=JobStatus.INGESTING,
                    current_step=f"Ingesting {len(normalized_products)} products to database",
                )

                total_ingested = await self.ingestor.ingest(normalized_products)
                logger.info(f"Ingested {total_ingested} products to database")

            # Step 6: Mark as completed
            await self.progress.update(
                job_id=job_id,
                processed=len(normalized_products),
                total=len(normalized_products),
                status=JobStatus.COMPLETED,
                current_step="Pipeline completed successfully",
            )

            logger.info(f"Pipeline completed for job {job_id}")

            return {
                "platform": platform.value,
                "total_extracted": len(raw_products),
                "total_normalized": len(normalized_products),
                "total_ingested": total_ingested,
                "extraction_tier": extraction_tier.value,
            }

        except Exception as e:
            logger.exception(f"Pipeline failed for job {job_id}: {e}")

            # Mark as failed
            await self.progress.update(
                job_id=job_id,
                processed=0,
                total=0,
                status=JobStatus.FAILED,
                current_step="Pipeline failed",
                error=str(e),
            )

            raise

    async def _extract_products(
        self, shop_url: str, platform: Platform, urls: list[str], job_id: str
    ) -> ExtractionResult:
        """Extract products based on platform and URLs.

        Args:
            shop_url: Base shop URL
            platform: Detected platform
            urls: List of URLs to extract from
            job_id: Job identifier for progress tracking

        Returns:
            ExtractionResult with products, tier, and quality score
        """
        # Select extractor based on platform
        if platform == Platform.SHOPIFY:
            extractor = ShopifyAPIExtractor()
            extraction_tier = ExtractionTier.API
            raw_products = await self._extract_with_circuit_breaker(
                extractor, shop_url, shop_url
            )

        elif platform == Platform.WOOCOMMERCE:
            extractor = WooCommerceAPIExtractor()
            extraction_tier = ExtractionTier.API
            raw_products = await self._extract_with_circuit_breaker(
                extractor, shop_url, shop_url
            )
            # Fallback to full chain on discovered URLs if API returned nothing
            if not raw_products and urls:
                logger.info("WooCommerce API returned 0 products, falling back to extraction chain")
                raw_products, extraction_tier = await self._extract_with_fallback_chain(
                    urls, shop_url, job_id
                )

        elif platform == Platform.MAGENTO:
            extractor = MagentoAPIExtractor()
            extraction_tier = ExtractionTier.API
            raw_products = await self._extract_with_circuit_breaker(
                extractor, shop_url, shop_url
            )
            # Fallback to full chain on discovered URLs if API returned nothing
            if not raw_products and urls:
                logger.info("Magento API returned 0 products, falling back to extraction chain")
                raw_products, extraction_tier = await self._extract_with_fallback_chain(
                    urls, shop_url, job_id
                )

        elif platform == Platform.BIGCOMMERCE:
            raw_products, extraction_tier = await self._extract_with_fallback_chain(
                urls, shop_url, job_id, css_schema=BIGCOMMERCE_SCHEMA
            )

        else:  # Platform.GENERIC
            raw_products, extraction_tier = await self._extract_with_fallback_chain(
                urls, shop_url, job_id
            )

        quality_score = self.quality_scorer.score_batch(raw_products)
        return ExtractionResult(
            products=raw_products,
            tier=extraction_tier,
            quality_score=quality_score,
            urls_attempted=len(urls),
        )

    async def _extract_with_fallback_chain(
        self,
        urls: list[str],
        shop_url: str,
        job_id: str,
        css_schema: dict | None = None,
    ) -> tuple[list[dict], ExtractionTier]:
        """Try extraction strategies in order: Schema.org → OG → CSS → SmartCSS → LLM.

        5-tier fallback (Tiers 2-5, Tier 1 is platform API handled above):
        - Tier 2: Schema.org JSON-LD
        - Tier 3: OpenGraph meta tags
        - Tier 4: SmartCSS (auto-generated selectors, cached per domain)
        - Tier 5: LLM extraction (universal fallback)
        Falls back to hardcoded CSS if no LLM extractors configured.

        Args:
            urls: List of URLs to extract from
            shop_url: Base shop URL (for rate limiting domain)
            job_id: Job identifier for progress tracking
            css_schema: Optional CSS schema (uses GENERIC_SCHEMA if None)

        Returns:
            Tuple of (raw_products, extraction_tier)
        """
        if not urls:
            return [], ExtractionTier.DEEP_CRAWL

        probe_url = urls[0]

        # Tier 2: Schema.org on first URL
        schema_extractor = SchemaOrgExtractor()
        schema_products = await self._extract_with_circuit_breaker(schema_extractor, probe_url, shop_url)
        if self._probe_acceptable(schema_products, "Schema.org"):
            products = await self._extract_from_urls(schema_extractor, urls, shop_url, job_id)
            return products, ExtractionTier.SITEMAP_CSS

        # Tier 3: OpenGraph on first URL
        og_extractor = OpenGraphExtractor()
        og_products = await self._extract_with_circuit_breaker(og_extractor, probe_url, shop_url)
        if self._probe_acceptable(og_products, "OpenGraph"):
            products = await self._extract_from_urls(og_extractor, urls, shop_url, job_id)
            return products, ExtractionTier.SITEMAP_CSS

        # Tier 4: SmartCSS (auto-generated selectors, if configured)
        if self.smart_css:
            logger.info("Trying SmartCSS extraction (auto-generated selectors)")
            smart_products = await self._extract_with_circuit_breaker(self.smart_css, probe_url, shop_url)
            if self._probe_acceptable(smart_products, "SmartCSS"):
                products = await self._extract_from_urls(self.smart_css, urls, shop_url, job_id)
                return products, ExtractionTier.SMART_CSS

        # Tier 5: LLM extraction (universal fallback, if configured)
        if self.llm_extractor:
            logger.info("Trying LLM extraction (universal fallback)")
            llm_products = await self._extract_with_circuit_breaker(self.llm_extractor, probe_url, shop_url)
            if self._probe_acceptable(llm_products, "LLM"):
                products = await self._extract_from_urls(self.llm_extractor, urls, shop_url, job_id)
                return products, ExtractionTier.LLM

        # Fallback: hardcoded CSS (for when no LLM is configured)
        schema = css_schema or GENERIC_SCHEMA
        logger.info("Falling back to hardcoded CSS extraction")
        css_extractor = CSSExtractor(schema)
        products = await self._extract_from_urls(css_extractor, urls, shop_url, job_id)
        return products, ExtractionTier.DEEP_CRAWL

    def _probe_acceptable(self, products: list[dict], tier_name: str) -> bool:
        """Check if probe results are acceptable quality to commit to this tier.

        Args:
            products: Raw product dicts from probe extraction
            tier_name: Name of the tier for logging

        Returns:
            True if products are non-empty and meet quality threshold
        """
        if not products:
            return False

        quality = self.quality_scorer.score_batch(products)
        if quality < 0.3:
            logger.info(
                "%s probe returned %d products but quality %.2f is below threshold, skipping",
                tier_name, len(products), quality,
            )
            return False

        logger.info(
            "%s probe successful: %d products, quality %.2f — committing to full extraction",
            tier_name, len(products), quality,
        )
        return True

    async def _extract_with_circuit_breaker(
        self, extractor, url: str, domain: str
    ) -> list[dict]:
        """Extract products using circuit breaker for fault tolerance.

        Args:
            extractor: Extractor instance
            url: URL to extract from
            domain: Domain for circuit breaker tracking

        Returns:
            List of raw product dicts
        """

        async def extract_fn():
            return await extractor.extract(url)

        try:
            return await self.circuit_breaker.call(domain, extract_fn)
        except Exception as e:
            logger.error(f"Extraction failed for {url}: {e}")
            return []

    async def _extract_from_urls(
        self, extractor, urls: list[str], domain: str, job_id: str
    ) -> list[dict]:
        """Extract products from multiple URLs using batch extraction.

        Uses extract_batch() which, for browser-based extractors, opens a single
        browser and crawls all URLs concurrently via arun_many().

        Args:
            extractor: Extractor instance
            urls: List of URLs to extract from
            domain: Domain for rate limiting (unused — arun_many handles concurrency)
            job_id: Job identifier for progress tracking

        Returns:
            List of raw product dicts from all URLs
        """
        products = await extractor.extract_batch(urls)

        await self.progress.update(
            job_id=job_id,
            processed=len(urls),
            total=len(urls),
            status=JobStatus.EXTRACTING,
            current_step=f"Extracted {len(urls)} URLs, got {len(products)} products",
        )
        return products
