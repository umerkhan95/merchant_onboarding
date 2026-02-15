"""Evaluation runner — orchestrates extractor runs and scoring.

Supported extraction tiers:
    1. schema_org - Extract from JSON-LD structured data (free)
    2. opengraph - Extract from OpenGraph meta tags (free)
    3. css_generic - Extract via generic CSS selectors (free)
    4. smart_css - Auto-generate CSS selectors per domain via LLM, cache and reuse (one-time LLM cost)
    5. llm - Universal LLM extraction, works on any website (LLM cost per page)

Default tiers (free): schema_org, opengraph, css_generic
All tiers (requires LLM_API_KEY): schema_org, opengraph, css_generic, smart_css, llm
"""

from __future__ import annotations

import logging
import time
import tracemalloc
from pathlib import Path

from evals.models import EvalReport, TestCase, TierResult
from evals.scorer import Scorer

logger = logging.getLogger(__name__)

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class EvalRunner:
    """Runs extractors against test cases and scores the results."""

    # Default tiers (free, no LLM cost)
    DEFAULT_TIERS = ["schema_org", "opengraph", "css_generic"]

    # All available tiers including LLM-based ones
    ALL_TIERS = ["schema_org", "opengraph", "css_generic", "smart_css", "llm"]

    def __init__(
        self,
        tiers: list[str] | None = None,
        force_offline: bool = False,
        force_live: bool = False,
        profile: bool = False,
    ):
        """Initialize the eval runner with a list of tiers to test.

        Args:
            tiers: List of tier names to test. Defaults to ["schema_org", "opengraph", "css_generic"]
            force_offline: If True, fail if snapshot is missing (never hit live URLs)
            force_live: If True, ignore snapshots and always hit live URLs
            profile: Enable memory profiling (slower). Default: False
        """
        self.tiers = tiers or self.DEFAULT_TIERS
        self.force_offline = force_offline
        self.force_live = force_live
        self.profile = profile

        if force_offline and force_live:
            raise ValueError("Cannot specify both force_offline and force_live")

    async def run(self, test_case: TestCase) -> EvalReport:
        """Run all configured tiers against a single test case.

        Args:
            test_case: The test case to evaluate

        Returns:
            EvalReport with results from all tiers
        """
        logger.info("Running eval for test case: %s", test_case.name)

        tier_results = []
        for tier_name in self.tiers:
            result = await self._run_tier(tier_name, test_case)
            tier_results.append(result)

        return EvalReport(
            test_case_name=test_case.name,
            url=test_case.url,
            platform=test_case.platform,
            tier_results=tier_results,
        )

    def _extract_offline(self, tier_name: str, html: str, url: str) -> list[dict]:
        """Extract products from saved HTML content.

        Args:
            tier_name: Name of the tier
            html: Raw HTML content
            url: URL for logging purposes

        Returns:
            List of extracted product dicts

        Raises:
            ValueError: If offline mode not supported for this tier
        """
        if tier_name == "schema_org":
            from app.extractors.schema_org_extractor import SchemaOrgExtractor
            return SchemaOrgExtractor.extract_from_html(html, url)

        elif tier_name == "opengraph":
            from app.extractors.opengraph_extractor import OpenGraphExtractor
            return OpenGraphExtractor.extract_from_html(html, url)

        else:
            raise ValueError(f"Offline mode not supported for tier: {tier_name}")

    def _get_product_urls(self, test_case: TestCase) -> list[str]:
        """Get individual product URLs from test case expected products.

        Falls back to the main test case URL if no product URLs are defined.
        """
        urls = []
        for product in test_case.products:
            if product.product_url:
                urls.append(product.product_url)
        return urls if urls else [test_case.url]

    async def _run_tier(self, tier_name: str, test_case: TestCase) -> TierResult:
        """Run a single tier extractor against a test case and score the results.

        Extracts from individual product URLs when available in the fixture,
        otherwise falls back to the main test case URL.

        Args:
            tier_name: Name of the tier to run
            test_case: The test case to evaluate

        Returns:
            TierResult with scores, timing, and error info
        """
        logger.info("Running tier '%s' for %s", tier_name, test_case.name)

        peak_memory_mb = None
        tokens_used = None
        estimated_cost = None

        try:
            # Create the extractor
            extractor = self._create_extractor(tier_name)

            # Check for offline HTML snapshot
            snapshot_html = None
            if test_case.html_file and not self.force_live:
                snapshot_path = FIXTURES_DIR / "snapshots" / test_case.html_file
                if snapshot_path.exists():
                    snapshot_html = snapshot_path.read_text(encoding="utf-8")
                    logger.info("Using offline snapshot: %s", snapshot_path.name)
                elif self.force_offline:
                    raise FileNotFoundError(
                        f"Offline mode enabled but snapshot not found: {snapshot_path}"
                    )

            # Start memory profiling if enabled
            if self.profile:
                tracemalloc.start()

            try:
                # Time the extraction
                start_time = time.monotonic()

                if snapshot_html and not self.force_live:
                    # Offline extraction from single snapshot
                    extracted_products = self._extract_offline(tier_name, snapshot_html, test_case.url)
                else:
                    # Live extraction — use individual product URLs when available
                    product_urls = self._get_product_urls(test_case)

                    # Browser-based tiers benefit from batch extraction (one browser, many URLs)
                    browser_tiers = {"css_generic", "smart_css", "llm"}
                    if tier_name in browser_tiers and len(product_urls) > 1:
                        extracted_products = await extractor.extract_batch(product_urls)
                    else:
                        extracted_products = []
                        for url in product_urls:
                            try:
                                products = await extractor.extract(url)
                                extracted_products.extend(products)
                            except Exception as e:
                                logger.warning("Extraction failed for %s: %s", url, e)

                duration = time.monotonic() - start_time

                # Get peak memory usage if profiling
                if self.profile:
                    _, peak = tracemalloc.get_traced_memory()
                    peak_memory_mb = peak / (1024 * 1024)

            finally:
                # Always stop tracemalloc if it was started
                if self.profile:
                    tracemalloc.stop()

            logger.info(
                "Tier '%s' extracted %d products in %.2fs",
                tier_name,
                len(extracted_products),
                duration,
            )

            # Score the results
            product_scores = Scorer.match_products(
                expected=test_case.products,
                extracted=extracted_products,
            )

            products_matched = len([ps for ps in product_scores if ps.field_scores])

            return TierResult(
                tier_name=tier_name,
                products_extracted=len(extracted_products),
                products_matched=products_matched,
                product_scores=product_scores,
                duration_seconds=duration,
                min_products=test_case.min_products,
                peak_memory_mb=peak_memory_mb,
                tokens_used=tokens_used,
                estimated_cost_usd=estimated_cost,
            )

        except Exception as e:
            logger.exception("Tier '%s' failed for %s: %s", tier_name, test_case.name, e)
            return TierResult(
                tier_name=tier_name,
                products_extracted=0,
                products_matched=0,
                product_scores=[],
                duration_seconds=0.0,
                error=str(e),
                min_products=test_case.min_products,
                peak_memory_mb=peak_memory_mb,
                tokens_used=tokens_used,
                estimated_cost_usd=estimated_cost,
            )

    def _create_extractor(self, tier_name: str):
        """Create an extractor instance for the given tier name.

        Args:
            tier_name: Name of the tier ("schema_org", "opengraph", "css_generic", "smart_css", "llm")

        Returns:
            Extractor instance

        Raises:
            ValueError: If tier_name is unknown
            ImportError: If tier dependencies are missing
        """
        if tier_name == "schema_org":
            from app.extractors.schema_org_extractor import SchemaOrgExtractor

            return SchemaOrgExtractor()

        elif tier_name == "opengraph":
            from app.extractors.opengraph_extractor import OpenGraphExtractor

            return OpenGraphExtractor()

        elif tier_name == "css_generic":
            from app.extractors.css_extractor import CSSExtractor
            from app.extractors.schemas.generic import GENERIC_SCHEMA

            return CSSExtractor(GENERIC_SCHEMA)

        elif tier_name == "smart_css":
            import os

            from app.config import settings
            from app.extractors.schema_cache import SchemaCache
            from app.extractors.smart_css_extractor import SmartCSSExtractor

            # Create LLM config from settings
            llm_config = settings.create_llm_config()
            if not llm_config:
                raise ValueError(
                    "SmartCSS tier requires LLM configuration. "
                    "Set LLM_API_KEY environment variable."
                )

            # Create Redis-backed schema cache
            try:
                import redis.asyncio as aioredis

                redis_client = aioredis.from_url(
                    settings.redis_url,
                    decode_responses=False,
                )
                cache = SchemaCache(redis_client=redis_client, ttl=settings.schema_cache_ttl)
            except Exception as e:
                logger.warning(
                    "Failed to initialize Redis for schema cache: %s. "
                    "Using in-memory fallback (no persistence).",
                    e,
                )
                # Fallback to in-memory cache
                from evals.memory_cache import InMemorySchemaCache

                cache = InMemorySchemaCache()

            return SmartCSSExtractor(llm_config=llm_config, schema_cache=cache)

        elif tier_name == "llm":
            from app.config import settings
            from app.extractors.llm_extractor import LLMExtractor

            # Create LLM config from settings
            llm_config = settings.create_llm_config()
            if not llm_config:
                raise ValueError(
                    "LLM tier requires LLM configuration. "
                    "Set LLM_API_KEY environment variable."
                )

            return LLMExtractor(
                llm_config=llm_config,
                temperature=settings.llm_temperature,
                max_tokens=settings.llm_max_tokens,
            )

        else:
            raise ValueError(f"Unknown tier: {tier_name}")

    async def run_all(self, test_cases: list[TestCase]) -> list[EvalReport]:
        """Run evaluation on multiple test cases sequentially.

        Args:
            test_cases: List of test cases to evaluate

        Returns:
            List of EvalReports, one per test case
        """
        reports = []
        for test_case in test_cases:
            report = await self.run(test_case)
            reports.append(report)

        return reports
