"""Pipeline-level evaluation runner.

Runs the full onboarding pipeline (detect → discover → extract → normalize)
against test cases and scores the output.

This differs from the tier-based EvalRunner by testing the complete end-to-end
pipeline as it would run in production, including platform detection, URL discovery,
and automatic tier fallback.
"""

from __future__ import annotations

import logging
import time
from unittest.mock import AsyncMock, MagicMock

from evals.models import EvalReport, TestCase, TierResult
from evals.scorer import Scorer

logger = logging.getLogger(__name__)


class PipelineEvalRunner:
    """Runs the full onboarding pipeline against test cases and scores results.

    This runner tests the complete pipeline flow:
    1. Platform detection
    2. URL discovery
    3. Product extraction (with tier fallback)
    4. Product normalization

    The pipeline returns normalized products, which we score against expected products
    to evaluate end-to-end extraction quality.
    """

    async def run(self, test_case: TestCase) -> EvalReport:
        """Run the full pipeline against a test case.

        Creates mock infrastructure (progress tracker, circuit breaker, rate limiter)
        and runs Pipeline.run() end-to-end.

        Args:
            test_case: The test case to evaluate

        Returns:
            EvalReport with pipeline results and scores
        """
        logger.info("Running pipeline eval for: %s", test_case.name)

        start = time.monotonic()
        try:
            # Create mock infrastructure components
            progress = self._create_mock_progress()
            circuit_breaker = self._create_mock_circuit_breaker()
            rate_limiter = self._create_mock_rate_limiter()

            # Import and create pipeline
            from app.services.pipeline import Pipeline

            pipeline = Pipeline(
                progress_tracker=progress,
                circuit_breaker=circuit_breaker,
                rate_limiter=rate_limiter,
                bulk_ingestor=None,  # Don't write to DB during evals
            )

            # Run the pipeline
            import uuid
            job_id = f"eval-{uuid.uuid4().hex[:8]}"

            # The pipeline returns normalized products via the normalizer
            # We need to capture them for scoring
            normalized_products = []
            original_normalize = pipeline.normalizer.normalize

            def capture_normalize(*args, **kwargs):
                """Capture normalized products for scoring."""
                product = original_normalize(*args, **kwargs)
                if product:
                    normalized_products.append(product)
                return product

            pipeline.normalizer.normalize = capture_normalize

            # Run pipeline
            result = await pipeline.run(job_id=job_id, shop_url=test_case.url)

            duration = time.monotonic() - start

            # Extract metadata from pipeline result
            platform_detected = result.get("platform", "unknown")
            extraction_tier = result.get("extraction_tier", "unknown")
            total_extracted = result.get("total_extracted", 0)
            total_normalized = result.get("total_normalized", 0)
            needs_review = result.get("needs_review", False)
            review_reason = result.get("review_reason", "unknown")

            # Check if pipeline needs review (soft failure)
            error_msg = None
            if needs_review:
                error_msg = f"Pipeline needs review: {review_reason}"
                logger.warning("Pipeline needs review for %s: %s", test_case.name, review_reason)

            # Convert normalized products to raw dicts for scoring
            # The scorer expects raw dicts, not Product models
            raw_products = [
                {
                    "title": p.title,
                    "price": str(p.price) if p.price else None,
                    "currency": p.currency,
                    "description": p.description,
                    "image_url": p.image_url,
                    "vendor": p.vendor,
                    "in_stock": p.in_stock,
                    "sku": p.sku,
                    "product_type": p.product_type,
                    "product_url": p.product_url,
                }
                for p in normalized_products
            ]

            # Score the results
            product_scores = Scorer.match_products(
                expected=test_case.products,
                extracted=raw_products,
            )

            products_matched = len([ps for ps in product_scores if ps.field_scores])

            tier_result = TierResult(
                tier_name=f"pipeline ({extraction_tier})",
                products_extracted=total_normalized,
                products_matched=products_matched,
                product_scores=product_scores,
                duration_seconds=duration,
                min_products=test_case.min_products,
                error=error_msg,
            )

            report = EvalReport(
                test_case_name=test_case.name,
                url=test_case.url,
                platform=test_case.platform,
                tier_results=[tier_result],
            )

            logger.info(
                "Pipeline eval complete: platform=%s (expected=%s), tier=%s, "
                "extracted=%d, normalized=%d, matched=%d, duration=%.1fs",
                platform_detected, test_case.platform, extraction_tier,
                total_extracted, total_normalized, products_matched, duration,
            )

            return report

        except Exception as e:
            duration = time.monotonic() - start
            logger.exception("Pipeline eval failed for %s: %s", test_case.name, e)

            tier_result = TierResult(
                tier_name="pipeline",
                products_extracted=0,
                products_matched=0,
                product_scores=[],
                duration_seconds=duration,
                error=str(e),
                min_products=test_case.min_products,
            )

            return EvalReport(
                test_case_name=test_case.name,
                url=test_case.url,
                platform=test_case.platform,
                tier_results=[tier_result],
            )

    async def run_all(self, test_cases: list[TestCase]) -> list[EvalReport]:
        """Run pipeline eval on multiple test cases sequentially.

        Args:
            test_cases: List of test cases to evaluate

        Returns:
            List of EvalReports, one per test case
        """
        reports = []
        for tc in test_cases:
            report = await self.run(tc)
            reports.append(report)
        return reports

    def _create_mock_progress(self) -> AsyncMock:
        """Create mock progress tracker that accepts all calls."""
        progress = AsyncMock()
        progress.update = AsyncMock()
        return progress

    def _create_mock_circuit_breaker(self) -> MagicMock:
        """Create mock circuit breaker that passes through all calls."""
        circuit_breaker = MagicMock()

        async def mock_call(domain, fn):
            """Pass through to the function."""
            return await fn()

        circuit_breaker.call = AsyncMock(side_effect=mock_call)
        return circuit_breaker

    def _create_mock_rate_limiter(self) -> MagicMock:
        """Create mock rate limiter that doesn't actually limit."""
        rate_limiter = MagicMock()

        # Mock the context manager
        class MockAcquire:
            async def __aenter__(self):
                return None

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                return None

        rate_limiter.acquire = MagicMock(return_value=MockAcquire())
        return rate_limiter
