from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.exceptions.errors import CircuitOpenError
from app.infra import CircuitBreaker, ProgressTracker, RateLimiter, RetryPolicy
from app.infra.circuit_breaker import CircuitState


class TestRateLimiter:
    """Test RateLimiter class."""

    @pytest.mark.asyncio
    async def test_concurrent_requests_limited_per_domain(self) -> None:
        """Test that concurrent requests are limited per domain."""
        rate_limiter = RateLimiter(max_concurrent=2)
        domain = "example.com"
        concurrent_count = 0
        max_concurrent_seen = 0

        async def task() -> None:
            nonlocal concurrent_count, max_concurrent_seen
            async with rate_limiter.acquire(domain):
                concurrent_count += 1
                max_concurrent_seen = max(max_concurrent_seen, concurrent_count)
                await asyncio.sleep(0.01)  # Simulate work
                concurrent_count -= 1

        # Start 5 tasks, but only 2 should run concurrently
        tasks = [task() for _ in range(5)]
        await asyncio.gather(*tasks)

        assert max_concurrent_seen == 2

    @pytest.mark.asyncio
    async def test_different_domains_independent_limits(self) -> None:
        """Test that different domains have independent rate limits."""
        rate_limiter = RateLimiter(max_concurrent=1)
        domain1 = "example.com"
        domain2 = "another.com"

        task1_started = asyncio.Event()
        task2_can_proceed = asyncio.Event()

        async def task1() -> None:
            async with rate_limiter.acquire(domain1):
                task1_started.set()
                await task2_can_proceed.wait()

        async def task2() -> None:
            # Wait for task1 to start
            await task1_started.wait()
            # Should be able to acquire immediately (different domain)
            async with rate_limiter.acquire(domain2):
                task2_can_proceed.set()

        await asyncio.gather(task1(), task2())

    @pytest.mark.asyncio
    async def test_semaphore_creation_thread_safe(self) -> None:
        """Test that semaphore creation is thread-safe."""
        rate_limiter = RateLimiter(max_concurrent=5)
        domain = "example.com"

        async def acquire_and_release() -> None:
            async with rate_limiter.acquire(domain):
                await asyncio.sleep(0.001)

        # Multiple tasks trying to create semaphore simultaneously
        tasks = [acquire_and_release() for _ in range(10)]
        await asyncio.gather(*tasks)

        # Should only have one semaphore for the domain
        assert len(rate_limiter._semaphores) == 1
        assert domain in rate_limiter._semaphores


