"""Tests for product completeness scoring in evaluations."""

from __future__ import annotations

import pytest

from evals.models import FieldScore, MatchType, ProductScore, TierResult


class TestCompletenessScore:
    """Tests for TierResult.completeness_score property."""

    def test_completeness_score_when_min_products_is_none(self):
        """When min_products is None, completeness should be 1.0."""
        tier = TierResult(
            tier_name="test_tier",
            products_extracted=10,
            products_matched=10,
            product_scores=[],
            duration_seconds=1.0,
            min_products=None,
        )

        assert tier.completeness_score == 1.0

    def test_completeness_score_when_min_products_is_zero(self):
        """When min_products is 0, completeness should be 1.0."""
        tier = TierResult(
            tier_name="test_tier",
            products_extracted=10,
            products_matched=10,
            product_scores=[],
            duration_seconds=1.0,
            min_products=0,
        )

        assert tier.completeness_score == 1.0

    def test_completeness_score_when_min_products_is_negative(self):
        """When min_products is negative, completeness should be 1.0."""
        tier = TierResult(
            tier_name="test_tier",
            products_extracted=10,
            products_matched=10,
            product_scores=[],
            duration_seconds=1.0,
            min_products=-5,
        )

        assert tier.completeness_score == 1.0

    def test_completeness_score_when_extracted_equals_min(self):
        """When extracted equals min_products, completeness should be 1.0."""
        tier = TierResult(
            tier_name="test_tier",
            products_extracted=30,
            products_matched=30,
            product_scores=[],
            duration_seconds=1.0,
            min_products=30,
        )

        assert tier.completeness_score == 1.0

    def test_completeness_score_when_extracted_exceeds_min(self):
        """When extracted exceeds min_products, completeness should cap at 1.0."""
        tier = TierResult(
            tier_name="test_tier",
            products_extracted=50,
            products_matched=50,
            product_scores=[],
            duration_seconds=1.0,
            min_products=30,
        )

        assert tier.completeness_score == 1.0

    def test_completeness_score_when_extracted_is_half_of_min(self):
        """When extracted is half of min_products, completeness should be 0.5."""
        tier = TierResult(
            tier_name="test_tier",
            products_extracted=15,
            products_matched=15,
            product_scores=[],
            duration_seconds=1.0,
            min_products=30,
        )

        assert tier.completeness_score == 0.5

    def test_completeness_score_when_extracted_is_zero(self):
        """When extracted is 0, completeness should be 0.0."""
        tier = TierResult(
            tier_name="test_tier",
            products_extracted=0,
            products_matched=0,
            product_scores=[],
            duration_seconds=1.0,
            min_products=30,
        )

        assert tier.completeness_score == 0.0

    def test_completeness_score_partial_extraction(self):
        """Test various partial extraction scenarios."""
        test_cases = [
            (10, 30, 10 / 30),  # 33.3%
            (20, 30, 20 / 30),  # 66.7%
            (25, 30, 25 / 30),  # 83.3%
            (29, 30, 29 / 30),  # 96.7%
        ]

        for extracted, min_products, expected_score in test_cases:
            tier = TierResult(
                tier_name="test_tier",
                products_extracted=extracted,
                products_matched=extracted,
                product_scores=[],
                duration_seconds=1.0,
                min_products=min_products,
            )

            assert tier.completeness_score == pytest.approx(expected_score, rel=1e-6)


