"""Celery tasks for onboarding jobs."""

from __future__ import annotations

# Placeholder for Celery task - will be implemented in pipeline orchestrator ticket
# This file exists to allow imports in API routes


class MockCeleryTask:
    """Mock Celery task for testing."""

    def delay(self, *args, **kwargs):  # noqa: ANN002, ANN003, ANN201
        """Mock delay method."""
        return None


# Placeholder task
process_onboarding_job = MockCeleryTask()
