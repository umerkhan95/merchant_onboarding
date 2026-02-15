"""Tests for baseline score storage and regression detection."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from evals.baseline import check_regression, load_baseline, save_baseline
from evals.models import EvalReport, FieldScore, MatchType, ProductScore, TierResult


@pytest.fixture
def sample_reports() -> list[EvalReport]:
    """Create sample eval reports for testing."""
    # Create some field scores
    field_scores_1 = [
        FieldScore(
            field_name="title",
            match_type=MatchType.FUZZY,
            score=0.9,
            expected="Test Product",
            extracted="Test Product",
        ),
        FieldScore(
            field_name="price",
            match_type=MatchType.NUMERIC,
            score=1.0,
            expected="29.99",
            extracted="29.99",
        ),
    ]

    field_scores_2 = [
        FieldScore(
            field_name="title",
            match_type=MatchType.FUZZY,
            score=0.85,
            expected="Another Product",
            extracted="Another Product",
        ),
        FieldScore(
            field_name="price",
            match_type=MatchType.NUMERIC,
            score=1.0,
            expected="39.99",
            extracted="39.99",
        ),
    ]

    product_scores = [
        ProductScore(
            expected_title="Test Product",
            extracted_title="Test Product",
            field_scores=field_scores_1,
        ),
        ProductScore(
            expected_title="Another Product",
            extracted_title="Another Product",
            field_scores=field_scores_2,
        ),
    ]

    tier_result = TierResult(
        tier_name="schema_org",
        products_extracted=2,
        products_matched=2,
        product_scores=product_scores,
        duration_seconds=1.5,
    )

    report = EvalReport(
        test_case_name="test_site",
        url="https://test.com",
        platform="shopify",
        tier_results=[tier_result],
    )

    return [report]


@pytest.fixture
def baseline_file_path(tmp_path: Path) -> Path:
    """Create a temporary baseline file path."""
    return tmp_path / "baseline.json"


def test_save_baseline_creates_valid_json(tmp_path: Path, sample_reports: list[EvalReport]):
    """Test that save_baseline creates a valid JSON file."""
    # Mock the module-level constants to use tmp_path
    with patch("evals.baseline.BASELINES_DIR", tmp_path), \
         patch("evals.baseline.BASELINE_FILE", tmp_path / "baseline.json"):

        # Mock git command
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0, stdout="abc123\n")

            baseline_path = save_baseline(sample_reports)

            # Verify file was created
            assert baseline_path.exists()

            # Verify content is valid JSON
            content = json.loads(baseline_path.read_text())

            # Verify structure
            assert "timestamp" in content
            assert "git_sha" in content
            assert "results" in content
            assert content["git_sha"] == "abc123"

            # Verify results
            assert "test_site" in content["results"]
            site_results = content["results"]["test_site"]
            assert "schema_org" in site_results

            tier_data = site_results["schema_org"]
            assert "avg_score" in tier_data
            assert "products_extracted" in tier_data
            assert "products_matched" in tier_data
            assert "field_averages" in tier_data

            # Verify field averages
            assert "title" in tier_data["field_averages"]
            assert "price" in tier_data["field_averages"]
            assert tier_data["field_averages"]["title"] == 0.875  # (0.9 + 0.85) / 2
            assert tier_data["field_averages"]["price"] == 1.0


def test_save_baseline_handles_git_failure(tmp_path: Path, sample_reports: list[EvalReport]):
    """Test that save_baseline handles git command failure gracefully."""
    with patch("evals.baseline.BASELINES_DIR", tmp_path), \
         patch("evals.baseline.BASELINE_FILE", tmp_path / "baseline.json"):

        # Mock git command failure
        with patch("subprocess.run") as mock_run:
            mock_run.side_effect = Exception("Git not available")

            baseline_path = save_baseline(sample_reports)

            # Should still create the file
            assert baseline_path.exists()

            # Git SHA should be empty string
            content = json.loads(baseline_path.read_text())
            assert content["git_sha"] == ""


def test_save_baseline_skips_error_tiers(tmp_path: Path):
    """Test that save_baseline skips tiers with errors."""
    # Create report with error tier
    tier_with_error = TierResult(
        tier_name="llm",
        products_extracted=0,
        products_matched=0,
        product_scores=[],
        duration_seconds=0.0,
        error="LLM API key not configured",
    )

    report = EvalReport(
        test_case_name="test_site",
        url="https://test.com",
        platform="shopify",
        tier_results=[tier_with_error],
    )

    with patch("evals.baseline.BASELINES_DIR", tmp_path), \
         patch("evals.baseline.BASELINE_FILE", tmp_path / "baseline.json"):

        baseline_path = save_baseline([report])

        content = json.loads(baseline_path.read_text())

        # Site should exist but have no tier results
        assert "test_site" in content["results"]
        assert len(content["results"]["test_site"]) == 0


def test_load_baseline_returns_none_when_no_file():
    """Test that load_baseline returns None when no baseline exists."""
    with patch("evals.baseline.BASELINE_FILE", Path("/nonexistent/baseline.json")):
        baseline = load_baseline()
        assert baseline is None


def test_load_baseline_returns_saved_data(tmp_path: Path):
    """Test that load_baseline returns saved baseline data."""
    baseline_data = {
        "timestamp": "2026-02-15T12:00:00Z",
        "git_sha": "abc123",
        "results": {
            "test_site": {
                "schema_org": {
                    "avg_score": 0.9,
                    "products_extracted": 2,
                    "products_matched": 2,
                    "field_averages": {
                        "title": 0.85,
                        "price": 1.0,
                    },
                },
            },
        },
    }

    baseline_file = tmp_path / "baseline.json"
    baseline_file.write_text(json.dumps(baseline_data))

    with patch("evals.baseline.BASELINE_FILE", baseline_file):
        loaded = load_baseline()
        assert loaded == baseline_data


def test_check_regression_passes_when_no_baseline():
    """Test that check_regression passes when no baseline exists."""
    with patch("evals.baseline.load_baseline", return_value=None):
        passed, message = check_regression([])
        assert passed is True
        assert "No baseline found" in message


def test_check_regression_passes_when_scores_stable(tmp_path: Path, sample_reports: list[EvalReport]):
    """Test that check_regression passes when scores are stable."""
    # Create baseline with same scores
    baseline_data = {
        "timestamp": "2026-02-15T12:00:00Z",
        "git_sha": "abc123",
        "results": {
            "test_site": {
                "schema_org": {
                    "avg_score": 0.925,
                    "products_extracted": 2,
                    "products_matched": 2,
                    "field_averages": {
                        "title": 0.875,  # (0.9 + 0.85) / 2
                        "price": 1.0,
                    },
                },
            },
        },
    }

    with patch("evals.baseline.load_baseline", return_value=baseline_data):
        passed, message = check_regression(sample_reports, threshold=0.05)
        assert passed is True
        assert "No significant changes" in message


def test_check_regression_detects_regression_below_threshold(tmp_path: Path):
    """Test that check_regression detects regressions below threshold."""
    # Create report with lower scores
    field_scores = [
        FieldScore(
            field_name="title",
            match_type=MatchType.FUZZY,
            score=0.70,  # Down from 0.875 in baseline
            expected="Test Product",
            extracted="Different Title",
        ),
        FieldScore(
            field_name="price",
            match_type=MatchType.NUMERIC,
            score=1.0,
            expected="29.99",
            extracted="29.99",
        ),
    ]

    product_scores = [
        ProductScore(
            expected_title="Test Product",
            extracted_title="Different Title",
            field_scores=field_scores,
        ),
    ]

    tier_result = TierResult(
        tier_name="schema_org",
        products_extracted=1,
        products_matched=1,
        product_scores=product_scores,
        duration_seconds=1.0,
    )

    report = EvalReport(
        test_case_name="test_site",
        url="https://test.com",
        platform="shopify",
        tier_results=[tier_result],
    )

    baseline_data = {
        "timestamp": "2026-02-15T12:00:00Z",
        "git_sha": "abc123",
        "results": {
            "test_site": {
                "schema_org": {
                    "avg_score": 0.925,
                    "products_extracted": 2,
                    "products_matched": 2,
                    "field_averages": {
                        "title": 0.875,
                        "price": 1.0,
                    },
                },
            },
        },
    }

    with patch("evals.baseline.load_baseline", return_value=baseline_data):
        passed, message = check_regression([report], threshold=0.05)
        assert passed is False
        assert "REGRESSION" in message
        assert "test_site.schema_org.title" in message


def test_check_regression_ignores_allowed_regressions(tmp_path: Path):
    """Test that check_regression ignores allowed regressions."""
    # Create report with lower scores
    field_scores = [
        FieldScore(
            field_name="title",
            match_type=MatchType.FUZZY,
            score=0.70,  # Down from 0.875 in baseline
            expected="Test Product",
            extracted="Different Title",
        ),
        FieldScore(
            field_name="price",
            match_type=MatchType.NUMERIC,
            score=1.0,
            expected="29.99",
            extracted="29.99",
        ),
    ]

    product_scores = [
        ProductScore(
            expected_title="Test Product",
            extracted_title="Different Title",
            field_scores=field_scores,
        ),
    ]

    tier_result = TierResult(
        tier_name="schema_org",
        products_extracted=1,
        products_matched=1,
        product_scores=product_scores,
        duration_seconds=1.0,
    )

    report = EvalReport(
        test_case_name="test_site",
        url="https://test.com",
        platform="shopify",
        tier_results=[tier_result],
    )

    baseline_data = {
        "timestamp": "2026-02-15T12:00:00Z",
        "git_sha": "abc123",
        "results": {
            "test_site": {
                "schema_org": {
                    "avg_score": 0.925,
                    "products_extracted": 2,
                    "products_matched": 2,
                    "field_averages": {
                        "title": 0.875,
                        "price": 1.0,
                    },
                },
            },
        },
    }

    with patch("evals.baseline.load_baseline", return_value=baseline_data):
        # Allow the title regression
        passed, message = check_regression(
            [report],
            threshold=0.05,
            allowed_regressions=["test_site.schema_org.title"],
        )
        assert passed is True
        assert "No significant changes" in message


def test_check_regression_reports_improvements(tmp_path: Path):
    """Test that check_regression reports improvements."""
    # Create report with higher scores
    field_scores = [
        FieldScore(
            field_name="title",
            match_type=MatchType.FUZZY,
            score=0.95,  # Up from 0.875 in baseline
            expected="Test Product",
            extracted="Test Product",
        ),
        FieldScore(
            field_name="price",
            match_type=MatchType.NUMERIC,
            score=1.0,
            expected="29.99",
            extracted="29.99",
        ),
    ]

    product_scores = [
        ProductScore(
            expected_title="Test Product",
            extracted_title="Test Product",
            field_scores=field_scores,
        ),
    ]

    tier_result = TierResult(
        tier_name="schema_org",
        products_extracted=1,
        products_matched=1,
        product_scores=product_scores,
        duration_seconds=1.0,
    )

    report = EvalReport(
        test_case_name="test_site",
        url="https://test.com",
        platform="shopify",
        tier_results=[tier_result],
    )

    baseline_data = {
        "timestamp": "2026-02-15T12:00:00Z",
        "git_sha": "abc123",
        "results": {
            "test_site": {
                "schema_org": {
                    "avg_score": 0.925,
                    "products_extracted": 2,
                    "products_matched": 2,
                    "field_averages": {
                        "title": 0.875,
                        "price": 1.0,
                    },
                },
            },
        },
    }

    with patch("evals.baseline.load_baseline", return_value=baseline_data):
        passed, message = check_regression([report], threshold=0.05)
        assert passed is True
        assert "IMPROVED" in message
        assert "test_site.schema_org.title" in message


def test_check_regression_skips_tiers_with_errors():
    """Test that check_regression skips tiers with errors."""
    tier_with_error = TierResult(
        tier_name="llm",
        products_extracted=0,
        products_matched=0,
        product_scores=[],
        duration_seconds=0.0,
        error="LLM API key not configured",
    )

    report = EvalReport(
        test_case_name="test_site",
        url="https://test.com",
        platform="shopify",
        tier_results=[tier_with_error],
    )

    baseline_data = {
        "timestamp": "2026-02-15T12:00:00Z",
        "git_sha": "abc123",
        "results": {
            "test_site": {
                "llm": {
                    "avg_score": 0.9,
                    "products_extracted": 2,
                    "products_matched": 2,
                    "field_averages": {
                        "title": 0.9,
                    },
                },
            },
        },
    }

    with patch("evals.baseline.load_baseline", return_value=baseline_data):
        passed, message = check_regression([report], threshold=0.05)
        # Should pass since error tier is skipped
        assert passed is True
        assert "No significant changes" in message


def test_check_regression_handles_missing_baseline_fields():
    """Test that check_regression handles fields missing from baseline."""
    # Create report with new field not in baseline
    field_scores = [
        FieldScore(
            field_name="title",
            match_type=MatchType.FUZZY,
            score=0.9,
            expected="Test Product",
            extracted="Test Product",
        ),
        FieldScore(
            field_name="new_field",  # Not in baseline
            match_type=MatchType.FUZZY,
            score=0.8,
            expected="New Value",
            extracted="New Value",
        ),
    ]

    product_scores = [
        ProductScore(
            expected_title="Test Product",
            extracted_title="Test Product",
            field_scores=field_scores,
        ),
    ]

    tier_result = TierResult(
        tier_name="schema_org",
        products_extracted=1,
        products_matched=1,
        product_scores=product_scores,
        duration_seconds=1.0,
    )

    report = EvalReport(
        test_case_name="test_site",
        url="https://test.com",
        platform="shopify",
        tier_results=[tier_result],
    )

    baseline_data = {
        "timestamp": "2026-02-15T12:00:00Z",
        "git_sha": "abc123",
        "results": {
            "test_site": {
                "schema_org": {
                    "avg_score": 0.9,
                    "products_extracted": 1,
                    "products_matched": 1,
                    "field_averages": {
                        "title": 0.9,
                        # new_field not in baseline
                    },
                },
            },
        },
    }

    with patch("evals.baseline.load_baseline", return_value=baseline_data):
        passed, message = check_regression([report], threshold=0.05)
        # Should pass since new fields are ignored
        assert passed is True