class TestOverallScore:
    """Tests for TierResult.overall_score property (60% accuracy + 40% completeness)."""

    def test_overall_score_perfect_accuracy_and_completeness(self):
        """When both accuracy and completeness are 1.0, overall should be 1.0."""
        # Create product score with perfect field scores
        field_scores = [
            FieldScore(field_name="title", match_type=MatchType.FUZZY, score=1.0, expected="Test", extracted="Test"),
            FieldScore(field_name="price", match_type=MatchType.NUMERIC, score=1.0, expected="100", extracted="100"),
        ]
        product_scores = [
            ProductScore(expected_title="Test", extracted_title="Test", field_scores=field_scores)
        ]

        tier = TierResult(
            tier_name="test_tier",
            products_extracted=30,
            products_matched=1,
            product_scores=product_scores,
            duration_seconds=1.0,
            min_products=30,
        )

        # avg_score = 1.0, completeness = 1.0
        # overall = (1.0 * 0.6) + (1.0 * 0.4) = 1.0
        assert tier.overall_score == 1.0

    def test_overall_score_perfect_accuracy_half_completeness(self):
        """When accuracy is 1.0 and completeness is 0.5, overall should be 0.8."""
        field_scores = [
            FieldScore(field_name="title", match_type=MatchType.FUZZY, score=1.0, expected="Test", extracted="Test"),
            FieldScore(field_name="price", match_type=MatchType.NUMERIC, score=1.0, expected="100", extracted="100"),
        ]
        product_scores = [
            ProductScore(expected_title="Test", extracted_title="Test", field_scores=field_scores)
        ]

        tier = TierResult(
            tier_name="test_tier",
            products_extracted=15,
            products_matched=1,
            product_scores=product_scores,
            duration_seconds=1.0,
            min_products=30,
        )

        # avg_score = 1.0, completeness = 0.5
        # overall = (1.0 * 0.6) + (0.5 * 0.4) = 0.6 + 0.2 = 0.8
        assert tier.overall_score == 0.8

    def test_overall_score_half_accuracy_perfect_completeness(self):
        """When accuracy is 0.5 and completeness is 1.0, overall should be 0.7."""
        field_scores = [
            FieldScore(field_name="title", match_type=MatchType.FUZZY, score=0.5, expected="Test", extracted="Tst"),
            FieldScore(field_name="price", match_type=MatchType.NUMERIC, score=0.5, expected="100", extracted="90"),
        ]
        product_scores = [
            ProductScore(expected_title="Test", extracted_title="Tst", field_scores=field_scores)
        ]

        tier = TierResult(
            tier_name="test_tier",
            products_extracted=30,
            products_matched=1,
            product_scores=product_scores,
            duration_seconds=1.0,
            min_products=30,
        )

        # avg_score = 0.5, completeness = 1.0
        # overall = (0.5 * 0.6) + (1.0 * 0.4) = 0.3 + 0.4 = 0.7
        assert tier.overall_score == 0.7

    def test_overall_score_half_accuracy_half_completeness(self):
        """When both accuracy and completeness are 0.5, overall should be 0.5."""
        field_scores = [
            FieldScore(field_name="title", match_type=MatchType.FUZZY, score=0.5, expected="Test", extracted="Tst"),
            FieldScore(field_name="price", match_type=MatchType.NUMERIC, score=0.5, expected="100", extracted="90"),
        ]
        product_scores = [
            ProductScore(expected_title="Test", extracted_title="Tst", field_scores=field_scores)
        ]

        tier = TierResult(
            tier_name="test_tier",
            products_extracted=15,
            products_matched=1,
            product_scores=product_scores,
            duration_seconds=1.0,
            min_products=30,
        )

        # avg_score = 0.5, completeness = 0.5
        # overall = (0.5 * 0.6) + (0.5 * 0.4) = 0.3 + 0.2 = 0.5
        assert tier.overall_score == 0.5

    def test_overall_score_zero_accuracy_perfect_completeness(self):
        """When accuracy is 0.0 and completeness is 1.0, overall should be 0.4."""
        field_scores = [
            FieldScore(field_name="title", match_type=MatchType.FUZZY, score=0.0, expected="Test", extracted=None),
            FieldScore(field_name="price", match_type=MatchType.NUMERIC, score=0.0, expected="100", extracted=None),
        ]
        product_scores = [
            ProductScore(expected_title="Test", extracted_title=None, field_scores=field_scores)
        ]

        tier = TierResult(
            tier_name="test_tier",
            products_extracted=30,
            products_matched=1,
            product_scores=product_scores,
            duration_seconds=1.0,
            min_products=30,
        )

        # avg_score = 0.0, completeness = 1.0
        # overall = (0.0 * 0.6) + (1.0 * 0.4) = 0.0 + 0.4 = 0.4
        assert tier.overall_score == 0.4

    def test_overall_score_no_min_products_set(self):
        """When min_products is None, completeness defaults to 1.0."""
        field_scores = [
            FieldScore(field_name="title", match_type=MatchType.FUZZY, score=0.8, expected="Test", extracted="Test"),
        ]
        product_scores = [
            ProductScore(expected_title="Test", extracted_title="Test", field_scores=field_scores)
        ]

        tier = TierResult(
            tier_name="test_tier",
            products_extracted=10,
            products_matched=1,
            product_scores=product_scores,
            duration_seconds=1.0,
            min_products=None,
        )

        # avg_score = 0.8, completeness = 1.0 (default)
        # overall = (0.8 * 0.6) + (1.0 * 0.4) = 0.48 + 0.4 = 0.88
        assert tier.overall_score == pytest.approx(0.88, rel=1e-6)

    def test_overall_score_no_products_extracted(self):
        """When no products extracted, overall should be 0.0."""
        tier = TierResult(
            tier_name="test_tier",
            products_extracted=0,
            products_matched=0,
            product_scores=[],
            duration_seconds=1.0,
            min_products=30,
        )

        # avg_score = 0.0 (no products), completeness = 0.0
        # overall = (0.0 * 0.6) + (0.0 * 0.4) = 0.0
        assert tier.overall_score == 0.0


