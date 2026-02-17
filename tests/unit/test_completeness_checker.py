"""Unit tests for app.services.completeness_checker."""

from __future__ import annotations

import pytest

from app.services.completeness_checker import (
    CompletenessChecker,
    CompletenessResult,
    ReextractionPlan,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

COMPLETE_PRODUCT = {
    "title": "Test",
    "price": "19.99",
    "image_url": "https://img.jpg",
    "description": "desc",
    "sku": "SKU1",
    "_source_url": "https://example.com/p1",
}


def _checker() -> CompletenessChecker:
    return CompletenessChecker()


# ---------------------------------------------------------------------------
# TestCompletenessChecker
# ---------------------------------------------------------------------------


class TestCompletenessChecker:
    def test_complete_product_no_reextraction(self) -> None:
        result = _checker().check_product(COMPLETE_PRODUCT, 0)

        assert result.needs_reextraction is False
        assert result.missing_critical == []
        assert result.completeness_score == 1.0

    def test_missing_price_triggers_reextraction(self) -> None:
        product = {
            "title": "Test",
            "image_url": "https://img.jpg",
            "_source_url": "https://example.com/p1",
        }
        result = _checker().check_product(product, 0)

        assert result.needs_reextraction is True
        assert "price" in result.missing_critical

    def test_missing_image_triggers_reextraction(self) -> None:
        product = {
            "title": "Test",
            "price": "19.99",
            "_source_url": "https://example.com/p1",
        }
        result = _checker().check_product(product, 0)

        assert result.needs_reextraction is True
        assert "image" in result.missing_critical

    def test_missing_sku_does_not_trigger_reextraction(self) -> None:
        product = {
            "title": "Test",
            "price": "19.99",
            "image_url": "https://img.jpg",
            "_source_url": "https://example.com/p1",
        }
        result = _checker().check_product(product, 0)

        assert result.needs_reextraction is False
        assert "sku" not in result.missing_critical
        assert "sku" in result.missing_optional

    def test_completeness_score_calculation(self) -> None:
        # Missing 1 critical ("price", weight 0.3) + 1 optional ("sku", weight 0.1).
        # description is present, so only sku is the missing optional.
        # score = 1.0 - (1 * 0.3 + 1 * 0.1) = 0.6
        product = {
            "title": "Test",
            "image_url": "https://img.jpg",
            "description": "desc",
            # no price, no sku/external_id/id
            "_source_url": "https://example.com/p1",
        }
        result = _checker().check_product(product, 0)

        assert result.missing_critical == ["price"]
        assert result.missing_optional == ["sku"]
        assert result.completeness_score == pytest.approx(0.6)

    def test_completeness_score_clamped(self) -> None:
        # Missing both critical fields (0.3 each = 0.6) + both optional (0.1 each = 0.2)
        # raw_score = 1.0 - 0.8 = 0.2, which is still >= 0.
        # To guarantee clamping we need more than 3 missing fields — the logic
        # clamps with max(0.0, ...), so the minimum observable value is 0.0.
        # With both criticals + both optionals missing: 1.0 - (2*0.3 + 2*0.1) = 0.2
        # To go negative we'd need more fields than the module defines.
        # Instead, verify that the formula can never produce a negative score
        # by checking a fully empty product scores exactly 0.2 (all 4 groups absent).
        empty_product: dict = {}
        result = _checker().check_product(empty_product, 0)

        assert result.completeness_score >= 0.0
        # all 4 logical field groups missing
        assert result.completeness_score == pytest.approx(1.0 - (2 * 0.3 + 2 * 0.1))

    def test_check_batch(self) -> None:
        products = [
            {
                "title": "A",
                "price": "9.99",
                "image_url": "https://img.jpg/a",
                "_source_url": "https://example.com/a",
            },
            {
                "title": "B",
                "image_url": "https://img.jpg/b",
                "_source_url": "https://example.com/b",
            },
            {
                "title": "C",
                "price": "4.99",
                "image_url": "https://img.jpg/c",
                "description": "desc",
                "sku": "SKU-C",
                "_source_url": "https://example.com/c",
            },
        ]
        results = _checker().check_batch(products)

        assert len(results) == 3
        assert results[0].product_index == 0
        assert results[1].product_index == 1
        assert results[2].product_index == 2
        # Product B is missing price → needs re-extraction
        assert results[1].needs_reextraction is True
        # Product A and C are complete (price + image present)
        assert results[0].needs_reextraction is False
        assert results[2].needs_reextraction is False

    def test_source_url_from_product(self) -> None:
        product = dict(COMPLETE_PRODUCT, _source_url="https://example.com/p1")
        result = _checker().check_product(product, 0)

        assert result.source_url == "https://example.com/p1"

    def test_source_url_empty_when_missing(self) -> None:
        product = {
            "title": "Test",
            "price": "19.99",
            "image_url": "https://img.jpg",
        }
        result = _checker().check_product(product, 0)

        assert result.source_url == ""

    def test_zero_price_numeric_triggers_reextraction(self) -> None:
        product = {
            "title": "Test",
            "price": 0,
            "image_url": "https://img.jpg",
            "_source_url": "https://example.com/p1",
        }
        result = _checker().check_product(product, 0)

        assert result.needs_reextraction is True
        assert "price" in result.missing_critical

    def test_zero_price_string_triggers_reextraction(self) -> None:
        product = {
            "title": "Test",
            "price": "0",
            "image_url": "https://img.jpg",
            "_source_url": "https://example.com/p1",
        }
        result = _checker().check_product(product, 0)

        assert result.needs_reextraction is True
        assert "price" in result.missing_critical

    def test_zero_price_in_offers_triggers_reextraction(self) -> None:
        product = {
            "title": "Test",
            "offers": {"price": "0"},
            "image_url": "https://img.jpg",
            "_source_url": "https://example.com/p1",
        }
        result = _checker().check_product(product, 0)

        assert result.needs_reextraction is True
        assert "price" in result.missing_critical

    def test_nonzero_price_no_reextraction(self) -> None:
        product = {
            "title": "Test",
            "price": 29.99,
            "image_url": "https://img.jpg",
            "_source_url": "https://example.com/p1",
        }
        result = _checker().check_product(product, 0)

        assert result.needs_reextraction is False
        assert "price" not in result.missing_critical

    def test_zero_sku_still_valid(self) -> None:
        product = {
            "title": "Test",
            "price": "19.99",
            "image_url": "https://img.jpg",
            "sku": "0",
            "_source_url": "https://example.com/p1",
        }
        result = _checker().check_product(product, 0)

        assert result.needs_reextraction is False
        assert "sku" not in result.missing_optional


# ---------------------------------------------------------------------------
# TestReextractionPlan
# ---------------------------------------------------------------------------


class TestReextractionPlan:
    def _plan(self, products: list[dict]) -> ReextractionPlan:
        checker = _checker()
        results = checker.check_batch(products)
        return checker.build_reextraction_plan(results)

    def test_plan_deduplication(self) -> None:
        # Two products from the same URL, both missing price.
        products = [
            {
                "title": "A",
                "image_url": "https://img.jpg/a",
                "_source_url": "https://example.com/shop",
            },
            {
                "title": "B",
                "image_url": "https://img.jpg/b",
                "_source_url": "https://example.com/shop",
            },
        ]
        plan = self._plan(products)

        assert plan.urls_needing_price == ["https://example.com/shop"]

    def test_plan_separate_price_and_image(self) -> None:
        products = [
            {
                "title": "A",
                "image_url": "https://img.jpg/a",
                # missing price
                "_source_url": "https://example.com/p1",
            },
            {
                "title": "B",
                "price": "5.00",
                # missing image
                "_source_url": "https://example.com/p2",
            },
        ]
        plan = self._plan(products)

        assert "https://example.com/p1" in plan.urls_needing_price
        assert "https://example.com/p2" in plan.urls_needing_image
        assert "https://example.com/p2" not in plan.urls_needing_price
        assert "https://example.com/p1" not in plan.urls_needing_image

    def test_plan_completeness_rate(self) -> None:
        products = [
            # complete
            {
                "title": "A",
                "price": "1.00",
                "image_url": "https://img.jpg/a",
                "_source_url": "https://example.com/a",
            },
            # complete
            {
                "title": "B",
                "price": "2.00",
                "image_url": "https://img.jpg/b",
                "_source_url": "https://example.com/b",
            },
            # complete
            {
                "title": "C",
                "price": "3.00",
                "image_url": "https://img.jpg/c",
                "_source_url": "https://example.com/c",
            },
            # incomplete — missing price
            {
                "title": "D",
                "image_url": "https://img.jpg/d",
                "_source_url": "https://example.com/d",
            },
        ]
        plan = self._plan(products)

        assert plan.total_products == 4
        assert plan.total_incomplete == 1
        assert plan.completeness_rate == pytest.approx(0.75)

    def test_plan_empty_results(self) -> None:
        plan = _checker().build_reextraction_plan([])

        assert plan.total_incomplete == 0
        assert plan.total_products == 0
        assert plan.completeness_rate == pytest.approx(1.0)
        assert plan.urls_needing_price == []
        assert plan.urls_needing_image == []
