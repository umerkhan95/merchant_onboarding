"""Unit tests for database layer (supabase_client, bulk_ingestor, queries)."""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, Mock, patch

import pytest

from app.db.bulk_ingestor import BulkIngestor
from app.db.queries import (
    COUNT_PRODUCTS_BY_SHOP,
    CREATE_PRODUCTS_TABLE,
    CREATE_STAGING_TABLE,
    SELECT_PRODUCT_BY_ID,
    SELECT_PRODUCTS_BY_SHOP,
    UPSERT_FROM_STAGING,
)
from app.db.supabase_client import DatabaseClient
from app.models.enums import Platform
from app.models.product import Product, Variant


class TestDatabaseClient:
    """Test suite for DatabaseClient."""

    @pytest.mark.asyncio
    async def test_connect_creates_pool(self):
        """Test that connect() creates asyncpg pool."""
        mock_pool = MagicMock()

        async def create_pool_async(*args, **kwargs):
            return mock_pool

        with patch("app.db.supabase_client.asyncpg.create_pool", side_effect=create_pool_async):
            client = DatabaseClient("postgresql://localhost/test")
            await client.connect()

            assert client._pool is mock_pool
            assert client.pool is mock_pool

    @pytest.mark.asyncio
    async def test_close_closes_pool(self):
        """Test that close() closes the pool gracefully."""
        mock_pool = AsyncMock()

        client = DatabaseClient("postgresql://localhost/test")
        client._pool = mock_pool

        await client.close()

        mock_pool.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_handles_no_pool(self):
        """Test that close() handles case when pool is None."""
        client = DatabaseClient("postgresql://localhost/test")
        client._pool = None

        # Should not raise
        await client.close()

    def test_pool_property_raises_when_not_connected(self):
        """Test that pool property raises RuntimeError if not connected."""
        client = DatabaseClient("postgresql://localhost/test")

        with pytest.raises(RuntimeError, match="Database not connected"):
            _ = client.pool

    @pytest.mark.asyncio
    async def test_connect_with_custom_pool_settings(self):
        """Test connection pool is created with correct settings."""
        mock_pool = MagicMock()
        captured_args = None
        captured_kwargs = None

        async def create_pool_async(*args, **kwargs):
            nonlocal captured_args, captured_kwargs
            captured_args = args
            captured_kwargs = kwargs
            return mock_pool

        with patch("app.db.supabase_client.asyncpg.create_pool", side_effect=create_pool_async):
            client = DatabaseClient("postgresql://localhost/test")
            await client.connect()

            assert captured_args == ("postgresql://localhost/test",)
            assert captured_kwargs == {
                "min_size": 2,
                "max_size": 10,
                "command_timeout": 60.0,
            }


