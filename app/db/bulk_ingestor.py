"""Bulk product ingestion using staging table pattern."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from app.db.queries import (
    COUNT_INVALID_PRODUCTS,
    CREATE_STAGING_TABLE,
    DELETE_INVALID_PRODUCTS,
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

    async def _ingest_batch(self, products: list[Product]) -> int:
        """Ingest a single batch of products.

        Args:
            products: Batch of products to ingest

        Returns:
            int: Number of products affected in this batch

        Raises:
            RuntimeError: If database operation fails
        """
        async with self.db.pool.acquire() as conn, conn.transaction():
            try:
                # Create staging table
                await conn.execute(CREATE_STAGING_TABLE)

                # Prepare batch data
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
                        p.vendor,
                        p.product_type,
                        p.in_stock,
                        json.dumps([v.model_dump(mode="json") for v in p.variants]),
                        json.dumps(p.tags),
                        json.dumps(p.raw_data),
                        p.scraped_at,
                        p.idempotency_key,
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
                        "product_url", "sku", "vendor", "product_type", "in_stock",
                        "variants", "tags", "raw_data", "scraped_at", "idempotency_key",
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
