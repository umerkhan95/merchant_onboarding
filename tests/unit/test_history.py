"""Unit tests for historical score tracking."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from evals.models import EvalReport, TierResult


@pytest.fixture
def mock_history_dir(tmp_path: Path, monkeypatch):
    """Mock HISTORY_DIR to use temp directory."""
    history_dir = tmp_path / "history"
    history_file = history_dir / "scores.jsonl"

    # Monkeypatch the module-level constants
    import evals.history as history_module
    monkeypatch.setattr(history_module, "HISTORY_DIR", history_dir)
    monkeypatch.setattr(history_module, "HISTORY_FILE", history_file)

    return history_dir, history_file


@pytest.fixture
def sample_reports() -> list[EvalReport]:
    """Create sample eval reports for testing."""
    tier1 = TierResult(
        tier_name="schema_org",
        products_extracted=5,
        products_matched=4,
        product_scores=[],  # Simplified
        duration_seconds=2.5,
        min_products=3,
    )
    tier2 = TierResult(
        tier_name="opengraph",
        products_extracted=3,
        products_matched=2,
        product_scores=[],
        duration_seconds=1.8,
        min_products=3,
    )

    # Manually set avg_score via property override (simulate real scores)
    # In real usage, product_scores would contain FieldScores
    tier1._avg_score = 0.85
    tier2._avg_score = 0.72

    report = EvalReport(
        test_case_name="test_site",
        url="https://example.com",
        platform="shopify",
        tier_results=[tier1, tier2],
    )
    return [report]


def test_save_run_creates_jsonl_file(mock_history_dir, sample_reports):
    """Test that save_run creates a JSONL file."""
    from evals.history import save_run

    history_dir, history_file = mock_history_dir

    with patch("evals.history._get_git_sha", return_value="abc123def456"):
        with patch("evals.history._get_git_branch", return_value="main"):
            save_run(sample_reports)

    assert history_file.exists()
    content = history_file.read_text()
    assert content.strip()  # Not empty

    # Parse the JSONL entry
    entry = json.loads(content.strip())
    assert "timestamp" in entry
    assert entry["git_sha"] == "abc123def456"
    assert entry["branch"] == "main"
    assert "scores" in entry
    assert "test_site" in entry["scores"]


def test_save_run_appends_to_existing_file(mock_history_dir, sample_reports):
    """Test that multiple saves append to the same file."""
    from evals.history import save_run

    history_dir, history_file = mock_history_dir

    with patch("evals.history._get_git_sha", return_value="commit1"):
        with patch("evals.history._get_git_branch", return_value="main"):
            save_run(sample_reports)

    with patch("evals.history._get_git_sha", return_value="commit2"):
        with patch("evals.history._get_git_branch", return_value="feature"):
            save_run(sample_reports)

    # Should have 2 lines
    lines = history_file.read_text().strip().split("\n")
    assert len(lines) == 2

    entry1 = json.loads(lines[0])
    entry2 = json.loads(lines[1])
    assert entry1["git_sha"] == "commit1"
    assert entry2["git_sha"] == "commit2"


def test_save_run_skips_error_tiers(mock_history_dir):
    """Test that tiers with errors are skipped."""
    from evals.history import save_run

    history_dir, history_file = mock_history_dir

    tier_error = TierResult(
        tier_name="llm",
        products_extracted=0,
        products_matched=0,
        product_scores=[],
        duration_seconds=0.0,
        error="LLM API key not found",
    )
    tier_ok = TierResult(
        tier_name="schema_org",
        products_extracted=5,
        products_matched=5,
        product_scores=[],
        duration_seconds=2.0,
        min_products=3,
    )

    report = EvalReport(
        test_case_name="test_site",
        url="https://example.com",
        platform="shopify",
        tier_results=[tier_error, tier_ok],
    )

    with patch("evals.history._get_git_sha", return_value="abc123"):
        with patch("evals.history._get_git_branch", return_value="main"):
            save_run([report])

    content = history_file.read_text()
    entry = json.loads(content.strip())

    # Only schema_org should be saved, not llm
    assert "schema_org" in entry["scores"]["test_site"]
    assert "llm" not in entry["scores"]["test_site"]


def test_load_history_empty_file(mock_history_dir):
    """Test load_history returns empty list when file doesn't exist."""
    from evals.history import load_history

    history_dir, history_file = mock_history_dir

    # File doesn't exist yet
    entries = load_history()
    assert entries == []


def test_load_history_returns_entries_in_order(mock_history_dir):
    """Test load_history returns entries in chronological order."""
    from evals.history import load_history

    history_dir, history_file = mock_history_dir
    history_dir.mkdir(parents=True, exist_ok=True)

    # Manually write 3 entries
    entries = [
        {"timestamp": "2026-01-01T10:00:00Z", "git_sha": "commit1", "branch": "main", "scores": {}},
        {"timestamp": "2026-01-02T10:00:00Z", "git_sha": "commit2", "branch": "main", "scores": {}},
        {"timestamp": "2026-01-03T10:00:00Z", "git_sha": "commit3", "branch": "main", "scores": {}},
    ]

    with history_file.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    loaded = load_history()
    assert len(loaded) == 3
    assert loaded[0]["git_sha"] == "commit1"
    assert loaded[1]["git_sha"] == "commit2"
    assert loaded[2]["git_sha"] == "commit3"


