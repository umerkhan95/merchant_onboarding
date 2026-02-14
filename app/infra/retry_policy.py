from __future__ import annotations

import random


class RetryPolicy:
    """Retry policy with exponential backoff and jitter.

    Provides configurable retry logic with exponential backoff to prevent
    overwhelming services during temporary failures.
    """

    @staticmethod
    def calculate_delay(
        attempt: int, base_delay: float = 1.0, max_delay: float = 60.0
    ) -> float:
        """Calculate delay for retry attempt using exponential backoff with jitter.

        Formula: min(base_delay * 2^attempt + random_jitter, max_delay)
        Jitter is a random float between 0 and base_delay to prevent thundering herd.

        Args:
            attempt: Current retry attempt number (0-indexed)
            base_delay: Base delay in seconds (default: 1.0)
            max_delay: Maximum delay cap in seconds (default: 60.0)

        Returns:
            Delay in seconds before next retry

        Examples:
            >>> RetryPolicy.calculate_delay(0, base_delay=1.0)  # ~1.0-2.0 seconds
            >>> RetryPolicy.calculate_delay(1, base_delay=1.0)  # ~2.0-3.0 seconds
            >>> RetryPolicy.calculate_delay(5, base_delay=1.0)  # ~32.0-33.0 or max_delay
        """
        # Exponential backoff: base_delay * 2^attempt
        exponential_delay = base_delay * (2**attempt)

        # Add jitter: random value between 0 and base_delay
        jitter = random.uniform(0, base_delay)

        # Apply max delay cap
        total_delay = min(exponential_delay + jitter, max_delay)

        return total_delay

    @staticmethod
    def should_retry(attempt: int, max_retries: int = 3) -> bool:
        """Determine if another retry should be attempted.

        Args:
            attempt: Current retry attempt number (0-indexed)
            max_retries: Maximum number of retries allowed (default: 3)

        Returns:
            True if should retry, False if max retries reached

        Examples:
            >>> RetryPolicy.should_retry(0, max_retries=3)  # True
            >>> RetryPolicy.should_retry(2, max_retries=3)  # True
            >>> RetryPolicy.should_retry(3, max_retries=3)  # False
        """
        return attempt < max_retries
