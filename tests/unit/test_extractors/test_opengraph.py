"""Unit tests for OpenGraphExtractor."""

from __future__ import annotations

import pytest

from app.extractors.opengraph_extractor import OpenGraphExtractor


class TestOpenGraphExtractor:
    """Test suite for OpenGraphExtractor."""

    def test_full_og_tags(self):
        """Test extraction of full OpenGraph tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="Amazing Product">
            <meta property="og:description" content="Best product ever">
            <meta property="og:image" content="https://example.com/image.jpg">
            <meta property="og:url" content="https://example.com/product">
            <meta property="og:price:amount" content="29.99">
            <meta property="og:price:currency" content="USD">
        </head>
        <body></body>
        </html>
        """

        products = OpenGraphExtractor.extract_from_html(html, "https://example.com/product")

        assert len(products) == 1
        og_data = products[0]
        assert og_data["og:title"] == "Amazing Product"
        assert og_data["og:description"] == "Best product ever"
        assert og_data["og:image"] == "https://example.com/image.jpg"
        assert og_data["og:price:amount"] == "29.99"
        assert og_data["og:price:currency"] == "USD"

    def test_partial_og_tags(self):
        """Test extraction when only some OG tags are present."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="Minimal Product">
            <meta property="og:image" content="https://example.com/img.jpg">
            <meta name="description" content="This is not OG">
        </head>
        <body></body>
        </html>
        """

        products = OpenGraphExtractor.extract_from_html(html, "https://example.com/minimal")

        assert len(products) == 1
        og_data = products[0]
        assert og_data["og:title"] == "Minimal Product"
        assert og_data["og:image"] == "https://example.com/img.jpg"
        assert "og:description" not in og_data

    def test_no_og_tags(self):
        """Test when page has no OpenGraph tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <title>Regular Page</title>
            <meta name="description" content="Not OpenGraph">
        </head>
        <body></body>
        </html>
        """

        products = OpenGraphExtractor.extract_from_html(html, "https://example.com/no-og")

        assert products == []

    def test_product_price_tags(self):
        """Test extraction of product:price tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="Product">
            <meta property="product:price:amount" content="49.99">
            <meta property="product:price:currency" content="EUR">
        </head>
        <body></body>
        </html>
        """

        products = OpenGraphExtractor.extract_from_html(html, "https://example.com/product-price")

        assert len(products) == 1
        og_data = products[0]
        assert og_data["product:price:amount"] == "49.99"
        assert og_data["product:price:currency"] == "EUR"

    def test_empty_content_tags(self):
        """Test handling of OG tags with empty content."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="">
            <meta property="og:description" content="Valid description">
        </head>
        <body></body>
        </html>
        """

        products = OpenGraphExtractor.extract_from_html(html, "https://example.com/empty-content")

        # Should skip empty content tags and only extract valid ones
        assert len(products) == 1
        og_data = products[0]
        assert "og:title" not in og_data  # Empty content is skipped
        assert og_data["og:description"] == "Valid description"
        assert len(og_data) == 1

    def test_mixed_og_and_product_tags(self):
        """Test extraction of both og: and product: prefixed tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="Mixed Product">
            <meta property="og:type" content="product">
            <meta property="product:price:amount" content="99.99">
            <meta property="product:availability" content="in stock">
        </head>
        <body></body>
        </html>
        """

        products = OpenGraphExtractor.extract_from_html(html, "https://example.com/mixed")

        assert len(products) == 1
        og_data = products[0]
        assert og_data["og:title"] == "Mixed Product"
        assert og_data["product:price:amount"] == "99.99"
        assert og_data["product:availability"] == "in stock"

    def test_malformed_meta_tags(self):
        """Test handling of malformed meta tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title">
            <meta content="No property">
            <meta property="og:description" content="Valid">
        </head>
        <body></body>
        </html>
        """

        products = OpenGraphExtractor.extract_from_html(html, "https://example.com/malformed")

        assert len(products) == 1
        og_data = products[0]
        # Should only extract valid tag
        assert og_data["og:description"] == "Valid"
        assert len(og_data) == 1

    def test_all_common_og_tags(self):
        """Test extraction of all commonly used OG tags."""
        html = """
        <!DOCTYPE html>
        <html>
        <head>
            <meta property="og:title" content="Complete Product">
            <meta property="og:type" content="product">
            <meta property="og:url" content="https://example.com/complete">
            <meta property="og:image" content="https://example.com/img.jpg">
            <meta property="og:description" content="Complete description">
            <meta property="og:site_name" content="Example Store">
            <meta property="og:price:amount" content="199.99">
            <meta property="og:price:currency" content="GBP">
            <meta property="product:price:amount" content="199.99">
            <meta property="product:condition" content="new">
            <meta property="product:availability" content="in stock">
        </head>
        <body></body>
        </html>
        """

        products = OpenGraphExtractor.extract_from_html(html, "https://example.com/complete")

        assert len(products) == 1
        og_data = products[0]
        assert len(og_data) == 11
        assert og_data["og:title"] == "Complete Product"
        assert og_data["og:type"] == "product"
        assert og_data["product:condition"] == "new"

    def test_from_metadata(self):
        """Test from_metadata static method."""
        metadata = {
            "og:title": "Test Product",
            "og:image": "https://example.com/img.jpg",
            "title": "Page Title",
            "description": "Page description",
        }
        result = OpenGraphExtractor.from_metadata(metadata)
        assert len(result) == 1
        assert result[0]["og:title"] == "Test Product"
        assert result[0]["og:image"] == "https://example.com/img.jpg"
        assert "title" not in result[0]

    def test_from_metadata_empty(self):
        """Test from_metadata with empty metadata."""
        assert OpenGraphExtractor.from_metadata({}) == []
        assert OpenGraphExtractor.from_metadata(None) == []
