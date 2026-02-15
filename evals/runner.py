"""Evaluation runner — orchestrates extractor runs and scoring."""

from __future__ import annotations

import logging
import time

from evals.models import EvalReport, TestCase, TierResult
from evals.scorer import Scorer

logger = logging.getLogger(__name__)


class EvalRunner:
    """Runs extractors against test cases and scores the results."""

    def __init__(self, tiers: list[str] | None = None):
        """Initialize the eval runner with a list of tiers to test.

        Args:
            tiers: List of tier names to test. Defaults to ["schema_org", "opengraph", "css_generic"]
        """
        self.tiers = tiers or ["schema_org", "opengraph", "css_generic"]

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

    async def _run_tier(self, tier_name: str, test_case: TestCase) -> TierResult:
        """Run a single tier extractor against a test case and score the results.

        Args:
            tier_name: Name of the tier to run
            test_case: The test case to evaluate

        Returns:
            TierResult with scores, timing, and error info
        """
        logger.info("Running tier '%s' for %s", tier_name, test_case.name)

        try:
            # Create the extractor
            extractor = self._create_extractor(tier_name)

            # Time the extraction
            start_time = time.monotonic()
            extracted_products = await extractor.extract(test_case.url)
            duration = time.monotonic() - start_time

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
            )

    def _create_extractor(self, tier_name: str):
        """Create an extractor instance for the given tier name.

        Args:
            tier_name: Name of the tier ("schema_org", "opengraph", "css_generic")

        Returns:
            Extractor instance

        Raises:
            ValueError: If tier_name is unknown
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
