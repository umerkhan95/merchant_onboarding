"""Tests for MerchantProfileIngestor."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.db.merchant_profile_ingestor import MerchantProfileIngestor
from app.models.enums import Platform
from app.models.merchant_profile import (
    AnalyticsTag,
    ContactInfo,
    MerchantProfile,
    SocialLinks,
)


def _make_profile(**overrides) -> MerchantProfile:
    """Create a test MerchantProfile with sensible defaults."""
    defaults = {
        "shop_id": "https://example.com",
        "platform": Platform.SHOPIFY,
        "shop_url": "https://example.com",
        "company_name": "Test Store",
        "logo_url": "https://example.com/logo.png",
        "description": "A test store",
        "extraction_confidence": 0.85,
        "contact": ContactInfo(emails=["test@example.com"], phones=["+1-555-1234"]),
        "social_links": SocialLinks(facebook="https://facebook.com/test"),
        "analytics_tags": [
            AnalyticsTag(provider="google_analytics_ga4", tag_id="G-TEST123", tag_type="GA4")
        ],
        "pages_crawled": ["https://example.com", "https://example.com/about"],
    }
    defaults.update(overrides)
    return MerchantProfile(**defaults)


class TestUpsert:
    """Tests for MerchantProfileIngestor.upsert()."""

    @pytest.mark.asyncio
    async def test_upsert_success(self):
        """Test successful profile upsert."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = MagicMock()
        mock_db.pool = mock_pool

        ingestor = MerchantProfileIngestor(mock_db)
        profile = _make_profile()

        result = await ingestor.upsert(profile)

        assert result is True
        mock_conn.execute.assert_called_once()

    @pytest.mark.asyncio
    async def test_upsert_passes_correct_parameters(self):
        """Test that upsert passes all 18 parameters correctly."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = MagicMock()
        mock_db.pool = mock_pool

        ingestor = MerchantProfileIngestor(mock_db)
        profile = _make_profile(
            company_name="My Store",
            founding_year=2020,
            industry="RetailStore",
            language="en",
            currency="USD",
        )

        await ingestor.upsert(profile)

        call_args = mock_conn.execute.call_args
        args = call_args[0]

        # First arg is SQL, rest are parameters
        assert args[1] == "https://example.com"  # shop_id
        assert args[2] == "shopify"  # platform.value
        assert args[3] == "https://example.com"  # shop_url
        assert args[4] == "My Store"  # company_name
        assert args[8] == 2020  # founding_year
        assert args[9] == "RetailStore"  # industry
        assert args[10] == "en"  # language
        assert args[11] == "USD"  # currency

        # JSONB fields should be JSON strings
        contact_json = json.loads(args[12])
        assert "test@example.com" in contact_json["emails"]

        social_json = json.loads(args[13])
        assert social_json["facebook"] == "https://facebook.com/test"

        analytics_json = json.loads(args[14])
        assert analytics_json[0]["tag_id"] == "G-TEST123"

        # confidence should be float
        assert isinstance(args[17], float)
        assert args[17] == 0.85

    @pytest.mark.asyncio
    async def test_upsert_db_error_raises_runtime_error(self):
        """Test that DB errors are wrapped in RuntimeError."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("Connection refused"))

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = MagicMock()
        mock_db.pool = mock_pool

        ingestor = MerchantProfileIngestor(mock_db)
        profile = _make_profile()

        with pytest.raises(RuntimeError, match="Failed to upsert"):
            await ingestor.upsert(profile)

    @pytest.mark.asyncio
    async def test_upsert_empty_optional_fields(self):
        """Test upsert with minimal profile (all optional fields None)."""
        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = MagicMock()
        mock_db.pool = mock_pool

        ingestor = MerchantProfileIngestor(mock_db)
        profile = _make_profile(
            company_name=None,
            logo_url=None,
            description=None,
            about_text=None,
            founding_year=None,
            industry=None,
            language=None,
            currency=None,
            favicon_url=None,
            contact=ContactInfo(),
            social_links=SocialLinks(),
            analytics_tags=[],
        )

        result = await ingestor.upsert(profile)
        assert result is True


class TestGet:
    """Tests for MerchantProfileIngestor.get()."""

    @pytest.mark.asyncio
    async def test_get_existing_profile(self):
        """Test getting an existing profile."""
        mock_row = {
            "shop_id": "https://example.com",
            "company_name": "Test Store",
            "contact": '{"emails": ["test@example.com"]}',
        }

        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=mock_row)

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = MagicMock()
        mock_db.pool = mock_pool

        ingestor = MerchantProfileIngestor(mock_db)
        result = await ingestor.get("https://example.com")

        assert result is not None
        assert result["shop_id"] == "https://example.com"
        assert result["company_name"] == "Test Store"

    @pytest.mark.asyncio
    async def test_get_nonexistent_profile(self):
        """Test getting a profile that doesn't exist."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(return_value=None)

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = MagicMock()
        mock_db.pool = mock_pool

        ingestor = MerchantProfileIngestor(mock_db)
        result = await ingestor.get("nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_db_error_returns_none(self):
        """Test that DB errors return None instead of raising."""
        mock_conn = AsyncMock()
        mock_conn.fetchrow = AsyncMock(side_effect=Exception("Connection lost"))

        mock_pool = MagicMock()
        mock_pool.acquire.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
        mock_pool.acquire.return_value.__aexit__ = AsyncMock(return_value=False)

        mock_db = MagicMock()
        mock_db.pool = mock_pool

        ingestor = MerchantProfileIngestor(mock_db)
        result = await ingestor.get("https://example.com")

        assert result is None
