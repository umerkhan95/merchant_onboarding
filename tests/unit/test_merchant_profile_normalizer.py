"""Unit tests for MerchantProfileNormalizer."""

from __future__ import annotations

import pytest

from app.models.enums import Platform
from app.models.merchant_profile import AnalyticsTag, MerchantProfile
from app.services.merchant_profile_normalizer import MerchantProfileNormalizer


@pytest.fixture
def normalizer():
    """Create MerchantProfileNormalizer instance."""
    return MerchantProfileNormalizer()


class TestMerchantProfileNormalizerBasics:
    """Tests for basic normalization functionality."""

    def test_normalize_full_profile(self, normalizer):
        """Normalize a complete raw data dict into MerchantProfile."""
        raw = {
            "jsonld_company_name": "Acme Corp",
            "og_site_name": "ACME",
            "title_tag": "Welcome to Acme",
            "jsonld_description": "Leading anvil manufacturer",
            "meta_description": "Quality products since 1950",
            "og_description": "Shop anvils online",
            "jsonld_logo": "https://example.com/logo.png",
            "favicon_url": "https://example.com/favicon.ico",
            "html_lang": "en",
            "currency": "USD",
            "founding_date": "1950",
            "industry": "Retail",
            "emails": ["sales@acme.com", "support@acme.com"],
            "phones": ["+1-555-0100"],
            "address_street": "123 Anvil Lane",
            "address_city": "Springfield",
            "address_region": "IL",
            "address_postal_code": "62701",
            "address_country": "US",
            "social_links": {
                "facebook": "https://facebook.com/acmecorp",
                "twitter": "https://twitter.com/acmecorp",
            },
            "analytics_tags": [
                {
                    "provider": "google_analytics_ga4",
                    "tag_id": "G-ABC123",
                    "tag_type": "GA4",
                },
            ],
            "about_text": "We have been manufacturing quality anvils for over 70 years.",
            "pages_crawled": ["https://example.com", "https://example.com/about"],
            "confidence": 0.85,
        }

        profile = normalizer.normalize(
            raw=raw,
            shop_id="acme-store",
            platform=Platform.SHOPIFY,
            shop_url="https://example.com",
        )

        assert profile is not None
        assert profile.company_name == "Acme Corp"
        assert profile.description == "Leading anvil manufacturer"
        assert profile.logo_url == "https://example.com/logo.png"
        assert profile.favicon_url == "https://example.com/favicon.ico"
        assert profile.language == "en"
        assert profile.currency == "USD"
        assert profile.founding_year == 1950
        assert profile.industry == "Retail"
        assert profile.about_text == "We have been manufacturing quality anvils for over 70 years."
        assert len(profile.contact.emails) == 2
        assert "sales@acme.com" in profile.contact.emails
        assert profile.contact.address_street == "123 Anvil Lane"
        assert profile.contact.address_city == "Springfield"
        assert profile.social_links.facebook == "https://facebook.com/acmecorp"
        assert profile.social_links.twitter == "https://twitter.com/acmecorp"
        assert len(profile.analytics_tags) == 1
        assert profile.analytics_tags[0].tag_id == "G-ABC123"
        assert profile.extraction_confidence == 0.85
        assert len(profile.pages_crawled) == 2

    def test_normalize_empty_raw_data(self, normalizer):
        """Return None for empty raw data dict."""
        result = normalizer.normalize(
            raw={},
            shop_id="empty-store",
            platform=Platform.WOOCOMMERCE,
            shop_url="https://example.com",
        )

        assert result is None

    def test_normalize_none_raw_data(self, normalizer):
        """Return None for None raw data."""
        result = normalizer.normalize(
            raw=None,
            shop_id="none-store",
            platform=Platform.MAGENTO,
            shop_url="https://example.com",
        )

        assert result is None