def test_load_history_with_last_n(mock_history_dir):
    """Test load_history with last_n parameter."""
    from evals.history import load_history

    history_dir, history_file = mock_history_dir
    history_dir.mkdir(parents=True, exist_ok=True)

    # Write 5 entries
    entries = [
        {"timestamp": f"2026-01-0{i}T10:00:00Z", "git_sha": f"commit{i}", "branch": "main", "scores": {}}
        for i in range(1, 6)
    ]

    with history_file.open("w") as f:
        for entry in entries:
            f.write(json.dumps(entry) + "\n")

    # Load only last 2
    loaded = load_history(last_n=2)
    assert len(loaded) == 2
    assert loaded[0]["git_sha"] == "commit4"
    assert loaded[1]["git_sha"] == "commit5"


def test_format_history_empty(mock_history_dir):
    """Test format_history with no entries."""
    from evals.history import format_history

    output = format_history([])
    assert "No history entries found" in output


def test_format_history_produces_table(mock_history_dir):
    """Test format_history produces readable table."""
    from evals.history import format_history

    entries = [
        {
            "timestamp": "2026-01-01T10:00:00Z",
            "git_sha": "abc123def",
            "branch": "main",
            "scores": {
                "site1": {
                    "tier1": {"overall_score": 0.85},
                    "tier2": {"overall_score": 0.75},
                },
                "site2": {
                    "tier1": {"overall_score": 0.90},
                },
            },
        },
    ]

    output = format_history(entries)
    assert "EVALUATION HISTORY" in output
    assert "abc123de" in output  # Truncated SHA
    assert "main" in output
    assert "2" in output  # 2 sites


def test_format_trend_empty(mock_history_dir):
    """Test format_trend with no entries."""
    from evals.history import format_trend

    output = format_trend([])
    assert "No history data" in output


def test_format_trend_produces_chart(mock_history_dir):
    """Test format_trend produces ASCII chart."""
    from evals.history import format_trend

    entries = [
        {
            "timestamp": "2026-01-01T10:00:00Z",
            "git_sha": f"commit{i}",
            "branch": "main",
            "scores": {
                "site1": {
                    "tier1": {"overall_score": 0.5 + (i * 0.05)},  # Increasing trend
                },
            },
        }
        for i in range(5)
    ]

    output = format_trend(entries)
    assert "Score Trend" in output
    assert "100%" in output  # Y-axis label
    assert "0%" in output
    # Should contain some bars
    assert "██" in output or "│" in output


def test_format_trend_with_site_filter(mock_history_dir):
    """Test format_trend with site filter."""
    from evals.history import format_trend

    entries = [
        {
            "timestamp": "2026-01-01T10:00:00Z",
            "git_sha": "commit1",
            "branch": "main",
            "scores": {
                "site1": {"tier1": {"overall_score": 0.8}},
                "site2": {"tier1": {"overall_score": 0.6}},
            },
        },
    ]

    output = format_trend(entries, site="site1")
    assert "site1" in output


def test_format_trend_with_tier_filter(mock_history_dir):
    """Test format_trend with tier filter."""
    from evals.history import format_trend

    entries = [
        {
            "timestamp": "2026-01-01T10:00:00Z",
            "git_sha": "commit1",
            "branch": "main",
            "scores": {
                "site1": {
                    "schema_org": {"overall_score": 0.8},
                    "opengraph": {"overall_score": 0.6},
                },
            },
        },
    ]

    output = format_trend(entries, tier="schema_org")
    assert "schema_org" in output


def test_format_trend_no_matching_data(mock_history_dir):
    """Test format_trend with filters that match nothing."""
    from evals.history import format_trend

    entries = [
        {
            "timestamp": "2026-01-01T10:00:00Z",
            "git_sha": "commit1",
            "branch": "main",
            "scores": {
                "site1": {"tier1": {"overall_score": 0.8}},
            },
        },
    ]

    output = format_trend(entries, site="nonexistent")
    assert "No matching data points" in output


def test_git_sha_fallback(mock_history_dir, sample_reports):
    """Test that save_run handles git command failures gracefully."""
    from evals.history import save_run

    history_dir, history_file = mock_history_dir

    # Simulate git command failure
    with patch("evals.history._get_git_sha", return_value=""):
        with patch("evals.history._get_git_branch", return_value=""):
            save_run(sample_reports)

    content = history_file.read_text()
    entry = json.loads(content.strip())
    assert entry["git_sha"] == ""
    assert entry["branch"] == ""


def test_save_run_stores_all_metrics(mock_history_dir, sample_reports):
    """Test that save_run stores all expected metrics."""
    from evals.history import save_run

    history_dir, history_file = mock_history_dir

    with patch("evals.history._get_git_sha", return_value="abc123"):
        with patch("evals.history._get_git_branch", return_value="main"):
            save_run(sample_reports)

    content = history_file.read_text()
    entry = json.loads(content.strip())

    # Check structure
    site_scores = entry["scores"]["test_site"]
    tier_scores = site_scores["schema_org"]

    assert "avg_score" in tier_scores
    assert "overall_score" in tier_scores
    assert "products_extracted" in tier_scores
    assert "completeness" in tier_scores
    assert "duration" in tier_scores

    # Check types and rounding
    assert isinstance(tier_scores["avg_score"], float)
    assert isinstance(tier_scores["overall_score"], float)
    assert isinstance(tier_scores["products_extracted"], int)
    assert isinstance(tier_scores["completeness"], float)
    assert isinstance(tier_scores["duration"], float)
