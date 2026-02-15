"""Extraction result validation. Detects zero-product failures and quality issues."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.extractors.base import ExtractionResult

logger = logging.getLogger(__name__)


@dataclass
class ValidationResult:
    """Outcome of validating an extraction result."""

    is_valid: bool
    reason: str
    message: str = ""

    def __bool__(self) -> bool:
        return self.is_valid


class ExtractionValidator:
    """Validate extraction results before pipeline proceeds.

    Catches two critical failure modes:
    1. Zero products extracted (site worked but nothing found)
    2. Low quality products (data is garbage / missing key fields)
    """

    def __init__(self, min_quality: float = 0.3):
        """Initialize validator.

        Args:
            min_quality: Minimum acceptable quality score (0.0–1.0)
        """
        self.min_quality = min_quality

    def validate(self, result: ExtractionResult) -> ValidationResult:
        """Validate an extraction result.

        Args:
            result: ExtractionResult from the pipeline

        Returns:
            ValidationResult with pass/fail reason
        """
        if result.is_empty:
            msg = (
                f"Extraction returned 0 products "
                f"(tier={result.tier}, urls_attempted={result.urls_attempted})"
            )
            logger.warning(msg)
            return ValidationResult(
                is_valid=False,
                reason="zero_products",
                message=msg,
            )

        if result.quality_score < self.min_quality:
            msg = (
                f"Quality score {result.quality_score:.2f} below threshold "
                f"{self.min_quality} ({result.product_count} products, tier={result.tier})"
            )
            logger.warning(msg)
            return ValidationResult(
                is_valid=False,
                reason="low_quality",
                message=msg,
            )

        logger.info(
            "Extraction validated: %d products, quality=%.2f, tier=%s",
            result.product_count, result.quality_score, result.tier,
        )
        return ValidationResult(
            is_valid=True,
            reason="passed",
            message=f"{result.product_count} products at quality {result.quality_score:.2f}",
        )
