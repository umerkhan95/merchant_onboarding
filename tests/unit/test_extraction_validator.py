"""Unit tests for ExtractionValidator."""

from __future__ import annotations

import pytest

from app.extractors.base import ExtractionResult
from app.models.enums import ExtractionTier
from app.services.extraction_validator import ExtractionValidator, ValidationResult


@pytest.fixture
def validator():
    return ExtractionValidator()


class TestValidationResult:
    """Tests for ValidationResult dataclass."""

    def test_valid_result_is_truthy(self):
        result = ValidationResult(is_valid=True, reason="passed")
        assert result
        assert bool(result) is True

    def test_invalid_result_is_falsy(self):
        result = ValidationResult(is_valid=False, reason="zero_products")
        assert not result
        assert bool(result) is False


class TestExtractionValidator:
    """Tests for ExtractionValidator.validate()."""

    def test_valid_extraction(self, validator):
        """Extraction with products and good quality passes."""
        result = ExtractionResult(
            products=[{"title": "Product", "price": "$10"}],
            tier=ExtractionTier.API,
            quality_score=0.55,
            urls_attempted=1,
        )
        validation = validator.validate(result)
        assert validation.is_valid
        assert validation.reason == "passed"

    def test_zero_products_fails(self, validator):
        """Extraction with 0 products fails validation."""
        result = ExtractionResult(
            products=[],
            tier=ExtractionTier.API,
            quality_score=0.0,
            urls_attempted=5,
        )
        validation = validator.validate(result)
        assert not validation.is_valid
        assert validation.reason == "zero_products"

    def test_low_quality_fails(self, validator):
        """Extraction with quality below threshold fails."""
        result = ExtractionResult(
            products=[{"price": "$10"}],  # no title = 0.0 quality
            tier=ExtractionTier.SITEMAP_CSS,
            quality_score=0.1,
            urls_attempted=3,
        )
        validation = validator.validate(result)
        assert not validation.is_valid
        assert validation.reason == "low_quality"

    def test_quality_at_threshold_passes(self, validator):
        """Extraction with quality exactly at threshold passes."""
        result = ExtractionResult(
            products=[{"title": "Product"}],
            tier=ExtractionTier.LLM,
            quality_score=0.3,
            urls_attempted=1,
        )
        validation = validator.validate(result)
        assert validation.is_valid

    def test_quality_just_below_threshold_fails(self, validator):
        """Extraction with quality just below threshold fails."""
        result = ExtractionResult(
            products=[{"title": "Product"}],
            tier=ExtractionTier.LLM,
            quality_score=0.29,
            urls_attempted=1,
        )
        validation = validator.validate(result)
        assert not validation.is_valid
        assert validation.reason == "low_quality"

    def test_custom_threshold(self):
        """Custom min_quality threshold is respected."""
        strict_validator = ExtractionValidator(min_quality=0.7)
        result = ExtractionResult(
            products=[{"title": "Product", "price": "$10"}],
            tier=ExtractionTier.API,
            quality_score=0.55,
            urls_attempted=1,
        )
        validation = strict_validator.validate(result)
        assert not validation.is_valid
        assert validation.reason == "low_quality"

    def test_message_includes_details(self, validator):
        """Validation messages include relevant details."""
        result = ExtractionResult(
            products=[],
            tier=ExtractionTier.SMART_CSS,
            quality_score=0.0,
            urls_attempted=10,
        )
        validation = validator.validate(result)
        assert "0 products" in validation.message
        assert "smart_css" in validation.message


class TestExtractionResult:
    """Tests for ExtractionResult dataclass."""

    def test_product_count(self):
        result = ExtractionResult(products=[{"a": 1}, {"b": 2}], tier=ExtractionTier.API)
        assert result.product_count == 2

    def test_is_empty(self):
        result = ExtractionResult(products=[], tier=ExtractionTier.API)
        assert result.is_empty

    def test_is_not_empty(self):
        result = ExtractionResult(products=[{"title": "x"}], tier=ExtractionTier.API)
        assert not result.is_empty

    def test_is_acceptable_with_good_quality(self):
        result = ExtractionResult(
            products=[{"title": "x"}], tier=ExtractionTier.API, quality_score=0.5
        )
        assert result.is_acceptable

    def test_is_not_acceptable_when_empty(self):
        result = ExtractionResult(
            products=[], tier=ExtractionTier.API, quality_score=0.5
        )
        assert not result.is_acceptable

    def test_is_not_acceptable_when_low_quality(self):
        result = ExtractionResult(
            products=[{"title": "x"}], tier=ExtractionTier.API, quality_score=0.1
        )
        assert not result.is_acceptable

    def test_errors_default_empty(self):
        result = ExtractionResult(products=[], tier=ExtractionTier.API)
        assert result.errors == []
