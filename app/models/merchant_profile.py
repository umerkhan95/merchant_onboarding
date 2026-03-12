"""MerchantProfile and related Pydantic models."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from pydantic import BaseModel, Field, model_validator

from app.models.enums import Platform


class SocialLinks(BaseModel):
    """Social media presence."""

    facebook: str | None = Field(None, description="Facebook profile URL or handle")
    instagram: str | None = Field(None, description="Instagram profile URL or handle")
    twitter: str | None = Field(None, description="Twitter/X profile URL or handle")
    linkedin: str | None = Field(None, description="LinkedIn profile URL or handle")
    tiktok: str | None = Field(None, description="TikTok profile URL or handle")
    youtube: str | None = Field(None, description="YouTube channel URL or handle")
    pinterest: str | None = Field(None, description="Pinterest profile URL or handle")


class AnalyticsTag(BaseModel):
    """Single analytics/tracking tag."""

    provider: str = Field(..., description="Analytics provider (e.g. google_analytics, facebook_pixel)")
    tag_id: str | None = Field(None, description="Tracking ID if extractable (e.g. UA-12345, G-12345)")
    tag_type: str | None = Field(None, description="Tag type (e.g. UA, GA4, GTM, PIXEL)")


class ContactInfo(BaseModel):
    """Contact information."""

    emails: list[str] = Field(default_factory=list, description="List of contact email addresses")
    phones: list[str] = Field(default_factory=list, description="List of contact phone numbers")
    address_street: str | None = Field(None, description="Street address")
    address_city: str | None = Field(None, description="City")
    address_region: str | None = Field(None, description="State/region/province")
    address_postal_code: str | None = Field(None, description="Postal/ZIP code")
    address_country: str | None = Field(None, description="Country")


class MerchantProfile(BaseModel):
    """Unified merchant profile across all platforms."""

    shop_id: str = Field(..., description="Merchant/shop identifier (same as products table)")
    platform: Platform = Field(..., description="Source e-commerce platform")
    shop_url: str = Field(..., description="Canonical shop URL")
    company_name: str | None = Field(None, description="Official company/merchant name")
    logo_url: str | None = Field(None, description="Logo image URL")
    description: str | None = Field(None, description="Meta description or tagline")
    about_text: str | None = Field(None, description="Truncated about page text")
    founding_year: int | None = Field(None, description="Year company was founded")
    industry: str | None = Field(None, description="Industry classification (from JSON-LD @type)")
    language: str | None = Field(None, description="Primary language (from html lang attribute)")
    currency: str | None = Field(None, max_length=3, description="ISO 4217 currency code")
    contact: ContactInfo = Field(default_factory=ContactInfo, description="Contact information")
    social_links: SocialLinks = Field(default_factory=SocialLinks, description="Social media links")
    analytics_tags: list[AnalyticsTag] = Field(default_factory=list, description="Tracking/analytics tags")
    favicon_url: str | None = Field(None, description="Favicon URL")
    pages_crawled: list[str] = Field(default_factory=list, description="List of pages crawled during extraction")
    extraction_confidence: float = Field(
        0.0, ge=0.0, le=1.0, description="Confidence score for profile extraction (0.0-1.0)"
    )
    raw_data: dict = Field(default_factory=dict, description="Original raw extraction data for debugging")
    scraped_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC), description="Timestamp of data extraction"
    )
    idempotency_key: str = Field(default="", description="SHA256 hash for deduplication")

    @model_validator(mode="after")
    def compute_idempotency_key(self) -> MerchantProfile:
        """Compute stable idempotency key from shop_id.

        Format: SHA256 of "{shop_id}"
        """
        key_string = self.shop_id
        self.idempotency_key = hashlib.sha256(key_string.encode("utf-8")).hexdigest()
        return self

    model_config = {
        "json_schema_extra": {
            "examples": [
                {
                    "shop_id": "mystore",
                    "platform": "shopify",
                    "shop_url": "https://example-store.myshopify.com",
                    "company_name": "Example Store Inc.",
                    "logo_url": "https://example.com/logo.png",
                    "description": "Premium online retailer of handcrafted goods",
                    "about_text": "Founded in 2015, Example Store specializes in artisanal products...",
                    "founding_year": 2015,
                    "industry": "RetailStore",
                    "language": "en",
                    "currency": "USD",
                    "contact": {
                        "emails": ["hello@example.com"],
                        "phones": ["+1-555-123-4567"],
                        "address_street": "123 Main St",
                        "address_city": "Portland",
                        "address_region": "OR",
                        "address_postal_code": "97201",
                        "address_country": "US",
                    },
                    "social_links": {
                        "facebook": "https://facebook.com/examplestore",
                        "instagram": "https://instagram.com/examplestore",
                        "twitter": "https://twitter.com/examplestore",
                        "linkedin": None,
                        "tiktok": None,
                        "youtube": None,
                        "pinterest": None,
                    },
                    "analytics_tags": [
                        {"provider": "google_analytics", "tag_id": "G-12345", "tag_type": "GA4"},
                        {"provider": "facebook_pixel", "tag_id": "123456789", "tag_type": "PIXEL"},
                    ],
                    "favicon_url": "https://example.com/favicon.ico",
                    "pages_crawled": [
                        "https://example.com",
                        "https://example.com/about",
                        "https://example.com/contact",
                    ],
                    "extraction_confidence": 0.92,
                    "raw_data": {},
                    "scraped_at": "2026-02-27T12:00:00Z",
                }
            ]
        }
    }
