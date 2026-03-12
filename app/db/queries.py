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
    gtin TEXT,
    mpn TEXT,
    vendor TEXT,
    product_type TEXT,
    in_stock BOOLEAN DEFAULT TRUE,
    condition TEXT,
    variants JSONB DEFAULT '[]',
    tags JSONB DEFAULT '[]',
    additional_images JSONB DEFAULT '[]',
    category_path JSONB DEFAULT '[]',
    raw_data JSONB DEFAULT '{}',
    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    idempotency_key TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retention_expires_at TIMESTAMPTZ,
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
    currency, image_url, product_url, sku, gtin, mpn, vendor, product_type, in_stock,
    condition, variants, tags, additional_images, category_path,
    raw_data, scraped_at, idempotency_key, retention_expires_at
)
SELECT
    external_id, shop_id, platform, title, description, price, compare_at_price,
    currency, image_url, product_url, sku, gtin, mpn, vendor, product_type, in_stock,
    condition, variants, tags, additional_images, category_path,
    raw_data, scraped_at, idempotency_key, retention_expires_at
FROM staging_products
ON CONFLICT (idempotency_key)
DO UPDATE SET
    title = EXCLUDED.title,
    description = EXCLUDED.description,
    price = EXCLUDED.price,
    compare_at_price = EXCLUDED.compare_at_price,
    image_url = EXCLUDED.image_url,
    product_url = EXCLUDED.product_url,
    sku = EXCLUDED.sku,
    gtin = EXCLUDED.gtin,
    mpn = EXCLUDED.mpn,
    vendor = EXCLUDED.vendor,
    product_type = EXCLUDED.product_type,
    currency = EXCLUDED.currency,
    in_stock = EXCLUDED.in_stock,
    condition = EXCLUDED.condition,
    variants = EXCLUDED.variants,
    tags = EXCLUDED.tags,
    additional_images = EXCLUDED.additional_images,
    category_path = EXCLUDED.category_path,
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

# Cleanup: remove invalid products (price=0, no image, no SKU, no external_id)
# Preserves legitimate free items that have images or SKUs.
DELETE_INVALID_PRODUCTS = """
DELETE FROM products
WHERE price = 0
  AND (image_url IS NULL OR image_url = '')
  AND (sku IS NULL OR sku = '')
  AND (external_id IS NULL OR external_id = '');
"""

# Count invalid products (for dry-run / preview)
COUNT_INVALID_PRODUCTS = """
SELECT COUNT(*) FROM products
WHERE price = 0
  AND (image_url IS NULL OR image_url = '')
  AND (sku IS NULL OR sku = '')
  AND (external_id IS NULL OR external_id = '');
"""

# --- Merchant Profiles ---

CREATE_MERCHANT_PROFILES_TABLE = """
CREATE TABLE IF NOT EXISTS merchant_profiles (
    id BIGSERIAL PRIMARY KEY,
    shop_id TEXT NOT NULL UNIQUE,
    platform TEXT NOT NULL,
    shop_url TEXT NOT NULL,

    -- Business identity
    company_name TEXT,
    logo_url TEXT,
    description TEXT,
    about_text TEXT,
    founding_year INTEGER,
    industry TEXT,
    language VARCHAR(10),
    currency VARCHAR(3),

    -- Contact (structured JSONB)
    contact JSONB DEFAULT '{}',

    -- Social links
    social_links JSONB DEFAULT '{}',

    -- Analytics/tracking tags
    analytics_tags JSONB DEFAULT '[]',

    -- Metadata
    favicon_url TEXT,
    pages_crawled JSONB DEFAULT '[]',
    extraction_confidence NUMERIC(3,2) DEFAULT 0.0,

    scraped_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    retention_expires_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_merchant_profiles_shop_id
    ON merchant_profiles(shop_id);
"""