class TestCircuitBreaker:
    """Test CircuitBreaker class."""

    @pytest.mark.asyncio
    async def test_opens_after_threshold_failures(self) -> None:
        """Test that circuit opens after threshold failures."""
        circuit_breaker = CircuitBreaker(threshold=3, timeout=60)
        domain = "example.com"

        async def failing_task() -> None:
            raise ValueError("Simulated failure")

        # Fail 3 times (threshold)
        for _ in range(3):
            with pytest.raises(ValueError):
                await circuit_breaker.call(domain, failing_task)

        # Check circuit is open
        status = await circuit_breaker.get_status(domain)
        assert status["state"] == CircuitState.OPEN.value

    @pytest.mark.asyncio
    async def test_rejects_calls_when_open(self) -> None:
        """Test that circuit rejects calls when open."""
        circuit_breaker = CircuitBreaker(threshold=2, timeout=60)
        domain = "example.com"

        async def failing_task() -> None:
            raise ValueError("Simulated failure")

        # Fail 2 times to open circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await circuit_breaker.call(domain, failing_task)

        # Next call should raise CircuitOpenError
        with pytest.raises(CircuitOpenError) as exc_info:
            await circuit_breaker.call(domain, failing_task)

        assert domain in str(exc_info.value)

    @pytest.mark.asyncio
    async def test_transitions_to_half_open_after_timeout(self) -> None:
        """Test that circuit transitions to half-open after timeout."""
        circuit_breaker = CircuitBreaker(threshold=2, timeout=0.1)  # 100ms timeout
        domain = "example.com"

        async def failing_task() -> None:
            raise ValueError("Simulated failure")

        # Open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await circuit_breaker.call(domain, failing_task)

        # Verify it's open
        status = await circuit_breaker.get_status(domain)
        assert status["state"] == CircuitState.OPEN.value

        # Wait for timeout
        await asyncio.sleep(0.15)

        # Next call should transition to HALF_OPEN and execute
        with pytest.raises(ValueError):
            await circuit_breaker.call(domain, failing_task)

        # Should be back to OPEN after failed test
        status = await circuit_breaker.get_status(domain)
        assert status["state"] == CircuitState.OPEN.value

    @pytest.mark.asyncio
    async def test_resets_to_closed_on_success_in_half_open(self) -> None:
        """Test that circuit resets to closed on success in half-open state."""
        circuit_breaker = CircuitBreaker(threshold=2, timeout=0.1)
        domain = "example.com"

        call_count = 0

        async def initially_failing_task() -> str:
            nonlocal call_count
            call_count += 1
            if call_count <= 2:
                raise ValueError("Simulated failure")
            return "success"

        # Open the circuit
        for _ in range(2):
            with pytest.raises(ValueError):
                await circuit_breaker.call(domain, initially_failing_task)

        # Wait for timeout
        await asyncio.sleep(0.15)

        # Successful call in HALF_OPEN should reset to CLOSED
        result = await circuit_breaker.call(domain, initially_failing_task)
        assert result == "success"

        status = await circuit_breaker.get_status(domain)
        assert status["state"] == CircuitState.CLOSED.value
        assert status["failure_count"] == 0

    @pytest.mark.asyncio
    async def test_closed_state_increments_failures(self) -> None:
        """Test that failures in CLOSED state increment counter."""
        circuit_breaker = CircuitBreaker(threshold=5, timeout=60)
        domain = "example.com"

        async def failing_task() -> None:
            raise ValueError("Simulated failure")

        # Fail once
        with pytest.raises(ValueError):
            await circuit_breaker.call(domain, failing_task)

        status = await circuit_breaker.get_status(domain)
        assert status["state"] == CircuitState.CLOSED.value
        assert status["failure_count"] == 1

        # Fail again
        with pytest.raises(ValueError):
            await circuit_breaker.call(domain, failing_task)

        status = await circuit_breaker.get_status(domain)
        assert status["failure_count"] == 2

    @pytest.mark.asyncio
    async def test_successful_calls_in_closed_state(self) -> None:
        """Test successful calls in CLOSED state."""
        circuit_breaker = CircuitBreaker(threshold=5, timeout=60)
        domain = "example.com"

        async def successful_task() -> str:
            return "success"

        result = await circuit_breaker.call(domain, successful_task)
        assert result == "success"

        status = await circuit_breaker.get_status(domain)
        assert status["state"] == CircuitState.CLOSED.value
        assert status["success_count"] == 1


class TestRetryPolicy:
    """Test RetryPolicy class."""

    def test_exponential_backoff_increases_delay(self) -> None:
        """Test that exponential backoff increases delay with attempts."""
        delays = [RetryPolicy.calculate_delay(i, base_delay=1.0) for i in range(5)]

        # Each delay should generally be larger than previous (accounting for jitter)
        # Attempt 0: ~1-2 seconds
        # Attempt 1: ~2-3 seconds
        # Attempt 2: ~4-5 seconds
        # Attempt 3: ~8-9 seconds
        # Attempt 4: ~16-17 seconds

        assert 1.0 <= delays[0] <= 2.0
        assert 2.0 <= delays[1] <= 3.0
        assert 4.0 <= delays[2] <= 5.0
        assert 8.0 <= delays[3] <= 9.0
        assert 16.0 <= delays[4] <= 17.0

    def test_respects_max_delay_cap(self) -> None:
        """Test that delays respect max_delay cap."""
        max_delay = 10.0

        # High attempt number should hit max_delay
        delay = RetryPolicy.calculate_delay(10, base_delay=1.0, max_delay=max_delay)

        assert delay <= max_delay

    def test_jitter_adds_randomness(self) -> None:
        """Test that jitter adds randomness to delays."""
        # Calculate multiple delays for same attempt
        delays = [RetryPolicy.calculate_delay(2, base_delay=1.0) for _ in range(10)]

        # Not all delays should be identical (due to jitter)
        assert len(set(delays)) > 1

    def test_should_retry_returns_false_after_max_retries(self) -> None:
        """Test that should_retry returns False after max_retries."""
        max_retries = 3

        assert RetryPolicy.should_retry(0, max_retries) is True
        assert RetryPolicy.should_retry(1, max_retries) is True
        assert RetryPolicy.should_retry(2, max_retries) is True
        assert RetryPolicy.should_retry(3, max_retries) is False
        assert RetryPolicy.should_retry(4, max_retries) is False

    def test_should_retry_with_zero_retries(self) -> None:
        """Test should_retry with max_retries=0."""
        assert RetryPolicy.should_retry(0, max_retries=0) is False

    def test_calculate_delay_with_custom_base(self) -> None:
        """Test calculate_delay with custom base_delay."""
        delay = RetryPolicy.calculate_delay(0, base_delay=2.0)

        # Attempt 0: base_delay * 2^0 + jitter = 2.0 + [0, 2.0]
        assert 2.0 <= delay <= 4.0


