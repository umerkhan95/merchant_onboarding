"""LLM cost budget tracker for Tier 4-5 extraction."""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

# Default cost-per-token estimates (USD) for common providers
_COST_PER_1K_INPUT = 0.00015  # gpt-4o-mini input
_COST_PER_1K_OUTPUT = 0.0006  # gpt-4o-mini output


class BudgetExceededError(Exception):
    """Raised when LLM cost budget is exceeded."""


class LLMBudgetTracker:
    """Track cumulative LLM cost per job and enforce budget limits.

    Usage:
        budget = LLMBudgetTracker(max_budget=50.0)
        budget.record_usage(input_tokens=3000, output_tokens=500)
        budget.check_budget()  # raises BudgetExceededError if over limit
    """

    def __init__(
        self,
        max_budget: float = 50.0,
        warn_threshold: float = 0.8,
        cost_per_1k_input: float = _COST_PER_1K_INPUT,
        cost_per_1k_output: float = _COST_PER_1K_OUTPUT,
    ) -> None:
        """Initialize budget tracker.

        Args:
            max_budget: Maximum allowed cost in USD per job (default $50)
            warn_threshold: Fraction of budget at which to log warnings (default 0.8)
            cost_per_1k_input: Cost per 1K input tokens (USD)
            cost_per_1k_output: Cost per 1K output tokens (USD)
        """
        self.max_budget = max_budget
        self.warn_threshold = warn_threshold
        self.cost_per_1k_input = cost_per_1k_input
        self.cost_per_1k_output = cost_per_1k_output
        self._total_cost: float = 0.0
        self._total_input_tokens: int = 0
        self._total_output_tokens: int = 0
        self._call_count: int = 0
        self._warned: bool = False

    @property
    def total_cost(self) -> float:
        return self._total_cost

    @property
    def remaining_budget(self) -> float:
        return max(0.0, self.max_budget - self._total_cost)

    @property
    def call_count(self) -> int:
        return self._call_count

    def estimate_cost(self, input_tokens: int, output_tokens: int) -> float:
        """Estimate cost for a given token count without recording it."""
        return (
            (input_tokens / 1000) * self.cost_per_1k_input
            + (output_tokens / 1000) * self.cost_per_1k_output
        )

    def record_usage(self, input_tokens: int, output_tokens: int) -> float:
        """Record token usage and return the cost of this call.

        Args:
            input_tokens: Number of input tokens used
            output_tokens: Number of output tokens used

        Returns:
            Cost of this individual call in USD
        """
        cost = self.estimate_cost(input_tokens, output_tokens)
        self._total_cost += cost
        self._total_input_tokens += input_tokens
        self._total_output_tokens += output_tokens
        self._call_count += 1

        # Warn at threshold
        if not self._warned and self._total_cost >= self.max_budget * self.warn_threshold:
            self._warned = True
            logger.warning(
                "LLM budget at %.0f%% ($%.4f / $%.2f) after %d calls",
                (self._total_cost / self.max_budget) * 100,
                self._total_cost,
                self.max_budget,
                self._call_count,
            )

        return cost

    def check_budget(self) -> None:
        """Raise BudgetExceededError if budget is exceeded."""
        if self._total_cost > self.max_budget:
            raise BudgetExceededError(
                f"LLM budget exceeded: ${self._total_cost:.4f} > ${self.max_budget:.2f} "
                f"after {self._call_count} calls "
                f"({self._total_input_tokens} input + {self._total_output_tokens} output tokens)"
            )

    def summary(self) -> dict:
        """Return a summary dict for logging/metadata."""
        return {
            "total_cost_usd": round(self._total_cost, 6),
            "max_budget_usd": self.max_budget,
            "remaining_usd": round(self.remaining_budget, 6),
            "call_count": self._call_count,
            "total_input_tokens": self._total_input_tokens,
            "total_output_tokens": self._total_output_tokens,
        }
