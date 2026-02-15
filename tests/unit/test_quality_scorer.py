"""Unit tests for QualityScorer."""

from __future__ import annotations

import pytest

from app.infra.quality_scorer import QualityScorer


@pytest.fixture
def scorer():
    return QualityScorer()


class TestScoreProduct:
    """Tests for scoring individual products."""

    def test_product_with_all_fields(self, scorer):
        """Product with title + price + image + description + sku scores 1.0."""
        product = {
            "title": "Test Product",
            "price": "$29.99",
            "image_url": "https://example.com/img.jpg",
            "description": "A great product",
            "sku": "SKU-123",
        }
        assert scorer.score_product(product) == 1.0

    def test_product_with_title_only(self, scorer):
        """Product with only a title gets base score of 0.4."""
        product = {"title": "Test Product"}
        assert scorer.score_product(product) == 0.4

    def test_product_with_no_title(self, scorer):
        """Product missing title/name scores 0.0 (unusable)."""
        product = {"price": "$29.99", "sku": "SKU-123"}
        assert scorer.score_product(product) == 0.0

    def test_product_with_empty_title(self, scorer):
        """Product with empty string title scores 0.0."""
        product = {"title": "", "price": "$29.99"}
        assert scorer.score_product(product) == 0.0

    def test_product_with_name_field(self, scorer):
        """WooCommerce-style 'name' field counts as title."""
        product = {"name": "WooCommerce Product", "price": "29.99"}
        assert scorer.score_product(product) >= 0.4

    def test_product_with_og_title(self, scorer):
        """OpenGraph 'og:title' field counts as title."""
        product = {"og:title": "OG Product", "og:price:amount": "19.99"}
        assert scorer.score_product(product) >= 0.4

    def test_product_with_title_and_price(self, scorer):
        """Title + price = 0.4 + 0.15 = 0.55."""
        product = {"title": "Product", "price": "$10"}
        assert scorer.score_product(product) == pytest.approx(0.55)

    def test_product_with_title_price_image(self, scorer):
        """Title + price + image = 0.4 + 0.15 + 0.15 = 0.70."""
        product = {"title": "Product", "price": "$10", "image_url": "https://img.com/a.jpg"}
        assert scorer.score_product(product) == pytest.approx(0.70)

    def test_product_with_none_values(self, scorer):
        """None values should not count as present."""
        product = {"title": "Product", "price": None, "image_url": None}
        assert scorer.score_product(product) == 0.4

    def test_product_with_empty_list_images(self, scorer):
        """Empty images list should not count."""
        product = {"title": "Product", "images": []}
        assert scorer.score_product(product) == 0.4

    def test_product_with_nonempty_list_images(self, scorer):
        """Non-empty images list should count."""
        product = {"title": "Product", "images": [{"src": "a.jpg"}]}
        assert scorer.score_product(product) > 0.4

    def test_product_with_offers_dict(self, scorer):
        """Schema.org offers dict counts as price."""
        product = {"title": "Product", "offers": {"price": "29.99"}}
        score = scorer.score_product(product)
        assert score > 0.4

    def test_product_with_body_html(self, scorer):
        """Shopify body_html counts as description."""
        product = {"title": "Product", "body_html": "<p>Description</p>"}
        score = scorer.score_product(product)
        assert score > 0.4

    def test_empty_dict(self, scorer):
        """Empty dict scores 0.0."""
        assert scorer.score_product({}) == 0.0


class TestScoreBatch:
    """Tests for scoring product batches."""

    def test_empty_batch(self, scorer):
        """Empty list scores 0.0."""
        assert scorer.score_batch([]) == 0.0

    def test_single_product_batch(self, scorer):
        """Single product batch equals that product's score."""
        product = {"title": "Product", "price": "$10"}
        assert scorer.score_batch([product]) == scorer.score_product(product)

    def test_mixed_quality_batch(self, scorer):
        """Batch score is the average of individual scores."""
        products = [
            {"title": "Good Product", "price": "$10", "image_url": "a.jpg", "description": "desc", "sku": "SKU"},
            {"title": "Title Only"},
            {"price": "$10"},  # no title = 0.0
        ]
        scores = [scorer.score_product(p) for p in products]
        expected_avg = sum(scores) / len(scores)
        assert scorer.score_batch(products) == pytest.approx(expected_avg)

    def test_all_high_quality(self, scorer):
        """All complete products should score high."""
        products = [
            {"title": f"Product {i}", "price": f"${i}", "image": "img.jpg", "description": "d", "sku": f"S{i}"}
            for i in range(5)
        ]
        assert scorer.score_batch(products) >= 0.9

    def test_all_no_title(self, scorer):
        """Products without titles score 0.0 average."""
        products = [{"price": "$10"}, {"sku": "ABC"}]
        assert scorer.score_batch(products) == 0.0
