"""Merchant profile normalizer — maps raw extracted data to MerchantProfile model."""

from __future__ import annotations

import logging
import re

from app.models.enums import Platform
from app.models.merchant_profile import (
    AnalyticsTag,
    ContactInfo,
    MerchantProfile,
    SocialLinks,
)
from app.security.html_sanitizer import HTMLSanitizer

logger = logging.getLogger(__name__)

_MAX_DESCRIPTION_LENGTH = 2000
_MAX_ABOUT_TEXT_LENGTH = 5000


class MerchantProfileNormalizer:
    """Maps raw extracted data from MerchantProfileExtractor to MerchantProfile model.

    Resolves field conflicts using priority chains:
    - Company name: JSON-LD > og:site_name > <title>
    - Logo: JSON-LD logo > favicon
    - Description: JSON-LD > meta description > og:description
    """

    def normalize(
        self,
        raw: dict,
        shop_id: str,
        platform: Platform,
        shop_url: str,
    ) -> MerchantProfile | None:
        """Normalize raw profile data into MerchantProfile model.

        Args:
            raw: Raw data dict from MerchantProfileExtractor
            shop_id: Merchant/shop identifier (same as products table)
            platform: Detected platform enum
            shop_url: Canonical shop URL

        Returns:
            MerchantProfile instance or None if extraction produced nothing useful
        """
        if not raw:
            return None

        # Company name priority chain
        company_name = (
            raw.get("jsonld_company_name")
            or raw.get("og_site_name")
            or raw.get("title_tag")
        )
        if company_name:
            company_name = company_name.strip()

        # Logo priority chain
        logo = raw.get("jsonld_logo")
        if isinstance(logo, dict):
            logo = logo.get("url") or logo.get("contentUrl")
        if isinstance(logo, list):
            logo = logo[0] if logo else None
            if isinstance(logo, dict):
                logo = logo.get("url") or logo.get("contentUrl")
        logo = logo or raw.get("favicon_url")

        # Description priority chain
        description = (
            raw.get("jsonld_description")
            or raw.get("meta_description")
            or raw.get("og_description")
        )
        if description:
            description = HTMLSanitizer.sanitize(description.strip())[:_MAX_DESCRIPTION_LENGTH]

        # About text
        about_text = raw.get("about_text")
        if about_text:
            about_text = HTMLSanitizer.sanitize(about_text.strip())[:_MAX_ABOUT_TEXT_LENGTH]

        # Founding year
        founding_year = self._parse_founding_year(raw.get("founding_date"))

        # Contact info
        contact = ContactInfo(
            emails=self._dedupe_list(raw.get("emails", [])),
            phones=self._dedupe_list(raw.get("phones", [])),
            address_street=raw.get("address_street"),
            address_city=raw.get("address_city"),
            address_region=raw.get("address_region"),
            address_postal_code=raw.get("address_postal_code"),
            address_country=self._normalize_country(raw.get("address_country")),
        )

        # Social links
        social_raw = raw.get("social_links", {})
        social_links = SocialLinks(**{
            k: v for k, v in social_raw.items()
            if k in SocialLinks.model_fields and isinstance(v, str)
        })

        # Analytics tags
        analytics_tags = []
        for tag_raw in raw.get("analytics_tags", []):
            try:
                analytics_tags.append(AnalyticsTag(**tag_raw))
            except Exception as e:
                logger.debug("Failed to create AnalyticsTag: %s", e)

        # Enforce field-length constraints before model construction to avoid
        # Pydantic ValidationError when raw data contains oversized values.
        raw_currency = raw.get("currency")
        currency = raw_currency[:3] if raw_currency else None

        raw_language = raw.get("html_lang")
        language = raw_language[:10] if raw_language else None

        try:
            profile = MerchantProfile(
                shop_id=shop_id,
                platform=platform,
                shop_url=shop_url,
                company_name=company_name,
                logo_url=logo if isinstance(logo, str) else None,
                description=description,
                about_text=about_text,
                founding_year=founding_year,
                industry=raw.get("industry"),
                language=language,
                currency=currency,
                contact=contact,
                social_links=social_links,
                analytics_tags=analytics_tags,
                favicon_url=raw.get("favicon_url"),
                pages_crawled=raw.get("pages_crawled", []),
                extraction_confidence=raw.get("confidence", 0.0),
                raw_data=raw,
            )
            return profile
        except Exception as e:
            logger.exception("Failed to create MerchantProfile: %s", e)
            return None

    @staticmethod
    def _parse_founding_year(value) -> int | None:
        """Extract a 4-digit year from various date formats."""
        if value is None:
            return None
        value_str = str(value).strip()
        match = re.search(r"\b(19|20)\d{2}\b", value_str)
        if match:
            return int(match.group(0))
        return None

    @staticmethod
    def _normalize_country(value) -> str | None:
        """Normalize country value — could be ISO code, full name, or dict."""
        if not value:
            return None
        if isinstance(value, dict):
            return (value.get("name") or value.get("@value") or "")[:100] or None
        return str(value).strip()[:100] or None

    @staticmethod
    def _dedupe_list(items: list) -> list:
        """Remove duplicates while preserving order."""
        seen = set()
        result = []
        for item in items:
            if item and item not in seen:
                seen.add(item)
                result.append(item)
        return result
