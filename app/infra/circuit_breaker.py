from __future__ import annotations

import asyncio
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from app.exceptions.errors import CircuitOpenError


class CircuitState(StrEnum):
    """Circuit breaker states."""

    CLOSED = "closed"  # Normal operation
    OPEN = "open"  # Failing, reject all calls
    HALF_OPEN = "half_open"  # Testing recovery with one call


@dataclass
class CircuitStatus:
    """Per-domain circuit breaker status."""

    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    last_failure_time: float = 0.0
    success_count: int = 0


class CircuitBreaker:
    """Circuit breaker for fault tolerance.

    Prevents cascading failures by stopping requests to failing services
    and allowing them time to recover.

    States:
        - CLOSED: Normal operation, failures increment counter
        - OPEN: Service is failing, reject all calls
        - HALF_OPEN: Testing if service recovered with one call
    """

    def __init__(self, threshold: int = 5, timeout: int = 60) -> None:
        """Initialize circuit breaker.

        Args:
            threshold: Number of failures before opening circuit (default: 5)
            timeout: Seconds to wait before transitioning to HALF_OPEN (default: 60)
        """
        self.threshold = threshold
        self.timeout = timeout
        self._circuits: dict[str, CircuitStatus] = {}
        self._lock = asyncio.Lock()

    async def call(
        self, domain: str, coro: Callable[[], Coroutine[Any, Any, Any]]
    ) -> Any:
        """Execute async call through circuit breaker.

        Args:
            domain: Domain name for circuit tracking
            coro: Async callable to execute

        Returns:
            Result of the callable

        Raises:
            CircuitOpenError: If circuit is open and timeout hasn't elapsed
            Exception: Any exception raised by the callable

        Example:
            async def fetch_data():
                return await client.get("https://example.com")

            result = await circuit_breaker.call("example.com", fetch_data)
        """
        circuit = await self._get_circuit(domain)

        # Check circuit state
        if circuit.state == CircuitState.OPEN:
            if self._should_attempt_reset(circuit):
                await self._transition_to_half_open(domain, circuit)
            else:
                raise CircuitOpenError(domain)

        # Execute call
        try:
            result = await coro()
            await self._on_success(domain, circuit)
            return result
        except Exception as e:
            await self._on_failure(domain, circuit)
            raise e

    async def _get_circuit(self, domain: str) -> CircuitStatus:
        """Get or create circuit status for domain (thread-safe).

        Args:
            domain: Domain name

        Returns:
            Circuit status for the domain
        """
        if domain in self._circuits:
            return self._circuits[domain]

        async with self._lock:
            if domain not in self._circuits:
                self._circuits[domain] = CircuitStatus()
            return self._circuits[domain]

    def _should_attempt_reset(self, circuit: CircuitStatus) -> bool:
        """Check if enough time has passed to attempt recovery.

        Args:
            circuit: Circuit status

        Returns:
            True if timeout has elapsed since last failure
        """
        return time.time() - circuit.last_failure_time >= self.timeout

    async def _transition_to_half_open(
        self, domain: str, circuit: CircuitStatus
    ) -> None:
        """Transition circuit to HALF_OPEN state.

        Args:
            domain: Domain name
            circuit: Circuit status
        """
        async with self._lock:
            circuit.state = CircuitState.HALF_OPEN

    async def _on_success(self, domain: str, circuit: CircuitStatus) -> None:
        """Handle successful call.

        Args:
            domain: Domain name
            circuit: Circuit status
        """
        async with self._lock:
            if circuit.state == CircuitState.HALF_OPEN:
                # Recovery successful, reset to CLOSED
                circuit.state = CircuitState.CLOSED
                circuit.failure_count = 0
                circuit.success_count = 0
            elif circuit.state == CircuitState.CLOSED:
                # Normal operation, increment success count
                circuit.success_count += 1

    async def _on_failure(self, domain: str, circuit: CircuitStatus) -> None:
        """Handle failed call.

        Args:
            domain: Domain name
            circuit: Circuit status
        """
        async with self._lock:
            circuit.failure_count += 1
            circuit.last_failure_time = time.time()

            if circuit.state == CircuitState.HALF_OPEN:
                # Test failed, back to OPEN
                circuit.state = CircuitState.OPEN
            elif circuit.failure_count >= self.threshold:
                # Threshold exceeded, open circuit
                circuit.state = CircuitState.OPEN

    async def get_status(self, domain: str) -> dict[str, Any]:
        """Get current circuit status for domain.

        Args:
            domain: Domain name

        Returns:
            Dict with state, failure_count, and other status info
        """
        circuit = await self._get_circuit(domain)
        return {
            "state": circuit.state.value,
            "failure_count": circuit.failure_count,
            "success_count": circuit.success_count,
            "last_failure_time": circuit.last_failure_time,
        }