class TestBulkIngestor:
    """Test suite for BulkIngestor."""

    def create_mock_product(
        self,
        external_id: str = "prod123",
        shop_id: str = "shop1",
        title: str = "Test Product",
    ) -> Product:
        """Create a mock Product instance for testing."""
        return Product(
            external_id=external_id,
            shop_id=shop_id,
            platform=Platform.SHOPIFY,
            title=title,
            description="Test description",
            price=Decimal("29.99"),
            compare_at_price=Decimal("39.99"),
            currency="USD",
            image_url="https://example.com/image.jpg",
            product_url="https://example.com/product",
            sku="SKU123",
            vendor="Test Vendor",
            product_type="Test Type",
            in_stock=True,
            variants=[
                Variant(
                    variant_id="var1",
                    title="Small",
                    price=Decimal("29.99"),
                    sku="SKU123-SM",
                    in_stock=True,
                )
            ],
            tags=["test", "product"],
            raw_data={"key": "value"},
        )

    @pytest.mark.asyncio
    async def test_ingest_empty_list(self):
        """Test that ingest handles empty product list."""
        mock_db = Mock(spec=DatabaseClient)
        ingestor = BulkIngestor(mock_db)

        result = await ingestor.ingest([])

        assert result == 0

    @pytest.mark.asyncio
    async def test_ingest_single_product(self):
        """Test ingesting a single product."""
        from contextlib import asynccontextmanager

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
        mock_conn.executemany = AsyncMock()

        @asynccontextmanager
        async def mock_transaction():
            yield None

        mock_conn.transaction = mock_transaction

        @asynccontextmanager
        async def mock_acquire():
            yield mock_conn

        mock_pool = MagicMock()
        mock_pool.acquire = mock_acquire

        mock_db = Mock(spec=DatabaseClient)
        mock_db.pool = mock_pool

        ingestor = BulkIngestor(mock_db)
        products = [self.create_mock_product()]

        result = await ingestor.ingest(products)

        assert result == 1
        mock_conn.execute.assert_any_await(CREATE_STAGING_TABLE)
        mock_conn.executemany.assert_awaited_once()
        mock_conn.execute.assert_any_await(UPSERT_FROM_STAGING)

    @pytest.mark.asyncio
    async def test_ingest_multiple_products(self):
        """Test ingesting multiple products."""
        from contextlib import asynccontextmanager

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 3")
        mock_conn.executemany = AsyncMock()

        @asynccontextmanager
        async def mock_transaction():
            yield None

        mock_conn.transaction = mock_transaction

        @asynccontextmanager
        async def mock_acquire():
            yield mock_conn

        mock_pool = MagicMock()
        mock_pool.acquire = mock_acquire

        mock_db = Mock(spec=DatabaseClient)
        mock_db.pool = mock_pool

        ingestor = BulkIngestor(mock_db)
        products = [
            self.create_mock_product(external_id="prod1", title="Product 1"),
            self.create_mock_product(external_id="prod2", title="Product 2"),
            self.create_mock_product(external_id="prod3", title="Product 3"),
        ]

        result = await ingestor.ingest(products)

        assert result == 3

    @pytest.mark.asyncio
    async def test_ingest_batching(self):
        """Test that large lists are processed in batches."""
        from contextlib import asynccontextmanager

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 500")
        mock_conn.executemany = AsyncMock()

        @asynccontextmanager
        async def mock_transaction():
            yield None

        mock_conn.transaction = mock_transaction

        @asynccontextmanager
        async def mock_acquire():
            yield mock_conn

        mock_pool = MagicMock()
        mock_pool.acquire = mock_acquire

        mock_db = Mock(spec=DatabaseClient)
        mock_db.pool = mock_pool

        ingestor = BulkIngestor(mock_db)
        # Create 750 products (should be 2 batches: 500 + 250)
        products = [
            self.create_mock_product(external_id=f"prod{i}", title=f"Product {i}")
            for i in range(750)
        ]

        result = await ingestor.ingest(products)

        # Should process 2 batches
        assert result == 1000  # 500 + 500 (mocked responses)
        assert mock_conn.execute.call_count >= 4  # At least 2 * (CREATE_STAGING + UPSERT)

    @pytest.mark.asyncio
    async def test_ingest_handles_error(self):
        """Test that ingest raises RuntimeError on database error."""
        from contextlib import asynccontextmanager

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(side_effect=Exception("Database error"))

        @asynccontextmanager
        async def mock_transaction():
            yield None

        mock_conn.transaction = mock_transaction

        @asynccontextmanager
        async def mock_acquire():
            yield mock_conn

        mock_pool = MagicMock()
        mock_pool.acquire = mock_acquire

        mock_db = Mock(spec=DatabaseClient)
        mock_db.pool = mock_pool

        ingestor = BulkIngestor(mock_db)
        products = [self.create_mock_product()]

        with pytest.raises(RuntimeError, match="Failed to ingest product batch"):
            await ingestor.ingest(products)

    @pytest.mark.asyncio
    async def test_ingest_batch_data_format(self):
        """Test that product data is correctly formatted for database insert."""
        from contextlib import asynccontextmanager

        captured_data = None

        async def capture_executemany(query, data):
            nonlocal captured_data
            captured_data = data

        mock_conn = AsyncMock()
        mock_conn.execute = AsyncMock(return_value="INSERT 0 1")
        mock_conn.executemany = AsyncMock(side_effect=capture_executemany)

        @asynccontextmanager
        async def mock_transaction():
            yield None

        mock_conn.transaction = mock_transaction

        @asynccontextmanager
        async def mock_acquire():
            yield mock_conn

        mock_pool = MagicMock()
        mock_pool.acquire = mock_acquire

        mock_db = Mock(spec=DatabaseClient)
        mock_db.pool = mock_pool

        ingestor = BulkIngestor(mock_db)
        product = self.create_mock_product(
            external_id="prod123",
            shop_id="shop1",
            title="Test Product",
        )
        products = [product]

        await ingestor.ingest(products)

        # Verify captured data structure
        assert captured_data is not None
        assert len(captured_data) == 1
        row = captured_data[0]

        # Verify key fields
        assert row[0] == "prod123"  # external_id
        assert row[1] == "shop1"  # shop_id
        assert row[2] == "shopify"  # platform
        assert row[3] == "Test Product"  # title
        assert row[5] == Decimal("29.99")  # price
        assert row[7] == "USD"  # currency


