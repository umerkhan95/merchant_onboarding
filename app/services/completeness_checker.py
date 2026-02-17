"""Product data completeness checking. Identifies missing critical fields and builds re-extraction plans."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.services.extraction_tracker import SOURCE_URL_KEY

logger = logging.getLogger(__name__)

CRITICAL_FIELDS: dict[str, tuple[str, ...]] = {
    "price": ("price", "og:price:amount", "offers"),
    "image": ("image_url", "image", "og:image", "images"),
}

OPTIONAL_FIELDS: dict[str, tuple[str, ...]] = {
    "description": ("description", "body_html", "og:description", "short_description"),
    "sku": ("sku", "external_id", "id"),
}


@dataclass
class CompletenessResult:
    source_url: str
    product_index: int
    missing_critical: list[str] = field(default_factory=list)
    missing_optional: list[str] = field(default_factory=list)
    completeness_score: float = 1.0
    needs_reextraction: bool = False


@dataclass
class ReextractionPlan:
    urls_needing_price: list[str] = field(default_factory=list)
    urls_needing_image: list[str] = field(default_factory=list)
    total_incomplete: int = 0
    total_products: int = 0
    completeness_rate: float = 1.0


class CompletenessChecker:
    """Check product data completeness and build re-extraction plans.

    Stateless — takes raw product dicts, returns completeness results and plans.
    Does not perform any re-extraction.
    """

    def check_product(self, product: dict, index: int) -> CompletenessResult:
        """Check a single product dict for missing critical and optional fields.

        Args:
            product: Raw product dict. May contain a ``_source_url`` key.
            index: Position of this product in its batch.

        Returns:
            CompletenessResult describing which fields are absent.
        """
        source_url = product.get(SOURCE_URL_KEY, "")
        missing_critical: list[str] = []
        missing_optional: list[str] = []

        for field_name, field_aliases in CRITICAL_FIELDS.items():
            if not self._has_any_field(product, field_aliases):
                missing_critical.append(field_name)
            elif field_name == "price" and self._price_is_zero(product, field_aliases):
                missing_critical.append(field_name)

        for field_name, field_aliases in OPTIONAL_FIELDS.items():
            if not self._has_any_field(product, field_aliases):
                missing_optional.append(field_name)

        raw_score = 1.0 - (len(missing_critical) * 0.3 + len(missing_optional) * 0.1)
        completeness_score = max(0.0, min(1.0, raw_score))
        needs_reextraction = len(missing_critical) > 0

        return CompletenessResult(
            source_url=source_url,
            product_index=index,
            missing_critical=missing_critical,
            missing_optional=missing_optional,
            completeness_score=completeness_score,
            needs_reextraction=needs_reextraction,
        )

    def check_batch(self, products: list[dict]) -> list[CompletenessResult]:
        """Check a batch of product dicts.

        Args:
            products: List of raw product dicts.

        Returns:
            One CompletenessResult per product, in the same order.
        """
        return [self.check_product(p, i) for i, p in enumerate(products)]

    def build_reextraction_plan(self, results: list[CompletenessResult]) -> ReextractionPlan:
        """Build a de-duplicated plan of URLs that need targeted re-extraction.

        Args:
            results: CompletenessResult list produced by ``check_batch()``.

        Returns:
            ReextractionPlan with sorted, unique URL lists and summary stats.
        """
        price_urls: set[str] = set()
        image_urls: set[str] = set()

        for result in results:
            if "price" in result.missing_critical:
                price_urls.add(result.source_url)
            if "image" in result.missing_critical:
                image_urls.add(result.source_url)

        total_incomplete = sum(1 for r in results if r.needs_reextraction)
        total_products = len(results)
        completeness_rate = (
            1.0 - (total_incomplete / total_products) if total_products > 0 else 1.0
        )

        logger.debug(
            "Re-extraction plan: %d/%d incomplete products, %.1f%% complete",
            total_incomplete,
            total_products,
            completeness_rate * 100,
        )

        return ReextractionPlan(
            urls_needing_price=sorted(price_urls),
            urls_needing_image=sorted(image_urls),
            total_incomplete=total_incomplete,
            total_products=total_products,
            completeness_rate=completeness_rate,
        )

    @staticmethod
    def _has_any_field(product: dict, field_names: tuple[str, ...]) -> bool:
        """Check if product has any of the given fields with a non-empty value.

        Numeric zero is treated as *absent* — a price of 0 is not meaningful data.
        """
        for name in field_names:
            val = product.get(name)
            if val is None:
                continue
            if isinstance(val, (int, float)):
                if val != 0:
                    return True
                continue
            if isinstance(val, list):
                if val:
                    return True
                continue
            if isinstance(val, dict):
                if val:
                    return True
                continue
            if str(val).strip():
                return True
        return False

    @staticmethod
    def _price_is_zero(product: dict, field_names: tuple[str, ...]) -> bool:
        """Return True when a price field is present but its value is zero.

        Handles edge cases that ``_has_any_field`` lets through because the raw
        value is a non-empty string (``"0"``, ``"0.00"``) or a dict with a zero
        inner price (``{"price": "0"}``).
        """
        for name in field_names:
            val = product.get(name)
            if val is None:
                continue
            if isinstance(val, dict):
                inner = val.get("price")
                if inner is not None:
                    try:
                        return float(inner) == 0
                    except (ValueError, TypeError):
                        return False
            if isinstance(val, (int, float)):
                return val == 0
            if isinstance(val, str):
                try:
                    return float(val.strip().replace(",", ".")) == 0
                except ValueError:
                    return False
        return False