class TestMerchantProfileNormalizerPriorities:
    """Tests for field priority chains."""

    def test_normalize_company_name_priority(self, normalizer):
        """JSON-LD name wins over og:site_name wins over title."""
        # Test 1: JSON-LD has priority
        raw1 = {
            "jsonld_company_name": "JSON-LD Name",
            "og_site_name": "OG Name",
            "title_tag": "Title Name",
        }
        profile1 = normalizer.normalize(
            raw1, "shop1", Platform.SHOPIFY, "https://example.com"
        )
        assert profile1.company_name == "JSON-LD Name"

        # Test 2: OG wins when no JSON-LD
        raw2 = {
            "og_site_name": "OG Name",
            "title_tag": "Title Name",
        }
        profile2 = normalizer.normalize(
            raw2, "shop2", Platform.SHOPIFY, "https://example.com"
        )
        assert profile2.company_name == "OG Name"

        # Test 3: Title is fallback
        raw3 = {
            "title_tag": "Title Name",
        }
        profile3 = normalizer.normalize(
            raw3, "shop3", Platform.SHOPIFY, "https://example.com"
        )
        assert profile3.company_name == "Title Name"

    def test_normalize_logo_priority(self, normalizer):
        """JSON-LD logo wins over favicon."""
        # Test 1: JSON-LD dict with url key
        raw1 = {
            "jsonld_logo": {"url": "https://example.com/logo.png"},
            "favicon_url": "https://example.com/favicon.ico",
        }
        profile1 = normalizer.normalize(
            raw1, "shop1", Platform.SHOPIFY, "https://example.com"
        )
        assert profile1.logo_url == "https://example.com/logo.png"

        # Test 2: JSON-LD dict with contentUrl key
        raw2 = {
            "jsonld_logo": {"contentUrl": "https://example.com/logo-content.png"},
            "favicon_url": "https://example.com/favicon.ico",
        }
        profile2 = normalizer.normalize(
            raw2, "shop2", Platform.SHOPIFY, "https://example.com"
        )
        assert profile2.logo_url == "https://example.com/logo-content.png"

        # Test 3: JSON-LD as direct string
        raw3 = {
            "jsonld_logo": "https://example.com/logo-string.png",
            "favicon_url": "https://example.com/favicon.ico",
        }
        profile3 = normalizer.normalize(
            raw3, "shop3", Platform.SHOPIFY, "https://example.com"
        )
        assert profile3.logo_url == "https://example.com/logo-string.png"

        # Test 4: Logo list (take first item)
        raw4 = {
            "jsonld_logo": [
                {"url": "https://example.com/logo1.png"},
                {"url": "https://example.com/logo2.png"},
            ],
            "favicon_url": "https://example.com/favicon.ico",
        }
        profile4 = normalizer.normalize(
            raw4, "shop4", Platform.SHOPIFY, "https://example.com"
        )
        assert profile4.logo_url == "https://example.com/logo1.png"

        # Test 5: Favicon fallback
        raw5 = {
            "favicon_url": "https://example.com/favicon.ico",
        }
        profile5 = normalizer.normalize(
            raw5, "shop5", Platform.SHOPIFY, "https://example.com"
        )
        assert profile5.logo_url == "https://example.com/favicon.ico"


class TestMerchantProfileNormalizerSanitization:
    """Tests for HTML sanitization and truncation."""

    def test_normalize_description_sanitized(self, normalizer):
        """HTML in description is sanitized."""
        raw = {
            "jsonld_description": "Premium store <script>alert('xss')</script> selling quality items",
        }

        profile = normalizer.normalize(
            raw, "shop1", Platform.SHOPIFY, "https://example.com"
        )

        # Script tags should be removed
        assert profile.description is not None
        assert "<script>" not in profile.description
        assert "alert" not in profile.description
        assert "Premium store" in profile.description

    def test_normalize_description_truncated(self, normalizer):
        """Long description truncated to 2000 characters."""
        long_desc = "A" * 3000
        raw = {
            "jsonld_description": long_desc,
        }

        profile = normalizer.normalize(
            raw, "shop1", Platform.SHOPIFY, "https://example.com"
        )

        assert profile.description is not None
        assert len(profile.description) <= 2000

    def test_normalize_about_text_truncated(self, normalizer):
        """Long about text truncated to 5000 characters."""
        long_about = "B" * 6000
        raw = {
            "about_text": long_about,
        }

        profile = normalizer.normalize(
            raw, "shop1", Platform.SHOPIFY, "https://example.com"
        )

        assert profile.about_text is not None
        assert len(profile.about_text) <= 5000

    def test_normalize_about_text_sanitized(self, normalizer):
        """HTML in about text is sanitized."""
        raw = {
            "about_text": "About us <iframe src='bad.com'></iframe> since 2010",
        }

        profile = normalizer.normalize(
            raw, "shop1", Platform.SHOPIFY, "https://example.com"
        )

        assert profile.about_text is not None
        assert "<iframe>" not in profile.about_text
        assert "About us" in profile.about_text


