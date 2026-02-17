"""Unit tests for ProductPageValidator."""

from __future__ import annotations

import pytest

from app.services.page_validator import PageValidationResult, ProductPageValidator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FILLER = "x " * 300  # 600 chars — safely clears the 500-char threshold


def _make_html(body_content: str, head_content: str = "") -> str:
    """Wrap content in a full HTML document with enough filler text to pass
    the 500-character body threshold."""
    return (
        "<!DOCTYPE html>"
        "<html>"
        f"<head>{head_content}</head>"
        f"<body>{body_content}<p>{_FILLER}</p></body>"
        "</html>"
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestProductPageValidator:
    def setup_method(self) -> None:
        self.validator = ProductPageValidator()

    # ------------------------------------------------------------------
    # 1. JSON-LD Product detection
    # ------------------------------------------------------------------

    def test_json_ld_product_detected(self) -> None:
        html = _make_html(
            '<script type="application/ld+json">'
            '{"@type":"Product","name":"Test"}'
            "</script>"
        )
        result = self.validator.validate(html, url="https://example.com/product/test")

        assert result.is_product_page is True
        assert "json_ld_product" in result.signals
        assert result.confidence >= 0.4
        assert result.rejection_reason == ""

    # ------------------------------------------------------------------
    # 2. OG product price tag detection
    # ------------------------------------------------------------------

    def test_og_product_tags_detected(self) -> None:
        html = _make_html(
            body_content="<h1>My Product</h1>",
            head_content='<meta property="product:price:amount" content="19.99">',
        )
        result = self.validator.validate(html, url="https://example.com/product/test")

        assert "og_product_price" in result.signals

    # ------------------------------------------------------------------
    # 3. Add-to-cart button detection
    # ------------------------------------------------------------------

    def test_add_to_cart_button_detected(self) -> None:
        html = _make_html('<button class="add-to-cart">Add to Cart</button>')
        result = self.validator.validate(html, url="https://example.com/product/test")

        assert "add_to_cart" in result.signals

    # ------------------------------------------------------------------
    # 4. 404 page rejection
    # ------------------------------------------------------------------

    def test_404_page_rejected(self) -> None:
        html = (
            "<!DOCTYPE html>"
            "<html>"
            "<head><title>404 Not Found</title></head>"
            "<body><p>The page you requested could not be found.</p></body>"
            "</html>"
        )
        result = self.validator.validate(html, url="https://example.com/missing")

        assert result.is_product_page is False
        assert result.rejection_reason == "error_page_title"

    # ------------------------------------------------------------------
    # 5. Empty / short page rejection
    # ------------------------------------------------------------------

    def test_empty_page_rejected(self) -> None:
        html = (
            "<!DOCTYPE html>"
            "<html>"
            "<head><title>Product</title></head>"
            "<body><p>Short.</p></body>"
            "</html>"
        )
        result = self.validator.validate(html, url="https://example.com/product/test")

        assert result.is_product_page is False
        assert result.rejection_reason == "insufficient_content"

    # ------------------------------------------------------------------
    # 6. Blog page — no product signals
    # ------------------------------------------------------------------

    def test_blog_page_no_signals(self) -> None:
        body = (
            "<article>"
            "<h1>My Blog Post</h1>"
            "<p>This is an interesting article about Python packaging.</p>"
            f"<p>{_FILLER}</p>"
            "</article>"
        )
        html = _make_html(body)
        result = self.validator.validate(html, url="https://example.com/blog/post")

        assert result.is_product_page is False
        assert result.confidence == 0.0
        assert result.signals == []

    # ------------------------------------------------------------------
    # 7. Confidence accumulation (JSON-LD + add-to-cart + price element)
    # ------------------------------------------------------------------

    def test_confidence_accumulation(self) -> None:
        html = _make_html(
            '<script type="application/ld+json">'
            '{"@type":"Product","name":"Shoes"}'
            "</script>"
            '<button class="add-to-cart">Add to Cart</button>'
            '<span itemprop="price">49.99</span>'
        )
        result = self.validator.validate(html, url="https://example.com/product/shoes")

        # json_ld=0.4, add_to_cart=0.2, price_element=0.15 → 0.75
        assert result.confidence == pytest.approx(0.75)
        assert "json_ld_product" in result.signals
        assert "add_to_cart" in result.signals
        assert "price_element" in result.signals

    # ------------------------------------------------------------------
    # 8. Custom threshold — only add-to-cart (0.2) < threshold 0.5
    # ------------------------------------------------------------------

    def test_custom_threshold(self) -> None:
        validator = ProductPageValidator(threshold=0.5)
        html = _make_html('<button class="add-to-cart">Add to Cart</button>')
        result = validator.validate(html, url="https://example.com/product/test")

        assert result.is_product_page is False
        assert result.confidence == pytest.approx(0.2)

    # ------------------------------------------------------------------
    # 9. JSON-LD as a list containing a Product item
    # ------------------------------------------------------------------

    def test_json_ld_product_in_list(self) -> None:
        html = _make_html(
            '<script type="application/ld+json">'
            '[{"@type":"BreadcrumbList"}, {"@type":"Product","name":"Widget"}]'
            "</script>"
        )
        result = self.validator.validate(html, url="https://example.com/product/widget")

        assert "json_ld_product" in result.signals
        assert result.is_product_page is True

    # ------------------------------------------------------------------
    # 10. Meta-refresh redirect to homepage is rejected
    # ------------------------------------------------------------------

    def test_redirect_to_homepage_rejected(self) -> None:
        html = (
            "<!DOCTYPE html>"
            "<html>"
            '<head><meta http-equiv="refresh" content="0;url=/"></head>'
            f"<body><p>{_FILLER}</p></body>"
            "</html>"
        )
        result = self.validator.validate(html, url="https://example.com/product/gone")

        assert result.is_product_page is False
        assert result.rejection_reason == "redirect_to_homepage"

    # ------------------------------------------------------------------
    # 11. Price element via itemprop="price"
    # ------------------------------------------------------------------

    def test_price_element_detected(self) -> None:
        html = _make_html('<span itemprop="price">19.99</span>')
        result = self.validator.validate(html, url="https://example.com/product/test")

        assert "price_element" in result.signals

    # ------------------------------------------------------------------
    # 12. Product title via .product-title class
    # ------------------------------------------------------------------

    def test_product_title_element_detected(self) -> None:
        html = _make_html('<h1 class="product-title">Product Name</h1>')
        result = self.validator.validate(html, url="https://example.com/product/test")

        assert "product_title" in result.signals
