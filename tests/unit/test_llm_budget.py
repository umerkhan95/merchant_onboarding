"""Unit tests for LLM budget tracker."""

import logging

import pytest

from app.infra.llm_budget import BudgetExceededError, LLMBudgetTracker


class TestLLMBudgetTracker:
    """Unit tests for LLMBudgetTracker."""

    def test_initial_state(self):
        """New tracker starts with zero cost and full budget."""
        tracker = LLMBudgetTracker(max_budget=10.0)
        assert tracker.total_cost == 0.0
        assert tracker.remaining_budget == 10.0
        assert tracker.call_count == 0

    def test_record_usage_tracks_cost(self):
        """Recording usage accumulates cost correctly."""
        tracker = LLMBudgetTracker(max_budget=10.0)
        cost = tracker.record_usage(input_tokens=1000, output_tokens=500)
        assert cost > 0
        assert tracker.total_cost == cost
        assert tracker.call_count == 1

    def test_record_usage_accumulates(self):
        """Multiple calls accumulate total cost."""
        tracker = LLMBudgetTracker(max_budget=10.0)
        cost1 = tracker.record_usage(input_tokens=1000, output_tokens=500)
        cost2 = tracker.record_usage(input_tokens=2000, output_tokens=1000)
        assert tracker.total_cost == pytest.approx(cost1 + cost2)
        assert tracker.call_count == 2

    def test_remaining_budget_decreases(self):
        """Remaining budget decreases as usage is recorded."""
        tracker = LLMBudgetTracker(max_budget=1.0)
        tracker.record_usage(input_tokens=1000, output_tokens=500)
        assert tracker.remaining_budget < 1.0

    def test_remaining_budget_never_negative(self):
        """Remaining budget floors at zero."""
        tracker = LLMBudgetTracker(max_budget=0.0001)
        tracker.record_usage(input_tokens=10000, output_tokens=5000)
        assert tracker.remaining_budget == 0.0

    def test_check_budget_passes_under_limit(self):
        """check_budget does not raise when under budget."""
        tracker = LLMBudgetTracker(max_budget=100.0)
        tracker.record_usage(input_tokens=1000, output_tokens=500)
        tracker.check_budget()  # Should not raise

    def test_check_budget_raises_over_limit(self):
        """check_budget raises BudgetExceededError when over budget."""
        tracker = LLMBudgetTracker(max_budget=0.0001)
        tracker.record_usage(input_tokens=10000, output_tokens=5000)
        with pytest.raises(BudgetExceededError, match="budget exceeded"):
            tracker.check_budget()

    def test_estimate_cost_does_not_record(self):
        """estimate_cost returns cost without tracking it."""
        tracker = LLMBudgetTracker(max_budget=10.0)
        estimated = tracker.estimate_cost(input_tokens=1000, output_tokens=500)
        assert estimated > 0
        assert tracker.total_cost == 0.0
        assert tracker.call_count == 0

    def test_warning_logged_at_threshold(self, caplog):
        """Warning is logged when usage reaches warn_threshold."""
        tracker = LLMBudgetTracker(
            max_budget=0.001, warn_threshold=0.5
        )
        with caplog.at_level(logging.WARNING):
            # Record enough to exceed 50% of $0.001
            tracker.record_usage(input_tokens=10000, output_tokens=5000)
        assert any("budget" in r.message.lower() for r in caplog.records)

    def test_warning_logged_only_once(self, caplog):
        """Budget warning is logged only once, not on every call."""
        tracker = LLMBudgetTracker(
            max_budget=0.001, warn_threshold=0.5
        )
        with caplog.at_level(logging.WARNING):
            tracker.record_usage(input_tokens=10000, output_tokens=5000)
            tracker.record_usage(input_tokens=10000, output_tokens=5000)

        warning_count = sum(
            1 for r in caplog.records if "budget" in r.message.lower()
        )
        assert warning_count == 1

    def test_summary_returns_dict(self):
        """summary() returns a dict with expected keys."""
        tracker = LLMBudgetTracker(max_budget=50.0)
        tracker.record_usage(input_tokens=3000, output_tokens=500)
        summary = tracker.summary()
        assert "total_cost_usd" in summary
        assert "max_budget_usd" in summary
        assert "remaining_usd" in summary
        assert "call_count" in summary
        assert "total_input_tokens" in summary
        assert "total_output_tokens" in summary
        assert summary["call_count"] == 1
        assert summary["total_input_tokens"] == 3000
        assert summary["total_output_tokens"] == 500

    def test_custom_cost_rates(self):
        """Custom cost-per-token rates are applied correctly."""
        tracker = LLMBudgetTracker(
            max_budget=100.0,
            cost_per_1k_input=0.01,  # $0.01 per 1K input
            cost_per_1k_output=0.03,  # $0.03 per 1K output
        )
        cost = tracker.record_usage(input_tokens=1000, output_tokens=1000)
        # 1K input * $0.01 + 1K output * $0.03 = $0.04
        assert cost == pytest.approx(0.04)
