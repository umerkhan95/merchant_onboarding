"""Merchant profile database operations — single-row upsert."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from app.db.queries import SELECT_ALL_MERCHANT_PROFILES, SELECT_MERCHANT_PROFILE, UPSERT_MERCHANT_PROFILE

if TYPE_CHECKING:
    from app.db.supabase_client import DatabaseClient
    from app.models.merchant_profile import MerchantProfile

logger = logging.getLogger(__name__)


class MerchantProfileIngestor:
    """Handles merchant profile upserts — one row per shop_id."""

    def __init__(self, db: DatabaseClient):
        self.db = db

    async def upsert(self, profile: MerchantProfile) -> bool:
        """Upsert a merchant profile into the database.

        Args:
            profile: MerchantProfile model to upsert

        Returns:
            True if the upsert succeeded

        Raises:
            RuntimeError: If database operation fails
        """
        try:
            # Serialize nested Pydantic models to JSON strings for JSONB columns
            contact_json = json.dumps(profile.contact.model_dump(mode="json"))
            social_json = json.dumps(profile.social_links.model_dump(mode="json"))
            analytics_json = json.dumps([t.model_dump(mode="json") for t in profile.analytics_tags])
            pages_json = json.dumps(profile.pages_crawled)

            # asyncpg expects native datetime objects for TIMESTAMPTZ columns
            scraped_at = profile.scraped_at

            async with self.db.pool.acquire() as conn:
                await conn.execute(
                    UPSERT_MERCHANT_PROFILE,
                    profile.shop_id,
                    profile.platform.value,
                    profile.shop_url,
                    profile.company_name,
                    profile.logo_url,
                    profile.description,
                    profile.about_text,
                    profile.founding_year,
                    profile.industry,
                    profile.language,
                    profile.currency,
                    contact_json,
                    social_json,
                    analytics_json,
                    profile.favicon_url,
                    pages_json,
                    float(profile.extraction_confidence),
                    scraped_at,
                )
                logger.info(
                    "Upserted merchant profile for %s (confidence: %.2f)",
                    profile.shop_id,
                    profile.extraction_confidence,
                )
                return True
        except Exception as e:
            logger.error("Failed to upsert merchant profile for %s: %s", profile.shop_id, e)
            raise RuntimeError(f"Failed to upsert merchant profile: {e}") from e

    async def list_all(self) -> list[dict]:
        """List all merchant profiles."""
        try:
            async with self.db.pool.acquire() as conn:
                rows = await conn.fetch(SELECT_ALL_MERCHANT_PROFILES)
                return [dict(r) for r in rows]
        except Exception as e:
            logger.error("Failed to list merchant profiles: %s", e)
            return []

    async def get(self, shop_id: str) -> dict | None:
        """Get a merchant profile by shop_id.

        Args:
            shop_id: The shop identifier

        Returns:
            Profile as dict or None if not found
        """
        try:
            async with self.db.pool.acquire() as conn:
                row = await conn.fetchrow(SELECT_MERCHANT_PROFILE, shop_id)
                if row:
                    return dict(row)
                return None
        except Exception as e:
            logger.error("Failed to get merchant profile for %s: %s", shop_id, e)
            return None