class TestSQLQueries:
    """Test that SQL query constants are valid strings."""

    def test_create_products_table_exists(self):
        """Test CREATE_PRODUCTS_TABLE is a non-empty string."""
        assert isinstance(CREATE_PRODUCTS_TABLE, str)
        assert len(CREATE_PRODUCTS_TABLE) > 0
        assert "CREATE TABLE IF NOT EXISTS products" in CREATE_PRODUCTS_TABLE
        assert "idempotency_key TEXT NOT NULL" in CREATE_PRODUCTS_TABLE
        assert "UNIQUE(idempotency_key)" in CREATE_PRODUCTS_TABLE

    def test_create_staging_table_exists(self):
        """Test CREATE_STAGING_TABLE is a non-empty string."""
        assert isinstance(CREATE_STAGING_TABLE, str)
        assert len(CREATE_STAGING_TABLE) > 0
        assert "CREATE TEMP TABLE" in CREATE_STAGING_TABLE
        assert "staging_products" in CREATE_STAGING_TABLE

    def test_upsert_from_staging_exists(self):
        """Test UPSERT_FROM_STAGING is a non-empty string."""
        assert isinstance(UPSERT_FROM_STAGING, str)
        assert len(UPSERT_FROM_STAGING) > 0
        assert "INSERT INTO products" in UPSERT_FROM_STAGING
        assert "FROM staging_products" in UPSERT_FROM_STAGING
        assert "ON CONFLICT (idempotency_key)" in UPSERT_FROM_STAGING
        assert "DO UPDATE SET" in UPSERT_FROM_STAGING

    def test_select_products_by_shop_exists(self):
        """Test SELECT_PRODUCTS_BY_SHOP is a non-empty string."""
        assert isinstance(SELECT_PRODUCTS_BY_SHOP, str)
        assert len(SELECT_PRODUCTS_BY_SHOP) > 0
        assert "SELECT * FROM products" in SELECT_PRODUCTS_BY_SHOP
        assert "WHERE shop_id = $1" in SELECT_PRODUCTS_BY_SHOP
        assert "LIMIT $2 OFFSET $3" in SELECT_PRODUCTS_BY_SHOP

    def test_count_products_by_shop_exists(self):
        """Test COUNT_PRODUCTS_BY_SHOP is a non-empty string."""
        assert isinstance(COUNT_PRODUCTS_BY_SHOP, str)
        assert len(COUNT_PRODUCTS_BY_SHOP) > 0
        assert "SELECT COUNT(*) FROM products" in COUNT_PRODUCTS_BY_SHOP
        assert "WHERE shop_id = $1" in COUNT_PRODUCTS_BY_SHOP

    def test_select_product_by_id_exists(self):
        """Test SELECT_PRODUCT_BY_ID is a non-empty string."""
        assert isinstance(SELECT_PRODUCT_BY_ID, str)
        assert len(SELECT_PRODUCT_BY_ID) > 0
        assert "SELECT * FROM products" in SELECT_PRODUCT_BY_ID
        assert "WHERE id = $1" in SELECT_PRODUCT_BY_ID

    def test_queries_use_parameterized_syntax(self):
        """Test that queries use PostgreSQL parameterized syntax."""
        # Verify SELECT queries use $1, $2, etc.
        assert "$1" in SELECT_PRODUCTS_BY_SHOP
        assert "$2" in SELECT_PRODUCTS_BY_SHOP
        assert "$3" in SELECT_PRODUCTS_BY_SHOP
        assert "$1" in COUNT_PRODUCTS_BY_SHOP
        assert "$1" in SELECT_PRODUCT_BY_ID

    def test_create_table_has_indexes(self):
        """Test that CREATE_PRODUCTS_TABLE includes necessary indexes."""
        assert "CREATE INDEX IF NOT EXISTS idx_products_shop_id" in CREATE_PRODUCTS_TABLE
        assert "CREATE INDEX IF NOT EXISTS idx_products_platform" in CREATE_PRODUCTS_TABLE
        assert "CREATE INDEX IF NOT EXISTS idx_products_idempotency" in CREATE_PRODUCTS_TABLE
