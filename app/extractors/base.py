"""Abstract base class for all data extractors and extraction result container."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.enums import ExtractionTier


@dataclass
class ExtractorResult:
    """Result from a single extractor call.

    Distinguishes "zero products found" (complete=True, products=[]) from
    "extraction failed" (complete=False, error=...). API extractors populate
    pages_completed / pages_expected when pagination is interrupted.
    """

    products: list[dict]
    complete: bool = True
    error: str | None = None
    pages_completed: int | None = None
    pages_expected: int | None = None

    @property
    def product_count(self) -> int:
        return len(self.products)

    @property
    def is_empty(self) -> bool:
        return len(self.products) == 0

    @property
    def is_partial(self) -> bool:
        """True when extraction succeeded but stopped before the last page."""
        return (
            self.complete
            and self.pages_expected is not None
            and self.pages_completed is not None
            and self.pages_completed < self.pages_expected
        )


class BaseExtractor(ABC):
    """Base class for extracting product data from various sources."""

    @abstractmethod
    async def extract(self, shop_url: str) -> ExtractorResult:
        """Extract raw product data from a shop URL.

        Args:
            shop_url: The URL of the shop to extract products from

        Returns:
            ExtractorResult with products and completion metadata.
        """

    async def extract_batch(self, urls: list[str]) -> ExtractorResult:
        """Extract from multiple URLs. Override for batch-optimized implementations.

        Default: sequential extract() calls. Browser-based extractors override
        with arun_many() for single-browser batch extraction.
        """
        all_products = []
        errors = []
        for url in urls:
            result = await self.extract(url)
            all_products.extend(result.products)
            if result.error:
                errors.append(result.error)
        return ExtractorResult(
            products=all_products,
            complete=not errors,
            error="; ".join(errors) if errors else None,
        )


@dataclass
class ExtractionResult:
    """Pipeline-level extraction result with quality metadata.

    Created by the pipeline after calling extractors. Aggregates products
    from ExtractorResult with quality scoring and audit trail.
    """

    products: list[dict]
    tier: ExtractionTier
    quality_score: float = 0.0
    urls_attempted: int = 0
    urls_succeeded: int = 0
    errors: list[str] = field(default_factory=list)
    audit: dict = field(default_factory=dict)

    @property
    def product_count(self) -> int:
        return len(self.products)

    @property
    def is_empty(self) -> bool:
        return len(self.products) == 0

    @property
    def is_acceptable(self) -> bool:
        """Result is acceptable if it has products with reasonable quality."""
        return not self.is_empty and self.quality_score >= 0.3
