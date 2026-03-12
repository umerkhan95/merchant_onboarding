"""Tests for markdown price/title extractor."""

import pytest

from app.extractors.markdown_price_extractor import (
    extract,
    extract_price,
    extract_title,
)


class TestExtractPrice:
    """Price extraction from text."""

    def test_usd_symbol(self):
        assert extract_price("$49.99") == ("49.99", "USD")

    def test_eur_symbol(self):
        assert extract_price("€29.90") == ("29.90", "EUR")

    def test_gbp_symbol(self):
        assert extract_price("£19.99") == ("19.99", "GBP")

    def test_eur_comma_decimal(self):
        assert extract_price("€29,90") == ("29.90", "EUR")

    def test_european_thousands(self):
        assert extract_price("€1.299,90") == ("1299.90", "EUR")

    def test_usd_thousands(self):
        assert extract_price("$1,299.99") == ("1299.99", "USD")

    def test_iso_code_prefix(self):
        assert extract_price("EUR 29.90") == ("29.90", "EUR")

    def test_iso_code_prefix_usd(self):
        assert extract_price("USD 49.99") == ("49.99", "USD")

    def test_trailing_iso_code(self):
        assert extract_price("49.99 EUR") == ("49.99", "EUR")

    def test_no_currency(self):
        result = extract_price("49.99")
        assert result is not None
        assert result[0] == "49.99"
        assert result[1] is None

    def test_yen_symbol(self):
        assert extract_price("¥3980") is not None
        amount, currency = extract_price("¥3980")
        assert currency == "JPY"

    def test_brazilian_real(self):
        assert extract_price("R$199,90") == ("199.90", "BRL")

    def test_no_price_in_text(self):
        assert extract_price("No price here") is None

    def test_skips_noise_lines(self):
        text = "Shipping $5.99\nPrice: $49.99"
        result = extract_price(text)
        assert result is not None
        assert result[0] == "49.99"

    def test_skips_compare_price(self):
        text = "Was $59.99\n$49.99"
        result = extract_price(text)
        assert result is not None
        assert result[0] == "49.99"

    def test_zero_price_rejected(self):
        assert extract_price("$0.00") is None

    def test_million_plus_rejected(self):
        assert extract_price("$1,500,000.00") is None

    def test_price_range_takes_first(self):
        result = extract_price("$29.99 - $59.99")
        assert result is not None
        assert result[0] == "29.99"

    def test_large_valid_price(self):
        result = extract_price("$999,999.99")
        assert result is not None
        assert result[0] == "999999.99"


class TestExtractTitle:
    """Title extraction from markdown."""

    def test_h1_heading(self):
        md = "# Premium Coffee Beans\n\nDescription here."
        assert extract_title(md) == "Premium Coffee Beans"

    def test_h2_heading_fallback(self):
        md = "Some nav text\n\n## Product Name\n\nDetails."
        assert extract_title(md) == "Product Name"

    def test_h1_preferred_over_h2(self):
        md = "# Main Title\n\n## Subtitle"
        assert extract_title(md) == "Main Title"

    def test_bold_fallback(self):
        md = "**Bold Product Title**\n\nSome description."
        assert extract_title(md) == "Bold Product Title"

    def test_short_title_rejected(self):
        md = "# Hi\n\nContent"
        assert extract_title(md) is None

    def test_no_title(self):
        md = "Just plain text with no headings or bold."
        assert extract_title(md) is None


class TestExtract:
    """Full extraction function."""

    def test_full_extraction(self):
        md = "# Artisan Coffee\n\n$24.99\n\nRich, bold flavor."
        result = extract(md, "https://example.com/product")
        assert result["name"] == "Artisan Coffee"
        assert result["price"] == "24.99"
        assert result["currency"] == "USD"

    def test_price_only(self):
        md = "Some product page\n\n€39,90\n\nDetails."
        result = extract(md)
        assert result["price"] == "39.90"
        assert result["currency"] == "EUR"
        assert "name" not in result

    def test_title_only(self):
        md = "# Product Name\n\nNo price on this page."
        result = extract(md)
        assert result["name"] == "Product Name"
        assert "price" not in result

    def test_empty_markdown(self):
        assert extract("") == {}

    def test_noise_only(self):
        md = "Navigation\nCart\nAbout us\nContact"
        assert extract(md) == {}
