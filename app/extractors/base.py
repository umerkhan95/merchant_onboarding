"""Abstract base class for all data extractors and extraction result container."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.enums import ExtractionTier


class BaseExtractor(ABC):
    """Base class for extracting product data from various sources."""

    @abstractmethod
    async def extract(self, shop_url: str) -> list[dict]:
        """Extract raw product data from a shop URL.

        Args:
            shop_url: The URL of the shop to extract products from

        Returns:
            List of raw product dicts. NO normalization.
            On error, log and return empty list.
        """

    async def extract_batch(self, urls: list[str]) -> list[dict]:
        """Extract from multiple URLs. Override for batch-optimized implementations.

        Default: sequential extract() calls. Browser-based extractors override
        with arun_many() for single-browser batch extraction.
        """
        all_products = []
        for url in urls:
            products = await self.extract(url)
            all_products.extend(products)
        return all_products


@dataclass
class ExtractionResult:
    """Wraps raw extraction output with quality metadata.

    Created by the pipeline after calling extractors — extractors themselves
    still return plain list[dict] (SRP: extractors extract, pipeline assesses).
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