class TestReportFormatting:
    """Tests for report formatting with completeness info."""

    def test_format_tier_shows_completeness_when_min_products_set(self):
        """Report should show completeness line when min_products is set."""
        from evals.report import ReportFormatter

        field_scores = [
            FieldScore(field_name="title", match_type=MatchType.FUZZY, score=0.9, expected="Test", extracted="Test"),
        ]
        product_scores = [
            ProductScore(expected_title="Test", extracted_title="Test", field_scores=field_scores)
        ]

        tier = TierResult(
            tier_name="schema_org",
            products_extracted=25,
            products_matched=1,
            product_scores=product_scores,
            duration_seconds=2.5,
            min_products=30,
        )

        output = ReportFormatter.format_tier(tier)

        # Should contain completeness line
        assert "Completeness: 25/30" in output
        assert "(83.3%)" in output

        # Should contain both Accuracy and Overall scores
        assert "Accuracy:" in output
        assert "Overall:" in output

    def test_format_tier_no_completeness_when_min_products_not_set(self):
        """Report should not show completeness line when min_products is None."""
        from evals.report import ReportFormatter

        field_scores = [
            FieldScore(field_name="title", match_type=MatchType.FUZZY, score=0.9, expected="Test", extracted="Test"),
        ]
        product_scores = [
            ProductScore(expected_title="Test", extracted_title="Test", field_scores=field_scores)
        ]

        tier = TierResult(
            tier_name="schema_org",
            products_extracted=25,
            products_matched=1,
            product_scores=product_scores,
            duration_seconds=2.5,
            min_products=None,
        )

        output = ReportFormatter.format_tier(tier)

        # Should NOT contain completeness line
        assert "Completeness:" not in output

        # Should still contain both Accuracy and Overall scores
        assert "Accuracy:" in output
        assert "Overall:" in output

    def test_format_report_uses_overall_score_for_best_tier(self):
        """Report should use overall_score (not avg_score) for best tier display."""
        from evals.models import EvalReport
        from evals.report import ReportFormatter

        field_scores = [
            FieldScore(field_name="title", match_type=MatchType.FUZZY, score=0.9, expected="Test", extracted="Test"),
        ]
        product_scores = [
            ProductScore(expected_title="Test", extracted_title="Test", field_scores=field_scores)
        ]

        tier = TierResult(
            tier_name="schema_org",
            products_extracted=25,
            products_matched=1,
            product_scores=product_scores,
            duration_seconds=2.5,
            min_products=30,
        )

        report = EvalReport(
            test_case_name="Test Site",
            url="https://example.com",
            platform="shopify",
            tier_results=[tier],
        )

        output = ReportFormatter.format_report(report)

        # Should show overall score in best tier
        expected_overall = (0.9 * 0.6) + ((25 / 30) * 0.4)  # ~0.87
        assert "overall score:" in output.lower()

    def test_format_summary_uses_overall_score(self):
        """Summary table should use overall_score for the Score column."""
        from evals.models import EvalReport
        from evals.report import ReportFormatter

        field_scores = [
            FieldScore(field_name="title", match_type=MatchType.FUZZY, score=0.8, expected="Test", extracted="Test"),
        ]
        product_scores = [
            ProductScore(expected_title="Test", extracted_title="Test", field_scores=field_scores)
        ]

        tier1 = TierResult(
            tier_name="schema_org",
            products_extracted=20,
            products_matched=1,
            product_scores=product_scores,
            duration_seconds=2.5,
            min_products=30,
        )

        tier2 = TierResult(
            tier_name="opengraph",
            products_extracted=30,
            products_matched=1,
            product_scores=product_scores,
            duration_seconds=3.0,
            min_products=30,
        )

        report = EvalReport(
            test_case_name="Test Site",
            url="https://example.com",
            platform="shopify",
            tier_results=[tier1, tier2],
        )

        output = ReportFormatter.format_summary([report])

        # Best tier should be opengraph (higher overall due to better completeness)
        # tier1: (0.8 * 0.6) + ((20/30) * 0.4) = 0.48 + 0.267 = 0.747
        # tier2: (0.8 * 0.6) + ((30/30) * 0.4) = 0.48 + 0.4 = 0.88
        assert "opengraph" in output

        # Should show overall average
        assert "Overall average score:" in output