UPSERT_MERCHANT_PROFILE = """
INSERT INTO merchant_profiles (
    shop_id, platform, shop_url, company_name, logo_url, description,
    about_text, founding_year, industry, language, currency,
    contact, social_links, analytics_tags,
    favicon_url, pages_crawled, extraction_confidence, scraped_at
) VALUES (
    $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11,
    $12, $13, $14, $15, $16, $17, $18
)
ON CONFLICT (shop_id) DO UPDATE SET
    platform = EXCLUDED.platform,
    shop_url = EXCLUDED.shop_url,
    company_name = EXCLUDED.company_name,
    logo_url = EXCLUDED.logo_url,
    description = EXCLUDED.description,
    about_text = EXCLUDED.about_text,
    founding_year = EXCLUDED.founding_year,
    industry = EXCLUDED.industry,
    language = EXCLUDED.language,
    currency = EXCLUDED.currency,
    contact = EXCLUDED.contact,
    social_links = EXCLUDED.social_links,
    analytics_tags = EXCLUDED.analytics_tags,
    favicon_url = EXCLUDED.favicon_url,
    pages_crawled = EXCLUDED.pages_crawled,
    extraction_confidence = EXCLUDED.extraction_confidence,
    scraped_at = EXCLUDED.scraped_at,
    updated_at = NOW();
"""

SELECT_MERCHANT_PROFILE = """
SELECT * FROM merchant_profiles WHERE shop_id = $1;
"""

SELECT_ALL_MERCHANT_PROFILES = """
SELECT * FROM merchant_profiles ORDER BY updated_at DESC;
"""

# GDPR: Delete all products for a merchant
DELETE_PRODUCTS_BY_SHOP = """
DELETE FROM products WHERE shop_id = $1;
"""

COUNT_PRODUCTS_BY_SHOP_FOR_DELETE = """
SELECT COUNT(*) FROM products WHERE shop_id = $1;
"""

# GDPR: Delete merchant profile
DELETE_MERCHANT_PROFILE = """
DELETE FROM merchant_profiles WHERE shop_id = $1;
"""

# GDPR: Data retention — add retention column
ALTER_PRODUCTS_ADD_RETENTION = """
ALTER TABLE products ADD COLUMN IF NOT EXISTS retention_expires_at TIMESTAMPTZ;
"""

ALTER_PROFILES_ADD_RETENTION = """
ALTER TABLE merchant_profiles ADD COLUMN IF NOT EXISTS retention_expires_at TIMESTAMPTZ;
"""

# GDPR: Delete expired records
DELETE_EXPIRED_PRODUCTS = """
DELETE FROM products
WHERE retention_expires_at IS NOT NULL
  AND retention_expires_at < NOW();
"""

DELETE_EXPIRED_PROFILES = """
DELETE FROM merchant_profiles
WHERE retention_expires_at IS NOT NULL
  AND retention_expires_at < NOW();
"""

COUNT_EXPIRED_PRODUCTS = """
SELECT COUNT(*) FROM products
WHERE retention_expires_at IS NOT NULL
  AND retention_expires_at < NOW();
"""

COUNT_EXPIRED_PROFILES = """
SELECT COUNT(*) FROM merchant_profiles
WHERE retention_expires_at IS NOT NULL
  AND retention_expires_at < NOW();
"""

# Set retention on existing records that don't have one
SET_DEFAULT_RETENTION_PRODUCTS = """
UPDATE products
SET retention_expires_at = created_at + ($1 || ' days')::INTERVAL
WHERE retention_expires_at IS NULL;
"""

SET_DEFAULT_RETENTION_PROFILES = """
UPDATE merchant_profiles
SET retention_expires_at = created_at + ($1 || ' days')::INTERVAL
WHERE retention_expires_at IS NULL;
"""

# Migration: add idealo-required columns to existing products table
ALTER_PRODUCTS_ADD_IDEALO_FIELDS = """
ALTER TABLE products ADD COLUMN IF NOT EXISTS gtin TEXT;
ALTER TABLE products ADD COLUMN IF NOT EXISTS mpn TEXT;
ALTER TABLE products ADD COLUMN IF NOT EXISTS condition TEXT;
ALTER TABLE products ADD COLUMN IF NOT EXISTS additional_images JSONB DEFAULT '[]';
ALTER TABLE products ADD COLUMN IF NOT EXISTS category_path JSONB DEFAULT '[]';
"""
