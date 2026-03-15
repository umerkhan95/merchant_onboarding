"""Pipeline orchestrator for merchant onboarding process.

Orchestrates the complete onboarding flow: detection -> discovery -> extraction -> normalization -> ingestion.
Contains NO business logic itself - only calls components in order.
"""

from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

from app.config import MAX_RESPONSE_SIZE
from app.exceptions.errors import CircuitOpenError, ExtractionError
from app.extractors.base import BaseExtractor, ExtractionResult
from app.extractors.css_extractor import CSSExtractor
from app.extractors.magento_api import MagentoAPIExtractor
from app.extractors.opengraph_extractor import OpenGraphExtractor
from app.extractors.schema_org_extractor import SchemaOrgExtractor
from app.extractors.unified_crawl_extractor import UnifiedCrawlExtractor
from app.extractors.schemas.bigcommerce import BIGCOMMERCE_SCHEMA
from app.extractors.schemas.generic import GENERIC_SCHEMA
from app.extractors.shopify_api import ShopifyAPIExtractor
from app.extractors.woocommerce_api import WooCommerceAPIExtractor
from app.infra.quality_scorer import QualityScorer
from app.models.enums import ExtractionTier, JobStatus, Platform
from app.services.completeness_checker import CompletenessChecker
from app.services.extraction_tracker import SOURCE_URL_KEY, ExtractionTracker
from app.services.extraction_validator import ExtractionValidator
from app.services.page_validator import ProductPageValidator
from app.services.platform_detector import PlatformDetector
from app.services.product_normalizer import ProductNormalizer
from app.services.reconciliation_reporter import ReconciliationReporter
from app.services.gtin_supplementer import GTINSupplementer
from app.services.shopify_price_supplementer import ShopifyPriceSupplementer
from app.services.url_discovery import URLDiscoveryService
from app.services.url_normalizer import normalize_shop_url
from app.extractors.merchant_profile_extractor import MerchantProfileExtractor
from app.services.merchant_profile_normalizer import MerchantProfileNormalizer

if TYPE_CHECKING:
    from app.db.bulk_ingestor import BulkIngestor
    from app.db.merchant_profile_ingestor import MerchantProfileIngestor
    from app.db.oauth_store import OAuthStore
    from app.extractors.llm_extractor import LLMExtractor
    from app.extractors.smart_css_extractor import SmartCSSExtractor
    from app.infra.circuit_breaker import CircuitBreaker
    from app.infra.llm_budget import LLMBudgetTracker
    from app.infra.progress_tracker import ProgressTracker
    from app.infra.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Pipeline-level timeout: 30 minutes max for any single job
_PIPELINE_TIMEOUT_SECONDS = 30 * 60

# Max URLs for targeted re-extraction (completeness pass)
_MAX_REEXTRACTION_URLS = 50

# Default max URLs to extract per job (prevents bans on target stores)
_DEFAULT_MAX_URLS = 20

# Concurrent extraction batch size (URLs processed in parallel per batch)
_EXTRACTION_CONCURRENCY = 10