class TestMerchantProfileNormalizerFoundingYear:
    """Tests for founding year parsing."""

    def test_normalize_founding_year_formats(self, normalizer):
        """Parse founding date in various formats."""
        # Test 1: Just year (YYYY)
        raw1 = {"founding_date": "2019"}
        profile1 = normalizer.normalize(
            raw1, "shop1", Platform.SHOPIFY, "https://example.com"
        )
        assert profile1.founding_year == 2019

        # Test 2: ISO date format (YYYY-MM-DD)
        raw2 = {"founding_date": "2019-03-15"}
        profile2 = normalizer.normalize(
            raw2, "shop2", Platform.SHOPIFY, "https://example.com"
        )
        assert profile2.founding_year == 2019

        # Test 3: Verbose format
        raw3 = {"founding_date": "Founded in 2019"}
        profile3 = normalizer.normalize(
            raw3, "shop3", Platform.SHOPIFY, "https://example.com"
        )
        assert profile3.founding_year == 2019

        # Test 4: Long format with day and month
        raw4 = {"founding_date": "March 15, 2019"}
        profile4 = normalizer.normalize(
            raw4, "shop4", Platform.SHOPIFY, "https://example.com"
        )
        assert profile4.founding_year == 2019

    def test_normalize_founding_year_invalid(self, normalizer):
        """Non-year strings return None."""
        raw = {
            "founding_date": "This is not a date",
        }

        profile = normalizer.normalize(
            raw, "shop1", Platform.SHOPIFY, "https://example.com"
        )

        assert profile.founding_year is None

    def test_normalize_founding_year_none(self, normalizer):
        """None founding_date returns None founding_year."""
        raw = {
            "founding_date": None,
        }

        profile = normalizer.normalize(
            raw, "shop1", Platform.SHOPIFY, "https://example.com"
        )

        assert profile.founding_year is None


class TestMerchantProfileNormalizerAnalytics:
    """Tests for analytics tag normalization."""

    def test_normalize_analytics_tags(self, normalizer):
        """Raw tag dicts converted to AnalyticsTag models."""
        raw = {
            "analytics_tags": [
                {
                    "provider": "google_analytics_ga4",
                    "tag_id": "G-ABC123",
                    "tag_type": "GA4",
                },
                {
                    "provider": "facebook_pixel",
                    "tag_id": "1234567890",
                    "tag_type": "Pixel",
                },
            ],
        }

        profile = normalizer.normalize(
            raw, "shop1", Platform.SHOPIFY, "https://example.com"
        )

        assert len(profile.analytics_tags) == 2
        assert all(isinstance(t, AnalyticsTag) for t in profile.analytics_tags)
        assert profile.analytics_tags[0].provider == "google_analytics_ga4"
        assert profile.analytics_tags[0].tag_id == "G-ABC123"
        assert profile.analytics_tags[1].provider == "facebook_pixel"

    def test_normalize_analytics_tags_invalid_skipped(self, normalizer):
        """Invalid analytics tags are skipped."""
        raw = {
            "analytics_tags": [
                {
                    "provider": "google_analytics_ga4",
                    "tag_id": "G-ABC123",
                    "tag_type": "GA4",
                },
                {
                    # Missing required provider field
                    "tag_id": "invalid",
                },
                {
                    "provider": "facebook_pixel",
                    "tag_id": "1234567890",
                    "tag_type": "Pixel",
                },
            ],
        }

        profile = normalizer.normalize(
            raw, "shop1", Platform.SHOPIFY, "https://example.com"
        )

        # Only valid tags are included
        assert len(profile.analytics_tags) == 2


class TestMerchantProfileNormalizerContactDedup:
    """Tests for contact info deduplication."""

    def test_normalize_contact_deduplication(self, normalizer):
        """Duplicate emails and phones are removed."""
        raw = {
            "emails": [
                "hello@example.com",
                "hello@example.com",
                "support@example.com",
            ],
            "phones": [
                "+1-555-0100",
                "(555) 010-0",
                "+1-555-0100",
            ],
        }

        profile = normalizer.normalize(
            raw, "shop1", Platform.SHOPIFY, "https://example.com"
        )

        assert len(profile.contact.emails) == 2
        assert "hello@example.com" in profile.contact.emails
        assert "support@example.com" in profile.contact.emails
        assert len(profile.contact.phones) == 2

    def test_normalize_social_links_filtering(self, normalizer):
        """Only known social platform keys are accepted."""
        raw = {
            "social_links": {
                "facebook": "https://facebook.com/mystore",
                "instagram": "https://instagram.com/mystore",
                "unknown_platform": "https://unknown.com/mystore",
                "twitter": "https://twitter.com/mystore",
            },
        }

        profile = normalizer.normalize(
            raw, "shop1", Platform.SHOPIFY, "https://example.com"
        )

        # Known platforms are included
        assert profile.social_links.facebook == "https://facebook.com/mystore"
        assert profile.social_links.instagram == "https://instagram.com/mystore"
        assert profile.social_links.twitter == "https://twitter.com/mystore"
        # Unknown platform is filtered out (not in model fields)
        assert not hasattr(profile.social_links, "unknown_platform")


