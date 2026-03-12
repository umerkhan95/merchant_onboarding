"""Unit tests for GDPR data retention cleanup and migration."""

from __future__ import annotations

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, Mock

import pytest

from app.db.bulk_ingestor import BulkIngestor
from app.db.queries import (
    ALTER_PRODUCTS_ADD_RETENTION,
    ALTER_PROFILES_ADD_RETENTION,
    DELETE_EXPIRED_PRODUCTS,
    DELETE_EXPIRED_PROFILES,
    SET_DEFAULT_RETENTION_PRODUCTS,
    SET_DEFAULT_RETENTION_PROFILES,
)
from app.db.supabase_client import DatabaseClient


def _make_ingestor():
    """Create a BulkIngestor with a mocked DB pool."""
    mock_conn = AsyncMock()

    @asynccontextmanager
    async def mock_acquire():
        yield mock_conn

    mock_pool = Mock()
    mock_pool.acquire = mock_acquire

    mock_db = Mock(spec=DatabaseClient)
    mock_db.pool = mock_pool

    return BulkIngestor(mock_db), mock_conn


class TestCleanupExpiredData:
    """Tests for BulkIngestor.cleanup_expired_data()."""

    @pytest.mark.asyncio
    async def test_returns_correct_counts(self):
        """cleanup_expired_data returns deleted counts for both tables."""
        ingestor, mock_conn = _make_ingestor()
        mock_conn.execute = AsyncMock(
            side_effect=["DELETE 5", "DELETE 2"],
        )

        result = await ingestor.cleanup_expired_data()

        assert result == {"products_deleted": 5, "profiles_deleted": 2}
        mock_conn.execute.assert_any_await(DELETE_EXPIRED_PRODUCTS)
        mock_conn.execute.assert_any_await(DELETE_EXPIRED_PROFILES)

    @pytest.mark.asyncio
    async def test_returns_zero_when_nothing_expired(self):
        """cleanup_expired_data returns zeros when no records are expired."""
        ingestor, mock_conn = _make_ingestor()
        mock_conn.execute = AsyncMock(
            side_effect=["DELETE 0", "DELETE 0"],
        )

        result = await ingestor.cleanup_expired_data()

        assert result == {"products_deleted": 0, "profiles_deleted": 0}

    @pytest.mark.asyncio
    async def test_handles_empty_result(self):
        """cleanup_expired_data handles None/empty execute result."""
        ingestor, mock_conn = _make_ingestor()
        mock_conn.execute = AsyncMock(
            side_effect=["", ""],
        )

        result = await ingestor.cleanup_expired_data()

        assert result == {"products_deleted": 0, "profiles_deleted": 0}


class TestApplyRetentionMigration:
    """Tests for BulkIngestor.apply_retention_migration()."""

    @pytest.mark.asyncio
    async def test_adds_columns_and_sets_defaults(self):
        """apply_retention_migration runs all four SQL statements."""
        ingestor, mock_conn = _make_ingestor()
        mock_conn.execute = AsyncMock(return_value="UPDATE 100")

        await ingestor.apply_retention_migration(retention_days=365)

        assert mock_conn.execute.await_count == 4
        mock_conn.execute.assert_any_await(ALTER_PRODUCTS_ADD_RETENTION)
        mock_conn.execute.assert_any_await(ALTER_PROFILES_ADD_RETENTION)
        mock_conn.execute.assert_any_await(SET_DEFAULT_RETENTION_PRODUCTS, "365")
        mock_conn.execute.assert_any_await(SET_DEFAULT_RETENTION_PROFILES, "365")

    @pytest.mark.asyncio
    async def test_passes_custom_retention_days(self):
        """apply_retention_migration passes the retention_days value as string."""
        ingestor, mock_conn = _make_ingestor()
        mock_conn.execute = AsyncMock(return_value="UPDATE 0")

        await ingestor.apply_retention_migration(retention_days=90)

        mock_conn.execute.assert_any_await(SET_DEFAULT_RETENTION_PRODUCTS, "90")
        mock_conn.execute.assert_any_await(SET_DEFAULT_RETENTION_PROFILES, "90")


class TestRetentionDuringIngestion:
    """Tests that retention_expires_at is set during product ingestion."""

    @pytest.mark.asyncio
    async def test_retention_date_included_in_staging_data(self):
        """Ingestion includes retention_expires_at in staging columns."""
        from datetime import datetime, timezone
        from decimal import Decimal

        from app.models.enums import Platform
        from app.models.product import Product

        captured_columns = None
        captured_records = None

        async def capture_copy(_table_name, *, records, columns):
            nonlocal captured_columns, captured_records
            captured_columns = columns
            captured_records = records

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
        mock_conn.copy_records_to_table = AsyncMock(side_effect=capture_copy)

        @asynccontextmanager
        async def mock_transaction():
            yield None

        mock_conn.transaction = mock_transaction

        @asynccontextmanager
        async def mock_acquire():
            yield mock_conn

        mock_pool = Mock()
        mock_pool.acquire = mock_acquire

        mock_db = Mock(spec=DatabaseClient)
        mock_db.pool = mock_pool

        ingestor = BulkIngestor(mock_db)

        product = Product(
            external_id="prod1",
            shop_id="shop1",
            platform=Platform.SHOPIFY,
            title="Test",
            description="",
            price=Decimal("10.00"),
            currency="USD",
            image_url="https://example.com/img.jpg",
            product_url="https://example.com/product",
            in_stock=True,
            raw_data={},
        )

        await ingestor.ingest([product])

        # Verify retention_expires_at is in the columns list
        assert captured_columns is not None
        assert "retention_expires_at" in captured_columns

        # Verify the last element of each record tuple is a datetime
        assert captured_records is not None
        assert len(captured_records) == 1
        retention_value = captured_records[0][-1]
        assert isinstance(retention_value, datetime)
        assert retention_value.tzinfo is not None

        # Verify the retention date is roughly 365 days from now
        expected = datetime.now(timezone.utc)
        diff_days = (retention_value - expected).days
        assert 364 <= diff_days <= 366


class TestRetentionQueryConstants:
    """Tests that GDPR retention SQL query constants are valid."""

    def test_delete_expired_products_query(self):
        assert "DELETE FROM products" in DELETE_EXPIRED_PRODUCTS
        assert "retention_expires_at" in DELETE_EXPIRED_PRODUCTS
        assert "NOW()" in DELETE_EXPIRED_PRODUCTS

    def test_delete_expired_profiles_query(self):
        assert "DELETE FROM merchant_profiles" in DELETE_EXPIRED_PROFILES
        assert "retention_expires_at" in DELETE_EXPIRED_PROFILES
        assert "NOW()" in DELETE_EXPIRED_PROFILES

    def test_alter_products_add_retention(self):
        assert "ALTER TABLE products" in ALTER_PRODUCTS_ADD_RETENTION
        assert "retention_expires_at" in ALTER_PRODUCTS_ADD_RETENTION

    def test_alter_profiles_add_retention(self):
        assert "ALTER TABLE merchant_profiles" in ALTER_PROFILES_ADD_RETENTION
        assert "retention_expires_at" in ALTER_PROFILES_ADD_RETENTION

    def test_set_default_retention_products(self):
        assert "UPDATE products" in SET_DEFAULT_RETENTION_PRODUCTS
        assert "$1" in SET_DEFAULT_RETENTION_PRODUCTS

    def test_set_default_retention_profiles(self):
        assert "UPDATE merchant_profiles" in SET_DEFAULT_RETENTION_PROFILES
        assert "$1" in SET_DEFAULT_RETENTION_PROFILES