class TestProgressTracker:
    """Test ProgressTracker class."""

    @pytest.fixture
    def mock_redis(self) -> MagicMock:
        """Create mock Redis client."""
        mock = MagicMock()
        mock.hset = AsyncMock()
        mock.expire = AsyncMock()
        mock.hgetall = AsyncMock()
        mock.delete = AsyncMock()
        return mock

    @pytest.fixture
    def tracker(self, mock_redis: MagicMock) -> ProgressTracker:
        """Create ProgressTracker with mock Redis."""
        return ProgressTracker(mock_redis)

    @pytest.mark.asyncio
    async def test_update_and_get_round_trip(
        self, tracker: ProgressTracker, mock_redis: MagicMock
    ) -> None:
        """Test update and get round-trip."""
        job_id = "job-123"
        processed = 50
        total = 100
        status = "processing"
        current_step = "Extracting products"

        # Update progress
        await tracker.update(job_id, processed, total, status, current_step)

        # Verify hset was called with correct data
        call_args = mock_redis.hset.call_args
        assert call_args[0][0] == "progress:job-123"
        mapping = call_args[1]["mapping"]
        assert mapping["processed"] == 50
        assert mapping["total"] == 100
        assert mapping["percentage"] == 50.0
        assert mapping["status"] == "processing"
        assert mapping["current_step"] == "Extracting products"

        # Verify expire was called
        mock_redis.expire.assert_called_once_with("progress:job-123", 86400)

    @pytest.mark.asyncio
    async def test_update_with_error(
        self, tracker: ProgressTracker, mock_redis: MagicMock
    ) -> None:
        """Test update with error message."""
        job_id = "job-123"
        error_msg = "Failed to connect to database"

        await tracker.update(
            job_id,
            processed=10,
            total=100,
            status="failed",
            current_step="Database connection",
            error=error_msg,
        )

        call_args = mock_redis.hset.call_args
        mapping = call_args[1]["mapping"]
        assert mapping["error"] == error_msg

    @pytest.mark.asyncio
    async def test_get_parses_numeric_values(
        self, tracker: ProgressTracker, mock_redis: MagicMock
    ) -> None:
        """Test that get() properly parses numeric values."""
        # Mock Redis response (bytes)
        mock_redis.hgetall.return_value = {
            b"processed": b"75",
            b"total": b"100",
            b"percentage": b"75.0",
            b"status": b"processing",
            b"current_step": b"Validating data",
        }

        result = await tracker.get("job-123")

        assert result is not None
        assert result["processed"] == 75
        assert result["total"] == 100
        assert result["percentage"] == 75.0
        assert result["status"] == "processing"
        assert result["current_step"] == "Validating data"

    @pytest.mark.asyncio
    async def test_get_returns_none_when_not_found(
        self, tracker: ProgressTracker, mock_redis: MagicMock
    ) -> None:
        """Test that get() returns None when job not found."""
        mock_redis.hgetall.return_value = {}

        result = await tracker.get("nonexistent-job")

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_removes_progress(
        self, tracker: ProgressTracker, mock_redis: MagicMock
    ) -> None:
        """Test that delete() removes progress data."""
        job_id = "job-123"

        await tracker.delete(job_id)

        mock_redis.delete.assert_called_once_with("progress:job-123")

    @pytest.mark.asyncio
    async def test_calculates_percentage_correctly(
        self, tracker: ProgressTracker, mock_redis: MagicMock
    ) -> None:
        """Test percentage calculation."""
        await tracker.update(
            job_id="job-123",
            processed=33,
            total=100,
            status="processing",
            current_step="Step 1",
        )

        call_args = mock_redis.hset.call_args
        mapping = call_args[1]["mapping"]
        assert mapping["percentage"] == 33.0

    @pytest.mark.asyncio
    async def test_handles_zero_total(
        self, tracker: ProgressTracker, mock_redis: MagicMock
    ) -> None:
        """Test handling of zero total (edge case)."""
        await tracker.update(
            job_id="job-123",
            processed=0,
            total=0,
            status="pending",
            current_step="Initializing",
        )

        call_args = mock_redis.hset.call_args
        mapping = call_args[1]["mapping"]
        assert mapping["percentage"] == 0.0

    @pytest.mark.asyncio
    async def test_key_format(self, tracker: ProgressTracker) -> None:
        """Test Redis key format."""
        key = tracker._get_key("job-123")
        assert key == "progress:job-123"
