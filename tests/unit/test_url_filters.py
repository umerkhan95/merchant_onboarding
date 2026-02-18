"""Unit tests for URL filtering helpers."""

from __future__ import annotations

import pytest

from app.services.url_filters import (
    NON_PRODUCT_PATHS,
    NON_PRODUCT_SEGMENTS,
    PLATFORM_PRODUCT_SITEMAPS,
    is_non_product_url,
)


class TestIsNonProductUrl:
    """Tests for is_non_product_url()."""

    @pytest.mark.parametrize("path", [
        "/about", "/blog", "/cart", "/checkout", "/contact", "/faq",
        "/login", "/privacy-policy", "/terms", "/terms-of-service",
        "/shipping", "/returns", "/wishlist", "/careers", "/press",
    ])
    def test_non_product_paths_exact_match(self, path: str):
        """Exact NON_PRODUCT_PATHS entries are rejected."""
        url = f"https://example.com{path}"
        assert is_non_product_url(url) is True

    def test_root_path_rejected(self):
        assert is_non_product_url("https://example.com/") is True
        assert is_non_product_url("https://example.com") is True

    @pytest.mark.parametrize("url", [
        "https://example.com/blog/my-great-post",
        "https://example.com/checkout/step1",
        "https://example.com/account/orders",
        "https://example.com/help/returns",
        "https://example.com/support/tickets/123",
        "https://example.com/careers/engineering",
        "https://example.com/press/2024",
        "https://example.com/category/shirts",
    ])
    def test_non_product_segments_match(self, url: str):
        """URLs containing a NON_PRODUCT_SEGMENTS part are rejected."""
        assert is_non_product_url(url) is True

    @pytest.mark.parametrize("url", [
        "https://example.com/products/cool-shirt",
        "https://example.com/product/123",
        "https://example.com/shop/shoes",
        "https://example.com/collections/summer",
        "https://example.com/earl-grey-tea",
        "https://example.com/women/dresses",
        "https://example.com/p/abc-123",
    ])
    def test_product_urls_pass_through(self, url: str):
        """Legitimate product URLs are NOT filtered."""
        assert is_non_product_url(url) is False

    @pytest.mark.parametrize("url", [
        "https://example.com/sitemap.xml",
        "https://example.com/robots.txt",
        "https://example.com/style.css",
        "https://example.com/logo.png",
        "https://example.com/data.json",
        "https://example.com/report.pdf",
        "https://example.com/script.js",
    ])
    def test_is_non_product_url_file_extensions(self, url: str):
        """URLs with non-product file extensions are rejected."""
        assert is_non_product_url(url) is True

    def test_query_params_not_matched_as_segments(self):
        """Query parameters should not trigger segment denylist."""
        # ?category=blog should NOT be rejected -- "blog" is in query, not path
        assert is_non_product_url("https://example.com/products?category=blog") is False
        # But /blog/products should be rejected (blog is a path segment)
        assert is_non_product_url("https://example.com/blog/products") is True

    @pytest.mark.parametrize("url", [
        "https://example.com/2023/02/16/what-is-whisky/",
        "https://example.com/2019/11/05/greetings-fans/",
        "https://example.com/2024/01/19/find-the-one/",
    ])
    def test_date_path_blog_posts_rejected(self, url: str):
        """WordPress date-path blog posts (/YYYY/MM/DD/slug) are rejected."""
        assert is_non_product_url(url) is True

    def test_date_like_product_urls_not_rejected(self):
        """Paths that look like dates but aren't blog posts pass through."""
        # Product with numbers in path should NOT be rejected
        assert is_non_product_url("https://example.com/product/2024-edition") is False
        # Year-only path is fine
        assert is_non_product_url("https://example.com/collections/2024") is False


class TestConstants:
    """Sanity checks on module-level constants."""

    def test_platform_product_sitemaps_keys(self):
        assert "shopify" in PLATFORM_PRODUCT_SITEMAPS
        assert "woocommerce" in PLATFORM_PRODUCT_SITEMAPS
        assert "magento" in PLATFORM_PRODUCT_SITEMAPS
        assert "bigcommerce" in PLATFORM_PRODUCT_SITEMAPS
        assert "generic" in PLATFORM_PRODUCT_SITEMAPS

    def test_non_product_paths_has_expected_entries(self):
        assert "/about" in NON_PRODUCT_PATHS
        assert "/cart" in NON_PRODUCT_PATHS
        assert "/checkout" in NON_PRODUCT_PATHS
        assert len(NON_PRODUCT_PATHS) >= 25

    def test_non_product_segments_has_expected_entries(self):
        assert "blog" in NON_PRODUCT_SEGMENTS
        assert "checkout" in NON_PRODUCT_SEGMENTS
        assert "cart" in NON_PRODUCT_SEGMENTS
        assert len(NON_PRODUCT_SEGMENTS) >= 10