# Normalization + ingestion batch size (products processed per chunk)
_NORMALIZE_BATCH_SIZE = 500


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
        llm_budget: LLMBudgetTracker | None = None,
        profile_ingestor: MerchantProfileIngestor | None = None,
        oauth_store: OAuthStore | None = None,
    ):
        """Initialize pipeline with infrastructure components.

        Args:
            progress_tracker: Redis-backed progress tracker
            circuit_breaker: Circuit breaker for fault tolerance
            rate_limiter: Per-domain rate limiter
            bulk_ingestor: Optional bulk ingestor for database operations
            smart_css_extractor: Optional auto-generating CSS extractor (Tier 4)
            llm_extractor: Optional universal LLM extractor (Tier 5)
            llm_budget: Optional LLM cost budget tracker (for Tier 4-5)
            profile_ingestor: Optional merchant profile ingestor for database operations
            oauth_store: Optional OAuth token store for authenticated platform APIs
        """
        self.detector = PlatformDetector()
        self.discovery = URLDiscoveryService()
        self.normalizer = ProductNormalizer()
        self.profile_normalizer = MerchantProfileNormalizer()
        self.quality_scorer = QualityScorer()
        self.validator = ExtractionValidator()
        self.completeness_checker = CompletenessChecker()
        self.reconciliation_reporter = ReconciliationReporter()
        self.page_validator = ProductPageValidator()
        self.progress = progress_tracker
        self.circuit_breaker = circuit_breaker
        self.rate_limiter = rate_limiter
        self.ingestor = bulk_ingestor
        self.profile_ingestor = profile_ingestor
        self.smart_css = smart_css_extractor
        self.llm_extractor = llm_extractor
        self.llm_budget = llm_budget
        self.oauth_store = oauth_store
        self._http_client: httpx.AsyncClient | None = None

    async def _emit_extraction_metadata(
        self, job_id: str, all_products: list[dict], tracker: ExtractionTracker
    ) -> None:
        """Emit recent_products and extraction_audit metadata to Redis."""
        # Last 5 products with display-safe fields
        recent = []
        for p in all_products[-5:]:
            # Resolve image URL from various raw formats
            image = p.get("image_url") or p.get("image") or p.get("og:image", "")
            if not image or not isinstance(image, str):
                # Shopify Admin API: images is a list of {src: "..."}
                images = p.get("images") or []
                if isinstance(images, list) and images:
                    first = images[0]
                    image = first.get("src", "") if isinstance(first, dict) else str(first)
                # Shopify Admin API: image can be a dict with src
                if not image:
                    img_obj = p.get("image")
                    if isinstance(img_obj, dict):
                        image = img_obj.get("src", "")
            # Resolve price from various raw formats
            price = p.get("price") or p.get("og:price:amount") or p.get("product:price:amount", "")
            if not price:
                # Shopify/BigCommerce Admin API: price is on the first variant
                variants = p.get("variants") or []
                if isinstance(variants, list) and variants:
                    first_v = variants[0]
                    if isinstance(first_v, dict):
                        price = first_v.get("price", "")

            recent.append({
                "title": p.get("title") or p.get("name") or p.get("og:title", ""),
                "price": price,
                "image_url": image if isinstance(image, str) else "",
            })

        audit = tracker.build_audit()
        audit_data = {
            "urls_success": audit.urls_with_products,
            "urls_empty": audit.urls_empty,
            "urls_error": audit.urls_errored,
            "urls_not_product": audit.urls_not_product,
            "total_products": audit.total_products,
        }

        await self.progress.set_metadata(
            job_id,
            recent_products=json.dumps(recent),
            extraction_audit=json.dumps(audit_data),
        )

    async def run(
        self, job_id: str, shop_url: str, timeout: int = _PIPELINE_TIMEOUT_SECONDS,
        max_urls: int | None = None, feed_url: str | None = None,
    ) -> dict:
        """Run the full pipeline: detect -> discover -> extract -> normalize -> ingest.

        Args:
            job_id: Unique job identifier for progress tracking
            shop_url: Merchant shop URL to onboard
            timeout: Max seconds before the pipeline is killed (default 30 min)
            max_urls: Cap discovered URLs to this number (None = no cap)
            feed_url: Google Shopping feed URL — if provided, skips detection/discovery/extraction

        Returns:
            Summary dict with platform, counts, and extraction tier
        """
        try:
            if feed_url:
                coro = self._run_feed_import(job_id, feed_url, shop_url or feed_url)
            else:
                coro = self._run_inner(job_id, shop_url, max_urls=max_urls)
            return await asyncio.wait_for(coro, timeout=timeout)
        except asyncio.TimeoutError:
            logger.error("Pipeline timed out after %ds for job %s", timeout, job_id)
            current_progress = await self.progress.get(job_id)
            await self.progress.update(
                job_id=job_id,
                processed=current_progress.get("processed", 0) if current_progress else 0,
                total=current_progress.get("total", 0) if current_progress else 0,
                status=JobStatus.FAILED,
                current_step="Pipeline timed out",
                error=f"Pipeline timed out after {timeout // 60} minutes",
            )
            raise

    def _create_http_client(self) -> httpx.AsyncClient:
        """Create a shared httpx.AsyncClient for the pipeline run.

        Includes SSRF redirect validation hook to block redirects to private IPs.
        """
        from app.extractors.browser_config import DEFAULT_HEADERS, get_default_user_agent
        from app.security.url_validator import URLValidator

        return httpx.AsyncClient(
            follow_redirects=True,
            timeout=30.0,
            headers={**DEFAULT_HEADERS, "User-Agent": get_default_user_agent()},
            event_hooks={"response": [URLValidator.validate_redirect_async]},
        )

    async def _run_feed_import(self, job_id: str, feed_url: str, shop_url: str) -> dict:
        """Shortcut pipeline path: parse a Google Shopping feed, normalize, ingest.

        Skips platform detection, URL discovery, and the extraction probe chain.
        The feed already contains complete product data with GTINs.
        """
        from app.extractors.google_feed_extractor import GoogleFeedExtractor
        from urllib.parse import urlparse as _feed_urlparse

        shop_url = shop_url or feed_url
        # Derive a shop domain from feed URL if no shop_url
        parsed = _feed_urlparse(feed_url)
        feed_domain = parsed.netloc or feed_url

        logger.info("Feed import for job %s: %s", job_id, feed_url)

        await self.progress.update(
            job_id=job_id, processed=0, total=0,
            status=JobStatus.EXTRACTING,
            current_step="Parsing Google Shopping feed",
        )
        await self.progress.set_metadata(
            job_id,
            shop_url=shop_url,
            platform=Platform.GENERIC.value,
            extraction_tier=ExtractionTier.GOOGLE_FEED.value,
            started_at=datetime.now(timezone.utc).isoformat(),
        )

        extractor = GoogleFeedExtractor()
        result = await extractor.extract(feed_url)

        if result.error or result.is_empty:
            reason = result.error or "Feed returned no products"
            await self.progress.update(
                job_id=job_id, processed=0, total=0,
                status=JobStatus.NEEDS_REVIEW,
                current_step=f"Feed import failed: {reason}",
                error=reason,
            )
            return {
                "platform": Platform.GENERIC.value,
                "total_extracted": 0,
                "total_normalized": 0,
                "total_ingested": 0,
                "extraction_tier": ExtractionTier.GOOGLE_FEED.value,
                "coverage_percentage": 0.0,
                "urls_failed": 0,
            }

        raw_products = result.products
        total_extracted = len(raw_products)
        logger.info("Feed parsed: %d products from %s", total_extracted, feed_url)

        # Normalize and ingest (same as standard pipeline Steps 4+5)
        await self.progress.update(
            job_id=job_id, processed=0, total=total_extracted,
            status=JobStatus.NORMALIZING,
            current_step=f"Normalizing {total_extracted} products from feed",
        )

        total_normalized = 0
        total_ingested = 0
        for batch_start in range(0, total_extracted, _NORMALIZE_BATCH_SIZE):
            batch_end = min(batch_start + _NORMALIZE_BATCH_SIZE, total_extracted)
            raw_batch = raw_products[batch_start:batch_end]

            normalized_batch = []
            for raw in raw_batch:
                product = self.normalizer.normalize(
                    raw=raw, shop_id=shop_url,
                    platform=Platform.GENERIC, shop_url=shop_url,
                )
                if product:
                    normalized_batch.append(product)

            total_normalized += len(normalized_batch)

            await self.progress.update(
                job_id=job_id, processed=batch_end, total=total_extracted,
                status=JobStatus.NORMALIZING,
                current_step=f"Normalized {batch_end}/{total_extracted} products",
            )

            if self.ingestor and normalized_batch:
                total_ingested += await self.ingestor.ingest(normalized_batch)

        logger.info("Feed import normalized %d, ingested %d products", total_normalized, total_ingested)

        # Mark complete
        await self.progress.update(
            job_id=job_id, processed=total_normalized, total=total_normalized,
            status=JobStatus.COMPLETED,
            current_step="Feed import completed successfully",
        )
        await self.progress.set_metadata(
            job_id,
            completed_at=datetime.now(timezone.utc).isoformat(),
            products_count=total_normalized,
        )

        return {
            "platform": Platform.GENERIC.value,
            "total_extracted": total_extracted,
            "total_normalized": total_normalized,
            "total_ingested": total_ingested,
            "extraction_tier": ExtractionTier.GOOGLE_FEED.value,
            "coverage_percentage": (total_normalized / total_extracted * 100) if total_extracted else 0.0,
            "urls_failed": 0,
        }

    async def _run_inner(self, job_id: str, shop_url: str, max_urls: int | None = None) -> dict:
        """Inner pipeline logic wrapped by run() with timeout."""
        shop_url = normalize_shop_url(shop_url)
        logger.info(f"Starting pipeline for job {job_id}, shop URL: {shop_url}")

        # Create a shared HTTP client for the entire pipeline run
        self._http_client = self._create_http_client()

        # Re-create components with shared client
        self.detector = PlatformDetector(client=self._http_client)
        self.discovery = URLDiscoveryService(client=self._http_client)

        try:
            # Step 1: Detect platform
            await self.progress.update(
                job_id=job_id,
                processed=0,
                total=0,
                status=JobStatus.DETECTING,
                current_step="Detecting e-commerce platform",
            )
            await self.progress.set_metadata(
                job_id,
                shop_url=shop_url,
                started_at=datetime.now(timezone.utc).isoformat(),
            )

            platform_result = await self.detector.detect(shop_url)
            platform = platform_result.platform
            logger.info(
                f"Platform detected: {platform} (confidence: {platform_result.confidence:.2f})"
            )
            await self.progress.set_metadata(job_id, platform=platform.value)

            # Step 1b: Extract merchant profile (non-blocking)
            merchant_profile = None
            try:
                profile_extractor = MerchantProfileExtractor(client=self._http_client)
                profile_result = await profile_extractor.extract(
                    shop_url=shop_url,
                    homepage_html=platform_result.html,
                )

                if profile_result.raw_data and not profile_result.error:
                    merchant_profile = self.profile_normalizer.normalize(
                        raw=profile_result.raw_data,
                        shop_id=shop_url,
                        platform=platform,
                        shop_url=shop_url,
                    )
                    if merchant_profile and self.profile_ingestor:
                        await self.profile_ingestor.upsert(merchant_profile)
                        logger.info(
                            "Merchant profile saved (confidence: %.2f, tags: %d)",
                            merchant_profile.extraction_confidence,
                            len(merchant_profile.analytics_tags),
                        )
                    await self.progress.set_metadata(
                        job_id,
                        merchant_profile_confidence=profile_result.confidence if profile_result else 0.0,
                    )
            except Exception as e:
                # Profile extraction failure never blocks the product pipeline
                logger.exception("Merchant profile extraction failed (non-fatal): %s", e)

            # Step 2: Discover product URLs
            await self.progress.update(
                job_id=job_id,
                processed=0,
                total=0,
                status=JobStatus.DISCOVERING,
                current_step=f"Discovering product URLs for {platform}",
            )

            urls = await self.discovery.discover(shop_url, platform)
            effective_max = max_urls or _DEFAULT_MAX_URLS
            if len(urls) > effective_max:
                logger.info(f"Capping discovered URLs from {len(urls)} to {effective_max}")
                urls = urls[:effective_max]

            # SSRF validation: filter out discovered URLs pointing to private/internal IPs
            from app.security.url_validator import URLValidator
            validated_urls = []
            ssrf_dropped = 0
            for url in urls:
                is_valid, reason = URLValidator.validate(url)
                if is_valid:
                    validated_urls.append(url)
                else:
                    ssrf_dropped += 1
                    logger.warning("SSRF: dropping discovered URL %s: %s", url, reason)
            if ssrf_dropped:
                logger.warning("SSRF: dropped %d of %d discovered URLs", ssrf_dropped, len(urls))
            urls = validated_urls

            logger.info(f"Discovered {len(urls)} URLs for extraction")

            if not urls:
                # Check if we have an OAuth connection that can fetch products
                # without needing discovered URLs (Admin APIs).
                has_admin_api = False
                if self.oauth_store and platform in (Platform.SHOPIFY, Platform.BIGCOMMERCE, Platform.WOOCOMMERCE, Platform.SHOPWARE):
                    from urllib.parse import urlparse as _oauth_urlparse
                    _oauth_domain = _oauth_urlparse(shop_url).netloc or shop_url
                    _oauth_conn = await self.oauth_store.get_connection(
                        platform.value, _oauth_domain
                    )
                    if not _oauth_conn:
                        _oauth_conn = await self.oauth_store.get_connection_by_domain(
                            _oauth_domain
                        )
                    # WooCommerce uses consumer_key instead of access_token
                    if platform == Platform.WOOCOMMERCE:
                        has_admin_api = (
                            _oauth_conn is not None
                            and _oauth_conn.consumer_key is not None
                        )
                    else:
                        has_admin_api = _oauth_conn is not None and _oauth_conn.access_token is not None

                if not has_admin_api:
                    logger.warning(f"No URLs discovered for {shop_url}")
                    await self.progress.update(
                        job_id=job_id,
                        processed=0,
                        total=0,
                        status=JobStatus.NEEDS_REVIEW,
                        current_step="No product URLs discovered -- needs manual review",
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
                logger.info(
                    "No URLs discovered but OAuth Admin API available for %s -- proceeding",
                    platform.value,
                )

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
                    f"Extraction validation failed for {shop_url}: {validation.reason} -- {validation.message}"
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
            total_extracted = len(raw_products)
            await self.progress.set_metadata(job_id, extraction_tier=extraction_tier.value)

            # Step 3c: Verify data completeness + targeted re-extraction
            await self.progress.update(
                job_id=job_id,
                processed=0,
                total=total_extracted,
                status=JobStatus.VERIFYING,
                current_step="Checking data completeness",
            )

            results = self.completeness_checker.check_batch(raw_products)
            plan = self.completeness_checker.build_reextraction_plan(results)

            # Cap price and image re-extraction independently (#86)
            capped_price_urls = plan.urls_needing_price[:_MAX_REEXTRACTION_URLS]
            capped_image_urls = plan.urls_needing_image[:_MAX_REEXTRACTION_URLS]
            if capped_price_urls or capped_image_urls:
                from app.services.completeness_checker import ReextractionPlan
                capped_plan = ReextractionPlan(
                    urls_needing_price=capped_price_urls,
                    urls_needing_image=capped_image_urls,
                    total_incomplete=plan.total_incomplete,
                )
                reextract_urls = len(set(capped_price_urls) | set(capped_image_urls))
                logger.info(
                    "Targeted re-extraction: %d incomplete products across %d URLs (price: %d, image: %d)",
                    plan.total_incomplete,
                    reextract_urls,
                    len(capped_price_urls),
                    len(capped_image_urls),
                )
                raw_products = await self._targeted_reextract(
                    raw_products, capped_plan, shop_url, platform
                )

            # Steps 4+5: Normalize and ingest in batches
            # Process _NORMALIZE_BATCH_SIZE products at a time through normalization
            # and ingestion to avoid holding all normalized products in memory.
            total_normalized = 0
            total_ingested = 0
            product_currency = None  # Track currency from products for profile backfill

            await self.progress.update(
                job_id=job_id,
                processed=0,
                total=total_extracted,
                status=JobStatus.NORMALIZING,
                current_step=f"Normalizing {total_extracted} products",
            )

            for batch_start in range(0, total_extracted, _NORMALIZE_BATCH_SIZE):
                batch_end = min(batch_start + _NORMALIZE_BATCH_SIZE, total_extracted)
                raw_batch = raw_products[batch_start:batch_end]

                # Normalize this batch
                normalized_batch = []
                for raw in raw_batch:
                    product = self.normalizer.normalize(
                        raw=raw,
                        shop_id=shop_url,
                        platform=platform,
                        shop_url=shop_url,
                    )
                    if product:
                        normalized_batch.append(product)

                # Capture currency from first normalized product for profile backfill
                if product_currency is None and normalized_batch:
                    product_currency = normalized_batch[0].currency

                total_normalized += len(normalized_batch)

                await self.progress.update(
                    job_id=job_id,
                    processed=batch_end,
                    total=total_extracted,
                    status=JobStatus.NORMALIZING,
                    current_step=f"Normalized {batch_end}/{total_extracted} products",
                )

                # Ingest this batch immediately (if ingestor available)
                if self.ingestor and normalized_batch:
                    total_ingested += await self.ingestor.ingest(normalized_batch)

            logger.info(f"Normalized {total_normalized} products")

            # Log normalization drop rate if products were lost
            if total_extracted:
                dropped = total_extracted - total_normalized
                if dropped > 0:
                    drop_rate = dropped / total_extracted * 100
                    logger.warning(
                        "Normalization dropped %d/%d products (%.1f%%)",
                        dropped,
                        total_extracted,
                        drop_rate,
                    )
                    if drop_rate > 50:
                        logger.error(
                            "Normalization drop rate >50%% -- possible extractor/normalizer mismatch"
                        )

            if total_ingested:
                logger.info(f"Ingested {total_ingested} products to database")

            # Backfill merchant profile currency from product data
            if (
                merchant_profile
                and not merchant_profile.currency
                and product_currency
                and self.profile_ingestor
            ):
                merchant_profile.currency = product_currency
                try:
                    await self.profile_ingestor.upsert(merchant_profile)
                    logger.info(
                        "Backfilled merchant profile currency: %s", product_currency
                    )
                except Exception as e:
                    logger.warning("Failed to backfill profile currency: %s", e)

            # Reconciliation report (uses tracker audit counts, not product list)
            audit = extraction_result.audit
            report = self.reconciliation_reporter.generate(
                discovered_urls=urls,
                audit_summary=audit,
                products_normalized=total_normalized,
            )
            await self.progress.set_metadata(
                job_id,
                reconciliation_report=report.to_json(),
                coverage_percentage=round(report.coverage_percentage, 2),
            )

            # Release raw_products memory now that normalization+ingestion is complete
            del raw_products

            # Step 6: Mark as completed
            await self.progress.update(
                job_id=job_id,
                processed=total_normalized,
                total=total_normalized,
                status=JobStatus.COMPLETED,
                current_step="Pipeline completed successfully",
            )
            await self.progress.set_metadata(
                job_id,
                completed_at=datetime.now(timezone.utc).isoformat(),
                products_count=total_normalized,
            )

            logger.info(f"Pipeline completed for job {job_id}")

            return {
                "platform": platform.value,
                "total_extracted": total_extracted,
                "total_normalized": total_normalized,
                "total_ingested": total_ingested,
                "extraction_tier": extraction_tier.value,
                "coverage_percentage": report.coverage_percentage,
                "urls_failed": len(report.failed_urls),
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
        finally:
            if self._http_client is not None:
                await self._http_client.aclose()

    async def _try_oauth_admin_extraction(
        self, platform: Platform, shop_url: str, job_id: str,
        tracker: ExtractionTracker
    ) -> tuple[list[dict], ExtractionTier] | None:
        """Attempt OAuth-authenticated admin API extraction via coordinator.

        Returns (raw_products, extraction_tier) on success, or None to signal
        the caller should fall back to public API / scraping chain.
        """
        if not self.oauth_store:
            return None

        from app.services.oauth_extraction_coordinator import OAuthExtractionCoordinator
        coordinator = OAuthExtractionCoordinator(self.oauth_store)
        resolved = await coordinator.try_resolve(platform, shop_url)
        if resolved is None:
            return None

        admin_extractor, extraction_tier = resolved
        try:
            await self.progress.set_metadata(job_id, extraction_tier=extraction_tier.value)
            raw_products = await self._extract_with_circuit_breaker(
                admin_extractor, shop_url, shop_url
            )
            if raw_products:
                ExtractionTracker.tag_products_with_source(raw_products, shop_url)
                tracker.record_success(shop_url, len(raw_products))
                await self._emit_extraction_metadata(job_id, raw_products, tracker)
                return raw_products, extraction_tier
            else:
                tracker.record_empty(shop_url)
                return None
        except Exception as e:
            logger.warning(
                "%s Admin API failed, falling back: %s",
                platform.value.title(), e,
            )
            await self.progress.set_metadata(job_id, oauth_fallback_reason=str(e))
            return None

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
            ExtractionResult with products, tier, quality score, and audit
        """
        tracker = ExtractionTracker()

        # Check for OAuth connections before platform-specific branches.
        # An OAuth connection is authoritative proof of platform, overriding detection.
        if self.oauth_store:
            from app.services.oauth_extraction_coordinator import OAuthExtractionCoordinator
            coordinator = OAuthExtractionCoordinator(self.oauth_store)
            platform = await coordinator.resolve_platform_override(platform, shop_url)

        # Select extractor based on platform
        if platform == Platform.SHOPIFY:
            # Try authenticated Shopify Admin API first (provides barcode/GTIN)
            oauth_result = await self._try_oauth_admin_extraction(
                platform, shop_url, job_id, tracker
            )
            if oauth_result is not None:
                raw_products, extraction_tier = oauth_result
                # Admin API provides GTIN natively, no supplementation needed
                audit = tracker.build_audit()
                quality_score = self.quality_scorer.score_batch(raw_products)
                return ExtractionResult(
                    products=raw_products,
                    tier=extraction_tier,
                    quality_score=quality_score,
                    urls_attempted=len(urls),
                    audit=audit.to_summary_dict(),
                )

            # Fall back to public Shopify API
            extractor = ShopifyAPIExtractor()
            extraction_tier = ExtractionTier.API
            await self.progress.set_metadata(job_id, extraction_tier=extraction_tier.value)
            raw_products = await self._extract_with_circuit_breaker(
                extractor, shop_url, shop_url
            )
            if raw_products:
                ExtractionTracker.tag_products_with_source(raw_products, shop_url)
                tracker.record_success(shop_url, len(raw_products))
                await self._emit_extraction_metadata(job_id, raw_products, tracker)
            else:
                tracker.record_empty(shop_url)
            # Fallback to full chain on discovered URLs if API returned nothing
            if not raw_products and urls:
                logger.info("Shopify API returned 0 products, falling back to extraction chain")
                raw_products, extraction_tier = await self._extract_with_fallback_chain(
                    urls, shop_url, job_id, tracker=tracker
                )
                # Supplement zero-price / geo-currency products with Shopify API pricing
                if raw_products:
                    supplementer = ShopifyPriceSupplementer(self.circuit_breaker)
                    raw_products = await supplementer.supplement(
                        raw_products, shop_url
                    )
            raw_products = await self._supplement_gtin_if_needed(
                raw_products, platform, shop_url, job_id
            )

        elif platform == Platform.WOOCOMMERCE:
            # Try authenticated WooCommerce REST API v3 first (provides GTIN via meta_data)
            oauth_result = await self._try_oauth_admin_extraction(
                platform, shop_url, job_id, tracker
            )
            if oauth_result is not None:
                raw_products, extraction_tier = oauth_result
                # REST API v3 provides GTIN natively via meta_data — skip supplementer
                audit = tracker.build_audit()
                quality_score = self.quality_scorer.score_batch(raw_products)
                return ExtractionResult(
                    products=raw_products,
                    tier=extraction_tier,
                    quality_score=quality_score,
                    urls_attempted=len(urls),
                    audit=audit.to_summary_dict(),
                )

            # Fall back to public WooCommerce Store API
            extractor = WooCommerceAPIExtractor()
            extraction_tier = ExtractionTier.API
            await self.progress.set_metadata(job_id, extraction_tier=extraction_tier.value)
            raw_products = await self._extract_with_circuit_breaker(
                extractor, shop_url, shop_url
            )
            if raw_products:
                ExtractionTracker.tag_products_with_source(raw_products, shop_url)
                tracker.record_success(shop_url, len(raw_products))
                await self._emit_extraction_metadata(job_id, raw_products, tracker)
            else:
                tracker.record_empty(shop_url)
            # Fallback to full chain on discovered URLs if API returned nothing
            if not raw_products and urls:
                logger.info("WooCommerce API returned 0 products, falling back to extraction chain")
                raw_products, extraction_tier = await self._extract_with_fallback_chain(
                    urls, shop_url, job_id, tracker=tracker
                )
            raw_products = await self._supplement_gtin_if_needed(
                raw_products, platform, shop_url, job_id
            )

        elif platform == Platform.MAGENTO:
            # Try authenticated Magento Admin API first (provides GTIN from custom attrs)
            oauth_result = await self._try_oauth_admin_extraction(
                platform, shop_url, job_id, tracker
            )
            if oauth_result is not None:
                raw_products, extraction_tier = oauth_result
                audit = tracker.build_audit()
                quality_score = self.quality_scorer.score_batch(raw_products)
                return ExtractionResult(
                    products=raw_products,
                    tier=extraction_tier,
                    quality_score=quality_score,
                    urls_attempted=len(urls),
                    audit=audit.to_summary_dict(),
                )

            # Fall back to unauthenticated public API then scraping chain
            extractor = MagentoAPIExtractor()
            extraction_tier = ExtractionTier.API
            await self.progress.set_metadata(job_id, extraction_tier=extraction_tier.value)
            raw_products = await self._extract_with_circuit_breaker(
                extractor, shop_url, shop_url
            )
            if raw_products:
                ExtractionTracker.tag_products_with_source(raw_products, shop_url)
                tracker.record_success(shop_url, len(raw_products))
                await self._emit_extraction_metadata(job_id, raw_products, tracker)
            else:
                tracker.record_empty(shop_url)
            # Fallback to full chain on discovered URLs if API returned nothing
            if not raw_products and urls:
                logger.info("Magento API returned 0 products, falling back to extraction chain")
                raw_products, extraction_tier = await self._extract_with_fallback_chain(
                    urls, shop_url, job_id, tracker=tracker
                )
            raw_products = await self._supplement_gtin_if_needed(
                raw_products, platform, shop_url, job_id
            )

        elif platform == Platform.BIGCOMMERCE:
            # Try authenticated BigCommerce Admin API first
            oauth_result = await self._try_oauth_admin_extraction(
                platform, shop_url, job_id, tracker
            )
            if oauth_result is not None:
                raw_products, extraction_tier = oauth_result
                audit = tracker.build_audit()
                quality_score = self.quality_scorer.score_batch(raw_products)
                return ExtractionResult(
                    products=raw_products,
                    tier=extraction_tier,
                    quality_score=quality_score,
                    urls_attempted=len(urls),
                    audit=audit.to_summary_dict(),
                )

            # Fallback to scraping chain
            raw_products, extraction_tier = await self._extract_with_fallback_chain(
                urls, shop_url, job_id, css_schema=BIGCOMMERCE_SCHEMA, tracker=tracker
            )

        elif platform == Platform.SHOPWARE:
            # Try authenticated Shopware Admin API first
            oauth_result = await self._try_oauth_admin_extraction(
                platform, shop_url, job_id, tracker
            )
            if oauth_result is not None:
                raw_products, extraction_tier = oauth_result
                audit = tracker.build_audit()
                quality_score = self.quality_scorer.score_batch(raw_products)
                return ExtractionResult(
                    products=raw_products,
                    tier=extraction_tier,
                    quality_score=quality_score,
                    urls_attempted=len(urls),
                    audit=audit.to_summary_dict(),
                )

            # Fallback to scraping chain
            raw_products, extraction_tier = await self._extract_with_fallback_chain(
                urls, shop_url, job_id, tracker=tracker
            )

        else:  # Platform.GENERIC
            raw_products, extraction_tier = await self._extract_with_fallback_chain(
                urls, shop_url, job_id, tracker=tracker
            )

        audit = tracker.build_audit()
        quality_score = self.quality_scorer.score_batch(raw_products)
        return ExtractionResult(
            products=raw_products,
            tier=extraction_tier,
            quality_score=quality_score,
            urls_attempted=len(urls),
            audit=audit.to_summary_dict(),
        )

    async def _extract_with_fallback_chain(
        self,
        urls: list[str],
        shop_url: str,
        job_id: str,
        css_schema: dict | None = None,
        *,
        tracker: ExtractionTracker,
    ) -> tuple[list[dict], ExtractionTier]:
        """Try extraction strategies in priority order with cross-tier field merging.

        Probes tiers sequentially. Once an acceptable tier is found, commits to
        full extraction with it and merges supplementary fields from any partial
        results collected during earlier (failed) probes.

        Priority: Schema.org > OpenGraph > SmartCSS > LLM > CSS

        Args:
            urls: List of URLs to extract from
            shop_url: Base shop URL (for rate limiting domain)
            job_id: Job identifier for progress tracking
            css_schema: Optional CSS schema (uses GENERIC_SCHEMA if None)
            tracker: ExtractionTracker for per-URL outcome recording

        Returns:
            Tuple of (raw_products, extraction_tier)
        """
        if not urls:
            return [], ExtractionTier.DEEP_CRAWL

        probe_url = urls[0]
        total_urls = len(urls)
        # Partial results from probed tiers (for merging into winning tier)
        partial_probes: list[dict] = []

        async def _set_probe_step(tier_name: str) -> None:
            await self.progress.update(
                job_id=job_id,
                processed=0,
                total=total_urls,
                status=JobStatus.EXTRACTING,
                current_step=f"Probing {tier_name} tier on sample URL",
            )

        async def _commit_tier(tier: ExtractionTier) -> None:
            await self.progress.set_metadata(job_id, extraction_tier=tier.value)

        # Tier 2: UnifiedCrawl (replaces separate Schema.org + OpenGraph probes)
        # One crawl extracts JSON-LD, OG tags, markdown price, and media images.
        await _set_probe_step("UnifiedCrawl")
        unified_extractor = UnifiedCrawlExtractor(
            http_client=self._http_client,
        )
        unified_products = await self._extract_with_circuit_breaker(
            unified_extractor, probe_url, shop_url
        )
        if self._probe_acceptable(unified_products, "UnifiedCrawl"):
            await _commit_tier(ExtractionTier.UNIFIED_CRAWL)
            products = await self._extract_from_urls_tracked(
                unified_extractor, urls, shop_url, job_id, tracker
            )
            if partial_probes:
                products = self._merge_tier_fields(products, partial_probes)
            return products, ExtractionTier.UNIFIED_CRAWL
        if unified_products:
            partial_probes.extend(unified_products)

        # Tier 4: SmartCSS (auto-generated selectors, if configured)
        if self.smart_css:
            await _set_probe_step("SmartCSS")
            smart_products = await self._extract_with_circuit_breaker(self.smart_css, probe_url, shop_url)
            if self._probe_acceptable(smart_products, "SmartCSS"):
                await _commit_tier(ExtractionTier.SMART_CSS)
                products = await self._extract_from_urls_tracked(
                    self.smart_css, urls, shop_url, job_id, tracker
                )
                if partial_probes:
                    products = self._merge_tier_fields(products, partial_probes)
                return products, ExtractionTier.SMART_CSS
            if smart_products:
                partial_probes.extend(smart_products)
        else:
            logger.warning("SmartCSS extractor not configured -- skipping Tier 4")

        # Tier 5: LLM extraction (universal fallback, if configured)
        if self.llm_extractor:
            await _set_probe_step("LLM")
            llm_products = await self._extract_with_circuit_breaker(self.llm_extractor, probe_url, shop_url)
            if self._probe_acceptable(llm_products, "LLM"):
                await _commit_tier(ExtractionTier.LLM)
                products = await self._extract_from_urls_tracked(
                    self.llm_extractor, urls, shop_url, job_id, tracker
                )
                if partial_probes:
                    products = self._merge_tier_fields(products, partial_probes)
                return products, ExtractionTier.LLM
        else:
            logger.warning("LLM extractor not configured -- skipping Tier 5")

        # Fallback: hardcoded CSS (for when no tier probe was acceptable)
        schema = css_schema or GENERIC_SCHEMA
        await _commit_tier(ExtractionTier.DEEP_CRAWL)
        await self.progress.update(
            job_id=job_id,
            processed=0,
            total=total_urls,
            status=JobStatus.EXTRACTING,
            current_step="Falling back to CSS extraction",
        )
        css_extractor = CSSExtractor(schema)
        products = await self._extract_from_urls_tracked(
            css_extractor, urls, shop_url, job_id, tracker
        )
        if partial_probes:
            products = self._merge_tier_fields(products, partial_probes)
        return products, ExtractionTier.DEEP_CRAWL

    @staticmethod
    def _is_value_present(val: object) -> bool:
        """Return True if val is non-None and non-empty (string/list/dict aware)."""
        if val is None:
            return False
        if isinstance(val, str) and not val.strip():
            return False
        if isinstance(val, (list, dict)) and not val:
            return False
        return True

    @staticmethod
    def _merge_tier_fields(
        primary: list[dict], supplementary: list[dict]
    ) -> list[dict]:
        """Merge non-empty fields from supplementary tier probes into primary products.

        For each product in primary, fills empty/missing fields with values from
        supplementary dicts. Primary values are never overwritten.

        Args:
            primary: Products from the best tier (full extraction)
            supplementary: Products from other tier probes (single-URL probe results)

        Returns:
            Primary products with gaps filled from supplementary data
        """
        if not supplementary or not primary:
            return primary

        merged_supplement: dict[str, object] = {}
        for supp in supplementary:
            for key, val in supp.items():
                if key in merged_supplement:
                    # Deep-merge offers dicts to preserve fields from both tiers
                    if key == "offers" and isinstance(val, dict) and isinstance(merged_supplement[key], dict):
                        for k, v in val.items():
                            if k not in merged_supplement[key] and Pipeline._is_value_present(v):
                                merged_supplement[key][k] = v  # type: ignore[union-attr]
                    continue
                if Pipeline._is_value_present(val):
                    merged_supplement[key] = val

        if not merged_supplement:
            return primary

        for product in primary:
            for key, val in merged_supplement.items():
                existing = product.get(key)
                if not Pipeline._is_value_present(existing):
                    product[key] = val
                elif key == "offers" and isinstance(val, dict) and isinstance(existing, dict):
                    # Deep-merge offers: fill missing fields without overwriting
                    for k, v in val.items():
                        if k not in existing and Pipeline._is_value_present(v):
                            existing[k] = v

        return primary

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
            "%s probe successful: %d products, quality %.2f -- committing to full extraction",
            tier_name, len(products), quality,
        )
        return True

    async def _extract_with_circuit_breaker(
        self, extractor, url: str, domain: str
    ) -> list[dict]:
        """Extract products using circuit breaker for fault tolerance.

        CircuitOpenError is caught separately and treated as a silent skip
        (logged at WARNING, returns []). Other exceptions are re-raised so the
        caller can decide how to handle them.

        Unwraps ExtractorResult — callers receive plain list[dict].

        Args:
            extractor: Extractor instance
            url: URL to extract from
            domain: Domain for circuit breaker tracking

        Returns:
            List of raw product dicts
        """

        async def extract_fn():
            result = await extractor.extract(url)
            return result.products

        try:
            return await self.circuit_breaker.call(domain, extract_fn)
        except CircuitOpenError:
            logger.warning("Circuit breaker OPEN for %s, skipping %s", domain, url)
            return []
        except Exception as e:
            logger.error("Extraction failed for %s: %s", url, e)
            raise

    async def _fetch_html(self, url: str) -> str | None:
        """Fetch raw HTML for page validation (lightweight httpx, no browser).

        Returns HTML string on success, None on any failure or if the response
        exceeds MAX_RESPONSE_SIZE.
        """
        client = self._http_client
        owns_client = client is None
        if owns_client:
            client = self._create_http_client()
        try:
            resp = await client.get(url)
            if resp.status_code < 400:
                content_length = int(resp.headers.get("content-length", 0))
                if content_length > MAX_RESPONSE_SIZE:
                    logger.warning(
                        "Response too large (%d bytes) from %s, skipping",
                        content_length,
                        url,
                    )
                    return None
                html = resp.text
                if len(html) > MAX_RESPONSE_SIZE:
                    logger.warning(
                        "Response body too large (%d chars) from %s, skipping",
                        len(html),
                        url,
                    )
                    return None
                return html
        except Exception as e:
            logger.debug("HTML fetch for validation failed for %s: %s", url, e)
        finally:
            if owns_client:
                await client.aclose()
        return None

    @staticmethod
    def _has_batch_extraction(extractor) -> bool:
        """Check if extractor overrides extract_batch with a non-default implementation.

        Browser-based extractors (CSS, SmartCSS, LLM) override extract_batch()
        to use arun_many() with a single shared browser, which is much more
        efficient than spawning per-URL browser instances.
        """
        ext_type = type(extractor)
        return (
            isinstance(extractor, BaseExtractor)
            and hasattr(ext_type, "extract_batch")
            and ext_type.extract_batch is not BaseExtractor.extract_batch
        )

    async def _extract_from_urls_tracked(
        self,
        extractor,
        urls: list[str],
        domain: str,
        job_id: str,
        tracker: ExtractionTracker,
    ) -> list[dict]:
        """Extract products from URLs with source tagging, outcome tracking, and concurrency.

        Routes through two paths:
        - **Batch path**: if extractor overrides extract_batch() (browser-based extractors),
          sends URL batches through extract_batch() for single-browser efficiency.
        - **Per-URL path**: otherwise, uses asyncio.gather with per-URL extract() calls.

        After all URLs are processed, checks for a catastrophic error rate:
        if >70% of URLs errored (and at least 4 URLs were attempted), raises
        ExtractionError to abort the pipeline.

        Args:
            extractor: Extractor instance
            urls: List of URLs to extract from
            domain: Domain for circuit breaker tracking
            job_id: Job identifier for progress tracking
            tracker: ExtractionTracker for outcome recording

        Returns:
            List of raw product dicts from all URLs
        """
        if self._has_batch_extraction(extractor):
            return await self._extract_batch_tracked(
                extractor, urls, domain, job_id, tracker
            )
        return await self._extract_per_url_tracked(
            extractor, urls, domain, job_id, tracker
        )

    async def _extract_batch_tracked(
        self,
        extractor,
        urls: list[str],
        domain: str,
        job_id: str,
        tracker: ExtractionTracker,
    ) -> list[dict]:
        """Batch extraction path for browser-based extractors.

        Sends URL batches through extract_batch() which uses a single browser
        instance with arun_many(). Circuit breaker wraps the entire batch.
        Per-URL tracking is inferred from product source URLs.
        """
        total = len(urls)
        all_products: list[dict] = []

        for i in range(0, total, _EXTRACTION_CONCURRENCY):
            batch_urls = urls[i : i + _EXTRACTION_CONCURRENCY]

            try:
                async def batch_fn(batch=batch_urls):
                    result = await extractor.extract_batch(batch)
                    return result.products

                async with self.rate_limiter.acquire(domain):
                    products = await self.circuit_breaker.call(domain, batch_fn)

                if products:
                    # Tag each product with its source URL (best effort from product_url field)
                    for product in products:
                        src = product.get("product_url") or product.get("url", "")
                        if src:
                            product[SOURCE_URL_KEY] = src
                    # Record batch-level success per URL that yielded products
                    seen_urls: set[str] = set()
                    for product in products:
                        src = product.get(SOURCE_URL_KEY, "")
                        if src and src not in seen_urls:
                            seen_urls.add(src)
                    for url in batch_urls:
                        if url in seen_urls:
                            url_products = [
                                p for p in products if p.get(SOURCE_URL_KEY) == url
                            ]
                            tracker.record_success(url, len(url_products))
                        else:
                            tracker.record_empty(url)
                    all_products.extend(products)
                else:
                    for url in batch_urls:
                        tracker.record_empty(url)

            except CircuitOpenError:
                logger.warning("Circuit breaker OPEN for %s, skipping batch", domain)
                break
            except Exception as e:
                logger.error("Batch extraction failed for %s: %s", domain, e)
                for url in batch_urls:
                    tracker.record_error(url, str(e))

            processed = min(i + len(batch_urls), total)
            await self.progress.update(
                job_id=job_id,
                processed=processed,
                total=total,
                status=JobStatus.EXTRACTING,
                current_step=f"Extracted {processed}/{total} URLs, got {len(all_products)} products",
            )
            await self._emit_extraction_metadata(job_id, all_products, tracker)

        # Catastrophic error rate detection
        audit = tracker.build_audit()
        if audit.urls_attempted > 3 and audit.urls_errored / audit.urls_attempted > 0.7:
            error_rate = audit.urls_errored / audit.urls_attempted
            raise ExtractionError(
                f"Catastrophic error rate: {error_rate:.0%} of {audit.urls_attempted} URLs failed"
            )

        return all_products

    async def _extract_per_url_tracked(
        self,
        extractor,
        urls: list[str],
        domain: str,
        job_id: str,
        tracker: ExtractionTracker,
    ) -> list[dict]:
        """Per-URL extraction path for HTTP-based extractors (Schema.org, OpenGraph).

        Processes URLs in batches of _EXTRACTION_CONCURRENCY using asyncio.gather.
        Each URL gets its own circuit-breaker-wrapped extract() call.
        """
        total = len(urls)
        all_products: list[dict] = []

        async def _extract_one(url: str) -> list[dict]:
            try:
                async def fn():
                    result = await extractor.extract(url)
                    return result.products

                async with self.rate_limiter.acquire(domain):
                    products = await self.circuit_breaker.call(domain, fn)
                if products:
                    ExtractionTracker.tag_products_with_source(products, url)
                    tracker.record_success(url, len(products))
                    return products

                # Empty result -- validate whether URL is actually a product page
                html = await self._fetch_html(url)
                if html:
                    validation = self.page_validator.validate(html, url)
                    if not validation.is_product_page:
                        tracker.record_not_product(url)
                        return []

                tracker.record_empty(url)
                return []
            except CircuitOpenError:
                logger.warning("Circuit breaker OPEN for %s, skipping %s", domain, url)
                tracker.record_error(url, "circuit_breaker_open")
                return []
            except Exception as e:
                logger.error("Extraction failed for %s: %s", url, e)
                tracker.record_error(url, str(e))
                return []

        for i in range(0, total, _EXTRACTION_CONCURRENCY):
            batch = urls[i : i + _EXTRACTION_CONCURRENCY]
            results = await asyncio.gather(*[_extract_one(u) for u in batch])
            for products in results:
                all_products.extend(products)

            processed = min(i + len(batch), total)
            await self.progress.update(
                job_id=job_id,
                processed=processed,
                total=total,
                status=JobStatus.EXTRACTING,
                current_step=f"Extracted {processed}/{total} URLs, got {len(all_products)} products",
            )
            await self._emit_extraction_metadata(job_id, all_products, tracker)

        # Catastrophic error rate detection: abort if >70% of URLs failed
        audit = tracker.build_audit()
        if audit.urls_attempted > 3 and audit.urls_errored / audit.urls_attempted > 0.7:
            error_rate = audit.urls_errored / audit.urls_attempted
            raise ExtractionError(
                f"Catastrophic error rate: {error_rate:.0%} of {audit.urls_attempted} URLs failed"
            )

        return all_products

    async def _targeted_reextract(
        self,
        raw_products: list[dict],
        plan,
        shop_url: str,
        platform: Platform | None = None,
    ) -> list[dict]:
        """Re-extract missing fields from specific URLs using targeted extractors.

        - Missing price -> try SchemaOrgExtractor, then browser CSS as fallback
        - Missing image -> try OpenGraphExtractor

        The browser CSS fallback uses wait_until="networkidle" to capture
        JS-rendered prices (e.g. WooCommerce sites that populate prices via AJAX).

        Merges filled fields back into the original products without overwriting.
        Capped at _MAX_REEXTRACTION_URLS (enforced by caller).

        Args:
            raw_products: Original product list (mutated in place)
            plan: ReextractionPlan from CompletenessChecker
            shop_url: Domain for circuit breaker

        Returns:
            Same product list with gaps filled where possible
        """
        url_to_indices: dict[str, list[int]] = {}
        for i, product in enumerate(raw_products):
            src = product.get(SOURCE_URL_KEY, "")
            if src:
                url_to_indices.setdefault(src, []).append(i)

        async def _reextract_url(extractor, url: str) -> tuple[str, list[dict]]:
            try:
                supplement = await self._extract_with_circuit_breaker(
                    extractor, url, shop_url
                )
            except Exception as e:
                logger.warning("Re-extraction failed for %s: %s", url, e)
                supplement = []
            return url, supplement

        # Re-extract missing prices and images via UnifiedCrawl
        # Combines JSON-LD + OG + markdown in a single pass per URL
        urls_needing_reextract = set()
        if plan.urls_needing_price:
            urls_needing_reextract.update(plan.urls_needing_price)
        if plan.urls_needing_image:
            urls_needing_reextract.update(plan.urls_needing_image)

        if urls_needing_reextract:
            unified_extractor = UnifiedCrawlExtractor(
                http_client=self._http_client,
            )
            results = await asyncio.gather(
                *[_reextract_url(unified_extractor, u) for u in urls_needing_reextract]
            )
            for url, supplement in results:
                if supplement:
                    self._fill_missing_fields(
                        raw_products, url_to_indices.get(url, []), supplement
                    )

            # Browser CSS fallback for URLs still missing prices after UnifiedCrawl.
            # Captures JS-rendered prices (e.g. WooCommerce sites that populate
            # prices via AJAX after initial page load).
            if plan.urls_needing_price:
                still_needing_price = self._urls_still_missing_price(
                    raw_products, plan.urls_needing_price, url_to_indices
                )
                if still_needing_price:
                    logger.info(
                        "Browser CSS fallback: %d URLs still missing price after UnifiedCrawl",
                        len(still_needing_price),
                    )
                    await self._browser_price_reextract(
                        raw_products, still_needing_price, url_to_indices, shop_url, platform
                    )

        return raw_products

    @staticmethod
    def _urls_still_missing_price(
        products: list[dict],
        candidate_urls: list[str],
        url_to_indices: dict[str, list[int]],
    ) -> list[str]:
        """Return URLs whose products still have no valid price after Schema.org re-extraction."""
        price_fields = ("price", "og:price:amount", "offers")
        still_missing: list[str] = []
        for url in candidate_urls:
            indices = url_to_indices.get(url, [])
            if not indices:
                continue
            # If ALL products for this URL are still missing a price, include it
            all_missing = True
            for idx in indices:
                if idx >= len(products):
                    continue
                product = products[idx]
                for field_name in price_fields:
                    val = product.get(field_name)
                    if val is not None:
                        if isinstance(val, dict):
                            inner = val.get("price")
                            if inner is not None:
                                try:
                                    if float(inner) != 0:
                                        all_missing = False
                                        break
                                except (ValueError, TypeError):
                                    pass
                        elif isinstance(val, (int, float)):
                            if val != 0:
                                all_missing = False
                                break
                        elif isinstance(val, str):
                            try:
                                if float(val.strip().replace(",", ".")) != 0:
                                    all_missing = False
                                    break
                            except ValueError:
                                pass
                if not all_missing:
                    break
            if all_missing:
                still_missing.append(url)
        return still_missing

    async def _browser_price_reextract(
        self,
        raw_products: list[dict],
        urls: list[str],
        url_to_indices: dict[str, list[int]],
        shop_url: str,
        platform: Platform | None = None,
    ) -> None:
        """Re-extract prices using browser-rendered CSS extraction.

        Selects the correct CSS schema for the detected platform and wraps
        each extraction in the circuit breaker for consistent protection.
        """
        from app.extractors.schemas.woocommerce import WOOCOMMERCE_SCHEMA
        from app.extractors.schemas.shopify import SHOPIFY_SCHEMA

        # Select platform-appropriate schema (#87)
        if platform == Platform.SHOPIFY:
            schema = SHOPIFY_SCHEMA
        elif platform == Platform.BIGCOMMERCE:
            schema = BIGCOMMERCE_SCHEMA
        elif platform == Platform.WOOCOMMERCE:
            schema = WOOCOMMERCE_SCHEMA
        else:
            schema = GENERIC_SCHEMA

        css_extractor = CSSExtractor(schema)

        for url in urls:
            try:
                supplement = await self._extract_with_circuit_breaker(
                    css_extractor, url, shop_url
                )
            except (CircuitOpenError, Exception) as e:
                logger.warning("Browser price re-extraction failed for %s: %s", url, e)
                supplement = []

            if supplement:
                self._fill_missing_fields(
                    raw_products, url_to_indices.get(url, []), supplement
                )

    @staticmethod
    def _fill_missing_fields(
        products: list[dict],
        indices: list[int],
        supplement: list[dict],
    ) -> None:
        """Fill empty/missing fields in products at given indices from supplement data.

        Same merge logic as _merge_tier_fields but targeted to specific products
        and skips private (_-prefixed) keys. Never overwrites existing non-empty values.
        """
        if not supplement or not indices:
            return

        merged: dict[str, object] = {}
        for supp in supplement:
            for key, val in supp.items():
                if key in merged or key.startswith("_"):
                    continue
                if Pipeline._is_value_present(val):
                    merged[key] = val

        if not merged:
            return

        _IMAGE_FIELDS = {"image_url", "image", "og:image", "additional_images"}

        for idx in indices:
            if idx >= len(products):
                continue
            product = products[idx]
            # API-sourced products: only fill image-related fields
            source = product.get("_source", "")
            api_sourced = "admin_api" in source if isinstance(source, str) else False
            for key, val in merged.items():
                if api_sourced and key not in _IMAGE_FIELDS:
                    continue
                if not Pipeline._is_value_present(product.get(key)):
                    product[key] = val

    async def _supplement_gtin_if_needed(
        self,
        raw_products: list[dict],
        platform: Platform,
        shop_url: str,
        job_id: str,
    ) -> list[dict]:
        """Run GTIN supplementation if needed. Never crashes the pipeline."""
        if not raw_products or not self._should_supplement_gtin(raw_products, platform):
            return raw_products
        try:
            await self.progress.update(
                job_id=job_id,
                processed=0,
                total=len(raw_products),
                status=JobStatus.EXTRACTING,
                current_step="Supplementing GTIN/EAN data",
            )
            if self._http_client is None:
                logger.error("HTTP client not initialized, skipping GTIN supplementation")
                return raw_products
            supplementer = GTINSupplementer(self._http_client)
            return await supplementer.supplement(raw_products, shop_url)
        except Exception as e:
            logger.error(
                "GTIN supplementation failed for %s (continuing without GTINs): %s",
                shop_url,
                e,
            )
            return raw_products

    @staticmethod
    def _should_supplement_gtin(products: list[dict], platform: Platform) -> bool:
        """Return True if GTIN supplementation should run.

        WooCommerce Store API never returns barcodes, so always supplement.
        For Shopify and Magento, only supplement when fewer than 10% of products
        already carry a GTIN (avoids redundant fetches when the API does provide them).
        """
        if platform == Platform.WOOCOMMERCE:
            return True
        if not products:
            return False
        gtin_count = sum(1 for p in products if p.get("gtin"))
        return gtin_count / len(products) < 0.1
