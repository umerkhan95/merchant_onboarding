"""Idealo CSV feed exporter — generates RFC-4180 compliant CSV feeds.

Exports products from the unified Product model to idealo's CSV feed format.
Merchant-provided settings (delivery, shipping, payment) are merged at export time.

Reference: idealo CSV feed specification
- Encoding: UTF-8
- Separator: comma (,)
- Decimal: period (.)
- Multi-value separator: semicolon (;)
- Required fields: sku, brand, title, url, price, delivery, deliveryCosts, paymentCosts
"""

from __future__ import annotations

import csv
import io
import logging
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.models.product import Product

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

logger = logging.getLogger(__name__)

# idealo CSV column order
IDEALO_COLUMNS = [
    "sku",
    "brand",
    "title",
    "categoryPath",
    "url",
    "imageUrls",
    "eans",
    "hans",  # MPN / manufacturer article number
    "price",
    "deliveryCosts",
    "delivery",
    "paymentCosts",
    "description",
    "conditionType",
]


class IdealoCSVExporter:
    """Generates idealo-compatible CSV feed from Product models."""

    def __init__(
        self,
        delivery_time: str = "",
        delivery_costs: str = "",
        payment_costs: str = "",
        brand_fallback: str = "",
    ):
        """Initialize with merchant-provided settings.

        Args:
            delivery_time: e.g. "1-3 working days"
            delivery_costs: e.g. "4.95" or "DHL:4.95;DPD:5.95"
            payment_costs: e.g. "0.00" or "PayPal:0.35;Klarna:0.00"
            brand_fallback: fallback brand name when product has no vendor
        """
        self.delivery_time = delivery_time
        self.delivery_costs = delivery_costs
        self.payment_costs = payment_costs
        self.brand_fallback = brand_fallback

    def export(self, products: list[Product]) -> str:
        """Export products to idealo CSV feed string.

        Args:
            products: List of Product models to export

        Returns:
            UTF-8 encoded CSV string (comma-separated)
        """
        output = io.StringIO()
        writer = csv.DictWriter(
            output,
            fieldnames=IDEALO_COLUMNS,
            delimiter=",",
            quoting=csv.QUOTE_MINIMAL,
            extrasaction="ignore",
        )
        writer.writeheader()

        exported = 0
        skipped = 0
        for product in products:
            row = self._product_to_row(product)
            if row is None:
                skipped += 1
                continue
            writer.writerow(row)
            exported += 1

        logger.info("Idealo CSV export: %d exported, %d skipped", exported, skipped)
        return output.getvalue()

    @staticmethod
    def _strip_html(text: str) -> str:
        """Strip HTML tags and collapse whitespace for plain-text feed fields."""
        text = _HTML_TAG_RE.sub(" ", text)
        return _WHITESPACE_RE.sub(" ", text).strip()

    def _product_to_row(self, product: Product) -> dict[str, str] | None:
        """Convert a Product to an idealo CSV row dict.

        Returns None if the product lacks required fields (sku, title, price).
        """
        sku = product.sku or product.external_id
        if not sku or not product.title or not product.price:
            return None

        # Collect all image URLs (primary + additional)
        all_images = [product.image_url] if product.image_url else []
        all_images.extend(product.additional_images or [])

        return {
            "sku": sku,
            "brand": product.vendor or self.brand_fallback,
            "title": product.title,
            "categoryPath": " > ".join(product.category_path) if product.category_path else (product.product_type or ""),
            "url": product.product_url,
            "imageUrls": ";".join(all_images),
            "eans": product.gtin or "",
            "hans": product.mpn or "",
            "price": f"{product.price:.2f}",
            "deliveryCosts": self.delivery_costs,
            "delivery": self.delivery_time,
            "paymentCosts": self.payment_costs,
            "description": self._strip_html(product.description or ""),
            "conditionType": product.condition.upper() if product.condition else "",
        }
