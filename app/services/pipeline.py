"""Pipeline orchestrator for merchant onboarding process.

Orchestrates the complete onboarding flow: detection → discovery → extraction → normalization → ingestion.
Contains NO business logic itself - only calls components in order.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import httpx

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
from app.services.completeness_checker import CompletenessChecker
from app.services.extraction_tracker import SOURCE_URL_KEY, ExtractionTracker
from app.services.extraction_validator import ExtractionValidator
from app.services.page_validator import ProductPageValidator
from app.services.platform_detector import PlatformDetector
from app.services.product_normalizer import ProductNormalizer
from app.services.reconciliation_reporter import ReconciliationReporter
from app.services.url_discovery import URLDiscoveryService
from app.services.url_normalizer import normalize_shop_url

if TYPE_CHECKING:
    from app.db.bulk_ingestor import BulkIngestor
    from app.extractors.llm_extractor import LLMExtractor
    from app.extractors.smart_css_extractor import SmartCSSExtractor
    from app.infra.circuit_breaker import CircuitBreaker
    from app.infra.progress_tracker import ProgressTracker
    from app.infra.rate_limiter import RateLimiter

logger = logging.getLogger(__name__)

# Pipeline-level timeout: 30 minutes max for any single job
_PIPELINE_TIMEOUT_SECONDS = 30 * 60

# Max URLs for targeted re-extraction (completeness pass)
_MAX_REEXTRACTION_URLS = 50

# Concurrent extraction batch size (URLs processed in parallel per batch)
_EXTRACTION_CONCURRENCY = 10


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
        self.completeness_checker = CompletenessChecker()
        self.reconciliation_reporter = ReconciliationReporter()
        self.page_validator = ProductPageValidator()
        self.progress = progress_tracker
        self.circuit_breaker = circuit_breaker
        self.rate_limiter = rate_limiter
        self.ingestor = bulk_ingestor
        self.smart_css = smart_css_extractor
        self.llm_extractor = llm_extractor

    async def run(
        self, job_id: str, shop_url: str, timeout: int = _PIPELINE_TIMEOUT_SECONDS
    ) -> dict:
        """Run the full pipeline: detect → discover → extract → normalize → ingest.

        Args:
            job_id: Unique job identifier for progress tracking
            shop_url: Merchant shop URL to onboard
            timeout: Max seconds before the pipeline is killed (default 30 min)

        Returns:
            Summary dict with platform, counts, and extraction tier
        """
        try:
            return await asyncio.wait_for(
                self._run_inner(job_id, shop_url), timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.error("Pipeline timed out after %ds for job %s", timeout, job_id)
            await self.progress.update(
                job_id=job_id,
                processed=0,
                total=0,
                status=JobStatus.FAILED,
                current_step="Pipeline failed",
                error=f"Pipeline timed out after {timeout // 60} minutes",
            )
            raise

    async def _run_inner(self, job_id: str, shop_url: str) -> dict:
        """Inner pipeline logic wrapped by run() with timeout."""
        shop_url = normalize_shop_url(shop_url)
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
            await self.progress.set_metadata(job_id, extraction_tier=extraction_tier.value)

            # Step 3c: Verify data completeness + targeted re-extraction
            await self.progress.update(
                job_id=job_id,
                processed=0,
                total=len(raw_products),
                status=JobStatus.VERIFYING,
                current_step="Checking data completeness",
            )

            results = self.completeness_checker.check_batch(raw_products)
            plan = self.completeness_checker.build_reextraction_plan(results)

            reextract_urls = len(set(plan.urls_needing_price) | set(plan.urls_needing_image))
            if reextract_urls > 0 and reextract_urls <= _MAX_REEXTRACTION_URLS:
                logger.info(
                    "Targeted re-extraction: %d incomplete products across %d URLs",
                    plan.total_incomplete,
                    reextract_urls,
                )
                raw_products = await self._targeted_reextract(
                    raw_products, plan, shop_url
                )

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

            # Step 4b: Reconciliation report
            audit = extraction_result.audit
            report = self.reconciliation_reporter.generate(
                discovered_urls=urls,
                audit_summary=audit,
                products_normalized=len(normalized_products),
            )
            await self.progress.set_metadata(
                job_id,
                reconciliation_report=report.to_json(),
                coverage_percentage=round(report.coverage_percentage, 2),
            )

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
            await self.progress.set_metadata(
                job_id,
                completed_at=datetime.now(timezone.utc).isoformat(),
                products_count=len(normalized_products),
            )

            logger.info(f"Pipeline completed for job {job_id}")

            return {
                "platform": platform.value,
                "total_extracted": len(raw_products),
                "total_normalized": len(normalized_products),
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

        # Select extractor based on platform
        if platform == Platform.SHOPIFY:
            extractor = ShopifyAPIExtractor()
            extraction_tier = ExtractionTier.API
            await self.progress.set_metadata(job_id, extraction_tier=extraction_tier.value)
            raw_products = await self._extract_with_circuit_breaker(
                extractor, shop_url, shop_url
            )
            if raw_products:
                ExtractionTracker.tag_products_with_source(raw_products, shop_url)
                tracker.record_success(shop_url, len(raw_products))
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
                    raw_products = await self._supplement_shopify_prices(
                        raw_products, shop_url
                    )

        elif platform == Platform.WOOCOMMERCE:
            extractor = WooCommerceAPIExtractor()
            extraction_tier = ExtractionTier.API
            await self.progress.set_metadata(job_id, extraction_tier=extraction_tier.value)
            raw_products = await self._extract_with_circuit_breaker(
                extractor, shop_url, shop_url
            )
            if raw_products:
                ExtractionTracker.tag_products_with_source(raw_products, shop_url)
                tracker.record_success(shop_url, len(raw_products))
            else:
                tracker.record_empty(shop_url)
            # Fallback to full chain on discovered URLs if API returned nothing
            if not raw_products and urls:
                logger.info("WooCommerce API returned 0 products, falling back to extraction chain")
                raw_products, extraction_tier = await self._extract_with_fallback_chain(
                    urls, shop_url, job_id, tracker=tracker
                )

        elif platform == Platform.MAGENTO:
            extractor = MagentoAPIExtractor()
            extraction_tier = ExtractionTier.API
            await self.progress.set_metadata(job_id, extraction_tier=extraction_tier.value)
            raw_products = await self._extract_with_circuit_breaker(
                extractor, shop_url, shop_url
            )
            if raw_products:
                ExtractionTracker.tag_products_with_source(raw_products, shop_url)
                tracker.record_success(shop_url, len(raw_products))
            else:
                tracker.record_empty(shop_url)
            # Fallback to full chain on discovered URLs if API returned nothing
            if not raw_products and urls:
                logger.info("Magento API returned 0 products, falling back to extraction chain")
                raw_products, extraction_tier = await self._extract_with_fallback_chain(
                    urls, shop_url, job_id, tracker=tracker
                )

        elif platform == Platform.BIGCOMMERCE:
            raw_products, extraction_tier = await self._extract_with_fallback_chain(
                urls, shop_url, job_id, css_schema=BIGCOMMERCE_SCHEMA, tracker=tracker
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
        tracker: ExtractionTracker | None = None,
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
            tracker: Optional ExtractionTracker for per-URL outcome recording

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

        # Tier 2: Schema.org on first URL
        await _set_probe_step("Schema.org")
        schema_extractor = SchemaOrgExtractor()
        schema_products = await self._extract_with_circuit_breaker(schema_extractor, probe_url, shop_url)
        if self._probe_acceptable(schema_products, "Schema.org"):
            await _commit_tier(ExtractionTier.SCHEMA_ORG)
            products = await self._extract_from_urls_tracked(
                schema_extractor, urls, shop_url, job_id, tracker
            )
            return products, ExtractionTier.SCHEMA_ORG
        if schema_products:
            partial_probes.extend(schema_products)

        # Tier 3: OpenGraph on first URL
        await _set_probe_step("OpenGraph")
        og_extractor = OpenGraphExtractor()
        og_products = await self._extract_with_circuit_breaker(og_extractor, probe_url, shop_url)
        if self._probe_acceptable(og_products, "OpenGraph"):
            await _commit_tier(ExtractionTier.OPENGRAPH)
            products = await self._extract_from_urls_tracked(
                og_extractor, urls, shop_url, job_id, tracker
            )
            if partial_probes:
                products = self._merge_tier_fields(products, partial_probes)
            return products, ExtractionTier.OPENGRAPH
        if og_products:
            partial_probes.extend(og_products)

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
            logger.warning("SmartCSS extractor not configured — skipping Tier 4")

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
            logger.warning("LLM extractor not configured — skipping Tier 5")

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
                    continue
                if Pipeline._is_value_present(val):
                    merged_supplement[key] = val

        if not merged_supplement:
            return primary

        for product in primary:
            for key, val in merged_supplement.items():
                if not Pipeline._is_value_present(product.get(key)):
                    product[key] = val

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

    async def _fetch_html(self, url: str) -> str | None:
        """Fetch raw HTML for page validation (lightweight httpx, no browser).

        Returns HTML string on success, None on any failure.
        """
        from app.extractors.browser_config import DEFAULT_HEADERS, get_default_user_agent

        headers = {**DEFAULT_HEADERS, "User-Agent": get_default_user_agent()}
        try:
            async with httpx.AsyncClient(
                follow_redirects=True, timeout=10.0, headers=headers
            ) as client:
                resp = await client.get(url)
                if resp.status_code < 400:
                    return resp.text
        except Exception as e:
            logger.debug("HTML fetch for validation failed for %s: %s", url, e)
        return None

    async def _extract_from_urls_tracked(
        self,
        extractor,
        urls: list[str],
        domain: str,
        job_id: str,
        tracker: ExtractionTracker,
    ) -> list[dict]:
        """Extract products per-URL with source tagging, outcome tracking, and concurrency.

        Processes URLs in batches of _EXTRACTION_CONCURRENCY using asyncio.gather.
        Each URL gets its own circuit-breaker-wrapped extract() call, enabling
        per-URL outcome recording and source URL tagging.

        Args:
            extractor: Extractor instance
            urls: List of URLs to extract from
            domain: Domain for circuit breaker tracking
            job_id: Job identifier for progress tracking
            tracker: ExtractionTracker for outcome recording

        Returns:
            List of raw product dicts from all URLs
        """
        total = len(urls)
        all_products: list[dict] = []

        async def _extract_one(url: str) -> list[dict]:
            try:
                async def fn():
                    return await extractor.extract(url)

                products = await self.circuit_breaker.call(domain, fn)
                if products:
                    ExtractionTracker.tag_products_with_source(products, url)
                    tracker.record_success(url, len(products))
                    return products

                # Empty result — validate whether URL is actually a product page
                html = await self._fetch_html(url)
                if html:
                    validation = self.page_validator.validate(html, url)
                    if not validation.is_product_page:
                        tracker.record_not_product(url)
                        return []

                tracker.record_empty(url)
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

        return all_products

    async def _targeted_reextract(
        self,
        raw_products: list[dict],
        plan,
        shop_url: str,
    ) -> list[dict]:
        """Re-extract missing fields from specific URLs using targeted extractors.

        - Missing price → try SchemaOrgExtractor
        - Missing image → try OpenGraphExtractor

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
            # _extract_with_circuit_breaker already swallows exceptions → returns []
            supplement = await self._extract_with_circuit_breaker(
                extractor, url, shop_url
            )
            return url, supplement

        # Concurrent re-extraction for missing prices via Schema.org
        if plan.urls_needing_price:
            schema_extractor = SchemaOrgExtractor()
            results = await asyncio.gather(
                *[_reextract_url(schema_extractor, u) for u in plan.urls_needing_price]
            )
            for url, supplement in results:
                if supplement:
                    self._fill_missing_fields(
                        raw_products, url_to_indices.get(url, []), supplement
                    )

        # Concurrent re-extraction for missing images via OpenGraph
        if plan.urls_needing_image:
            og_extractor = OpenGraphExtractor()
            results = await asyncio.gather(
                *[_reextract_url(og_extractor, u) for u in plan.urls_needing_image]
            )
            for url, supplement in results:
                if supplement:
                    self._fill_missing_fields(
                        raw_products, url_to_indices.get(url, []), supplement
                    )

        return raw_products

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

        for idx in indices:
            if idx >= len(products):
                continue
            product = products[idx]
            for key, val in merged.items():
                if not Pipeline._is_value_present(product.get(key)):
                    product[key] = val

    # ── Shopify API price supplementation ────────────────────────────────

    async def _supplement_shopify_prices(
        self, raw_products: list[dict], shop_url: str
    ) -> list[dict]:
        """Supplement Schema.org products with canonical Shopify API pricing.

        Fixes two issues for Shopify stores that fell back to Schema.org:
        1. Zero-price: JSON-LD may omit 'offers' entirely (geo-targeting/inventory).
        2. Geo-currency: JSON-LD may serve location-specific prices (e.g. EUR)
           instead of the merchant's base catalog currency.

        The Shopify /products.json API always returns canonical base pricing.
        """
        api_products = await self._fetch_shopify_api_products(shop_url)
        if not api_products:
            return raw_products

        # Build lookups by handle and normalised title
        api_by_handle: dict[str, dict] = {}
        api_by_title: dict[str, dict] = {}
        base_currency = api_products[0].get("_shop_currency", "USD")

        for ap in api_products:
            handle = ap.get("handle", "").lower().strip()
            title = ap.get("title", "").strip().lower()
            if handle:
                api_by_handle[handle] = ap
            if title:
                api_by_title[title] = ap

        filled_count = 0
        corrected_count = 0

        for product in raw_products:
            offers = product.get("offers", {})
            if isinstance(offers, list):
                offers = offers[0] if offers else {}
            if not isinstance(offers, dict):
                offers = {}

            price_raw = str(offers.get("price", "0")) if offers else "0"
            try:
                price_val = float(price_raw)
            except (ValueError, TypeError):
                price_val = 0.0

            schema_currency = (offers.get("priceCurrency") or "").upper()

            needs_price = price_val == 0
            needs_currency = bool(
                schema_currency
                and base_currency
                and schema_currency != base_currency.upper()
            )

            if not needs_price and not needs_currency:
                continue

            api_match = self._match_shopify_product(
                product, api_by_handle, api_by_title
            )
            if not api_match:
                continue

            variants = api_match.get("variants", [])
            api_price = variants[0].get("price", "0") if variants else "0"

            # Don't replace with zero from the API
            try:
                if float(api_price) == 0:
                    continue
            except (ValueError, TypeError):
                continue

            # Inject / update offers
            current_offers = product.get("offers")
            if not current_offers or (isinstance(current_offers, list) and not current_offers):
                product["offers"] = {
                    "price": api_price,
                    "priceCurrency": base_currency,
                    "availability": "https://schema.org/InStock",
                }
            elif isinstance(current_offers, dict):
                current_offers["price"] = api_price
                current_offers["priceCurrency"] = base_currency
            elif (
                isinstance(current_offers, list)
                and current_offers
                and isinstance(current_offers[0], dict)
            ):
                current_offers[0]["price"] = api_price
                current_offers[0]["priceCurrency"] = base_currency

            if needs_price:
                filled_count += 1
            if needs_currency:
                corrected_count += 1

        if filled_count or corrected_count:
            logger.info(
                "Shopify API supplementation: %d zero-price filled, %d geo-currency corrected (base: %s)",
                filled_count,
                corrected_count,
                base_currency,
            )
        return raw_products

    async def _fetch_shopify_api_products(self, shop_url: str) -> list[dict]:
        """Fetch products from Shopify API, trying alternative endpoints for headless stores.

        Headless Shopify stores (Hydrogen/custom) often block /products.json at
        the main domain but serve it from a ``shop.`` subdomain.
        """
        from urllib.parse import urlparse

        shopify_extractor = ShopifyAPIExtractor()

        # Try the main URL first
        products = await self._extract_with_circuit_breaker(
            shopify_extractor, shop_url, shop_url
        )
        if products:
            return products

        # Try shop.{base_domain} for headless Shopify stores
        parsed = urlparse(shop_url)
        base_domain = parsed.netloc.lower().removeprefix("www.")
        alt_url = f"{parsed.scheme}://shop.{base_domain}"

        products = await self._extract_with_circuit_breaker(
            shopify_extractor, alt_url, shop_url
        )
        if products:
            logger.info(
                "Shopify API found at alternative endpoint %s (%d products)",
                alt_url,
                len(products),
            )
            return products

        return []

    @staticmethod
    def _match_shopify_product(
        schema_product: dict,
        api_by_handle: dict[str, dict],
        api_by_title: dict[str, dict],
    ) -> dict | None:
        """Match a Schema.org product to a Shopify API product by URL handle or title."""
        # Primary: extract handle from product URL
        product_url = schema_product.get("url", "")
        if "/products/" in product_url:
            handle = (
                product_url.split("/products/")[-1]
                .rstrip("/")
                .split("?")[0]
                .lower()
            )
            if handle and handle in api_by_handle:
                return api_by_handle[handle]

        # Fallback: exact title match (case-insensitive)
        title = schema_product.get("name", "").strip().lower()
        if title and title in api_by_title:
            return api_by_title[title]

        return None
