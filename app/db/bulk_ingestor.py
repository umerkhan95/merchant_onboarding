"""Bulk product ingestion using staging table pattern."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from app.config import settings
from app.db.queries import (
    ALTER_PRODUCTS_ADD_RETENTION,
    ALTER_PROFILES_ADD_RETENTION,
    COUNT_INVALID_PRODUCTS,
    CREATE_STAGING_TABLE,
    DELETE_EXPIRED_PRODUCTS,
    DELETE_EXPIRED_PROFILES,
    DELETE_INVALID_PRODUCTS,
    DELETE_MERCHANT_PROFILE,
    DELETE_PRODUCTS_BY_SHOP,
    SET_DEFAULT_RETENTION_PRODUCTS,
    SET_DEFAULT_RETENTION_PROFILES,
    UPSERT_FROM_STAGING,
)

if TYPE_CHECKING:
    from app.db.supabase_client import DatabaseClient
    from app.models.product import Product

logger = logging.getLogger(__name__)


class BulkIngestor:
    """Handles bulk product upserts using staging table pattern."""

    BATCH_SIZE = 500

    def __init__(self, db: DatabaseClient):
        """Initialize bulk ingestor.

        Args:
            db: DatabaseClient instance with active connection pool
        """
        self.db = db

    async def ingest(self, products: list[Product]) -> int:
        """Bulk upsert products using staging table pattern.

        Strategy:
        1. Create temporary staging table
        2. Batch insert products into staging
        3. Upsert from staging to products table
        4. Return number of affected rows

        Args:
            products: List of Product models to ingest

        Returns:
            int: Number of products inserted or updated

        Raises:
            RuntimeError: If database operation fails
        """
        if not products:
            logger.info("No products to ingest")
            return 0

        total_affected = 0

        # Process in batches to avoid memory issues
        for i in range(0, len(products), self.BATCH_SIZE):
            batch = products[i : i + self.BATCH_SIZE]
            affected = await self._ingest_batch(batch)
            total_affected += affected
            logger.info(f"Ingested batch {i // self.BATCH_SIZE + 1}: {affected} products affected")

        logger.info(f"Bulk ingest complete. Total products affected: {total_affected}")
        return total_affected

    @staticmethod
    def _deduplicate_by_key(products: list[Product]) -> list[Product]:
        """Remove products with duplicate idempotency keys within a batch.

        PostgreSQL ON CONFLICT DO UPDATE cannot handle two rows with the same
        constrained value in a single command. Keeps the last occurrence (most
        recently processed) when duplicates exist.
        """
        seen: dict[str, Product] = {}
        for p in products:
            seen[p.idempotency_key] = p
        deduped = list(seen.values())
        if len(deduped) < len(products):
            logger.info(
                "Deduplicated %d → %d products by idempotency_key before insert",
                len(products), len(deduped),
            )
        return deduped

    async def _ingest_batch(self, products: list[Product]) -> int:
        """Ingest a single batch of products.

        Args:
            products: Batch of products to ingest

        Returns:
            int: Number of products affected in this batch

        Raises:
            RuntimeError: If database operation fails
        """
        products = self._deduplicate_by_key(products)
        if not products:
            return 0

        async with self.db.pool.acquire() as conn, conn.transaction():
            try:
                # Create staging table
                await conn.execute(CREATE_STAGING_TABLE)

                # Prepare batch data
                retention_expires = datetime.now(timezone.utc) + timedelta(
                    days=settings.data_retention_days,
                )
                staging_data = [
                    (
                        p.external_id,
                        p.shop_id,
                        p.platform.value,
                        p.title,
                        p.description,
                        p.price,
                        p.compare_at_price,
                        p.currency,
                        p.image_url,
                        p.product_url,
                        p.sku,
                        p.gtin,
                        p.mpn,
                        p.vendor,
                        p.product_type,
                        p.in_stock,
                        p.condition,
                        json.dumps([v.model_dump(mode="json") for v in p.variants]),
                        json.dumps(p.tags),
                        json.dumps(p.additional_images),
                        json.dumps(p.category_path),
                        json.dumps(p.raw_data),
                        p.scraped_at,
                        p.idempotency_key,
                        retention_expires,
                    )
                    for p in products
                ]

                # COPY records into staging table (~50-100K rows/sec vs ~1-5K for executemany)
                await conn.copy_records_to_table(
                    "staging_products",
                    records=staging_data,
                    columns=[
                        "external_id", "shop_id", "platform", "title", "description",
                        "price", "compare_at_price", "currency", "image_url",
                        "product_url", "sku", "gtin", "mpn", "vendor", "product_type",
                        "in_stock", "condition", "variants", "tags", "additional_images",
                        "category_path", "raw_data", "scraped_at", "idempotency_key",
                        "retention_expires_at",
                    ],
                )

                # Upsert from staging to products table
                result = await conn.execute(UPSERT_FROM_STAGING)

                # Parse affected rows from result string (e.g., "INSERT 0 42")
                affected_count = int(result.split()[-1]) if result else 0

                return affected_count

            except Exception as e:
                logger.error(f"Bulk ingest batch failed: {e}")
                raise RuntimeError(f"Failed to ingest product batch: {e}") from e

    async def count_invalid_products(self) -> int:
        """Count products that would be removed by cleanup_invalid_products.

        Invalid products have price=0 AND no image AND no SKU AND no external_id.
        """
        async with self.db.pool.acquire() as conn:
            return await conn.fetchval(COUNT_INVALID_PRODUCTS)

    async def delete_merchant_data(self, shop_id: str) -> dict[str, int]:
        """Delete all data for a merchant (GDPR right to erasure).

        Args:
            shop_id: The merchant's shop identifier

        Returns:
            Dict with counts of deleted records per table
        """
        async with self.db.pool.acquire() as conn:
            # Delete products
            result = await conn.execute(DELETE_PRODUCTS_BY_SHOP, shop_id)
            deleted_products = int(result.split()[-1]) if result else 0

            # Delete merchant profile
            result = await conn.execute(DELETE_MERCHANT_PROFILE, shop_id)
            deleted_profiles = int(result.split()[-1]) if result else 0

            logger.info(
                "GDPR erasure for %s: %d products, %d profiles deleted",
                shop_id, deleted_products, deleted_profiles,
            )

            return {
                "products_deleted": deleted_products,
                "profiles_deleted": deleted_profiles,
            }

    async def cleanup_invalid_products(self) -> int:
        """Remove invalid products from the database.

        Deletes products where price=0 AND image_url is empty AND sku is empty
        AND external_id is empty. Legitimate free items with images or SKUs
        are preserved.

        Returns:
            Number of deleted rows.
        """
        async with self.db.pool.acquire() as conn:
            result = await conn.execute(DELETE_INVALID_PRODUCTS)
            deleted = int(result.split()[-1]) if result else 0
            logger.info("Cleaned up %d invalid products from database", deleted)
            return deleted

    async def cleanup_expired_data(self) -> dict[str, int]:
        """Delete records past their retention date (GDPR storage limitation).

        Returns:
            Dict with counts of deleted records per table
        """
        async with self.db.pool.acquire() as conn:
            result_products = await conn.execute(DELETE_EXPIRED_PRODUCTS)
            deleted_products = int(result_products.split()[-1]) if result_products else 0

            result_profiles = await conn.execute(DELETE_EXPIRED_PROFILES)
            deleted_profiles = int(result_profiles.split()[-1]) if result_profiles else 0

            logger.info(
                "Retention cleanup: %d expired products, %d expired profiles deleted",
                deleted_products, deleted_profiles,
            )

            return {
                "products_deleted": deleted_products,
                "profiles_deleted": deleted_profiles,
            }

    async def apply_retention_migration(self, retention_days: int) -> None:
        """Add retention columns and set defaults for existing records.

        Args:
            retention_days: Number of days from creation to retain data
        """
        async with self.db.pool.acquire() as conn:
            await conn.execute(ALTER_PRODUCTS_ADD_RETENTION)
            await conn.execute(ALTER_PROFILES_ADD_RETENTION)
            await conn.execute(SET_DEFAULT_RETENTION_PRODUCTS, str(retention_days))
            await conn.execute(SET_DEFAULT_RETENTION_PROFILES, str(retention_days))
            logger.info("Applied retention policy: %d days for existing records", retention_days)