class TestMerchantProfileNormalizerIdempotency:
    """Tests for idempotency key generation."""

    def test_normalize_idempotency_key(self, normalizer):
        """Same shop_id produces same idempotency_key."""
        raw = {"jsonld_company_name": "Store 1"}

        profile1 = normalizer.normalize(
            raw, "store-123", Platform.SHOPIFY, "https://example.com"
        )

        profile2 = normalizer.normalize(
            raw, "store-123", Platform.SHOPIFY, "https://different.com"
        )

        # Same shop_id -> same idempotency_key
        assert profile1.idempotency_key == profile2.idempotency_key

    def test_normalize_idempotency_key_different_shops(self, normalizer):
        """Different shop_ids produce different idempotency_keys."""
        raw = {"jsonld_company_name": "Store"}

        profile1 = normalizer.normalize(
            raw, "store-123", Platform.SHOPIFY, "https://example.com"
        )

        profile2 = normalizer.normalize(
            raw, "store-456", Platform.SHOPIFY, "https://example.com"
        )

        # Different shop_ids -> different idempotency_keys
        assert profile1.idempotency_key != profile2.idempotency_key

    def test_normalize_idempotency_key_is_sha256(self, normalizer):
        """Idempotency key is a SHA256 hash."""
        raw = {"jsonld_company_name": "Test Store"}

        profile = normalizer.normalize(
            raw, "test-shop", Platform.SHOPIFY, "https://example.com"
        )

        # SHA256 hashes are 64 hex characters
        assert len(profile.idempotency_key) == 64
        assert all(c in "0123456789abcdef" for c in profile.idempotency_key)


class TestMerchantProfileNormalizerEdgeCases:
    """Tests for edge cases and error handling."""

    def test_normalize_whitespace_trimming(self, normalizer):
        """Whitespace is trimmed from text fields."""
        raw = {
            "jsonld_company_name": "  Store Name  \n",
            "meta_description": "\t  Description with spaces  \t",
        }

        profile = normalizer.normalize(
            raw, "shop1", Platform.SHOPIFY, "https://example.com"
        )

        assert profile.company_name == "Store Name"
        assert profile.description == "Description with spaces"

    def test_normalize_missing_optional_fields(self, normalizer):
        """Profile is created even with only minimal data."""
        raw = {
            "title_tag": "Minimal Store",
        }

        profile = normalizer.normalize(
            raw, "minimal-shop", Platform.BIGCOMMERCE, "https://example.com"
        )

        assert profile is not None
        assert profile.company_name == "Minimal Store"
        assert profile.description is None
        assert profile.about_text is None
        assert profile.founding_year is None
        assert len(profile.contact.emails) == 0
        assert profile.social_links.facebook is None

    def test_normalize_all_platforms_supported(self, normalizer):
        """Normalization works for all platform types."""
        raw = {"title_tag": "Test Store"}

        for platform in Platform:
            profile = normalizer.normalize(
                raw, "shop1", platform, "https://example.com"
            )
            assert profile is not None
            assert profile.platform == platform

    def test_normalize_currency_truncation(self, normalizer):
        """Currency is truncated to 3 characters (ISO 4217)."""
        raw = {
            "title_tag": "Store",
            "currency": "TOOLONGCURRENCY",
        }

        profile = normalizer.normalize(
            raw, "shop1", Platform.SHOPIFY, "https://example.com"
        )

        assert len(profile.currency) == 3

    def test_normalize_html_lang_truncation(self, normalizer):
        """HTML language is truncated to 10 characters."""
        raw = {
            "title_tag": "Store",
            "html_lang": "en-US-x-twain-very-long",
        }

        profile = normalizer.normalize(
            raw, "shop1", Platform.SHOPIFY, "https://example.com"
        )

        assert len(profile.language) <= 10

    def test_normalize_preserves_raw_data(self, normalizer):
        """Original raw data is preserved in profile."""
        raw = {
            "jsonld_company_name": "Store",
            "custom_field": "custom_value",
        }

        profile = normalizer.normalize(
            raw, "shop1", Platform.SHOPIFY, "https://example.com"
        )

        # raw_data should contain original data
        assert profile.raw_data == raw
