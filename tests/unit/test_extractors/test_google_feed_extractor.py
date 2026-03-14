"""Unit tests for Google Shopping Feed extractor."""

from __future__ import annotations

import pathlib
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.extractors.google_feed_extractor import GoogleFeedExtractor

FIXTURES = pathlib.Path(__file__).resolve().parent.parent.parent / "fixtures"


# ── XML Parsing ─────────────────────────────────────────────────────


class TestXmlParsing:
    """Tests for XML (RSS 2.0) feed parsing."""

    def _load_xml(self) -> str:
        return (FIXTURES / "google_feed.xml").read_text()

    def test_parses_xml_products(self):
        body = self._load_xml()
        products = GoogleFeedExtractor._parse_xml(body, "https://test.com/feed.xml")
        # 5th item has empty title, should be skipped
        assert len(products) == 4

    def test_extracts_basic_fields(self):
        body = self._load_xml()
        products = GoogleFeedExtractor._parse_xml(body, "https://test.com/feed.xml")
        first = products[0]
        assert first["id"] == "PROD-001"
        assert first["title"] == "Weber Spirit II E-310 Gas Grill"
        assert first["link"] == "https://test-store.com/grills/spirit-ii-e310"
        assert first["brand"] == "Weber"
        assert first["mpn"] == "44010001"

    def test_extracts_price_and_currency(self):
        body = self._load_xml()
        products = GoogleFeedExtractor._parse_xml(body, "https://test.com/feed.xml")
        first = products[0]
        assert first["price"] == "449.99"
        assert first["currency"] == "EUR"

    def test_extracts_gtin(self):
        body = self._load_xml()
        products = GoogleFeedExtractor._parse_xml(body, "https://test.com/feed.xml")
        assert products[0]["gtin"] == "4012345678901"
        assert products[2]["gtin"] == "0012345678905"

    def test_extracts_image(self):
        body = self._load_xml()
        products = GoogleFeedExtractor._parse_xml(body, "https://test.com/feed.xml")
        assert products[0]["image_link"] == "https://test-store.com/media/spirit-ii.jpg"

    def test_extracts_additional_images(self):
        body = self._load_xml()
        products = GoogleFeedExtractor._parse_xml(body, "https://test.com/feed.xml")
        first = products[0]
        assert len(first["additional_image_link"]) == 2
        assert "spirit-ii-side.jpg" in first["additional_image_link"][0]
        assert "spirit-ii-top.jpg" in first["additional_image_link"][1]

    def test_extracts_availability(self):
        body = self._load_xml()
        products = GoogleFeedExtractor._parse_xml(body, "https://test.com/feed.xml")
        assert products[0]["availability"] == "in_stock"
        assert products[2]["availability"] == "out_of_stock"

    def test_extracts_condition(self):
        body = self._load_xml()
        products = GoogleFeedExtractor._parse_xml(body, "https://test.com/feed.xml")
        assert products[0]["condition"] == "new"
        assert products[3]["condition"] == "refurbished"

    def test_extracts_product_type(self):
        body = self._load_xml()
        products = GoogleFeedExtractor._parse_xml(body, "https://test.com/feed.xml")
        assert "Grills" in products[0]["product_type"]

    def test_extracts_sale_price(self):
        body = self._load_xml()
        products = GoogleFeedExtractor._parse_xml(body, "https://test.com/feed.xml")
        second = products[1]
        assert second["sale_price"] == "39.99"
        assert second["price"] == "59.99"

    def test_source_tag(self):
        body = self._load_xml()
        products = GoogleFeedExtractor._parse_xml(body, "https://test.com/feed.xml")
        assert all(p["_source"] == "google_feed" for p in products)

    def test_skips_items_without_title(self):
        body = self._load_xml()
        products = GoogleFeedExtractor._parse_xml(body, "https://test.com/feed.xml")
        titles = [p["title"] for p in products]
        assert "" not in titles

    def test_empty_xml_returns_empty(self):
        body = '<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
        products = GoogleFeedExtractor._parse_xml(body, "https://test.com/feed.xml")
        assert products == []

    def test_malformed_xml_raises(self):
        with pytest.raises(Exception):
            GoogleFeedExtractor._parse_xml("<not valid xml>>>", "https://test.com")


# ── CSV/TSV Parsing ──────────────────────────────────────────────────


