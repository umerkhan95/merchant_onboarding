"""Pipeline orchestrator for merchant onboarding process.

Orchestrates the complete onboarding flow: detection → discovery → extraction → normalization → ingestion.
Contains NO business logic itself - only calls components in order.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.extractors.css_extractor import CSSExtractor
from app.extractors.magento_api import MagentoAPIExtractor
from app.extractors.opengraph_extractor import OpenGraphExtractor
from app.extractors.schema_org_extractor import SchemaOrgExtractor
from app.extractors.schemas.bigcommerce import BIGCOMMERCE_SCHEMA
from app.extractors.schemas.generic import GENERIC_SCHEMA
from app.extractors.shopify_api import ShopifyAPIExtractor
from app.extractors.woocommerce_api import WooCommerceAPIExtractor
from app.models.enums import ExtractionTier, JobStatus, Platform
from app.services.platform_detector import PlatformDetector
from app.services.product_normalizer import ProductNormalizer
from app.services.url_discovery import URLDiscoveryService

if TYPE_CHECKING:
    from app.db.bulk_ingestor import BulkIngestor
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
    ):
        """Initialize pipeline with infrastructure components.

        Args:
            progress_tracker: Redis-backed progress tracker
            circuit_breaker: Circuit breaker for fault tolerance
            rate_limiter: Per-domain rate limiter
            bulk_ingestor: Optional bulk ingestor for database operations
        """
        self.detector = PlatformDetector()
        self.discovery = URLDiscoveryService()
        self.normalizer = ProductNormalizer()
        self.progress = progress_tracker
        self.circuit_breaker = circuit_breaker
        self.rate_limiter = rate_limiter
        self.ingestor = bulk_ingestor

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
                    status=JobStatus.COMPLETED,
                    current_step="Completed with no products found",
                )
                return {
                    "platform": platform.value,
                    "total_extracted": 0,
                    "total_normalized": 0,
                    "total_ingested": 0,
                    "extraction_tier": ExtractionTier.API.value,
                }

            # Step 3: Extract products
            await self.progress.update(
                job_id=job_id,
                processed=0,
                total=len(urls),
                status=JobStatus.EXTRACTING,
                current_step=f"Extracting products from {len(urls)} URLs",
            )

            raw_products, extraction_tier = await self._extract_products(
                shop_url, platform, urls, job_id
            )
            logger.info(f"Extracted {len(raw_products)} raw products (tier: {extraction_tier})")

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
    ) -> tuple[list[dict], ExtractionTier]:
        """Extract products based on platform and URLs.

        Args:
            shop_url: Base shop URL
            platform: Detected platform
            urls: List of URLs to extract from
            job_id: Job identifier for progress tracking

        Returns:
            Tuple of (raw_products, extraction_tier)
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
            # Fallback to CSS extraction on discovered URLs if API returned nothing
            if not raw_products and urls:
                logger.info("WooCommerce API returned 0 products, falling back to CSS on discovered URLs")
                raw_products, extraction_tier = await self._extract_with_fallback_chain(
                    urls, shop_url, job_id
                )

        elif platform == Platform.MAGENTO:
            extractor = MagentoAPIExtractor()
            extraction_tier = ExtractionTier.API
            raw_products = await self._extract_with_circuit_breaker(
                extractor, shop_url, shop_url
            )
            # Fallback to CSS extraction on discovered URLs if API returned nothing
            if not raw_products and urls:
                logger.info("Magento API returned 0 products, falling back to CSS on discovered URLs")
                raw_products, extraction_tier = await self._extract_with_fallback_chain(
                    urls, shop_url, job_id
                )

        elif platform == Platform.BIGCOMMERCE:
            # BigCommerce: CSS extraction on discovered URLs
            raw_products, extraction_tier = await self._extract_with_fallback_chain(
                urls, shop_url, job_id, css_schema=BIGCOMMERCE_SCHEMA
            )

        else:  # Platform.GENERIC
            raw_products, extraction_tier = await self._extract_with_fallback_chain(
                urls, shop_url, job_id
            )

        return raw_products, extraction_tier

    async def _extract_with_fallback_chain(
        self,
        urls: list[str],
        shop_url: str,
        job_id: str,
        css_schema: dict | None = None,
    ) -> tuple[list[dict], ExtractionTier]:
        """Try extraction strategies in order: Schema.org → OpenGraph → CSS.

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

        # Try Schema.org on first URL
        schema_extractor = SchemaOrgExtractor()
        schema_products = await self._extract_with_circuit_breaker(schema_extractor, urls[0], shop_url)
        if schema_products:
            logger.info("Schema.org extraction successful, extracting from all URLs")
            products = await self._extract_from_urls(schema_extractor, urls, shop_url, job_id)
            return products, ExtractionTier.SITEMAP_CSS

        # Try OpenGraph on first URL
        og_extractor = OpenGraphExtractor()
        og_products = await self._extract_with_circuit_breaker(og_extractor, urls[0], shop_url)
        if og_products:
            logger.info("OpenGraph extraction successful, extracting from all URLs")
            products = await self._extract_from_urls(og_extractor, urls, shop_url, job_id)
            return products, ExtractionTier.SITEMAP_CSS

        # Fallback to CSS extraction
        schema = css_schema or GENERIC_SCHEMA
        logger.info("Falling back to CSS extraction")
        css_extractor = CSSExtractor(schema)
        products = await self._extract_from_urls(css_extractor, urls, shop_url, job_id)
        return products, ExtractionTier.DEEP_CRAWL

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
        """Extract products from multiple URLs with rate limiting and progress tracking.

        Args:
            extractor: Extractor instance
            urls: List of URLs to extract from
            domain: Domain for rate limiting
            job_id: Job identifier for progress tracking

        Returns:
            List of raw product dicts from all URLs
        """
        all_products = []

        for i, url in enumerate(urls):
            async with self.rate_limiter.acquire(domain):
                products = await self._extract_with_circuit_breaker(extractor, url, domain)
                all_products.extend(products)

                # Update progress every 5 URLs
                if (i + 1) % 5 == 0:
                    await self.progress.update(
                        job_id=job_id,
                        processed=i + 1,
                        total=len(urls),
                        status=JobStatus.EXTRACTING,
                        current_step=f"Extracted {i + 1}/{len(urls)} URLs",
                    )

        return all_products
