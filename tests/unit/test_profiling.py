"""Unit tests for performance profiling feature."""

import pytest

from evals.models import ExpectedProduct, TestCase, TierResult
from evals.runner import EvalRunner


@pytest.fixture
def simple_test_case():
    """Create a simple test case for profiling tests."""
    return TestCase(
        name="Test",
        url="https://example.com",
        platform="generic",
        products=[
            ExpectedProduct(
                title="Test Product",
                price="9.99",
                currency="USD",
            )
        ],
    )


class TestProfilingFeature:
    """Tests for performance profiling functionality."""

    @pytest.mark.asyncio
    async def test_profiling_on_error_returns_none(self, simple_test_case):
        """When extraction fails, profiling metrics should be None."""
        runner = EvalRunner(tiers=["nonexistent_tier"], profile=True)
        report = await runner.run(simple_test_case)

        tier_result = report.tier_results[0]

        # Should have error
        assert tier_result.error is not None

        # Performance metrics should be None on error
        assert tier_result.peak_memory_mb is None
        assert tier_result.tokens_used is None
        assert tier_result.estimated_cost_usd is None

    @pytest.mark.asyncio
    async def test_profiling_default_is_disabled(self, simple_test_case):
        """Default behavior should have profiling disabled."""
        runner = EvalRunner(tiers=["nonexistent_tier"])
        report = await runner.run(simple_test_case)

        tier_result = report.tier_results[0]
        assert tier_result.peak_memory_mb is None


class TestTierResultModel:
    """Tests for TierResult data model with performance fields."""

    def test_tier_result_with_performance_metrics(self):
        """TierResult should accept performance metric fields."""
        result = TierResult(
            tier_name="test",
            products_extracted=5,
            products_matched=3,
            product_scores=[],
            duration_seconds=1.5,
            peak_memory_mb=12.5,
            tokens_used=1500,
            estimated_cost_usd=0.0025,
        )

        assert result.peak_memory_mb == 12.5
        assert result.tokens_used == 1500
        assert result.estimated_cost_usd == 0.0025

    def test_tier_result_without_performance_metrics(self):
        """TierResult should work with None performance metrics."""
        result = TierResult(
            tier_name="test",
            products_extracted=5,
            products_matched=3,
            product_scores=[],
            duration_seconds=1.5,
        )

        assert result.peak_memory_mb is None
        assert result.tokens_used is None
        assert result.estimated_cost_usd is None

    def test_tier_result_existing_properties_still_work(self):
        """Existing TierResult properties should still function."""
        result = TierResult(
            tier_name="test",
            products_extracted=5,
            products_matched=3,
            product_scores=[],
            duration_seconds=1.5,
            min_products=10,
            peak_memory_mb=5.0,
        )

        assert result.completeness_score == 0.5
        assert result.overall_score == 0.2
