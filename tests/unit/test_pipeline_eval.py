"""Unit tests for pipeline evaluation runner."""

import pytest

from evals.models import ExpectedProduct, TestCase
from evals.pipeline_runner import PipelineEvalRunner


@pytest.mark.asyncio
async def test_pipeline_eval_handles_error():
    """Test that PipelineEvalRunner handles errors gracefully.

    When the pipeline fails (e.g., invalid URL, network error), the runner
    should catch the exception and return an EvalReport with an error field.
    """
    runner = PipelineEvalRunner()

    tc = TestCase(
        name="Invalid Site",
        url="https://this-does-not-exist-12345.com",
        platform="generic",
        products=[ExpectedProduct(title="Test Product")],
        min_products=1,
    )

    report = await runner.run(tc)

    # Verify report structure
    assert report.test_case_name == "Invalid Site"
    assert report.url == "https://this-does-not-exist-12345.com"
    assert report.platform == "generic"

    # Should have exactly one tier result
    assert len(report.tier_results) == 1

    tier_result = report.tier_results[0]

    # Should have an error message (pipeline needs review)
    assert tier_result.error is not None
    assert "needs review" in tier_result.error.lower()

    # Should have zero products extracted
    assert tier_result.products_extracted == 0

    # Scorer creates ProductScore for each expected product even if not found
    # So we should have 1 product score (the expected one) with all 0.0 field scores
    assert len(tier_result.product_scores) == 1
    assert tier_result.product_scores[0].expected_title == "Test Product"
    assert tier_result.product_scores[0].extracted_title is None
    assert tier_result.product_scores[0].avg_score == 0.0

    # Duration should be non-negative
    assert tier_result.duration_seconds >= 0


@pytest.mark.asyncio
async def test_pipeline_eval_creates_mock_infrastructure():
    """Test that the runner creates proper mock infrastructure.

    The pipeline requires progress tracker, circuit breaker, and rate limiter.
    Verify that mocks are created correctly and don't interfere with execution.
    """
    runner = PipelineEvalRunner()

    # Test mock creation methods
    progress = runner._create_mock_progress()
    circuit_breaker = runner._create_mock_circuit_breaker()
    rate_limiter = runner._create_mock_rate_limiter()

    # Verify they're callable
    assert callable(progress.update)
    assert callable(circuit_breaker.call)
    assert callable(rate_limiter.acquire)

    # Verify progress tracker accepts calls
    await progress.update(
        job_id="test",
        processed=1,
        total=10,
        status="testing",
        current_step="test step",
    )

    # Verify circuit breaker passes through calls
    async def test_fn():
        return "success"

    result = await circuit_breaker.call("example.com", test_fn)
    assert result == "success"

    # Verify rate limiter context manager works
    async with rate_limiter.acquire("example.com"):
        pass  # Should not block or error


@pytest.mark.asyncio
async def test_pipeline_eval_run_all():
    """Test running multiple test cases sequentially."""
    runner = PipelineEvalRunner()

    test_cases = [
        TestCase(
            name="Invalid Site 1",
            url="https://this-does-not-exist-1.com",
            platform="generic",
            products=[ExpectedProduct(title="Product 1")],
        ),
        TestCase(
            name="Invalid Site 2",
            url="https://this-does-not-exist-2.com",
            platform="shopify",
            products=[ExpectedProduct(title="Product 2")],
        ),
    ]

    reports = await runner.run_all(test_cases)

    # Should return one report per test case
    assert len(reports) == 2

    # Verify each report corresponds to the correct test case
    assert reports[0].test_case_name == "Invalid Site 1"
    assert reports[0].platform == "generic"

    assert reports[1].test_case_name == "Invalid Site 2"
    assert reports[1].platform == "shopify"

    # All should have errors (invalid URLs)
    for report in reports:
        assert len(report.tier_results) == 1
        assert report.tier_results[0].error is not None
