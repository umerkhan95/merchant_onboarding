"""Product and variant Pydantic models."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from app.models.enums import Platform


class Variant(BaseModel):
    """Product variant model."""

    variant_id: str = Field(..., description="External variant ID from the platform")
    title: str = Field(..., description="Variant display title")
    price: Decimal = Field(..., description="Variant price", decimal_places=2)
    sku: str | None = Field(None, description="Stock keeping unit identifier")
    in_stock: bool = Field(..., description="Availability status")

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "variant_id": "12345",
                    "title": "Small / Red",
                    "price": "29.99",
                    "sku": "SHIRT-SM-RED",
                    "in_stock": True,
                }
            ]
        }
    }


class Product(BaseModel):
    """Unified product model across all platforms."""

    external_id: str = Field(..., description="External product ID from the platform")
    shop_id: str = Field(..., description="Merchant/shop identifier")
    platform: Platform = Field(..., description="Source platform")
    title: str = Field(..., description="Product title")
    description: str = Field(..., description="Product description (HTML or plain text)")
    price: Decimal = Field(..., description="Primary product price", decimal_places=2)
    compare_at_price: Decimal | None = Field(None, description="Original/compare-at price", decimal_places=2)
    currency: str = Field(..., max_length=3, description="ISO 4217 currency code")
    image_url: str = Field(..., description="Primary product image URL")
    product_url: str = Field(..., description="Canonical product page URL")
    sku: str | None = Field(None, description="Stock keeping unit identifier")
    gtin: str | None = Field(None, description="GTIN/EAN/UPC barcode identifier")
    mpn: str | None = Field(None, description="Manufacturer part number")
    vendor: str | None = Field(None, description="Product vendor/brand")
    product_type: str | None = Field(None, description="Product category/type")
    in_stock: bool = Field(..., description="Availability status")
    condition: str | None = Field(None, description="Product condition (NEW, REFURBISHED, USED)")
    variants: list[Variant] = Field(default_factory=list, description="Product variants")
    tags: list[str] = Field(default_factory=list, description="Product tags")
    additional_images: list[str] = Field(default_factory=list, description="Additional product image URLs")
    category_path: list[str] = Field(default_factory=list, description="Category breadcrumb hierarchy")
    raw_data: dict = Field(default_factory=dict, description="Original platform data for debugging")
    scraped_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Timestamp of data extraction"
    )
    idempotency_key: str = Field(default="", description="SHA256 hash for deduplication")

    @field_validator("currency")
    @classmethod
    def validate_currency_uppercase(cls, v: str) -> str:
        """Ensure currency code is uppercase."""
        return v.upper()

    @model_validator(mode="after")
    def compute_idempotency_key(self) -> Product:
        """Compute stable idempotency key from key product fields.

        Format: SHA256 of "{external_id}|{platform}|{shop_id}|{sku}"
        Falls back to including title when both external_id and sku are empty.
        """
        key_components = [
            self.external_id or "",
            self.platform.value if self.platform else "",
            self.shop_id or "",
            self.sku or "",
        ]
        if not self.external_id and not self.sku:
            key_components.append(self.title or "")
        key_string = "|".join(key_components)
        self.idempotency_key = hashlib.sha256(key_string.encode("utf-8")).hexdigest()
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "external_id": "7891234567890",
                    "shop_id": "mystore",
                    "platform": "shopify",
                    "title": "Premium Cotton T-Shirt",
                    "description": "High-quality cotton t-shirt",
                    "price": "29.99",
                    "compare_at_price": "39.99",
                    "currency": "USD",
                    "image_url": "https://example.com/images/shirt.jpg",
                    "product_url": "https://example.com/products/premium-shirt",
                    "sku": "SHIRT-001",
                    "vendor": "Brand Co",
                    "product_type": "Apparel",
                    "in_stock": True,
                    "variants": [],
                    "tags": ["cotton", "premium", "bestseller"],
                    "raw_data": {},
                    "scraped_at": "2026-02-14T12:00:00Z",
                }
            ]
        }
    }
