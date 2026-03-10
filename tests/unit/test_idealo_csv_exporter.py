"""Tests for IdealoCSVExporter."""

import csv
import io
from decimal import Decimal

from app.exporters.idealo_csv import IDEALO_COLUMNS, IdealoCSVExporter
from app.models.enums import Platform
from app.models.product import Product


def _make_product(**overrides) -> Product:
    """Create a minimal Product for testing."""
    defaults = {
        "external_id": "12345",
        "shop_id": "https://example.com",
        "platform": Platform.SHOPIFY,
        "title": "Test Product",
        "description": "A test product",
        "price": Decimal("29.99"),
        "currency": "EUR",
        "image_url": "https://example.com/img.jpg",
        "product_url": "https://example.com/products/test",
        "sku": "SKU-001",
        "in_stock": True,
    }
    defaults.update(overrides)
    return Product(**defaults)


def _parse_csv(csv_str: str) -> list[list[str]]:
    """Parse CSV output into rows."""
    reader = csv.reader(io.StringIO(csv_str))
    return list(reader)


class TestIdealoCSVExporter:
    def test_export_basic_product(self):
        exporter = IdealoCSVExporter(
            delivery_time="1-3 working days",
            delivery_costs="4.95",
            payment_costs="0.00",
        )
        product = _make_product()
        rows = _parse_csv(exporter.export([product]))

        assert len(rows) == 2  # header + 1 row
        assert rows[0] == IDEALO_COLUMNS

        row = rows[1]
        assert row[0] == "SKU-001"  # sku
        assert row[2] == "Test Product"  # title
        assert row[8] == "29.99"  # price
        assert row[10] == "1-3 working days"  # delivery

    def test_export_with_gtin_and_mpn(self):
        exporter = IdealoCSVExporter()
        product = _make_product(gtin="4006381333931", mpn="MPN-123")
        rows = _parse_csv(exporter.export([product]))

        assert rows[1][6] == "4006381333931"  # eans
        assert rows[1][7] == "MPN-123"  # hans

    def test_export_with_additional_images(self):
        exporter = IdealoCSVExporter()
        product = _make_product(
            additional_images=["https://example.com/img2.jpg", "https://example.com/img3.jpg"]
        )
        rows = _parse_csv(exporter.export([product]))

        images = rows[1][5]  # imageUrls
        assert "https://example.com/img.jpg" in images
        assert "https://example.com/img2.jpg" in images
        assert ";" in images  # semicolon separator

    def test_export_with_category_path(self):
        exporter = IdealoCSVExporter()
        product = _make_product(category_path=["Electronics", "Phones", "Smartphones"])
        rows = _parse_csv(exporter.export([product]))

        assert rows[1][3] == "Electronics > Phones > Smartphones"

    def test_export_with_condition(self):
        exporter = IdealoCSVExporter()
        product = _make_product(condition="REFURBISHED")
        rows = _parse_csv(exporter.export([product]))

        assert rows[1][13] == "REFURBISHED"  # conditionType

    def test_export_leaves_condition_empty_when_unknown(self):
        exporter = IdealoCSVExporter()
        product = _make_product()  # no condition set
        rows = _parse_csv(exporter.export([product]))

        assert rows[1][13] == ""  # conditionType empty when not known

    def test_export_skips_product_without_sku_or_external_id(self):
        exporter = IdealoCSVExporter()
        product = _make_product(sku=None, external_id="")
        rows = _parse_csv(exporter.export([product]))

        assert len(rows) == 1  # header only

    def test_export_uses_external_id_when_sku_missing(self):
        exporter = IdealoCSVExporter()
        product = _make_product(sku=None, external_id="EXT-999")
        rows = _parse_csv(exporter.export([product]))

        assert rows[1][0] == "EXT-999"

    def test_export_multiple_products(self):
        exporter = IdealoCSVExporter(delivery_time="2-5 days")
        products = [
            _make_product(sku=f"SKU-{i}", title=f"Product {i}")
            for i in range(5)
        ]
        rows = _parse_csv(exporter.export(products))

        assert len(rows) == 6  # header + 5 rows

    def test_export_with_vendor_as_brand(self):
        exporter = IdealoCSVExporter()
        product = _make_product(vendor="Nike")
        rows = _parse_csv(exporter.export([product]))

        assert rows[1][1] == "Nike"  # brand

    def test_export_empty_list(self):
        exporter = IdealoCSVExporter()
        rows = _parse_csv(exporter.export([]))

        assert len(rows) == 1  # header only

    def test_csv_uses_comma_separator(self):
        """Verify idealo spec: comma-separated, not tab."""
        exporter = IdealoCSVExporter()
        product = _make_product()
        output = exporter.export([product])

        # Header line should contain commas, not tabs
        header_line = output.splitlines()[0]
        assert "," in header_line
        assert "\t" not in header_line

    def test_export_strips_html_from_description(self):
        exporter = IdealoCSVExporter()
        product = _make_product(description="<h4>Bold</h4>\n<p>A <em>great</em> product.</p>")
        rows = _parse_csv(exporter.export([product]))

        desc = rows[1][12]  # description column
        assert "<" not in desc
        assert "Bold" in desc
        assert "great" in desc

    def test_export_brand_fallback_when_no_vendor(self):
        exporter = IdealoCSVExporter(brand_fallback="Shop Brand")
        product = _make_product(vendor=None)
        rows = _parse_csv(exporter.export([product]))

        assert rows[1][1] == "Shop Brand"  # brand uses fallback

    def test_export_vendor_takes_precedence_over_fallback(self):
        exporter = IdealoCSVExporter(brand_fallback="Shop Brand")
        product = _make_product(vendor="Nike")
        rows = _parse_csv(exporter.export([product]))

        assert rows[1][1] == "Nike"  # vendor wins over fallback
