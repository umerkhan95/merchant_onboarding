"""SQL queries for product database operations."""

from __future__ import annotations

# Schema creation
CREATE_PRODUCTS_TABLE = """
CREATE TABLE IF NOT EXISTS products (
    id BIGSERIAL PRIMARY KEY,
    external_id TEXT NOT NULL,
    shop_id TEXT NOT NULL,
    platform TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    price NUMERIC(12,2) NOT NULL,
    compare_at_price NUMERIC(12,2),
    currency VARCHAR(3) NOT NULL DEFAULT 'USD',
    image_url TEXT DEFAULT '',
    product_url TEXT DEFAULT '',
    sku TEXT,
    vendor TEXT,
    product_type TEXT,
    in_stock BOOLEAN DEFAULT TRUE,
    variants JSONB DEFAULT '[]',
    tags JSONB DEFAULT '[]',
    raw_data JSONB DEFAULT '{}',
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    idempotency_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE(idempotency_key)
);
CREATE INDEX IF NOT EXISTS idx_products_shop_id ON products(shop_id);
CREATE INDEX IF NOT EXISTS idx_products_platform ON products(platform);
CREATE INDEX IF NOT EXISTS idx_products_idempotency ON products(idempotency_key);
"""

# Staging table for bulk operations (INCLUDING DEFAULTS only — no constraints/indexes
# so COPY can load data without ON CONFLICT overhead; dedup handled by final upsert)
CREATE_STAGING_TABLE = """
CREATE TEMP TABLE IF NOT EXISTS staging_products (LIKE products INCLUDING DEFAULTS) ON COMMIT DROP;
"""

# Bulk upsert from staging
UPSERT_FROM_STAGING = """
INSERT INTO products (
    external_id, shop_id, platform, title, description, price, compare_at_price,
    currency, image_url, product_url, sku, vendor, product_type, in_stock,
    variants, tags, raw_data, scraped_at, idempotency_key
)
SELECT
    external_id, shop_id, platform, title, description, price, compare_at_price,
    currency, image_url, product_url, sku, vendor, product_type, in_stock,
    variants, tags, raw_data, scraped_at, idempotency_key
FROM staging_products
ON CONFLICT (idempotency_key)
DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    price = EXCLUDED.price,
    compare_at_price = EXCLUDED.compare_at_price,
    image_url = EXCLUDED.image_url,
    product_url = EXCLUDED.product_url,
    in_stock = EXCLUDED.in_stock,
    variants = EXCLUDED.variants,
    tags = EXCLUDED.tags,
    raw_data = EXCLUDED.raw_data,
    scraped_at = EXCLUDED.scraped_at,
    updated_at = NOW();
"""

# Read operations
SELECT_PRODUCTS_BY_SHOP = """
SELECT * FROM products WHERE shop_id = $1 ORDER BY created_at DESC LIMIT $2 OFFSET $3;
"""

SELECT_PRODUCTS_BY_DOMAIN = """
SELECT * FROM products
WHERE shop_id LIKE '%' || $1 || '%'
ORDER BY created_at DESC LIMIT $2 OFFSET $3;
"""

COUNT_PRODUCTS_BY_SHOP = """
SELECT COUNT(*) FROM products WHERE shop_id = $1;
"""

COUNT_PRODUCTS_BY_DOMAIN = """
SELECT COUNT(*) FROM products WHERE shop_id LIKE '%' || $1 || '%';
"""

SELECT_PRODUCT_BY_ID = """
SELECT * FROM products WHERE id = $1;
"""

COUNT_ALL_PRODUCTS = """
SELECT COUNT(*) FROM products;
"""
