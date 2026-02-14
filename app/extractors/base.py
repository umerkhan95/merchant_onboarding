"""Abstract base class for all data extractors."""

from __future__ import annotations

from abc import ABC, abstractmethod


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