class TestCsvParsing:
    """Tests for CSV/TSV feed parsing."""

    def _load_csv(self) -> str:
        return (FIXTURES / "google_feed.csv").read_text()

    def test_parses_tsv_products(self):
        body = self._load_csv()
        products = GoogleFeedExtractor._parse_csv(body, "https://test.com/feed.csv")
        assert len(products) == 3

    def test_extracts_basic_fields(self):
        body = self._load_csv()
        products = GoogleFeedExtractor._parse_csv(body, "https://test.com/feed.csv")
        first = products[0]
        assert first["id"] == "PROD-001"
        assert first["title"] == "Weber Spirit II E-310 Gas Grill"
        assert first["brand"] == "Weber"

    def test_extracts_price_and_currency(self):
        body = self._load_csv()
        products = GoogleFeedExtractor._parse_csv(body, "https://test.com/feed.csv")
        assert products[0]["price"] == "449.99"
        assert products[0]["currency"] == "EUR"

    def test_extracts_gtin(self):
        body = self._load_csv()
        products = GoogleFeedExtractor._parse_csv(body, "https://test.com/feed.csv")
        assert products[0]["gtin"] == "4012345678901"

    def test_csv_sale_price(self):
        body = self._load_csv()
        products = GoogleFeedExtractor._parse_csv(body, "https://test.com/feed.csv")
        assert products[1]["sale_price"] == "39.99"

    def test_source_tag(self):
        body = self._load_csv()
        products = GoogleFeedExtractor._parse_csv(body, "https://test.com/feed.csv")
        assert all(p["_source"] == "google_feed" for p in products)

    def test_empty_csv_returns_empty(self):
        body = "id\ttitle\tprice\n"
        products = GoogleFeedExtractor._parse_csv(body, "https://test.com/feed.csv")
        assert products == []


# ── Price String Parsing ─────────────────────────────────────────────


class TestPriceStringParsing:
    """Tests for _parse_price_string."""

    def test_standard_format(self):
        assert GoogleFeedExtractor._parse_price_string("49.99 EUR") == ("49.99", "EUR")

    def test_no_currency(self):
        assert GoogleFeedExtractor._parse_price_string("49.99") == ("49.99", "")

    def test_us_format_with_thousands(self):
        amount, cur = GoogleFeedExtractor._parse_price_string("1,299.99 USD")
        assert amount == "1299.99"
        assert cur == "USD"

    def test_european_comma_decimal(self):
        amount, cur = GoogleFeedExtractor._parse_price_string("49,99 EUR")
        assert amount == "49.99"
        assert cur == "EUR"

    def test_gbp(self):
        assert GoogleFeedExtractor._parse_price_string("19.99 GBP") == ("19.99", "GBP")

    def test_empty_string(self):
        assert GoogleFeedExtractor._parse_price_string("") == ("", "")

    def test_whitespace_only(self):
        assert GoogleFeedExtractor._parse_price_string("   ") == ("", "")


# ── Format Detection ─────────────────────────────────────────────────


class TestFormatDetection:
    """Tests for _is_xml format detection."""

    def test_xml_content_type(self):
        assert GoogleFeedExtractor._is_xml("", "application/xml; charset=utf-8") is True

    def test_csv_content_type(self):
        assert GoogleFeedExtractor._is_xml("", "text/csv") is False

    def test_tsv_content_type(self):
        assert GoogleFeedExtractor._is_xml("", "text/tab-separated-values") is False

    def test_body_starts_with_xml_decl(self):
        assert GoogleFeedExtractor._is_xml('<?xml version="1.0"?>', "") is True

    def test_body_starts_with_rss(self):
        assert GoogleFeedExtractor._is_xml("<rss version='2.0'>", "") is True

    def test_body_starts_with_csv_data(self):
        assert GoogleFeedExtractor._is_xml("id,title,price\n1,Test,9.99", "") is False


# ── Full Extract (Integration) ───────────────────────────────────────


class TestExtractIntegration:
    """Tests for the full extract() method with mocked HTTP."""

    @pytest.mark.asyncio
    async def test_extract_xml_success(self):
        xml_body = (FIXTURES / "google_feed.xml").read_text()
        mock_resp = MagicMock()
        mock_resp.text = xml_body
        mock_resp.content = xml_body.encode()
        mock_resp.headers = {"content-type": "application/xml"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        extractor = GoogleFeedExtractor()
        with patch("app.extractors.google_feed_extractor.httpx.AsyncClient", return_value=mock_client):
            result = await extractor.extract("https://test-store.com/feed.xml")

        assert result.complete is True
        assert result.error is None
        assert result.product_count == 4

    @pytest.mark.asyncio
    async def test_extract_csv_success(self):
        csv_body = (FIXTURES / "google_feed.csv").read_text()
        mock_resp = MagicMock()
        mock_resp.text = csv_body
        mock_resp.content = csv_body.encode()
        mock_resp.headers = {"content-type": "text/tab-separated-values"}
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        extractor = GoogleFeedExtractor()
        with patch("app.extractors.google_feed_extractor.httpx.AsyncClient", return_value=mock_client):
            result = await extractor.extract("https://test-store.com/feed.csv")

        assert result.complete is True
        assert result.product_count == 3

    @pytest.mark.asyncio
    async def test_extract_http_error_returns_failure(self):
        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        extractor = GoogleFeedExtractor()
        with patch("app.extractors.google_feed_extractor.httpx.AsyncClient", return_value=mock_client):
            result = await extractor.extract("https://test-store.com/feed.xml")

        assert result.complete is False
        assert result.error is not None
        assert result.product_count == 0

    @pytest.mark.asyncio
    async def test_extract_oversized_response_rejected(self):
        mock_resp = MagicMock()
        mock_resp.content = b"x" * (11 * 1024 * 1024)  # 11MB
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        extractor = GoogleFeedExtractor()
        with patch("app.extractors.google_feed_extractor.httpx.AsyncClient", return_value=mock_client):
            result = await extractor.extract("https://test-store.com/feed.xml")

        assert result.complete is False
        assert "size limit" in result.error.lower()
